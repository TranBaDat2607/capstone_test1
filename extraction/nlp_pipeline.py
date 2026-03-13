"""
extraction/nlp_pipeline.py

LLM-based constrained entity and relation extraction from PDF page text.

Given a page of text from an ESG/Annual Report, prompts an LLM to extract
structured entities and relations conforming to the ontology schema v2.0.

Extraction targets per page:
    - Claim        : qualitative ESG assertions ("FPT cam kết giảm 30% carbon...")
    - DataPoint    : quantitative data points with value + unit
    - Metric       : standardised GRI/ISSB metrics
    - Target       : long-term ESG targets / commitments
    - Project      : named ESG initiatives

Output: list of entity dicts + relation dicts (same format as sample_instances.json)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False
    logger.warning("anthropic SDK not installed. NLP pipeline will be unavailable.")


# ---------------------------------------------------------------------------
# Extraction prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert ESG data extraction system specialized in Vietnamese corporate sustainability reports.

Your task is to extract structured ESG entities and relations from report text, strictly following the ontology schema below.

ENTITY TYPES to extract:
1. Claim      - Qualitative positive assertions about ESG performance (e.g., "We commit to net zero by 2050")
2. DataPoint  - Specific quantitative data (value + unit + year extracted from tables or text)
3. Metric     - Standardized GRI/ISSB metrics with gri_code
4. Target     - Long-term ESG goals with target_year
5. Project    - Named ESG initiatives/programs

PILLAR values: "E" (Environment), "S" (Social), "G" (Governance)
SENTIMENT values: "Positive", "Neutral", "Negative"
DATA_TYPE values: "Actual", "Restated", "Estimated"

RELATION TYPES to extract:
- claims_reduction : Company -> Claim  (company makes an ESG claim)
- supported_by     : Claim -> DataPoint (data supports a claim)
- has_emission     : Company -> Metric  (company has a measurable metric)
- targets_reduction: Company -> Target  (company sets a target)
- invests_in       : Company -> Project (company invests in ESG project)

OUTPUT FORMAT (JSON only, no explanation):
{
  "entities": [
    {"id": "CLM_XXX", "type": "Claim", "properties": {"text": "...", "pillar": "E", "sentiment": "Positive", "page_ref": 12, "year": 2023}},
    {"id": "DP_XXX", "type": "DataPoint", "properties": {"description": "...", "value": 1250, "unit": "tonne CO2e", "year": 2023, "page_ref": 12, "data_type": "Actual"}}
  ],
  "relations": [
    {"id": "REL_XXX", "type": "claims_reduction", "source_id": "COMP_XXX", "target_id": "CLM_XXX", "properties": {"year": 2023}, "extracted_at": "2026-03-14", "confidence_score": 0.90, "extraction_method": "LLM_Constraint"}
  ]
}

Rules:
- Only extract information explicitly stated in the text (no inference)
- Use sequential numeric IDs: CLM_001, DP_001, METRIC_001, TGT_001, PRJ_001
- Confidence score: 0.95 for direct quotes, 0.80 for inferred from context
- If no entities found on a page, return {"entities": [], "relations": []}
- Preserve original Vietnamese text in "text" fields
"""

_USER_PROMPT_TEMPLATE = """Extract ESG entities and relations from this report page.

Company ID: {company_id}
Report ID: {report_id}
Page number: {page_number}
Current date for extraction: 2026-03-14

--- PAGE TEXT ---
{page_text}

--- TABLES ON THIS PAGE ---
{table_text}

Extract all ESG Claims, DataPoints, Metrics, Targets, and Projects. Return JSON only."""


