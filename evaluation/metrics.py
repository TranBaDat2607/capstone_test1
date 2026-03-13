"""
evaluation/metrics.py

Quantitative evaluation functions for the ESG Greenwashing Detection system.

Covers:
* Claim-classification metrics (precision, recall, F1, accuracy, per-class).
* Evidence grounding rate — proportion of reasoning steps that cite a valid
  Knowledge Graph node ID.
* Silence-detection recall — how many truly-silent categories were flagged.
* Temporal-consistency agreement — binary agreement between the module's
  divergence signal and human-annotated labels.
* Full system evaluation rollup.

scikit-learn is used when available; pure-Python fallbacks are provided for
environments where it is not installed.
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sklearn import guard
# ---------------------------------------------------------------------------
try:
    from sklearn.metrics import (
        precision_recall_fscore_support,
        accuracy_score,
        classification_report,
    )
    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False
    logger.info(
        "scikit-learn not found — falling back to pure-Python metric implementations."
    )

# ---------------------------------------------------------------------------
# Default label set
# ---------------------------------------------------------------------------
_DEFAULT_LABELS: list[str] = ["Verified", "Greenwashing", "Insufficient_Evidence"]


# ---------------------------------------------------------------------------
# Claim-level classification metrics
# ---------------------------------------------------------------------------

def compute_claim_metrics(
    predictions: list[str],
    ground_truth: list[str],
    labels: list[str] | None = None,
) -> dict:
    """Compute precision, recall, F1, accuracy, and per-class metrics for
    ESG claim classification.

    Args:
        predictions:  Model-predicted labels for each claim.
        ground_truth: Human-annotated gold-standard labels.
        labels:       Ordered list of class labels.  Defaults to
                      ``["Verified", "Greenwashing", "Insufficient_Evidence"]``.

    Returns:
        A dict::

            {
                "precision":  float,   # macro-averaged
                "recall":     float,   # macro-averaged
                "f1":         float,   # macro-averaged
                "accuracy":   float,
                "per_class": {
                    label: {
                        "precision": float,
                        "recall":    float,
                        "f1":        float,
                        "support":   int,
                    },
                    ...
                },
            }

    Raises:
        ValueError: If *predictions* and *ground_truth* have different lengths.
    """
    if len(predictions) != len(ground_truth):
        raise ValueError(
            f"predictions ({len(predictions)}) and ground_truth "
            f"({len(ground_truth)}) must have the same length."
        )

    if not labels:
        labels = _DEFAULT_LABELS

    if _SKLEARN_AVAILABLE:
        return _compute_claim_metrics_sklearn(predictions, ground_truth, labels)
    return _compute_claim_metrics_manual(predictions, ground_truth, labels)


def _compute_claim_metrics_sklearn(
    predictions: list[str],
    ground_truth: list[str],
    labels: list[str],
) -> dict:
    """sklearn-backed implementation of ``compute_claim_metrics``."""
    precision_arr, recall_arr, f1_arr, support_arr = precision_recall_fscore_support(
        ground_truth,
        predictions,
        labels=labels,
        average=None,
        zero_division=0,
    )
    accuracy = accuracy_score(ground_truth, predictions)

    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        ground_truth,
        predictions,
        labels=labels,
        average="macro",
        zero_division=0,
    )

    per_class: dict[str, dict] = {}
    for i, label in enumerate(labels):
        per_class[label] = {
            "precision": round(float(precision_arr[i]), 4),
            "recall":    round(float(recall_arr[i]), 4),
            "f1":        round(float(f1_arr[i]), 4),
            "support":   int(support_arr[i]),
        }

    return {
        "precision": round(float(macro_p), 4),
        "recall":    round(float(macro_r), 4),
        "f1":        round(float(macro_f1), 4),
        "accuracy":  round(float(accuracy), 4),
        "per_class": per_class,
    }


def _compute_claim_metrics_manual(
    predictions: list[str],
    ground_truth: list[str],
    labels: list[str],
) -> dict:
    """Pure-Python fallback for ``compute_claim_metrics``."""
    # Build per-class TP, FP, FN counts.
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for pred, gold in zip(predictions, ground_truth):
        if pred == gold:
            tp[pred] += 1
        else:
            fp[pred] += 1
            fn[gold] += 1

    support: dict[str, int] = defaultdict(int)
    for gold in ground_truth:
        support[gold] += 1

    per_class: dict[str, dict] = {}
    precision_list: list[float] = []
    recall_list: list[float] = []
    f1_list: list[float] = []

    for label in labels:
        p = tp[label] / max(tp[label] + fp[label], 1)
        r = tp[label] / max(tp[label] + fn[label], 1)
        f = (2 * p * r) / max(p + r, 1e-9)
        per_class[label] = {
            "precision": round(p, 4),
            "recall":    round(r, 4),
            "f1":        round(f, 4),
            "support":   support[label],
        }
        precision_list.append(p)
        recall_list.append(r)
        f1_list.append(f)

    n = max(len(labels), 1)
    macro_p = sum(precision_list) / n
    macro_r = sum(recall_list) / n
    macro_f = sum(f1_list) / n
    accuracy = sum(1 for p, g in zip(predictions, ground_truth) if p == g) / max(
        len(predictions), 1
    )

    return {
        "precision": round(macro_p, 4),
        "recall":    round(macro_r, 4),
        "f1":        round(macro_f, 4),
        "accuracy":  round(accuracy, 4),
        "per_class": per_class,
    }


# ---------------------------------------------------------------------------
# Evidence grounding rate
# ---------------------------------------------------------------------------

def compute_evidence_grounding_rate(
    reasoning_chains: list[dict],
    kg_node_ids: set,
) -> float:
    """Compute the proportion of LLM reasoning steps that cite a valid KG node.

    A *reasoning chain* is expected to be a dict with a ``"steps"`` key
    containing a list of step dicts.  Each step dict may contain a
    ``"cited_nodes"`` key (list of node ID strings) or a ``"node_id"`` key.

    Args:
        reasoning_chains: List of reasoning-chain dicts produced by the
                          RL-guided reasoning module.
        kg_node_ids:      Set of all valid node IDs present in the KG.

    Returns:
        Float in ``[0.0, 1.0]`` — proportion of steps that cite at least one
        valid KG node.  Returns ``0.0`` when there are no steps.
    """
    total_steps = 0
    grounded_steps = 0

    for chain in reasoning_chains:
        steps: list[dict] = chain.get("steps", [])
        if not steps:
            # Treat a chain with no steps sub-key as a single-step chain.
            steps = [chain]

        for step in steps:
            total_steps += 1

            # Collect candidate node references from the step.
            cited: list[str] = []
            if "cited_nodes" in step and isinstance(step["cited_nodes"], list):
                cited.extend(step["cited_nodes"])
            if "node_id" in step:
                cited.append(step["node_id"])
            if "evidence_node_ids" in step and isinstance(
                step["evidence_node_ids"], list
            ):
                cited.extend(step["evidence_node_ids"])

            if any(nid in kg_node_ids for nid in cited):
                grounded_steps += 1

    if total_steps == 0:
        return 0.0
    return round(grounded_steps / total_steps, 4)


# ---------------------------------------------------------------------------
# Silence recall
# ---------------------------------------------------------------------------

def compute_silence_recall(
    detected_silence: list[str],
    actual_silence: list[str],
) -> float:
    """Compute recall of mandatory disclosure categories detected as silent.

    Recall is defined as::

        |detected_silence ∩ actual_silence| / |actual_silence|

    Args:
        detected_silence: Categories flagged as silent by the detector.
        actual_silence:   Ground-truth silent categories (e.g. from manual audit).

    Returns:
        Float in ``[0.0, 1.0]``.  Returns ``1.0`` when *actual_silence* is
        empty (vacuously correct).
    """
    if not actual_silence:
        return 1.0

    detected_set = set(detected_silence)
    actual_set = set(actual_silence)
    true_positives = detected_set & actual_set
    return round(len(true_positives) / max(len(actual_set), 1), 4)


# ---------------------------------------------------------------------------
# Temporal consistency agreement
# ---------------------------------------------------------------------------

def compute_temporal_consistency_agreement(
    module_scores: list[float],
    human_labels: list[bool],
) -> float:
    """Compute binary agreement between the temporal consistency module and
    human-annotated divergence labels.

    The module score is converted to a binary signal: a score below ``0.5``
    indicates detected divergence (``True``).

    Args:
        module_scores: Per-company (or per-year) consistency scores in
                       ``[0.0, 1.0]`` as produced by
                       ``TemporalConsistencyModule``.
        human_labels:  Human-annotated boolean labels where ``True`` means
                       divergence was observed.

    Returns:
        Float in ``[0.0, 1.0]`` — proportion of instances where the module
        agrees with the human label.

    Raises:
        ValueError: If *module_scores* and *human_labels* differ in length.
    """
    if len(module_scores) != len(human_labels):
        raise ValueError(
            f"module_scores ({len(module_scores)}) and human_labels "
            f"({len(human_labels)}) must have the same length."
        )

    if not module_scores:
        return 0.0

    agreements = sum(
        1
        for score, label in zip(module_scores, human_labels)
        if (score < 0.5) == label  # module flags divergence when score < 0.5
    )
    return round(agreements / len(module_scores), 4)


# ---------------------------------------------------------------------------
# Full system evaluation
# ---------------------------------------------------------------------------

def evaluate_system(
    audit_results: list[dict],
    ground_truth: list[dict],
) -> dict:
    """Run the full evaluation suite over a batch of audit results.

    Each element of *audit_results* is expected to be a dict with at least:
    * ``"claim_id"``        — unique identifier
    * ``"verdict"``         — predicted label string
    * ``"reasoning_chain"`` — reasoning-chain dict (for grounding rate)
    * ``"silence_flags"``   — list of flagged-silent categories (optional)
    * ``"consistency_score"`` — float from temporal consistency module (optional)

    Each element of *ground_truth* is expected to have:
    * ``"claim_id"``        — matching identifier
    * ``"verdict"``         — gold-standard label string
    * ``"actual_silence"``  — list of truly-silent categories (optional)
    * ``"divergence"``      — bool for temporal divergence (optional)

    Args:
        audit_results: List of system-produced audit result dicts.
        ground_truth:  List of ground-truth annotation dicts.

    Returns:
        A comprehensive metrics dict::

            {
                "claim_metrics":             dict,    # from compute_claim_metrics
                "evidence_grounding_rate":   float,
                "silence_recall":            float,
                "temporal_consistency_agreement": float,
                "n_audits":                  int,
            }
    """
    # Align by claim_id.
    gt_index: dict[str, dict] = {
        item["claim_id"]: item
        for item in ground_truth
        if "claim_id" in item
    }

    predictions: list[str] = []
    gold_labels: list[str] = []
    reasoning_chains: list[dict] = []
    detected_silence_all: list[str] = []
    actual_silence_all: list[str] = []
    consistency_scores: list[float] = []
    divergence_labels: list[bool] = []

    # Collect all valid KG node IDs for grounding check.
    # The audit_results may embed a "kg_node_ids" top-level key; if not, we
    # derive it from referenced evidence.
    kg_node_ids: set[str] = set()

    for result in audit_results:
        claim_id = result.get("claim_id")
        if claim_id not in gt_index:
            logger.debug("Skipping claim_id '%s' — no ground truth entry.", claim_id)
            continue

        gt_item = gt_index[claim_id]

        pred_verdict = result.get("verdict", "Insufficient_Evidence")
        gold_verdict = gt_item.get("verdict", "Insufficient_Evidence")
        predictions.append(pred_verdict)
        gold_labels.append(gold_verdict)

        # Reasoning chain.
        chain = result.get("reasoning_chain", {})
        if chain:
            reasoning_chains.append(chain)
            # Accumulate node IDs referenced in the chain.
            for step in chain.get("steps", [chain]):
                for key in ("cited_nodes", "evidence_node_ids"):
                    for nid in step.get(key, []):
                        kg_node_ids.add(nid)
                if "node_id" in step:
                    kg_node_ids.add(step["node_id"])

        # Silence signals.
        detected_silence_all.extend(result.get("silence_flags", []))
        actual_silence_all.extend(gt_item.get("actual_silence", []))

        # Temporal consistency.
        if "consistency_score" in result and "divergence" in gt_item:
            consistency_scores.append(float(result["consistency_score"]))
            divergence_labels.append(bool(gt_item["divergence"]))

    # Claim-level metrics.
    if predictions:
        claim_metrics = compute_claim_metrics(predictions, gold_labels)
    else:
        claim_metrics = {
            "precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0,
            "per_class": {},
        }

    # Evidence grounding rate.
    grounding_rate = (
        compute_evidence_grounding_rate(reasoning_chains, kg_node_ids)
        if reasoning_chains
        else 0.0
    )

    # Silence recall.
    silence_recall = compute_silence_recall(detected_silence_all, actual_silence_all)

    # Temporal consistency agreement.
    temporal_agreement = (
        compute_temporal_consistency_agreement(consistency_scores, divergence_labels)
        if consistency_scores
        else 0.0
    )

    return {
        "claim_metrics": claim_metrics,
        "evidence_grounding_rate": grounding_rate,
        "silence_recall": silence_recall,
        "temporal_consistency_agreement": temporal_agreement,
        "n_audits": len(predictions),
    }
