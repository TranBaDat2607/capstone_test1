#!/usr/bin/env python3
"""
Step 2 — extract temporal ESG knowledge-graph triples from the page-level KPI JSONs
written by step01, mirroring EmeraldMind/src/EmeraldKG/2-extract-triplet.py but:

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

Run from the REPO ROOT:

    python src/run.py extract_triples --dry-run --doc AAA_2023
    python src/run.py extract_triples --doc AAA_2023 --source report
    python src/run.py extract_triples --doc AAA_2023 --source news

MIGRATED FROM ``src/step02_extract_triplet_from_jsonl.py`` (2026-07-29), the 15th and
final stage of this refactor. Only the docstring and import block differ, plus one
plumbing change: ``REPO_ROOT`` now comes from ``esg_kg.core.paths``; the 5 JSONL
helpers (``load_pages_from_jsonl``, ``build_page_text``, ``page_has_esg``,
``select_documents``, ``parse_company_year_from_filename``) come from
``esg_kg.core.io_jsonl`` instead of being borrowed off step01's file directly;
``RateLimiter``/``DEFAULT_RATE_LIMIT`` come from ``esg_kg.core.llm``;
``get_identity_keys`` comes from ``esg_kg.core.schema``; ``get_stable_entity_id`` and
``PROVENANCE_CLASSES`` come from ``esg_kg.core.identity`` — all five were confirmed
byte-identical to their ``src/`` originals before being dropped here. The stage-local
``schema_sets(schema) -> (classes, edges)`` is DELETED rather than kept: it duplicated
``esg_kg.core.schema.load_schema_sets(schema) -> (classes, edges, edge_directions)`` in
its first two return values, so every call site now unpacks that 3-tuple and discards
``edge_directions`` (step02 never validates edge direction — that is step03's job).
Matches the precedent of step03/step04 dropping a stage-local duplicate once a kernel
equivalent exists, rather than keeping it "for compatibility".

There is no ``_Provider`` involved: like step01, this stage talks to Gemini directly via
``google.genai.Client``. ``TEMPORAL_GRAPH_PROMPT_TEMPLATE``, ``NEWS_GRAPH_PROMPT_TEMPLATE``,
and everything else in this file stay stage-local: nothing else in the pipeline imports them.

2026-08-04: the additive ``--provider openai`` path (added 2026-07-29 while the Gemini
project behind GEMINI_API_KEY was billing-blocked) was removed outright — this project
now pays only for Gemini, so this stage is gemini-only again, no fallback.

Both prompt templates carry the Vietnamese-output fix (issue #6, landed in ``src/``
first per DESIGN.md §5.3/§5.6 the day before this migration) — this file moved them
verbatim, already fixed. ``test/test_esg_kg_extract_triples.py`` compares the two trees
on the real corpus (the pure helpers), on the two prompt templates byte-for-byte, and on
a stubbed Gemini client (the paid path, both ``--source report`` and ``--source news``)
to keep it that way.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
from google import genai
from google.genai import types

from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.io_jsonl import (
    build_page_text,
    load_pages_from_jsonl,
    page_has_esg,
    parse_company_year_from_filename,
    select_documents,
)
from esg_kg.core.llm import DEFAULT_RATE_LIMIT, RateLimiter
from esg_kg.core.schema import get_identity_keys, load_schema_sets
from esg_kg.core.identity import PROVENANCE_CLASSES, get_stable_entity_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


DEFAULT_INPUT = REPO_ROOT / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_KPI_DIR = REPO_ROOT / "kpi_output"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_WORKERS = 4


# --------------------------------------------------------------------------- #
# Gemini config + prompt template (verbatim; carries the issue-#6 language fix).
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
    "## EVENT ANCHORING RULES (REQUIRED - anchor every event to >= 2 entities when the text allows)\n"
    "------------------\n"
    "Event/observation nodes (KPIObservation, Emission, Waste, Penalty, Controversy, Investment,\n"
    "Initiative, Project) must NOT hang off the reporting organization alone. Whenever the text\n"
    "names a second real-world entity for the same fact, you MUST also emit the corresponding\n"
    "schema edge in the same JSON array:\n"
    "* a named factory / plant / mine / site -> KPIObservation --observedAtFacility--> Facility,\n"
    "  Facility --generatesEmission--> Emission, Facility --generatesWaste--> Waste\n"
    "  (plus Facility --locatedIn--> Location when the place is named)\n"
    "* a named province / city / country     -> Organization|Facility|Project --locatedIn--> Location\n"
    "* a named product                        -> Product --producedBy--> Organization,\n"
    "  Product --manufacturedAt--> Facility\n"
    "* a named authority / regulator          -> Penalty --enforcedBy--> Authority,\n"
    "  Certification/Standard --issuedBy--> Authority\n"
    "* a named partner / subsidiary           -> Organization --partnersWith/owns--> Organization\n"
    "Example: 'Nha may Yen Bai dat san luong 43.200 tan' MUST yield BOTH\n"
    "Organization --reportsKPI--> KPIObservation AND KPIObservation --observedAtFacility--> Facility.\n"
    "Only anchor to entities the text actually names - NEVER invent a facility, location or\n"
    "authority that is not in the text.\n\n"
    "------------------\n"
    "## OUTPUT LANGUAGE (name / title / description / free text)\n"
    "------------------\n"
    "Write every `name`, `title`, `description` and other free-text property VALUE in "
    "VIETNAMESE, with full diacritics, exactly matching the source text. Do NOT translate "
    "into English. Do NOT strip diacritics (khong duoc bo dau).\n"
    "  - WRONG (translated): \"An Phat Green Environment and Plastic Joint Stock Company\"\n"
    "  - WRONG (diacritics stripped): \"CONG TY CO PHAN NHUA VA MOI TRUONG XANH AN PHAT\"\n"
    "  - RIGHT: \"CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT\"\n"
    "This rule does NOT apply to: dates (valid_from/valid_to/date/recorded_at - always ISO "
    "YYYY[-MM[-DD]], never a Vietnamese date phrase), `class`/`predicate` (schema "
    "vocabulary, must match the schema exactly), ids (source_id/kpi_id/claim_id), booleans "
    "(is_current/date_uncertain), and unit (controlled vocabulary). Leave those exactly as "
    "specified elsewhere in this prompt.\n\n"
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
    "POSITIVE EXAMPLE (valid temporal extraction; the KPI is anchored to BOTH the organization\n"
    "and the facility the text names)\n"
    "-----------------\n"
    "[{{\n"
    '  "subject": {{"class": "Organization", "properties": {{"name": "Công ty Cổ phần Vật liệu Xây dựng Sông Hồng", "industry": "Textiles", '
    '"valid_from": "2020-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "predicate": "reportsKPI",\n'
    '  "object": {{"class": "KPIObservation", "properties": {{"kpi_type": "ESG-1-1", "title": "Total energy consumed", '
    '"value": 42.7, "unit": "MWh", "kind": "achieved", "direction": "reduction", "year": 2023, "target_year": null, '
    '"baseline_year": 2020, "source_id": "acme_2023.pdf_1_2", "company": "acme", '
    '"valid_from": "2023-01-01", "valid_to": "2023-12-31", "is_current": false}}}},\n'
    '  "temporal_metadata": {{"valid_from": "2023-01-01", "valid_to": null, "recorded_at": "{year}-01-01"}}\n'
    "}},\n"
    "{{\n"
    '  "subject": {{"class": "KPIObservation", "properties": {{"kpi_type": "ESG-1-1", "title": "Total energy consumed", '
    '"value": 42.7, "unit": "MWh", "kind": "achieved", "direction": "reduction", "year": 2023, "target_year": null, '
    '"baseline_year": 2020, "source_id": "acme_2023.pdf_1_2", "company": "acme", '
    '"valid_from": "2023-01-01", "valid_to": "2023-12-31", "is_current": false}}}},\n'
    '  "predicate": "observedAtFacility",\n'
    '  "object": {{"class": "Facility", "properties": {{"name": "Nhà máy Sông Hồng Hà Nội", "type": "factory", '
    '"valid_from": "2020-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "temporal_metadata": {{"valid_from": "2023-01-01", "valid_to": "2023-12-31", "recorded_at": "{year}-01-01"}}\n'
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


# News-oriented variant (SYSTEM_DESIGN §5.2). Same ontology, temporal rules and output
# format as the report template, but framed so the model treats the text as THIRD-PARTY
# news ABOUT the company (conduct side), not a statement BY the company (claim side).
NEWS_GRAPH_PROMPT_TEMPLATE = (
    "You are an ESG temporal knowledge-graph extractor working on a THIRD-PARTY NEWS ARTICLE.\n\n"
    "## CONTEXT - THIS IS INDEPENDENT NEWS, NOT THE COMPANY'S OWN REPORT\n"
    "The text below is a news article written by an external source ABOUT the company\n"
    "'{company}', NOT a statement made BY the company. Treat every fact as REPORTED CONDUCT /\n"
    "third-party observation - evidence of what the company actually did, not what it claims.\n"
    "* Source domain : {source_domain}\n"
    "* Article title : {title}\n"
    "* Publish date  : {publish_date}\n"
    "* URL           : {url}\n\n"
    "## INPUTS\n"
    "* KNOWLEDGE GRAPH SCHEMA: entity classes, edge labels, and temporal properties (JSON).\n"
    "* documents: plain text from one news article.\n"
    "* KPI records: optional JSON list of numbers observed in the article.\n\n"
    "## Task\n"
    "Extract **temporal** relations describing the company's real-world CONDUCT as reported by\n"
    "this article. This is a TEMPORAL knowledge graph - you MUST include temporal properties for\n"
    "all nodes and edges. Obey the ontology below.\n\n"
    "## PREFER CONDUCT CLASSES AND EDGES (use only classes/edges present in the schema)\n"
    "* ALWAYS create a MediaReport node for this article and link it to the company:\n"
    "    MediaReport --mentionsOrganization--> Organization\n"
    "  (this anchors the article and the company on the conduct side).\n"
    "* A fine / sanction / administrative penalty -> Penalty, linked as:\n"
    "    Organization --subjectToPenalty--> Penalty   (and Penalty --enforcedBy--> Authority if named).\n"
    "* A real-world number REPORTED BY THE NEWS (not a company target) -> KPIObservation with\n"
    "    kind='achieved', linked as Organization --reportsKPI--> KPIObservation.\n"
    "* An independent certification / audit / verification -> ThirdPartyVerification or\n"
    "    Organization --holdsCertification--> Certification.\n"
    "* A scandal / violation / lawsuit narrative -> you may create a Controversy node, but only\n"
    "    emit it as part of a schema-legal edge; otherwise capture the event via MediaReport/Penalty.\n"
    "* Do NOT invent SustainabilityClaim / Goal / target-KPIObservation nodes from news - those\n"
    "    belong to the company's own reports (claim side). News is the conduct side.\n\n"
    "## EVENT ANCHORING RULES (REQUIRED - anchor every event to >= 2 entities when the text allows)\n"
    "Conduct nodes (Penalty, Controversy, MediaReport, KPIObservation) must NOT hang off the\n"
    "company alone. Whenever the article names a second real-world entity for the same fact,\n"
    "you MUST also emit the corresponding schema edge in the same JSON array:\n"
    "* the authority that fined/sanctioned      -> Penalty --enforcedBy--> Authority\n"
    "* the factory / plant / site involved      -> KPIObservation --observedAtFacility--> Facility\n"
    "  (plus Facility --locatedIn--> Location when the place is named)\n"
    "* the province / city of the incident      -> Organization|Facility --locatedIn--> Location\n"
    "* a named product                          -> MediaReport --mentionsProduct--> Product\n"
    "* the factory / plant / site named in the article -> MediaReport --mentionsFacility--> Facility\n"
    "  (in addition to Facility --locatedIn--> Location below, if the place is also named)\n"
    "* the province / city / area central to the story -> MediaReport --mentionsFacility--> Location\n"
    "* a named partner / subsidiary / supplier  -> Organization --partnersWith/owns--> Organization\n"
    "Only anchor to entities the article actually names - NEVER invent one.\n\n"
    "------------------\n"
    "## KNOWLEDGE GRAPH SCHEMA\n"
    "------------------\n"
    "{schema_json}\n\n"
    "------------------\n"
    "## TEMPORAL EXTRACTION RULES\n"
    "------------------\n"
    "ALL nodes and edges MUST include temporal information:\n\n"
    "**For ALL Nodes:** valid_from (YYYY-MM-DD or YYYY), valid_to (or null), is_current (bool).\n"
    "**For ALL Edges:** a temporal_metadata object with valid_from, valid_to (or null), recorded_at.\n\n"
    "**Temporal Inference Rules:**\n"
    "1. Use the event's OWN date/period if the article states it explicitly (an exact date, or a "
    "quarter/period tied to an explicit year, e.g. 'quy 2/2025' or 'nam 2023') for valid_from, "
    "and set date_uncertain=false - the text itself anchors the date, independent of publish date.\n"
    "2. If the article does NOT state the event's own date/period explicitly (e.g. 'quy 2' with no "
    "year given, or a vague 'gan day'/'recently'), do NOT assume it means the publish year - fall "
    "back to the publish date {publish_date} for valid_from / recorded_at, and set "
    "date_uncertain=true so downstream consumers know this date is a proxy, not a confirmed event "
    "date. When genuinely unsure whether the article stated an explicit period, prefer "
    "date_uncertain=true (never guess silently).\n"
    "3. Ongoing/most-recent facts: valid_to=null, is_current=true; past events: is_current=false.\n"
    "4. For observed numbers, use the reported year as valid_from, applying the same "
    "date_uncertain rule as #1/#2 (explicit year in text -> false; inferred/assumed -> true).\n"
    "5. Controversy, Penalty, MediaReport, and KPIObservation nodes MUST include a boolean "
    "date_uncertain property set per rules #1/#2/#4 above.\n\n"
    "------------------\n"
    "## OUTPUT LANGUAGE (name / title / description / free text)\n"
    "------------------\n"
    "Write every `name`, `title`, `description` and other free-text property VALUE in "
    "VIETNAMESE, with full diacritics, exactly matching the source text. Do NOT translate "
    "into English. Do NOT strip diacritics (khong duoc bo dau).\n"
    "  - WRONG (translated): \"An Phat Green Environment and Plastic Joint Stock Company\"\n"
    "  - WRONG (diacritics stripped): \"CONG TY CO PHAN NHUA VA MOI TRUONG XANH AN PHAT\"\n"
    "  - RIGHT: \"CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT\"\n"
    "This rule does NOT apply to: dates (valid_from/valid_to/date/recorded_at - always ISO "
    "YYYY[-MM[-DD]], never a Vietnamese date phrase), `class`/`predicate` (schema "
    "vocabulary, must match the schema exactly), ids (source_id/kpi_id/claim_id), booleans "
    "(is_current/date_uncertain), and unit (controlled vocabulary). Leave those exactly as "
    "specified elsewhere in this prompt.\n\n"
    "------------------\n"
    "## STRICT EXTRACTION RULES\n"
    "------------------\n"
    "Return a single JSON *array* of objects with keys:\n"
    "    subject  | predicate | object | temporal_metadata\n"
    "where predicate is an edge label from the schema, subject.class & object.class are entity\n"
    "classes from the schema, and each entity's properties are a subset of that class's declared\n"
    "keys (INCLUDING valid_from, valid_to, is_current). Do not add extra keys, comments, or prose.\n\n"
    "-----------------\n"
    "POSITIVE EXAMPLE (independent news reporting a penalty, explicit event date -> date_uncertain=false)\n"
    "-----------------\n"
    "[{{\n"
    '  "subject": {{"class": "MediaReport", "properties": {{"report_id": "vietnamnet_2024_aaa_tax", '
    '"title": "Khai sai thuế, Nhựa An Phát Xanh bị xử lý hơn 1,7 tỷ đồng", "publisher": "vietnamnet.vn", '
    '"date": "2024-08-14", "date_uncertain": false, "valid_from": "2024-08-14", "valid_to": null, '
    '"is_current": true}}}},\n'
    '  "predicate": "mentionsOrganization",\n'
    '  "object": {{"class": "Organization", "properties": {{"name": "CTCP Nhựa An Phát Xanh", '
    '"valid_from": "2024-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "temporal_metadata": {{"valid_from": "2024-08-14", "valid_to": null, "recorded_at": "{year}-01-01"}}\n'
    "}},\n"
    "{{\n"
    '  "subject": {{"class": "Organization", "properties": {{"name": "CTCP Nhựa An Phát Xanh", '
    '"valid_from": "2024-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "predicate": "subjectToPenalty",\n'
    '  "object": {{"class": "Penalty", "properties": {{"penalty_id": "aaa_tax_2024", '
    '"description": "Xử phạt do khai sai thuế", "amount": "1.7 billion VND", "date": "2024-08-14", '
    '"date_uncertain": false, "valid_from": "2024-08-14", "valid_to": null, "is_current": true}}}},\n'
    '  "temporal_metadata": {{"valid_from": "2024-08-14", "valid_to": null, "recorded_at": "{year}-01-01"}}\n'
    "}}]\n\n"
    "-----------------\n"
    "UNCERTAIN-DATE EXAMPLE (article says only \"quy 2\" with NO year stated for that figure -> "
    "must NOT assume it means the publish year; fall back to publish date and flag it)\n"
    "-----------------\n"
    "[{{\n"
    '  "subject": {{"class": "Organization", "properties": {{"name": "CTCP Nhựa An Phát Xanh", '
    '"valid_from": "2024-01-01", "valid_to": null, "is_current": true}}}},\n'
    '  "predicate": "reportsKPI",\n'
    '  "object": {{"class": "KPIObservation", "properties": {{"kpi_type": "profit", '
    '"title": "Lợi nhuận quý 2 tăng trưởng 24,6 phần trăm", "value": 24.6, "unit": "percent", "kind": "achieved", '
    '"direction": "increase", "year": {year}, "source_id": "doanhnhan_baophapluat_20260614", '
    '"date_uncertain": true, "valid_from": "{publish_date}", "valid_to": null, "is_current": true}}}},\n'
    '  "temporal_metadata": {{"valid_from": "{publish_date}", "valid_to": null, "recorded_at": "{year}-01-01"}}\n'
    "}}]\n\n"
    "-----------------\n"
    "BEGIN EXTRACTION\n"
    "-----------------\n"
    "Extract temporal conduct triples from the following article **and output only the JSON array**.\n\n"
    "------------------\n"
    "COMPANY NAME: {company}\n"
    "PUBLISH YEAR: {year}\n"
    "------------------\n\n"
    "Output a valid JSON array, or an empty array [] if nothing found.\n\n"
)


def build_page_prompt(schema: Dict[str, Any], page_text: str, page_no: int,
                      page_kpis: List[Dict[str, Any]], company: str, year: int,
                      source: str = "report", article_meta: Optional[Dict[str, Any]] = None) -> str:
    if source == "news":
        meta = article_meta or {}
        header = NEWS_GRAPH_PROMPT_TEMPLATE.format(
            schema_json=json.dumps(schema, ensure_ascii=False, indent=2),
            company=company,
            year=year,
            source_domain=meta.get("source_domain", ""),
            title=meta.get("title", ""),
            publish_date=meta.get("publish_date", ""),
            url=meta.get("url", ""),
        )
    else:
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
    entities, edge_labels, _ = load_schema_sets(schema)
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
# Deterministic claim_id (GRAPH_IMPROVEMENT_PLAN.md C1 / GitHub issue #2).
#
# SustainabilityClaim's identity_keys is exactly ["claim_id"] (config/schema.json), and
# get_stable_entity_id hashes a node's identity straight off that property value. Left
# to the LLM (the prompt only says to leave the ids' VALUE as-is, never how to build
# one), claim_id is free text the model invents per call - re-running this stage over
# the identical source sentence can mint a different id and silently re-partition every
# already-paid crosscheck dossier (DESIGN.md Sec1.1: claim resolution in
# load/neo4j_sync.py is 100% stable_id tier, no fallback). Deriving it instead from
# (source_doc, page, normalized description) makes it a pure function of content +
# provenance, so identical input always reproduces the identical id regardless of what
# the LLM would have called it.
def _normalize_claim_text(text: str) -> str:
    """Case/whitespace-insensitive so trivial LLM formatting drift (extra spaces,
    trailing whitespace, casing) never changes the derived claim_id."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# --- Sentence-position anchoring (GRAPH_IMPROVEMENT_PLAN.md follow-up to C1) -------- #
