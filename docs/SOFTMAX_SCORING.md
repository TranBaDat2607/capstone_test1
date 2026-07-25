# Softmax Scoring — phân bố 3 chỉ số `green_washing / not_green_washing / abstain` cho mỗi claim

> **Trạng thái (cập nhật 2026-07-25): ĐÃ cài đặt ở `src/step07b_enrich_dossiers.py`,
> nhưng KHÔNG dùng trong bản giao cuối.** Đã chạy thật: 1093/1093 claim trong
> `graph_output/crosscheck/aaa_claim_assessments.json` có `assessment_scores` (nằm trong
> snapshot HF đã pin). Tuy nhiên bề mặt trình bày cuối là UI `frontend/` + `api/`, và nó
> **không đọc** các trường này (grep `score|softmax|abstain` trên `frontend/js/app.js` +
> `api/evidence_service.py` = 0 kết quả); chỉ `step08` (→ property Neo4j) và `step09`
> (ledger text) đọc, và cả hai đều chạy được khi thiếu.
>
> Hệ quả: stage này **không được port** sang kiến trúc module `src_module/esg_kg/`
> (lý do + điều kiện đảo ngược: `src_module/esg_kg/DESIGN.md` §4.1). Nó **không bị xoá** —
> `python src/step07b_enrich_dossiers.py` vẫn chạy được. Tài liệu này vì vậy mô tả một
> **hướng đã cân nhắc và đã loại khỏi phạm vi**, không phải một thành phần đang phục vụ.
>
> Vấn đề 1 trong kế hoạch cải thiện trước bảo vệ lần 1. Đọc cùng
> `docs/CROSSCHECK_EXPANSION.md` (Vấn đề 2 — nguồn tín hiệu `kpi_gap` / `broken_promise` /
> `structural_contradiction` mà công thức ở đây tiêu thụ; **chưa có generator nên cả ba số
> hạng λ hiện đóng góp đúng 0**).

## 1. Mục tiêu và ràng buộc

Giữ **nguyên** format dossier hiện tại của step07 (`<ticker>_claim_assessments.json`,
assessment 3 nhãn + evidence buckets), nhưng bổ sung cho **mỗi claim** một phân bố:

```json
"assessment_scores": {
  "contradicted": 0.62,
  "supported":    0.11,
  "abstain":      0.27
}
```

với `sum = 1.0` (kết quả softmax). Ràng buộc thiết kế:

1. **Không vi phạm nguyên tắc §1.1 của SYSTEM_DESIGN** ("không score, không verdict").
   Cách dung hòa: đây **không phải xác suất công ty greenwashing** — nó là **phân bố
   cân bằng bằng chứng** (evidence-balance distribution) trên *một claim*, chuẩn hóa để
   3 thành phần so sánh được với nhau. **Tên key phải trung thực với semantics đó:**
   dùng `contradicted / supported / abstain` (thẳng hàng với bộ nhãn categorical
   `appears_contradicted / appears_supported / unverified`), **không** dùng
   `green_washing / not_green_washing` — một key literal `"green_washing": 0.62` trong
   JSON tự phản bội lời biện luận ở trên (hội đồng nhìn thấy key trước khi nghe giải
   thích, và tên đó lan xuống Neo4j/UI thì không rút lại được). Nhãn categorical vẫn
   là đầu ra chính; scores là lớp advisory bổ sung, có cờ `assessment_is_advisory=true`
   như cũ. Khi trình bày với hội đồng: *"chúng tôi lượng hóa mức cân bằng bằng chứng,
   không kết luận greenwashing"*.
