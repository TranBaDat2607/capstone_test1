#!/usr/bin/env python3
"""
Offline test for test3/graph_rag_arm.py — the Graph-RAG retrieval arm.

No LLM, no Neo4j, no network. Synthetic graphs for the behaviour, plus a real-corpus
arm for non-vacuity. Run from the repo root:

    python test3/test_graph_rag_arm.py

The property this file exists to protect: the arm must be the SAME retrieval step07
performs, only run backwards (evidence → claim instead of claim → evidence). If it
quietly becomes a different ranking, the comparison stops measuring Graph-RAG and
starts measuring a lookalike — the exact mistake `evalu/retrieval_eval.py:30-32`
warns about. So the tests pin the two tiers, the gates, and the tier priority.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

from test3.graph_rag_arm import CLAIM_CLASS, INDICATOR_BOOST, GraphArm  # noqa: E402

RESOLVED_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def node(cls, **props):
    return {"class": cls, "properties": props}


def fixture():
    """
    Hand-built graph, indices fixed so the assertions can name them:

      0 Organization AAA (issuer)      1 claim: shares tokens with evidence 5
      2 claim: shares NO tokens, but hangs off indicator 4
      3 claim: one shared token only (below the min_overlap gate)
      4 StandardIndicator               5 evidence: KPIObservation (news)
      6 Organization BBB (other issuer) 7 claim of BBB, same tokens as evidence 5
    """
    nodes = [
        node("Organization", name="Công ty AAA", ticker="AAA"),
        node(CLAIM_CLASS, description="giảm phát thải khí nhà kính trong sản xuất", year=2024),
        node(CLAIM_CLASS, description="cam kết trung hoà các bon toàn chuỗi", year=2024),
        node(CLAIM_CLASS, description="giảm chi phí quản lý doanh nghiệp", year=2024),
        node("StandardIndicator", name="TT96-6.1 Phát thải", pillar="E"),
        node("KPIObservation", title="giảm phát thải khí nhà kính đạt mục tiêu",
             source_type="news", year=2024),
        node("Organization", name="Công ty BBB", ticker="BBB"),
        node(CLAIM_CLASS, description="giảm phát thải khí nhà kính trong sản xuất", year=2024),
    ]
    edges = [
        {"subject": 0, "predicate": "claims", "object": 1},
        {"subject": 0, "predicate": "claims", "object": 2},
        {"subject": 0, "predicate": "claims", "object": 3},
        {"subject": 6, "predicate": "claims", "object": 7},
        # indicator axis: claim 2 --alignsWithIndicator--> 4 <--measuredUnder-- evidence 5
        {"subject": 2, "predicate": "alignsWithIndicator", "object": 4},
        {"subject": 5, "predicate": "measuredUnder", "object": 4},
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
def test_two_tiers() -> None:
    print("\n[1] the two retrieval tiers, run backwards (evidence → claim)")

    arm = GraphArm(fixture())
    hits = arm.retrieve(5, "AAA", top_k=10)
    got = {h["node_index"] for h in hits}

    check("token-overlap tier finds the lexically close claim", 1 in got, str(sorted(got)))
    check("indicator tier finds the claim sharing ZERO tokens", 2 in got, str(sorted(got)))
    check("min_overlap gate rejects the one-shared-token claim", 3 not in got, str(sorted(got)))

    tiers = {h["node_index"]: h["tier"] for h in hits}
    check("tiers are labelled", tiers.get(2) == "indicator" and tiers.get(1) == "token_overlap",
          str(tiers))

    # Tier priority: step07 gives indicator pairs a deliberately huge boost so they
    # always outrank token pairs for the LLM budget. Backwards must keep that order.
    check("indicator tier outranks token tier",
          hits[0]["node_index"] == 2, str([(h["node_index"], h["score"]) for h in hits]))
    check("the boost is the same constant step07 uses",
          hits[0]["score"] >= INDICATOR_BOOST, str(hits[0]["score"]))


def test_scoping_and_gates() -> None:
    print("\n[2] issuer scoping and the temporal window")

    arm = GraphArm(fixture())

    # Cross-company leakage is the failure mode a graph system can have and BM25 cannot
    # (AGENT_AB_EVALUATION.md §6.2 "rò rỉ thật"). Node 7 is a perfect token match but
    # belongs to BBB — it must never surface under AAA.
    got = {h["node_index"] for h in arm.retrieve(5, "AAA", top_k=10)}
    check("a perfect token match from ANOTHER issuer never leaks in", 7 not in got, str(sorted(got)))
    check("querying BBB returns BBB's claim", 7 in {h["node_index"] for h in arm.retrieve(5, "BBB", top_k=10)})
    check("unknown ticker returns nothing", arm.retrieve(5, "ZZZ", top_k=10) == [])

    # Temporal window: evidence is 2024. A window that excludes 2024 must drop the
    # token-tier hit. (The indicator tier applies the same window in step07.)
    narrow = arm.retrieve(5, "AAA", top_k=10, window_before=0, window_after=0, claim_year_override=2000)
    check("a claim outside the temporal window is dropped",
          1 not in {h["node_index"] for h in narrow}, str(narrow))

    check("top_k caps the result list", len(arm.retrieve(5, "AAA", top_k=1)) == 1)
    check("a non-conduct source node still returns a ranked list, never a crash",
          isinstance(arm.retrieve(0, "AAA", top_k=3), list))


def test_claim_text() -> None:
    print("\n[3] the returned claim text is the node's own text")

    arm = GraphArm(fixture())
    hit = next(h for h in arm.retrieve(5, "AAA", top_k=10) if h["node_index"] == 1)
    check("claim_text comes from the claim node",
          hit["claim_text"] == "giảm phát thải khí nhà kính trong sản xuất", repr(hit["claim_text"]))
    check("every hit carries node_index / claim_text / score / tier",
          {"node_index", "claim_text", "score", "tier"} <= set(hit), str(sorted(hit)))


def test_real_corpus() -> None:
    print("\n[4] real corpus: the arm actually retrieves something")

    if not RESOLVED_GRAPH.exists():
        print(f"  SKIP  {RESOLVED_GRAPH.name} missing")
        return

    data = json.loads(RESOLVED_GRAPH.read_text(encoding="utf-8"))
    arm = GraphArm(data)

    tickers = arm.tickers()
    check("issuers found in the real graph", len(tickers) > 0, str(tickers))

    total_claims = sum(len(arm.claims_for_ticker(t)) for t in tickers)
    check("claims found for the real issuers", total_claims > 0, str(total_claims))

    # Non-vacuity: run the arm over real conduct nodes and require it to return claims
    # for at least some of them. Without this the synthetic assertions above could all
    # pass while the arm returns nothing on the data that matters.
    conduct = arm.conduct_nodes()
    check("conduct (news) nodes found", len(conduct) > 0, str(len(conduct)))

    answered = 0
    probed = 0
    for xi in conduct[:200]:
        ticker = arm.ticker_of(xi)
        if not ticker:
            continue
        probed += 1
        if arm.retrieve(xi, ticker, top_k=5):
            answered += 1
    check("the arm returns claims for real evidence nodes", answered > 0, f"{answered}/{probed}")
    print(f"        {len(tickers)} issuers · {total_claims} claims · {len(conduct)} conduct nodes")
    print(f"        probed {probed} conduct nodes, {answered} got at least one claim")


def main() -> int:
    ensure_utf8_stdout()
    print("=" * 72)
    print(" test3/graph_rag_arm.py — offline test")
    print("=" * 72)

    test_two_tiers()
    test_scoping_and_gates()
    test_claim_text()
    test_real_corpus()

    print("\n" + "=" * 72)
    if FAILURES:
        print(f" FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print(" ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
