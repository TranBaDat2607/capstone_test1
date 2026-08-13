"""
Baseline comparison for claim→conduct retrieval.

Why this module exists
----------------------
`metrics.py` measures whether the pipeline is internally consistent. That is
system testing, not evaluation: none of it answers the question a thesis
committee actually asks —

    does Graph-RAG retrieve better evidence than a simpler method, and by how much?

The comparable capstone (AIP491, ESG QA over Vietnamese banks) answers it by
running BM25 / Dense / MMR against KG / KG_Enhanced on an expert-annotated gold
set and reporting Recall@k and Precision@k. This module builds the same shape
for the claim↔conduct task.

The ablation arms
-----------------
    random                a floor. Any method that cannot beat it is not working.
    bm25                  lexical retrieval, no graph at all
    token_overlap         the pipeline's own tier-2 scorer, graph removed
    indicator_only        only the 2-hop join claim→StandardIndicator←conduct
    token_plus_indicator  what the system does today (both tiers)
    *_scoped              the same, restricted to the claimant's own news feed

The `*_scoped` arms exist because the negative control found the conduct pool is
global (claims_vs_conduct.py:485) — so scoping is a change whose value has to be
measured, not assumed.

Retrieval helpers are IMPORTED from the pipeline itself (`topic_tokens`,
`node_text`, `node_year`, ...) rather than reimplemented. A reimplementation
would be measuring a lookalike of the system instead of the system.

Gold labels
-----------
`evaluate_run` needs a gold set per claim. Two sources, in increasing strength:

  proxy   `same-company` from negative_control's attribution — objective and free,
          but only measures whether evidence is about the right company, not
          whether it is topically relevant. A weak, honest lower bound.
  human   the blind annotation (annotation.py). Required for real Recall/Precision.

The candidate set given to annotators MUST be POOLED across every method here.
Judging only the incumbent's output makes every baseline look worse by
construction, because anything a baseline found and the incumbent missed would
go unjudged and be scored as non-relevant.
"""

from __future__ import annotations

import math
import random as _random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.crosscheck.claims_vs_conduct import (  # noqa: E402
    Graph,
    claim_keywords,
    date_uncertain,
    node_text,
    node_year,
    topic_tokens,
)

from evalu.negative_control import attribute_ticker  # noqa: E402

CONDUCT_CLASSES = {"Controversy", "Penalty", "MediaReport"}

METHODS = (
    "random",
    "bm25",
    "token_overlap",
    "indicator_only",
    "token_plus_indicator",
    "token_plus_indicator_scoped",
    "bm25_scoped",
)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def recall_at_k(ranked: Sequence[int], gold: Set[int], k: int) -> Optional[float]:
    """None when there is nothing to recall — never 0.0, which would read as failure."""
    if not gold:
        return None
    return len(set(ranked[:k]) & gold) / len(gold)


def precision_at_k(ranked: Sequence[int], gold: Set[int], k: int) -> float:
    """Divided by k, not by the number returned: a short list is still penalised."""
    return len(set(ranked[:k]) & gold) / k


def evaluate_run(run: Dict[str, Sequence[int]], gold: Dict[str, Set[int]],
                 ks: Iterable[int] = (3, 5, 10)) -> Dict[str, Any]:
    """Macro-average Recall@k / Precision@k over the claims that have gold."""
    ks = tuple(ks)
    sums: Dict[str, List[float]] = defaultdict(list)
    scored = 0
    for claim_id, ranked in run.items():
        g = gold.get(claim_id) or set()
        if not g:
            continue
        scored += 1
        for k in ks:
            sums[f"recall@{k}"].append(recall_at_k(ranked, g, k) or 0.0)
            sums[f"precision@{k}"].append(precision_at_k(ranked, g, k))
    out: Dict[str, Any] = {"claims_scored": scored}
    for key, vals in sums.items():
        out[key] = (sum(vals) / len(vals)) if vals else None
    return out


# --------------------------------------------------------------------------- #
# BM25
# --------------------------------------------------------------------------- #
def bm25_scores(query: str, docs: Dict[int, str],
                k1: float = 1.5, b: float = 0.75) -> Dict[int, float]:
    """Okapi BM25 over a small in-memory corpus, tokenised like the pipeline."""
    tok_docs = {i: list(topic_tokens(t)) for i, t in docs.items()}
    n = len(tok_docs) or 1
    avgdl = (sum(len(t) for t in tok_docs.values()) / n) or 1.0

    df: Counter = Counter()
    for toks in tok_docs.values():
        df.update(set(toks))

    q_terms = list(topic_tokens(query))
    scores: Dict[int, float] = {}
    for i, toks in tok_docs.items():
        tf = Counter(toks)
        dl = len(toks) or 1
        s = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            # +1 inside the log keeps IDF >= 0, so a term present in every
            # document contributes nothing instead of contributing negatively
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            f = tf[term]
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        scores[i] = s
    return scores


