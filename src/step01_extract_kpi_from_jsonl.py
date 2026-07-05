#!/usr/bin/env python3
"""
Extract ESG KPIs from the sentence-level labeled JSONL, mimicking
EmeraldMind/src/EmeraldKG/1-kpi-extraction.py but:

  * input is the labeled JSONL (already-extracted sentences), not PDFs
  * KPI schema is the single-sector construction definitions
  * model is Gemini 2.5 Flash via the official google-genai SDK
  * page text is reconstructed by grouping sentences per (source_pdf, page)
  * only pages containing >= 1 esg=true sentence are sent to the LLM
    (the full page text is still used as input); other pages get an empty file

Output mirrors step 1: one JSON file per page, each holding a list of KPI objects.
Reads the project-global .env at the repo root (GEMINI_API_KEY).
"""

import os
import re
import json
import argparse
import collections
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Tuple
from logging import getLogger, basicConfig, INFO, WARNING

from dotenv import load_dotenv
from google import genai
from google.genai import types

basicConfig(level=INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = getLogger(__name__)
getLogger("google_genai.models").setLevel(WARNING)

# Repo root = parent of this script's folder (src/ -> capstone_test1/)
REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = REPO_ROOT / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"
DEFAULT_KPI_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_OUT_DIR = REPO_ROOT / "kpi_output"
DEFAULT_MODEL = "gemini-2.5-flash"

# The construction KPI file is single-sector; sector detection is unnecessary.
SECTOR = "Xây dựng - Vật liệu xây dựng - Bất động sản"


# --------------------------------------------------------------------------- #
# Helpers carried over / adapted from 1-kpi-extraction.py
# --------------------------------------------------------------------------- #
def parse_company_year_from_filename(pdf_filename: str) -> Tuple[str, str]:
    """Extract company name and year from a source_pdf filename (same logic as step 1)."""
    basename = os.path.splitext(pdf_filename)[0]

    year_match = re.search(r"(\d{4})$", basename)
    if year_match:
        year = year_match.group(1)
        company_part = basename[: year_match.start()].rstrip("_-")
        company = re.sub(r"[_\-\s]+$", "", company_part)
        return company, year

    parts = basename.split("_")
    if len(parts) >= 2:
        for i in range(len(parts) - 1, -1, -1):
            if re.match(r"^\d{4}$", parts[i]):
                year = parts[i]
                company = "_".join(parts[:i])
                return company, year

    logger.warning(f"Could not parse company and year from filename: {pdf_filename}")
    return os.path.splitext(pdf_filename)[0], "unknown"


def normalize_kpi_response(data: List[Dict]) -> List[Dict]:
    """Strip trailing % into unit and cast year-like fields to int (verbatim from step 1)."""
    for item in data:
        for obs in item.get("observations", []):
            val = obs.get("value")
            if isinstance(val, str):
                if val.endswith("%"):
                    obs["unit"] = obs.get("unit") or "%"
                    val = val.rstrip("%")
                try:
                    obs["value"] = float(val)
                except ValueError:
                    pass

            for key in ("year", "baseline_year", "target_year"):
                yr = obs.get(key)
                if isinstance(yr, str) and yr.isdigit():
                    obs[key] = int(yr)
    return data


# --------------------------------------------------------------------------- #
# JSONL loading / page reconstruction
# --------------------------------------------------------------------------- #
def load_pages_from_jsonl(path: Path) -> "collections.OrderedDict":
    """
    Group rows into { source_pdf: { page: [ (sentence_index, text, esg), ... ] } },
    preserving first-seen document order.
    """
    docs: "collections.OrderedDict[str, Dict[int, List[Tuple[int, str, bool]]]]" = collections.OrderedDict()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            src = row.get("source_pdf", "unknown.pdf")
            page = int(row.get("page", 0))
            sidx = int(row.get("sentence_index", 0))
            text = row.get("text", "") or ""
            esg = bool(row.get("esg", False))
            docs.setdefault(src, {}).setdefault(page, []).append((sidx, text, esg))
    return docs


def build_page_text(rows: List[Tuple[int, str, bool]]) -> str:
    """Join all sentences on a page, ordered by sentence_index."""
    ordered = sorted(rows, key=lambda r: r[0])
    return " ".join(t.strip() for _, t, _ in ordered if t.strip())


def page_has_esg(rows: List[Tuple[int, str, bool]]) -> bool:
    return any(esg for _, _, esg in rows)


# --------------------------------------------------------------------------- #
# KPI JSON schema for structured outputs (Gemini OpenAPI-3 dialect:
# nullable fields use "nullable": True; no additionalProperties).
# --------------------------------------------------------------------------- #
_OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "number", "nullable": True},
        "unit": {"type": "string", "nullable": True},
        "kind": {"type": "string", "enum": ["baseline", "target", "achieved", "projection"]},
        "direction": {"type": "string", "enum": ["absolute", "reduction", "increase"]},
        "year": {"type": "integer", "nullable": True},
        "target_year": {"type": "integer", "nullable": True},
        "baseline_year": {"type": "integer", "nullable": True},
        "source_id": {"type": "string"},
        "snippet": {"type": "string"},
    },
    "required": [
        "value", "unit", "kind", "direction", "year",
        "target_year", "baseline_year", "source_id", "snippet",
    ],
}

