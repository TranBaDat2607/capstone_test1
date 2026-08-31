#!/usr/bin/env python3
"""
run_evaluation.py — assembles the evaluation report from measured results only.

Three rules this runner enforces, all of them learned from the report it
replaces:

1. **A metric that could not be measured is printed as unmeasured, with its
   reason.** It is never dropped. A missing row reads as an oversight; a row
   saying "KHÔNG ĐO ĐƯỢC — needs N LLM calls" reads as a boundary, and the
   difference matters to a reader deciding what the system has actually been
   shown to do.
2. **Expert-rating tiers refuse to run on annotations that do not belong to this
   corpus.** The shipped `sample_expert_annotations.json` rates Vinamilk claims
   that appear in no dossier here; fed through the (correct) IAA engine it still
   produced a Krippendorff α, and the previous report presented that number as
   expert agreement. The engines are kept — the guard is what was missing.
3. **Nothing is rounded into a claim it cannot support.** Small denominators
   carry their Wilson interval; partly-circular metrics carry their caveat.

Offline: no LLM, no Neo4j, no network.
Run:  python evalu/run_evaluation.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

EVALU_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALU_DIR.parent
# Put the REPO ROOT on the path (not evalu/ itself), so these are absolute package
# imports like every other module here uses -- and so `python -m evalu.run_evaluation`
# works as well as `python evalu/run_evaluation.py`. Matches evalu/build_census_43.py.
sys.path.insert(0, str(REPO_ROOT))

from evalu.evalu_pipeline_metrics import PipelineEvaluator  # noqa: E402
from evalu.evalu_labelfree import LabelFreeEvaluator  # noqa: E402
from evalu.evalu_grounding import GroundingEvaluator  # noqa: E402
from evalu.evalu_iaa_engine import IAAEngine  # noqa: E402
from evalu.evalu_likert_rubric import LikertRubricEvaluator  # noqa: E402

ANNOTATIONS = EVALU_DIR / "sample_expert_annotations.json"
REPORT_JSON = EVALU_DIR / "evaluation_report.json"
REPORT_MD = EVALU_DIR / "evaluation_report.md"
REPORT_DOCX = EVALU_DIR / "evaluation_report.docx"
DOSSIERS = REPO_ROOT / "graph_output" / "crosscheck" / "aaa_claim_assessments.json"
RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
ISSUER_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"
DATA_VERSION = REPO_ROOT / "data_version.json"

UNMEASURED = "KHÔNG ĐO ĐƯỢC"


def _load(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _mtime(path: Path) -> str:
    if not path.exists():
        return "missing"
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _corpus_scope(graph: Dict[str, Any], tier1: Dict[str, Any]) -> Dict[str, Any]:
    """Which documents these numbers actually describe.

    Worth stating on the report rather than leaving to the reader's assumption,
    because two document populations sit side by side in `data/labeled/` and only
    one of them is in the graph: the AAA pilot that was extracted, and a
    1,216-document sector sweep that was classified and then stopped. Averaging
    them would describe a graph that does not exist.

    News-article counts are given at three stages because they disagree, and the
    disagreement is real: articles labeled -> articles extracted into per-page
    graphs -> articles still carrying a source_doc after entity resolution.
    """
    doc_dirs = sorted(p.name for p in (REPO_ROOT / "graph_output" / "graphs").iterdir()
                      if p.is_dir()) if (REPO_ROOT / "graph_output" / "graphs").exists() else []
    # News documents are named <TICKER>__<domain>__<hash>; reports are not.
    news_dirs = [d for d in doc_dirs if "__" in d]
    report_dirs = [d for d in doc_dirs if "__" not in d]

    nodes = graph.get("nodes", [])
    news_nodes = sum(1 for n in nodes
                     if (n.get("properties") or {}).get("source_type") == "news")

    per_file = (tier1.get("stage_1_ingestion", {}).get("esg_snr", {}) or {}).get("per_file", {})
    pilot_esg = sum(v["esg_true"] for v in per_file.values() if v["scope"] == "in_graph")
    sweep_esg = sum(v["esg_true"] for v in per_file.values() if v["scope"] == "sector_sweep")

    return {
        "graph_doc_dirs": len(doc_dirs),
        "report_dirs": len(report_dirs),
        "news_dirs": len(news_dirs),
        "report_years": sorted(d.rsplit("_", 1)[-1] for d in report_dirs),
        "pilot_esg_true_sentences": pilot_esg,
        "sector_sweep_esg_true_sentences": sweep_esg,
        "news_nodes": news_nodes,
        "news_node_pct": round(100 * news_nodes / len(nodes), 1) if nodes else None,
    }


def evaluate_expert_tier() -> Dict[str, Any]:
    """IAA + Likert rubric — only if the ratings describe THIS corpus.

    The check is deliberately cheap and specific: every rated dossier id must
    match a claim in the real dossier file. Synthetic demo rows fail it, and they
    are exactly what produced the discredited agreement coefficient. The IAA
    engine itself is untouched and correct; it was fed the wrong input.
    """
    annotations = _load(ANNOTATIONS) or []
    dossiers = _load(DOSSIERS) or []
    real_ids = {str(d.get("claim_id")) for d in dossiers}
    real_texts = {(d.get("claim_text") or "").strip().lower() for d in dossiers}

    matched = [a for a in annotations
               if str(a.get("dossier_id")) in real_ids
               or (a.get("claim_text") or "").strip().lower() in real_texts]

    if len(matched) < 2:
        return {
            "measured": False,
            "reason": (f"Chỉ {len(matched)}/{len(annotations)} dòng đánh giá ứng với một hồ sơ "
                       f"có thật trong corpus này. File đang có là bản mẫu dựng sẵn (claim của "
                       f"Vinamilk, dossier_id kiểu 'claim_vnm_2023_001') — không tồn tại trong "
                       f"bất kỳ hồ sơ nào ở đây. Hệ số đồng thuận tính trên đó không mô tả gì "
                       f"về hệ thống này."),
            "annotations_found": len(annotations),
            "annotations_matching_corpus": len(matched),
            "requirement": ("≥ 3 người chấm độc lập trên ≥ 30 hồ sơ thật, chấm trực tiếp trên "
                            "giao diện ESG Evidence View và không trao đổi trước với nhau"),
            "engine_ready": True,
        }

    likert_items: List[Dict[str, int]] = []
    for ann in matched:
        row = {}
        for rater, data in (ann.get("ratings") or {}).items():
            if isinstance(data, dict):
                scores = [v for k, v in data.items()
                          if k != "label" and isinstance(v, (int, float))]
                if scores:
                    row[rater] = int(round(sum(scores) / len(scores)))
        if row:
            likert_items.append(row)

    flat = [{"annotator_role": r, "ratings": d}
            for ann in matched for r, d in (ann.get("ratings") or {}).items()
            if isinstance(d, dict)]

    return {
        "measured": True,
        "krippendorff_alpha_ordinal": round(IAAEngine.krippendorff_alpha_ordinal(likert_items), 4),
        "gwet_ac2_ordinal": round(IAAEngine.gwet_ac1_ac2(
            likert_items, categories=[1, 2, 3, 4, 5], ordinal_weights=True), 4),
        "n_dossiers_rated": len(matched),
        "rubric": LikertRubricEvaluator().aggregate_expert_scores(flat),
    }


def run_full_evaluation() -> Dict[str, Any]:
    print("=" * 70)
    print(" ESG Graph-RAG — evaluation over artifacts on disk (offline, no LLM)")
    print("=" * 70)

    graph = _load(RESOLVED) or {}
    print("[1/4] Tier 1 — pipeline control metrics ...")
    tier1 = PipelineEvaluator().run_all()
    print("[2/4] Label-free cross-check metrics ...")
    tier2 = LabelFreeEvaluator().run_all()
    print("[3/4] A — round-trip grounding ...")
    grounding = GroundingEvaluator().run()
    print("[4/4] Expert rating tier ...")
    tier3 = evaluate_expert_tier()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "framework_reference": "evalu.pdf §1-§3 (metric table + Likert rubric)",
        "scope": {
            "resolved_graph": {
                "path": "graph_output/resolved/resolved_graph.json",
                "mtime_utc": _mtime(RESOLVED),
                "nodes": len(graph.get("nodes", [])),
                "edges": len(graph.get("edges", [])),
            },
            "dossiers": {
                "path": "graph_output/crosscheck/aaa_claim_assessments.json",
                "mtime_utc": _mtime(DOSSIERS),
                "claims": len(_load(DOSSIERS) or []),
            },
            "issuers_in_corpus": sorted((_load(ISSUER_REGISTRY) or {}).keys()),
            "corpus": _corpus_scope(graph, tier1),
            "data_snapshot": _load(DATA_VERSION) or {},
        },
        "tier_1_pipeline_controls": tier1,
        "tier_1b_grounding": grounding,
        "tier_2_labelfree_crosscheck": tier2,
        "tier_3_expert_ratings": tier3,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"  wrote {REPORT_JSON}")

    with open(REPORT_MD, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(payload))
    print(f"  wrote {REPORT_MD}")

    # .docx is a convenience for handing the report to a reader, not a second
    # source of truth: export_docx converts the Markdown just written, so the two
    # files cannot disagree. python-docx is optional (repo convention for
    # unlisted deps), so a bare clone still produces the .md and .json and simply
    # says why the Word file is missing.
    try:
        from export_docx import export

        print(f"  wrote {export(REPORT_MD, REPORT_DOCX)}")
    except ImportError:
        print("  (bo qua .docx — chua cai python-docx: pip install python-docx)")

    measured = sum(1 for stage in tier1.values() for m in stage.values() if m["measured"])
    total = sum(len(stage) for stage in tier1.values())
    print(f"\nTier 1: {measured}/{total} metrics measured.")
    return payload


def _fmt_score(m: Dict[str, Any]) -> str:
    if not m.get("measured"):
        return f"**{UNMEASURED}**"
    s = m.get("score")
    if s is None:
        return "—"
    return f"**{s:.4f}** ({s * 100:.1f}%)"


def _fmt_frac(m: Dict[str, Any]) -> str:
    n, d = m.get("numerator"), m.get("denominator")
    if n is None or d is None:
        return "—"
    return f"{n:,} / {d:,}"


def render_markdown(data: Dict[str, Any]) -> str:
    t1 = data["tier_1_pipeline_controls"]
    t2 = data["tier_2_labelfree_crosscheck"]
    t3 = data["tier_3_expert_ratings"]
    scope = data["scope"]

    md: List[str] = []
    md.append("# Báo cáo đánh giá hệ thống Graph-RAG phát hiện greenwashing")
    md.append(f"\n*Tạo lúc {data['generated_at']} · khung tham chiếu: {data['framework_reference']}*")
    md.append("\n> **Nguyên tắc của báo cáo này:** mọi con số đều đọc từ artifact trên đĩa. "
              "Metric không đo được thì ghi thẳng là "
              f"**{UNMEASURED}** kèm lý do và chi phí để đo — không có giá trị mặc định, "
              "không có số benchmark thay thế.")

    md.append("\n## 0. Phạm vi dữ liệu được đánh giá\n")
    md.append("| Artifact | Giá trị |")
    md.append("|---|---|")
    md.append(f"| Đồ thị đã resolve | {scope['resolved_graph']['nodes']:,} node · "
              f"{scope['resolved_graph']['edges']:,} cạnh |")
    md.append(f"| Sửa đổi lần cuối | `{scope['resolved_graph']['mtime_utc']}` |")
    md.append(f"| Hồ sơ claim (dossier) | {scope['dossiers']['claims']:,} |")
    md.append(f"| Doanh nghiệp trong corpus | {', '.join(scope['issuers_in_corpus'])} "
              f"({len(scope['issuers_in_corpus'])} tổ chức duy nhất) |")
    c = scope.get("corpus") or {}
    if c:
        md.append(f"| Tài liệu đã trích xuất thành đồ thị | **{c['graph_doc_dirs']}** = "
                  f"{c['report_dirs']} báo cáo thường niên + {c['news_dirs']} bài báo |")
        md.append(f"| Năm của các báo cáo | {', '.join(c['report_years'])} |")
        md.append(f"| Câu `esg=true` của pilot AAA | {c['pilot_esg_true_sentences']:,} |")
        md.append(f"| Tỷ trọng node đến từ tin tức | **{c['news_node_pct']}%** "
                  f"({c['news_nodes']:,}/{scope['resolved_graph']['nodes']:,}) |")
        md.append(f"| Corpus quét ngành — đã phân loại, **CHƯA** vào đồ thị | "
                  f"{c['sector_sweep_esg_true_sentences']:,} câu `esg=true` "
                  "(1.216 tài liệu) |")
    ds = scope.get("data_snapshot") or {}
    if ds.get("revision"):
        md.append(f"| Snapshot dữ liệu | `{ds.get('repo_id')}` @ "
                  f"`{str(ds['revision'])[:12]}` (đẩy {ds.get('pushed_at')}) |")

    md.append(f"\n> **Toàn bộ báo cáo này mô tả MỘT doanh nghiệp** — "
              f"{', '.join(scope['issuers_in_corpus'])}. Mọi con số bên dưới là của pilot đó, "
              "không phải của toàn ngành. Corpus quét ngành 1.216 tài liệu đã được phân loại "
              "ESG nhưng chưa từng chạy qua bước trích xuất đồ thị, nên không đóng góp node "
              "nào và không nằm trong bất kỳ mẫu số nào ngoài dòng SNR được ghi rõ là "
              "\"quét ngành\".")

    # ---- Tier 1 ----
    md.append("\n---\n## 1. Tầng 1 — 11 chỉ số kiểm soát pipeline (evalu.pdf §1–§5)\n")
    stage_titles = {
        "stage_1_ingestion": "Giai đoạn 1 — Thu thập & phân loại ESG",
        "stage_2_extraction": "Giai đoạn 2 — Trích xuất triplet & KPI",
        "stage_3_entity_resolution": "Giai đoạn 3 — Hợp nhất thực thể",
        "stage_4_indicator_axis": "Giai đoạn 4 — Trục chỉ tiêu TT96/GRI",
        "stage_5_crosscheck": "Giai đoạn 5 — Đối soát chéo claim ↔ conduct",
    }
    for stage_key, metrics in t1.items():
        md.append(f"\n### {stage_titles.get(stage_key, stage_key)}\n")
        md.append("| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |")
        md.append("|---|---|---|---|")
        for m in metrics.values():
            md.append(f"| {m['metric']} | {_fmt_score(m)} | {_fmt_frac(m)} | `{m['source']}` |")
        for m in metrics.values():
            if not m.get("measured"):
                md.append(f"\n> **{m['metric']} — {UNMEASURED}.** {m.get('reason', '')}")
            elif m.get("note"):
                md.append(f"\n- *{m['metric']}*: {m['note']}")

    # Detail blocks worth surfacing rather than leaving in the JSON.
    snr = t1["stage_1_ingestion"]["esg_snr"]
    if snr.get("measured"):
        md.append("\n#### Chi tiết SNR — chỉ số nhạy với định nghĩa \"có căn cứ\"\n")
        md.append("| Định nghĩa | SNR |")
        md.append("|---|---|")
        md.append(f"| Chặt: có số **kèm đơn vị đo** hoặc thuật ngữ TT96/GRI | "
                  f"**{snr['score']:.4f}** ({snr['numerator']:,}/{snr['denominator']:,}) |")
        sens = snr.get("sensitivity_any_number") or {}
        if sens.get("snr") is not None:
            md.append(f"| Lỏng: có **bất kỳ chữ số nào** (cận trên) | "
                      f"{sens['snr']:.4f} ({sens['grounded']:,}/{sens['esg_true']:,}) |")
        sector = snr.get("sector_sweep_scope") or {}
        if sector.get("snr") is not None:
            md.append(f"| Corpus quét ngành (đã phân loại, **chưa** vào đồ thị) | "
                      f"{sector['snr']:.4f} ({sector['grounded']:,}/{sector['esg_true']:,}) |")
        md.append(f"\nKho thuật ngữ dùng để đối chiếu: {snr.get('lexicon_size', 0)} mục "
                  "(35 KPI TT96/QĐ2171/QCVN09/SSC-IFC + 136 mã GRI).")

    align = t1["stage_4_indicator_axis"]["indicator_alignment_coverage"]
    if align.get("measured"):
        md.append("\n#### Chi tiết độ phủ trục chỉ tiêu\n")
        md.append("| Lớp node | Đã gắn chỉ tiêu | Tổng | Tỷ lệ |")
        md.append("|---|---|---|---|")
        for cls, b in sorted(align.get("per_class", {}).items()):
            md.append(f"| {cls} | {b['aligned']:,} | {b['total']:,} | {b['pct']}% |")
        kpi = align.get("kpi_measured_under") or {}
        if kpi.get("total"):
            md.append(f"| KPIObservation (`measuredUnder`) | {kpi['aligned']:,} | "
                      f"{kpi['total']:,} | {kpi['pct']}% |")
        md.append(f"\nPhân bố phương pháp gắn: `{align.get('method_mix')}`")

    # ---- Tier 2 ----
    # ---- A: grounding ----
    a = data.get("tier_1b_grounding") or {}
    md.append("\n---\n## 2. Độ đúng trích xuất — round-trip grounding (A)\n")
    if a.get("measured"):
        md.append(f"### **{a['score']:.4f}** ({a['score'] * 100:.1f}%) — "
                  f"{a['numerator']:,}/{a['denominator']:,} giá trị KPI có mặt đúng trên trang "
                  "mà chính node đó trích dẫn\n")
        md.append("> **Đây là chỉ số ĐỘ ĐÚNG thật, không phải proxy.** Văn bản gốc chính là "
                  "ground truth cho câu hỏi \"con số này có trong tài liệu không?\", nên không "
                  "cần ai gán nhãn. Nó lấp đúng lỗ hổng mà `quality.py` tự ghi nhận ở `q1_accuracy`: "
                  "*\"manual 30–50 node sample audit is out of scope\"* — ở đây là "
                  f"{a['denominator']:,} node, tự động.\n")
        md.append(f"- **{a['mismatches']:,} giá trị KHÔNG tìm thấy** trên trang được trích dẫn "
                  "→ đây là danh sách cần soi tay.")
        sk = a.get("skipped") or {}
        md.append(f"- Không so được (đã loại khỏi mẫu số, không tính là đạt): `{sk}`")
        md.append(f"- Tổng node KPIObservation: {a.get('kpi_nodes_total', 0):,}")
        if a.get("worst_documents"):
            md.append("\n| Tài liệu nhiều sai lệch nhất | Khớp | Lệch |")
            md.append("|---|---|---|")
            for w in a["worst_documents"]:
                md.append(f"| {w['doc']} | {w['ok']} | **{w['miss']}** |")
        if a.get("mismatch_examples"):
            md.append("\nVí dụ giá trị không tìm thấy trên trang trích dẫn:\n")
            for ex in a["mismatch_examples"][:5]:
                md.append(f"- `{ex.get('title')}` = **{ex.get('value')}** {ex.get('unit') or ''} "
                          f"→ trích dẫn {ex.get('cited')}")
        md.append(f"\n> ⚠ {a['caveat']}")
    else:
        md.append(f"**{UNMEASURED}.** {a.get('reason', '')}")

    md.append("\n---\n## 3. Tầng 3 — đánh giá không cần nhãn ở tầng đối soát\n")
    md.append("*(theo `docs/proposals/EVALUATION_WITHOUT_LABELS.md`; toàn bộ offline, 0 đồng)*\n")

    b2 = t2["b2_permutation_test"]
    if b2.get("measured"):
        md.append("### B2 — Kiểm định hoán vị trên số claim bị mâu thuẫn\n")
        md.append(f"- Quan sát thực tế: **{b2['observed']}** claim `appears_contradicted` "
                  f"từ {b2['n_contradicting_items']} mẩu bằng chứng mâu thuẫn.")
        md.append(f"- Phân phối null ({b2['n_permutations']} lần hoán vị, seed `{b2['seed']}`): "
                  f"trung bình {b2['null_mean']}, khoảng [{b2['null_min']}, {b2['null_max']}].")
        md.append(f"- **p = {b2['p_value']}** (đuôi dưới).")
        md.append(f"\n> {b2['note']}")

    b2b = t2["b2b_pairing_coherence"]
    if b2b.get("measured"):
        lex, yr = b2b["lexical_overlap"], b2b.get("year_distance")
        md.append("\n### B2b — Cặp (claim, bằng chứng) được giữ có mạch lạc hơn ghép ngẫu nhiên không?\n")
        md.append("| Thống kê | Quan sát | Null (ngẫu nhiên) | p |")
        md.append("|---|---|---|---|")
        md.append(f"| Chồng lấp từ vựng (Jaccard) | **{lex['observed']}** | {lex['null_mean']} | "
                  f"**{lex['p_value']}** |")
        if yr:
            md.append(f"| Khoảng cách năm trung bình | {yr['observed_years']} năm | "
                      f"{yr['null_mean_years']} năm | {yr['p_value']} |")
        md.append(f"\n> ⚠ {b2b['caveat']}")
        if yr and yr["p_value"] > 0.05:
            md.append(f"\n> **Kết quả âm cần ghi nhận:** bằng chứng được giữ **không** gần claim "
                      f"về mặt thời gian hơn mức ngẫu nhiên (p = {yr['p_value']}). Chiều thời "
                      f"gian hiện không đóng góp gì cho việc ghép cặp — chỉ có chiều từ vựng.")

    an = t2.get("d_anachronism") or {}
    if an.get("measured"):
        sup, con = an["by_role"]["supports"], an["by_role"]["contradicts"]
        md.append("\n### D — Bằng chứng đi SAU claim (kiểm nguyên tắc P8)\n")
        md.append("| Vai trò bằng chứng | Vi phạm | So sánh được | Tỷ lệ |")
        md.append("|---|---|---|---|")
        md.append(f"| `contradicts` (vi phạm P8 trực tiếp) | **{con['violations']}** | "
                  f"{con['comparable']} | **{con['rate'] * 100:.1f}%** |")
        md.append(f"| `supports` (nhẹ hơn, xem ghi chú) | {sup['violations']} | "
                  f"{sup['comparable']} | {sup['rate'] * 100:.1f}% |")
        md.append(f"\n- Khoảng cách lớn nhất: **+{an['max_gap_years']} năm**.")
        md.append(f"- Phân bố (năm bằng chứng − năm claim): `{an['gap_distribution']}`")
        if an.get("worst_contradictions"):
            md.append("\nCác mâu thuẫn lệch thời gian nặng nhất:\n")
            for w in an["worst_contradictions"][:3]:
                md.append(f"- **+{w['gap_years']} năm** — claim {w['claim_year']} bị bác bỏ bằng "
                          f"bằng chứng {w['evidence_year']}: \"{w['claim_text']}\"")
        md.append(f"\n> {an['note']}")
        md.append(f"\n> ⚠ {an['caveat']}")
        md.append("\n> **Vì sao kết luận này vững:** ba đường độc lập cùng chỉ về một chỗ — "
                  "(1) B2b cho thấy khoảng cách năm của cặp được giữ không tốt hơn ghép ngẫu "
                  "nhiên, (2) D cho thấy phần lớn mâu thuẫn dùng bằng chứng đi sau, (3) tham số "
                  "`window_after` đang để 50 năm. `docs/proposals/EVALUATION_WITHOUT_LABELS.md` §3.3 đã "
                  "**dự báo trước** MR-4 sẽ hỏng nặng; D xác nhận dự báo đó mà không tốn một "
                  "lệnh gọi LLM nào.")

    ab = t2.get("e_time_window_ablation") or {}
    if ab.get("measured"):
        md.append("\n### E — Ablation cửa sổ thời gian truy hồi\n")
        md.append("| `window_after` | supports | contradicts | Tổng bằng chứng | Claim còn bằng chứng |")
        md.append("|---|---|---|---|---|")
        for r in ab["rows"]:
            mark = " ← **hiện tại**" if r["is_live_setting"] else ""
            md.append(f"| {r['window_after']} năm{mark} | {r['kept_supports']} | "
                      f"{r['kept_contradicts']} | {r['kept_total']} | {r['claims_with_evidence']} |")
        md.append(f"\n> {ab['note']}")
        md.append(f"\n> ⚠ {ab['caveat']}")

    dup = t2["duplicate_claim_consistency"]
    if dup.get("measured"):
        md.append("\n### Tính nhất quán trên claim trùng lặp\n")
        md.append(f"- **{dup['score']:.4f}** — {dup['numerator']}/{dup['denominator']} nhóm claim "
                  f"trùng lặp cho cùng một kết luận.")
        md.append(f"- Khoảng tin cậy Wilson 95%: `{dup['wilson_95ci']}` "
                  "(mẫu nhỏ — đọc theo khoảng, không đọc theo tỷ lệ trần).")
        for ex in dup.get("inconsistent_examples", []):
            md.append(f"- ❗ Bất nhất: \"{ex['claim_text']}\" → `{'` vs `'.join(ex['verdicts'])}` "
                      f"(năm {ex['years']}).")

    y = t2["retrieval_yield"]
    if y.get("measured"):
        md.append("\n### Hiệu suất tầng truy hồi (thay cho \"Context Precision@k\")\n")
        md.append(f"- **{y['score']:.4f}** — giữ lại {y['numerator']:,}/{y['denominator']:,} "
                  f"cặp ứng viên.")
        md.append(f"- Phân rã: `{y['by_bucket']}`")
        md.append(f"- {y['claims_with_any_evidence']:,}/{y['total_claims']:,} claim có ít nhất "
                  "một mẩu bằng chứng.")
        md.append(f"\n> ⚠ {y['caveat']}")

    dis = t2["internal_score_disagreement"]
    if dis.get("measured"):
        md.append(f"\n### Bất đồng nội bộ giữa điểm offline và phán quyết LLM\n")
        md.append(f"- **{dis['score']:.4f}** — {dis['numerator']}/{dis['denominator']} hồ sơ.")

    conf = t2["confidence_spectrum"]
    md.append("\n### Phổ `confidence` của LLM (ghi nhận, không phải điểm số)\n")
    md.append(f"- Phân bố: `{conf.get('distribution')}` → chỉ **{conf.get('distinct_values')}** "
              f"giá trị phân biệt, thấp nhất {conf.get('minimum')}.")
    md.append(f"- {conf.get('note')}")

    # ---- Not computable ----
    md.append(f"\n---\n## 3. Những gì {UNMEASURED} — và cần gì để đo\n")
    md.append("| Chỉ số | Vì sao chưa đo được | Chi phí để đo |")
    md.append("|---|---|---|")
    for item in t2["not_computable"].values():
        md.append(f"| {item['metric']} | {item['reason']} | {item['cost_to_obtain']} |")
    for stage in t1.values():
        for m in stage.values():
            if not m.get("measured"):
                md.append(f"| {m['metric']} | {m.get('reason', '')} | "
                          "chạy lại step03 phase 2 (có tính phí) |")
    b3 = t2["b3_structural_negative_control"]
    md.append(f"| {b3['metric']} | {b3['reason']} | {b3['becomes_measurable_when']} |")

    # ---- Tier 3 ----
    md.append("\n---\n## 4. Tầng chuyên gia (rubric Likert 5 điểm + IAA)\n")
    if t3.get("measured"):
        md.append(f"- Krippendorff α (ordinal): **{t3['krippendorff_alpha_ordinal']}**")
        md.append(f"- Gwet AC2 (ordinal): **{t3['gwet_ac2_ordinal']}**")
        md.append(f"- Số hồ sơ được chấm: {t3['n_dossiers_rated']}")
    else:
        md.append(f"**{UNMEASURED}.** {t3['reason']}\n")
        md.append(f"- Số dòng đánh giá tìm thấy: {t3['annotations_found']}")
        md.append(f"- Số dòng khớp với hồ sơ thật trong corpus: **{t3['annotations_matching_corpus']}**")
        md.append(f"- Điều kiện để đo: {t3['requirement']}")
        md.append("- Bộ máy tính α / AC2 (`evalu_iaa_engine.py`) đã sẵn sàng; "
                  "cái còn thiếu là dữ liệu chấm thật, không phải code.")

    md.append("\n---")
    md.append("*Sinh tự động bởi `evalu/run_evaluation.py`. "
              "Ràng buộc được kiểm bởi `test/test_evalu_metrics.py`.*")
    return "\n".join(md)


if __name__ == "__main__":
    run_full_evaluation()
