"""Step 6c — enrich the cross-check dossiers with an evidence-balance distribution (NO LLM/DB).

Design doc: docs/SOFTMAX_SCORING.md (read it before changing the formula — the parameter
choices and the §1.1 framing are deliberate). Companion of docs/CROSSCHECK_EXPANSION.md:
when the `signals` generator lands, the λ terms below start contributing; until then a
missing/empty `signals` key simply contributes 0, so this script is safe to run today.

For every claim dossier written by step07 (graph_output/crosscheck/<ticker>_claim_assessments.json)
this computes a softmax distribution over three evidence-balance components:

    assessment_scores = {contradicted, supported, abstain}     (sums to 1.0)

This is NOT a greenwashing probability (SYSTEM_DESIGN §1.1 — no ground truth exists).
It is a normalized balance of the *already-adjudicated* evidence on one claim; the
categorical `assessment` stays the primary output. The whole computation is deterministic
over the frozen dossier — re-running step07 (LLM) would not reproduce the inputs, but the
dossier itself ships in the pinned HF snapshot (data_version.json), so every number here
is reproducible from pinned data.

Written back into the SAME dossier file, per claim:
  + assessment_scores               {contradicted, supported, abstain}
  + score_components                z-values, per-side weight sums, signal terms, params
  + score_disagrees_with_assessment argmax != categorical label (the mixed-evidence set)

Run from the repo root (offline, free, idempotent):
    python src/step07b_enrich_dossiers.py --dry-run              # compute + report, no write
    python src/step07b_enrich_dossiers.py                        # enrich the AAA dossier
    python src/step07b_enrich_dossiers.py --calibrate            # grid (tau, beta1, w_max); beta0 stays fixed
    python src/step07b_enrich_dossiers.py --bin-confidence       # ordinal 3-level confidence
    python src/step07b_enrich_dossiers.py --params '{"tau":0.75}'
"""

import argparse
import itertools
import json
import logging
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CROSSCHECK_DIR = REPO_ROOT / "graph_output" / "crosscheck"

# Defaults from docs/SOFTMAX_SCORING.md §2. beta0 is a design decision (the zero-evidence
# abstain prior, ≈0.69), NOT a fitted parameter — --calibrate never touches it (§4).
DEFAULT_PARAMS: Dict[str, float] = {
    "tau": 1.0,
    "beta0": 1.5,
    "beta1": 1.0,
    "lam_struct": 0.5,
    "lam_kpi": 0.5,
    "lam_bp": 0.5,
    "w_max": 3.0,
    "date_uncertain_penalty": 0.8,
}

SIGNAL_LAMBDAS = {
    "structural_contradiction": "lam_struct",
    "kpi_gap": "lam_kpi",
    "broken_promise": "lam_bp",
}

# score key -> the categorical assessment its argmax corresponds to (for the disagree flag).
SCORE_TO_ASSESSMENT = {
    "contradicted": "appears_contradicted",
    "supported": "appears_supported",
    "abstain": "unverified_insufficient_evidence",
}

# --bin-confidence: LLM self-reported confidence is ordinal, not calibrated (§2) —
# collapse it to three levels to drop the false precision. Upper-bound exclusive.
CONF_BINS: Tuple[Tuple[float, float], ...] = ((0.5, 0.3), (0.8, 0.6), (10.0, 0.9))

# Grid searched by --calibrate (beta0 deliberately absent — see §4).
CALIBRATION_GRID = {
    "tau": (0.5, 0.75, 1.0, 1.5),
    "beta1": (0.5, 0.75, 1.0, 1.5),
    "w_max": (2.0, 3.0, 4.0),
}


# --------------------------------------------------------------------------- formula
def evidence_weight(ev: Dict[str, Any], params: Dict[str, float], bin_confidence: bool) -> float:
    conf = float(ev.get("confidence") or 0.0)
    if conf <= 0.0:
        return 0.0
    if bin_confidence:
        conf = next(level for bound, level in CONF_BINS if conf < bound)
    return conf * (params["date_uncertain_penalty"] if ev.get("date_uncertain") else 1.0)


