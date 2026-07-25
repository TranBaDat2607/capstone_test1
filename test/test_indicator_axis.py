#!/usr/bin/env python3
"""
Stage-level tests for the TT96/GRI indicator axis (docs/STANDARD_INDICATOR_AXIS.md).

test_temporal_invariants.py covers the axis at the helper level (GraphPatch.add_edge,
doc_key_for, the keyword tier). The rules that decide what the axis MEANS live inside
step05c's run(), which nothing exercised: the self-reported-zero Penalty rule, the
kpi_id-not-kpi_type boundary, and the confirmed-crosswalk gate. This file drives the
real run() over a temporary workspace so those rules are covered end to end -- which
also gets the stage-level append-only and idempotency invariants for free.

Offline: no LLM, no Neo4j, no network, no writes outside a temp dir.

    python test/test_indicator_axis.py
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from step03c_canonicalize_kpis import Matcher, canonicalize_kpis  # noqa: E402
from step05c_link_standard_indicators import run  # noqa: E402

SCHEMA_PATH = REPO / "config" / "schema.json"
DEFS_PATH = REPO / "kpi_definitions_construction.json"
ALIASES_PATH = REPO / "config" / "kpi_type_aliases.json"

_ALL_DEFS = json.loads(DEFS_PATH.read_text(encoding="utf-8"))
DEFS = [d for d in _ALL_DEFS if d["id"] in ("TT96-6.1.1", "TT96-6.5.1", "TT96-6.5.2")]
assert len(DEFS) == 3, "fixture expects these three indicators to exist in the definitions"


def props(node: dict) -> dict:
    return node.get("properties", {})


def mini_graph() -> dict:
    """One node per rule under test, in a fixed order so append-only can be checked."""
    def n(cls, **p):
        p.setdefault("valid_from", "2023")
        p.setdefault("valid_to", None)
        p.setdefault("is_current", True)
        return {"class": cls, "properties": p}

    return {
        "nodes": [
            # 0: canonicalized by step03c -> must link
            n("KPIObservation", kpi_id="TT96-6.1.1", kpi_type="GHG emissions",
              title="Tổng phát thải KNK", value=12450, unit="tCO2e", source_type="report"),
            # 1: standard code sits in kpi_type but step03c never ran -> must NOT link
            n("KPIObservation", kpi_type="TT96-6.1.1", title="Phát thải chưa canonical",
              source_type="report"),
            # 2: self-reported "fined 0 times" -> a compliance claim, NOT conduct
            n("Penalty", penalty_id="AAA_2022_EnvPenalty_0times", amount=0,
              description="Số lần bị phạt vi phạm môi trường"),
            # 3: a real fine -> genuine conduct evidence
            n("Penalty", penalty_id="AAA_2023_EnvPenalty", amount=150_000_000,
              description="Xử phạt xả thải vượt chuẩn", source_type="news"),
            # 4: GHG observation -> TT96-6.1.1
            n("Emission", category="Scope 1", scope="1", value=8000, unit="tCO2e"),
        ],
        "edges": [],
    }


def crosswalk_doc() -> dict:
    """Both review states, so the gate is tested in both directions."""
    return {
        "version": "test",
        "confirmed": [
            {"tt96": "TT96-6.1.1", "gri": ["GRI 305-1"], "gri_name": "Direct GHG",
             "status": "needs_review"},
            {"tt96": "TT96-6.5.1", "gri": ["GRI 2-27"], "gri_name": "Compliance",
             "status": "confirmed"},
        ],
        "needs_review": [],
    }


class Workspace:
    """A temp dir holding graph + defs + crosswalk, and a run() invocation over them."""

    def __init__(self, graph=None, crosswalk=None):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_axis_"))
        self.graph_path = self.dir / "resolved_graph.json"
        self.defs_path = self.dir / "defs.json"
        self.crosswalk_path = self.dir / "crosswalk.json"
        self.stats_path = self.dir / "stats.json"
        self._write(self.graph_path, graph if graph is not None else mini_graph())
        self._write(self.defs_path, DEFS)
        self._write(self.crosswalk_path, crosswalk if crosswalk is not None else crosswalk_doc())

    @staticmethod
    def _write(path: Path, obj) -> None:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    def run(self, **overrides):
        args = argparse.Namespace(
            input=self.graph_path, defs=self.defs_path, crosswalk=self.crosswalk_path,
            schema=SCHEMA_PATH, no_gri=False, no_align=False,
            trust_draft_crosswalk=False, stats_out=self.stats_path, dry_run=False,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        run(args)
        return self.graph

    @property
    def graph(self) -> dict:
        return json.loads(self.graph_path.read_text(encoding="utf-8"))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def edges_of(graph: dict, label: str, source_idx: int = None) -> list:
    out = [e for e in graph["edges"] if e.get("predicate") == label]
    if source_idx is not None:
        out = [e for e in out if e.get("subject") == source_idx]
    return out


def indicator_id_at(graph: dict, idx: int):
    return props(graph["nodes"][idx]).get("id")


# --------------------------------------------------------------------------- #
# The rule that keeps the signal from flipping sign (§5.3 step 5)
# --------------------------------------------------------------------------- #
def test_self_reported_zero_penalty_gets_no_conduct_edge():
    """"Fined 0 times" is a company boasting, not evidence against it.

    Linking it as conduct would make a self-congratulation count as a violation --
    the one failure mode here that makes the system conclude the OPPOSITE of the
    truth, rather than merely miss something.
    """
    ws = Workspace()
    try:
        g = ws.run()
        p = props(g["nodes"][2])
        assert p.get("self_reported_zero") is True, p
        assert edges_of(g, "measuredUnder", source_idx=2) == [], \
            "a self-reported zero penalty must not be linked as conduct evidence"
        stats = json.loads(ws.stats_path.read_text(encoding="utf-8"))
        assert stats["penalty_self_reported_zero"] == 1, stats
    finally:
        ws.close()


def test_real_penalty_does_get_a_conduct_edge():
    """The other branch. Without it, an implementation that never links any Penalty
    would pass the test above and silently destroy the conduct side."""
    ws = Workspace()
    try:
        g = ws.run()
        linked = edges_of(g, "measuredUnder", source_idx=3)
        assert len(linked) == 1, linked
        assert indicator_id_at(g, linked[0]["object"]) == "TT96-6.5.2"
        assert "self_reported_zero" not in props(g["nodes"][3])
    finally:
        ws.close()


# --------------------------------------------------------------------------- #
# The step03c / step05c boundary
# --------------------------------------------------------------------------- #
def test_measured_under_reads_kpi_id_and_never_guesses_from_kpi_type():
    """step05c consumes the canonical kpi_id step03c assigned; it must not re-derive
    an indicator from raw kpi_type. Keeping the boundary sharp is what makes a bad
    mapping traceable to step03c instead of ambiguous between two stages."""
    ws = Workspace()
    try:
        g = ws.run()
        # node 0 carries kpi_id -> linked
        linked = edges_of(g, "measuredUnder", source_idx=0)
        assert len(linked) == 1 and indicator_id_at(g, linked[0]["object"]) == "TT96-6.1.1"
        # node 1 carries the same code in kpi_type only -> NOT linked
        assert edges_of(g, "measuredUnder", source_idx=1) == [], \
            "step05c must not infer an indicator from kpi_type"
    finally:
        ws.close()


def test_emission_links_to_the_ghg_indicator():
    ws = Workspace()
    try:
        g = ws.run()
        linked = edges_of(g, "measuredUnder", source_idx=4)
        assert len(linked) == 1 and indicator_id_at(g, linked[0]["object"]) == "TT96-6.1.1"
    finally:
        ws.close()


def test_step03c_assigns_kpi_id_without_ever_rewriting_kpi_type():
    """kpi_type is part of KPIObservation.identity_keys. Rewriting it would change
    node identity, reorder the resolved graph, and invalidate the positional
    node_index references in the paid step07 dossiers."""
    matcher = Matcher(_ALL_DEFS, json.loads(ALIASES_PATH.read_text(encoding="utf-8")))
    triples = [{
        "subject": {"class": "KPIObservation",
                    "properties": {"kpi_type": "Male employees", "title": "Male employees",
                                   "unit": "người", "value": 120, "year": 2023}},
        "predicate": "reportsKPI",
        "object": {"class": "Organization", "properties": {"name": "AAA"}},
    }]
    canonicalize_kpis(triples, matcher)
    p = triples[0]["subject"]["properties"]
    assert p["kpi_type"] == "Male employees", "kpi_type must survive canonicalization untouched"
    assert p["kpi_id"] == "SSCIFC-S6", p


# --------------------------------------------------------------------------- #
# The human-review gate on the GRI crosswalk
# --------------------------------------------------------------------------- #
def test_gri_edges_only_come_from_confirmed_crosswalk_rows():
    """Every row in config/standard_crosswalk.json is still needs_review, so this gate
    is the only thing keeping unreviewed mappings out of the base graph."""
    ws = Workspace()
    try:
        g = ws.run()
        eq = edges_of(g, "equivalentTo")
        targets = {indicator_id_at(g, e["object"]) for e in eq}
        assert targets == {"GRI 2-27"}, f"only the confirmed row may emit an edge, got {targets}"
    finally:
        ws.close()


def test_trust_draft_crosswalk_opens_the_gate_explicitly():
    ws = Workspace()
    try:
        g = ws.run(trust_draft_crosswalk=True)
        targets = {indicator_id_at(g, e["object"]) for e in edges_of(g, "equivalentTo")}
        assert targets == {"GRI 305-1", "GRI 2-27"}, targets
    finally:
        ws.close()


def test_no_gri_skips_the_axis_entirely():
    ws = Workspace()
    try:
        g = ws.run(no_gri=True)
        assert edges_of(g, "equivalentTo") == []
    finally:
        ws.close()


# --------------------------------------------------------------------------- #
# Stage-level invariants the dossiers depend on
# --------------------------------------------------------------------------- #
def test_stage_is_append_only_and_preserves_node_order():
    """step06 keys Neo4j nodes by array index and the step07 dossiers reference nodes
    by node_index, so a reorder silently corrupts the paid advisory layer. The existing
    helper-level test compares class names; this compares the full property payload of
    every original node, which also catches a node being replaced by a different one of
    the same class."""
    ws = Workspace()
    try:
        before = ws.graph["nodes"]
        after = ws.run()["nodes"]
        assert len(after) > len(before), "the stage should have appended indicator nodes"
        for i, original in enumerate(before):
            assert after[i]["class"] == original["class"], f"node {i} changed class"
            for k, v in props(original).items():
                # step05c may ADD properties (self_reported_zero) but never change one
                assert props(after[i])[k] == v, f"node {i} property {k!r} was mutated"
    finally:
        ws.close()


def test_stage_is_idempotent():
    """Re-running is part of the normal workflow (any step05 re-run forces it), so a
    second pass must not duplicate nodes or edges."""
    ws = Workspace()
    try:
        first = ws.run()
        second = ws.run()
        assert len(second["nodes"]) == len(first["nodes"]), "nodes duplicated on re-run"
        assert len(second["edges"]) == len(first["edges"]), "edges duplicated on re-run"
        assert second == first
    finally:
        ws.close()


def test_indicator_nodes_are_all_anchored_to_a_document():
    """A dangling indicator cannot answer the TT96-compliance query, which is one of
    the two analyses the whole axis exists for."""
    ws = Workspace()
    try:
        g = ws.run()
        part_of_sources = {e["subject"] for e in edges_of(g, "partOf")}
        for i, node in enumerate(g["nodes"]):
            if node["class"] == "StandardIndicator" and str(props(node).get("id", "")).startswith("TT96-"):
                assert i in part_of_sources, f"indicator {props(node)['id']} has no partOf edge"
    finally:
        ws.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
