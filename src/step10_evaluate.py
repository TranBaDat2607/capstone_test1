"""Step 8 / P6 — Evaluation for the Vietnamese greenwashing-evidence POC (AAA).

System context: docs/SYSTEM_DESIGN.md §10 (evaluation without ground truth) + §11 (P6) and
docs/EVALUATION.md.

Because there is NO greenwashing ground truth (SYSTEM_DESIGN §1.1), this stage does not measure
"greenwashing accuracy". It validates the evidence-linking machinery and demonstrates utility,
via four methods:
  1. Coverage metrics      — how much independent conduct evidence exists (offline, free).
  2. Case studies          — narrated end-to-end examples (offline, free).
  3. Manual link-precision — methodology (described here + docs/EVALUATION.md), with a small
                             illustrative indicator from the 30-case gold set.
  4. Ablations             — LLM adjudicator vs a naive lexical baseline on the 30 gold cases
                             (the ONLY part that spends money — OpenAI, ~30 calls, cached), plus
                             a free corpus-level structural-vs-LLM ablation over all dossiers.

All rendered output is in Vietnamese (the POC audience); the code/comments are English to match
the rest of the repo. Framing is non-negotiable: evidence + an advisory opinion, never a score
or a verdict.

Run from the repo root (all sections default to building the full report):
    python src/step10_evaluate.py                       # full Vietnamese report → graph_output/evaluation/
    python src/step10_evaluate.py --coverage            # just the coverage section, to stdout   (free)
    python src/step10_evaluate.py --case-studies        # just the case studies, to stdout        (free)
    python src/step10_evaluate.py --ablation --no-llm    # baseline + corpus structural ablation   (free)
    python src/step10_evaluate.py --ablation             # + the 30-case OpenAI adjudication ablation (~$0.02)
"""

import argparse
import csv
import json
import logging
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SRC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SRC_DIR.parent

# ---- default artifact locations (all already on disk; evaluation is offline-first) ----
DEFAULT_ASSESSMENTS = REPO_ROOT / "graph_output" / "crosscheck" / "aaa_claim_assessments.json"
DEFAULT_STATS = REPO_ROOT / "graph_output" / "crosscheck" / "aaa_crosscheck_stats.json"
DEFAULT_CASES = REPO_ROOT / "config" / "evaluation" / "ablation_cases.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "evaluation"
# coverage.csv has moved around; try the known locations in order.
COVERAGE_CANDIDATES = [
    REPO_ROOT / "data" / "interim" / "news_sentences" / "coverage.csv",
    REPO_ROOT / "data" / "outputs" / "news" / "coverage.csv",
]

VERDICTS = ("supports", "contradicts", "irrelevant")

# Vietnamese labels for the advisory assessments and verdicts.
ASSESS_VI = {
    "appears_supported": "Có vẻ được chứng thực",
    "appears_contradicted": "Có vẻ bị mâu thuẫn",
    "unverified_insufficient_evidence": "Chưa kiểm chứng / thiếu bằng chứng",
}
VERDICT_VI = {
    "supports": "chứng thực (supports)",
    "contradicts": "mâu thuẫn (contradicts)",
    "irrelevant": "không liên quan (irrelevant)",
}

COVERAGE_CAVEAT_VI = (
    "Độ phủ tin tức thấp nghĩa là *có ít bằng chứng độc lập được tìm thấy*, KHÔNG phải là "
    "*doanh nghiệp trong sạch*. Vắng bằng chứng mâu thuẫn không đồng nghĩa với vô can "
    "(SYSTEM_DESIGN §8.3)."
)


