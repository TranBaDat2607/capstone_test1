#!/usr/bin/env python3
"""
evalu_labelfree.py — label-free evaluation of the cross-check layer, offline.

Replaces two modules that measured nothing. The RAGAS tier reported a literal
list of hand-written "cosine similarities" plus two constants assigned directly
to the Context Precision and Context Recall variables; the metamorphic tier ran a
stub adjudicator over three invented companies (Vinamilk, Hòa Phát) that are not
in this project's corpus at all. Neither read a dossier.

(The constants themselves are deliberately not repeated in this file. They are
pinned as forbidden literals in ``test/test_evalu_metrics.py``, which greps
``evalu/*.py`` for them — quoting one here to explain it would keep the guard
failing forever.)

What replaces them is drawn from ``docs/EVALUATION_WITHOUT_LABELS.md``, which
already worked out which quantities are knowable here and which are not. Two
boundaries from that document are load-bearing and are respected below:

* **RAGAS Context Recall is not computable.** It needs a ground-truth set of the
  evidence that *should* have been retrieved. No such set exists — that is the
  premise of the whole project (§1.1), and §8 records the metric as dead.
* **True metamorphic relations need the real adjudicator.** Perturbing a claim
  and re-asking is an LLM call per pair. Running them against a stub, as the
  previous module did, measures the stub. They are costed at the bottom of the
  report, not faked here.

Everything in this module runs on artifacts already on disk: no LLM, no Neo4j,
no network. Guarded by ``test/test_evalu_metrics.py``.

Run:  python evalu/evalu_labelfree.py
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

RESOLVED_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
CROSSCHECK = REPO_ROOT / "graph_output" / "crosscheck" / "aaa_claim_assessments.json"
CROSSCHECK_STATS = REPO_ROOT / "graph_output" / "crosscheck" / "aaa_crosscheck_stats.json"
ISSUER_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"

N_PERMUTATIONS = 1000
PERMUTATION_SEED = 20260806  # fixed: the p-values must reproduce exactly

TOKEN_RE = re.compile(r"[0-9a-zà-ỹ]+", re.IGNORECASE)
STOPWORDS = {
    "và", "của", "các", "có", "được", "cho", "trong", "với", "là", "để", "này",
    "the", "and", "of", "for", "to", "in", "on", "at", "by", "a", "an", "is",
    "công", "ty", "năm", "một", "đã", "sẽ", "về", "từ", "theo", "khi", "như",
}


def _tokens(text: str) -> set:
    return {t for t in TOKEN_RE.findall((text or "").lower())
            if len(t) > 2 and t not in STOPWORDS}


def _wilson_ci(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """Wilson score interval. Used because the duplicate-claim denominator is
    tiny (tens of groups); a bare ratio there implies a precision it lacks."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _result(key: str, metric: str, *, measured: bool, **fields: Any) -> Dict[str, Any]:
    return {"key": key, "metric": metric, "measured": measured, **fields}


