#!/usr/bin/env python3
"""
Extract temporal ESG knowledge-graph triples from the page-level KPI JSONs
written by `extract_kpi_from_jsonl.py`, mirroring
EmeraldMind/src/EmeraldKG/2-extract-triplet.py but:

  * page text is reconstructed from the same labeled JSONL step 1 reads
    (via `build_page_text`), not from on-disk .txt side products.
  * per-page KPI JSONs come from kpi_output/<pdf_stem>_kpis/, written by step 1.
  * single GEMINI_API_KEY client + internal 10-RPM rate limiter
    (instead of EmeraldMind's pool of GEMINI_API_KEY_1..6).
  * triple-extraction prompt, JSON recovery, schema validation, and
    triple->graph conversion are kept identical to EmeraldMind's step 2.

Output:
  graph_output/graphs/<pdf_stem>/page{N}.json          valid temporal graph
  graph_output/graphs/<pdf_stem>/page{N}_bugged.json   schema-invalid triples
  graph_output/graphs/<pdf_stem>/page{N}_malformed.txt LLM responses that were not parseable JSON
  graph_output/debug_outputs_per_page/<pdf_stem>/<pdf_stem>_p{N}.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Reuse step-1 helpers. When run as `python src/extract_triplet_from_jsonl.py`
# Python puts src/ on sys.path automatically.
from extract_kpi_from_jsonl import (
    REPO_ROOT,
    build_page_text,
    load_pages_from_jsonl,
    page_has_esg,
    parse_company_year_from_filename,
    select_documents,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


DEFAULT_INPUT = REPO_ROOT / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_KPI_DIR = REPO_ROOT / "kpi_output"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_RATE_LIMIT = 10  # RPM
DEFAULT_MAX_WORKERS = 4


# --------------------------------------------------------------------------- #
# Rate limiter (verbatim port from 2-extract-triplet.py).
# Per-client RPM throttle. With a single API key we use client_idx=0.
# --------------------------------------------------------------------------- #
class RateLimiter:
    def __init__(self, max_calls_per_minute: int = DEFAULT_RATE_LIMIT):
        self.max_calls = max_calls_per_minute
        self.call_times: Dict[int, deque] = {}
        self.locks: Dict[int, Lock] = {}

    def wait_if_needed(self, client_idx: int) -> None:
        if client_idx not in self.call_times:
            self.call_times[client_idx] = deque()
            self.locks[client_idx] = Lock()

        with self.locks[client_idx]:
            now = time.time()
            calls = self.call_times[client_idx]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= self.max_calls:
                wait_time = 60 - (now - calls[0]) + 0.1
                if wait_time > 0:
                    logger.info(f"Rate limit: waiting {wait_time:.1f}s for client {client_idx}")
                    time.sleep(wait_time)
                    now = time.time()
                    while calls and now - calls[0] >= 60:
                        calls.popleft()
            calls.append(time.time())


# --------------------------------------------------------------------------- #
# Schema helpers (verbatim from 2-extract-triplet.py)
# --------------------------------------------------------------------------- #
def get_identity_keys(schema: Dict[str, Any]) -> Dict[str, List[str]]:
    return {n["class"]: n.get("identity_keys", ["name"]) for n in schema.get("nodes", [])}


def get_stable_entity_id(entity: Dict[str, Any], identity_keys_map: Dict[str, List[str]]) -> str:
    entity_class = entity.get("class", "Unknown")
    props = entity.get("properties", {})
    keys = identity_keys_map.get(entity_class, ["name"])
    parts = [entity_class]
    for k in keys:
        v = props.get(k, "")
        if isinstance(v, str):
            v = v.strip().lower()
        parts.append(str(v))
    return "|".join(parts)


def schema_sets(schema: Dict[str, Any]) -> Tuple[set, set]:
    classes = {n["class"] for n in schema["nodes"]}
    edges = {e["label"] for e in schema["edges"]}
    return classes, edges


# --------------------------------------------------------------------------- #
# Gemini config + prompt template (verbatim).
# --------------------------------------------------------------------------- #
CFG_JSON = types.GenerateContentConfig(
    temperature=0,
    response_mime_type="application/json",
    system_instruction="Return *only* valid JSON - no prose.",
)


TEMPORAL_GRAPH_PROMPT_TEMPLATE = (
    "You are an ESG temporal knowledge-graph extractor.\n\n"
    "## INPUTS\n"
    "* KNOWLEDGE GRAPH SCHEMA: list of entity classes, edge labels, and temporal properties (JSON).\n"
    "* documents: plain text from one ESG-related PDF page.\n"
    "* KPI records: optional JSON list for that page.\n\n"
    "## Task\n"
    "Extract **temporal** relations explicitly stated in the text.\n"
    "This is a TEMPORAL knowledge graph - you MUST include temporal properties for all nodes and edges.\n"
    "Obey the ontology below.\n\n"
    "------------------\n"
    "## KNOWLEDGE GRAPH SCHEMA\n"
    "------------------\n"
    "{schema_json}\n\n"
    "------------------\n"
    "## TEMPORAL EXTRACTION RULES\n"
    "------------------\n"
    "ALL nodes and edges MUST include temporal information:\n\n"
    "**For ALL Nodes:**\n"
    "* valid_from: The date when this information became valid (ISO format YYYY-MM-DD or YYYY)\n"
    "* valid_to: The date when this information was superseded (ISO format or null if current)\n"
    "* is_current: Boolean indicating if this is the current/latest version (true/false)\n\n"
    "**For ALL Edges (relationships):**\n"
    "Include these as additional properties in the temporal_metadata object:\n"
    "* valid_from: When this relationship started\n"
    "* valid_to: When this relationship ended (null if still active)\n"
    "* recorded_at: When this relationship was recorded/reported\n\n"
    "**Temporal Inference Rules:**\n"
    "1. If the text mentions a specific year (e.g., '2023 emissions'), set valid_from to that year\n"
    "2. If reporting year is {year}, and no end date is mentioned, set valid_to to null and is_current to true\n"
    "3. For historical data, set is_current to false\n"
    "4. For KPI observations, use the 'year' field as valid_from\n"
    "5. If no temporal info is explicit, infer from context (reporting year, document date, etc.)\n"
    "6. For organizational facts (like industry), if stated in a {year} report without historical context, use {year} as valid_from\n"
    "7. For time-bound observations (emissions, waste, KPIs), each year/period is a separate node version\n"
    "8. For entities (organizations, facilities), only create new versions when properties actually change\n\n"
    "**Entity Versioning:**\n"
    "* Observations (KPIObservation, Emission, Waste) are inherently time-bound - each is a unique node\n"
    "* Entities (Organization, Facility, Person) should be versioned only when their properties change)\n"
    "* Use 'supersedes' edges to link entity versions (newer version supersedes older version)\n"
    "* The newest version of an entity should have is_current=true, older versions is_current=false\n\n"
    "------------------\n"
    "## STRICT EXTRACTION RULES\n"
    "------------------\n"
    "Return a single JSON *array* of objects with keys:\n"
    "    subject  | predicate | object | temporal_metadata\n"
    "where:\n"
    "* predicate in edge labels from schema.\n"
    "* subject.class & object.class in entity classes from schema.\n"
    "* properties subset of declared keys for that class (INCLUDING valid_from, valid_to, is_current).\n"
    "* temporal_metadata contains edge temporal properties (valid_from, valid_to, recorded_at)\n"
    "Do not add extra keys, comments, or prose.\n\n"
    "-----------------\n"
    "POSITIVE EXAMPLE (valid temporal extraction)\n"
    "-----------------\n"
    "[{{\n"
    '  "subject": {{"class": "Organization", "properties": {{"name": "Acme Corp", "industry": "Textiles", '
    '"valid_from": "2020-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "predicate": "reportsKPI",\n'
    '  "object": {{"class": "KPIObservation", "properties": {{"kpi_type": "ESG-1-1", "title": "Total energy consumed", '
    '"value": 42.7, "unit": "MWh", "kind": "achieved", "direction": "reduction", "year": 2023, "target_year": null, '
    '"baseline_year": 2020, "source_id": "acme_2023.pdf_1_2", "company": "acme", '
    '"valid_from": "2023-01-01", "valid_to": "2023-12-31", "is_current": false}}}},\n'
    '  "temporal_metadata": {{"valid_from": "2023-01-01", "valid_to": null, "recorded_at": "{year}-01-01"}}\n'
    "}}]\n\n"
    "-----------------\n"
    "BEGIN EXTRACTION\n"
    "-----------------\n"
    "Extract temporal triples from the following text **and output only the JSON array**.\n\n"
    "------------------\n"
    "COMPANY NAME: {company}\n"
    "REPORTING YEAR: {year}\n"
    "------------------\n\n"
    "Output a valid JSON array, or an empty array [] if nothing found.\n\n"
)


def build_page_prompt(schema: Dict[str, Any], page_text: str, page_no: int,
                      page_kpis: List[Dict[str, Any]], company: str, year: int) -> str:
    header = TEMPORAL_GRAPH_PROMPT_TEMPLATE.format(
        schema_json=json.dumps(schema, ensure_ascii=False, indent=2),
        company=company,
        year=year,
    )
    kpi_section = (
        f"--- KPI OBSERVATIONS (page {page_no}) ---\n```json\n"
        f"{json.dumps(page_kpis, indent=2, ensure_ascii=False)}\n```\n\n"
        if page_kpis else ""
    )
    return f"{header}\n\n--- DOC page {page_no} ---\n\n{page_text}\n\n{kpi_section}"


# --------------------------------------------------------------------------- #
# JSON cleaning / recovery (verbatim).
# --------------------------------------------------------------------------- #
def _response_to_text(resp) -> str:
    if isinstance(resp, genai.types.GenerateContentResponse):
        buf: List[str] = []
        for cand in resp.candidates or []:
            for part in (cand.content.parts or []):
                txt = getattr(part, "text", None)
                if txt:
                    buf.append(txt)
        return "\n".join(buf)
    return str(resp)


def _clean_json_response(resp) -> str:
    text = _response_to_text(resp).strip()
    if not text:
        return ""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("Here") or text.lower().startswith("i'll"):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("[") or line.strip().startswith("{"):
                text = "\n".join(lines[i:])
                break
    start = text.find("[")
    end = text.rfind("]") + 1
    if start != -1 and end > start:
        return text[start:end]
    start = text.find("{")
    end = text.rfind("}") + 1
    return text[start:end] if start != -1 and end > start else ""


def _parse_json_response(raw) -> Tuple[Union[Dict, List, str], bool]:
    cleaned = _clean_json_response(raw)
    if not cleaned:
        logger.warning("Empty response after cleaning")
        return [], False
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    cleaned = re.sub(r"//.*?$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    try:
        return json.loads(cleaned), True
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parsing failed: {e}")
        try:
            fixed = cleaned.replace("'", '"')
            fixed = re.sub(r"(\w+):", r'"\1":', fixed)
            parsed = json.loads(fixed)
            logger.info("Recovered JSON with fixes")
            return parsed, True
        except Exception:
            logger.error("Could not recover JSON")
            return [], False


def _validate_extraction_format(data: Any, schema: Dict[str, Any]) -> bool:
    if not isinstance(data, list):
        logger.warning(f"Expected list, got {type(data)}")
        return False
    entities, edge_labels = schema_sets(schema)
    valid_count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        if not {"subject", "predicate", "object"}.issubset(item.keys()):
            continue
        ok = True
        for k in ("subject", "object"):
            e = item[k]
            if not isinstance(e, dict) or not {"class", "properties"}.issubset(e.keys()):
                ok = False
                break
            if not isinstance(e["properties"], dict):
                ok = False
                break
            if e["class"] not in entities:
                ok = False
                break
        if not ok:
            continue
        if item["predicate"] not in edge_labels:
            continue
        valid_count += 1
    logger.info(f"Validated {valid_count}/{len(data)} triples")
    return valid_count > 0


# --------------------------------------------------------------------------- #
# Triple list -> graph (verbatim).
# --------------------------------------------------------------------------- #
OBSERVATION_CLASSES = {"KPIObservation", "Emission", "Waste"}


def triple_list_to_graph(triples: List[Dict[str, Any]], schema: Dict[str, Any]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    node_index: Dict[str, int] = {}
    identity_keys_map = get_identity_keys(schema)
    edges: List[Dict[str, Any]] = []

    def _idx(entity: Dict[str, Any]) -> Optional[int]:
        if not isinstance(entity, dict) or "class" not in entity or "properties" not in entity:
            return None
        stable_id = get_stable_entity_id(entity, identity_keys_map)
        props = entity["properties"]
        entity_class = entity["class"]
        if entity_class in OBSERVATION_CLASSES:
            version_key = f"{stable_id}|{json.dumps(props, sort_keys=True)}"
        else:
            version_key = f"{stable_id}|{props.get('valid_from', '')}|{props.get('valid_to', '')}"
        if version_key not in node_index:
            node_index[version_key] = len(nodes)
            nodes.append({"class": entity_class, "properties": props, "stable_id": stable_id})
        return node_index[version_key]

    for t in triples:
        if not {"subject", "predicate", "object"}.issubset(t.keys()):
            continue
        s = _idx(t["subject"])
        o = _idx(t["object"])
        if s is None or o is None:
            continue
        edge = {"subject": s, "predicate": t["predicate"], "object": o}
        if "temporal_metadata" in t:
            edge["temporal_metadata"] = t["temporal_metadata"]
        edges.append(edge)

    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------- #
# I/O adapters: page text from JSONL, KPIs from kpi_output/.
# Page numbering is 1-based throughout (matches step 1's page_NNN_kpis.json).
# --------------------------------------------------------------------------- #
def pages_for_doc(jsonl_pages: Dict[int, List[Tuple[int, str, bool]]]) -> List[Dict[str, Any]]:
    out = []
    for page_num in sorted(jsonl_pages.keys()):
        rows = jsonl_pages[page_num]
        out.append({
            "page": page_num,
            "text": build_page_text(rows),
            "has_esg": page_has_esg(rows),
        })
    return out


def load_kpis_for_doc(pdf_stem: str, kpi_dir: Path) -> Dict[int, List[Dict[str, Any]]]:
    sub = kpi_dir / f"{pdf_stem}_kpis"
    out: Dict[int, List[Dict[str, Any]]] = {}
    if not sub.exists():
        logger.warning(f"KPI directory not found: {sub}")
        return out
    for f in sub.glob("page_*_kpis.json"):
        m = re.search(r"page_(\d+)_kpis\.json$", f.name)
        if not m:
            continue
        page_num = int(m.group(1))
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Error reading {f}: {e}")
            continue
        if isinstance(data, list):
            out.setdefault(page_num, []).extend(data)
        elif isinstance(data, dict):
            out.setdefault(page_num, []).append(data)
    return out


# --------------------------------------------------------------------------- #
# LLM call (verbatim semantics, simplified for a single client).
# --------------------------------------------------------------------------- #
def call_llm(prompt: str, client: genai.Client, client_idx: int,
             rate_limiter: RateLimiter, schema: Dict[str, Any], model: str,
             retries: int = 3) -> Tuple[Any, str, bool]:
    last_error: Optional[Exception] = None
    last_raw = ""
    rate_limit_failures = 0
    for attempt in range(1, retries + 1):
        try:
            rate_limiter.wait_if_needed(client_idx)
            resp = client.models.generate_content(model=model, contents=prompt, config=CFG_JSON)
            last_raw = _response_to_text(resp)
            parsed, ok = _parse_json_response(last_raw)
            if ok:
                if _validate_extraction_format(parsed, schema):
                    logger.info(f"Extracted {len(parsed)} relations")
                else:
                    logger.warning(f"Attempt {attempt}: valid JSON but format issues")
                return parsed, last_raw, False
            logger.warning(f"Attempt {attempt}: could not parse valid JSON")
        except Exception as e:
            last_error = e
            es = str(e).lower()
            if "rate" in es or "quota" in es or "429" in es:
                rate_limit_failures += 1
                logger.warning(f"Attempt {attempt} - Rate limit hit for client {client_idx}: {e}")
            else:
                logger.error(f"Attempt {attempt} failed: {e}")
        if attempt < retries:
            wait = 2 ** (attempt - 1)
            logger.info(f"Waiting {wait}s before retry...")
            time.sleep(wait)
    if rate_limit_failures == retries:
        return [], last_raw, True
    logger.error(f"All {retries} attempts failed. Last error: {last_error}")
    return [], last_raw, False


# --------------------------------------------------------------------------- #
# Per-page processing.
# --------------------------------------------------------------------------- #
def process_page(page_info: Dict[str, Any], page_kpis: List[Dict[str, Any]],
                 client: genai.Client, client_idx: int, rate_limiter: RateLimiter,
                 schema: Dict[str, Any], model: str, esg_only: bool,
                 pdf_stem: str, dbg_pdf_dir: Path, g_pdf_dir: Path,
                 company: str, year: int) -> Tuple[int, bool, bool]:
    p_no = page_info["page"]
    page_text = page_info["text"]
    has_esg = page_info["has_esg"]

    out_file = g_pdf_dir / f"page{p_no}.json"
    bugged_file = g_pdf_dir / f"page{p_no}_bugged.json"

    if out_file.exists():
        logger.info(f"Skipping page {p_no} (already exists)")
        return p_no, True, False

    if not page_text:
        out_file.write_text(json.dumps({"nodes": [], "edges": []}, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        return p_no, True, False

    if esg_only and not has_esg:
        logger.info(f"Page {p_no}: no ESG sentence - writing empty graph")
        out_file.write_text(json.dumps({"nodes": [], "edges": []}, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        return p_no, True, False

    logger.info(f"-> Processing page {p_no} with client {client_idx}")
    prompt = build_page_prompt(schema, page_text, p_no, page_kpis, company=company, year=year)

    max_retries = 2
    for retry in range(max_retries):
        parsed, raw, rate_limited = call_llm(prompt, client, client_idx, rate_limiter,
                                             schema, model, retries=2)
        if rate_limited:
            logger.warning(f"Page {p_no} skipped due to rate limiting on client {client_idx}")
            return p_no, False, True

        dbg_path = dbg_pdf_dir / f"{pdf_stem}_p{p_no}.txt"
        dbg_path.write_text(
            f"==== PROMPT ====\n{prompt[:2000]}...\n\n==== RESPONSE ====\n{raw or '[NO RESPONSE]'}",
            encoding="utf-8",
        )

        if raw:
            if isinstance(parsed, list) and parsed:
                entities, edge_labels = schema_sets(schema)
                valid_triples: List[Dict[str, Any]] = []
                invalid_triples: List[Dict[str, Any]] = []
                for triple in parsed:
                    if not isinstance(triple, dict):
                        invalid_triples.append(triple)
                        continue
                    if not {"subject", "predicate", "object"}.issubset(triple.keys()):
                        invalid_triples.append(triple)
                        continue
                    valid = True
                    for k in ("subject", "object"):
                        ent = triple.get(k, {})
                        if not isinstance(ent, dict):
                            valid = False
                            break
                        if "class" not in ent or "properties" not in ent:
                            valid = False
                            break
                        if ent["class"] not in entities:
                            valid = False
                            break
                    if triple.get("predicate") not in edge_labels:
                        valid = False
                    (valid_triples if valid else invalid_triples).append(triple)

                if invalid_triples:
                    logger.warning(f"Page {p_no}: {len(invalid_triples)} invalid triples -> bugged file")
                    bugged_file.write_text(
                        json.dumps(invalid_triples, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

                graph = (triple_list_to_graph(valid_triples, schema)
                         if valid_triples else {"nodes": [], "edges": []})
                out_file.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
                logger.info(f"Page {p_no}: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
                return p_no, True, False
            else:
                malformed = g_pdf_dir / f"page{p_no}_malformed.txt"
                malformed.write_text(
                    f"Company: {company}\nYear: {year}\nPage: {p_no}\n\n"
                    f"==== MALFORMED RESPONSE ====\n{raw}\n\n==== END MALFORMED RESPONSE ====\n",
                    encoding="utf-8",
                )
                logger.warning(f"Page {p_no}: malformed JSON -> {malformed.name}")

        logger.warning(f"Page {p_no} LLM call failed, retry {retry + 1}/{max_retries}")
        time.sleep(2)

    logger.error(f"Page {p_no} failed after {max_retries} retries")
    return p_no, False, False


# --------------------------------------------------------------------------- #
# Per-document driver.
# --------------------------------------------------------------------------- #
def process_document(source_pdf: str, jsonl_pages: Dict[int, List[Tuple[int, str, bool]]],
                     kpi_dir: Path, out_dir: Path, schema: Dict[str, Any], model: str,
                     client: genai.Client, rate_limiter: RateLimiter,
                     esg_only: bool, max_workers: int) -> Tuple[int, int]:
    pdf_stem = os.path.splitext(source_pdf)[0]
    company, year_str = parse_company_year_from_filename(source_pdf)
    try:
        year = int(year_str)
    except ValueError:
        logger.warning(f"Year not parseable from {source_pdf}; defaulting to 2024")
        year = 2024

    g_pdf_dir = out_dir / "graphs" / pdf_stem
    g_pdf_dir.mkdir(parents=True, exist_ok=True)
    dbg_pdf_dir = out_dir / "debug_outputs_per_page" / pdf_stem
    dbg_pdf_dir.mkdir(parents=True, exist_ok=True)

    page_kpi_map = load_kpis_for_doc(pdf_stem, kpi_dir)
    pages = pages_for_doc(jsonl_pages)

    logger.info(f"=== Processing {source_pdf} - {company} ({year}) - {len(pages)} pages ===")

    success = 0
    failed = 0
    rate_limited = 0
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(
                process_page, pg, page_kpi_map.get(pg["page"], []),
                client, 0, rate_limiter, schema, model, esg_only,
                pdf_stem, dbg_pdf_dir, g_pdf_dir, company, year,
            ): pg["page"]
            for pg in pages
        }
        for fut in as_completed(futures):
            page_no = futures[fut]
            try:
                _, ok, was_rate_limited = fut.result()
            except Exception as e:
                logger.error(f"Page {page_no} exception: {e}")
                failed += 1
                continue
            if ok:
                success += 1
            else:
                failed += 1
                if was_rate_limited:
                    rate_limited += 1

    if rate_limited:
        logger.warning(f"{rate_limited} page(s) skipped due to rate limiting")
    logger.info(f"=== Finished {source_pdf}: {success}/{len(pages)} succeeded ===")
    return success, failed


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract temporal ESG graphs from labeled JSONL + KPI dir using Gemini"
    )
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT, help="Labeled JSONL path")
    parser.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA, help="Graph schema JSON")
    parser.add_argument("--kpi-dir", type=Path, default=DEFAULT_KPI_DIR, help="Per-doc KPI root (kpi_output/)")
    parser.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--doc", type=str, help="Process only source_pdf names containing this substring")
    parser.add_argument("--limit-docs", type=int, help="Process only the first N documents")
    parser.add_argument("--all", action="store_true", help="Process all documents")
    parser.add_argument("--all-pages", action="store_true",
                        help="Run every non-empty page (default: only pages with >=1 ESG sentence)")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Parallel page workers")
    parser.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT, help="Max RPM (default 10)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model id")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input JSONL not found: {args.input}")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}")
        return

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    entities, edges = schema_sets(schema)
    logger.info(f"Schema loaded: {len(entities)} entity classes, {len(edges)} edge labels")

    client = genai.Client(api_key=api_key)
    rate_limiter = RateLimiter(max_calls_per_minute=args.rate_limit)

    docs = load_pages_from_jsonl(args.input)
    selected = select_documents(docs, args)
    if not selected:
        return

    esg_only = not args.all_pages

    total_success = 0
    total_failed = 0
    for src in selected:
        s, f = process_document(
            src, docs[src],
            args.kpi_dir, args.out_dir, schema, args.model,
            client, rate_limiter, esg_only=esg_only, max_workers=args.max_workers,
        )
        total_success += s
        total_failed += f
    logger.info(
        f"Done. {total_success} page(s) succeeded, {total_failed} failed "
        f"across {len(selected)} doc(s) -> {args.out_dir}"
    )


if __name__ == "__main__":
    main()
