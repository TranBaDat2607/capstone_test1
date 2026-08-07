"""Render an evaluation run as JSON + Markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evalu.model import MetricResult


def _fmt(value: Optional[float], as_pct: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%" if as_pct else f"{value:.4f}"


def _status(m: MetricResult) -> str:
    if m.passed is True:
        return "PASS"
    if m.passed is False:
        return "FAIL"
    return "info"


def build_payload(metrics: Sequence[MetricResult],
                  context: Dict[str, Any],
                  rubric: Optional[Dict[str, Any]] = None,
                  expert: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "schema": "evalu.report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "framework": "Khung Đánh giá Toàn diện cho Hệ thống Graph-RAG "
                     "Phát hiện Greenwashing Không Nhãn",
        "context": context,
        "component_metrics": [m.to_dict() for m in metrics],
        "expert_rubric": rubric,
        "expert_evaluation": expert,
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    ctx = payload.get("context", {})
    metrics = payload.get("component_metrics", [])

    out: List[str] = []
    out.append("# Báo cáo Đánh giá Hệ thống Graph-RAG (không nhãn)")
    out.append("")
    out.append(f"*Sinh tự động lúc {payload['generated_at']} — "
               f"`python evalu/run_evaluation.py`*")
    out.append("")
    out.append("> Hệ thống là **Decision-Support System**, không phải bộ phân loại "
               "greenwashing. Không tồn tại nhãn chuẩn, nên mọi con số dưới đây là "
               "**chỉ số nội bộ (intrinsic)** đo tính nhất quán của pipeline — "
               "KHÔNG phải accuracy so với sự thật.")
    out.append("")

    # ---- context -----------------------------------------------------------
    out.append("## 0. Phạm vi dữ liệu đo")
    out.append("")
    out.append("| Hạng mục | Giá trị |")
    out.append("|---|---|")
    for k, v in ctx.items():
        out.append(f"| {k} | {v} |")
    out.append("")

    # ---- summary -----------------------------------------------------------
    out.append("## 1. Tổng hợp chỉ số nội bộ theo module (§2)")
    out.append("")
    out.append("| Mã | Chỉ số | Giá trị | Tử/Mẫu | Trạng thái |")
    out.append("|---|---|---:|---:|:--:|")
    for m in metrics:
        num, den = m.get("numerator"), m.get("denominator")
        frac = "—" if den in (None, 0) else f"{num:,.0f} / {den:,.0f}"
        out.append(f"| {m['metric_id']} | {m['name']} | {m['pct'] or '—'} | {frac} | "
                   f"{_status_from_dict(m)} |")
    out.append("")

    # ---- per-module detail -------------------------------------------------
    out.append("## 2. Chi tiết từng module")
    out.append("")
    current = None
    for m in metrics:
        if m["module"] != current:
            current = m["module"]
            out.append(f"### {current}")
            out.append("")
        out.append(f"**{m['metric_id']} — {m['name']}**  ")
        out.append(f"Giá trị: **{m['pct'] or '—'}**"
                   + (f" ({m['numerator']:,.0f}/{m['denominator']:,.0f})"
                      if m.get("denominator") else "")
                   + (f" · Mục tiêu: {m['target']}" if m.get("target") else ""))
        out.append("")
        if m.get("purpose"):
            out.append(f"*Chỉ số này dùng để làm gì:* {m['purpose']}")
            out.append("")
        if m.get("how_to_read"):
            out.append(f"*Cách đọc:* {m['how_to_read']}")
            out.append("")
        if m.get("limitation"):
            out.append(f"*Hạn chế:* {m['limitation']}")
            out.append("")
        for line in _detail_lines(m):
            out.append(line)
        out.append("")

    # ---- expert layer ------------------------------------------------------
    out.append("## 3. Tầng đánh giá chuyên gia (§3) và độ đồng thuận (§4)")
    out.append("")
    expert = payload.get("expert_evaluation")
    rubric = payload.get("expert_rubric")
    if expert:
        out.append(f"- Số phiếu: **{expert['n_ballots']}** từ **{expert['n_raters']}** "
                   f"chuyên gia trên **{expert['n_claims']}** hồ sơ")
        out.append(f"- Hàng đợi phân giải mâu thuẫn: **{expert['review_queue_size']}** mục")
        out.append("")
        out.append("| Khía cạnh | Gwet AC2 | Krippendorff α | Mức (Landis & Koch) | ≥ 0.61 |")
        out.append("|---|---:|---:|---|:--:|")
        for dim, blob in expert["per_dimension"].items():
            ag = blob.get("agreement")
            if not ag:
                out.append(f"| {dim} | — | — | — | — |")
                continue
            out.append(f"| {dim} | {_fmt(ag['gwet_ac2'], False)} | "
                       f"{_fmt(ag['krippendorff_alpha'], False)} | "
                       f"{ag['headline_label'] or '—'} | "
                       f"{'✔' if ag['meets_substantial_threshold'] else '✘'} |")
    else:
        out.append("**Chưa thu thập phiếu chấm nào.** Bộ công cụ đã sẵn sàng: "
                   "`evalu/rubric.py` chứa rubric 4 khía cạnh × thang Likert 5 điểm, "
                   "3 nhóm hội đồng, bộ sinh phiếu trống và pipeline đồng thuận "
                   "(Gwet AC2 / Krippendorff α, ngưỡng 0.61).")
        out.append("")
        out.append("Sinh phiếu trống:")
        out.append("")
        out.append("```bash")
        out.append("python evalu/run_evaluation.py --make-sheet "
                   "--rater-id ceo01 --panel ceo --n-claims 30")
        out.append("```")
    out.append("")
    if rubric:
        out.append(f"Hệ số chính: **{rubric['iaa']['headline']}** — {rubric['iaa']['why']}")
        out.append("")

    out.append("## 4. Giới hạn cần nêu khi trích dẫn báo cáo này")
    out.append("")
    out.append("- Không có ground truth ⇒ không có precision/recall/F1 về greenwashing.")
    out.append("- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, không đo **tính đúng**.")
    out.append("- Tỷ lệ abstention cao phản ánh kho tin tức độc lập còn mỏng, "
               "không phải lỗi thuật toán.")
    out.append("- M1.1 (SNR) đo mức độ *neo được vào từ vựng KPI/GRI*, "
               "không phải độ chính xác của bộ phân loại ESG.")
    out.append("")
    return "\n".join(out)


def _status_from_dict(m: Dict[str, Any]) -> str:
    if m.get("passed") is True:
        return "PASS"
    if m.get("passed") is False:
        return "FAIL"
    return "info"


def _detail_lines(m: Dict[str, Any]) -> List[str]:
    d = m.get("details") or {}
    lines: List[str] = []
    if d.get("by_reason"):
        lines.append("Phân loại vi phạm: "
                     + ", ".join(f"`{k}` = {v:,}" for k, v in d["by_reason"].items()))
    if d.get("by_assessment"):
        lines.append("Phân bố kết luận: "
                     + ", ".join(f"`{k}` = {v:,}" for k, v in d["by_assessment"].items()))
    if d.get("by_class"):
        lines.append("Theo lớp: "
                     + ", ".join(f"`{k}` {v['aligned']:,}/{v['total']:,}"
                                 for k, v in d["by_class"].items()))
    if d.get("missing_by_field"):
        lines.append("Thiếu trường: "
                     + ", ".join(f"`{k}` = {v:,}" for k, v in d["missing_by_field"].items()))
    if d.get("edges_total") is not None:
        lines.append(f"Cạnh: {d['edges_complete']:,}/{d['edges_total']:,} · "
                     f"Node T2/T3: {d['nodes_complete']:,}/{d['nodes_total']:,}")
    if d.get("edge_gaps_by_predicate"):
        lines.append("Cạnh thiếu thời gian, theo predicate: "
                     + ", ".join(f"`{k}` = {v:,}"
                                 for k, v in d["edge_gaps_by_predicate"].items()))
    if d.get("node_gaps_by_class"):
        lines.append("Node thiếu `valid_from`, theo lớp: "
                     + ", ".join(f"`{k}` = {v:,}"
                                 for k, v in d["node_gaps_by_class"].items()))
    if d.get("clusters"):
        top = d["clusters"][:5]
        lines.append("Cụm trùng lớn nhất: "
                     + ", ".join(f"`{c['class']}`×{c['size']}" for c in top))
    if d.get("top_domains"):
        lines.append("Tên miền bị loại nhiều nhất: "
                     + ", ".join(f"`{dom}` = {n}" for dom, n in d["top_domains"][:5]))
    if d.get("guarded_fields_seen"):
        lines.append(f"Số trường được canh giữ thực tế: {d['guarded_fields_seen']:,} "
                     f"(trên các trường {', '.join('`' + f + '`' for f in d.get('guarded_field_names', []))}) "
                     "— mẫu số chỉ tính node thực sự mang giá trị đo, "
                     "nên 100% ở đây không phải kết quả rỗng")
    if d.get("match_stats"):
        s = d["match_stats"]
        lines.append(f"Ghép node trước/sau sửa: {s['matched']:,} khớp · "
                     f"{s['only_before']:,} chỉ có trước · {s['only_after']:,} chỉ có sau")
    if d.get("note"):
        lines.append(f"*{d['note']}*")
    return lines


def write(payload: Dict[str, Any], out_dir: Path, label: str = "latest") -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"evaluation_report_{label}.json"
    md_path = out_dir / f"evaluation_report_{label}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