# --------------------------------------------------------------------------- #
# retrieval runs
# --------------------------------------------------------------------------- #
def build_context(graph_data: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the retrieval arms share: pool, tokens, indicator joins."""
    g = Graph(graph_data)
    conduct = [i for i, n in enumerate(g.nodes)
               if n.get("class") in CONDUCT_CLASSES
               and (n.get("properties") or {}).get("source_type") == "news"]

    ind_conduct: Dict[int, List[int]] = defaultdict(list)
    for si in conduct:
        for pred, obj in g.out.get(si, []):
            if pred == "measuredUnder":
                ind_conduct[obj].append(si)

    return {
        "g": g,
        "conduct": conduct,
        "ctok": {i: topic_tokens(node_text(g.nodes[i])) for i in conduct},
        "ctext": {i: node_text(g.nodes[i]) for i in conduct},
        "cticker": {i: attribute_ticker(g.nodes[i]) for i in conduct},
        "ind_conduct": ind_conduct,
        "kw": claim_keywords(g),
    }


def claim_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every SustainabilityClaim with the fields the arms need."""
    g = ctx["g"]
    out = []
    for i, n in enumerate(g.nodes):
        if n.get("class") != "SustainabilityClaim":
            continue
        inds = [obj for pred, obj in g.out.get(i, []) if pred == "alignsWithIndicator"]
        ticker = None
        for pred, subj in g.inc.get(i, []) if hasattr(g, "inc") else []:
            if pred == "claims":
                ticker = (g.nodes[subj].get("properties") or {}).get("ticker")
        out.append({
            "node_index": i,
            "claim_id": (n.get("properties") or {}).get("claim_id") or f"n{i}",
            "text": node_text(n),
            "year": node_year(n),
            "indicators": inds,
            "ticker": (ticker or "").upper() or None,
        })
    return out


def _within_window(ctx, ci_year, xi, before=1, after=2) -> bool:
    g = ctx["g"]
    xyear = node_year(g.nodes[xi])
    if ci_year is None or xyear is None or date_uncertain(g.nodes[xi]):
        return True
    return (ci_year - before) <= xyear <= (ci_year + after)


def run_method(ctx: Dict[str, Any], claims: Sequence[Dict[str, Any]],
               method: str, top_k: int = 10, seed: int = 42
               ) -> Dict[str, List[int]]:
    """One retrieval configuration -> {claim_id: ranked conduct node indexes}."""
    g = ctx["g"]
    rng = _random.Random(seed)
    scoped = method.endswith("_scoped")
    base = method[:-len("_scoped")] if scoped else method

    run: Dict[str, List[int]] = {}
    for c in claims:
        pool = ctx["conduct"]
        if scoped and c["ticker"]:
            pool = [x for x in pool if ctx["cticker"].get(x) == c["ticker"]]
        pool = [x for x in pool if _within_window(ctx, c["year"], x)]

        if base == "random":
            ranked = list(pool)
            rng.shuffle(ranked)
        elif base == "bm25":
            sc = bm25_scores(c["text"], {i: ctx["ctext"][i] for i in pool})
            ranked = [i for i, s in sorted(sc.items(), key=lambda kv: -kv[1]) if s > 0]
        elif base == "indicator_only":
            hits = []
            for ind in c["indicators"]:
                hits.extend(x for x in ctx["ind_conduct"].get(ind, []) if x in set(pool))
            ranked = sorted(set(hits), key=lambda x: -(node_year(g.nodes[x]) or 0))
        else:
            ctoks = topic_tokens(c["text"], ctx["kw"].get(c["node_index"]))
            scored: List[Tuple[int, int, int]] = []
            for xi in pool:
                ov = len(ctoks & ctx["ctok"][xi])
                if ov:
                    scored.append((ov, node_year(g.nodes[xi]) or 0, xi))
            if base == "token_plus_indicator":
                # mirror the pipeline: indicator-joined pairs outrank token hits
                have = {x for _, _, x in scored}
                for ind in c["indicators"]:
                    for xi in ctx["ind_conduct"].get(ind, []):
                        if xi not in set(pool):
                            continue
                        if xi in have:
                            scored = [(o + 1000 if x == xi else o, y, x)
                                      for o, y, x in scored]
                        else:
                            scored.append((1000, node_year(g.nodes[xi]) or 0, xi))
                            have.add(xi)
            scored.sort(key=lambda t: (-t[0], -t[1]))
            ranked = [x for _, _, x in scored]

        run[c["claim_id"]] = ranked[:top_k]
    return run


def pool_candidates(runs: Dict[str, Dict[str, Sequence[int]]],
                    depth: int = 10) -> Dict[str, Set[int]]:
    """TREC-style pooling: the union of every method's top-`depth`."""
    pool: Dict[str, Set[int]] = defaultdict(set)
    for run in runs.values():
        for claim_id, ranked in run.items():
            pool[claim_id].update(ranked[:depth])
    return dict(pool)


def proxy_gold_same_company(ctx: Dict[str, Any], claims: Sequence[Dict[str, Any]],
                            pool: Dict[str, Set[int]]) -> Dict[str, Set[int]]:
    """
    A free, objective — and deliberately weak — stand-in for human relevance:
    a candidate counts as relevant if it comes from the claimant's own news feed.

    This measures company attribution ONLY, never topical relevance, so the
    absolute values mean little. What it can support is a RELATIVE comparison
    between methods, available before any annotation exists.
    """
    by_id = {c["claim_id"]: c for c in claims}
    gold: Dict[str, Set[int]] = {}
    for claim_id, cands in pool.items():
        t = (by_id.get(claim_id) or {}).get("ticker")
        if not t:
            continue
        hits = {x for x in cands if ctx["cticker"].get(x) == t}
        if hits:
            gold[claim_id] = hits
    return gold
