"""
metric_spec.py — the formal side of the evaluation: what each metric IS.

`metrics.py` computes the numbers and carries the reader-facing prose
(purpose / how_to_read / limitation). What it does not carry is the thing a
reviewer asks for first: **the definition**. A percentage whose numerator and
denominator are not written down cannot be checked, cannot be reproduced, and
cannot be defended — so this module states, per metric, four things:

    what        one-sentence definition
    formula     the equation, in set notation over named symbols (§ SYMBOLS)
    built_from  which artifact on disk, and the procedure applied to it
    why         the motivation — what goes wrong if it is not measured

`render_focused()` assembles those into an Evaluation section shaped the way a
paper's is: setup, definitions, results, the hypothesis test, threats to
validity. The NUMBERS are never written here — they are read out of the report
payload, so this module and `evaluation_report_<label>.json` cannot disagree
about a value. A metric with no entry raises `KeyError` rather than rendering a
bare percentage, which is the failure this file exists to prevent
(`test/test_evalu_run_report.py` group [7]).

Offline, pure: no I/O, no artifacts, no network.
"""

from __future__ import annotations

from typing import Any, Dict, List

SYMBOLS = [
    ("S_r, S_n", "tập câu đã gán nhãn của kênh báo cáo / kênh tin tức"),
    ("esg(s)", "cờ nhị phân do ViDeBERTa-v3-ESG gán cho câu s"),
    ("L", "từ vựng ESG có kiểm soát (TT96 / QĐ2171 / QCVN09 / GRI), đã fold dấu"),
    ("G = (V, E)", "đồ thị đã phân giải, `graph_output/resolved/resolved_graph.json`"),
    ("V_T1", "node thực thể bền vững (Organization, Facility, …) — danh tính vô thời gian"),
    ("V_T2∪T3", "node sự kiện/quan sát (KPIObservation, Penalty, MediaReport, …)"),
    ("Σ", "tập bộ ba hợp lệ (predicate, lớp nguồn, lớp đích) khai trong `config/schema.json`"),
    ("τ(e)", "`temporal_metadata` của cạnh e"),
    ("D", "tập hồ sơ đối soát (dossier), một phần tử cho mỗi SustainabilityClaim"),
    ("a(d)", "kết luận tư vấn của hồ sơ d ∈ {appears_supported, appears_contradicted, "
             "unverified_insufficient_evidence}"),
    ("feed(x)", "mã CK mà bằng chứng x được thu thập dưới đó, suy từ tiền tố "
                "`source_doc = <TICKER>__<domain>__<hash>`"),
    ("ticker(d)", "mã CK của doanh nghiệp phát ra tuyên bố trong hồ sơ d"),
]