# `description` (used above) is still LLM output: a re-run that re-transcribes the same
# source sentence slightly differently (truncation point, punctuation, mild paraphrase)
# still changes the hash. This layer anchors to the page's real, LLM-independent JSONL
# sentence row(s) instead, when a confident match can be found, falling back to the
# description-text hash above otherwise. Verified on the real corpus (1,217 claims):
# hashing on sentence_index alone (even with date) produced 40 real collisions - one
# sentence enumerating several distinct facts for the same year - so the anchor is
# (sentence_index, start_token_offset) pairs, not sentence_index alone; that gave 0
# collisions. 360/1,217 real claims get a confident anchor; the rest (including all
# historical pre-"issue #6" English-description claims, which can't token-match against
# Vietnamese rows) fall back to the text hash - i.e. this is strictly additive.
_CLAIM_MATCH_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

MIN_CLAIM_DESC_TOKENS_FOR_MATCH = 4   # below this: too generic/risky, go straight to fallback
CLAIM_MATCH_OVERLAP_THRESHOLD = 0.7   # longest-common-run / min(|desc|,|row|) a row must clear
MAX_CLAIM_MATCHED_ROWS = 3            # more distinct rows than this => ambiguous, distrust it


def _claim_match_tokens(text: str) -> List[str]:
    """`\\w+` on lowercased text - confirmed Vietnamese-diacritic-safe. Deliberately NOT
    esg_kg.core.naming.normalize_name: that strips legal-form phrases and fixes
    cross-document OCR artifacts, tuned for entity-NAME matching (anchor_kpi.py's job)
    - it would corrupt full-sentence semantics here. Both `description` and the JSONL
    `text` come from the same already-clean pipeline, so no OCR/legal-form
    normalization is needed."""
    return _CLAIM_MATCH_TOKEN_RE.findall((text or "").lower())


