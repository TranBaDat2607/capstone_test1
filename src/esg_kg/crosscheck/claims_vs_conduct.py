"""Step 6 / P4 — cross-check reported ESG claims against news conduct.

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
  6b  adjudicate each (claim, candidate) pair  — REQUIRED. LLM structured output
      via Gemini or DeepSeek, whichever --provider-order names (a swappable
      choice, not a cascade); the run aborts up front if no provider is
      available — there is no deterministic fallback.
  6c  write schema-legal linking edges         — verifiedBy / contradictedBy /
      contradictedByMedia, each stamped llm_suggested=true (attributable, re-runnable)
  6c-guard  self-verification guard            — a company-owned domain never creates
      a verifiedBy edge (independence, §6.4)
  6d  dossier + advisory assessment            — evidence + rationale + caveats

Design decisions (docs/SYSTEM_DESIGN.md, plan glistening-hopping-galaxy):
  * LLM-only: adjudication is mandatory. Quota/billing limits are managed via
    --max-llm-pairs, not by falling back to a deterministic-only mode.
  * deterministic retrieval by default; embeddings (--embed) are optional.
  * 2026-08-04: OpenAI support was removed outright (no fallback) once Gemini
    came back from billing-block — see core/llm.py's docstring for that history.
  * 2026-08-06: DeepSeek V4 Flash (`core.llm._DeepSeekProvider`) was added as a
    SWAPPABLE alternative, not a repeat of the OpenAI episode: Gemini stays the
    working default, DeepSeek is opt-in via `--provider-order deepseek`. One
    provider is normally active per run; `--provider-order` still accepts a
    comma list if a cascade is ever wanted, but that isn't the intended use.
  * 2026-08-06 (later same day): OpenAI (`core.llm._OpenAIProvider`) was
    RE-ADDED, at the user's explicit request, as a third opt-in alternative for
    THIS stage only — `--provider-order openai`. Needs `OPENAI_API_KEY` in
    `.env`; `OPENAI_MODEL` overrides the default model. Not a reversal of the
    2026-08-04 removal note above: this is the same deliberate-swap shape as
    the DeepSeek addition, not a forced fallback, and it is NOT wired into
    align_claims/extract_triples/fix_triples/entities (their own --provider
    flags still only accept gemini/deepseek).

Run from the repo root:
  python src/step07_crosscheck_claims_vs_conduct.py --dry-run   (old tree, still runs)
  python src/run.py claims_vs_conduct --dry-run          (this tree)
Equivalently, from inside src/: python -m esg_kg.crosscheck.claims_vs_conduct --dry-run

--------------------------------------------------------------------------------------
Moved verbatim from src/step07_crosscheck_claims_vs_conduct.py (Model A: that file still
exists and still runs). NO logic line changed. What differs:

  * the docstring and the import block — every symbol this stage used to take from a
    sibling STAGE now comes from the kernel: `REPO_ROOT` <- core.paths (since step01's
    move), `load_schema_sets` <- core.schema (since step03), `normalize_name`/
    `name_tokens` <- core.naming (since step04 was confirmed a dissolved hub), and
    `_Provider`/`_OpenAIProvider` <- core.llm — that slice (2026-07-27) EXTRACTED these
    two classes FROM this very file, so this migration is the one that finally imports
    them back rather than re-defining them.
  * one DEAD import from the old file is not carried over: `RateLimiter` (from step02).
    It was never referenced directly in step07 — only the provider's own `__init__`
    constructs one, and that class is imported pre-built from core.llm. Same shape
    the 05d slice found with its own dead `RateLimiter` import.
  * 2026-08-04: `_OpenAIProvider` was removed outright from core.llm (no OpenAI
    fallback anywhere in this project any more) and replaced here with
    `_GeminiProvider` — same `call(system, user) -> str` contract, so nothing else
    in this file's Adjudicator cascade needed to change shape.

WHAT MUST NOT BE "TIDIED" HERE
`node_text` below is NOT the same function as `esg_kg.resolve.align_claims.node_text`
despite the shared name: THIS one takes a NODE and dispatches on its `class`;
align_claims' takes a PROPERTIES DICT. Unifying them would silently rewrite
align_claims' paid classification prompt. Keep them separate.

`ADJUDICATE_SYSTEM` is paid behaviour, not prose — rewording it still "works" at runtime
while changing every verdict this stage has ever produced, so
`test/test_esg_kg_crosscheck.py` pins it byte-for-byte.

`Adjudicator` stays HERE, not in core/llm.py, exactly as that module's docstring always
said it would: it is prompt text + verdict parsing + the provider cascade — stage logic,
not kernel. Migrating this stage is what finally unblocks step08 (needs `node_text`) — see
PIPELINE.md §2.1. (It also unblocked `step10`, via the same lazy-import pattern, until
that stage was removed from the project outright on 2026-07-28 — DESIGN.md §4.3.)

THE IN-PLACE-PATCH QUESTION (PIPELINE.md §3) DOES NOT APPLY
This stage reads `resolved_graph.json` (the *previous* stages' output) and writes to a
different directory (`graph_output/crosscheck/`) — it never meets its own past output,
so the real-corpus equivalence arm is non-vacuous by construction, the same shape step03's
migration established.

A DEFECT FIXED IN A FOLLOW-UP COMMIT, BOTH TREES
`_parse_verdict` had the same shape of bug `parse_reply` had in step05d before a308608:
`json.loads("[]")` succeeds (returns a list, not a dict), and the next line called
`.get()` on it, raising `AttributeError`. Here the blast radius was smaller — the call
sits inside `Adjudicator.adjudicate`'s own try/except, so it degraded to "no verdict for
this pair" rather than losing an entire run's adjudications — but it still misfiled an
oddly-shaped-but-parseable reply as a *provider failure* instead of an unusable-reply
no-op. Following the same order step05d's fix did, the migration moved the stage AS IS
first (verbatim, bug included); the `isinstance(out, dict)` guard landed in a separate
commit, in both trees, per DESIGN.md §5.3.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
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

from esg_kg.core.llm import (
    DEEPSEEK_DEFAULT_MODEL,
    DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    _DeepSeekProvider,
    _GeminiProvider,
    _OpenAIProvider,
    _Provider,
)
from esg_kg.core.llm_cache import ContentCache
from esg_kg.core.naming import name_tokens, normalize_name
from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.schema import load_schema_sets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "crosscheck"
# DEFAULT_MODEL comes from esg_kg.core.llm (GEMINI_MODEL env var, default
# gemini-2.5-flash-lite) — see that module's docstring.
DEFAULT_PROVIDER_ORDER = "gemini"
DEFAULT_RATE_LIMIT = 10
DEFAULT_MAX_LLM_PAIRS = 300
DEFAULT_TOP_K = 8
DEFAULT_WINDOW_BEFORE = 1     # conduct may predate the claim year by at most this
DEFAULT_WINDOW_AFTER = 50     # ...and may follow it by "any" plausible number of years
DEFAULT_MIN_TOPIC_OVERLAP = 2  # a single shared token is too weak a retrieval signal on
                                # its own (even VN-aware, a lone shared word can still be
                                # coincidental) — require at least 2. Indicator-axis pairs
                                # (tier="indicator") bypass this gate entirely by design.
DEFAULT_CACHE = DEFAULT_OUT_DIR / "adjudication_cache.json"  # issue #9: per-issuer, keyed
                                                               # by (claim_text, evidence_text,
                                                               # evidence_meta) content

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

# Tightened 2026-08-07 (Layer 2 of the ACG/AGG contamination fix): production rationale
# text was generalizing from ONE adverse event to the company's ENTIRE trustworthiness —
# e.g. "the company was fined for stock manipulation, therefore it likely didn't really
# appoint an independent vote-counter either" — a halo inference the old wording's own
# example ("a green/responsible claim vs a penalty... in the same period") invited. The
# retrieval-side fix (issuer scoping + VN-aware topic tokens) removes the WRONG-COMPANY
# case; this prompt change targets the remaining SAME-COMPANY-but-different-topic case,
# which retrieval alone cannot rule out.
ADJUDICATE_SYSTEM = (
    "You assess greenwashing evidence for a Vietnamese ESG knowledge graph. You are given "
    "ONE ESG claim a company made in its own report, and ONE piece of independent evidence "
    "about the company (usually a news item). Decide, using ONLY the two texts, whether the "
    "evidence SUPPORTS the claim, CONTRADICTS it, or is IRRELEVANT.\n"
    "Rules:\n"
    "- Treat the evidence as independent conduct ('what the company did'), not as a restatement "
    "of the claim.\n"
    "- 'contradicts' means the evidence is in tension with the SAME SPECIFIC topic, process, or "
    "activity the claim describes (e.g. a claim about emissions vs an emissions violation; a claim "
    "about a specific governance procedure vs evidence that THAT SAME procedure failed or was "
    "skipped). A general negative fact about the company (an unrelated penalty, violation, or "
    "controversy on a different topic) does NOT by itself contradict a claim about a different, "
    "specific topic — do not infer 'the company is untrustworthy in general, therefore this claim "
    "is false' from one adverse event unless the evidence is actually about the same matter as "
    "the claim.\n"
    "- 'supports' means the evidence independently corroborates that SAME specific claim (e.g. a "
    "third-party verification, certification, or an observed metric consistent with the claim).\n"
    "- Prefer 'irrelevant' when the evidence is about a different topic than the claim — even if "
    "both are negative, both are positive, or both broadly concern ESG/governance — or when the "
    "evidence is neutral financial/market coverage. Do not guess.\n"
    "- The texts are Vietnamese. confidence is 0.0-1.0. Ground the rationale in the evidence text.\n"
    "## OUTPUT LANGUAGE\n"
    "Write `rationale` in VIETNAMESE, with full diacritics, matching the language of the claim/evidence "
    "texts. Do NOT translate into English. Do NOT strip diacritics (khong duoc bo dau). This rule does "
    "NOT apply to `verdict` (a fixed English label: supports/contradicts/irrelevant) or `confidence` "
    "(a number)."
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


def node_ticker(node: Dict[str, Any]) -> Optional[str]:
    """The issuer ticker a conduct node's crawl belongs to, read from `source_doc`
    (`esg_news_crawler` names every crawled doc "<TICKER>__<domain>__<hash>", verified
    100% coverage on the live graph's news-sourced conduct nodes). Returns None when
    source_doc is absent/unparseable — synthetic fixtures and any future conduct source
    that doesn't carry this convention — so retrieval treats "unknown origin" as
    "don't exclude it" rather than "wrong company"; only a POSITIVELY MISMATCHED ticker
    is filtered out (§6a's "same issuer", never actually enforced before this)."""
    src = str(props(node).get("source_doc", "") or "")
    if "__" not in src:
        return None
    ticker = src.split("__", 1)[0].strip().upper()
    return ticker or None


def date_uncertain(node: Dict[str, Any]) -> bool:
    p = props(node)
    if p.get("date_uncertain") in (True, "true", "True"):
        return True
    # A bare "YYYY-01-01" is the preprocessor's placeholder for an unknown day/month.
    return bool(re.fullmatch(r"(19|20)\d{2}-01-01", str(p.get("date", "") or "")))


_word_tokenize = None  # lazy-bound on first call, see _vn_segments


def _vn_segments(text: str) -> List[str]:
    """Word-level VN segments via underthesea (already a hard dependency — same tool
    `data_processing/sentence_splitter.py` uses, imported the same guarded way). Bound
    lazily rather than at module import time: `import underthesea` has the side effect of
    attaching a handler to the ROOT logger, which makes this module's own
    `logging.basicConfig(level=logging.INFO)` below a silent no-op (basicConfig only
    configures root when it has no handlers yet) if underthesea were imported above it —
    every INFO-level progress log in this stage would vanish. Falls back to a plain
    whitespace split if the tokenizer errors on unusual input — retrieval must never crash
    on that."""
    global _word_tokenize
    if _word_tokenize is None:
        from underthesea import word_tokenize as _wt
        _word_tokenize = _wt
    try:
        return _word_tokenize(text or "")
    except Exception:
        return (text or "").split()


def topic_tokens(text: str, extra: Optional[Set[str]] = None) -> Set[str]:
    """Topic tokens for retrieval overlap. Each underthesea segment is normalize_name()'d
    and kept WHOLE (space-joined for multi-word segments), not exploded into unigrams —
    that is what stops an unrelated VN compound from colliding with an unrelated word that
    only shares one syllable. Concretely: "cổ phiếu" (stock) normalizes to "co phieu" and
    survives as ONE token, distinct from the bare "phieu" that "phiếu bầu" (ballot)
    contributes — plain unigram splitting used to strip "cổ" as a stopword and leave the
    orphan "phieu", which is exactly how an unrelated company's stock-manipulation Penalty
    got matched against a ballot-counting governance claim in production (2026-08-07).
    A segment is dropped only when EVERY one of its words is itself a STOPWORD (e.g. "công
    ty" -> "cong"+"ty", both boilerplate) — one non-boilerplate word is enough to keep the
    whole segment, same threshold plain name_tokens applied per-word before."""
    toks: Set[str] = set()
    for seg in _vn_segments(text):
        norm = normalize_name(seg)
        words = norm.split()
        if not words or all(w in STOPWORDS for w in words):
            continue
        if len(norm) >= 3:
            toks.add(norm)
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
# LLM adjudication (single provider: Gemini).
#
# Does the SAME narrow, grounded 3-way task regardless of provider. A provider that
# fails 3x with no success (e.g. a 403 billing block) is disabled, so the run still
# finishes (with whatever calls already succeeded) rather than hanging.
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
    # Valid JSON of the wrong SHAPE ('[]', '"txt"', '42') must be refused like any other
    # unusable reply. Without this the `.get` below raised AttributeError, and since that
    # call sits inside Adjudicator.adjudicate's own try/except, it was misfiled as a
    # provider *failure* instead of an unusable-reply no-op.
    if not isinstance(out, dict):
        return None
    if out.get("verdict") not in ("supports", "contradicts", "irrelevant"):
        return None
    out["confidence"] = float(out.get("confidence", 0.0) or 0.0)
    out.setdefault("rationale", "")
    return out


class Adjudicator:
    """A cascade of LLM providers with per-provider graceful failure. `adjudicate` tries
    each enabled provider in preference order and returns the first parsed verdict, tagged
    with the provider that produced it. When one provider dies (e.g. a 403), the next takes
    over automatically; if all die, the caller falls back to deterministic signals.

    `cache` (GitHub issue #9, `core.llm_cache.ContentCache`) is optional and keyed on the
    content actually sent — `(claim_text, evidence_text, evidence_meta)` — not on the
    (claim, candidate) node-index pair, so two DIFFERENT pairs that happen to carry the
    IDENTICAL text (e.g. a boilerplate claim sentence repeated across two report years,
    or two claims retrieved against the same conduct candidate) share one paid call,
    within a single run as well as across re-runs. Only a DEFINITIVE outcome is cached —
    a real verdict, or a confirmed-unparseable reply from a provider that actually
    answered — never a pure provider failure/unavailability, so a transient 403 or a
    not-yet-configured API key can't freeze "no verdict" into the cache forever.

    CACHE KEY IS SALTED WITH THE PROMPT + PROVIDER/MODEL (thesis_review.md P1, fixed
    2026-08-13). Before this, the key was content-only — no prompt, no model, no
    provider — so the 2026-08-07 ADJUDICATE_SYSTEM tightening (halo-reasoning guard)
    never reached a single already-cached verdict: every pair whose (claim_text,
    evidence_text, evidence_meta) had been seen before the prompt change kept replaying
    the OLD prompt's answer forever. `_cache_salt` is
    `sha256(ADJUDICATE_SYSTEM)[:12] + "|" + "<name>:<model>,..."` for the enabled
    provider cascade, computed once at construction time and passed as the FIRST part
    to every `cache.get`/`cache.put` call — so a byte-for-byte prompt edit, or a
    provider/model change, changes every key and a legacy unsalted cache file (fewer
    parts hashed) can never collide with a salted key by construction."""

    def __init__(self, model: str, rate_limit: int, order: List[str],
                 api_key: Optional[str] = None,
                 cache: Optional[ContentCache] = None) -> None:
        # override=True so the repo .env is authoritative — a stale shell GEMINI_API_KEY
        # must not shadow the key the user edits in .env. Only applies when
        # api_key is not explicitly given (a one-off override).
        if api_key is None:
            load_dotenv(REPO_ROOT / ".env", override=True)
        # `model or <provider's own default>`, never the caller's raw `model`: with
        # a single positional argument shared across the whole registry, a Gemini
        # model id passed for `--provider-order deepseek` would otherwise be sent
        # straight to DeepSeek's API (see core.llm.build_llm_provider's docstring).
        registry = {
            "gemini": lambda: _GeminiProvider(model or DEFAULT_MODEL, rate_limit, api_key=api_key),
            "deepseek": lambda: _DeepSeekProvider(model or DEEPSEEK_DEFAULT_MODEL, rate_limit, api_key=api_key),
            # 2026-08-06: re-added at the user's explicit request, opt-in via
            # --provider-order openai — see core/llm.py's docstring for why this
            # isn't a repeat of the 2026-08-04 OpenAI removal.
            "openai": lambda: _OpenAIProvider(model or OPENAI_DEFAULT_MODEL, rate_limit, api_key=api_key),
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
        self.cache = cache
        # P1 fix: bind cache entries to the exact prompt + provider/model that could
        # have produced them. Order matters (it's part of the cascade), so this is
        # NOT sorted — a reordered --provider-order is a legitimately different run.
        prompt_hash = hashlib.sha256(ADJUDICATE_SYSTEM.encode("utf-8")).hexdigest()[:12]
        provider_sig = ",".join(f"{p.name}:{p.model}" for p in self.providers)
        self._cache_salt = f"{prompt_hash}|{provider_sig}"
        if self.enabled:
            logger.info(f"Adjudicator ready: providers = {[p.name for p in self.providers]}")
        else:
            logger.warning("No LLM provider available.")

    def adjudicate(self, claim_text: str, evidence_text: str, evidence_meta: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if self.cache is not None:
            cached, hit = self.cache.get(self._cache_salt, claim_text, evidence_text, evidence_meta)
            if hit:
                return cached
        user = (
            f"CLAIM (company report): \"{claim_text}\"\n\n"
            f"EVIDENCE ({evidence_meta}): \"{evidence_text}\"\n\n"
            "Return only JSON: verdict (supports|contradicts|irrelevant), confidence (0-1), rationale."
        )
        result: Optional[Dict[str, Any]] = None
        answered = False  # a provider returned WITHOUT raising, i.e. gave a real reply
        for p in self.providers:
            if not p.enabled:
                continue
            try:
                raw = p.call(ADJUDICATE_SYSTEM, user)
                p.calls += 1
                answered = True
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
        if self.cache is not None and answered:
            self.cache.put(self._cache_salt, claim_text, evidence_text, evidence_meta, value=result)
        return result

    def summary(self) -> Dict[str, Any]:
        return {"active": self.enabled,
                "providers": [{"name": p.name, "enabled": p.enabled,
                               "calls_ok": p.calls, "failures": p.failures} for p in self.providers]}


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

    # ---- conduct pool (independent = news, SAME ISSUER only) ----
    # §6a always documented "same issuer + VN topic overlap + temporal window" but the
    # issuer half was never enforced — the pool spanned every ticker's crawled news, so a
    # generic topic-token collision (e.g. "phieu" shared between "phiếu bầu"/ballot and
    # "cổ phiếu"/stock once "cổ" is stripped as a stopword) could pull another company's
    # penalty into this issuer's dossier. Scope by source_doc's "<TICKER>__" prefix now;
    # a node with no parseable source_doc (synthetic fixtures, non-crawler sources) is
    # kept rather than dropped — see node_ticker's docstring.
    ticker_u = args.ticker.upper()
    conduct = [i for i, n in enumerate(g.nodes)
               if n.get("class") in CONDUCT_CLASSES and props(n).get("source_type") == "news"
               and node_ticker(n) in (None, ticker_u)]
    conduct_by_cls = Counter(g.cls(i) for i in conduct)
    logger.info(f"Conduct pool (source_type=news, issuer={ticker_u}): "
                f"{len(conduct)} nodes {dict(conduct_by_cls)}")

    # pre-tokenize the conduct pool once
    ctok = {i: topic_tokens(node_text(g.nodes[i])) for i in conduct}

    # ---- indicator-axis index (tier-1 retrieval, docs/STANDARD_INDICATOR_AXIS.md §6) ----
    # A claim and a conduct node that hang off the SAME StandardIndicator are almost always
    # topically relevant to each other — the LLM then only has to decide supports/contradicts,
    # not relevance. This turns retrieval from a global token overlap into a 2-hop graph join:
    #   claim --alignsWithIndicator--> (StandardIndicator) <--measuredUnder-- conduct(news)
    ind_conduct: Dict[int, List[int]] = defaultdict(list)
    for si in conduct:
        for pred, obj in g.out.get(si, []):
            if pred == "measuredUnder":
                ind_conduct[obj].append(si)
    claim_inds: Dict[int, List[int]] = defaultdict(list)
    for ci in claim_idxs:
        for pred, obj in g.out.get(ci, []):
            if pred == "alignsWithIndicator":
                claim_inds[ci].append(obj)
    n_indicator_links = sum(len(v) for v in claim_inds.values())
    logger.info(f"Indicator axis: {n_indicator_links} claim→indicator link(s); "
                f"{sum(len(v) for v in ind_conduct.values())} indicator←conduct(news) link(s)")

    # Score boost so an indicator-joined pair always outranks a token-overlap pair for the LLM
    # budget (all_pairs is sorted by score descending at :447). It is deliberately large.
    INDICATOR_BOOST = 1000
    tier_of: Dict[Tuple[int, int], str] = {}

    # LLM adjudication is mandatory — no deterministic fallback. Abort up front if no
    # provider is available so the run never silently degrades into a weaker mode.
    cache_path = getattr(args, "cache", None)
    cache = ContentCache(cache_path) if cache_path else None
    adjud = Adjudicator(args.model, args.rate_limit, args.provider_order, cache=cache)
    if not adjud.enabled:
        logger.error("No LLM provider available (need GEMINI_API_KEY, DEEPSEEK_API_KEY "
                     "and/or OPENAI_API_KEY in .env, matching --provider-order) — "
                     "aborting: this pipeline requires LLM adjudication.")
        return

    # ---- 6a retrieval: candidate conduct per claim (deterministic, cheap) ----
    min_overlap = getattr(args, "min_topic_overlap", DEFAULT_MIN_TOPIC_OVERLAP)
    cand_of: Dict[int, List[int]] = {}
    all_pairs: List[Tuple[int, int, int]] = []  # (overlap, claim_idx, conduct_idx)
    for ci in claim_idxs:
        ctoks = topic_tokens(node_text(g.nodes[ci]), kw.get(ci))
        cyear = node_year(g.nodes[ci])
        scored: List[Tuple[int, int, int]] = []  # (overlap, recency, conduct_idx)
        for xi in conduct:
            overlap = len(ctoks & ctok[xi])
            if overlap < min_overlap:
                continue
            xyear = node_year(g.nodes[xi])
            if cyear is not None and xyear is not None and not date_uncertain(g.nodes[xi]):
                if xyear < cyear - args.window_before or xyear > cyear + args.window_after:
                    continue
            scored.append((overlap, xyear or 0, xi))

        # Tier 1: inject indicator-joined conduct with a boosted score. These bypass the
        # token-overlap gate (a claim and a KPI on the same indicator can share zero tokens —
        # "giảm phát thải" vs "12.450 tCO2e") but keep the temporal window unless date-uncertain.
        token_xis = {xi for _, _, xi in scored}
        for si in claim_inds.get(ci, []):
            for xi in ind_conduct.get(si, []):
                if xi in token_xis:
                    # already a token candidate — promote it to tier-1 priority
                    scored = [(ov + INDICATOR_BOOST if x == xi else ov, y, x) for ov, y, x in scored]
                else:
                    xyear = node_year(g.nodes[xi])
                    if cyear is not None and xyear is not None and not date_uncertain(g.nodes[xi]):
                        if xyear < cyear - args.window_before or xyear > cyear + args.window_after:
                            continue
                    scored.append((INDICATOR_BOOST, xyear or 0, xi))
                    token_xis.add(xi)
                tier_of[(ci, xi)] = "indicator"

        scored.sort(key=lambda t: (-t[0], -t[1]))
        top = scored[: args.top_k]
        cand_of[ci] = [xi for _, _, xi in top]
        all_pairs.extend((ov, ci, xi) for ov, _, xi in top)
    claims_with_cands = sum(1 for ci in claim_idxs if cand_of[ci])
    pairs_total = len(all_pairs)

    # ---- 6b adjudication: highest-overlap pairs first, up to the budget, concurrent ----
    verdicts: Dict[Tuple[int, int], Dict[str, Any]] = {}
    llm_pairs = 0
    if pairs_total:
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
    budget_hit = pairs_total > args.max_llm_pairs

    # ---- 6c assembly per claim ----
    dossiers: List[Dict[str, Any]] = []
    new_edges: List[Dict[str, Any]] = []
    assess_hist: Counter = Counter()
    for ci in claim_idxs:
        cnode = g.nodes[ci]
        ctext = node_text(cnode)
        cyear = node_year(cnode)
        candidates = cand_of[ci]

        supporting: List[Dict[str, Any]] = []
        contradicting: List[Dict[str, Any]] = []
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
                  "provider": prov, "date_uncertain": date_uncertain(xnode),
                  "retrieval_tier": tier_of.get((ci, xi), "token_overlap")}

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
                label = CONTRADICT_EDGE.get(xcls)
                if label and legal(label, "SustainabilityClaim", xcls):
                    new_edges.append(_mk_edge(ci, label, xi, v, conf, why, src_type, prov, None))

        indep_support = [e for e in supporting if e.get("independent")]

        # ---- 6d assessment (LLM evidence links only) ----
        if contradicting:
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
        if candidates and not adjudicated_here:
            reason = "exceeded the adjudication budget" if budget_hit else "could not be adjudicated (LLM provider failure)"
            caveats.append(f"This claim's candidate evidence {reason} and was not evaluated.")
        if any(e.get("date_uncertain") for e in contradicting + indep_support):
            caveats.append("At least one evidence item has an uncertain publish date.")
        if contradicting and indep_support:
            caveats.append("Evidence is mixed (both supporting and contradicting items found).")

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
                      "avg_candidates_per_claim": round(pairs_total / max(1, len(claim_idxs)), 2),
                      "indicator_tier_pairs": sum(1 for (ci, xi) in tier_of
                                                  if xi in cand_of.get(ci, [])),
                      "claims_with_indicator_link": sum(1 for ci in claim_idxs if claim_inds.get(ci))},
        "assessments": dict(assess_hist),
        "linking_edges_written": len(new_edges),
        "edges_by_provider": dict(Counter(e["properties"].get("llm_provider") for e in new_edges)),
        "llm": {"pairs_adjudicated": llm_pairs, "budget": args.max_llm_pairs, **adjud.summary()},
        "params": {"top_k": args.top_k, "window_before": args.window_before,
                   "window_after": args.window_after, "dry_run": args.dry_run},
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
    if cache is not None:
        cache.save()

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
    `_node_key = "n{index}"` / `:_Entity` convention (step06_load_graph_to_neo4j.py)."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("neo4j driver not installed; skipping --to-neo4j.")
        return
    load_dotenv(REPO_ROOT / ".env")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
    user = os.getenv("NEO4J_USER", "greenwashing")
    pwd = os.getenv("NEO4J_PASSWORD", "changeme")
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
    p.add_argument("--min-topic-overlap", type=int, default=DEFAULT_MIN_TOPIC_OVERLAP,
                   help="Minimum shared VN topic-token count for a token-overlap candidate "
                        "(indicator-axis pairs bypass this gate).")
    p.add_argument("--max-llm-pairs", type=int, default=DEFAULT_MAX_LLM_PAIRS)
    p.add_argument("--model", type=str, default=None,
                   help="Model id; defaults to the chosen provider's own default "
                        "(GEMINI_MODEL for gemini, DEEPSEEK_MODEL for deepseek, "
                        "OPENAI_MODEL for openai) when omitted.")
    p.add_argument("--provider-order", type=str, default=DEFAULT_PROVIDER_ORDER,
                   help="Comma-separated adjudication preference: gemini, deepseek, openai. "
                        "A swappable choice, not a required fallback chain — set to "
                        "e.g. 'deepseek' or 'openai' alone to use that provider instead "
                        "of Gemini. 'openai' needs OPENAI_API_KEY in .env.")
    p.add_argument("--max-workers", type=int, default=8, help="Concurrent adjudication workers.")
    p.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT)
    p.add_argument("--embed", action="store_true",
                   help="(reserved) embedding re-rank of candidates; off by default.")
    p.add_argument("--dry-run", action="store_true",
                   help="Still runs LLM adjudication and prints stats, but writes nothing.")
    p.add_argument("--to-neo4j", action="store_true", help="Also MERGE advisory edges into Neo4j.")
    p.add_argument("--database", default=None, help="Neo4j database for --to-neo4j (default: user home db).")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE,
                   help="Adjudication cache (issue #9); a re-run reuses it instead of paying again.")
    p.add_argument("--no-cache", action="store_true",
                   help="Ignore the adjudication cache (forces every pair to ask the model again).")
    args = p.parse_args()

    if args.no_cache:
        args.cache = None
    args.provider_order = [s.strip().lower() for s in args.provider_order.split(",") if s.strip()]
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run step05_resolve_entities.py first)")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return
    run(args)


if __name__ == "__main__":
    main()