# --------------------------------------------------------------------------- shared helpers
def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows PowerShell needs this for VN diacritics
    except Exception:
        pass


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_assessments(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        logger.error(f"Missing dossier file {path}. Run src/step07_crosscheck_claims_vs_conduct.py first.")
        sys.exit(1)
    return _load_json(path)


def load_stats(path: Path) -> Dict[str, Any]:
    return _load_json(path) if path.exists() else {}


def load_coverage(path: Optional[Path]) -> List[Dict[str, str]]:
    p = path or next((c for c in COVERAGE_CANDIDATES if c.exists()), None)
    if not p or not p.exists():
        logger.warning("coverage.csv not found; sector-coverage section will be limited.")
        return []
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- 1. coverage (§10, free)
def build_coverage_section(ticker: str, stats: Dict[str, Any],
                           coverage: List[Dict[str, str]]) -> str:
    t = ticker.upper()
    row = next((r for r in coverage if r.get("ticker", "").upper() == t), None)
    lines = ["## 2. Độ phủ dữ liệu (Coverage)", "",
             "Độ phủ đo *lượng bằng chứng độc lập* thu thập được, không đo mức độ vi phạm.", ""]

    # 2.1 issuer coverage
    lines += ["### 2.1 Độ phủ của doanh nghiệp khảo sát"]
    if row:
        lines += [
            f"- **{t} — {row.get('company', '')}**",
            f"  - Bài báo thu thập: **{row.get('articles', '?')}**; câu tin tức: "
            f"**{row.get('sentences', '?')}**.",
            f"  - Ứng viên truy vấn: {row.get('candidates', '?')}; tải thành công: "
            f"{row.get('fetched_ok', '?')}.",
            f"  - Nguồn nhiều nhất: {row.get('top_domains', '—')}",
        ]
    else:
        lines.append(f"- Không tìm thấy dòng coverage cho {t}.")
    lines.append("")

    # 2.2 conduct pool actually landed in the graph (from crosscheck stats)
    pool = (stats.get("conduct_pool") or {})
    by_class = pool.get("by_class") or {}
    assess = (stats.get("assessments") or {})
    lines += ["### 2.2 Bằng chứng phía \"hành vi\" (conduct) đã vào đồ thị"]
    if by_class:
        pool_bits = ", ".join(f"{v} {k}" for k, v in sorted(by_class.items(), key=lambda kv: -kv[1]))
        lines += [
            f"- Tổng node conduct (source_type=news) gắn với {t}: **{pool.get('total', '?')}** "
            f"({pool_bits}).",
            f"- Số claim của {t}: **{stats.get('claims', '?')}**; cặp (claim, conduct) được truy "
            f"hồi: {(stats.get('retrieval') or {}).get('candidate_pairs', '?')} "
            f"(trung bình {(stats.get('retrieval') or {}).get('avg_candidates_per_claim', '?')} "
            f"ứng viên/claim).",
        ]
    if assess:
        lines += [
            "- Phân bố đánh giá tư vấn (advisory):",
            f"  - {ASSESS_VI['appears_supported']}: **{assess.get('appears_supported', 0)}**",
            f"  - {ASSESS_VI['appears_contradicted']}: **{assess.get('appears_contradicted', 0)}**",
            f"  - {ASSESS_VI['unverified_insufficient_evidence']}: "
            f"**{assess.get('unverified_insufficient_evidence', 0)}**",
        ]
    lines.append("")

    # 2.3 sector-wide context (all companies in coverage.csv) — shows scalability
    if coverage:
        arts = [int(r["articles"]) for r in coverage if r.get("articles", "").isdigit()]
        sents = [int(r["sentences"]) for r in coverage if r.get("sentences", "").isdigit()]
        thin = [r["ticker"] for r in coverage
                if r.get("sentences", "").isdigit() and int(r["sentences"]) < 900]
        lines += [
            "### 2.3 Bối cảnh toàn ngành (khả năng mở rộng)",
            f"- Đã thu thập tin tức cho **{len(coverage)}** doanh nghiệp niêm yết "
            f"(ngành Xây dựng / Vật liệu / Bất động sản).",
            f"- Tổng cộng ~**{sum(arts):,}** bài báo và ~**{sum(sents):,}** câu tin tức "
            f"(trung vị {int(statistics.median(sents)) if sents else '?'} câu/doanh nghiệp).",
            f"- Doanh nghiệp có độ phủ mỏng (< 900 câu): {len(thin)} "
            f"({', '.join(thin[:12])}{'…' if len(thin) > 12 else ''}).",
            "",
        ]

    lines += [f"> ⚠ **Lưu ý độ phủ:** {COVERAGE_CAVEAT_VI}", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- 2. case studies (§10, free)
# Genuine environmental language only — the negative lookahead avoids "working environment"
# (a Social/HR phrase) being mistaken for an Environmental claim.
GREEN_KEYWORDS = re.compile(
    r"thân thiện (với )?môi trường|môi trường(?! làm việc)|tái chế|recycl|environmentally friendly|"
    r"nước thải|xả thải|no discharge|green company|công ty xanh|carbon|phát thải|"
    r"năng lượng tái tạo|sinh học|compostable",
    re.IGNORECASE)
# Preferred environmental claims for the §3.3 unverified case study (first match that exists).
GREEN_PREFER_IDS = [
    "AnPhat_2011_EnvFriendlyPackaging",
    "AAA_Baocaothuongnien_2016.pdf_28_water_reuse_claim",
    "AAA_Baocaothuongnien_2016.pdf_28_no_environmental_penalty_claim",
]


def _pick(dossiers: List[Dict[str, Any]], assessment: str,
          prefer_ids: Optional[List[str]] = None,
          keyword: Optional[re.Pattern] = None) -> Optional[Dict[str, Any]]:
    pool = [d for d in dossiers if d.get("assessment") == assessment]
    for pid in (prefer_ids or []):
        hit = next((d for d in pool if d.get("claim_id") == pid), None)
        if hit:
            return hit
    if keyword:
        kw = [d for d in pool if keyword.search(d.get("claim_text", ""))]
        if kw:
            return kw[0]

    def _max_conf(d):
        bucket = "contradicting_evidence" if assessment == "appears_contradicted" else "supporting_evidence"
        return max((float(e.get("confidence") or 0) for e in d.get(bucket, [])), default=0)

    return max(pool, key=_max_conf) if pool else None


def _narrate_case(d: Dict[str, Any], maxlen: int) -> List[str]:
    a = d.get("assessment")
    bucket = "contradicting_evidence" if a == "appears_contradicted" else "supporting_evidence"
    mark = "✗" if a == "appears_contradicted" else "✓"
    out = [
        f"- **Claim** `{d.get('claim_id', '?')}` (năm {d.get('year', '?')}, "
        f"nguồn={d.get('claim_source_type', 'report')}):",
        f"  > {_truncate(d.get('claim_text', ''), maxlen)}",
        f"- **Đánh giá tư vấn:** {ASSESS_VI.get(a, a)} *(advisory — không phải phán quyết)*",
    ]
    ev_items = d.get(bucket, [])
    if ev_items:
        out.append("- **Bằng chứng liên kết:**")
        for e in ev_items[:3]:
            dom = e.get("source_domain") or "news"
            conf = e.get("confidence")
            conf = f"{float(conf):.2f}" if conf is not None else "?"
            out.append(f"  - {mark} `{e.get('class', '?')}` (độ tin cậy {conf}, năm "
                       f"{e.get('year', '?')}, {dom}): \"{_truncate(e.get('text', ''), maxlen)}\"")
            if e.get("rationale"):
                out.append(f"    - *Lý giải (LLM):* {_truncate(e['rationale'], maxlen + 160)}")
    else:
        out.append("- **Bằng chứng liên kết:** (không có bằng chứng độc lập nào được liên kết)")
    for cv in d.get("caveats", []) or []:
        out.append(f"- *Cảnh báo:* {cv}")
    return out


def build_case_studies_section(dossiers: List[Dict[str, Any]], maxlen: int) -> str:
    lines = ["## 3. Nghiên cứu tình huống (Case studies)", "",
             "Mỗi tình huống được thuật lại đầu-cuối để kiểm tra hệ thống có *surface đúng* "
             "liên kết bằng chứng hay không (SYSTEM_DESIGN §10).", ""]

    contra = _pick(dossiers, "appears_contradicted", prefer_ids=["AAA_SC_001"])
    support = _pick(dossiers, "appears_supported",
                    prefer_ids=["AnPhat_2012_HR_FrequentBonusSystem_P49"])
    unver = _pick(dossiers, "unverified_insufficient_evidence",
                  prefer_ids=GREEN_PREFER_IDS, keyword=GREEN_KEYWORDS)

    if contra:
        lines += ["### 3.1 Trường hợp \"Có vẻ bị mâu thuẫn\"", ""]
        lines += _narrate_case(contra, maxlen)
        lines += ["", "Đây chính là *payoff* của đồ thị: claim khẳng định tăng trưởng, nhưng một "
                  "chỉ số quan sát độc lập cho thấy điều ngược lại — hệ thống đưa cả hai lên một "
                  "node doanh nghiệp và để nhà phân tích tự kết luận.", ""]

    if support:
        lines += ["### 3.2 Trường hợp \"Có vẻ được chứng thực\"", ""]
        lines += _narrate_case(support, maxlen)
        lines += ["", "Bằng chứng độc lập (không phải chính doanh nghiệp) củng cố cho claim; "
                  "self-verification guard đảm bảo tin từ chính domain của doanh nghiệp không được "
                  "tính là \"chứng thực\".", ""]

    if unver:
        lines += ["### 3.3 Trường hợp \"Chưa kiểm chứng / thiếu bằng chứng\"", ""]
        lines += _narrate_case(unver, maxlen)
        lines += ["", "Không có liên kết KHÔNG có nghĩa là claim sai — chỉ là *chưa tìm được* bằng "
                  "chứng độc lập tương ứng trong phạm vi tin đã thu thập (xem lưu ý độ phủ).", ""]

    # 3.4 the known gap: the tax-penalty controversy that is not yet in the graph (P5 note)
    lines += [
        "### 3.4 Khoảng trống đã biết: vụ phạt thuế (chưa vào đồ thị)",
        "",
        "Một minh hoạ kinh điển của greenwashing với AAA là: doanh nghiệp tự định vị *\"tiên "
        "phong sản phẩm nhựa thân thiện môi trường\"* (claim Môi trường), trong khi báo chí độc "
        "lập đưa tin *\"Khai sai thuế, Nhựa An Phát Xanh bị xử lý hơn 1,7 tỷ đồng\"* "
        "(`vietnamnet.vn`, 2024 — một `Controversy`/`Penalty` phía Quản trị).",
        "",
        "Cặp mâu thuẫn này **chưa** xuất hiện trong lần chạy hiện tại: bài báo về vụ phạt thuế "
        "chưa được trích xuất thành node `Penalty`/`Controversy` (xem `CLAIM_CONDUCT_CROSSCHECK.md` "
        "§6/§8 và SYSTEM_DESIGN §11 P5). Đây là một hạn chế về *độ phủ trích xuất*, không phải về "
        "logic cross-check — khi bài báo được trích xuất lại, cặp claim↔conduct này sẽ được liên "
        "kết như các trường hợp ở §3.1.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- 3+4. ablation
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on", "at", "by", "is", "are",
    "as", "its", "it", "from", "that", "this", "has", "have", "company", "aaa", "vnd", "achieved",
    "va", "cua", "cac", "trong", "nam", "la", "cho", "den", "cong", "ty", "voi", "cong ty",
    "billion", "million", "ty", "trieu", "%",
}
CLAIM_POSITIVE = {
    "growth", "grow", "increase", "increased", "increasing", "highest", "exceeding", "exceed",
    "expected", "ensures", "ensure", "ensuring", "maintain", "maintained", "stable", "pioneering",
    "largest", "leading", "leader", "boosted", "boost", "high", "tăng", "tăng trưởng", "cao nhất",
    "dẫn dắt", "lớn nhất", "vượt",
}
EVIDENCE_NEGATIVE = {
    "decrease", "decreased", "decline", "reduction", "reduce", "reduced", "below", "lower",
    "loss", "fell", "drop", "giảm", "sụt", "thấp", "lỗ",
}


def _tokens(s: str) -> set:
    toks = set(re.findall(r"\w+", (s or "").lower(), re.UNICODE))
    return {t for t in toks if len(t) >= 3 and t not in STOPWORDS}


def _has_negative_number(s: str) -> bool:
    # a real minus sign before a number (not a hyphen inside a range like "80-85")
    return bool(re.search(r"(?<!\d)-\s*\d", s or ""))


def baseline_verdict(case: Dict[str, Any]) -> str:
    """A deliberately naive, explainable lexical baseline (the 'no-LLM' arm of the ablation):
    topic overlap decides relevant-vs-irrelevant; polarity decides supports-vs-contradicts.
    It cannot compare magnitudes (e.g. EPS 2,550 vs 1,213), which is precisely where the LLM helps."""
    claim_t = _tokens(case["claim_text"])
    ev_t = _tokens(case["evidence_text"])
    overlap = claim_t & ev_t
    if not overlap:
        return "irrelevant"
    ev_negative = bool(ev_t & EVIDENCE_NEGATIVE) or _has_negative_number(case["evidence_text"])
    claim_positive = bool(claim_t & CLAIM_POSITIVE)
    if ev_negative and claim_positive:
        return "contradicts"
    return "supports"


def _cache_path(out_dir: Path) -> Path:
    return out_dir / "ablation_llm_results.json"


def run_llm_arm(cases: List[Dict[str, Any]], args: argparse.Namespace,
                out_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Adjudicate the (capped) gold cases via the reused cross-check Adjudicator (OpenAI).
    Cached per (model, case_id) so re-runs cost nothing. Returns {case_id: verdict_record}."""
    cache = {}
    cpath = _cache_path(out_dir)
    if cpath.exists() and not args.refresh:
        cache = _load_json(cpath)
    model_key = args.openai_model
    cache.setdefault(model_key, {})

    todo = [c for c in cases if c["id"] not in cache[model_key]]
    if not todo:
        logger.info(f"All {len(cases)} cases cached for model '{model_key}' — 0 new LLM calls.")
        return cache[model_key]

    try:
        sys.path.insert(0, str(SRC_DIR))
        from step07_crosscheck_claims_vs_conduct import Adjudicator
    except Exception as e:
        logger.error(f"Cannot import Adjudicator ({e}); skipping the LLM arm.")
        return cache[model_key]

    adjud = Adjudicator(gemini_model=args.model, openai_model=args.openai_model,
                        rate_limit=args.rate_limit, order=args.provider_order.split(","))
    if not adjud.enabled:
        logger.warning("No LLM provider available (billing/key). LLM arm skipped; offline parts still render.")
        return cache[model_key]

    logger.info(f"Adjudicating {len(todo)} uncached cases via {args.provider_order} "
                f"(model {model_key}) — capped, ~{len(todo)} calls.")
    for c in todo:
        res = adjud.adjudicate(c["claim_text"], c["evidence_text"], c["evidence_meta"])
        if res is None:
            logger.warning(f"[{c['id']}] no verdict returned (provider down); leaving uncached.")
            continue
        cache[model_key][c["id"]] = {
            "verdict": res.get("verdict"), "confidence": res.get("confidence"),
            "rationale": res.get("rationale"), "provider": res.get("provider"),
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)
    logger.info(f"Wrote LLM ablation cache → {cpath}")
    return cache[model_key]


def score(pred: Dict[str, str], ref: Dict[str, str]) -> Dict[str, Any]:
    """Accuracy + per-class precision/recall/F1 + confusion counts, over cases present in `pred`."""
    ids = [i for i in ref if i in pred]
    n = len(ids)
    correct = sum(1 for i in ids if pred[i] == ref[i])
    confusion: Counter = Counter()  # (ref, pred) -> count
    for i in ids:
        confusion[(ref[i], pred[i])] += 1
    per_class = {}
    for c in VERDICTS:
        tp = sum(1 for i in ids if ref[i] == c and pred[i] == c)
        fp = sum(1 for i in ids if ref[i] != c and pred[i] == c)
        fn = sum(1 for i in ids if ref[i] == c and pred[i] != c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[c] = {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1}
    return {"n": n, "correct": correct, "accuracy": correct / n if n else 0.0,
            "per_class": per_class, "confusion": confusion}


def _confusion_table_vi(confusion: Counter) -> List[str]:
    header = "| thực tế (ref) \\ dự đoán | " + " | ".join(VERDICTS) + " |"
    sep = "|" + "---|" * (len(VERDICTS) + 1)
    rows = [header, sep]
    for r in VERDICTS:
        cells = " | ".join(str(confusion.get((r, p), 0)) for p in VERDICTS)
        rows.append(f"| **{r}** | {cells} |")
    return rows


def build_ablation_section(cases: List[Dict[str, Any]], dossiers: List[Dict[str, Any]],
                           args: argparse.Namespace, out_dir: Path) -> str:
    ref = {c["id"]: c["reference_verdict"] for c in cases}
    base_pred = {c["id"]: baseline_verdict(c) for c in cases}
    base = score(base_pred, ref)

    llm_records = {} if args.no_llm else run_llm_arm(cases, args, out_dir)
    llm_pred = {cid: rec["verdict"] for cid, rec in llm_records.items() if rec.get("verdict")}
    llm = score(llm_pred, ref) if llm_pred else None

    lines = ["## 5. Ablation — đóng góp của từng thành phần", "",
             f"Bộ gold gồm **{len(cases)}** cặp (claim, bằng chứng) do người gán nhãn tham chiếu "
             "(10 supports / 10 contradicts / 10 irrelevant; xem `config/evaluation/ablation_cases.json`). "
             "Đây KHÔNG phải gold greenwashing — nó chỉ chấm *độ đúng của liên kết bằng chứng*.", ""]

    # 5.1 baseline vs LLM on the 30 cases
    lines += ["### 5.1 Baseline từ vựng (không LLM) vs. LLM adjudicator", "",
              f"- **Baseline** (chỉ dùng chồng lấp từ khoá + dấu hiệu tăng/giảm): độ đồng thuận với "
              f"nhãn tham chiếu = **{base['accuracy']*100:.1f}%** ({base['correct']}/{base['n']}).",
              ]
    if llm:
        prov = next((r.get("provider") for r in llm_records.values() if r.get("provider")), args.openai_model)
        lines.append(f"- **LLM** ({prov}): độ đồng thuận = **{llm['accuracy']*100:.1f}%** "
                     f"({llm['correct']}/{llm['n']}).")
    else:
        lines.append("- **LLM**: chưa chạy (dùng `--ablation` không kèm `--no-llm`, cần OPENAI_API_KEY "
                     "còn hạn mức). Phần dưới sẽ tự bổ sung khi có kết quả LLM.")
    lines.append("")

    lines += ["**Ma trận nhầm lẫn — Baseline:**", ""] + _confusion_table_vi(base["confusion"]) + [""]
    if llm:
        lines += ["**Ma trận nhầm lẫn — LLM:**", ""] + _confusion_table_vi(llm["confusion"]) + [""]

    # per-class precision/recall table
    lines += ["**Precision / Recall / F1 theo lớp:**", "",
              "| lớp | baseline P | baseline R | baseline F1 | LLM P | LLM R | LLM F1 |",
              "|---|---|---|---|---|---|---|"]
    for c in VERDICTS:
        b = base["per_class"][c]
        if llm:
            l = llm["per_class"][c]
            lcells = f"{l['precision']:.2f} | {l['recall']:.2f} | {l['f1']:.2f}"
        else:
            lcells = "— | — | —"
        lines.append(f"| {c} | {b['precision']:.2f} | {b['recall']:.2f} | {b['f1']:.2f} | {lcells} |")
    lines.append("")

    # 5.2 per-case detail table
    lines += ["### 5.2 Chi tiết từng ca", "",
              "| id | tham chiếu | baseline | LLM | loại |",
              "|---|---|---|---|---|"]
    for c in cases:
        cid = c["id"]
        lp = llm_pred.get(cid, "—")
        b_ok = "✓" if base_pred[cid] == ref[cid] else "✗"
        l_ok = "✓" if (cid in llm_pred and llm_pred[cid] == ref[cid]) else ("✗" if cid in llm_pred else "—")
        lines.append(f"| {cid} | {ref[cid]} | {base_pred[cid]} {b_ok} | {lp} {l_ok} | {c['case_type']} |")
    lines.append("")

    # 5.3 corpus-level structural-vs-LLM ablation (free, over all dossiers)
    lines += _corpus_structural_ablation_vi(dossiers)

    # 5.4 interpretation + link-precision note
    lines += [
        "### 5.4 Diễn giải",
        "",
        "- Baseline bắt được các mâu thuẫn có *từ khoá tăng/giảm rõ ràng* (ví dụ \"revenue "
        "decrease -42.3%\" so với claim \"ensures growth\") và loại đúng phần lớn cặp *khác chủ đề* "
        "(irrelevant dựng sẵn), nhưng **không so sánh được độ lớn số** (EPS 2.550 vs 1.213) nên bỏ "
        "sót nhiều mâu thuẫn định lượng — đây là chỗ LLM đóng góp.",
        "- Một số ca `real` được gán nhãn tham chiếu là *irrelevant* dù bản chạy production trả về "
        "*contradicts* (ví dụ IR01–IR05): đó là các ca lệch cửa sổ thời gian hoặc chỉ số không thực "
        "sự đo điều claim khẳng định — cố tình đưa vào để lộ điểm yếu (SYSTEM_DESIGN §12).",
        "- **Chỉ báo link-precision (minh hoạ):** trên bộ 30 ca, độ đồng thuận LLM↔người là "
        + (f"**{llm['accuracy']*100:.1f}%**" if llm else "*(chạy `--ablation` để có số)*")
        + ". Đây chỉ là *chỉ báo* trên mẫu nhỏ; phương pháp đánh giá link-precision đầy đủ ở §4.",
        "",
    ]
    return "\n".join(lines)


def _corpus_structural_ablation_vi(dossiers: List[Dict[str, Any]]) -> List[str]:
    n = len(dossiers)
    struct = sum(1 for d in dossiers if (d.get("signals") or {}).get("structural_contradiction"))
    has_contra_ev = sum(1 for d in dossiers if d.get("contradicting_evidence"))
    indep_support = sum(1 for d in dossiers if any(e.get("independent")
                        for e in d.get("supporting_evidence", [])))
    supported = sum(1 for d in dossiers if d.get("assessment") == "appears_supported")
    contradicted = sum(1 for d in dossiers if d.get("assessment") == "appears_contradicted")
    flagged = sum(1 for d in dossiers if d.get("flagged_non_independent_support"))
    struct_only_edge = struct - has_contra_ev  # contradicted via a pre-existing graph edge only
    return [
        "### 5.3 Ablation cấp toàn corpus: chỉ-cấu-trúc vs. +LLM (miễn phí)",
        "",
        f"Trên toàn bộ **{n}** claim của doanh nghiệp:",
        "",
        "| cấu hình | Có vẻ mâu thuẫn | Có vẻ chứng thực | Chưa kiểm chứng |",
        "|---|---|---|---|",
        f"| **Chỉ tín hiệu cấu trúc** (không LLM) | {struct} | 0 | {n - struct} |",
        f"| **+LLM (hybrid đầy đủ)** | {contradicted} | {supported} | "
        f"{n - contradicted - supported} |",
        "",
        f"- Tín hiệu cấu trúc (claim có cạnh mâu thuẫn & không có xác minh) tự nó gắn cờ **{struct}** "
        f"claim cho hàng đợi rà soát, nhưng **không tạo được đánh giá \"chứng thực\" nào** (cấu trúc "
        "không thể *củng cố* claim).",
        f"- LLM bổ sung toàn bộ trục *chứng thực*: **{indep_support}** claim có bằng chứng độc lập "
        f"củng cố (thành **{supported}** \"Có vẻ được chứng thực\" sau khi loại các claim đồng thời bị "
        "mâu thuẫn), cùng lý giải + độ tin cậy cho từng mâu thuẫn.",
        f"- Trong {struct} mâu thuẫn: **{has_contra_ev}** có bằng chứng mâu thuẫn kèm lý giải của LLM; "
        f"**{max(struct_only_edge, 0)}** đến từ cạnh mâu thuẫn có sẵn trong đồ thị (chỉ cấu trúc).",
        f"- **Self-verification guard** đã hạ cấp **{flagged}** \"chứng thực\" đến từ chính domain của "
        "doanh nghiệp — nếu không có guard, tín hiệu *support* sẽ bị thổi phồng (SYSTEM_DESIGN §6.4).",
        "",
    ]


# --------------------------------------------------------------------------- static VN sections
def build_intro_section(ticker: str, stats: Dict[str, Any]) -> str:
    issuer = (stats.get("issuer") or {})
    name = issuer.get("name", "CTCP Nhựa An Phát Xanh")
    return "\n".join([
        f"# Báo cáo đánh giá (P6) — {ticker.upper()} · {name}",
        "",
        f"*Sinh tự động bởi `src/step10_evaluate.py` lúc {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')} "
        "— đọc từ các artifact offline (dossier cross-check, coverage), không gọi Neo4j.*",
        "",
        "## 1. Khung đánh giá & ràng buộc",
        "",
        "Hệ thống **không có nhãn ground-truth greenwashing** cho doanh nghiệp Việt Nam "
        "(SYSTEM_DESIGN §1.1). Vì vậy đánh giá **không đo \"độ chính xác greenwashing\"** và "
        "**không có điểm số/phán quyết**. Thay vào đó, ta kiểm chứng *cỗ máy liên kết bằng chứng* "
        "và minh hoạ tính hữu ích qua 4 phương pháp (SYSTEM_DESIGN §10):",
        "",
        "1. **Độ phủ dữ liệu** — lượng bằng chứng độc lập có được (offline).",
        "2. **Nghiên cứu tình huống** — thuật lại vài claim đầu-cuối (offline).",
        "3. **Link-precision thủ công** — *phương pháp luận* + một chỉ báo minh hoạ trên bộ 30 ca.",
        "4. **Ablation** — LLM vs baseline trên 30 ca (phần duy nhất tốn phí, đã giới hạn & cache), "
        "cùng ablation chỉ-cấu-trúc vs +LLM trên toàn corpus (miễn phí).",
        "",
        "> Mọi kết luận cuối cùng thuộc về **con người**. Hệ thống chỉ *trình hiện bằng chứng + ý "
        "kiến tư vấn*, không tự phán xử.",
        "",
    ])


def build_precision_methodology_section() -> str:
    return "\n".join([
        "## 4. Link-precision thủ công — phương pháp luận", "",
        "Vì không có gold greenwashing, ta đo **độ chính xác của *liên kết*** (một cạnh "
        "`verifiedBy`/`contradictedBy*` do LLM đề xuất có đúng không?), **không** đo độ chính xác so "
        "với một nhãn greenwashing (SYSTEM_DESIGN §10).", "",
        "**Quy trình đề xuất (để mở rộng quy mô):**",
        "1. Lấy mẫu phân tầng các phán quyết đã ghi cạnh (supports/contradicts) theo lớp và theo độ "
        "tin cậy; kèm một phần các cặp *irrelevant* (cần bật log phán quyết ở bước 6 để có mẫu này).",
        "2. Ẩn nhãn của LLM; để **≥2 người** độc lập gán supports/contradicts/irrelevant cho từng cặp "
        "chỉ dựa trên *văn bản claim + bằng chứng*.",
        "3. Tính **độ đồng thuận người↔người** (ví dụ Cohen's κ) để xác nhận nhiệm vụ đủ rõ, rồi tính "
        "**độ đồng thuận LLM↔người** = *link-precision*.",
        "4. Báo cáo theo lớp (precision của contradicts thường quan trọng nhất vì nó nhạy cảm về danh "
        "tiếng), luôn kèm hạn chế (§6).", "",
        "**Chỉ báo hiện có:** bộ 30 ca (`config/evaluation/ablation_cases.json`) là một mẫu vàng nhỏ do "
        "tác giả gán nhãn; độ đồng thuận LLM↔nhãn tham chiếu trên bộ này (xem §5.1) là một *chỉ báo "
        "minh hoạ* cho link-precision, chưa thay thế được nghiên cứu đầy đủ với nhiều người gán nhãn.",
        "",
    ])


def build_limitations_section() -> str:
    return "\n".join([
        "## 6. Hạn chế & khung đạo đức", "",
        "(theo SYSTEM_DESIGN §12 — trình bày trung thực bên cạnh mọi con số)", "",
        "- **Chỉ mang tính tư vấn.** Hệ thống *gợi ý*, không *quyết định*. Không output nào là phán "
        "quyết greenwashing và không có điểm số. Cần con người rà soát trước mọi sử dụng đối ngoại.",
        "- **Doanh nghiệp thật, hàm ý nhạy cảm.** Đặt tên một công ty cạnh \"claim bị mâu thuẫn\" là "
        "nhạy cảm về danh tiếng; mọi đánh giá đều gắn *bài báo nguồn + ngày* để kiểm chứng và giữ ý "
        "kiến quy về LLM (`llm_suggested_*`).",
        "- **Không ground-truth ⇒ không tuyên bố accuracy.** Ta báo link-precision + case study, "
        "không báo accuracy phân loại.",
        "- **Thiên lệch độ phủ.** Vắng tin mâu thuẫn *không* là bằng chứng vô can; doanh nghiệp nhỏ / "
        "nhiều PR sẽ trông \"sạch\". Luôn kèm lưu ý độ phủ.",
        "- **Bất định ngày tháng.** `publish_date` không tin cậy làm yếu việc canh thời gian; được gắn "
        "cờ, không giấu (một số ca IR ở §5 chính là hệ quả của cửa sổ thời gian rộng).",
        "- **Lỗi LLM.** Phán quyết có thể ảo mâu thuẫn; structured output, bám văn bản, độ tin cậy và "
        "kiểm tra link-precision thủ công giúp giới hạn rủi ro.",
        "- **PR tự chứng thực.** Tin PR của chính doanh nghiệp nằm ở phía conduct; self-verification "
        "guard loại các cạnh `verifiedBy` từ domain của doanh nghiệp — nếu guard bỏ sót thì chỉ làm "
        "*support* bị thổi phồng (nới lỏng), không bao giờ tạo cáo buộc sai.",
        "- **Khoảng trống trích xuất.** Ví dụ vụ phạt thuế (§3.4) chưa vào đồ thị — hạn chế về độ phủ "
        "trích xuất, cần trích xuất lại bài báo.",
        "",
        "---",
        "",
        "*Báo cáo này chỉ trình hiện bằng chứng và ý kiến tư vấn. Không phải phán quyết greenwashing.*",
    ])


# --------------------------------------------------------------------------- report assembly
def build_full_report(ticker: str, dossiers: List[Dict[str, Any]], stats: Dict[str, Any],
                      coverage: List[Dict[str, str]], cases: List[Dict[str, Any]],
                      args: argparse.Namespace, out_dir: Path) -> str:
    parts = [
        build_intro_section(ticker, stats),
        build_coverage_section(ticker, stats, coverage),
        build_case_studies_section(dossiers, args.maxlen),
        build_precision_methodology_section(),
        build_ablation_section(cases, dossiers, args, out_dir),
        build_limitations_section(),
    ]
    return "\n".join(parts).rstrip() + "\n"


# --------------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> None:
    dossiers = load_assessments(args.assessments)
    stats = load_stats(args.stats)
    coverage = load_coverage(args.coverage)
    cases = _load_json(args.cases)["cases"] if args.cases.exists() else []
    if args.max_cases:
        cases = cases[: args.max_cases]
    out_dir = args.out_dir

    # section-only modes print to stdout; default assembles the full report to a file.
    only = args.coverage_only or args.case_studies_only or args.ablation_only
    if args.coverage_only:
        print(build_coverage_section(args.ticker, stats, coverage))
    if args.case_studies_only:
        print(build_case_studies_section(dossiers, args.maxlen))
    if args.ablation_only:
        if not cases:
            logger.error(f"No gold cases at {args.cases}.")
            sys.exit(1)
        print(build_ablation_section(cases, dossiers, args, out_dir))
    if only:
        return

    if not cases:
        logger.error(f"No gold cases at {args.cases}; cannot build the ablation section.")
        sys.exit(1)
    report = build_full_report(args.ticker, dossiers, stats, coverage, cases, args, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.ticker.lower()}_evaluation_report.md"
    out_path.write_text(report, encoding="utf-8")
    logger.info(f"Wrote Vietnamese evaluation report → {out_path} ({len(report):,} chars)")
    print(f"\nĐã ghi báo cáo đánh giá → {out_path}")
    print(f"  ({len(dossiers)} claim; {len(cases)} ca gold; "
          f"LLM arm = {'off (--no-llm)' if args.no_llm else 'on'})")


def main() -> None:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Step 8 / P6 — Vietnamese evaluation (coverage + case studies + ablation). "
                    "Offline by default; only the 30-case ablation optionally calls OpenAI.")
    p.add_argument("--ticker", default="AAA", help="Issuer to evaluate (default AAA).")
    # section-only switches (default = build the full report)
    p.add_argument("--coverage", dest="coverage_only", action="store_true",
                   help="Print only the coverage section (free).")
    p.add_argument("--case-studies", dest="case_studies_only", action="store_true",
                   help="Print only the case studies (free).")
    p.add_argument("--ablation", dest="ablation_only", action="store_true",
                   help="Print only the ablation section (LLM unless --no-llm).")
    # ablation controls
    p.add_argument("--no-llm", action="store_true",
                   help="Ablation: baseline + corpus structural only; no OpenAI calls.")
    p.add_argument("--refresh", action="store_true", help="Ignore the LLM ablation cache and re-call.")
    p.add_argument("--max-cases", type=int, default=None, help="Cap the gold cases used (cost/debug).")
    p.add_argument("--openai-model", default="gpt-4o-mini", help="OpenAI model for the LLM arm.")
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini model id (primary, if available).")
    p.add_argument("--provider-order", default="openai",
                   help="Adjudication provider order (default 'openai'; Gemini is billing-blocked).")
    p.add_argument("--rate-limit", type=int, default=60, help="LLM calls/minute cap.")
    # paths
    p.add_argument("--assessments", type=Path, default=DEFAULT_ASSESSMENTS, help="Dossier JSON.")
    p.add_argument("--stats", type=Path, default=DEFAULT_STATS, help="Cross-check stats JSON.")
    p.add_argument("--coverage-csv", dest="coverage", type=Path, default=None,
                   help="coverage.csv (auto-detected if omitted).")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="30-case gold fixture.")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Report + cache output dir.")
    p.add_argument("--maxlen", type=int, default=320, help="Truncate claim/evidence text length.")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