SPECS: Dict[str, Dict[str, str]] = {
    "M1.1r": {
        "what": "Tỷ lệ câu được classifier nhận là ESG mà còn neo được vào một cụm từ "
                "trong từ vựng chuẩn — phần tín hiệu thực sự dùng được cho khâu sau.",
        "formula": "M1.1 = |{s ∈ S : esg(s) = 1 ∧ ∃t ∈ L, t ⊑ fold(text(s))}| / |{s ∈ S : esg(s) = 1}|",
        "built_from": "`data/labeled/classified/all_sentences_classified.jsonl`, stream một "
                      "lượt. L dựng bởi `evalu/lexicon.py` từ `kpi_definitions_construction.json` "
                      "(35 KPI + cụm con), `config/kpi_type_aliases.json` và "
                      "`config/gri_catalog.json`; so khớp bằng `LexiconMatcher` trên chuỗi đã fold dấu.",
        "why": "Classifier gán nhãn theo ngữ nghĩa câu, nên văn tiếp thị rỗng ('hướng tới "
               "phát triển bền vững') vẫn lọt qua. Chỉ số này tách phần *đo được* khỏi phần "
               "*hứa hẹn*, tức chất lượng đầu vào của khâu trích xuất KPI.",
    },
    "M1.2r": {
        "what": "Tỷ lệ câu giữ nguyên đủ ba toạ độ nguồn qua toàn bộ pipeline.",
        "formula": "M1.2 = |{s ∈ S : source_pdf(s) ≠ ⊥ ∧ page(s) ≠ ⊥ ∧ sentence_index(s) ≠ ⊥}| / |S|",
        "built_from": "Cùng một lượt stream với M1.1. Kiểm `is not None` chứ không kiểm "
                      "truthiness — `page = 0` là một toạ độ thật, không phải khuyết.",
        "why": "Điều kiện tiên quyết của toàn hệ: một thẻ trên giao diện nói 'doanh nghiệp X "
               "mâu thuẫn' mà không chỉ được về đúng trang báo cáo thì không kiểm chứng được, "
               "và không được phép hiển thị.",
    },
    "M2.1": {
        "what": "Phần đồ thị thực sự tham gia được vào suy luận theo thời gian.",
        "formula": "M2.1 = ( |{e ∈ E : {valid_from, valid_to, recorded_at} ⊆ dom(τ(e)) ∧ "
                   "τ(e).valid_from ≠ ⊥}| + |{v ∈ V_T2∪T3 : valid_from(v) ≠ ⊥}| ) / "
                   "( |E| + |V_T2∪T3| )",
        "built_from": "`resolved_graph.json`. Node T1 bị loại khỏi mẫu số theo P2 (danh tính "
                      "vô thời gian). `valid_to = ⊥` được tính là **khoảng mở**, không phải "
                      "khuyết — chỉ kiểm sự *có mặt* của khoá.",
        "why": "Câu hỏi greenwashing luôn mang mốc thời gian ('cam kết 2021 vs hành vi 2023'). "
               "Cạnh không có `valid_from` thì không trả lời được câu hỏi đó. Phạt khoảng mở "
               "sẽ đẩy pipeline đi **bịa ngày kết thúc**, nên định nghĩa cố ý không phạt.",
    },
    "M2.2": {
        "what": "Tỷ lệ cạnh có bộ ba (predicate, lớp nguồn, lớp đích) hợp lệ theo schema.",
        "formula": "M2.2 = |{e ∈ E : (pred(e), cls(src(e)), cls(tgt(e))) ∈ Σ}| / |E|",
        "built_from": "`resolved_graph.json` × `config/schema.json`. Một nhãn cạnh có thể hợp "
                      "lệ với **nhiều** cặp lớp; khớp bất kỳ cặp nào là hợp lệ.",
        "why": "Bắt cạnh sai lớp trước khi chúng đi vào Neo4j và vào truy hồi bằng chứng. "
               "Xem giới hạn tự khai: chỉ số này đo đầu ra của chính validator.",
    },
    "M2.3": {
        "what": "Khâu sửa lỗi bằng LLM được phép chữa HÌNH DẠNG bộ ba, nhưng không được đụng "
                "vào GIÁ TRỊ ĐO.",
        "formula": "M2.3 = |{v ∈ M : ∀f ∈ F, π_f^trước(v) = π_f^sau(v)}| / |M|,  "
                   "F = {value, unit, amount, quantity, target_value},  "
                   "M = {v : stable_id(v) khớp cả hai phía ∧ ∃f ∈ F xuất hiện ở ít nhất một phía}",
        "built_from": "Phía *trước*: node trong `graph_output/graphs/<doc>/page*.json` (mang "
                      "`stable_id` do step 02 stamp). Phía *sau*: node trong "
                      "`all_validated_triples.json`, tính lại id bằng chính "
                      "`get_stable_entity_id` của pipeline. Ba dạng vi phạm được phân biệt: "
                      "`changed` / `dropped` / `invented`.",
        "why": "Một mô hình được nhắc bằng tiếng Anh rất dễ 'sửa' `tấn` → `tons` hoặc làm tròn "
               "một con số; sai lệch đó đi thẳng vào hồ sơ đối soát mà không ai thấy. Điều kiện "
               "`∃f ∈ F` giữ cho mẫu số không rỗng — 100% trên tập không có trường nào để bảo "
               "vệ là 100% vô nghĩa.",
    },
    "M3.1": {
        "what": "Nguyên tắc P1: không lớp T1 nào được đưa trường thời gian vào `identity_keys`.",
        "formula": "M3.1 = |{c ∈ C_T1 : identity_keys(c) ∩ TimeFields ≠ ∅}| / |C_T1|,  "
                   "TimeFields = {valid_from, valid_to, date, year, validity_period, …}",
        "built_from": "`config/schema.json`. Bản đồ tầng T1/T2/T3 **import từ "
                      "`esg_kg.report.quality`**, không khai lại — bản sao thứ hai sẽ trôi khỏi "
                      "lint mà pipeline đang thật sự dùng.",
        "why": "Nếu danh tính một doanh nghiệp phụ thuộc thời gian thì mỗi năm sinh ra một "
               "node mới, và tuyên bố 2021 không bao giờ nối được với hành vi 2023. Lớp quan "
               "sát (KPIObservation…) thì **được phép** khoá theo thời gian, nên nằm ngoài "
               "phạm vi chứ không phải ngoại lệ.",
    },
    "M3.2": {
        "what": "Tỷ lệ thực thể T1 còn trùng lặp sau khi phân giải (Stage A/B/C/D).",
        "formula": "M3.2 = Σ_{b ∈ B, |b| > 1} (|b| − 1) / |V_T1|,  "
                   "B = phân hoạch V_T1 theo khoá (class, normalize_name(name))",
        "built_from": "`resolved_graph.json`, gom nhóm bằng chính `normalize_name` của "
                      "pipeline. Trùng khác lớp bị bỏ qua có chủ ý (một Facility và một "
                      "Organization được phép trùng tên).",
        "why": "Thực thể bị vỡ làm loãng bằng chứng: tuyên bố treo vào node này, tin tức treo "
               "vào node kia, khâu đối soát không bao giờ nối được hai bên.",
    },
    "M4.1": {
        "what": "Độ phủ của trục chỉ tiêu TT96/GRI trên các node có thể gán chỉ tiêu.",
        "formula": "M4.1 = |{v ∈ V_A : ∃e ∈ E, pred(e) = alignsWithIndicator ∧ src(e) = v}| / |V_A|,  "
                   "V_A = SustainabilityClaim ∪ Goal ∪ Initiative",
        "built_from": "`resolved_graph.json` sau step 05c (tầng từ khoá) và, nếu có chạy, "
                      "step 05d (tầng LLM).",
        "why": "Trục chỉ tiêu là mặt phẳng chung để nối *tuyên bố* với *hành vi*: không có "
               "cạnh này thì một claim không bao giờ gặp được KPI/tin tức cùng chủ đề.",
    },
    "M4.2": {
        "what": "Một lời tự khai 'số lần bị xử phạt: 0' phải được gắn cờ VÀ không được biến "
                "thành bằng chứng conduct.",
        "formula": "M4.2 = |{p ∈ P_0 : self_reported_zero(p) ∧ deg_axis(p) = 0}| / |P_0|,  "
                   "P_0 = {v ∈ V : cls(v) = Penalty ∧ amount(v) = 0},  "
                   "deg_axis = bậc trên cạnh {measuredUnder, alignsWithIndicator}",
        "built_from": "`resolved_graph.json`. 'Cạnh conduct' **chỉ** gồm cạnh trục chỉ tiêu; "
                      "cạnh cấu trúc `Organization -subjectToPenalty-> Penalty` KHÔNG tính — "
                      "nó chỉ ghi nhận doanh nghiệp đã công bố, và mọi Penalty tự khai 0 đều "
                      "hợp lệ khi có nó.",
        "why": "Đây là kiểu sai lầm mà một công cụ chống greenwashing tuyệt đối không được "
               "mắc: khuếch đại lời tự khen thành 'đã được xác minh'.",
    },
    "M5.1": {
        "what": "Tỷ lệ tuyên bố mà hệ thống TỪ CHỐI kết luận vì không đủ bằng chứng độc lập.",
        "formula": "M5.1 = |{d ∈ D : a(d) = unverified_insufficient_evidence}| / |D|",
        "built_from": "`graph_output/crosscheck/*_claim_assessments.json` (đầu ra step 07).",
        "why": "Trong hệ hỗ trợ ra quyết định, **im lặng đúng lúc là một tính năng**: thà "
               "không nói còn hơn quy kết sai cho một doanh nghiệp có thật, nêu đích danh. "
               "Đây là thuộc tính của DỮ LIỆU (kho tin độc lập mỏng), không phải của thuật "
               "toán — và **không được** trình bày như chỉ tiêu cần giảm.",
    },
    "M5.2": {
        "what": "Tỷ lệ bằng chứng-ủng-hộ bị loại vì đến từ chính tên miền của doanh nghiệp.",
        "formula": "M5.2 = |Flagged| / (|Kept| + |Flagged|),  "
                   "Flagged = bằng chứng ủng hộ bị guard tự-xác-minh loại, "
                   "Kept = bằng chứng ủng hộ từ nguồn độc lập được giữ",
        "built_from": "Trường `flagged_non_independent_support` và `supporting_evidence` của "
                      "hồ sơ step 07.",
        "why": "Doanh nghiệp không được tự xác nhận mình. Nếu 'bằng chứng độc lập' hoá ra là "
               "thông cáo trên website của chính họ thì toàn bộ kết luận sụp.",
    },
    "NC.1": {
        "what": "Negative control: khi hệ thống trích một bản tin làm bằng chứng cho tuyên bố "
                "của doanh nghiệp T, bản tin đó có thật sự nói về T không?",
        "formula": "NC.1 = |{(d, x) : feed(x) = ticker(d)}| / |{(d, x) : feed(x) ≠ ⊥}|,  "
                   "x chạy trên supporting_evidence ∪ contradicting_evidence của d",
        "built_from": "Hồ sơ step 07 × `resolved_graph.json` (`node_index` → node) × "
                      "`config/issuer_registry.json` (biến thể tên mỗi issuer). Quy thuộc "
                      "bằng tiền tố `source_doc`; `cross_feed_unmentioned` còn kiểm xem văn "
                      "bản mà LLM **thực sự nhìn thấy** có nhắc tên doanh nghiệp không.",
        "why": "Đây là phép kiểm **CÓ THỂ LÀM HỆ THỐNG TRƯỢT** — khác toàn bộ nhóm M1–M5 vốn "
               "chỉ đối chiếu hệ thống với thiết kế của chính nó, nên không cái nào FAIL một "
               "cách thú vị, nên không cái nào chứng minh được hệ thống *hoạt động*. Nếu bằng "
               "chứng không nói về đúng công ty thì mọi kết luận phía sau vô giá trị, bất kể "
               "LLM lập luận hay đến đâu.",
    },
    "NC.2": {
        "what": "Biến NC.1 thành một phép kiểm giả thuyết có đối chứng: truy hồi có mang tín "
                "hiệu *công ty* hay chỉ đang khớp *chủ đề*?",
        "formula": "H₀: bằng chứng được rút ngẫu nhiên đều từ kho conduct toàn cục.  "
                   "E[same-feed | H₀] = Σ_T (|Pool_T| / |Pool|)·c_T / Σ_T c_T,  "
                   "observed = Σ_T same_T / Σ_T c_T,  lift = observed / E[·| H₀]",
        "built_from": "`Pool_T` = số node conduct (Controversy/Penalty/MediaReport, "
                      "`source_type = news`) thuộc feed của mã T; `c_T` = số trích dẫn hệ "
                      "thống thực sự dùng cho các tuyên bố của T.",
        "why": "NC.1 = 100% tự nó chưa đủ: nếu kho chỉ có tin của một công ty thì bốc ngẫu "
               "nhiên cũng ra 100%. `lift ≈ 1` nghĩa là **không bác bỏ được H₀** — truy hồi "
               "không phân biệt được với bốc ngẫu nhiên; `lift ≥ 2` mới coi là có tín hiệu "
               "thật; `lift < 1` là tệ hơn cả ngẫu nhiên.",
    },
}
# The two ingestion metrics are measured once per channel; the news rows reuse the
# report rows' definition verbatim rather than restating it, so the two can never
# drift into describing different computations.
SPECS["M1.1n"] = dict(SPECS["M1.1r"],
                      built_from=SPECS["M1.1r"]["built_from"].replace(
                          "data/labeled/classified/all_sentences_classified.jsonl",
                          "data/labeled/news_labeled/all_news_sentences_classified.jsonl"))