_KPI_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "kpi_type": {"type": "string"},
        "title": {"type": "string"},
        "observations": {"type": "array", "items": _OBSERVATION_SCHEMA},
        "page": {"type": "integer"},
        "doc_name": {"type": "string"},
        "company": {"type": "string"},
        "sector": {"type": "string"},
    },
    "required": ["kpi_type", "title", "observations", "page", "doc_name", "company", "sector"],
}

KPI_SCHEMA = {
    "type": "object",
    "properties": {"kpis": {"type": "array", "items": _KPI_ITEM_SCHEMA}},
    "required": ["kpis"],
}


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #
class KPIExtractor:
    def __init__(self, kpi_defs_path: Path, model: str = DEFAULT_MODEL, max_tokens: int = 8000):
        # Load the project-global .env at the repo root regardless of cwd.
        load_dotenv(REPO_ROOT / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"GEMINI_API_KEY not set. Copy {REPO_ROOT / '.env.example'} to "
                f"{REPO_ROOT / '.env'} and paste your key."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

        with open(kpi_defs_path, "r", encoding="utf-8") as f:
            self.kpi_defs = json.load(f)

        logger.info(
            f"KPIExtractor ready: model={model}, {len(self.kpi_defs)} KPI definitions, sector='{SECTOR}'"
        )

    def _build_prompt(self, page_text: str, company: str, sector: str,
                      page_num: int, doc_name: str) -> Tuple[str, str]:
        defs = "\n".join(f"{d['id']}: {d.get('definition', '')}" for d in self.kpi_defs)

        system = (
            "You are ESG-KPI-EXTRACTOR-V2. Produce only JSON conforming exactly to the schema. "
            "If no KPI can be unambiguously extracted, return an empty list. The text is in Vietnamese.\n\n"
            f"For each extracted KPI, set:\n"
            f"- company: \"{company}\"\n"
            f"- sector: \"{sector}\"\n"
            f"- page: {page_num}\n"
            f"- doc_name: \"{doc_name}\"\n\n"
            "Classification rules:\n"
            "- baseline   : historic reference (keywords: kể từ / năm gốc / baseline / since)\n"
            "- target     : ambition or commitment (keywords: mục tiêu / cam kết / hướng tới / goal / target)\n"
            "- achieved   : result already met (keywords: đạt được / đã giảm / đã thực hiện / achieved)\n"
            "- projection : future estimate not yet committed\n\n"
            "If a sentence contains several numbers for the same KPI, create separate observation objects.\n"
            "If a metric does not fully match any KPI definition, set kpi_type to \"other\" and use a "
            "descriptive title.\n"
            "Set source_id to \"{doc}_{page}_{index}\" using the doc name, page number, and an ascending index.\n"
            "snippet must be <= 160 characters, quoting the source text."
        )

        user = (
            f"KPI_DEFINITIONS (subset):\n{defs}\n\n"
            f"TEXT SOURCE (page {page_num} of {doc_name}):\n"
            f"\"\"\"{page_text}\"\"\""
        )
        return system, user

    def extract_page(self, page_text: str, company: str, sector: str,
                     page_num: int, doc_name: str) -> List[Dict[str, Any]]:
        system, user = self._build_prompt(page_text, company, sector, page_num, doc_name)

        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=KPI_SCHEMA,
                max_output_tokens=self.max_tokens,
                temperature=0,
            ),
        )

        # Gemini surfaces safety blocks / non-STOP terminations via finish_reason.
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            finish = getattr(candidates[0], "finish_reason", None)
            finish_name = getattr(finish, "name", str(finish)) if finish is not None else ""
            if finish_name and finish_name not in ("STOP", "MAX_TOKENS"):
                logger.warning(
                    f"Non-STOP finish_reason={finish_name} on page {page_num} of {doc_name}; returning []."
                )
                return []

        text = (resp.text or "").strip()
        if not text:
            return []
        kpis = json.loads(text).get("kpis", [])
        return normalize_kpi_response(kpis)

    def process_document(self, source_pdf: str, pages: Dict[int, List[Tuple[int, str, bool]]],
                         out_dir: Path, esg_only: bool, max_workers: int) -> int:
        pdf_stem = os.path.splitext(source_pdf)[0]
        company, year = parse_company_year_from_filename(source_pdf)
        out_subdir = out_dir / f"{pdf_stem}_kpis"
        out_subdir.mkdir(parents=True, exist_ok=True)

        logger.info(f"=== {source_pdf} (company={company}, year={year}) — {len(pages)} pages ===")

        def _process_one(page_num: int) -> Tuple[int, List[Dict[str, Any]], bool]:
            rows = pages[page_num]
            out_file = out_subdir / f"page_{page_num:03d}_kpis.json"

            if out_file.exists():
                logger.info(f"Skipping page {page_num} (output exists)")
                return page_num, json.loads(out_file.read_text(encoding="utf-8")), True

            page_text = build_page_text(rows)
            if not page_text:
                return page_num, [], True
            if esg_only and not page_has_esg(rows):
                logger.info(f"Page {page_num}: no ESG sentence — writing empty []")
                return page_num, [], True

            try:
                results = self.extract_page(page_text, company, SECTOR, page_num, source_pdf)
                return page_num, results, True
            except Exception as e:
                logger.exception(f"Error on page {page_num}: {e}")
                return page_num, [], False

        total_kpis = 0
        failed = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(_process_one, p): p for p in sorted(pages.keys())}
            for fut in concurrent.futures.as_completed(futures):
                page_num, results, ok = fut.result()
                if not ok:
                    failed.append(page_num)
                    continue
                out_file = out_subdir / f"page_{page_num:03d}_kpis.json"
                out_file.write_text(
                    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                if results:
                    total_kpis += len(results)
                    logger.info(f"Page {page_num}: extracted {len(results)} KPI(s)")

        if failed:
            logger.warning(f"{len(failed)} page(s) failed and were skipped: {sorted(failed)}")
        logger.info(f"Total KPIs for {source_pdf}: {total_kpis}")
        return total_kpis


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def select_documents(docs: "collections.OrderedDict", args) -> List[str]:
    names = list(docs.keys())
    if args.doc:
        matched = [n for n in names if args.doc in n]
        if not matched:
            logger.error(f"No source_pdf matches --doc '{args.doc}'. Available: {names}")
        return matched
    if args.all:
        return names
    if args.limit_docs:
        return names[: args.limit_docs]
    # Default: cheap first run — just the first document.
    logger.info("No scope flag given; defaulting to the first document. Use --all / --limit-docs / --doc.")
    return names[:1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract ESG KPIs from labeled JSONL using Claude Haiku")
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT, help="Labeled JSONL path")
    parser.add_argument("-k", "--kpi-defs", type=Path, default=DEFAULT_KPI_DEFS, help="KPI definitions JSON")
    parser.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--doc", type=str, help="Process only source_pdf names containing this substring")
    parser.add_argument("--limit-docs", type=int, help="Process only the first N documents")
    parser.add_argument("--all", action="store_true", help="Process all documents")
    parser.add_argument("--all-pages", action="store_true",
                        help="Run every non-empty page (default: only pages with >=1 ESG sentence)")
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel page workers (default 4)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model id")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input JSONL not found: {args.input}")
        return
    if not args.kpi_defs.exists():
        logger.error(f"KPI definitions not found: {args.kpi_defs}")
        return

    docs = load_pages_from_jsonl(args.input)
    selected = select_documents(docs, args)
    if not selected:
        return

    extractor = KPIExtractor(args.kpi_defs, model=args.model)
    esg_only = not args.all_pages

    grand_total = 0
    for src in selected:
        grand_total += extractor.process_document(
            src, docs[src], args.out_dir, esg_only=esg_only, max_workers=args.max_workers
        )
    logger.info(f"Done. Extracted {grand_total} KPI(s) across {len(selected)} document(s) -> {args.out_dir}")


if __name__ == "__main__":
    main()