def _longest_common_run(a: List[str], b: List[str]) -> Tuple[int, int]:
    """Longest common CONTIGUOUS token run between `a` and `b` (longest-common-substring
    DP over token sequences). Returns (run_length, start_index_in_b); (0, -1) if none.

    Contiguity (not just shared vocabulary) is what separates "this description is a
    copy/truncation of that sentence" from "this description happens to share common
    Vietnamese words with an unrelated sentence" - confirmed on the real corpus: a
    same-page, different-fact sentence pair scored 0.5-0.6 under plain set-overlap
    purely from shared function/business words, which is why the threshold below is
    0.7, not lower; contiguity removes that ambiguity at negligible extra cost (rows
    are a few dozen tokens)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0, -1
    prev = [0] * (m + 1)
    best_len, best_end = 0, -1
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best_len:
                    best_len, best_end = cur[j], j
        prev = cur
    return (best_len, best_end - best_len) if best_len else (0, -1)


def match_claim_sentence_anchors(description: str, page_rows: List[Tuple[int, str, bool]]
                                 ) -> List[Tuple[int, int]]:
    """Match a claim's LLM-produced `description` back to the page's real JSONL
    sentence row(s) it was drawn from. Returns sorted, deduped (sentence_index,
    start_token_offset) pairs, or [] if there is no confident match (caller must fall
    back to hashing the raw description text - the original C1 behaviour).

    (sentence_index, start_offset) rather than sentence_index alone is deliberate: an
    enumeration sentence can name several distinct facts for the same year (e.g. an
    awards list) - the start offset of each claim's matched span is what stays stable
    across truncation-depth drift while still distinguishing those facts from
    each other, since each starts at a different point in the row."""
    desc_tokens = _claim_match_tokens(description)
    if len(desc_tokens) < MIN_CLAIM_DESC_TOKENS_FOR_MATCH:
        return []
    anchors: List[Tuple[int, int]] = []
    for sentence_index, text, _esg in page_rows:
        row_tokens = _claim_match_tokens(text)
        if not row_tokens:
            continue
        run_len, start = _longest_common_run(desc_tokens, row_tokens)
        if run_len == 0:
            continue
        if run_len / min(len(desc_tokens), len(row_tokens)) >= CLAIM_MATCH_OVERLAP_THRESHOLD:
            anchors.append((sentence_index, start))
    anchors = sorted(set(anchors))
    if not anchors or len(anchors) > MAX_CLAIM_MATCHED_ROWS:
        return []
    return anchors


def make_deterministic_claim_id(source_doc: str, page: int, description: str, date: str = "",
                                sentence_anchors: Optional[List[Tuple[int, int]]] = None) -> str:
    """`date` is real extracted content (e.g. an award's year, a meeting's exact day),
    not an LLM-invented id - it disambiguates the real corpus case where the same page
    repeats identical claim text for several different years (e.g. an awards table:
    'Sao vang dat Viet' in 2009/2010/2011, same description, same page, different
    date) - without it those collapse into one node under (source_doc, page,
    description) alone. Still a pure function of content + provenance.

    `sentence_anchors`, when non-empty, is the output of `match_claim_sentence_anchors`
    - hashing on that POSITION instead of the LLM's raw copied text is robust to
    re-transcription drift (different truncation point, punctuation, mild paraphrase)
    as long as the LLM is still anchored to the same underlying sentence. Falls back to
    hashing the normalized description text (the original C1 behaviour) when no anchors
    are supplied - keeps every existing caller's behaviour unchanged. The "pos:"/"text:"
    prefixes give the two encoding shapes disjoint hash namespaces."""
    if sentence_anchors:
        content_key = "pos:" + ",".join(f"{s}:{o}" for s, o in sentence_anchors)
    else:
        content_key = "text:" + _normalize_claim_text(description)
    basis = f"{source_doc}|{page}|{content_key}|{_normalize_claim_text(str(date))}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"claim_{digest}"


def assign_deterministic_claim_ids(triples: List[Dict[str, Any]], source_doc: str, page: int,
                                   page_rows: Optional[List[Tuple[int, str, bool]]] = None
                                   ) -> List[Dict[str, Any]]:
    """Overwrite claim_id on every SustainabilityClaim entity in `triples` in place,
    discarding whatever the LLM invented. MUST run before triple_list_to_graph, which
    computes node identity (and thus dedup within the page) from claim_id.

    `page_rows` (optional): the page's raw JSONL rows, used to attempt sentence-position
    anchoring per claim before falling back to the text hash. Omitting it (default None)
    reproduces the original C1 behaviour exactly."""
    for t in triples:
        for k in ("subject", "object"):
            ent = t.get(k)
            if isinstance(ent, dict) and ent.get("class") == "SustainabilityClaim":
                props = ent.setdefault("properties", {})
                description = props.get("description", "")
                anchors = match_claim_sentence_anchors(description, page_rows) if page_rows else None
                props["claim_id"] = make_deterministic_claim_id(
                    source_doc, page, description, props.get("date", ""), sentence_anchors=anchors)
    return triples


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


def stamp_source_type(graph: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    """Tag every node/edge with its provenance channel (SYSTEM_DESIGN §3.2).

    `report` (claim side) vs `news` (conduct side). Additive: node props get a
    `source_type` key (the step-3 validator ignores unknown props unless --strict);
    edges get a top-level `source_type`. Mutates and returns `graph`.
    """
    for node in graph.get("nodes", []):
        node.setdefault("properties", {})["source_type"] = source_type
    for edge in graph.get("edges", []):
        edge["source_type"] = source_type
    return graph


def stamp_provenance(graph: Dict[str, Any], doc_stem: str, page: int, source: str,
                     article_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stamp deterministic source provenance on claim/evidence nodes (not T1 entities).

    The extractor knows exactly which document and page it is processing, so claim and
    evidence nodes get `source_doc`/`source_page` here rather than relying on the LLM's
    free-text `source`. For `--source news`, the article's title/url/domain (from
    `load_news_doc_meta`) ride along so the UI can cite the article by name.
    `provenance_method="extraction"` marks these as ground truth — the offline patch
    (step05b) never overwrites them. Mutates and returns `graph`.
    """
    for node in graph.get("nodes", []):
        if node.get("class") not in PROVENANCE_CLASSES:
            continue
        props = node.setdefault("properties", {})
        props["source_doc"] = doc_stem
        props["source_page"] = int(page)
        props["provenance_method"] = "extraction"
        if source == "news" and article_meta:
            for src_key, dst_key in (("title", "article_title"), ("url", "article_url"),
                                     ("source_domain", "source_domain")):
                v = article_meta.get(src_key)
                if v:
                    props[dst_key] = v
    return graph


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


