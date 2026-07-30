#!/usr/bin/env python3
"""Behaviour tests for the standards-registry audit that replaces step04b's graph scan.

WHY THIS EXISTS
step04b used to READ graph_output/resolved/resolved_graph.json — step05's output — while
step05 reads the registry step04b writes. A dependency cycle: on a bare clone the stage
could not run at all. And the scan earned nothing: every alias in the committed registry
is a hardcoded SEED, so the only thing it ever produced was a to-review list.

So the registry becomes static config (nobody generates it) and the to-review list becomes
an AUDIT inside step00, the offline diagnostic stage — same family as the P1 identity lint.
The cycle disappears because step00 reports on a graph instead of feeding one.

THE THING THE AUDIT MUST NOT LOSE
The graph holds ~432 Standard/Regulation nodes and only ~10 of them are the five reference
documents; the rest are accounting standards, ISO certificates and tax circulars that are
deliberately out of scope. A naive "not in the registry" list would be ~420 lines of noise.
That is why the per-document match patterns survive the move: the audit reports only a
mention that LOOKS LIKE one of the five documents but is not yet covered.

Offline: no LLM, no Neo4j, no network, no artifacts on disk — the graph here is synthetic
so the assertions stay true after any re-extraction.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone and
`test_esg_kg_equivalence.py` already proved the two agreed on this exact behaviour.

    python test/test_standards_audit.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.report import quality as new_quality  # noqa: E402

# A registry shaped like config/standards_registry.json after the move: the match patterns
# and exclude hints that used to live in step04b's SEEDS now ride along in the config.
REGISTRY = {
    "GRI": {
        "canonical_name": "GRI Standards",
        "kind": "Standard",
        "aliases": ["GRI Standards", "Global Reporting Initiative"],
        "exclusions": [{"name": "GRI 305-1", "reason": "an indicator, not the document"}],
        "match_patterns": [r"\bgri\b|global reporting"],
        "exclude_hints": [],
    },
    "TT96": {
        "canonical_name": "Thông tư 96/2020/TT-BTC",
        "kind": "Regulation",
        "aliases": ["Thông tư 96/2020/TT-BTC"],
        "exclusions": [],
        "match_patterns": [r"96\s*/\s*2020"],
        "exclude_hints": ["ke toan"],
    },
}


def graph(names_with_degree):
    """Build a {nodes, edges} graph whose Standard/Regulation nodes have the given degrees."""
    nodes, edges = [], []
    for name, cls, degree in names_with_degree:
        idx = len(nodes)
        nodes.append({"class": cls, "properties": {"name": name}})
        for _ in range(degree):
            other = len(nodes)
            nodes.append({"class": "Organization", "properties": {"name": f"org{other}"}})
            edges.append({"subject": idx, "predicate": "adoptsStandard", "object": other})
    return nodes, edges


def audit(nodes, edges, registry=None, **kw):
    reg = REGISTRY if registry is None else registry
    return new_quality.standards_registry_audit(nodes, edges, reg, **kw)


def uncovered_names(result):
    return {u["name"] for u in result["uncovered"]}


def test_an_unregistered_spelling_of_a_known_document_is_reported():
    """The whole point: a GRI variant nobody has curated yet must surface."""
    nodes, edges = graph([("GRI Sustainability Reporting Standards", "Standard", 3)])
    result = audit(nodes, edges)
    assert uncovered_names(result) == {"GRI Sustainability Reporting Standards"}, result
    entry = result["uncovered"][0]
    assert entry["doc_key"] == "GRI", entry
    assert entry["degree"] == 3, entry


def test_an_unrelated_standard_is_not_reported():
    """The noise filter. Without it the audit prints ~420 out-of-scope documents and
    nobody reads it — the reason the per-document patterns had to survive the move."""
    nodes, edges = graph([
        ("Chuẩn mực Kế toán Việt Nam", "Standard", 5),
        ("QCVN 40:2011/BTNMT", "Standard", 2),
        ("ISO 14001", "Standard", 4),
    ])
    result = audit(nodes, edges)
    assert result["uncovered"] == [], result


def test_a_curated_exclusion_stays_excluded():
    """A human already ruled on this name; the audit must not re-open it every run."""
    nodes, edges = graph([("GRI 305-1", "Standard", 9)])
    result = audit(nodes, edges)
    assert result["uncovered"] == [], result


def test_the_canonical_name_is_never_reported_as_unknown():
    """step04b's own feedback artifact, fixed here.

    step04b flagged `canonical_name` itself as a name needing review: it writes that name
    into the registry, step05 stamps it onto the merged node, and the next scan reads it
    back as an unrecognised mention. The registry's canonical name is BY DEFINITION covered.
    """
    nodes, edges = graph([("GRI Standards", "Standard", 21),
                          ("Thông tư 96/2020/TT-BTC", "Regulation", 12)])
    result = audit(nodes, edges)
    assert result["uncovered"] == [], result
    assert result["covered_mentions"] == 2, result


def test_exclude_hints_keep_a_lookalike_out():
    """`96/2020` also appears in accounting circulars; the hint is what tells them apart."""
    nodes, edges = graph([("Chuẩn mực ke toan số 96/2020", "Standard", 4)])
    result = audit(nodes, edges)
    assert result["uncovered"] == [], result


def test_suggestion_follows_how_load_bearing_the_mention_is():
    """A mention wired into the graph is worth curating; a stray one probably is not."""
    nodes, edges = graph([("GRI Standard", "Standard", 7),
                          ("Global Reporting Initiative (GRI)", "Standard", 1)])
    result = audit(nodes, edges, min_degree=2)
    by_name = {u["name"]: u["suggest"] for u in result["uncovered"]}
    assert by_name == {"GRI Standard": "include",
                       "Global Reporting Initiative (GRI)": "exclude"}, by_name


def test_uncovered_is_ordered_by_degree_so_the_top_of_the_list_matters_most():
    nodes, edges = graph([("GRI Standard", "Standard", 2),
                          ("Global Reporting Initiative (GRI)", "Standard", 8)])
    result = audit(nodes, edges)
    assert [u["name"] for u in result["uncovered"]] == [
        "Global Reporting Initiative (GRI)", "GRI Standard"], result


def test_a_registry_without_patterns_reports_nothing_instead_of_everything():
    """Failure mode that matters: config missing `match_patterns` must degrade to silence,
    never to a 400-line dump that trains people to ignore the section."""
    reg = {"GRI": {"canonical_name": "GRI Standards", "kind": "Standard",
                   "aliases": ["GRI Standards"], "exclusions": []}}
    nodes, edges = graph([("GRI Sustainability Reporting Standards", "Standard", 3),
                          ("Chuẩn mực Kế toán Việt Nam", "Standard", 5)])
    result = audit(nodes, edges, registry=reg)
    assert result["uncovered"] == [], result


def test_one_mention_is_claimed_by_at_most_one_document():
    nodes, edges = graph([("GRI Sustainability Reporting Standards", "Standard", 3)])
    result = audit(nodes, edges)
    assert len(result["uncovered"]) == 1, result


def test_the_real_registry_is_shaped_the_way_the_audit_expects():
    """config/standards_registry.json is now static config — nothing regenerates it, so a
    hand-edit that drops `match_patterns` would silently blind the audit."""
    import json
    reg = json.loads((REPO / "config" / "standards_registry.json").read_text(encoding="utf-8"))
    assert set(reg) == {"TT96", "GRI", "SSCIFC", "QD2171", "QCVN09"}, sorted(reg)
    for key, entry in reg.items():
        assert entry.get("canonical_name"), key
        assert entry.get("kind") in ("Standard", "Regulation"), key
        assert entry.get("aliases"), key
        assert entry.get("match_patterns"), f"{key} has no match_patterns — audit goes blind"
        assert isinstance(entry.get("exclude_hints", []), list), key


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed.")
