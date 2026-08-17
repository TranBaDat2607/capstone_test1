#!/usr/bin/env python3
"""
Stage 13 — re-adjudicate legacy-prompt pairs under the CURRENT prompt.

WHY THIS EXISTS
`replay_adjudications` (stage 12) recovered 4,259 paid verdicts and found they are not
one dataset but two. The P1 fix (`067b93f`, 2026-08-13) salted the adjudication cache key
with `sha256(ADJUDICATE_SYSTEM)[:12] + "|" + "<provider>:<model>"`, so:

    unsalted 3-part key  ->  the OLD, pre-halo-guard prompt
    salted 4-part key    ->  the prompt in the tree today

Measured on the pairs carrying both: they disagree **6.1% overall but 43.8% (21/48) once
either verdict is non-`irrelevant`** — precisely the pairs a supports/contradicts
classifier trains on. Distilling a model on the merged set would teach it contradictory
labels for byte-identical text.

This stage closes the gap the cheap way: ask the CURRENT prompt about the legacy pairs
that are non-`irrelevant` and have no current verdict yet (182 of them today), instead of
re-adjudicating all 3,520. The `irrelevant` legacy majority is deliberately left alone —
it is 2,992 pairs, and stage-1 (relevant vs irrelevant) has plenty of signal without it.

THE SELECTION BIAS THIS INTRODUCES, STATED PLAINLY
Re-adjudicating only what the OLD prompt called supports/contradicts finds the pairs the
new prompt *demotes*, and can never find pairs the new prompt would *promote* out of
`irrelevant`. The halo guard made the prompt stricter, so demotions are the expected
direction and the bias is mostly benign for stage 2 — but stage 1's legacy `irrelevant`
labels remain unverified by the current prompt, and any paper text should say so rather
than describe the result as a clean single-generation relabelling.

WHY IT DELEGATES TO `Adjudicator`
The new verdicts are only useful if they are indistinguishable from ones step07 would
have produced. So this stage constructs the real `Adjudicator` and calls `.adjudicate()`:
the prompt, the verdict parsing, the provider cascade and the salted cache key are all
step07's. Nothing about the paid path is reimplemented here — this file only decides
WHICH pairs to ask about, and what to record afterwards.

WHY WRITING INTO THE LIVE CACHE IS SAFE, AND WANTED
New entries carry the current salt; legacy entries carry no salt. Different keys, so the
write is append-only in effect and no paid verdict is overwritten (pinned by
`test_existing_entries_survive`; a `.pre_readjudicate.bak` is taken first anyway, because
the file is worth thousands of paid calls and `ContentCache.save()` is not atomic).
Writing there is also the point: a later `claims_vs_conduct` run gets these verdicts free.

COST CONTROL
Every result is cached under the key `Adjudicator` itself computes, so a re-run is free
and an interrupted run resumes for free — the cache is checkpointed every
`--checkpoint-every` results so a crash never loses work already paid for. `--dry-run`
prints the target set and calls nothing; `--limit` caps the paid calls.

    python src/run.py readjudicate --dry-run       # what would be asked, and how much
    python src/run.py readjudicate                 # ~182 paid calls today
    python src/run.py replay_adjudications         # re-extract; the rows are now `current`
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from esg_kg.core.llm_cache import ContentCache
from esg_kg.core.paths import REPO_ROOT
from esg_kg.crosscheck.claims_vs_conduct import ADJUDICATE_SYSTEM, Adjudicator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_REPLAY = REPO_ROOT / "graph_output" / "replay" / "adjudicated_pairs.jsonl"
DEFAULT_CACHE = REPO_ROOT / "graph_output" / "crosscheck" / "adjudication_cache.json"
DEFAULT_OUT = REPO_ROOT / "graph_output" / "replay" / "readjudicated.jsonl"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "replay" / "readjudicate_stats.json"
DEFAULT_CHECKPOINT_EVERY = 25


def prompt_hash() -> str:
    """`Adjudicator.__init__`'s prompt component, from the LIVE prompt."""
    return hashlib.sha256(ADJUDICATE_SYSTEM.encode("utf-8")).hexdigest()[:12]


