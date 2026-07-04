#!/usr/bin/env python3
"""
Step 6 / P4 — cross-check reported ESG claims against news conduct.

Reads the resolved temporal KG (`graph_output/resolved/resolved_graph.json`, step 4),
and for every `SustainabilityClaim` on the issuer links the conduct evidence that
supports or contradicts it, then emits an ADVISORY evidence dossier
(`graph_output/crosscheck/aaa_claim_assessments.json`). It never emits a greenwashing
score or a hard label — only `appears_supported` / `appears_contradicted` /
`unverified_insufficient_evidence`, always flagged advisory, always with caveats
(see docs/SYSTEM_DESIGN.md §1.1, §6).

This is the in-KG *inversion* of EmeraldMind's detection steps (EmeraldKG 6a/6b/7):
their claim is an external CSV row scored against the KG with gold labels; here the
claim is a node already IN the graph, cross-checked against conduct nodes already in
the graph, producing advisory evidence links — no ground truth, no accuracy claim.

Pipeline (mirrors §6):
  6a  retrieve conduct candidates per claim   — same issuer + VN topic overlap +
      temporal window (+ optional embedding rank behind --embed)
  6b  adjudicate each (claim, candidate) pair  — gemini-2.5-flash structured output;
      optional, budgeted (--max-llm-pairs), degrades gracefully on 403 / --no-llm
  6c  write schema-legal linking edges         — verifiedBy / contradictedBy /
      contradictedByMedia, each stamped llm_suggested=true (attributable, re-runnable)
  6c-guard  self-verification guard            — a company-owned domain never creates
      a verifiedBy edge (independence, §6.4)
  6d  deterministic signals                    — structural contradiction + KPI gap
  6e  dossier + advisory assessment            — evidence + rationale + caveats

Design decisions (docs/SYSTEM_DESIGN.md, plan glistening-hopping-galaxy):
  * offline-first: deterministic signals ALWAYS run; the LLM is opt-in and non-fatal.
  * deterministic retrieval by default; embeddings (--embed) are optional (the current
    Gemini embedding endpoint may be billing-blocked and the candidate pool is tiny).

Run from the repo root:  python src/crosscheck_claims_vs_conduct.py --dry-run
Reuses REPO_ROOT / RateLimiter / load_schema_sets / normalize_name from earlier stages;
loads .env (GEMINI_API_KEY) at the repo root.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from extract_kpi_from_jsonl import REPO_ROOT
from extract_triplet_from_jsonl import RateLimiter
from fix_invalid_triplets import load_schema_sets
from build_issuer_registry import normalize_name, name_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "crosscheck"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER_ORDER = "gemini,openai"   # primary,fallback
DEFAULT_RATE_LIMIT = 10
DEFAULT_MAX_LLM_PAIRS = 300
DEFAULT_TOP_K = 8
DEFAULT_WINDOW_BEFORE = 1     # conduct may predate the claim year by at most this
DEFAULT_WINDOW_AFTER = 50     # ...and may follow it by "any" plausible number of years

# Conduct-side node classes (the "doing"). Claims are the "saying" (SustainabilityClaim).
CONDUCT_CLASSES = {"Controversy", "Penalty", "MediaReport", "KPIObservation", "ThirdPartyVerification"}

# How a verdict + evidence class maps to a schema-legal claim edge. Pairs are checked
# against config/schema.json at runtime; anything not legal stays dossier-only.
SUPPORT_EDGE = "verifiedBy"                      # SustainabilityClaim -> {ThirdPartyVerification, KPIObservation}
CONTRADICT_EDGE = {                              # SustainabilityClaim -> ...
    "Controversy": "contradictedBy",
    "MediaReport": "contradictedByMedia",
}

# Self-verification guard (§6.4): the issuer's own domains must never "verify" its own
# claims. POC inline list + an issuer-token heuristic (a domain containing a core issuer
# token is treated as company-owned). Safe-failure direction: a miss only inflates
# support, never fabricates a contradiction.
COMPANY_DOMAINS = {
    "anphatholdings.vn", "aneco.com.vn", "anphatbioplastics.com", "anphat.vn",
    "aaa.com.vn", "aaa.com", "aaplastic.vn",
}
ISSUER_DOMAIN_TOKENS = {"anphat", "aneco", "aaplastic"}

# Tokens that must not drive topic overlap: generic + the issuer's own name (all conduct
# is about the issuer, so name tokens would match everything and mean nothing).
STOPWORDS: Set[str] = {
    "cong", "ty", "co", "phan", "tnhh", "tap", "doan", "aaa", "an", "phat", "xanh",
    "nhua", "green", "plastic", "plastics", "environment", "moi", "truong", "va",
    "cua", "cac", "trong", "nam", "the", "and", "for", "with", "cong ty",
    "bao", "cao", "report", "nien", "thuong", "ve", "la", "den", "cho", "khi",
}

ADJUDICATION_SCHEMA = {  # Gemini OpenAPI-3 dialect (same style as extract_kpi's KPI_SCHEMA)
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supports", "contradicts", "irrelevant"]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
}

ADJUDICATE_SYSTEM = (
    "You assess greenwashing evidence for a Vietnamese ESG knowledge graph. You are given "
    "ONE ESG claim a company made in its own report, and ONE piece of independent evidence "
    "about the company (usually a news item). Decide, using ONLY the two texts, whether the "
    "evidence SUPPORTS the claim, CONTRADICTS it, or is IRRELEVANT.\n"
    "Rules:\n"
    "- Treat the evidence as independent conduct ('what the company did'), not as a restatement "
    "of the claim.\n"
    "- 'contradicts' means the evidence is in tension with the claim (e.g. a green/responsible "
    "claim vs a penalty, violation, controversy, or an adverse metric in the same period).\n"
    "- 'supports' means the evidence independently corroborates the claim (e.g. a third-party "
    "verification, certification, or an observed metric consistent with the claim).\n"
    "- Prefer 'irrelevant' when the evidence is about an unrelated topic or is neutral "
    "financial/market coverage. Do not guess.\n"
    "- The texts are Vietnamese. confidence is 0.0-1.0. Ground the rationale in the evidence text."
)


# --------------------------------------------------------------------------- #
# Node helpers.
# --------------------------------------------------------------------------- #
def props(node: Dict[str, Any]) -> Dict[str, Any]:
    return node.get("properties", {}) or {}


def node_text(node: Dict[str, Any]) -> str:
    """A readable text blob for a node, used for topic overlap and the LLM prompt."""
    p = props(node)
    cls = node.get("class")
    if cls == "KPIObservation":
        bits = [str(p.get(k)) for k in ("title", "kpi_type", "value", "unit", "kind") if p.get(k) not in (None, "")]
        return " ".join(bits)
    if cls == "ThirdPartyVerification":
        return " ".join(str(p.get(k)) for k in ("verifier", "result") if p.get(k))
    for k in ("description", "title", "text", "result", "name", "term"):
        if p.get(k):
            return str(p[k])
    return ""


def node_year(node: Dict[str, Any]) -> Optional[int]:
    """Best-effort effective year: explicit year fields, then dates, then an id/source string."""
    p = props(node)
    for k in ("publish_year", "target_year", "year"):
        v = p.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit() and len(v.strip()) == 4:
            return int(v.strip())
    for k in ("date", "valid_from", "publish_date_normalized", "date_normalized"):
        m = re.search(r"(19|20)\d{2}", str(p.get(k, "") or ""))
        if m:
            return int(m.group(0))
    for k in ("claim_id", "report_id", "controversy_id", "penalty_id", "verification_id", "source_id", "source"):
        m = re.search(r"(19|20)\d{2}", str(p.get(k, "") or ""))
        if m:
            return int(m.group(0))
    return None


def node_domain(node: Dict[str, Any]) -> str:
    """The publishing domain of a conduct node (MediaReport stores it in `publisher`)."""
    p = props(node)
    for k in ("source_domain", "publisher", "source"):
        v = p.get(k)
        if v and "." in str(v):
            return str(v).strip().lower()
    return ""


def date_uncertain(node: Dict[str, Any]) -> bool:
    p = props(node)
    if p.get("date_uncertain") in (True, "true", "True"):
        return True
    # A bare "YYYY-01-01" is the preprocessor's placeholder for an unknown day/month.
    return bool(re.fullmatch(r"(19|20)\d{2}-01-01", str(p.get("date", "") or "")))


def topic_tokens(text: str, extra: Optional[Set[str]] = None) -> Set[str]:
    toks = {t for t in name_tokens(text) if len(t) >= 3 and t not in STOPWORDS}
    if extra:
        toks |= {t for t in extra if len(t) >= 3 and t not in STOPWORDS}
    return toks


def is_company_domain(domain: str) -> bool:
    if not domain:
        return False
    d = domain.lower()
    if d in COMPANY_DOMAINS:
        return True
    return any(tok in d for tok in ISSUER_DOMAIN_TOKENS)


# --------------------------------------------------------------------------- #
# Graph indexing.
# --------------------------------------------------------------------------- #
class Graph:
    def __init__(self, data: Dict[str, Any]):
        self.nodes: List[Dict[str, Any]] = data["nodes"]
        self.edges: List[Dict[str, Any]] = data["edges"]
        self.out: Dict[int, List[Tuple[str, int]]] = defaultdict(list)   # subj -> [(pred, obj)]
        self.inc: Dict[int, List[Tuple[str, int]]] = defaultdict(list)   # obj  -> [(pred, subj)]
        for e in self.edges:
            s, o, pr = e.get("subject"), e.get("object"), e.get("predicate")
            if isinstance(s, int) and isinstance(o, int) and pr:
                self.out[s].append((pr, o))
                self.inc[o].append((pr, s))

    def cls(self, i: int) -> str:
        return self.nodes[i].get("class", "")


def find_issuer(g: Graph, ticker: str) -> Optional[int]:
    cands = [i for i, n in enumerate(g.nodes)
             if n.get("class") == "Organization" and str(props(n).get("ticker", "")).upper() == ticker.upper()]
    if not cands:
        return None
    # the resolved issuer anchor is the most-connected Organization (usually index 0)
    return max(cands, key=lambda i: len(g.out[i]) + len(g.inc[i]))


def claim_keywords(g: Graph) -> Dict[int, Set[str]]:
    """claim index -> {ClaimKeyword terms} via hasKeyword edges."""
    kw: Dict[int, Set[str]] = defaultdict(set)
    for e in g.edges:
        if e.get("predicate") == "hasKeyword":
            s, o = e.get("subject"), e.get("object")
            if isinstance(s, int) and isinstance(o, int) and g.cls(o) == "ClaimKeyword":
                term = props(g.nodes[o]).get("term")
                if term:
                    kw[s] |= name_tokens(term)
    return kw


# --------------------------------------------------------------------------- #
# LLM adjudication (optional, multi-provider with graceful fallback).
#
# Primary: gemini-2.5-flash. Fallback: OpenAI gpt-4o-mini. Both do the SAME narrow,
# grounded 3-way task, so either is adequate for the POC. A provider that fails 3x with
# no success (e.g. a 403 billing block) is disabled and the next one is tried, so the run
# always finishes — on the other provider, or on deterministic signals.
# --------------------------------------------------------------------------- #
def _parse_verdict(raw: str) -> Optional[Dict[str, Any]]:
    """Parse a provider's JSON reply into {verdict, confidence, rationale} or None."""
    if not raw:
        return None
    try:
        out = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except Exception:
            return None
    if out.get("verdict") not in ("supports", "contradicts", "irrelevant"):
        return None
    out["confidence"] = float(out.get("confidence", 0.0) or 0.0)
    out.setdefault("rationale", "")
    return out