2. **Deterministic + offline — nhưng phải phát biểu đúng tầng.** Điểm số phải tính lại
   được từ dossier đã có, **không gọi LLM thêm** (Gemini đang bị chặn; OpenAI tốn tiền;
   và LLM tự báo xác suất thì không calibrate được). Mọi thành phần của công thức đều
   đã nằm sẵn trong dossier: `confidence`, `independent`, `date_uncertain`, các bucket
   evidence, và (sau Vấn đề 2) `signals`. **Phát biểu chính xác khi bảo vệ:**
   deterministic là **tầng tổng hợp trên dossier đã đóng băng** — chạy lại step07 (LLM)
   sẽ *không* tái lập đúng bucket/confidence cũ. Dossier vì vậy được đối xử như *bằng
   chứng đã version hóa*: nó nằm trong snapshot HF được pin bởi `data_version.json`,
   nên mọi con số tái lập được từ dữ liệu đã pin. Khung trình bày: *"LLM chạy một lần,
   kết quả cấp cặp được lưu làm bằng chứng; công thức chỉ cân lại lời khai đã ghi âm —
   thẩm phán không lấy lại lời khai."*
3. **Tương thích EmeraldMind:** bộ ba **cùng không gian đầu ra** với
   `greenwashing / not_greenwashing / abstain` của EmeraldMind (`7-classify.py`) qua
   mapping cố định `contradicted↔greenwashing`, `supported↔not_greenwashing`,
   `abstain↔abstain` — nên phần đánh giá vẫn so sánh trực tiếp được hai hệ ("cùng
   không gian đầu ra với SOTA reference, nhưng có evidence trail"). **Mapping này chỉ
   xuất hiện trong phần so sánh của step10**, không nằm trong dossier / Neo4j / UI.

## 2. Công thức

Ký hiệu: với mỗi claim, `C` = tập contradicting evidence, `S⁺` = tập supporting evidence
có `independent=true` (bucket `flagged_non_independent_support` **không bao giờ** được
tính — giữ đúng self-verification guard của step07).

**Trọng số một mẩu bằng chứng** (phạt ngày không chắc chắn):

$$
w(e) = \text{confidence}(e) \times
\begin{cases}
0.8 & \text{nếu } \text{date\_uncertain}(e) = \text{true} \\
1.0 & \text{ngược lại}
\end{cases}
$$

Hai ghi chú về `w(e)`:

- **Phía contradicting không lọc độc lập** — step07 chỉ gắn `independent` cho support.
  Đây là chủ đích: bằng chứng mâu thuẫn đến từ chính miền của công ty là *admission
  against interest* (tự nhận bất lợi), đáng tính đủ trọng số.
- **`confidence` của LLM là đại lượng ordinal, không phải xác suất calibrated** (LLM
  self-report nổi tiếng dồn cụm 0.7–0.9, overconfident). `W_max` tồn tại chính để chặn
  thiệt hại từ điểm yếu này. Cờ `--bin-confidence` quy confidence về 3 mức ordinal
  (`<0.5→0.3`, `0.5–0.8→0.6`, `>0.8→0.9`) để bỏ độ chính xác giả; mặc định tắt để giữ
  đúng công thức gốc, nhưng sensitivity arm trong step10 (§4) đo cả hai chế độ.

**Logits:**

$$
z_{\text{contra}} = \min\!\left(\sum_{e \in C} w(e),\ W_{max}\right)
$$

$$
z_{\text{support}} = \min\!\left(\sum_{e \in S^{+}} w(e),\ W_{max}\right)
$$

$$
z_{\text{abstain}} = \beta_0 - \beta_1\cdot\left(z_{\text{contra}} + z_{\text{support}}\right)
$$

*(`z_abstain` giảm dần khi tổng khối lượng bằng chứng của hai phía kia tăng.)*

**Softmax với nhiệt độ $\tau$:**

$$
\big(\text{score}_{\text{contra}},\ \text{score}_{\text{support}},\ \text{score}_{\text{abstain}}\big)
= \operatorname{softmax}\!\left(\frac{z_{\text{contra}}}{\tau},\ \frac{z_{\text{support}}}{\tau},\ \frac{z_{\text{abstain}}}{\tau}\right)
$$

tức, với mỗi thành phần $i \in \{\text{contra}, \text{support}, \text{abstain}\}$:

$$
\text{score}_i = \frac{\exp(z_i / \tau)}{\displaystyle\sum_{j \in \{\text{contra}, \text{support}, \text{abstain}\}} \exp(z_j / \tau)}
$$

**Tham số mặc định** (điểm khởi đầu, sẽ calibrate — xem §4):

| Tham số | Mặc định | Vai trò |
|---|---|---|
| $\tau$ | 1.0 | độ "nhọn" của phân bố |
| $\beta_0$ | 1.5 | thiên vị abstain khi không có bằng chứng (đúng tinh thần "unverified là mặc định") |
| $\beta_1$ | 1.0 | tốc độ abstain nhường chỗ khi có bằng chứng |
| $\lambda_{struct}, \lambda_{kpi}, \lambda_{bp}$ | 0.5 | đóng góp của tín hiệu offline (Vấn đề 2); = 0 khi chưa cài Vấn đề 2 |
| $W_{max}$ | 3.0 | chặn trên tổng trọng số một phía (chống 15 bài báo yếu lấn át 1 bằng chứng mạnh) |
| phạt `date_uncertain` | 0.8 | ăn khớp caveat hiện có của step07 |

**Kiểm chứng nhanh bằng số** ($\tau=1$, $\beta_0=1.5$, $\beta_1=1$):

- *Không bằng chứng:* $(z_{\text{contra}}, z_{\text{support}}, z_{\text{abstain}}) = (0,\ 0,\ 1.5)$
  → $\text{scores} \approx (0.15,\ 0.15,\ \mathbf{0.69})$ — abstain thắng rõ, khớp
  1.001/1.093 claim `unverified` của AAA.
- *1 contradicting conf 0.8:* $(0.8,\ 0,\ 0.7) \to \text{scores} \approx (\mathbf{0.43},\ 0.19,\ 0.38)$
  — nghiêng mâu thuẫn nhưng còn dè dặt, phản ánh đúng "một bài báo thì chưa chắc".
- *2 contradicting conf 0.8:* $(1.6,\ 0,\ -0.1) \to \text{scores} \approx (\mathbf{0.72},\ 0.15,\ 0.13)$
  — tự tin dần theo khối lượng bằng chứng. Hành vi đơn điệu, giải thích được — đúng thứ hội đồng cần.

Một hệ quả semantics cần nói rõ (tránh bị hỏi bất ngờ): khi bằng chứng **nặng cả hai
phía**, $z_{\text{abstain}}$ sụp sâu → phân bố tiến về $\sim(0.5,\ 0.5,\ 0.0)$ — "tự tin giằng co",
**không phải** abstain cao. Đây là lựa chọn thiết kế đúng semantics EmeraldMind
(abstain = thiếu bằng chứng, không phải bằng chứng xung đột); case giằng co được bắt
bằng cờ `score_disagrees_with_assessment` (§3) + caveat "Evidence is mixed" sẵn có.

## 3. Quan hệ với assessment categorical hiện tại

Quy tắc 6d của step07 là **lexicographic**: có ≥1 contradicting → `appears_contradicted`
bất kể bao nhiêu supporting. Softmax thì cân cả hai phía, nên **argmax có thể lệch nhãn
categorical** (ví dụ 1 contradicting conf 0.4 vs 3 supporting conf 0.9 → argmax =
`supported` nhưng nhãn = `appears_contradicted`). Mặt khác, chính tính chất này làm
softmax **bền hơn nhãn categorical trước một phán quyết LLM sai đơn lẻ**: quy tắc 6d bị
lật hoàn toàn bởi 1 cặp `contradicts` phán nhầm, còn trong softmax cặp nhầm đó chỉ đóng
góp tối đa confidence của nó vào một tổng bị chặn `W_max` và bị phía kia cân lại.

**Quyết định thiết kế: không ép khớp.** Giữ nhãn categorical theo quy tắc cũ (format
không đổi), thêm cờ:

```json
"score_disagrees_with_assessment": true
```

khi argmax ≠ nhãn. Các claim lệch chính là **mixed-evidence** — tập con đáng đưa vào
review queue và là case study tốt cho step10. Báo cáo "tỷ lệ nhất quán argmax" như một
chỉ số đánh giá (kỳ vọng >90% trên AAA vì đa số claim chỉ có bằng chứng một phía).

## 4. Calibration (không cần ground truth)

Không có nhãn chuẩn nên **không** calibrate theo "độ đúng greenwashing" — calibrate theo
**tính nhất quán nội bộ**: grid search tối đa hóa tỷ lệ argmax trùng nhãn categorical
trên 1.093 dossier AAA (offline, chạy vài giây).

**Một cái bẫy phải né:** trên AAA, 1.001/1.093 claim unverified *luôn* khớp argmax miễn
β₀>0 — chúng không tạo áp lực gì lên grid search. Áp lực thật đến từ ~92 claim có bằng
chứng, và để ép các claim "1 bằng chứng yếu" (vd. 1 contradicting conf 0.4 → z =
(0.4, 0, 1.1) → abstain thắng) khớp nhãn lexicographic, grid search sẽ bị kéo về **β₀
thấp / τ nhỏ** — tức tự phá tinh thần "unverified là mặc định" mà bảng tham số tuyên bố.
Vì vậy:

- **β₀ CỐ ĐỊNH theo prior, không đưa vào grid**: chọn trước mức abstain mong muốn khi
  zero-evidence (β₀=1.5 ⇒ abstain ≈ 0.69) — đây là một quyết định thiết kế, không phải
  tham số fit.
- Grid search chỉ trên **(τ, β₁, W_max)**, tối đa hóa tỷ lệ argmax trùng nhãn.
- Phần lệch do bằng chứng đơn lẻ yếu là **feature, không phải lỗi cần calibrate mất đi**:
  "một bài báo conf 0.4 chưa đủ nghiêng" — khi bảo vệ, gọi tên nó thay vì giấu nó.

Mục tiêu vẫn khiêm tốn nhưng phòng thủ được: "tham số được chọn để phân bố tái tạo quy
tắc quyết định đã thiết kế; phần lệch còn lại là mixed-evidence hoặc bằng chứng-yếu có
chủ đích". Kèm **sensitivity analysis** 1 trang trong step10, gồm 3 arm — chặn trước câu
hỏi "đổi tham số thì kết quả đổi bao nhiêu" và "confidence LLM không calibrate thì sao":

1. score thay đổi thế nào theo τ, β₀;
2. **nhiễu ±0.1 lên mọi confidence → bao nhiêu % argmax bị lật** (đo trực tiếp độ nhạy
   với input yếu nhất của công thức);
3. bật/tắt `--bin-confidence` (ordinal 3 mức) → tỷ lệ nhất quán đổi bao nhiêu.

## 5. Cài đặt

**Script mới `src/step07b_enrich_dossiers.py`** (offline, NO LLM/DB — cùng script sinh
`signals` của Vấn đề 2, vì scores tiêu thụ signals):

```
đọc  graph_output/crosscheck/<ticker>_claim_assessments.json
  (+ graph_output/resolved/resolved_graph.json cho signals — xem CROSSCHECK_EXPANSION.md)
tính signals → tính (z_contra, z_support, z_abstain) → softmax → ghi NGƯỢC vào chính dossier:
  + assessment_scores {contradicted, supported, abstain}
  + score_components  {z_contradicted, z_supported, z_abstain, sum_w mỗi phía,
                       signal_terms, params}    # audit trail — hội đồng truy được từng số hạng
  + score_disagrees_with_assessment
cờ: --ticker, --params <json>, --calibrate (grid search (τ,β₁,W_max), β₀ cố định, in bảng),
    --bin-confidence (ordinal 3 mức), --dry-run
```

Lý do tách khỏi step07: step07 là đường chạy **tốn tiền** (LLM bắt buộc) — enrichment
phải chạy lại được nhiều lần miễn phí khi chỉnh tham số, đúng nguyên tắc "verify cheaply".

**Lan truyền xuống hạ nguồn (mỗi chỗ ~vài dòng):**

- `step08_sync_crosscheck_to_neo4j.py`: SET thêm `score_contradicted` / `score_supported` /
  `score_abstain` + `score_disagrees_with_assessment` lên node claim (đã có sẵn khung
  MERGE properties; `--clear-advisory` cũng phải REMOVE chúng).
- `step09_report_claim_ledger.py`: in một dòng
  `scores: contradicted=0.62 · supported=0.11 · abstain=0.27`.
- Lớp hiển thị: các điểm `score_*` được ghi sẵn lên node claim trong Neo4j (step08), nên
  UI bất kỳ đọc được. Thanh trực quan "cân bằng bằng chứng" 3 đoạn từng nằm ở demo Streamlit
  (`app.py`) — đã gỡ cùng app.py; một UI sau này có thể vẽ lại từ chính các điểm này. Nhớ
  framing: "cân bằng bằng chứng ≠ xác suất greenwashing".
- Pseudo-code lõi (~30 dòng, không dependency mới):

```python
import math

def softmax_scores(d, p):                      # d = dossier item, p = params
    w = lambda e: (e.get("confidence") or 0.0) * (0.8 if e.get("date_uncertain") else 1.0)
    sig = d.get("signals", {}) or {}
    z_c = min(sum(w(e) for e in d["contradicting_evidence"]), p["w_max"]) \
        + p["lam"] * sum(bool(sig.get(k)) for k in
                         ("structural_contradiction", "kpi_gap", "broken_promise"))
    z_s = min(sum(w(e) for e in d["supporting_evidence"] if e.get("independent")), p["w_max"])
    z_a = p["beta0"] - p["beta1"] * (z_c + z_s)
    exps = [math.exp(z / p["tau"]) for z in (z_c, z_s, z_a)]
    s = sum(exps)
    return {"contradicted": exps[0] / s, "supported": exps[1] / s, "abstain": exps[2] / s}
```

## 6. Chuẩn bị câu hỏi hội đồng

| Câu hỏi dự kiến | Trả lời chuẩn bị sẵn |
|---|---|
| "`contradicted: 0.62` nghĩa là 62% khả năng greenwashing?" | Không — là tỷ trọng bằng chứng nghiêng về mâu thuẫn sau chuẩn hóa (tên key nói đúng điều đó). Không tồn tại ground truth để nói về xác suất đúng nghĩa (§1.1). |
| "Con số lấy từ đâu? Chạy lại có ra đúng không?" | Công thức đóng, deterministic **trên dossier đã đóng băng** (pin trong `data_version.json` — snapshot HF); `score_components` cho phép truy ngược từng số hạng. Chạy lại step07b ra đúng số cũ; chạy lại step07 là *lấy lời khai mới* — công thức chỉ cân lại lời khai đã lưu, thẩm phán không lấy lại lời khai. |
| "Input do LLM sinh (bucket, confidence) thì tin sao được?" | Không *giả định* nó đúng — *đo* nó: step10 đo link-precision cấp cặp (manual + 30-case gold set) và công bố con số đó làm giới hạn tin cậy. Lỗi LLM bị cô lập ở từng cặp có rationale + trace về câu nguồn, một người verify được trong 30 giây — khác hẳn một verdict holistic. Sensitivity arm ±0.1 confidence (§4) đo thêm độ nhạy của argmax với chỗ yếu nhất. |
| "Sao không để LLM chấm thẳng?" | LLM probabilities không calibrate được, không tái lập được, tốn tiền mỗi lần chỉnh; công thức offline thì tái lập + audit + miễn phí — và đẩy phần "không tin được" xuống đơn vị nhỏ nhất kiểm tra được. |
| "Tham số chọn thế nào?" | β₀ cố định theo prior (quyết định thiết kế: abstain ≈0.7 khi zero-evidence); grid search (τ, β₁, W_max) tối đa nhất quán với quy tắc categorical + sensitivity analysis trong step10 (§4 — kể cả lý do KHÔNG đưa β₀ vào grid). |
| "abstain khác gì unverified?" | Cùng semantics (theo EmeraldMind: từ chối phán xét vì thiếu bằng chứng) — nhưng giờ có *mức độ*: abstain 0.9 (mù hoàn toàn) khác abstain ~0.4 (bằng chứng ít và yếu). Lưu ý: giằng co nặng hai phía **không** ra abstain cao — nó ra phân bố ~50/50 với abstain thấp, được bắt bằng cờ `score_disagrees_with_assessment` + caveat "Evidence is mixed" (§2). |