SPECS["M1.2n"] = dict(SPECS["M1.2r"])

UNMEASURED = "KHÔNG ĐO ĐƯỢC"


def _fmt(m: Dict[str, Any]) -> str:
    if m.get("pct") is None:
        return f"*{UNMEASURED}*"
    num, den = m.get("numerator"), m.get("denominator")
    if den:
        return f"**{m['pct']}** ({num:,.0f} / {den:,.0f})"
    return f"**{m['pct']}**"


def _status(m: Dict[str, Any]) -> str:
    return "PASS" if m.get("passed") else ("FAIL" if m.get("passed") is False else "—")


def render_focused(payload: Dict[str, Any]) -> str:
    """
    The Evaluation section: setup → definitions → results → hypothesis test →
    threats to validity. Every number is read from `payload`; nothing is
    restated here, so this document cannot disagree with the JSON it came from.
    """
    metrics: List[Dict[str, Any]] = payload.get("component_metrics", [])
    ctx = payload.get("context", {})
    by_id = {m["metric_id"]: m for m in metrics}
    for m in metrics:
        if m["metric_id"] not in SPECS:                       # never a bare number
            raise KeyError(f"{m['metric_id']} has no entry in metric_spec.SPECS — "
                           "a metric may not be reported without its definition")

    o: List[str] = []
    o.append("# Đánh giá hệ thống — khung không nhãn (label-free evaluation)")
    o.append("")
    o.append(f"*Số liệu đọc từ `evaluation_report` sinh lúc {payload['generated_at']}.*")
    o.append("")

    o.append("## 1. Vì sao không có precision / recall / F1")
    o.append("")
    o.append("Không tồn tại bộ dữ liệu greenwashing **có nhãn** cho doanh nghiệp niêm yết Việt "
             "Nam. Không có nhãn thì không có ma trận nhầm lẫn, và mọi con số dạng "
             "*accuracy* đều là bịa. Khung này vì thế đo ba thứ **đo được**, theo thứ tự "
             "tăng dần về sức thuyết phục:")
    o.append("")
    o.append("1. **Chỉ số nội bộ (M1–M5)** — hệ thống có làm đúng điều nó tự tuyên bố không: "
             "truy nguyên được, hợp schema, không bịa giá trị, không tự xác minh. Điểm yếu "
             "cố hữu: chúng chỉ đối chiếu hệ thống **với thiết kế của chính nó**, nên không "
             "cái nào có thể FAIL một cách thú vị.")
    o.append("2. **Negative control (NC.1, NC.2)** — phép kiểm **có thể làm hệ thống trượt**, "
             "kèm giả thuyết không và một thống kê (lift) để bác bỏ nó.")
    o.append("3. **Tầng chuyên gia** — rubric Likert 5 điểm + độ đồng thuận (Gwet AC2 / "
             "Krippendorff α). Bộ máy đã sẵn sàng; chưa có phiếu chấm thật nên **không** báo "
             "số nào ở đây.")
    o.append("")
    o.append("> Hệ thống là **Decision-Support System**, không phải bộ phân loại greenwashing. "
             "Đầu ra là hồ sơ bằng chứng + đánh giá tư vấn, không phải phán quyết.")
    o.append("")

    o.append("## 2. Thiết lập thực nghiệm")
    o.append("")
    o.append("| Hạng mục | Giá trị |")
    o.append("|---|---|")
    for k, v in ctx.items():
        o.append(f"| {k} | {v} |")
    o.append("")
    o.append("**Ký hiệu dùng trong các công thức:**")
    o.append("")
    o.append("| Ký hiệu | Nghĩa |")
    o.append("|---|---|")
    for sym, meaning in SYMBOLS:
        o.append(f"| `{sym}` | {meaning} |")
    o.append("")

    o.append("## 3. Kết quả")
    o.append("")
    o.append("| Mã | Chỉ số | Giá trị | Tử / Mẫu | Trạng thái |")
    o.append("|---|---|---:|---:|:--:|")
    for m in metrics:
        num, den = m.get("numerator"), m.get("denominator")
        frac = "—" if not den else f"{num:,.0f} / {den:,.0f}"
        o.append(f"| {m['metric_id']} | {m['name']} | {m['pct'] or UNMEASURED} | {frac} | "
                 f"{_status(m)} |")
    o.append("")

    o.append("## 4. Định nghĩa chỉ số")
    o.append("")
    current = None
    for m in metrics:
        spec = SPECS[m["metric_id"]]
        if m["module"] != current:
            current = m["module"]
            o.append(f"### {current}")
            o.append("")
        o.append(f"#### {m['metric_id']} — {m['name']}")
        o.append("")
        o.append(spec["what"])
        o.append("")
        o.append("```")
        o.append(spec["formula"])
        o.append("```")
        o.append("")
        o.append(f"**Kết quả:** {_fmt(m)}"
                 + (f" · mục tiêu: {m['target']}" if m.get("target") else ""))
        if m.get("pct") is None:
            reason = (m.get("details") or {}).get("unmeasured_reason", "")
            if reason:
                o.append("")
                o.append(f"> {reason}")
        o.append("")
        o.append(f"**Xây dựng từ:** {spec['built_from']}")
        o.append("")
        o.append(f"**Vì sao cần:** {spec['why']}")
        o.append("")

    nc2 = by_id.get("NC.2") or {}
    d2 = nc2.get("details") or {}
    o.append("## 5. Kiểm định giả thuyết của negative control")
    o.append("")
    if d2.get("lift") is not None:
        o.append(f"- Quan sát: **{(d2['observed_rate'] or 0) * 100:.2f}%** same-feed trên "
                 f"{nc2.get('denominator', 0):,} trích dẫn.")
        o.append(f"- Kỳ vọng dưới H₀ (bốc ngẫu nhiên từ kho {d2.get('pool_total', 0)} node "
                 f"conduct): **{(d2['expected_rate_by_chance'] or 0) * 100:.2f}%**.")
        o.append(f"- **lift = {d2['lift']:.2f}** → "
                 + ("bác bỏ được H₀ (ngưỡng lift ≥ 2): truy hồi mang tín hiệu công ty."
                    if d2["lift"] >= 2 else
                    "**KHÔNG** bác bỏ được H₀: truy hồi không phân biệt được với bốc ngẫu nhiên."))
        o.append("")
        o.append(f"Phân bố kho theo mã: `{d2.get('pool_by_ticker')}`.")
    else:
        o.append(f"*{UNMEASURED}* — không đủ trích dẫn để kiểm định.")
    o.append("")

    o.append("## 6. Giới hạn & đe doạ tính hợp lệ")
    o.append("")
    o.append("Mỗi chỉ số tự khai giới hạn của chính nó; đây là bản gom, **phải đọc kèm bất kỳ "
             "con số nào được trích ra ngoài tài liệu này**.")
    o.append("")
    for m in metrics:
        if m.get("limitation"):
            o.append(f"- **{m['metric_id']}** — {m['limitation']}")
    o.append("")
    o.append("Bốn giới hạn ở tầng khung, không thuộc riêng chỉ số nào:")
    o.append("")
    o.append("- Không có ground truth ⇒ **không** có precision/recall/F1 về greenwashing.")
    o.append("- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, **không** đo **tính đúng**.")
    o.append("- Tỷ lệ abstention cao phản ánh **kho tin tức độc lập còn mỏng**, không phải "
             "lỗi thuật toán.")
    o.append("- Đồ thị hiện chỉ phủ **5 mã CK**; corpus 197 doanh nghiệp mới dừng ở tầng "
             "phân loại câu. Mọi phát biểu 'hệ thống bao phủ 197 doanh nghiệp' là sai.")
    o.append("")
    return "\n".join(o)