class _Provider:
    """One LLM backend. `call(system, user)` returns the raw text reply or raises."""
    name = "base"

    def __init__(self) -> None:
        self.enabled = False
        self.calls = 0
        self.failures = 0

    def call(self, system: str, user: str) -> str:  # pragma: no cover
        raise NotImplementedError


class _GeminiProvider(_Provider):
    name = "gemini"

    def __init__(self, model: str, rate_limit: int) -> None:
        super().__init__()
        self.model = model
        if not os.getenv("GEMINI_API_KEY"):
            return
        try:
            from google import genai
            from google.genai import types
            self._types = types
            self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            self.rl = RateLimiter(max_calls_per_minute=rate_limit)
            self.enabled = True
        except Exception as e:  # pragma: no cover
            logger.warning(f"[gemini] client init failed ({e}); provider disabled.")

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = self.client.models.generate_content(
            model=self.model, contents=user,
            config=self._types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_schema=ADJUDICATION_SCHEMA, temperature=0),
        )
        return (resp.text or "").strip()


class _OpenAIProvider(_Provider):
    name = "openai"

    def __init__(self, model: str, rate_limit: int) -> None:
        super().__init__()
        self.model = model
        if not os.getenv("OPENAI_API_KEY"):
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.rl = RateLimiter(max_calls_per_minute=rate_limit)
            self.enabled = True
        except Exception as e:  # pragma: no cover
            logger.warning(f"[openai] client init failed ({e}); provider disabled.")

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()