def select_targets(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The legacy pairs worth paying to re-ask about: non-`irrelevant`, and not already
    carrying a current-prompt verdict.

    Keyed on the three strings that ARE the cache key — (claim_text, evidence_text,
    evidence_meta) — not on node indices: two different node pairs can carry identical
    text and share one paid call, so an index-keyed selection would buy the same verdict
    twice. A pair whose legacy providers disagreed is kept, not skipped: that split is
    exactly the noise this stage resolves."""
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        k = (r["claim_text"], r["evidence_text"], r["evidence_meta"])
        slot = by_key.setdefault(k, {"claim_text": k[0], "evidence_text": k[1],
                                     "evidence_meta": k[2], "legacy_verdicts": {},
                                     "has_current": False,
                                     "claim_id": r.get("claim_id"),
                                     "evidence_class": r.get("evidence_class"),
                                     "evidence_domain": r.get("evidence_domain"),
                                     "evidence_year": r.get("evidence_year")})
        if r["prompt_generation"] == "current":
            slot["has_current"] = True
        else:
            slot["legacy_verdicts"][r.get("provider") or "?"] = r["verdict"]

    targets = []
    for slot in by_key.values():
        if slot["has_current"] or not slot["legacy_verdicts"]:
            continue
        if set(slot["legacy_verdicts"].values()) == {"irrelevant"}:
            continue
        slot.pop("has_current")
        targets.append(slot)
    return targets


def run(args: argparse.Namespace) -> Dict[str, Any]:
    replay_path = Path(args.replay)
    if not replay_path.exists():
        raise SystemExit(
            f"replay output not found: {replay_path}\n"
            "Run `python src/run.py replay_adjudications` first.")
    rows = [json.loads(l) for l in replay_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    targets = select_targets(rows)
    logger.info(f"{len(rows)} replay row(s) -> {len(targets)} target pair(s) "
                f"(legacy, non-irrelevant, no current verdict)")

    legacy_hist = Counter()
    for t in targets:
        vs = set(t["legacy_verdicts"].values())
        legacy_hist["|".join(sorted(vs))] += 1
    logger.info(f"legacy verdicts on the targets: {dict(legacy_hist)}")

    attempted = targets if args.limit is None else targets[: args.limit]
    if args.dry_run:
        chars = sum(len(t["claim_text"]) + len(t["evidence_text"]) + len(t["evidence_meta"])
                    for t in attempted)
        logger.info(f"Dry run — would make up to {len(attempted)} paid call(s) "
                    f"(~{chars:,} chars of pair text + the system prompt each). "
                    "Nothing called, nothing written.")
        return {"targets": len(targets), "attempted": len(attempted), "dry_run": True}

    cache_path = Path(args.cache)
    if cache_path.exists():
        # ContentCache.save() rewrites the whole file and is not atomic; this file is
        # worth thousands of paid calls, so take a copy before touching it.
        backup = cache_path.with_suffix(".json.pre_readjudicate.bak")
        shutil.copy2(cache_path, backup)
        logger.info(f"backed up {cache_path.name} -> {backup.name}")

    cache = ContentCache(cache_path)
    before = set(cache.entries)
    adjud = Adjudicator(args.model, args.rate_limit, args.provider_order, cache=cache)
    if not adjud.enabled:
        raise SystemExit(
            "No LLM provider available (need GEMINI_API_KEY in .env matching "
            "--provider-order) — aborting: this stage requires LLM adjudication.")
    logger.info(f"cache salt = {adjud._cache_salt}")

    results: List[Dict[str, Any]] = []
    done = 0

    def _one(t: Dict[str, Any]):
        was_cached = cache.get(adjud._cache_salt, t["claim_text"], t["evidence_text"],
                               t["evidence_meta"])[1]
        # `Adjudicator` disables a provider after 3 failures with 0 successes, and from
        # then on `.adjudicate()` returns None WITHOUT calling anything. Capturing the
        # flag first is what lets the stats separate "asked, reply unusable" from "never
        # asked" — conflating them once reported a dead run as 177 bad replies.
        enabled_before = adjud.enabled
        out = adjud.adjudicate(t["claim_text"], t["evidence_text"], t["evidence_meta"])
        return t, out, was_cached, enabled_before

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as exe:
        for t, out, was_cached, enabled_before in exe.map(_one, attempted):
            done += 1
            legacy = sorted(set(t["legacy_verdicts"].values()))
            verdict = (out or {}).get("verdict")
            if verdict:
                status = "cache_hit" if was_cached else "verdict"
            elif not enabled_before:
                status = "not_asked"
            else:
                status = "no_verdict"
            results.append({
                "status": status,
                "claim_id": t.get("claim_id"),
                "claim_text": t["claim_text"],
                "evidence_text": t["evidence_text"],
                "evidence_meta": t["evidence_meta"],
                "evidence_class": t.get("evidence_class"),
                "evidence_domain": t.get("evidence_domain"),
                "evidence_year": t.get("evidence_year"),
                "verdict": verdict,
                "confidence": (out or {}).get("confidence"),
                "rationale": (out or {}).get("rationale", ""),
                "provider": (out or {}).get("provider"),
                "prompt_generation": "current",
                "legacy_verdicts": t["legacy_verdicts"],
                "changed": (verdict is not None and [verdict] != legacy),
                "cache_hit": was_cached,
            })
            if done % args.checkpoint_every == 0:
                if cache.save():
                    logger.info(f"checkpoint: {done}/{len(attempted)} done, cache saved")
    cache.save()

    usable = [r for r in results if r["verdict"]]
    by_status = Counter(r["status"] for r in results)
    stats = {
        "targets": len(targets),
        "attempted": len(attempted),
        "llm_calls": by_status["verdict"] + by_status["no_verdict"],
        "cache_hits": by_status["cache_hit"],
        "verdicts": len(usable),
        # asked but came back without a verdict — a provider exception OR an unparseable
        # reply. `Adjudicator.adjudicate` returns None for both and the difference is not
        # observable from here, so the name does not claim to know which.
        "asked_no_verdict": by_status["no_verdict"],
        "not_asked": by_status["not_asked"],
        "provider_disabled": not adjud.enabled,
        "by_status": dict(by_status),
        "new_cache_entries": len(set(cache.entries) - before),
        "cache_entries_total": len(cache.entries),
        "legacy_verdict_shapes": dict(legacy_hist),
        "current_verdicts": dict(Counter(r["verdict"] for r in usable)),
        "changed": sum(1 for r in usable if r["changed"]),
        "unchanged": sum(1 for r in usable if not r["changed"]),
        "transitions": dict(Counter(
            f"{'|'.join(sorted(set(r['legacy_verdicts'].values())))} -> {r['verdict']}"
            for r in usable)),
        # the RESOLVED model, not the raw flag: --model defaults to None and the
        # Adjudicator falls back to GEMINI_MODEL, so args.model would record `null`
        # as the provenance of a paid artifact.
        "model": (adjud.providers[0].model if adjud.providers else args.model),
        "provider_signature": adjud._cache_salt.split("|", 1)[-1],
        "cache_salt": adjud._cache_salt,
        "provider_summary": adjud.summary(),
    }
    logger.info("re-adjudication stats:\n" + json.dumps(stats, indent=2, ensure_ascii=False))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats_path = Path(args.stats_out)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {len(results)} row(s) -> {out_path}")

    # A provider that died mid-run leaves the rest never_asked. Everything paid for is
    # already persisted (cache + outputs above) and a re-run resumes free, so abort
    # LOUDLY rather than return a stats block that reads like a completed run.
    if stats["not_asked"] or stats["provider_disabled"]:
        raise SystemExit(
            f"provider disabled mid-run: {stats['not_asked']} pair(s) were never asked "
            f"(verdicts={stats['verdicts']}, failures="
            f"{sum(p['failures'] for p in stats['provider_summary']['providers'])}).\n"
            "Adjudicator disables a provider after 3 failures with 0 successes, which a "
            "burst of 429s can trigger under high --max-workers. Everything already paid "
            "for is cached; lower --max-workers / --rate-limit and re-run — the completed "
            "pairs will be free cache hits.")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="Re-adjudicate legacy-prompt pairs under the CURRENT prompt, so the "
                     "training set is single-generation. Targets only the non-irrelevant "
                     "legacy pairs with no current verdict. PAID — use --dry-run first.")
    p.add_argument("--replay", type=Path, default=DEFAULT_REPLAY,
                   help="replay_adjudications output to select targets from.")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE,
                   help="Adjudication cache to read AND append to (backed up first).")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--model", type=str, default=None,
                   help="Model id. Defaults to GEMINI_MODEL from .env — which must match "
                        "the model behind the existing current-generation entries, or the "
                        "new verdicts form a THIRD generation instead of joining them.")
    p.add_argument("--provider-order", type=str, default="gemini")
    p.add_argument("--rate-limit", type=int, default=10)
    p.add_argument("--max-workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=None, help="Cap the paid calls.")
    p.add_argument("--checkpoint-every", type=int, default=DEFAULT_CHECKPOINT_EVERY,
                   help="Persist the cache every N results so a crash loses nothing paid for.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the target set and call nothing.")
    args = p.parse_args()
    args.provider_order = [s.strip().lower() for s in args.provider_order.split(",") if s.strip()]
    run(args)


if __name__ == "__main__":
    main()
