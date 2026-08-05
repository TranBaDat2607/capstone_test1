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

Run from the repo root:
  python src/run.py extract --doc AAA_2023
Equivalently, from inside src/:  python -m esg_kg.kpi.extract --doc AAA_2023

Moved verbatim from src/step01_extract_kpi_from_jsonl.py (Model A: that file still exists
and still runs). Only the docstring and the import block differ: `REPO_ROOT` now comes from
`esg_kg.core.paths`, and the 5 JSONL-reconstruction helpers (`load_pages_from_jsonl`,
`build_page_text`, `page_has_esg`, `select_documents`, `parse_company_year_from_filename`)
now come from `esg_kg.core.io_jsonl` instead of being defined here — that module is what
lets `step02` stop reaching into this file once IT migrates (PIPELINE.md §2.1). There is no
`_Provider` involved: this stage talks to Gemini directly via `google.genai.Client`.
`KPIExtractor`, its prompt, its JSON schema, and `normalize_kpi_response` all stay stage-local:
nothing else in the pipeline imports them.

2026-08-04: the additive `--provider openai` path (added 2026-07-29 while the Gemini
project behind GEMINI_API_KEY was billing-blocked) was removed outright — this project now
pays only for Gemini, so this stage is gemini-only again, no fallback.

test/test_esg_kg_extract.py compares the two trees on the real corpus (the pure helpers) and
on a stubbed Gemini client (the paid path) to keep it that way.
"""

import os
import json
import argparse
import collections
import concurrent.futures
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from logging import getLogger, basicConfig, INFO, WARNING

from dotenv import load_dotenv
from google.genai import types

from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.llm import DEFAULT_MODEL, GeminiContextCache, build_gemini_client
from esg_kg.core.io_jsonl import (
    build_page_text,
    load_pages_from_jsonl,
    page_has_esg,
    parse_company_year_from_filename,
    select_documents,
)
basicConfig(level=INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = getLogger(__name__)
getLogger("google_genai.models").setLevel(WARNING)

DEFAULT_INPUT = REPO_ROOT / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"
DEFAULT_KPI_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_OUT_DIR = REPO_ROOT / "kpi_output"
# DEFAULT_MODEL comes from esg_kg.core.llm (GEMINI_MODEL env var, default
# gemini-2.5-flash-lite) — see that module's docstring. Re-exported here so
# `extract.DEFAULT_MODEL` keeps working for existing call sites.

# The construction KPI file is single-sector; sector detection is unnecessary.
SECTOR = "Xây dựng - Vật liệu xây dựng - Bất động sản"


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
    def __init__(self, kpi_defs_path: Path, model: str = DEFAULT_MODEL, max_tokens: int = 8000,
                use_context_cache: bool = True):
        # Load the project-global .env at the repo root regardless of cwd.
        load_dotenv(REPO_ROOT / ".env")
        self.max_tokens = max_tokens

        client = build_gemini_client()
        if client is None:
            raise RuntimeError(
                f"GEMINI_API_KEY not set. Copy {REPO_ROOT / '.env.example'} to "
                f"{REPO_ROOT / '.env'} and paste your key."
            )
        self.client = client
        self.model = model

        with open(kpi_defs_path, "r", encoding="utf-8") as f:
            self.kpi_defs = json.load(f)
        self.defs_text = "\n".join(f"{d['id']}: {d.get('definition', '')}" for d in self.kpi_defs)

        # issue #11: KPI_DEFINITIONS never changes across the whole run (loaded once,
        # above), so this is the widest-scope cache of the three stages — one
        # client.caches.create() here serves every page of every document this
        # extractor processes, not just one document.
        #
        # That width is also the risk: the cache's TTL (core/llm.py, default 3600s)
        # is fixed for the process's lifetime, but a full-sector --all run over the
        # current corpus (873k sentences across ~197 companies) can easily run past
        # an hour. Without self-healing, every page after expiry would 400 on
        # cached_content and be silently lost (extract_page has no try/except of its
        # own; the caller marks the page failed and moves on, so a second full
        # invocation would be needed to pick the rest up). `self._ctx_cache` /
        # `self._cache_static_content` are kept so `_recreate_cache` can force a
        # fresh `caches.create()` — see there and `extract_page`.
        self.cache_name = None
        self._ctx_cache: Optional[GeminiContextCache] = None
        self._cache_static_content: Optional[str] = None
        self._cache_lock = threading.Lock()
        if use_context_cache:
            self._ctx_cache = GeminiContextCache(client, model)
            self._cache_static_content = f"KPI_DEFINITIONS (subset):\n{self.defs_text}"
            self.cache_name = self._ctx_cache.get_or_create(self._cache_static_content)

        logger.info(
            f"KPIExtractor ready: model={self.model}, "
            f"{len(self.kpi_defs)} KPI definitions, sector='{SECTOR}', "
            f"context_cache={'on' if self.cache_name else 'off'}"
        )

    def _build_prompt(self, page_text: str, company: str, sector: str,
                      page_num: int, doc_name: str) -> Tuple[str, str]:
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
            "snippet must be <= 160 characters, quoting the source text.\n\n"
            "## OUTPUT LANGUAGE (title / snippet / other free text)\n"
            "------------------\n"
            "Write `title`, `snippet`, and any other free-text property VALUE in VIETNAMESE, with full "
            "diacritics, exactly matching the source text. Do NOT translate into English. Do NOT strip "
            "diacritics (khong duoc bo dau).\n"
            "This rule does NOT apply to: kpi_type (a fixed code from the controlled KPI vocabulary), "
            "unit, value, year/target_year/baseline_year, source_id, company/sector/doc_name (copied "
            "verbatim as given above)."
        )

        # issue #11: when self.cache_name is set, KPI_DEFINITIONS lives in the cache
        # instead of being resent every page — only the page-specific TEXT SOURCE is sent.
        if self.cache_name is not None:
            user = f"TEXT SOURCE (page {page_num} of {doc_name}):\n\"\"\"{page_text}\"\"\""
        else:
            user = (
                f"KPI_DEFINITIONS (subset):\n{self.defs_text}\n\n"
                f"TEXT SOURCE (page {page_num} of {doc_name}):\n"
                f"\"\"\"{page_text}\"\"\""
            )
        return system, user

    def _recreate_cache(self) -> Optional[str]:
        """Force a fresh `client.caches.create()` for the KPI_DEFINITIONS block,
        bypassing `GeminiContextCache`'s in-process memoization (which would
        otherwise keep handing back the same now-expired name forever). Called from
        `extract_page` when a cached generate_content call fails in a way that looks
        like an expired/unknown cache. If recreation itself fails, `get_or_create`
        already falls back to `None` — the next call then goes uncached rather than
        losing the page, same as a cache that failed to create in the first place."""
        if self._ctx_cache is None or self._cache_static_content is None:
            return self.cache_name
        with self._cache_lock:
            self._ctx_cache.invalidate(self._cache_static_content)
            self.cache_name = self._ctx_cache.get_or_create(self._cache_static_content)
        return self.cache_name

    def _build_call(self, system: str, user: str) -> Tuple[Any, "types.GenerateContentConfig"]:
        # issue #11 follow-up (2026-08-05): the Gemini API rejects cached_content
        # combined with system_instruction in the SAME call ("CachedContent can not
        # be used with GenerateContent request setting system_instruction, tools or
        # tool_config"). Unlike extract_triples's constant system instruction, this
        # one embeds per-page facts (company/page/doc_name) and can't be baked into
        # the cache — so when cached, it travels as a regular content turn instead.
        if self.cache_name is not None:
            contents = f"{system}\n\n{user}"
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=KPI_SCHEMA,
                max_output_tokens=self.max_tokens,
                temperature=0,
                cached_content=self.cache_name,
            )
        else:
            contents = user
            config = types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=KPI_SCHEMA,
                max_output_tokens=self.max_tokens,
                temperature=0,
            )
        return contents, config

    def extract_page(self, page_text: str, company: str, sector: str,
                     page_num: int, doc_name: str) -> List[Dict[str, Any]]:
        system, user = self._build_prompt(page_text, company, sector, page_num, doc_name)
        contents, config = self._build_call(system, user)

        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            # A cached run's TTL (core/llm.py, default 3600s) can lapse mid-run on a
            # long --all extraction — the symptom is generate_content rejecting the
            # cached_content we sent. Recreate the cache once and retry this same
            # page instead of losing it (the caller has no retry of its own — see
            # __init__'s comment). Any other failure re-raises unchanged so it's
            # handled the same way it always was.
            msg = str(e).lower()
            cache_related = self.cache_name is not None and (
                "cachedcontent" in msg or "cached_content" in msg or "cached content" in msg
            )
            if not cache_related:
                raise
            logger.warning(
                f"[gemini cache] cached_content rejected on page {page_num} of {doc_name} "
                f"(likely expired past its TTL mid-run) — recreating once and retrying: {e}"
            )
            self._recreate_cache()
            contents, config = self._build_call(system, user)
            resp = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
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
    parser.add_argument("--no-context-cache", action="store_true",
                        help="Disable Gemini explicit context caching (issue #11) for "
                             "KPI_DEFINITIONS. On by default: one cache for the whole run, "
                             "reused across every page of every document.")
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

    extractor = KPIExtractor(args.kpi_defs, model=args.model,
                             use_context_cache=not args.no_context_cache)
    esg_only = not args.all_pages

    grand_total = 0
    for src in selected:
        grand_total += extractor.process_document(
            src, docs[src], args.out_dir, esg_only=esg_only, max_workers=args.max_workers
        )
    logger.info(f"Done. Extracted {grand_total} KPI(s) across {len(selected)} document(s) -> {args.out_dir}")


if __name__ == "__main__":
    main()