class NLPExtractionPipeline:
    """
    LLM-based constrained extraction of ESG entities and relations from PDF pages.

    Parameters
    ----------
    api_key : str | None
        Anthropic API key. If None, reads from ANTHROPIC_API_KEY environment variable.
    model : str
        Claude model to use for extraction.
    company_id : str
        KG company node ID (e.g. "COMP_FPT") — added to extracted relations.
    report_id : str
        KG report node ID (e.g. "RPT_FPT_ESG_2023") — added to extracted_from relations.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        company_id: str = "COMP_UNKNOWN",
        report_id: str = "RPT_UNKNOWN",
    ) -> None:
        self.model = model
        self.company_id = company_id
        self.report_id = report_id
        self._entity_counters: dict[str, int] = {}

        if not _HAS_ANTHROPIC:
            self._client = None
            logger.warning("NLPExtractionPipeline initialized without Anthropic SDK.")
        else:
            self._client = _anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_page(self, page: dict[str, Any]) -> dict[str, Any]:
        """
        Extract entities and relations from a single parsed PDF page.

        Parameters
        ----------
        page : dict
            Output dict from PDFParser.parse() — keys: page_number, text, tables.

        Returns
        -------
        dict
            {entities: list[dict], relations: list[dict]}
        """
        if self._client is None:
            return {"entities": [], "relations": []}

        page_text = page.get("text", "").strip()
        if len(page_text) < 50:
            return {"entities": [], "relations": []}

        # Format tables as text
        table_text = self._tables_to_text(page.get("tables", []))

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            company_id=self.company_id,
            report_id=self.report_id,
            page_number=page.get("page_number", "?"),
            page_text=page_text[:3000],  # Cap to avoid token limits
            table_text=table_text[:1000] if table_text else "(none)",
        )

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text.strip()
            result = self._parse_json_response(raw)
            result = self._add_provenance(result, page.get("page_number", 0))
            return result
        except Exception as e:
            logger.warning("Extraction failed for page %s: %s", page.get("page_number"), e)
            return {"entities": [], "relations": []}

    def extract_from_pages(self, pages: list[dict]) -> dict[str, Any]:
        """
        Extract entities and relations from all pages of a parsed PDF.

        Deduplicates entity IDs across pages using sequential counters.

        Returns
        -------
        dict
            {entities: list[dict], relations: list[dict]}  (merged across all pages)
        """
        all_entities: list[dict] = []
        all_relations: list[dict] = []
        self._entity_counters = {}

        for page in pages:
            result = self.extract_from_page(page)
            # Remap IDs to avoid cross-page collisions
            remapped = self._remap_ids(result)
            all_entities.extend(remapped["entities"])
            all_relations.extend(remapped["relations"])

        logger.info(
            "Extracted %d entities, %d relations from %d pages",
            len(all_entities), len(all_relations), len(pages),
        )
        return {"entities": all_entities, "relations": all_relations}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json_response(self, raw: str) -> dict:
        """Extract JSON from LLM response, handling markdown code fences."""
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract the first JSON object/array
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except json.JSONDecodeError:
                    logger.debug("Could not parse JSON from: %s", raw[:200])
                    return {"entities": [], "relations": []}
            else:
                return {"entities": [], "relations": []}

        if not isinstance(data, dict):
            return {"entities": [], "relations": []}

        return {
            "entities": data.get("entities", []) if isinstance(data.get("entities"), list) else [],
            "relations": data.get("relations", []) if isinstance(data.get("relations"), list) else [],
        }

    def _add_provenance(self, result: dict, page_number: int) -> dict:
        """Add extracted_from relations for each entity back to the report."""
        new_relations = list(result.get("relations", []))
        for entity in result.get("entities", []):
            etype = entity.get("type", "")
            if etype in ("Claim", "DataPoint", "Metric"):
                new_relations.append({
                    "id": f"REL_EXT_{entity['id']}",
                    "type": "extracted_from",
                    "source_id": entity["id"],
                    "target_id": self.report_id,
                    "properties": {"page_number": page_number},
                    "extracted_at": "2026-03-14",
                    "confidence_score": 1.0,
                    "extraction_method": "RE_Model",
                })
        result["relations"] = new_relations
        return result

    def _remap_ids(self, result: dict) -> dict:
        """Remap entity IDs to be globally unique across pages."""
        id_map: dict[str, str] = {}

        new_entities = []
        for entity in result.get("entities", []):
            old_id = entity.get("id", "")
            prefix = old_id.split("_")[0] if "_" in old_id else old_id
            count = self._entity_counters.get(prefix, 0) + 1
            self._entity_counters[prefix] = count
            new_id = f"{prefix}_{count:03d}"
            id_map[old_id] = new_id
            new_entity = dict(entity)
            new_entity["id"] = new_id
            new_entities.append(new_entity)

        new_relations = []
        for rel in result.get("relations", []):
            new_rel = dict(rel)
            new_rel["source_id"] = id_map.get(rel.get("source_id", ""), rel.get("source_id", ""))
            new_rel["target_id"] = id_map.get(rel.get("target_id", ""), rel.get("target_id", ""))
            old_rel_id = rel.get("id", "")
            prefix = old_rel_id.split("_")[0] + "_" + old_rel_id.split("_")[1] if "_" in old_rel_id else old_rel_id
            count = self._entity_counters.get(prefix, 0) + 1
            self._entity_counters[prefix] = count
            new_rel["id"] = f"{prefix}_{count:03d}"
            new_relations.append(new_rel)

        return {"entities": new_entities, "relations": new_relations}

    @staticmethod
    def _tables_to_text(tables: list[dict]) -> str:
        """Convert extracted tables to pipe-delimited text for the prompt."""
        lines = []
        for i, table in enumerate(tables, 1):
            lines.append(f"[Table {i}]")
            for row in table.get("rows", []):
                lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)
