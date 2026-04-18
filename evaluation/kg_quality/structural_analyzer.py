"""
evaluation.kg_quality.structural_analyzer

Module 2 — Structural Quality Analyzer.

Measures graph topology health using standard graph-theory metrics.
Zero LLM cost, zero ground-truth requirements.

Metrics produced:
    M2.1  Orphan Node Rate             (ONR)
    M2.2  Weakly Connected Components  (WCC)
    M2.3  Graph Density
    M2.4  Average Node Degree by Type
    M2.5  Indicator Coverage Rate      (ICR)
    M2.6  Mandatory Indicator Coverage (MIC)
    M2.7  Confidence Distribution
    M2.8  Hub Analysis
"""
from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx

from config import Config
from kg.graph_store import KnowledgeGraph

logger = logging.getLogger(__name__)


class StructuralAnalyzer:
    """Analyze KG topology and structural health."""

    def __init__(
        self,
        kg: KnowledgeGraph,
        indicators_path: str | Path | None = None,
    ) -> None:
        self._kg = kg
        self._g: nx.MultiDiGraph = kg._graph  # noqa: SLF001
        self._indicators_path = (
            Path(indicators_path)
            if indicators_path
            else Config.ONTOLOGY_DIR / "framework_indicators.json"
        )

    # ── helpers ────────────────────────────────────────────────────────

    def _load_mandatory_map(self) -> dict[str, list[str]]:
        """Return {indicator_id: [regulation_ids]} for mandatory indicators."""
        try:
            with open(self._indicators_path, encoding="utf-8") as f:
                catalog = json.load(f)
            indicators = catalog.get("indicators", catalog)
            if isinstance(indicators, dict):
                indicators = list(indicators.values())
            result: dict[str, list[str]] = {}
            for ind in indicators:
                mf = ind.get("mandatory_for", [])
                if mf:
                    result[ind["indicator_id"]] = mf
            return result
        except Exception:
            logger.warning("Could not load indicators for mandatory coverage.", exc_info=True)
            return {}

    # ── metrics ────────────────────────────────────────────────────────

    def _orphan_node_rate(self) -> tuple[float, list[str]]:
        """M2.1 — fraction of nodes with zero degree."""
        total = self._g.number_of_nodes()
        if total == 0:
            return 0.0, []
        orphans = [n for n, d in self._g.degree() if d == 0]
        return round(len(orphans) / total, 4), orphans

    def _connected_components(self) -> tuple[int, int, list[int]]:
        """M2.2 — weakly connected component count + sizes."""
        components = list(nx.weakly_connected_components(self._g))
        sizes = sorted([len(c) for c in components], reverse=True)
        largest = sizes[0] if sizes else 0
        return len(components), largest, sizes

    def _graph_density(self) -> float:
        """M2.3 — |E| / (|V| * (|V| - 1))."""
        v = self._g.number_of_nodes()
        e = self._g.number_of_edges()
        if v <= 1:
            return 0.0
        return round(e / (v * (v - 1)), 4)

    def _avg_degree_by_type(self) -> tuple[dict[str, dict[str, float]], list[dict]]:
        """M2.4 — average in/out degree per node type + flagged nodes."""
        type_degrees: dict[str, list[tuple[int, int]]] = {}
        for node_id, data in self._g.nodes(data=True):
            ntype = data.get("node_type", "Unknown")
            in_d = self._g.in_degree(node_id)
            out_d = self._g.out_degree(node_id)
            type_degrees.setdefault(ntype, []).append((in_d, out_d))

        result: dict[str, dict[str, float]] = {}
        for ntype, degrees in type_degrees.items():
            avg_in = sum(d[0] for d in degrees) / len(degrees)
            avg_out = sum(d[1] for d in degrees) / len(degrees)
            result[ntype] = {"in": round(avg_in, 4), "out": round(avg_out, 4)}

        # Flag nodes below expected minimums
        expected_min = {"Claim": ("out", 2), "Indicator": ("in", 1), "Company": ("total", 3)}
        flagged: list[dict] = []
        for node_id, data in self._g.nodes(data=True):
            ntype = data.get("node_type", "Unknown")
            if ntype not in expected_min:
                continue
            direction, minimum = expected_min[ntype]
            if direction == "out":
                actual = self._g.out_degree(node_id)
            elif direction == "in":
                actual = self._g.in_degree(node_id)
            else:
                actual = self._g.degree(node_id)
            if actual < minimum:
                flagged.append({
                    "node_id": node_id,
                    "node_type": ntype,
                    "expected_min": f"{direction}>={minimum}",
                    "actual": actual,
                })

        return result, flagged

    def _indicator_coverage_rate(self) -> float:
        """M2.5 — fraction of Indicators with at least one supporting Claim."""
        indicators = self._kg.get_nodes_by_type("Indicator")
        if not indicators:
            return 0.0
        supports_edges = self._kg.get_relations_by_type("supports")
        supported_ids = {e["target_id"] for e in supports_edges}
        covered = sum(1 for i in indicators if i["node_id"] in supported_ids)
        return round(covered / len(indicators), 4)

    def _mandatory_indicator_coverage(self) -> dict[str, float]:
        """M2.6 — per-regulation coverage of mandatory indicators."""
        mandatory_map = self._load_mandatory_map()
        if not mandatory_map:
            return {}

        supports_edges = self._kg.get_relations_by_type("supports")
        supported_ids = {e["target_id"] for e in supports_edges}

        # Group by regulation
        reg_totals: Counter[str] = Counter()
        reg_covered: Counter[str] = Counter()
        for ind_id, regs in mandatory_map.items():
            for reg in regs:
                reg_totals[reg] += 1
                if ind_id in supported_ids:
                    reg_covered[reg] += 1

        return {
            reg: round(reg_covered[reg] / reg_totals[reg], 4)
            for reg in sorted(reg_totals)
        }

    def _confidence_distribution(self) -> dict[str, Any]:
        """M2.7 — statistics over edge confidence_score values."""
        scores: list[float] = []
        for e in self._kg.get_all_edges():
            cs = e.get("properties", {}).get("confidence_score")
            if cs is not None:
                try:
                    scores.append(float(cs))
                except (ValueError, TypeError):
                    pass

        if not scores:
            return {"mean": None, "median": None, "std": None, "histogram": {}}

        buckets = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.9": 0, "0.9-1.0": 0}
        for s in scores:
            if s < 0.3:
                buckets["0.0-0.3"] += 1
            elif s < 0.6:
                buckets["0.3-0.6"] += 1
            elif s < 0.9:
                buckets["0.6-0.9"] += 1
            else:
                buckets["0.9-1.0"] += 1

        return {
            "mean": round(statistics.mean(scores), 4),
            "median": round(statistics.median(scores), 4),
            "std": round(statistics.pstdev(scores), 4),
            "histogram": buckets,
        }

    def _hub_analysis(self, top_k: int = 5) -> list[dict]:
        """M2.8 — top-k nodes by total degree."""
        degree_list = sorted(self._g.degree(), key=lambda x: x[1], reverse=True)
        result: list[dict] = []
        for node_id, deg in degree_list[:top_k]:
            ntype = self._g.nodes[node_id].get("node_type", "Unknown")
            result.append({"node_id": node_id, "node_type": ntype, "degree": deg})
        return result

    # ── public API ─────────────────────────────────────────────────────

    def analyze(self) -> dict[str, Any]:
        """Run all structural quality checks and return a results dict."""
        onr, orphan_ids = self._orphan_node_rate()
        n_components, largest, comp_sizes = self._connected_components()
        density = self._graph_density()
        avg_deg, flagged = self._avg_degree_by_type()
        icr = self._indicator_coverage_rate()
        mic = self._mandatory_indicator_coverage()
        conf_dist = self._confidence_distribution()
        hubs = self._hub_analysis()

        result = {
            "orphan_node_rate": onr,
            "connected_components": n_components,
            "largest_component_size": largest,
            "graph_density": density,
            "indicator_coverage_rate": icr,
            "mandatory_indicator_coverage": mic,
            "confidence_distribution": conf_dist,
            "avg_degree_by_type": avg_deg,
            "top_hubs": hubs,
            "flagged_nodes": flagged,
        }

        logger.info(
            "Structural analysis done — ONR=%.4f  WCC=%d  density=%.4f  ICR=%.4f",
            onr, n_components, density, icr,
        )
        return result