def signal_active(signals: Dict[str, Any], key: str) -> bool:
    # signals values are `false` or a payload dict (CROSSCHECK_EXPANSION §2); {} is inactive.
    value = signals.get(key)
    return bool(value) and value != {}


def softmax_scores(d: Dict[str, Any], params: Dict[str, float],
                   bin_confidence: bool = False) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return (assessment_scores, score_components) for one dossier item."""
    contradicting = d.get("contradicting_evidence") or []
    # supporting_evidence is already the independent-only bucket (step07); the guard is
    # kept so the formula stays correct even on a dossier assembled elsewhere.
    supporting = [e for e in (d.get("supporting_evidence") or []) if e.get("independent", True)]

    sum_w_contra = sum(evidence_weight(e, params, bin_confidence) for e in contradicting)
    sum_w_support = sum(evidence_weight(e, params, bin_confidence) for e in supporting)

    signals = d.get("signals") or {}
    signal_terms = {key: (params[lam] if signal_active(signals, key) else 0.0)
                    for key, lam in SIGNAL_LAMBDAS.items()}

    z_contra = min(sum_w_contra, params["w_max"]) + sum(signal_terms.values())
    z_support = min(sum_w_support, params["w_max"])
    z_abstain = params["beta0"] - params["beta1"] * (z_contra + z_support)

    exps = [math.exp(z / params["tau"]) for z in (z_contra, z_support, z_abstain)]
    total = sum(exps)
    scores = {
        "contradicted": round(exps[0] / total, 4),
        "supported": round(exps[1] / total, 4),
        "abstain": round(exps[2] / total, 4),
    }
    components = {
        "z_contradicted": round(z_contra, 4),
        "z_supported": round(z_support, 4),
        "z_abstain": round(z_abstain, 4),
        "sum_w_contradicting": round(sum_w_contra, 4),
        "sum_w_supporting": round(sum_w_support, 4),
        "signal_terms": signal_terms,
        "params": {**params, "bin_confidence": bin_confidence},
    }
    return scores, components


def argmax_label(scores: Dict[str, float]) -> str:
    # dict order (contradicted, supported, abstain) breaks exact ties deterministically,
    # matching the categorical rule's precedence.
    return max(scores, key=scores.get)


# --------------------------------------------------------------------------- enrichment
def enrich(dossiers: List[Dict[str, Any]], params: Dict[str, float],
           bin_confidence: bool) -> Dict[str, Any]:
    """Mutate dossiers in place; return summary stats."""
    argmax_hist: Counter = Counter()
    disagree_ids: List[str] = []
    per_bucket_agree: Dict[str, List[int]] = {}
    for d in dossiers:
        scores, components = softmax_scores(d, params, bin_confidence)
        top = argmax_label(scores)
        agrees = SCORE_TO_ASSESSMENT[top] == d.get("assessment")
        d["assessment_scores"] = scores
        d["score_components"] = components
        d["score_disagrees_with_assessment"] = not agrees

        argmax_hist[top] += 1
        bucket = d.get("assessment", "?")
        per_bucket_agree.setdefault(bucket, [0, 0])
        per_bucket_agree[bucket][0] += int(agrees)
        per_bucket_agree[bucket][1] += 1
        if not agrees:
            disagree_ids.append(str(d.get("claim_id")))

    n = len(dossiers) or 1
    agree_total = sum(a for a, _ in per_bucket_agree.values())
    return {
        "claims": len(dossiers),
        "argmax_histogram": dict(argmax_hist),
        "argmax_agreement": round(agree_total / n, 4),
        "agreement_by_assessment": {
            k: f"{a}/{t}" for k, (a, t) in sorted(per_bucket_agree.items())},
        "disagreements": len(disagree_ids),
        "disagreement_claim_ids_sample": disagree_ids[:10],
    }


def agreement_rate(dossiers: List[Dict[str, Any]], params: Dict[str, float],
                   bin_confidence: bool) -> float:
    agree = 0
    for d in dossiers:
        scores, _ = softmax_scores(d, params, bin_confidence)
        agree += int(SCORE_TO_ASSESSMENT[argmax_label(scores)] == d.get("assessment"))
    return agree / (len(dossiers) or 1)


def calibrate(dossiers: List[Dict[str, Any]], base_params: Dict[str, float],
              bin_confidence: bool) -> Dict[str, float]:
    """Grid search (tau, beta1, w_max) for max argmax↔assessment agreement; beta0 fixed (§4).
    Ties break toward the documented defaults so calibration never drifts without cause."""
    def distance_to_default(combo: Dict[str, float]) -> float:
        return sum(abs(combo[k] - DEFAULT_PARAMS[k]) for k in CALIBRATION_GRID)

    rows = []
    for tau, beta1, w_max in itertools.product(*CALIBRATION_GRID.values()):
        candidate = {**base_params, "tau": tau, "beta1": beta1, "w_max": w_max}
        rate = agreement_rate(dossiers, candidate, bin_confidence)
        rows.append((rate, candidate))
    rows.sort(key=lambda r: (-r[0], distance_to_default(r[1])))

    logger.info("Calibration grid (beta0 fixed at %.2f — design prior, not fitted):",
                base_params["beta0"])
    logger.info("  %-6s %-6s %-6s %s", "tau", "beta1", "w_max", "argmax agreement")
    for rate, c in rows[:10]:
        logger.info("  %-6.2f %-6.2f %-6.2f %.4f", c["tau"], c["beta1"], c["w_max"], rate)
    best_rate, best = rows[0]
    logger.info("Best: tau=%.2f beta1=%.2f w_max=%.2f (agreement %.4f)",
                best["tau"], best["beta1"], best["w_max"], best_rate)
    return best


# --------------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> None:
    path = args.input or (DEFAULT_CROSSCHECK_DIR / f"{args.ticker.lower()}_claim_assessments.json")
    if not path.exists():
        logger.error(f"No dossiers at {path}. Run Step 6 (step07) first — or `data_sync.py pull`.")
        sys.exit(1)
    dossiers = json.loads(path.read_text(encoding="utf-8"))

    params = dict(DEFAULT_PARAMS)
    if args.params:
        overrides = json.loads(args.params)
        unknown = set(overrides) - set(params)
        if unknown:
            logger.error(f"Unknown param(s) {sorted(unknown)}; valid: {sorted(params)}")
            sys.exit(1)
        params.update({k: float(v) for k, v in overrides.items()})

    if args.calibrate:
        params = calibrate(dossiers, params, args.bin_confidence)

    stats = enrich(dossiers, params, args.bin_confidence)
    logger.info("Enrichment summary:\n" + json.dumps(stats, indent=2, ensure_ascii=False))

    if args.dry_run:
        logger.info("--dry-run: dossier not written.")
        return
    path.write_text(json.dumps(dossiers, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {stats['claims']} enriched dossiers back to {path}")
    logger.info("Next: python src/step08_sync_crosscheck_to_neo4j.py  (pushes scores to Neo4j)")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 6c — offline evidence-balance softmax scores on the cross-check "
                    "dossiers (docs/SOFTMAX_SCORING.md; NO LLM, NO DB, idempotent).")
    p.add_argument("--ticker", default="AAA", help="Issuer whose dossier to enrich (default AAA).")
    p.add_argument("-i", "--input", type=Path, default=None,
                   help="Dossier JSON (default graph_output/crosscheck/<ticker>_claim_assessments.json).")
    p.add_argument("--params", type=str, default=None,
                   help='JSON overrides, e.g. \'{"tau":0.75,"w_max":2.0}\'.')
    p.add_argument("--calibrate", action="store_true",
                   help="Grid-search (tau, beta1, w_max) for argmax↔assessment agreement; "
                        "beta0 stays fixed (design prior). Uses the best combo for enrichment.")
    p.add_argument("--bin-confidence", action="store_true",
                   help="Treat LLM confidence as ordinal: <0.5→0.3, 0.5–0.8→0.6, >0.8→0.9.")
    p.add_argument("--dry-run", action="store_true", help="Compute + report; write nothing.")
    run(p.parse_args())


if __name__ == "__main__":
    main()