def _year_int(*candidates: Any) -> Optional[int]:
    """First 4-digit year found among the candidates (int or string)."""
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, int) and c:
            return c
        m = re.search(r"(?:19|20)\d{2}", str(c))
        if m:
            return int(m.group(0))
    return None


def load_news_doc_meta(path: Path) -> Dict[str, Dict[str, Any]]:
    """First-seen article metadata per source_pdf, for `--source news`.

    Reads the P1-preprocessed news JSONL (`publish_date_normalized`, `publish_year`,
    `date_uncertain`, ...). All rows of one article share these fields, so the first
    surviving row is representative. `load_pages_from_jsonl` is left untouched (step 1
    depends on its signature); this is a separate, additive reader over the same file.
    """
    meta: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            src = row.get("source_pdf", "unknown")
            if src in meta:
                continue
            year = _year_int(
                row.get("publish_year"),
                row.get("publish_date_normalized"),
                row.get("publish_date"),
                row.get("date_crawled"),
            ) or datetime.now().year
            meta[src] = {
                "company": row.get("company") or row.get("ticker") or "",
                "ticker": row.get("ticker", ""),
                "year": year,
                "source_domain": row.get("source_domain", ""),
                "url": row.get("url", ""),
                "title": row.get("title", ""),
                "publish_date": row.get("publish_date_normalized") or row.get("publish_date") or "",
                "date_uncertain": bool(row.get("date_uncertain", False)),
            }
    return meta


