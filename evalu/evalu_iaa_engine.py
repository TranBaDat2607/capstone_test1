#!/usr/bin/env python3
"""
evalu_iaa_engine.py — Inter-Annotator Agreement (IAA) & Consensus Resolution Engine

Implements the mathematical IAA formulas from evalu.docx:
1. Fleiss' Kappa (κ): Nominal classification agreement across multiple raters.
2. Krippendorff's Alpha (α): Ordinal Likert 5-point agreement with Quadratic Weights and missing data handling.
3. Gwet's AC1 / AC2: Paradox-robust agreement coefficient for imbalanced datasets.
4. Consensus Resolution Pipeline: 4-step workflow (Independent ratings -> IAA computation -> Disagreement spotting -> Weighted Median Adjudication).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Union


class IAAEngine:
    """Inter-Annotator Agreement calculation engine supporting Fleiss' Kappa, Krippendorff's Alpha, and Gwet's AC1/AC2."""

    @staticmethod
    def fleiss_kappa(ratings_matrix: List[List[int]], num_categories: int) -> float:
        """Fleiss' Kappa (κ) for N subjects rated into K nominal categories by M raters.

        ratings_matrix[i][j] = number of raters who assigned subject i to category j.
        """
        N = len(ratings_matrix)  # number of subjects
        if N == 0:
            return 1.0

        n = sum(ratings_matrix[0])  # number of raters per subject
        if n <= 1:
            return 1.0

        # P_i: degree of agreement for i-th subject
        P_i = []
        for row in ratings_matrix:
            sum_sq = sum(j ** 2 for j in row)
            P_i.append((sum_sq - n) / (n * (n - 1)))

        P_bar = sum(P_i) / N

        # P_e: chance agreement based on marginal proportions
        p_j = []
        for j in range(num_categories):
            col_sum = sum(ratings_matrix[i][j] for i in range(N))
            p_j.append(col_sum / (N * n))

        P_e_bar = sum(pj ** 2 for pj in p_j)

        if P_e_bar == 1.0:
            return 1.0

        kappa = (P_bar - P_e_bar) / (1.0 - P_e_bar)
        return float(kappa)

    @staticmethod
    def krippendorff_alpha_ordinal(ratings: List[Dict[str, Optional[int]]], min_score: int = 1, max_score: int = 5) -> float:
        """Krippendorff's Alpha (α) for Ordinal Likert data (1-5) with Quadratic Weights and missing value support.

        ratings: list of dicts where keys are raters ('rater1', 'rater2', ...) and values are integer scores (or None).
        """
        N = len(ratings)
        if N == 0:
            return 1.0

        # Pairwise observations
        observed_pairs = []
        all_values = []

        for item in ratings:
            scores = [v for v in item.values() if v is not None]
            if len(scores) < 2:
                continue
            all_values.extend(scores)
            for i in range(len(scores)):
                for j in range(i + 1, len(scores)):
                    observed_pairs.append((scores[i], scores[j]))

        if not observed_pairs:
            return 1.0

        # Quadratic distance function for ordinal Likert
        def d2(v1: int, v2: int) -> float:
            return float((v1 - v2) ** 2)

        # Observed disagreement (D_o)
        D_o = sum(d2(v1, v2) for v1, v2 in observed_pairs) / len(observed_pairs)

        # Expected disagreement (D_e)
        expected_pairs = []
        for i in range(len(all_values)):
            for j in range(i + 1, len(all_values)):
                expected_pairs.append((all_values[i], all_values[j]))

        if not expected_pairs:
            return 1.0

        D_e = sum(d2(v1, v2) for v1, v2 in expected_pairs) / len(expected_pairs)

        if D_e == 0:
            return 1.0

        alpha = 1.0 - (D_o / D_e)
        return float(alpha)

    @staticmethod
    def gwet_ac1_ac2(ratings: List[Dict[str, Optional[int]]], categories: List[int], ordinal_weights: bool = True) -> float:
        """Gwet's AC1 (for nominal) or AC2 (for ordinal Likert).

        Bypasses the Kappa Paradox when class distribution is severely imbalanced.
        """
        N = len(ratings)
        if N == 0:
            return 1.0

        K = len(categories)
        cat_map = {c: i for i, c in enumerate(categories)}

        # Distance weight matrix W_kl
        def weight(k: int, l: int) -> float:
            if not ordinal_weights:
                return 1.0 if k == l else 0.0
            # Quadratic ordinal weight
            return 1.0 - ((k - l) ** 2) / ((K - 1) ** 2)

        # Calculate observed agreement P_a
        pa_sum = 0.0
        total_valid = 0

        for item in ratings:
            scores = [v for v in item.values() if v is not None]
            n_i = len(scores)
            if n_i <= 1:
                continue

            item_pa = 0.0
            pair_count = 0
            for i in range(n_i):
                for j in range(n_i):
                    if i != j:
                        k_idx = cat_map[scores[i]]
                        l_idx = cat_map[scores[j]]
                        item_pa += weight(k_idx, l_idx)
                        pair_count += 1

            if pair_count > 0:
                pa_sum += item_pa / pair_count
                total_valid += 1

        if total_valid == 0:
            return 1.0

        p_a = pa_sum / total_valid

        # Calculate marginal probabilities pi_k
        cat_counts = Counter()
        total_ratings_count = 0
        for item in ratings:
            for v in item.values():
                if v is not None:
                    cat_counts[v] += 1
                    total_ratings_count += 1

        pi = [cat_counts[c] / max(total_ratings_count, 1) for c in categories]

        # Chance agreement p_e for Gwet's AC
        p_e = 0.0
        for k in range(K):
            for l in range(K):
                w_kl = weight(k, l)
                p_e += w_kl * pi[k] * pi[l]

        if p_e == 1.0:
            return 1.0

        gwet_ac = (p_a - p_e) / (1.0 - p_e)
        return float(gwet_ac)