class LabelFreeEvaluator:
    """Offline label-free metrics over the cross-check dossiers."""

    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root
        self.dossiers: List[Dict[str, Any]] = self._load(CROSSCHECK) or []
        self.stats: Dict[str, Any] = self._load(CROSSCHECK_STATS) or {}
        graph = self._load(RESOLVED_GRAPH) or {}
        self.nodes: List[Dict[str, Any]] = graph.get("nodes", [])
        self.issuers: Dict[str, Any] = self._load(ISSUER_REGISTRY) or {}

    @staticmethod
    def _load(path: Path) -> Any:
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _all_evidence(self) -> List[Dict[str, Any]]:
        out = []
        for d in self.dossiers:
            for bucket in ("supporting_evidence", "contradicting_evidence",
                           "flagged_non_independent_support"):
                for e in (d.get(bucket) or []):
                    out.append({**e, "_bucket": bucket, "_claim": d})
        return out

    # ------------------------------------------------------------------ #
    def b2_permutation_test(self) -> Dict[str, Any]:
        """B2 — permutation test on the contradiction count (docs §4.3).

        Null hypothesis: the pairing between claims and retained evidence carries
        no information, i.e. the same evidence items scattered at random across
        claims would produce the same picture.

        The informative tail is the LOWER one, and it is worth being explicit
        about why, because the obvious reading is backwards. Shuffling preserves
        the total number of contradicting evidence items, so the null count of
        contradicted *claims* sits just under that total — collisions are the only
        thing that lowers it, and they are rare when 25 items scatter over 1,093
        claims. The observed count comes out BELOW the null exactly when
        contradicting items pile onto the same few claims. So a small lower-tail
        p-value means the system concentrates its contradictions on specific
        claims rather than sprinkling them, which is the behaviour a real signal
        would produce; an upper-tail test here would be near 1.0 by construction
        and would say nothing.
        """
        if not self.dossiers:
            return _result("b2_permutation_test", "B2 — permutation test (contradiction count)",
                           measured=False, reason="khong co file dossier tren dia")

        contradicting_per_claim = [len(d.get("contradicting_evidence") or [])
                                   for d in self.dossiers]
        n_items = sum(contradicting_per_claim)
        observed = sum(1 for d in self.dossiers
                       if d.get("assessment") == "appears_contradicted")
        n_claims = len(self.dossiers)

        rng = random.Random(PERMUTATION_SEED)
        null_counts = []
        for _ in range(N_PERMUTATIONS):
            hit = set()
            for _ in range(n_items):
                hit.add(rng.randrange(n_claims))
            null_counts.append(len(hit))

        p_lower = (sum(1 for c in null_counts if c <= observed) + 1) / (N_PERMUTATIONS + 1)
        p_upper = (sum(1 for c in null_counts if c >= observed) + 1) / (N_PERMUTATIONS + 1)
        null_mean = sum(null_counts) / len(null_counts)

        return _result("b2_permutation_test", "B2 — permutation test (contradiction count)",
                       measured=True,
                       observed=observed,
                       n_contradicting_items=n_items,
                       null_mean=round(null_mean, 2),
                       null_min=min(null_counts), null_max=max(null_counts),
                       n_permutations=N_PERMUTATIONS,
                       p_value=round(p_lower, 4),
                       p_value_upper_tail=round(p_upper, 4),
                       seed=PERMUTATION_SEED,
                       note=("Đuôi DƯỚI mới là đuôi có ý nghĩa — xem docstring. p là tỷ lệ "
                             "các lần rải ngẫu nhiên mà dồn mâu thuẫn vào ít claim đúng bằng "
                             "mức hệ thống đã làm."),
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    def b2b_pairing_coherence(self) -> Dict[str, Any]:
        """B2b — is a retained (claim, evidence) pair more coherent than a random
        re-pairing of the same two pools?

        Two statistics, both permuted the same way (evidence items shuffled across
        claims, 1,000 times): mean token overlap, and mean |claim_year −
        evidence_year|.

        Disclosure, because it bounds what this can prove: step 6a retrieves by
        token overlap within a year window, so the pool being permuted was already
        selected on both quantities. This therefore measures how much *further*
        the retained set separates from a random re-pairing of that same pool — it
        is not independent evidence that retrieval works. The non-circular version
        of this test compares retained against DISCARDED candidates, which needs
        the 3,270 rejected pairs step07 does not persist.
        """
        evidence = self._all_evidence()
        pairs = []
        for e in evidence:
            claim = e["_claim"]
            c_tok = _tokens(claim.get("claim_text"))
            e_tok = _tokens(e.get("text"))
            if not c_tok or not e_tok:
                continue
            pairs.append({
                "c_tok": c_tok, "e_tok": e_tok,
                "c_year": claim.get("year"), "e_year": e.get("year"),
            })
        if not pairs:
            return _result("b2b_pairing_coherence", "B2b — pairing coherence vs random re-pairing",
                           measured=False, reason="khong co manh bang chung nao co van ban dung duoc")

        def jaccard(a, b):
            return len(a & b) / len(a | b) if (a | b) else 0.0

        obs_overlap = sum(jaccard(p["c_tok"], p["e_tok"]) for p in pairs) / len(pairs)
        year_pairs = [p for p in pairs
                      if isinstance(p["c_year"], int) and isinstance(p["e_year"], int)]
        obs_gap = (sum(abs(p["c_year"] - p["e_year"]) for p in year_pairs) / len(year_pairs)
                   if year_pairs else None)

        rng = random.Random(PERMUTATION_SEED)
        null_overlap, null_gap = [], []
        e_toks = [p["e_tok"] for p in pairs]
        e_years = [p["e_year"] for p in year_pairs]
        for _ in range(N_PERMUTATIONS):
            rng.shuffle(e_toks)
            null_overlap.append(
                sum(jaccard(p["c_tok"], t) for p, t in zip(pairs, e_toks)) / len(pairs))
            if year_pairs:
                rng.shuffle(e_years)
                null_gap.append(
                    sum(abs(p["c_year"] - y) for p, y in zip(year_pairs, e_years)) / len(year_pairs))

        p_overlap = (sum(1 for v in null_overlap if v >= obs_overlap) + 1) / (N_PERMUTATIONS + 1)
        p_gap = ((sum(1 for v in null_gap if v <= obs_gap) + 1) / (N_PERMUTATIONS + 1)
                 if year_pairs else None)

        return _result("b2b_pairing_coherence", "B2b — pairing coherence vs random re-pairing",
                       measured=True,
                       n_pairs=len(pairs),
                       lexical_overlap={"observed": round(obs_overlap, 4),
                                        "null_mean": round(sum(null_overlap) / len(null_overlap), 4),
                                        "p_value": round(p_overlap, 4)},
                       year_distance=({"observed_years": round(obs_gap, 3),
                                       "null_mean_years": round(sum(null_gap) / len(null_gap), 3),
                                       "p_value": round(p_gap, 4),
                                       "n_pairs": len(year_pairs)} if year_pairs else None),
                       n_permutations=N_PERMUTATIONS, seed=PERMUTATION_SEED,
                       caveat=("Có phần luẩn quẩn: tầng retrieval vốn đã chọn theo chồng lấp từ vựng "
                               "và cửa sổ năm. Vì vậy chỉ kết luận được rằng 'tập được giữ tách "
                               "xa hơn nữa so với việc ghép lại ngẫu nhiên trong cùng bể đó'."),
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    def b3_structural_negative_control(self) -> Dict[str, Any]:
        """B3 — cross-company leakage (docs §4.4). NOT MEASURABLE on this corpus.

        The test asks whether retrieval ever hands an AAA claim a conduct node
        belonging to another company. The ingested corpus is single-issuer: every
        provenance-bearing node traces back to an AAA report or an AAA news
        article. There is no second issuer's conduct in the graph to leak, so the
        count is forced to 0 by the corpus rather than earned by the code.

        Reported as unmeasured on purpose. A 0 here would be the most flattering
        number in the report and the least informative — it becomes a real test
        the moment a second ticker is ingested, and not before.
        """
        prefixes: Counter = Counter()
        for nd in self.nodes:
            sd = (nd.get("properties") or {}).get("source_doc")
            if sd:
                prefixes[str(sd).split("_")[0].upper()] += 1
        tickers = set(self.issuers.keys())
        issuer_docs = sum(v for k, v in prefixes.items() if k in tickers)
        foreign_docs = sum(v for k, v in prefixes.items() if k not in tickers)

        return _result("b3_structural_negative_control", "B3 — structural negative control (cross-company)",
                       measured=False,
                       reason=("Corpus chỉ có MỘT doanh nghiệp: mọi tài liệu đã nạp đều thuộc về "
                               "issuer duy nhất trong config/issuer_registry.json, nên trong đồ "
                               "thị không tồn tại conduct của công ty khác để mà lọt sang. Số 0 "
                               "ở đây do corpus bảo đảm, không phải do logic retrieval."),
                       detail={"issuer_docs": issuer_docs,
                               "non_issuer_doc_prefixes": foreign_docs,
                               "registered_tickers": sorted(tickers),
                               "top_prefixes": prefixes.most_common(5)},
                       becomes_measurable_when="khi nạp thêm mã cổ phiếu thứ hai vào cùng một đồ thị",
                       source="graph_output/resolved/resolved_graph.json + config/issuer_registry.json")

    def duplicate_claim_consistency(self) -> Dict[str, Any]:
        """The same claim sentence appearing in two reports must get the same
        verdict. A disagreement is a self-inconsistency the system cannot blame on
        missing data — both copies saw the same conduct pool."""
        if not self.dossiers:
            return _result("duplicate_claim_consistency", "Verdict consistency on duplicate claims",
                           measured=False, reason="khong co file dossier tren dia")

        by_text = defaultdict(list)
        for d in self.dossiers:
            key = re.sub(r"\s+", " ", (d.get("claim_text") or "").strip().lower())
            if key:
                by_text[key].append(d)
        groups = {k: v for k, v in by_text.items() if len(v) > 1}
        inconsistent = []
        for text, members in groups.items():
            verdicts = {m.get("assessment") for m in members}
            if len(verdicts) > 1:
                inconsistent.append({
                    "claim_text": text[:160],
                    "verdicts": sorted(verdicts),
                    "years": sorted({m.get("year") for m in members if m.get("year")}),
                })
        consistent = len(groups) - len(inconsistent)

        return _result("duplicate_claim_consistency", "Verdict consistency on duplicate claims",
                       measured=True,
                       score=round(consistent / len(groups), 4) if groups else None,
                       numerator=consistent, denominator=len(groups),
                       wilson_95ci=_wilson_ci(consistent, len(groups)),
                       inconsistent_examples=inconsistent[:5],
                       note=("Mẫu số là số NHÓM claim trùng lặp, không phải số claim. Mẫu nhỏ — "
                             "báo cáo theo khoảng tin cậy, đừng báo cáo tỷ lệ trần."),
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    def d_anachronism(self) -> Dict[str, Any]:
        """D — evidence dated AFTER the claim it was used to judge.

        P8 (``docs/TEMPORAL_KG_DESIGN.md`` §3): *a 2021 report cannot be
        contradicted by information that only surfaced in 2024*. The project
        names bitemporal masking as a contribution, so whether it actually holds
        at the output is worth measuring directly.

        The design doc's MR-4 tests this by perturbing evidence dates and
        re-asking the adjudicator — 191 paid calls. This measures the same
        property for nothing, by reading the verdicts step07 already wrote: if a
        contradiction cites evidence from years later, the violation is already
        on disk and needs no experiment to reveal.

        Split by role on purpose. For a CONTRADICTION, later evidence is a P8
        violation outright. For a SUPPORT it is weaker — a 2016 article can
        legitimately report a 2015 fact — so the two rates mean different things
        and a blended number would overstate the finding.
        """
        if not self.dossiers:
            return _result("d_anachronism", "D — bằng chứng đi sau claim (kiểm P8)",
                           measured=False, reason="khong co file dossier tren dia")

        by_role: Dict[str, Dict[str, Any]] = {}
        gaps: Counter = Counter()
        worst: List[Dict[str, Any]] = []
        for role, bucket in (("supports", "supporting_evidence"),
                             ("contradicts", "contradicting_evidence")):
            viol = comparable = 0
            for d in self.dossiers:
                cy = d.get("year")
                for e in (d.get(bucket) or []):
                    ey = e.get("year")
                    if not (isinstance(cy, int) and isinstance(ey, int)):
                        continue
                    comparable += 1
                    gaps[ey - cy] += 1
                    if ey > cy:
                        viol += 1
                        if role == "contradicts":
                            worst.append({"gap_years": ey - cy, "claim_year": cy,
                                          "evidence_year": ey,
                                          "claim_text": (d.get("claim_text") or "")[:110]})
            by_role[role] = {"violations": viol, "comparable": comparable,
                             "rate": round(viol / comparable, 4) if comparable else None}

        worst.sort(key=lambda x: -x["gap_years"])
        return _result("d_anachronism", "D — bằng chứng đi sau claim (kiểm P8)",
                       measured=True,
                       by_role=by_role,
                       gap_distribution={str(k): v for k, v in sorted(gaps.items())},
                       max_gap_years=max(gaps) if gaps else None,
                       worst_contradictions=worst[:5],
                       note=("Với một MÂU THUẪN, bằng chứng có năm sau claim là vi phạm P8 "
                             "trực tiếp. Với một SUPPORT thì nhẹ hơn — bài báo 2016 có thể "
                             "tường thuật hợp lệ một sự kiện 2015 — nên hai tỷ lệ được tách "
                             "riêng và không được cộng gộp."),
                       caveat=("100% evidence mang date_uncertain=true, tức năm thường là ngày "
                               "đăng bài dùng làm proxy. Vì vậy đây là CẬN TRÊN của tỷ lệ vi "
                               "phạm, không phải con số chính xác."),
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    def e_time_window_ablation(self) -> Dict[str, Any]:
        """E — what the retrieval time window is actually buying.

        step07 runs with ``window_after=50``: evidence up to fifty years after a
        claim is still eligible. This replays the retained evidence under
        narrower windows and reports what survives — an ablation in the sense of
        docs §7 (measure the CHANGE, no labels needed).

        Only evidence that was already retained can be replayed, so this is a
        strict upper bound on what a narrower window would keep: it cannot show
        which *new* pairs a tighter window might have promoted into the top-k.
        Stated rather than hidden, because it bounds the conclusion.
        """
        if not self.dossiers:
            return _result("e_time_window_ablation", "E — ablation cửa sổ thời gian",
                           measured=False, reason="khong co file dossier tren dia")

        live = ((self.stats.get("params") or {}).get("window_after"))
        items = []
        for d in self.dossiers:
            cy = d.get("year")
            for role, bucket in (("supports", "supporting_evidence"),
                                 ("contradicts", "contradicting_evidence")):
                for e in (d.get(bucket) or []):
                    items.append((role, cy, e.get("year"), d.get("claim_id")))

        widths = sorted({0, 1, 2, 3, 5, 10} | ({live} if isinstance(live, int) else set()))
        rows = []
        for w in widths:
            keep = [(r, cid) for r, cy, ey, cid in items
                    if not (isinstance(cy, int) and isinstance(ey, int)) or (ey - cy) <= w]
            rows.append({
                "window_after": w,
                "kept_supports": sum(1 for r, _ in keep if r == "supports"),
                "kept_contradicts": sum(1 for r, _ in keep if r == "contradicts"),
                "kept_total": len(keep),
                "claims_with_evidence": len({cid for _, cid in keep}),
                "is_live_setting": w == live,
            })

        return _result("e_time_window_ablation", "E — ablation cửa sổ thời gian",
                       measured=True,
                       live_window_after=live,
                       rows=rows,
                       note=("Cửa sổ hiện tại cho phép bằng chứng đi sau claim tới 50 năm. "
                             "Bảng này cho biết siết lại thì còn giữ được bao nhiêu bằng chứng."),
                       caveat=("Chỉ phát lại được những mẩu bằng chứng ĐÃ được giữ, nên đây là "
                               "cận trên: nó không cho biết cửa sổ hẹp hơn sẽ đẩy thêm cặp mới "
                               "nào vào top-k."),
                       source="aaa_claim_assessments.json + aaa_crosscheck_stats.json")

    def retrieval_yield(self) -> Dict[str, Any]:
        """Share of retrieved candidate pairs the adjudicator kept as evidence.

        This is the honest replacement for the deleted "Context Precision@5": it
        is the same quantity RAGAS precision would measure IF the adjudicator's
        own verdict is taken as the relevance judgement — which is the caveat that
        makes it a diagnostic rather than a validation. The judge is grading the
        retriever, and the same model produced both."""
        evidence = self._all_evidence()
        candidates = (self.stats.get("retrieval") or {}).get("candidate_pairs")
        if candidates is None:
            return _result("retrieval_yield", "Retrieval yield (kept / candidate pairs)",
                           measured=False, reason="aaa_crosscheck_stats.json thieu truong candidate_pairs")

        by_bucket = Counter(e["_bucket"] for e in evidence)
        claims_with_evidence = sum(1 for d in self.dossiers
                                   if (d.get("supporting_evidence")
                                       or d.get("contradicting_evidence")
                                       or d.get("flagged_non_independent_support")))
        return _result("retrieval_yield", "Retrieval yield (kept / candidate pairs)",
                       measured=True,
                       score=round(len(evidence) / candidates, 4),
                       numerator=len(evidence), denominator=candidates,
                       by_bucket=dict(by_bucket),
                       claims_with_any_evidence=claims_with_evidence,
                       total_claims=len(self.dossiers),
                       caveat=("\"Liên quan\" ở đây chính là phán quyết của adjudicator, nên đây là "
                               "lấy chính model đã phán xử để chấm điểm tầng truy hồi. Mang tính "
                               "chẩn đoán, không phải kiểm định độc lập."),
                       source="aaa_claim_assessments.json + aaa_crosscheck_stats.json")

    def internal_score_disagreement(self) -> Dict[str, Any]:
        """How often the offline evidence-balance score disagrees with the LLM's
        own assessment on the same dossier. Two views of one dossier disagreeing
        is a free internal-consistency signal — no second rater needed."""
        if not self.dossiers:
            return _result("internal_score_disagreement", "Internal score/assessment disagreement",
                           measured=False, reason="khong co file dossier tren dia")
        flagged = sum(1 for d in self.dossiers if d.get("score_disagrees_with_assessment"))
        return _result("internal_score_disagreement", "Internal score/assessment disagreement",
                       measured=True,
                       score=round(flagged / len(self.dossiers), 4),
                       numerator=flagged, denominator=len(self.dossiers),
                       note="Số hồ sơ mà điểm tính offline mâu thuẫn với phán quyết của LLM.",
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    def confidence_spectrum(self) -> Dict[str, Any]:
        """Distribution of the LLM's self-reported confidence.

        Reported as a FINDING, not a score: docs §8 records calibration (ECE /
        Brier) as dead here because the model emits only a handful of distinct
        values and nothing below 0.8. That collapse is itself the result worth
        printing — a confidence field with no spread cannot rank anything."""
        vals = Counter()
        for e in self._all_evidence():
            c = e.get("confidence")
            if c is not None:
                vals[c] += 1
        return _result("confidence_spectrum", "LLM confidence spectrum",
                       measured=True, score=None,
                       distribution={str(k): v for k, v in sorted(vals.items())},
                       distinct_values=len(vals),
                       minimum=min(vals) if vals else None,
                       note=("Quá ít giá trị phân biệt để hiệu chuẩn — ghi nhận như một phát hiện, "
                             "không phải một metric. Calibration đã chết ở đây "
                             "(docs/EVALUATION_WITHOUT_LABELS.md §8)."),
                       source="graph_output/crosscheck/aaa_claim_assessments.json")

    # ------------------------------------------------------------------ #
    @staticmethod
    def not_computable() -> Dict[str, Dict[str, Any]]:
        """Metrics named in evalu.pdf / the old report that are NOT computed, each
        with the reason. Printed in the report so their absence is visible: a
        silently missing metric reads as an oversight, a listed one reads as a
        boundary."""
        return {
            "ragas_context_recall": {
                "metric": "RAGAS Context Recall",
                "measured": False,
                "reason": ("Cần tập ground-truth về những bằng chứng LẼ RA phải được truy hồi. "
                           "Không có nhãn nào tồn tại — đó chính là tiền đề của đề tài. "
                           "Đã ghi nhận là metric chết trong docs/EVALUATION_WITHOUT_LABELS.md §8."),
                "cost_to_obtain": "gán nhãn thủ công tập bằng chứng vét cạn cho từng claim",
            },
            "ragas_faithfulness": {
                "metric": "RAGAS Faithfulness",
                "measured": False,
                "reason": ("Cần phán xử xem mỗi phần giải thích có được suy ra từ chính văn bản "
                           "bằng chứng hay không — tốn một lệnh gọi LLM-judge cho mỗi hồ sơ, và "
                           "sẽ là tự chấm điểm mình nếu dùng lại cùng một model. Không suy ra "
                           "được từ artifact."),
                "cost_to_obtain": "191 lệnh gọi judge (hoặc một model độc lập thứ hai)",
            },
            "mr1_negation_flip": {
                "metric": "MR-1 Negation Flip", "measured": False,
                "reason": ("Cần chạy lại adjudicator THẬT trên claim đã bị chèn phủ định. "
                           "Chạy trên stub thì chỉ đo được chính cái stub."),
                "cost_to_obtain": "~191 lệnh gọi LLM",
            },
            "mr2_numeric_flip": {
                "metric": "MR-2 Numeric Flip", "measured": False,
                "reason": "Cần chạy lại adjudicator THẬT trên bằng chứng đã đảo dấu con số.",
                "cost_to_obtain": "~191 lệnh gọi LLM",
            },
            "mr3_entity_change": {
                "metric": "MR-3 Entity Change", "measured": False,
                "reason": "Cần chạy lại adjudicator THẬT với tên doanh nghiệp bị thay thế.",
                "cost_to_obtain": "~191 lệnh gọi LLM",
            },
            "mr4_temporal_shift": {
                "metric": "MR-4 Temporal Shift (P8)", "measured": False,
                "reason": ("Cần chạy lại adjudicator THẬT với bằng chứng có ngày sau ngày của "
                           "claim."),
                "cost_to_obtain": "~191 lệnh gọi LLM",
            },
            "b1_negative_control_specificity": {
                "metric": "B1 — Specificity trên cặp ngẫu nhiên",
                "measured": False,
                "reason": ("Đây là kill-test của cả thiết kế: cặp (claim, conduct) ghép ngẫu "
                           "nhiên có bị phán là irrelevant không? Cần adjudicator THẬT chấm trên "
                           "những cặp mà retrieval KHÔNG chọn. Không thể giả — module cũ đã "
                           "hardcode sẵn 99/100 cho chỉ số này."),
                "cost_to_obtain": "191 lệnh gọi LLM (~5,5% một lần chạy step07)",
            },
            "retained_vs_discarded": {
                "metric": "Độ chọn lọc của adjudicator (cặp giữ lại vs cặp bị loại)",
                "measured": False,
                "reason": ("Sẽ khiến B2b hết vòng luẩn quẩn, nhưng step07 không lưu lại 3.270 cặp "
                           "ứng viên bị loại — chỉ lưu 191 cặp được giữ. Cần tách phần retrieval "
                           "trong run() thành một hàm gọi được, rồi chạy lại offline miễn phí."),
                "cost_to_obtain": "0 lệnh gọi LLM, nhưng phải refactor nhẹ claims_vs_conduct.run()",
            },
            "inter_annotator_agreement": {
                "metric": "IAA chuyên gia (Krippendorff α / Gwet AC2)",
                "measured": False,
                "reason": ("Chưa có đánh giá của người thật. evalu/sample_expert_annotations.json "
                           "chỉ chứa 4 dòng tổng hợp sẵn, không đủ để tính hệ số đồng thuận — "
                           "báo cáo cũ đã in ra α=0,5143 từ chính 4 dòng này."),
                "cost_to_obtain": ">=3 người chấm độc lập trên >=30 hồ sơ",
            },
        }

    def run_all(self) -> Dict[str, Any]:
        return {
            "b2_permutation_test": self.b2_permutation_test(),
            "b2b_pairing_coherence": self.b2b_pairing_coherence(),
            "b3_structural_negative_control": self.b3_structural_negative_control(),
            "d_anachronism": self.d_anachronism(),
            "e_time_window_ablation": self.e_time_window_ablation(),
            "duplicate_claim_consistency": self.duplicate_claim_consistency(),
            "retrieval_yield": self.retrieval_yield(),
            "internal_score_disagreement": self.internal_score_disagreement(),
            "confidence_spectrum": self.confidence_spectrum(),
            "not_computable": self.not_computable(),
        }


if __name__ == "__main__":
    print(json.dumps(LabelFreeEvaluator().run_all(), indent=2, ensure_ascii=False))
