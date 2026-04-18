"""
evaluation.kg_quality.schema_validator

Module 1 — Schema Conformance Validator.

Checks every node and edge in the KG against the expected ontology types
and required properties.  Zero LLM cost, zero ground-truth requirements.

Metrics produced:
    M1.1  Node Type Validity Rate   (NTVR)
    M1.2  Property Completeness     (PCS)
    M1.3  Edge Type Validity Rate   (ETVR)
    M1.4  Dangling Reference Rate   (DRR)
    M1.5  Claim Type Validity Rate  (CTVR)
    M1.6  Confidence Range Validity (CRV)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import Config
from kg.graph_store import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── Expected schema ──────────────────────────────────────���─────────────

VALID_NODE_TYPES: set[str] = {
    "Company", "Regulation", "Report", "Indicator",
    "Claim", "NewsEvent", "Metric", "DataPoint",
    "Target", "Project",
}

REQUIRED_PROPERTIES: dict[str, set[str]] = {
    "Company":    {"name"},
    "Regulation": {"name"},
    "Report":     {"year"},
    "Indicator":  {"framework", "code", "pillar", "category"},
    "Claim":      {"indicator_id", "claim_type", "claim_text",
                   "confidence_score", "report_id"},
    "NewsEvent":  {"headline", "sentiment"},
}

VALID_EDGE_TYPES: set[str] = {
    "complies_with", "requires", "supports", "extracted_from",
    "maps_to", "contradicted_by", "mentions", "amended_by",
    "has_emission", "targets_reduction", "invests_in",
    "violates", "claims_reduction",
}

VALID_CLAIM_TYPES: set[str] = {"reported", "committed", "aspirational", "qualitative"}


# ── Validator ──────────────────────────────────────────────────────────

class SchemaValidator:
    """Validate KG contents against the expected ontology schema."""

    def __init__(
        self,
        kg: KnowledgeGraph,
        indicators_path: str | Path | None = None,
    ) -> None:
        self._kg = kg
        self._indicators_path = (
            Path(indicators_path)
            if indicators_path
            else Config.ONTOLOGY_DIR / "framework_indicators.json"
        )
        self._indicator_map: dict[str, list[str]] = {}

    # ── helpers ────────────────────────────────────────────────────────

    def _load_indicator_map(self) -> None:
        """Build indicator_id → valid_claim_types mapping."""
        if self._indicator_map:
            return
        try:
            with open(self._indicators_path, encoding="utf-8") as f:
                catalog = json.load(f)
            indicators = catalog.get("indicators", catalog)
            if isinstance(indicators, dict):
                indicators = list(indicators.values())
            for ind in indicators:
                ind_id = ind.get("indicator_id", "")
                vct = ind.get("valid_claim_types", [])
                if ind_id:
                    self._indicator_map[ind_id] = vct
            logger.info("Loaded %d indicators for CTVR check.", len(self._indicator_map))
        except FileNotFoundError:
            logger.warning("Indicators file not found at %s — CTVR will be skipped.", self._indicators_path)
        except Exception:
            logger.warning("Failed to parse indicators file — CTVR will be skipped.", exc_info=True)

    # ── metrics ────────────────────────────────────────────────────────

    def _node_type_validity_rate(self, all_nodes: list[dict]) -> tuple[float, list[dict]]:
        """M1.1 — fraction of nodes with a recognised type."""
        if not all_nodes:
            return 1.0, []
        violations: list[dict] = []
        valid = 0
        for n in all_nodes:
            if n["node_type"] in VALID_NODE_TYPES:
                valid += 1
            else:
                violations.append({"node_id": n["node_id"], "invalid_type": n["node_type"]})
        return round(valid / len(all_nodes), 4), violations

    def _property_completeness(self, all_nodes: list[dict]) -> tuple[dict[str, float], float, list[dict]]:
        """M1.2 — per-type average of required-property presence."""
        per_type: dict[str, float] = {}
        violations: list[dict] = []

        for ntype, required in REQUIRED_PROPERTIES.items():
            nodes = [n for n in all_nodes if n["node_type"] == ntype]
            if not nodes:
                per_type[ntype] = 1.0
                continue
            total_score = 0.0
            for n in nodes:
                props = set(n.get("properties", {}).keys())
                present = required & props
                score = len(present) / len(required)
                total_score += score
                missing = required - present
                if missing:
                    violations.append({"node_id": n["node_id"], "type": ntype, "missing": sorted(missing)})
            per_type[ntype] = round(total_score / len(nodes), 4)

        avg = round(sum(per_type.values()) / max(len(per_type), 1), 4)
        return per_type, avg, violations

    def _edge_type_validity_rate(self, all_edges: list[dict]) -> tuple[float, list[dict]]:
        """M1.3 — fraction of edges with a recognised rel_type."""
        if not all_edges:
            return 1.0, []
        violations: list[dict] = []
        valid = 0
        for e in all_edges:
            if e.get("type", e.get("rel_type", "")) in VALID_EDGE_TYPES:
                valid += 1
            else:
                violations.append({"rel_id": e.get("rel_id"), "invalid_type": e.get("type", e.get("rel_type", ""))})
        return round(valid / len(all_edges), 4), violations

    def _dangling_reference_rate(self, all_nodes: list[dict]) -> float:
        """M1.4 — fraction of stub/Unknown nodes (auto-created by add_relation)."""
        if not all_nodes:
            return 0.0
        dangling = sum(1 for n in all_nodes if n["node_type"] == "Unknown")
        return round(dangling / len(all_nodes), 4)

    def _claim_type_validity_rate(self, all_nodes: list[dict]) -> tuple[float | None, list[dict]]:
        """M1.5 — fraction of Claims whose claim_type matches their Indicator's allowed types."""
        self._load_indicator_map()
        if not self._indicator_map:
            return None, []

        claims = [n for n in all_nodes if n["node_type"] == "Claim"]
        if not claims:
            return 1.0, []

        violations: list[dict] = []
        valid = 0
        for c in claims:
            props = c.get("properties", {})
            ctype = props.get("claim_type", "")
            ind_id = props.get("indicator_id", "")
            allowed = self._indicator_map.get(ind_id, [])
            if not allowed:
                # Indicator unknown — skip
                valid += 1
                continue
            if ctype in allowed:
                valid += 1
            else:
                violations.append({
                    "claim_id": c["node_id"],
                    "claim_type": ctype,
                    "indicator_id": ind_id,
                    "allowed": allowed,
                })
        return round(valid / len(claims), 4), violations

    def _confidence_range_validity(self, all_edges: list[dict]) -> float:
        """M1.6 — fraction of edges whose confidence_score is in [0, 1]."""
        scored = [
            e for e in all_edges
            if "confidence_score" in e.get("properties", {})
        ]
        if not scored:
            return 1.0
        valid = sum(
            1 for e in scored
            if 0.0 <= float(e["properties"]["confidence_score"]) <= 1.0
        )
        return round(valid / len(scored), 4)

    # ── public API ─────────────────────────────────────────────────────

    def validate(self) -> dict[str, Any]:
        """Run all schema conformance checks and return a results dict."""
        stats = self._kg.stats()
        all_nodes: list[dict] = []
        for ntype in stats.get("nodes_by_type", {}):
            all_nodes.extend(self._kg.get_nodes_by_type(ntype))
        # Also grab Unknown stubs
        all_nodes.extend(self._kg.get_nodes_by_type("Unknown"))

        all_edges = self._kg.get_all_edges()

        ntvr, ntvr_violations = self._node_type_validity_rate(all_nodes)
        pcs_per_type, pcs_avg, pcs_violations = self._property_completeness(all_nodes)
        etvr, etvr_violations = self._edge_type_validity_rate(all_edges)
        drr = self._dangling_reference_rate(all_nodes)
        ctvr, ctvr_violations = self._claim_type_validity_rate(all_nodes)
        crv = self._confidence_range_validity(all_edges)

        all_violations = ntvr_violations + pcs_violations + etvr_violations + ctvr_violations

        result = {
            "node_type_validity_rate": ntvr,
            "property_completeness": pcs_per_type,
            "property_completeness_avg": pcs_avg,
            "edge_type_validity_rate": etvr,
            "dangling_reference_rate": drr,
            "claim_type_validity_rate": ctvr,
            "confidence_range_validity": crv,
            "violations": all_violations,
        }

        logger.info(
            "Schema validation done — NTVR=%.4f  PCS=%.4f  ETVR=%.4f  DRR=%.4f  CTVR=%s  CRV=%.4f",
            ntvr, pcs_avg, etvr, drr, ctvr, crv,
        )
        return result