class ConsensusResolver:
    """Consensus Resolution Pipeline (4-step workflow)."""

    def __init__(self, rater_weights: Optional[Dict[str, float]] = None):
        # Default weights: Auditor/ESG Specialist has higher legal/standard weight (1.5), CEO/HRD higher operational weight (1.2), standard (1.0)
        self.weights = rater_weights or {"auditor": 1.5, "esg_specialist": 1.4, "ceo": 1.2, "hrd": 1.0}

    def spot_disagreements(self, ratings: List[Dict[str, Any]], delta_threshold: int = 2) -> List[Dict[str, Any]]:
        """Step 3: Disagreements Spotting — filters items with Likert score difference >= delta_threshold or label contradiction."""
        disagreements = []

        for idx, item in enumerate(ratings):
            scores = [v for k, v in item.items() if isinstance(v, (int, float))]
            if len(scores) >= 2:
                max_score = max(scores)
                min_score = min(scores)
                if (max_score - min_score) >= delta_threshold:
                    disagreements.append({
                        "item_index": idx,
                        "item_id": item.get("id", f"claim_{idx}"),
                        "max_score": max_score,
                        "min_score": min_score,
                        "delta": max_score - min_score,
                        "ratings": item
                    })

        return disagreements

    def resolve_weighted_median(self, item_ratings: Dict[str, Union[int, float, str]]) -> Union[int, float]:
        """Step 4: Adjudication Panel — resolves consensus score using Weighted Median based on expert roles."""
        weighted_scores = []

        for rater, score in item_ratings.items():
            if isinstance(score, (int, float)) and rater in self.weights:
                w = self.weights.get(rater, 1.0)
                weighted_scores.append((score, w))

        if not weighted_scores:
            numeric_scores = [s for s in item_ratings.values() if isinstance(s, (int, float))]
            return float(sum(numeric_scores) / len(numeric_scores)) if numeric_scores else 3.0

        weighted_scores.sort(key=lambda x: x[0])
        total_weight = sum(w for _, w in weighted_scores)
        half_weight = total_weight / 2.0

        cum_weight = 0.0
        for score, w in weighted_scores:
            cum_weight += w
            if cum_weight >= half_weight:
                return float(score)

        return float(weighted_scores[-1][0])


if __name__ == "__main__":
    # Test sample ratings
    sample_likert = [
        {"auditor": 5, "esg_specialist": 5, "ceo": 4, "hrd": 4},
        {"auditor": 1, "esg_specialist": 2, "ceo": 5, "hrd": 4},  # Disagreement item
        {"auditor": 4, "esg_specialist": 4, "ceo": 4, "hrd": 3},
        {"auditor": 5, "esg_specialist": 4, "ceo": 5, "hrd": 5},
    ]

    alpha = IAAEngine.krippendorff_alpha_ordinal(sample_likert)
    gwet = IAAEngine.gwet_ac1_ac2(sample_likert, categories=[1, 2, 3, 4, 5], ordinal_weights=True)

    resolver = ConsensusResolver()
    disagreements = resolver.spot_disagreements(sample_likert, delta_threshold=2)

    print(f"Krippendorff's Alpha (Ordinal): {alpha:.4f}")
    print(f"Gwet's AC2 (Ordinal Likert): {gwet:.4f}")
    print(f"Disagreements Spotted: {len(disagreements)}")
