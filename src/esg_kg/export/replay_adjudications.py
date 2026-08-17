#!/usr/bin/env python3
"""
Cache replay — turn the already-paid-for adjudication caches into a labelled
`(claim, evidence, verdict)` JSONL, offline and free.

WHY THIS EXISTS
`graph_output/crosscheck/adjudication_cache*.json` holds thousands of verdicts the
project has already paid Gemini/OpenAI for. They are the natural training set for a
distilled claim-evidence classifier — except the cache is CONTENT-ADDRESSED: each entry
is `sha256(parts) -> {verdict, confidence, rationale, provider}` and **the claim and
evidence text are not stored**. The texts exist only in the resolved graph; the mapping
between them exists only in the hash.

This tool rebuilds that mapping by recomputing the keys. For every (claim, conduct) pair
in the graph it derives the exact key `Adjudicator.adjudicate` would have used and looks
it up. A hit yields a fully-labelled training row; a miss yields nothing. No provider is
ever constructed, so a miss costs nothing — which is the whole point.

WHY NOT "JUST RE-RUN step07 WITH THE CACHES WARM"
That was the obvious plan and it does not survive contact with the artifacts:

  * step07 builds a real `Adjudicator`, which calls a real provider on every MISS. Any
    drift in retrieval or prompt turns a "free replay" into a full-price run.
  * The historical runs did not share one retrieval configuration. The 2026-08-08 OpenAI
    pass left 2,102 entries for ACG alone; the 2026-08-13 Gemini pass retrieved 359
    candidate pairs for the same issuer. Reproducing "the" retrieval therefore cannot
    recover both.

So this tool does not reproduce retrieval at all. It probes the full
claims x conduct cross product, which is a strict SUPERSET of any historical retrieval
(top_k, min_topic_overlap, the temporal window and the issuer scoping only ever NARROW
that set). The cache lookup is itself the filter. On the real graph the cross product is
481 x 342 = ~165k pairs, about a second of sha256 per key shape — cheaper than the
retrieval it replaces.

WHY THE CROSS PRODUCT ALSO SURVIVED THE P5 REORDER (measured, not assumed)
The 2026-08-14 P5 fix (issue #20, `anchor_kpi`'s stale glob) rebuilt and REORDERED the
resolved graph: 10,634/14,744 -> 10,624/15,130. That broke every recovery route keyed on
NODE INDEX — the dossiers' own `node_index` values now land on different classes
entirely, so reconstructing pairs from `*_claim_assessments.json` recovers 0%. Probing the
cross product is immune to it: it never trusts an index, only the text at that index, and
P5 preserved the claim/conduct node CONTENT. Both graphs therefore recover 4,259/4,259
today. `--input` defaults to the canonical `resolved_graph.json` like every other stage;
`graph_output/resolved/_pre_p5_backup/resolved_graph.json.bak` gives identical output and
is the fallback if a future rebuild ever does drop the texts.

That is a property of the current artifacts, not a guarantee: a rebuild that re-extracts
or re-words claim text WOULD break recovery, silently, because a changed text is simply a
key that misses. `MIN_RECOVERY_RATE` exists for that day — the run aborts with the backup
path in the message rather than quietly writing an empty training set.

TWO PROMPT GENERATIONS SHARE THESE FILES — NEVER MERGE THEM
The P1 fix (`067b93f`, 2026-08-13) salted the cache key with
`sha256(ADJUDICATE_SYSTEM)[:12] + "|" + "<provider>:<model>"`. So:

    unsalted 3-part key  ->  written BEFORE that fix, by the OLD pre-halo-guard prompt
    salted 4-part key    ->  written after, by the prompt in the tree today

Both shapes are live in `adjudication_cache.json` right now, for overlapping pairs, and
they disagree often (on the 43 census pairs the legacy verdicts match the current
dossiers 23/43, the salted ones 42/43). A training set that merged them would carry
contradictory labels for byte-identical text. Every row is therefore stamped with
`prompt_generation` (`current` | `legacy`), `--generation` selects, and the stats report
how many pairs carry both and how often they disagree — that number is the measured
impact of the P1 fix.

WHY IT IMPORTS FROM `crosscheck.claims_vs_conduct`
Normally a stage does not reach into another stage. Here the imported helpers ARE the
contract: this tool is only correct if it produces byte-identical strings to the ones
step07 hashed, so `node_text`/`node_domain`/`node_year`/`ADJUDICATE_SYSTEM` must be the
same objects, not copies. A copy would drift silently and the only symptom would be a
quietly shrinking training set. `test/test_replay_adjudications.py` pins the key
derivation against the real `Adjudicator`.

Read-only: never patches `resolved_graph.json`, the caches, or Neo4j — a separate derived
artifact, the same boundary `export_kgc` keeps.

    python src/run.py replay_adjudications --dry-run
    python src/run.py replay_adjudications -i graph_output/resolved/_pre_p5_backup/resolved_graph.json.bak
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.llm_cache import ContentCache
from esg_kg.core.paths import REPO_ROOT
from esg_kg.crosscheck.claims_vs_conduct import (
    ADJUDICATE_SYSTEM,
    CONDUCT_CLASSES,
    node_domain,
    node_text,
    node_year,
    props,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
PRE_P5_BACKUP = REPO_ROOT / "graph_output" / "resolved" / "_pre_p5_backup" / "resolved_graph.json.bak"
DEFAULT_CACHE_DIR = REPO_ROOT / "graph_output" / "crosscheck"
DEFAULT_OUT = REPO_ROOT / "graph_output" / "replay" / "adjudicated_pairs.jsonl"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "replay" / "replay_stats.json"

# Provider/model signatures to try when salting. The salt is
# `<prompt_hash>|<name>:<model>` — the model is NOT recoverable from the cache file, so
# it has to be probed. `gemini-2.5-flash` is what the 2026-08-13 re-adjudication actually
# ran on (verified: 43/43 census pairs recover under it); `DEFAULT_MODEL` today is
# `gemini-2.5-flash-lite`, which is why guessing from the current env would find nothing.
# Extend with --salt-model rather than editing this list.
DEFAULT_SALT_MODELS = (
    "gemini:gemini-2.5-flash",
    "gemini:gemini-2.5-flash-lite",
    "gemini:gemini-2.0-flash",
    "deepseek:deepseek-chat",
    "openai:gpt-4o-mini",
)

# Below this, the run is pointed at the wrong graph and an empty training set would be
# worse than an error (it looks like "the caches were empty").
MIN_RECOVERY_RATE = 0.02

VERDICTS = ("supports", "contradicts", "irrelevant")


# --------------------------------------------------------------------------- #
# Key derivation — must mirror Adjudicator exactly.
# --------------------------------------------------------------------------- #
def prompt_hash() -> str:
    """`Adjudicator.__init__`'s prompt component, read from the LIVE prompt so a
    byte-for-byte prompt edit moves this tool and the stage together."""
    return hashlib.sha256(ADJUDICATE_SYSTEM.encode("utf-8")).hexdigest()[:12]


def salt_for(provider_sig: str) -> str:
    """Reproduce `Adjudicator._cache_salt` for a `"<name>:<model>"` signature.

    The stage builds the signature from its ENABLED provider cascade
    (`",".join(f"{p.name}:{p.model}")`), so a multi-provider run salts with a comma
    list — pass that whole list as one `--salt-model` value to match it."""
    return f"{prompt_hash()}|{provider_sig}"


def evidence_meta(node: Dict[str, Any]) -> str:
    """The `evidence_meta` string step07 hashes as the third key part
    (`claims_vs_conduct.run`'s `_adj`). Part of the hashed content — reword it and every
    lookup misses."""
    return f"{node.get('class')} from {node_domain(node) or 'news'}, year {node_year(node)}"


# --------------------------------------------------------------------------- #
# Pools — the stage's conduct universe, without the narrowing filters.
# --------------------------------------------------------------------------- #
def claim_indices(nodes: List[Dict[str, Any]]) -> List[int]:
    """Every SustainabilityClaim. The stage restricts to claims linked to ONE issuer via
    a `claims` edge; not restricting here is deliberate — it only widens the probe, and
    the historical runs each scoped to a different ticker."""
    return [i for i, n in enumerate(nodes) if n.get("class") == "SustainabilityClaim"]


def conduct_indices(nodes: List[Dict[str, Any]]) -> List[int]:
    """The conduct pool exactly as step07 defines it (CONDUCT_CLASSES + source_type=news),
    minus the per-ticker `node_ticker` scoping, which only ever removes candidates."""
    return [i for i, n in enumerate(nodes)
            if n.get("class") in CONDUCT_CLASSES and props(n).get("source_type") == "news"]


def load_caches(paths: List[Path]) -> Dict[str, Dict[str, Any]]:
    """filename -> {key: value}. A corrupt or missing file is reported and skipped, never
    fatal — same posture as `ContentCache`'s own load."""
    caches: Dict[str, Dict[str, Any]] = {}
    for p in paths:
        try:
            raw = json.loads(Path(p).read_text(encoding="utf-8"))
            entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning(f"cache {p} unreadable ({exc}) — skipped")
            continue
        caches[Path(p).name] = entries
        logger.info(f"cache {Path(p).name}: {len(entries)} entrie(s)")
    return caches


# --------------------------------------------------------------------------- #
# Replay.
# --------------------------------------------------------------------------- #
def replay(nodes: List[Dict[str, Any]], caches: Dict[str, Dict[str, Any]],
           salts: List[Tuple[str, str]], generation: str = "both",
           ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Probe every (claim, conduct) pair against every cache under every key shape.

    Returns (rows, stats). One row per (pair, prompt_generation, cache_file): a pair
    adjudicated by two providers legitimately yields two rows, which is what makes the
    cross-provider agreement signal measurable. Deduplication is the consumer's call —
    this tool reports what was actually bought, and never invents a row.
    """
    claims = claim_indices(nodes)
    conduct = conduct_indices(nodes)

    claim_texts = {ci: node_text(nodes[ci]) for ci in claims}
    ev_texts = {xi: node_text(nodes[xi]) for xi in conduct}
    ev_metas = {xi: evidence_meta(nodes[xi]) for xi in conduct}

    # key shape -> (label, generation, salt or None)
    shapes: List[Tuple[str, str, Optional[str]]] = [("unsalted", "legacy", None)]
    shapes += [(f"salted[{sig}]", "current", salt) for sig, salt in salts]

    rows: List[Dict[str, Any]] = []
    recovered_keys: Dict[str, set] = defaultdict(set)
    shape_hits: Counter = Counter()
    # (ci, xi) -> {generation: verdict} for the cross-generation disagreement count
    per_pair: Dict[Tuple[int, int], Dict[str, str]] = defaultdict(dict)
    # (ci, xi, generation) -> {provider: verdict}. The same key living in several cache
    # files is the free cross-provider label-quality signal, so this spans files.
    per_provider: Dict[Tuple[int, int, str], Dict[str, str]] = defaultdict(dict)
    # Two different node pairs can carry byte-identical text and therefore share ONE
    # paid entry; a training set must dedupe on text, not on node index.
    text_pairs: set = set()

    for ci in claims:
        ctext = claim_texts[ci]
        for xi in conduct:
            etext, meta = ev_texts[xi], ev_metas[xi]
            for shape_label, gen, salt in shapes:
                if generation != "both" and gen != generation:
                    continue
                parts = (ctext, etext, meta) if salt is None else (salt, ctext, etext, meta)
                key = ContentCache.key(*parts)
                for cache_file, entries in caches.items():
                    if key not in entries:
                        continue
                    recovered_keys[cache_file].add(key)
                    value = entries[key]
                    # A cached `None` is step07 recording "a provider answered but the
                    # reply was unusable" — a real outcome, but not a label. Count it,
                    # never emit it as training data.
                    if not isinstance(value, dict) or value.get("verdict") not in VERDICTS:
                        shape_hits[f"{shape_label}:unusable"] += 1
                        continue
                    shape_hits[shape_label] += 1
                    per_pair[(ci, xi)][gen] = value["verdict"]
                    text_pairs.add((ctext, etext))
                    prov = value.get("provider")
                    if prov:
                        per_provider[(ci, xi, gen)][prov] = value["verdict"]
                    rows.append({
                        "claim_node_index": ci,
                        "evidence_node_index": xi,
                        "claim_id": props(nodes[ci]).get("claim_id"),
                        "claim_text": ctext,
                        "evidence_text": etext,
                        "evidence_meta": meta,
                        "evidence_class": nodes[xi].get("class"),
                        "evidence_domain": node_domain(nodes[xi]),
                        "evidence_year": node_year(nodes[xi]),
                        "verdict": value["verdict"],
                        "confidence": value.get("confidence"),
                        "rationale": value.get("rationale", ""),
                        "provider": value.get("provider"),
                        "cache_file": cache_file,
                        "key_shape": "unsalted" if salt is None else "salted",
                        "salt": salt,
                        "prompt_generation": gen,
                    })

    total_entries = sum(len(e) for e in caches.values())
    total_recovered = sum(len(k) for k in recovered_keys.values())
    both = [p for p, g in per_pair.items() if len(g) > 1]
    disagree = [p for p in both if len(set(per_pair[p].values())) > 1]
    multi_prov = [k for k, v in per_provider.items() if len(v) > 1]
    prov_agree = [k for k in multi_prov if len(set(per_provider[k].values())) == 1]

    stats = {
        "claims_probed": len(claims),
        "conduct_probed": len(conduct),
        "pairs_probed": len(claims) * len(conduct),
        "key_shapes_tried": [s[0] for s in shapes],
        "rows": len(rows),
        "cache_entries": total_entries,
        "recovered_cache_entries": total_recovered,
        "recovery_rate": round(total_recovered / total_entries, 4) if total_entries else 0.0,
        "per_cache_file": {f: {"entries": len(caches[f]),
                               "recovered": len(recovered_keys.get(f, set())),
                               "unrecovered": len(caches[f]) - len(recovered_keys.get(f, set()))}
                           for f in caches},
        "hits_by_key_shape": dict(shape_hits),
        "rows_by_generation": dict(Counter(r["prompt_generation"] for r in rows)),
        "rows_by_verdict": dict(Counter(r["verdict"] for r in rows)),
        "rows_by_provider": dict(Counter(r["provider"] for r in rows)),
        "verdict_by_generation": {
            g: dict(Counter(r["verdict"] for r in rows if r["prompt_generation"] == g))
            for g in sorted({r["prompt_generation"] for r in rows})
        },
        "distinct_pairs": len(per_pair),
        "distinct_text_pairs": len(text_pairs),
        "pairs_with_both_generations": len(both),
        "generations_disagree": len(disagree),
        "generation_disagreement_rate": round(len(disagree) / len(both), 4) if both else None,
        "cross_provider_pairs": len(multi_prov),
        "cross_provider_agree": len(prov_agree),
        "cross_provider_agreement_rate": (round(len(prov_agree) / len(multi_prov), 4)
                                          if multi_prov else None),
    }
    return rows, stats


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if not Path(args.input).exists():
        raise SystemExit(
            f"input not found: {args.input}\n"
            "Run `python src/run.py build_resolved` first, or point --input at "
            f"{PRE_P5_BACKUP} (the graph these caches were paid on)."
        )
    cache_paths = [Path(c) for c in (args.cache or [])]
    if not cache_paths:
        cache_paths = sorted(DEFAULT_CACHE_DIR.glob("adjudication_cache*.json"))
    if not cache_paths:
        raise SystemExit(f"no adjudication caches found under {DEFAULT_CACHE_DIR}")

    graph = json.loads(Path(args.input).read_text(encoding="utf-8"))
    nodes = graph.get("nodes", [])
    logger.info(f"graph: {len(nodes)} nodes from {args.input}")

    sigs = list(DEFAULT_SALT_MODELS) + list(getattr(args, "salt_model", []) or [])
    salts = [(sig, salt_for(sig)) for sig in dict.fromkeys(sigs)]

    caches = load_caches(cache_paths)
    rows, stats = replay(nodes, caches, salts, generation=args.generation)
    stats["input_graph"] = str(args.input)
    stats["generation_filter"] = args.generation
    stats["prompt_hash"] = prompt_hash()

    logger.info("replay stats:\n" + json.dumps(stats, indent=2, ensure_ascii=False))

    if stats["cache_entries"] and stats["recovery_rate"] < MIN_RECOVERY_RATE:
        raise SystemExit(
            f"recovery rate {stats['recovery_rate']:.1%} — this graph is almost certainly "
            f"not the one these verdicts were paid on.\n"
            f"The 2026-08-14 P5 fix (issue #20) reordered resolved_graph.json; the caches "
            f"match the pre-P5 snapshot. Retry with:\n"
            f"    --input {PRE_P5_BACKUP}"
        )

    if args.dry_run:
        logger.info("Dry run — nothing written.")
        return stats

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats_out = Path(args.stats_out)
    stats_out.parent.mkdir(parents=True, exist_ok=True)
    stats_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {len(rows)} row(s) -> {out}")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="Replay the paid adjudication caches into a labelled (claim, evidence, "
                     "verdict) JSONL. Offline and free — never constructs an LLM provider, "
                     "so a cache miss costs nothing. Read-only against its inputs.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT,
                   help="Resolved graph to recompute texts from. Must be the graph the "
                        f"verdicts were paid on — see {PRE_P5_BACKUP}.")
    p.add_argument("--cache", type=Path, action="append",
                   help="Adjudication cache file (repeatable). Default: every "
                        "adjudication_cache*.json in graph_output/crosscheck/.")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--salt-model", action="append", default=[],
                   help="Extra '<provider>:<model>' signature to try when salting keys "
                        "(repeatable); a multi-provider run salts with a comma list.")
    p.add_argument("--generation", choices=("current", "legacy", "both"), default="both",
                   help="Which prompt generation to emit. 'current' = salted keys written "
                        "by today's ADJUDICATE_SYSTEM; 'legacy' = unsalted keys from the "
                        "pre-2026-08-13 prompt. Default 'both' — they must not be merged "
                        "blindly, so the row carries prompt_generation and you choose.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