# --------------------------------------------------------------------------- #
# LLM call (verbatim semantics, simplified for a single client).
# --------------------------------------------------------------------------- #
def call_llm(prompt: str, client: Any, client_idx: int,
             rate_limiter: RateLimiter, schema: Dict[str, Any], model: str,
             retries: int = 3) -> Tuple[Any, str, bool]:
    """`client` is a `genai.Client`."""
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
                 client: Any, client_idx: int, rate_limiter: RateLimiter,
                 schema: Dict[str, Any], model: str, esg_only: bool,
                 pdf_stem: str, dbg_pdf_dir: Path, g_pdf_dir: Path,
                 company: str, year: int,
                 source: str = "report", article_meta: Optional[Dict[str, Any]] = None,
                 page_rows: Optional[List[Tuple[int, str, bool]]] = None) -> Tuple[int, bool, bool]:
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
    prompt = build_page_prompt(schema, page_text, p_no, page_kpis, company=company, year=year,
                               source=source, article_meta=article_meta)

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
                entities, edge_labels, _ = load_schema_sets(schema)
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

                if valid_triples:
                    assign_deterministic_claim_ids(valid_triples, pdf_stem, p_no, page_rows=page_rows)
                graph = (triple_list_to_graph(valid_triples, schema)
                         if valid_triples else {"nodes": [], "edges": []})
                stamp_source_type(graph, source)
                stamp_provenance(graph, pdf_stem, p_no, source, article_meta)
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
                     client: Any, rate_limiter: RateLimiter,
                     esg_only: bool, max_workers: int,
                     source: str = "report", doc_meta: Optional[Dict[str, Any]] = None
                     ) -> Tuple[int, int]:
    if source == "news":
        # news source_pdf is an id like "AAA__vietstock.vn__<hash>" (no .pdf); do NOT
        # os.path.splitext it - that would strip ".vn__<hash>" and collapse every article
        # from one domain into a single dir. Company/year come from the article metadata.
        pdf_stem = source_pdf
        meta = doc_meta or {}
        company = meta.get("company") or meta.get("ticker") or source_pdf
        year = int(meta.get("year") or datetime.now().year)
    else:
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

    logger.info(f"=== Processing {source_pdf} [{source}] - {company} ({year}) - {len(pages)} pages ===")

    article_meta = doc_meta if source == "news" else None
    success = 0
    failed = 0
    rate_limited = 0
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(
                process_page, pg, page_kpi_map.get(pg["page"], []),
                client, 0, rate_limiter, schema, model, esg_only,
                pdf_stem, dbg_pdf_dir, g_pdf_dir, company, year,
                source, article_meta,
                jsonl_pages.get(pg["page"], []),
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
# Offline preview (no LLM, no writes) - verify --source/meta/prompt for free.
# --------------------------------------------------------------------------- #
def dry_run_preview(selected: List[str], docs: Dict[str, Any], schema: Dict[str, Any],
                    esg_only: bool, source: str, news_meta: Dict[str, Dict[str, Any]],
                    kpi_dir: Path) -> None:
    print(f"\nDRY RUN [{source}] - no Gemini calls, nothing written.\n")
    for src in selected:
        pages = pages_for_doc(docs[src])
        esg_pages = [p for p in pages if p["has_esg"]]
        to_send = esg_pages if esg_only else [p for p in pages if p["text"]]

        if source == "news":
            meta: Optional[Dict[str, Any]] = news_meta.get(src, {})
            stem = src
            company = meta.get("company") or meta.get("ticker") or src
            year = int(meta.get("year") or datetime.now().year)
            extra = (f"  domain={meta.get('source_domain', '')}  date={meta.get('publish_date', '')}"
                     f"{' (uncertain)' if meta.get('date_uncertain') else ''}")
        else:
            meta = None
            stem = os.path.splitext(src)[0]
            company, year_str = parse_company_year_from_filename(src)
            try:
                year = int(year_str)
            except ValueError:
                year = 2024
            extra = ""

        print(f"=== {src}  [{source}] ===")
        print(f"  stem={stem}  company={company!r}  year={year}{extra}")
        print(f"  pages={len(pages)}  esg_pages={len(esg_pages)}  will_send={len(to_send)}")

        page_kpis = load_kpis_for_doc(stem, kpi_dir)
        sample = to_send[0] if to_send else None
        if sample:
            prompt = build_page_prompt(
                schema, sample["text"], sample["page"], page_kpis.get(sample["page"], []),
                company=company, year=year, source=source, article_meta=meta,
            )
            print(f"  --- prompt sample (page {sample['page']}, {len(prompt)} chars, first 1200) ---")
            print("  " + prompt[:1200].replace("\n", "\n  "))
        print()


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
    parser.add_argument("--source", choices=["report", "news"], default="report",
                        help="report (default): company self-reporting -> claim side. "
                             "news: third-party news -> conduct side; uses the news prompt and "
                             "stamps source_type=news (input: P1-preprocessed news JSONL).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Offline preview: list selected docs, ESG page counts and a prompt "
                             "sample. No Gemini calls, no API key needed, nothing written.")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input JSONL not found: {args.input}")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    entities, edges, _ = load_schema_sets(schema)
    logger.info(f"Schema loaded: {len(entities)} entity classes, {len(edges)} edge labels")

    docs = load_pages_from_jsonl(args.input)
    selected = select_documents(docs, args)
    if not selected:
        return

    # news: per-article metadata (company/year/domain/title) alongside the page text.
    news_meta = load_news_doc_meta(args.input) if args.source == "news" else {}
    esg_only = not args.all_pages

    if args.dry_run:
        dry_run_preview(selected, docs, schema, esg_only, args.source, news_meta, args.kpi_dir)
        return

    load_dotenv(REPO_ROOT / ".env")
    rate_limiter = RateLimiter(max_calls_per_minute=args.rate_limit)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}")
        return
    client = genai.Client(api_key=api_key)
    model = args.model

    total_success = 0
    total_failed = 0
    for src in selected:
        s, f = process_document(
            src, docs[src],
            args.kpi_dir, args.out_dir, schema, model,
            client, rate_limiter, esg_only=esg_only, max_workers=args.max_workers,
            source=args.source, doc_meta=news_meta.get(src),
        )
        total_success += s
        total_failed += f
    logger.info(
        f"Done [{args.source}]. {total_success} page(s) succeeded, {total_failed} failed "
        f"across {len(selected)} doc(s) -> {args.out_dir}"
    )


if __name__ == "__main__":
    main()