class Adjudicator:
    """A cascade of LLM providers with per-provider graceful failure. `adjudicate` tries
    each enabled provider in preference order and returns the first parsed verdict, tagged
    with the provider that produced it. When one provider dies (e.g. a 403), the next takes
    over automatically; if all die, the caller falls back to deterministic signals."""

    def __init__(self, gemini_model: str, openai_model: str, rate_limit: int, order: List[str]) -> None:
        # override=True so the repo .env is authoritative — a stale shell OPENAI_API_KEY /
        # GEMINI_API_KEY must not shadow the key the user edits in .env.
        load_dotenv(REPO_ROOT / ".env", override=True)
        registry = {
            "gemini": lambda: _GeminiProvider(gemini_model, rate_limit),
            "openai": lambda: _OpenAIProvider(openai_model, rate_limit),
        }
        self.providers: List[_Provider] = []
        for name in order:
            make = registry.get(name)
            if not make:
                logger.warning(f"Unknown adjudication provider '{name}' — ignored.")
                continue
            p = make()
            if p.enabled:
                self.providers.append(p)
            else:
                logger.info(f"[{name}] not available (no key / SDK) — skipped.")
        self.enabled = bool(self.providers)
        if self.enabled:
            logger.info(f"Adjudicator ready: providers = {[p.name for p in self.providers]}")
        else:
            logger.warning("No LLM provider available — deterministic-only.")

    def adjudicate(self, claim_text: str, evidence_text: str, evidence_meta: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        user = (
            f"CLAIM (company report): \"{claim_text}\"\n\n"
            f"EVIDENCE ({evidence_meta}): \"{evidence_text}\"\n\n"
            "Return only JSON: verdict (supports|contradicts|irrelevant), confidence (0-1), rationale."
        )
        result: Optional[Dict[str, Any]] = None
        for p in self.providers:
            if not p.enabled:
                continue
            try:
                raw = p.call(ADJUDICATE_SYSTEM, user)
                p.calls += 1
                out = _parse_verdict(raw)
                if out is not None:
                    out["provider"] = p.name
                    result = out
                break  # this provider answered; don't cascade further
            except Exception as e:
                p.failures += 1
                logger.warning(f"[{p.name}] adjudication failed ({e}).")
                if p.failures >= 3 and p.calls == 0:
                    logger.error(f"[{p.name}] 3 failures with 0 successes — disabling; falling back to next provider.")
                    p.enabled = False
                continue  # try the next provider for this same pair
        if not any(p.enabled for p in self.providers):
            self.enabled = False
        return result

    def summary(self) -> Dict[str, Any]:
        return {"active": self.enabled,
                "providers": [{"name": p.name, "enabled": p.enabled,
                               "calls_ok": p.calls, "failures": p.failures} for p in self.providers]}


# --------------------------------------------------------------------------- #
# Deterministic signals (§6.5).
# --------------------------------------------------------------------------- #
def structural_contradiction(g: Graph, claim_idx: int, issuer_idx: int,
                             new_contradictions: List[int]) -> bool:
    """A claim with contradiction evidence but no INDEPENDENT verification in-graph.
    Uses newly-adjudicated contradictions plus any pre-existing contradictedBy* edges;
    report-side verifiedBy does not count as independent verification (§6.4)."""
    has_contra = bool(new_contradictions)
    for pred, obj in g.out[claim_idx]:
        if pred in ("contradictedBy", "contradictedByMedia"):
            has_contra = True
    return has_contra


def build_kpi_gaps(g: Graph, report_targets: List[int],
                   news_observed: List[int]) -> List[Dict[str, Any]]:
    """Precompute adverse (report target, news observed) KPI pairs ONCE. Strict on purpose
    (§6.5 — a complementary signal, never a verdict): same non-generic kpi_type and >=2
    shared title tokens, with the observed value moving opposite to the target's direction.
    Sparse by nature; each gap carries its token set for cheap per-claim lookup."""
    obs = [(oi, props(g.nodes[oi]), topic_tokens(node_text(g.nodes[oi]))) for oi in news_observed]
    gaps: List[Dict[str, Any]] = []
    for ti in report_targets:
        tp = props(g.nodes[ti])
        direction = str(tp.get("direction", ""))
        tv, tkind = tp.get("value"), str(tp.get("kpi_type", ""))
        if direction not in ("reduction", "increase") or not isinstance(tv, (int, float)):
            continue
        ttok = topic_tokens(node_text(g.nodes[ti]))
        for oi, op, otok in obs:
            if tkind in ("", "other") or str(op.get("kpi_type", "")) != tkind:
                continue
            if len(ttok & otok) < 2:
                continue
            ov = op.get("value")
            if not isinstance(ov, (int, float)):
                continue
            if (direction == "reduction" and ov > tv) or (direction == "increase" and ov < tv):
                gaps.append({"tokens": ttok, "kpi_title": tp.get("title"), "kpi_type": tkind,
                             "direction": direction, "target_value": tv, "observed_value": ov,
                             "note": "observed conduct moves opposite to the reported target"})
    return gaps


def kpi_gap_for_claim(claim_tokens: Set[str], gaps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Attach a precomputed gap to a claim only when they share a topic. Advisory only."""
    for gp in gaps:
        if gp["tokens"] & claim_tokens:
            return {k: v for k, v in gp.items() if k != "tokens"}
    return None


# --------------------------------------------------------------------------- #
# Driver.
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> None:
    data = json.loads(args.input.read_text(encoding="utf-8"))
    g = Graph(data)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    _, _, edge_dirs = load_schema_sets(schema)

    def legal(label: str, src_cls: str, tgt_cls: str) -> bool:
        return (src_cls, tgt_cls) in edge_dirs.get(label, [])

    issuer_idx = find_issuer(g, args.ticker)
    if issuer_idx is None:
        logger.error(f"No issuer Organization with ticker={args.ticker} in the graph.")
        return
    logger.info(f"Issuer '{args.ticker}' = node #{issuer_idx} "
                f"({props(g.nodes[issuer_idx]).get('name')})")

    # ---- claims on the issuer ----
    claim_idxs = [o for (pr, o) in g.out[issuer_idx] if pr == "claims" and g.cls(o) == "SustainabilityClaim"]
    claim_idxs = sorted(set(claim_idxs))
    kw = claim_keywords(g)
    logger.info(f"{len(claim_idxs)} SustainabilityClaims linked to the issuer")

    # ---- conduct pool (independent = news) ----
    conduct = [i for i, n in enumerate(g.nodes)
               if n.get("class") in CONDUCT_CLASSES and props(n).get("source_type") == "news"]
    report_targets = [i for i, n in enumerate(g.nodes)
                      if n.get("class") == "KPIObservation" and props(n).get("source_type") == "report"
                      and props(n).get("kind") == "target"]
    news_observed = [i for i in conduct if g.cls(i) == "KPIObservation"]
    conduct_by_cls = Counter(g.cls(i) for i in conduct)
    logger.info(f"Conduct pool (source_type=news): {len(conduct)} nodes {dict(conduct_by_cls)}")

    # pre-tokenize the conduct pool + precompute KPI-gap signals once
    ctok = {i: topic_tokens(node_text(g.nodes[i])) for i in conduct}
    kpi_gaps = build_kpi_gaps(g, report_targets, news_observed)
    logger.info(f"KPI-gap signals precomputed: {len(kpi_gaps)}")

    adjud = None
    if not (args.no_llm or args.dry_run):
        adjud = Adjudicator(args.model, args.openai_model, args.rate_limit, args.provider_order)

    # ---- 6a retrieval: candidate conduct per claim (deterministic, cheap) ----
    cand_of: Dict[int, List[int]] = {}
    all_pairs: List[Tuple[int, int, int]] = []  # (overlap, claim_idx, conduct_idx)
    for ci in claim_idxs:
        ctoks = topic_tokens(node_text(g.nodes[ci]), kw.get(ci))
        cyear = node_year(g.nodes[ci])
        scored: List[Tuple[int, int, int]] = []  # (overlap, recency, conduct_idx)
        for xi in conduct:
            overlap = len(ctoks & ctok[xi])
            if overlap == 0:
                continue
            xyear = node_year(g.nodes[xi])
            if cyear is not None and xyear is not None and not date_uncertain(g.nodes[xi]):
                if xyear < cyear - args.window_before or xyear > cyear + args.window_after:
                    continue
            scored.append((overlap, xyear or 0, xi))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        top = scored[: args.top_k]
        cand_of[ci] = [xi for _, _, xi in top]
        all_pairs.extend((ov, ci, xi) for ov, _, xi in top)
    claims_with_cands = sum(1 for ci in claim_idxs if cand_of[ci])
    pairs_total = len(all_pairs)

    # ---- 6b adjudication: highest-overlap pairs first, up to the budget, concurrent ----
    verdicts: Dict[Tuple[int, int], Dict[str, Any]] = {}
    llm_pairs = 0
    if adjud and adjud.enabled and pairs_total:
        all_pairs.sort(key=lambda t: -t[0])
        budget_pairs = all_pairs[: args.max_llm_pairs]
        logger.info(f"Adjudicating {len(budget_pairs)}/{pairs_total} candidate pairs "
                    f"(budget {args.max_llm_pairs}, {args.max_workers} workers)")

        def _adj(pair: Tuple[int, int, int]):
            _, ci, xi = pair
            meta = f"{g.cls(xi)} from {node_domain(g.nodes[xi]) or 'news'}, year {node_year(g.nodes[xi])}"
            return (ci, xi), adjud.adjudicate(node_text(g.nodes[ci]), node_text(g.nodes[xi]), meta)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as exe:
            for key, res in exe.map(_adj, budget_pairs):
                llm_pairs += 1
                if res:
                    verdicts[key] = res
        logger.info(f"Adjudication done: {llm_pairs} pairs, {len(verdicts)} verdicts, "
                    f"active_providers={[p.name for p in adjud.providers if p.enabled]}")
    adjudicated_pairs = set(verdicts.keys())
    budget_hit = adjud is not None and adjud.enabled and pairs_total > args.max_llm_pairs

    # ---- 6c/6d/6e assembly per claim ----
    dossiers: List[Dict[str, Any]] = []
    new_edges: List[Dict[str, Any]] = []
    assess_hist: Counter = Counter()
    for ci in claim_idxs:
        cnode = g.nodes[ci]
        ctext = node_text(cnode)
        cyear = node_year(cnode)
        ctoks = topic_tokens(ctext, kw.get(ci))
        candidates = cand_of[ci]

        supporting: List[Dict[str, Any]] = []
        contradicting: List[Dict[str, Any]] = []
        new_contra_targets: List[int] = []
        adjudicated_here = False

        for xi in candidates:
            verdict = verdicts.get((ci, xi))
            if not verdict:
                continue
            adjudicated_here = True
            v = verdict["verdict"]
            if v not in ("supports", "contradicts"):   # irrelevant → adjudicated, no edge
                continue
            conf, why, prov = verdict["confidence"], verdict.get("rationale", ""), verdict.get("provider")
            xnode = g.nodes[xi]
            xcls = g.cls(xi)
            domain = node_domain(xnode)
            src_type = props(xnode).get("source_type")
            ev = {"node_index": xi, "class": xcls, "text": node_text(xnode)[:400],
                  "source_domain": domain, "date": props(xnode).get("date"),
                  "year": node_year(xnode), "confidence": conf, "rationale": why,
                  "provider": prov, "date_uncertain": date_uncertain(xnode)}

            if v == "supports":
                # self-verification guard: the issuer's own domain cannot verify its claim
                if is_company_domain(domain):
                    ev["independent"] = False
                    ev["guard"] = "dropped: company-owned domain cannot self-verify"
                    supporting.append(ev)  # visible, but never counted toward appears_supported
                    continue
                ev["independent"] = True
                supporting.append(ev)
                if legal(SUPPORT_EDGE, "SustainabilityClaim", xcls):
                    new_edges.append(_mk_edge(ci, SUPPORT_EDGE, xi, v, conf, why, src_type, prov, True))
            else:  # contradicts
                contradicting.append(ev)
                new_contra_targets.append(xi)
                label = CONTRADICT_EDGE.get(xcls)
                if label and legal(label, "SustainabilityClaim", xcls):
                    new_edges.append(_mk_edge(ci, label, xi, v, conf, why, src_type, prov, None))

        # ---- 6d deterministic signals ----
        structural = structural_contradiction(g, ci, issuer_idx, new_contra_targets)
        gap = kpi_gap_for_claim(ctoks, kpi_gaps)
        indep_support = [e for e in supporting if e.get("independent")]

        # ---- 6e assessment (evidence links + structural only; kpi_gap is advisory, §6.5) ----
        if contradicting or structural:
            assessment = "appears_contradicted"
        elif indep_support:
            assessment = "appears_supported"
        else:
            assessment = "unverified_insufficient_evidence"
        assess_hist[assessment] += 1

        caveats = ["No ground-truth greenwashing label exists; this is an advisory opinion."]
        if not conduct:
            caveats.append("No independent (news) conduct evidence exists for this issuer.")
        elif not candidates:
            caveats.append("No topically-related independent evidence was found for this claim.")
        if adjud is None or not adjud.enabled:
            caveats.append("LLM adjudication was not run; assessment rests on deterministic signals only.")
        elif candidates and not adjudicated_here and budget_hit:
            caveats.append("This claim's candidate evidence exceeded the adjudication budget and was not evaluated.")
        if any(e.get("date_uncertain") for e in contradicting + indep_support):
            caveats.append("At least one evidence item has an uncertain publish date.")
        if contradicting and indep_support:
            caveats.append("Evidence is mixed (both supporting and contradicting items found).")
        if gap:
            caveats.append("A KPI numeric-gap signal was detected (advisory, not conclusive on its own).")

        dossiers.append({
            "claim_id": props(cnode).get("claim_id"),
            "claim_node_index": ci,
            "claim_text": ctext,
            "claim_source_type": props(cnode).get("source_type", "report"),
            "year": cyear,
            "assessment": assessment,
            "assessment_is_advisory": True,
            "supporting_evidence": indep_support,
            "flagged_non_independent_support": [e for e in supporting if not e.get("independent")],
            "contradicting_evidence": contradicting,
            "signals": {"structural_contradiction": structural, "kpi_gap": gap},
            "caveats": caveats,
        })

    # ---- stats ----
    stats = {
        "issuer": {"ticker": args.ticker, "node_index": issuer_idx,
                   "name": props(g.nodes[issuer_idx]).get("name")},
        "claims": len(claim_idxs),
        "conduct_pool": {"total": len(conduct), "by_class": dict(conduct_by_cls)},
        "retrieval": {"claims_with_candidates": claims_with_cands,
                      "candidate_pairs": pairs_total,
                      "avg_candidates_per_claim": round(pairs_total / max(1, len(claim_idxs)), 2)},
        "kpi_gap_signals": len(kpi_gaps),
        "assessments": dict(assess_hist),
        "linking_edges_written": len(new_edges),
        "edges_by_provider": dict(Counter(e["properties"].get("llm_provider") for e in new_edges)),
        "llm": {"pairs_adjudicated": llm_pairs, "budget": args.max_llm_pairs,
                **(adjud.summary() if adjud else {"active": False, "providers": []})},
        "params": {"top_k": args.top_k, "window_before": args.window_before,
                   "window_after": args.window_after, "no_llm": args.no_llm, "dry_run": args.dry_run},
        "coverage_caveat": ("Thin independent conduct — absence of contradiction is NOT exoneration "
                            "(docs/SYSTEM_DESIGN.md §8.3)."),
    }

    logger.info("\n=== Cross-check summary ===\n" + json.dumps(stats, indent=2, ensure_ascii=False))

    if args.dry_run:
        logger.info("Dry run — no files written, no edges persisted.")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.ticker.lower()
    (args.out_dir / f"{prefix}_claim_assessments.json").write_text(
        json.dumps(dossiers, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / f"{prefix}_crosscheck_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "crosscheck_edges.json").write_text(
        json.dumps(new_edges, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {len(dossiers)} dossiers + {len(new_edges)} linking edges to {args.out_dir}")

    if args.to_neo4j and new_edges:
        _write_back_neo4j(new_edges, args)


def _mk_edge(subj: int, pred: str, obj: int, verdict: str, conf: float, why: str,
             ev_source_type: Optional[str], provider: Optional[str],
             independent: Optional[bool]) -> Dict[str, Any]:
    p = {"llm_verdict": verdict, "confidence": conf, "rationale": why,
         "evidence_source_type": ev_source_type, "llm_provider": provider,
         "llm_suggested": True, "recorded_at": datetime.now(timezone.utc).isoformat()}
    if independent is not None:
        p["independent"] = independent
    return {"subject": subj, "predicate": pred, "object": obj, "properties": p}


def _write_back_neo4j(new_edges: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    """Optional: MERGE the advisory edges into Neo4j, matching nodes on the loader's
    `_node_key = "n{index}"` / `:_Entity` convention (load_graph_to_neo4j.py)."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("neo4j driver not installed; skipping --to-neo4j.")
        return
    load_dotenv(REPO_ROOT / ".env")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
    user = os.getenv("NEO4J_USER", "greenwashing")
    pwd = os.getenv("NEO4J_PASSWORD", "nammovuivui")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    written = 0
    with driver.session(database=args.database) as sess:
        for e in new_edges:
            q = (
                f"MATCH (s:_Entity {{_node_key:$sk}}), (t:_Entity {{_node_key:$tk}}) "
                f"MERGE (s)-[r:`{e['predicate']}` {{llm_suggested:true, _edge_key:$ek}}]->(t) "
                f"SET r += $props"
            )
            sess.run(q, sk=f"n{e['subject']}", tk=f"n{e['object']}",
                     ek=f"{e['subject']}-{e['predicate']}-{e['object']}", props=e["properties"])
            written += 1
    driver.close()
    logger.info(f"Neo4j write-back: MERGEd {written} advisory edges (llm_suggested=true).")


def main() -> None:
    p = argparse.ArgumentParser(description="Step 6 / P4 — cross-check claims vs conduct (advisory).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--ticker", type=str, default="AAA")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--window-before", type=int, default=DEFAULT_WINDOW_BEFORE)
    p.add_argument("--window-after", type=int, default=DEFAULT_WINDOW_AFTER)
    p.add_argument("--max-llm-pairs", type=int, default=DEFAULT_MAX_LLM_PAIRS)
    p.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model id (primary).")
    p.add_argument("--openai-model", type=str, default=DEFAULT_OPENAI_MODEL, help="OpenAI model id (fallback).")
    p.add_argument("--provider-order", type=str, default=DEFAULT_PROVIDER_ORDER,
                   help="Comma-separated adjudication preference, e.g. 'gemini,openai' or 'openai'.")
    p.add_argument("--max-workers", type=int, default=8, help="Concurrent adjudication workers.")
    p.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT)
    p.add_argument("--embed", action="store_true",
                   help="(reserved) embedding re-rank of candidates; off by default.")
    p.add_argument("--no-llm", action="store_true", help="Deterministic signals only (no adjudication).")
    p.add_argument("--dry-run", action="store_true", help="--no-llm and write nothing (offline preview).")
    p.add_argument("--to-neo4j", action="store_true", help="Also MERGE advisory edges into Neo4j.")
    p.add_argument("--database", default=None, help="Neo4j database for --to-neo4j (default: user home db).")
    args = p.parse_args()

    args.provider_order = [s.strip().lower() for s in args.provider_order.split(",") if s.strip()]
    if args.dry_run:
        args.no_llm = True
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run resolve_entities.py first)")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return
    run(args)


if __name__ == "__main__":
    main()
