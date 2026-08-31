# Đánh giá hệ thống khi KHÔNG có nhãn chuẩn (label-free evaluation)

> **Trạng thái: ĐỀ XUẤT, chưa triển khai.** Không có dòng code nào trong repo hiện thực
> các phép đo ở §3–§7. Đọc file này như một *thiết kế đánh giá*, không phải mô tả code
> đang chạy — cùng loại với `CROSSCHECK_EXPANSION.md` và `BERT_NER_GRAPH_QUALITY.md`.
>
> **Quan hệ với `step10` đã bị xoá (2026-07-28):** `src/step10_evaluate.py` và
> `docs/EVALUATION.md` bị loại khỏi phạm vi đề tài vì lối đo *coverage / case-study /
> ablation thuần mô tả* không còn là deliverable. Tài liệu này **không khôi phục** step10.
> Khác biệt cốt lõi: step10 đếm hệ thống làm được bao nhiêu; thiết kế dưới đây kiểm tra
> hệ thống có **hơn ngẫu nhiên**, có **ổn định**, và có **tôn trọng các quan hệ logic nó
> tự tuyên bố** hay không — ba thứ đo được mà không cần một nhãn nào. §7 (ablation) là
> phần duy nhất trùng ý tưởng với step10, và nó ở đây với vai trò phụ.
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §1.1 (ràng buộc không-ground-truth,
> nguồn gốc của mọi thứ dưới đây) · [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) §4
> (Q1–Q8 — đo chất lượng **đồ thị**; tài liệu này đo chất lượng **kết quả**, hai tầng khác nhau)
> · [`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) (đối tượng được đo)
>
> **CẬP NHẬT 2026-08-08 — tiền đề "không có nhãn nào" nay cần nói chính xác hơn.**
> Đã tồn tại một tập nhãn người thật: **220 cặp `(claim, evidence)`, hai người chấm độc lập,
> Cohen's κ = 0,714** (`sheetA.xlsx` / `sheetB.xlsx`, theo sổ tay đã freeze
> [`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md); kết quả ở
> [`ANNOTATION_RESULTS.md`](./ANNOTATION_RESULTS.md)). Điều này **không** làm file này hết
> giá trị, vì tập đó là mẫu các **dự đoán dương** của hệ: nó cho **precision**, còn recall,
> prevalence và toàn bộ phần hệ thống nằm ngoài 220 cặp thì vẫn phải đo theo khung không-nhãn
> dưới đây. Cách nói đúng từ nay: *"không có tập greenwashing có nhãn ở quy mô corpus; có một
> tập gold 220 cặp ở tầng link"* — đừng lặp lại "không có nhãn nào" một cách không điều kiện.

---

## 0. Tóm tắt cho người bận rộn

| Câu hỏi | Trả lời ngắn |
|---|---|
| Không có nhãn thì đo được accuracy không? | **Không.** Bất kỳ ai nói ngược lại là đang bịa. Đừng tuyên bố độ chính xác. |
| Vậy đo được gì? | **Ba thuộc tính**: (1) *non-randomness* — hệ hơn ngẫu nhiên (§4); (2) *reliability* — hệ ổn định (§5, §6); (3) *logical soundness* — hệ tuân thủ quan hệ nó tuyên bố (§3). |
| Metric nào mạnh nhất trên đơn vị chi phí? | **§4 Negative control** — 191 lệnh gọi LLM, cho ra p-value thật. Đồng thời là kill-test của cả đề tài. |
| Metric nào giá trị học thuật cao nhất? | **§3 MR-4 (dịch thời gian)** — nó kiểm chứng chính nguyên tắc P8 mà đề tài nhận là đóng góp. |
| Metric nào chạy được ngay hôm nay, 0đ? | §2.3 (claim trùng lặp — **đã có kết quả: 1/23 mâu thuẫn**), §7.1 (ablation guard: 18 cạnh). |
| Vì sao tự làm mà vẫn khách quan? | Vì bạn **không phán xét claim nào đúng**. Bạn áp một phép biến đổi máy móc rồi kiểm quan hệ đầu vào ↔ đầu ra. Không có chỗ cho thiên kiến người làm — đây chính là khác biệt so với tự gán nhãn. |
| Chỗ trống của lĩnh vực | [Survey NLP greenwashing (arXiv 2502.07541)](https://arxiv.org/pdf/2502.07541) kết luận: **chưa tồn tại dataset greenwashing đã kiểm chứng, chưa có benchmark chuẩn, chưa có giao thức đánh giá không-ground-truth.** Nên bản thiết kế đánh giá này là một đóng góp phát biểu được, không phải lời xin lỗi vì thiếu dữ liệu. |

---

## 1. Ràng buộc, và ranh giới nó vẽ ra

### 1.1 Ràng buộc

1. **Không có nhãn greenwashing chuẩn** cho doanh nghiệp Việt Nam (`SYSTEM_DESIGN.md` §1.1).
2. **Không có chuyên gia gán nhãn.**
3. **Tác giả tự gán nhãn là không khách quan** — và sẽ bị hội đồng chất vấn đúng chỗ đó.

Ràng buộc 2 và 3 loại bỏ toàn bộ nhóm metric dựa trên mẫu gán nhãn tay: link precision,
Cohen's κ người–người, κ người–LLM, recall vét cạn. **Đừng dùng chúng.**

### 1.2 Ranh giới: cái gì đo được, cái gì không

| | Đo được không nhãn? | Ghi chú |
|---|---|---|
| **Validity / accuracy** — hệ có đúng không | ❌ **Không** | Cần oracle. Không có oracle thì không có accuracy. Chấm hết. |
| **Non-randomness** — hệ có hơn ngẫu nhiên không | ✅ Có | Qua nhóm đối chứng + kiểm định hoán vị (§4) |
| **Reliability** — cùng đầu vào cho cùng đầu ra | ✅ Có | Test–retest, claim trùng lặp (§5) |
| **Logical soundness** — đầu ra biến đổi đúng khi đầu vào biến đổi | ✅ Có | Metamorphic testing (§3) |
| **Convergent validity** — hai phương pháp độc lập có đồng ý nhau | ✅ Có | κ giữa tầng keyword và tầng LLM (§6) |
| **Contribution** — thành phần nào đóng góp bao nhiêu | ✅ Có | Ablation (§7) |

**Câu phải nói ra trước khi hội đồng hỏi:**

> Không tồn tại nhãn greenwashing chuẩn cho doanh nghiệp Việt Nam, và survey của lĩnh vực
> xác nhận chưa có benchmark. Do đó tôi **không tuyên bố độ chính xác**. Tôi đo ba thuộc
> tính kiểm chứng được: hệ thống hơn ngẫu nhiên (p-value từ kiểm định hoán vị), hệ thống
> ổn định (test–retest và claim trùng lặp), và hệ thống tôn trọng các quan hệ logic nó
> tuyên bố (6 metamorphic relation, trong đó MR-4 kiểm chính nguyên tắc thời gian P8 của
> thiết kế).

---

## 2. Ảnh chụp hiện trạng — mọi phép đo dưới đây neo vào các số này

**Đo ngày 2026-07-28.** Ghi rõ nguồn vì hai artifact KHÔNG thay thế được cho nhau (§8.1).

### 2.1 Quy mô

| Đại lượng | Giá trị | Nguồn |
|---|---|---|
| Node / edge trong Neo4j | 12.969 / 17.155 | Neo4j live |
| Node / edge trong `resolved_graph.json` | 10.425 / 14.402 | file |
| Chênh lệch node | +2.544 | **Không phải lệch phiên bản** — step06 sinh thêm node version (vd. `Organization` 438 → 1.224). Node gốc khớp nhau. |
| Dossier claim | 1.093 | `graph_output/crosscheck/aaa_claim_assessments.json` |
| Conduct pool | 124 (108 `KPIObservation` + 16 `MediaReport`) | `aaa_crosscheck_stats.json` |
| Node `source_type=news` trong đồ thị | 208 / 10.425 = **2,0%** | file |

### 2.2 Đầu ra tầng cross-check

| Đại lượng | Giá trị |
|---|---|
| `unverified_insufficient_evidence` | 1.001 (91,6%) |
| `appears_supported` | 70 (6,4%) |
| `appears_contradicted` | 22 (2,0%) |
| Cặp ứng viên retrieval | 3.461 |
| Evidence item được giữ | 191 → **yield 5,5%** |
| Claim có ≥1 bằng chứng | 92 (8,4%) |
| Cạnh advisory trong Neo4j | 209 = 166 `llm_supports` + 25 `llm_contradicts` + 18 `llm_flagged_support` |
| Lớp node bằng chứng | `KPIObservation` 175, `MediaReport` 34 — **chưa từng có `Controversy`/`Penalty`** |
| `date_uncertain` trên evidence | **191/191 = 100%** |
| `confidence` LLM phát ra | chỉ 3 giá trị: `{0.8: 106, 0.9: 84, 1.0: 1}` |
| `score_disagrees_with_assessment` | 66/1.093 = **6,04%** |
| Điểm `abstain` (softmax) | min 0,002 · max 0,691 · **20 giá trị phân biệt** |

### 2.3 Metric đã chạy được, 0đ, kết quả có sẵn

**Nhất quán trên claim trùng lặp** — cùng một câu tuyên bố xuất hiện ở nhiều báo cáo thì
hệ thống phải cho cùng kết luận.

```
23 nhóm trùng lặp / 50 claim
1 nhóm MÂU THUẪN (4,3%):
  "largest plastic packaging exporter in vietnam"
    2020 -> appears_supported
    2023 -> unverified_insufficient_evidence
```

Cách đo (offline, không LLM, không Neo4j):

```python
import json, re
from collections import defaultdict
d = json.load(open("graph_output/crosscheck/aaa_claim_assessments.json", encoding="utf-8"))
by = defaultdict(list)
for x in d:
    by[re.sub(r"\s+", " ", x["claim_text"].strip().lower())].append(x)
dups = {k: v for k, v in by.items() if len(v) > 1}
incons = sum(1 for v in dups.values() if len({x["assessment"] for x in v}) > 1)
print(f"verdict_consistency_duplicate = {1 - incons/len(dups):.3f}  ({len(dups)} nhóm)")
```

**Cảnh báo cỡ mẫu:** 23 nhóm là nhỏ. Báo cáo kèm khoảng tin cậy Wilson, đừng báo cáo trần
tỉ lệ. Đây là chỉ báo bổ trợ, không phải metric chính.

---

## 3. HỌ A — Metamorphic / Behavioral testing ⭐ trọng tâm

### 3.1 Nguyên lý — vì sao nó thay được nhãn

Metamorphic testing sinh ra để giải đúng **oracle problem**: khi không biết đầu ra đúng cho
một đầu vào bất kỳ, ta vẫn kiểm được **quan hệ** giữa đầu ra của đầu vào gốc và đầu ra của
đầu vào đã biến đổi theo cách đã biết ([survey MT × LLM](https://arxiv.org/html/2605.13898v1)).

Áp vào đây: **bạn không cần biết claim "AAA tiên phong nhựa thân thiện môi trường" là đúng
hay sai. Bạn chỉ cần biết rằng nếu phủ định nó, kết luận của hệ thống PHẢI đổi.**

Khung phân loại test lấy từ [CheckList, ACL 2020](https://aclanthology.org/2020.acl-main.442.pdf):

- **MFT** (Minimum Functionality Test) — ca đơn giản, đáp án mang tính định nghĩa
- **INV** (Invariance) — biến đổi giữ nhãn ⇒ đầu ra phải **không đổi**
- **DIR** (Directional) — biến đổi đổi nhãn ⇒ đầu ra phải đổi **theo hướng đã biết**

### 3.2 Sáu metamorphic relation cho hệ này

Đối tượng đo: hàm phán xử của step07 — `Adjudicator.adjudicate(claim, evidence) -> {supports, contradicts, irrelevant}`.

| MR | Loại | Biến đổi | Kỳ vọng bắt buộc | Sinh bằng |
|---|---|---|---|---|
| **MR-1 Phủ định** | DIR | Claim: chèn phủ định | `supports` ⇒ **không được** còn là `supports` | Template |
| **MR-2 Đảo dấu số** | DIR | Evidence: `-42,3%` → `+42,3%`; "giảm" ↔ "tăng" | Verdict phải lật | Regex |
| **MR-3 Đổi chủ thể** | DIR | Evidence: thay "An Phát"/"AAA" bằng công ty khác | ⇒ `irrelevant` | Thay chuỗi |
| **MR-4 Dịch thời gian** | DIR | Evidence: đẩy ngày ra **sau** ngày claim | ⇒ `irrelevant` | Sửa trường ngày |
| **MR-5 Diễn đạt lại** | INV | Claim: paraphrase giữ nghĩa | Verdict **không đổi** | Template |
| **MR-6 Chèn nhiễu** | INV | Evidence: nối thêm 1 câu vô quan | Verdict **không đổi** | Nối chuỗi |

### 3.3 Vì sao MR-2 và MR-4 được ưu tiên

- **MR-2** — 175/191 evidence là `KPIObservation` chứa số (§2.2). Đây là phần lớn bề mặt
  thật của hệ. Biến đổi thuần regex nên **không nhập nhiễu LLM** vào phép đo.
- **MR-4** — kiểm chứng trực tiếp **nguyên tắc P8** (`TEMPORAL_KG_DESIGN.md` §3): *"báo cáo
  2021 không thể bị buộc tội mâu thuẫn với thông tin chỉ xuất hiện 2024"*. Đề tài nhận mặt
  nạ bitemporal là đóng góp; MR-4 là cách duy nhất chứng minh nó thật sự hoạt động ở tầng
  output.
  **Dự báo trước khi chạy (ghi lại để khỏi self-serving):** MR-4 sẽ **hỏng nặng**, vì 100%
  evidence mang `date_uncertain=True` nên bộ lọc thời gian gần như không có gì để bấu víu
  (§2.2). Một dự báo hỏng có kiểm chứng vẫn là kết quả nghiên cứu tốt hơn một con số đẹp
  không ai tin.

### 3.4 Công thức

Cho MR loại DIR, trên tập cặp `P` có verdict gốc khác `irrelevant`:

```
MR_violation_rate = |{p ∈ P : verdict(T(p)) KHÔNG thoả kỳ vọng}| / |P|
```

Cho MR loại INV:

```
MR_flip_rate = |{p ∈ P : verdict(T(p)) ≠ verdict(p)}| / |P|
```

Báo cáo cả hai kèm khoảng tin cậy Wilson 95%. **Thấp hơn là tốt hơn cho cả hai.**

### 3.5 Cách chạy trên dữ liệu thật

Tập đo: **191 cặp (claim, evidence) đã có verdict**, trích thẳng từ dossier — không cần
chạy lại retrieval.

```python
import json
d = json.load(open("graph_output/crosscheck/aaa_claim_assessments.json", encoding="utf-8"))
pairs = [
    {"claim_id": x["claim_id"], "claim_text": x["claim_text"],
     "evidence_node": e["node_index"], "evidence_text": e["text"],
     "evidence_year": e.get("year"), "claim_year": x.get("year"),
     "verdict_goc": role}
    for x in d
    for role, lst in (("supports", x.get("supporting_evidence") or []),
                      ("contradicts", x.get("contradicting_evidence") or []))
    for e in lst
]
assert len(pairs) == 191
```

Sau đó, với mỗi MR: sinh cặp biến đổi bằng template/regex, gọi lại `Adjudicator` (tái dùng
`esg_kg.crosscheck.claims_vs_conduct.Adjudicator` — stage đã migrate), so verdict.

**Bắt buộc**: dùng đúng `ADJUDICATE_SYSTEM` gốc và `temperature=0`. Đổi prompt là đo hệ khác.

Chi phí: 191 × 6 = **1.146 lệnh gọi** ≈ 33% một lần chạy step07 gốc (3.461).

### 3.6 Cạm bẫy — MR-1 và MR-5 tự nhập nhiễu

Nếu sinh câu phủ định / paraphrase **bằng LLM**, bạn đưa nhiễu của LLM vào chính phép đo và
không còn phân biệt được "hệ sai" với "câu sinh ra tồi". Cách vá: **biến đổi theo template
máy móc**, không nhờ LLM viết lại.

Claim trong dossier đang ở **tiếng Anh** (kiểm chứng: `"implemented many meaningful social
activities…"`, `"Ensures growth in revenue and profit"`), nên template hoạt động tốt:

```python
NEG = [(r"\bEnsures\b", "Fails to ensure"), (r"\bimplemented\b", "failed to implement"),
       (r"\bachieved\b", "did not achieve"), (r"\breduced\b", "did not reduce"),
       (r"\bincreased\b", "did not increase"), (r"\bfully\b", "only partially")]
```

MR-2/3/4/6 thuần regex hoặc thay chuỗi ⇒ **không dính vấn đề này**. Đó là lý do thứ hai để
ưu tiên chúng.

---

## 4. HỌ B — Negative control + kiểm định hoán vị ⭐ mạnh nhất trên đơn vị chi phí

### 4.1 Nguyên lý

Bạn không biết cặp nào đúng, nhưng bạn biết chắc: **cặp ghép ngẫu nhiên phần lớn phải là
`irrelevant`**. Đó là một nhóm đối chứng hợp lệ, và nó không cần một nhãn nào.

### 4.2 Metric B1 — Specificity trên cặp ngẫu nhiên

Lấy 191 cặp `(claim, conduct)` mà retrieval **không** chọn (lấy ngẫu nhiên từ 1.093 × 124
trừ đi 3.461 cặp đã xét), cho adjudicator chấm với **đúng prompt gốc**.

```
specificity_random = |{cặp ngẫu nhiên nhận verdict "irrelevant"}| / 191
lift = P(verdict ≠ irrelevant | cặp retrieval chọn) / P(verdict ≠ irrelevant | cặp ngẫu nhiên)
```

**Đây là kill-test của cả đề tài.** Nếu `lift ≈ 1` — tức hệ phán "supports/contradicts" cho
cặp ngẫu nhiên với tỉ lệ tương đương cặp được chọn — thì tầng retrieval **không đóng góp gì**
và toàn bộ pipeline là nhiễu. Kết quả này phải được báo cáo dù nó xấu.

Giá trị tham chiếu: yield hiện tại trên cặp retrieval là **5,5%** (§2.2). Nếu cặp ngẫu nhiên
cũng cho ~5%, đó là tin rất xấu; nếu cho <1%, `lift > 5` và retrieval thật sự có tác dụng.

Chi phí: **191 lệnh gọi** = 5,5% một lần chạy step07.

### 4.3 Metric B2 — Kiểm định hoán vị (0đ, không LLM)

Cho ra **p-value thật mà không cần nhãn nào**:

1. Giữ nguyên tập verdict đã có.
2. Xáo trộn ngẫu nhiên ánh xạ claim ↔ evidence 1.000 lần.
3. Mỗi lần, tính lại thống kê quan tâm — vd. số claim `appears_contradicted` theo quy tắc
   ánh xạ của step07 (`crosscheck/claims_vs_conduct.py`, hàm gán assessment).
4. So giá trị thật (**22**) với phân phối null.

```
p = (số hoán vị cho thống kê ≥ giá trị thật + 1) / (1000 + 1)
```

Phát biểu được: *"số phát hiện mâu thuẫn cao hơn mức ngẫu nhiên với p < 0,01"* — một câu
định lượng, phòng thủ được, **không tốn một xu LLM** vì bước 3 chỉ chạy lại logic gán nhãn
xác định trên verdict đã có.

### 4.4 Metric B3 — Đối chứng âm cấu trúc (0đ)

Bổ sung rẻ: ghép claim của AAA với conduct node **của tổ chức khác** đã có sẵn trong đồ thị
(438 `Organization`). Không cần LLM nếu chỉ đo tầng retrieval: đếm bao nhiêu cặp như vậy lọt
vào top-k của step 6a. Con số này phải **≈ 0**; lớn hơn 0 là lỗi định danh chủ thể.

---

## 5. HỌ C — Độ tin cậy, thay cho inter-annotator agreement

Bạn không có 2 người chấm. Nhưng **Krippendorff's α được định nghĩa cho bất kỳ tập rater
nào** — coi mỗi lần chạy hệ thống là một rater. Đây là thay thế hợp lệ, không phải mẹo.

| Metric | Cách đo | Chi phí | Kỳ vọng |
|---|---|---|---|
| **C1 Test–retest** | Chạy lại 191 cặp × 3 lần, tính α giữa các lần | 573 gọi | Ở `temperature=0` mà α < 1 thì **bản thân đó là phát hiện** |
| **C2 Position bias** | Đảo thứ tự evidence trong prompt → flip rate | 191 gọi | LLM-judge nổi tiếng nhạy vị trí |
| **C3 Nhất quán claim trùng lặp** | §2.3 | **0đ** | Đã có: 1/23 |
| **C4 Nhất quán score ↔ nhãn** | `score_disagrees_with_assessment` | **0đ** | Đã có: 6,04% |

**C4 cần đọc cẩn thận:** softmax của step07b là hàm xác định trên chính dossier, nên đây là
kiểm tra *tính mạch lạc nội bộ giữa hai cách tóm tắt cùng một bằng chứng*, không phải hai
nguồn độc lập. Đừng trình bày nó như agreement giữa hai hệ.

---

## 6. HỌ D — Convergent validity giữa hai phương pháp độc lập

Hai phương pháp độc lập cùng gán chỉ tiêu cho một claim mà đồng ý nhau ⇒ bằng chứng hội tụ,
khái niệm đo lường chuẩn, **không cần nhãn**.

- Tầng 1: `alignment_method=keyword` (step05c, xác định, từ khớp cụm từ dài nhất)
- Tầng 2: `alignment_method=llm` (step05d, phân loại chủ đề bằng LLM)

**Hiện tại không tính được:** đã kiểm, 639/639 cạnh `alignsWithIndicator` đều là `keyword`,
**0 cạnh `llm`**. Mở khoá bằng cách chạy step05d:

```bash
python src/run.py align_claims --max-llm-pairs 200
```

Sau đó tính Cohen's κ trên tập claim mà **cả hai tầng** đều gán được:

```cypher
MATCH (c:SustainabilityClaim)-[r1:alignsWithIndicator {alignment_method:'keyword'}]->(i1),
      (c)-[r2:alignsWithIndicator {alignment_method:'llm'}]->(i2)
RETURN c._node_key, i1.id AS keyword_id, i2.id AS llm_id
```

κ cao ⇒ hai cách nhìn độc lập hội tụ. κ thấp ⇒ ít nhất một tầng không đáng tin, và bạn biết
phải điều tra chỗ nào. **Cả hai kết quả đều dùng được**, đó là dấu hiệu của một metric tốt.

---

## 7. HỌ E — Ablation

Đo **thay đổi**, không đo đúng/sai ⇒ không cần nhãn.

| Ablation | Δ đo được | Chi phí |
|---|---|---|
| **E1** Tắt self-verification guard | 18 cạnh `llm_flagged_support` quay về `llm_supports` (+10,8% support) | **0đ, đã biết** |
| **E2** Bỏ trục chỉ tiêu | Δ số ứng viên retrieval, Δ số claim hiển thị được (264 → ?) | 0đ (chỉ chạy lại retrieval offline) |
| **E3** Đổi cửa sổ thời gian | `window_before=1, window_after=50` hiện tại rất rộng → thu hẹp, đo Δ cặp ứng viên | 0đ |
| **E4** Bỏ tầng keyword alignment | Δ độ phủ claim | 0đ |

**E3 đáng chú ý:** cửa sổ `window_after=50` nghĩa là bằng chứng sau claim tới 50 năm vẫn được
xét. Kết hợp với `date_uncertain=100%`, khả năng cao trục thời gian hiện **không ràng buộc gì**.
E3 định lượng được điều đó mà không cần nhãn, và nó nói cùng một câu chuyện với MR-4 (§3.3) —
hai đường độc lập dẫn tới cùng kết luận thì kết luận đó vững.

---

## 8. Metric ĐÃ KIỂM và ĐÃ CHẾT — đừng đề xuất lại

Ghi lại để vòng sau không mất công. Tất cả đều đã đo trên dữ liệu thật ngày 2026-07-28.

| Metric | Vì sao chết | Bằng chứng |
|---|---|---|
| **Calibration (ECE / Brier) trên `confidence`** | LLM chỉ phát ra 3 giá trị, không có item nào < 0,8 ⇒ không có phổ thì không có đường hiệu chuẩn | `{0.8: 106, 0.9: 84, 1.0: 1}` |
| **Đối chiếu số liệu report ↔ news trên cùng chỉ tiêu** | **0/25** chỉ tiêu có cả hai kênh | cũng là lý do `kpi_gap` là ghost signal (`CROSSCHECK_EXPANSION.md`) |
| **κ hội tụ keyword ↔ llm** | 0 cạnh `llm` tồn tại | 639/639 là `keyword` — **hồi sinh được** bằng §6 |
| **`date_uncertain` như caveat phân biệt** | 191/191 = 100% ⇒ entropy 0, không phân biệt được dossier nào | §2.2 |
| **Mọi metric cần nhãn** | Ràng buộc §1.1 | link precision, κ người–LLM, recall vét cạn |
| **Điểm greenwashing cấp công ty** | Đã bác bỏ có lý do từ trước | `STANDARD_INDICATOR_AXIS.md` §2.5 |

---

## 9. Cạm bẫy đo lường trên chính đồ thị này

### 9.1 ⚠ KHÔNG join dossier với `resolved_graph.json` bằng `claim_node_index`

`claim_node_index` trong dossier **đã lệch** so với `resolved_graph.json` hiện tại. Đo thực tế:

```
offset 0  : 203 claim      offset -1 : 78
offset -3 : 231            offset -2 : 23
không tìm thấy trong ±3: 557
```

Hệ quả: mọi metric join bằng chỉ số mảng sẽ sai ~50% mà **không báo lỗi**.

**Luôn join bằng `claim_id`.** Đã kiểm trên Neo4j live: 1.093/1.093 khớp text, 1.093/1.093
khớp assessment, 0 `claim_id` trùng. Tầng advisory lành lặn *chính vì* step08 giải bằng
stable-id chứ không tin vào vị trí mảng — đây cũng là thứ GitHub issue #2 đang bảo vệ.

### 9.2 Neo4j và file KHÔNG thay thế cho nhau

12.969 vs 10.425 node **không phải lệch phiên bản** — step06 sinh thêm node version
(`Organization` 438 → 1.224). Node gốc khớp nhau (đã kiểm: text tại `n5442` giống hệt).
Nhưng mọi metric đếm node phải ghi rõ nguồn, nếu không con số không tái lập được.

### 9.3 Mẫu số của selective disclosure

35 chỉ tiêu vocabulary = TT96 (19) + QĐ2171 (1) + QCVN09 (1) + SSC-IFC (14). **GRI (32 node)
là tự nguyện, không được nằm trong mẫu số** của một metric về "chỉ tiêu bắt buộc bị bỏ qua".

- Trên 35 chỉ tiêu bắt buộc: **25 có số liệu report → 10 im lặng**
- Chỉ riêng TT96 (19): **1 im lặng** — `TT96-6.8.1 Huy động vốn xanh`

Query đúng (nêu rõ mẫu số trong mọi lần báo cáo):

```cypher
MATCH (i:StandardIndicator) WHERE i.id STARTS WITH 'TT96'
OPTIONAL MATCH (i)<-[:measuredUnder]-(k) WHERE k.source_type = 'report'
WITH i, count(k) AS n WHERE n = 0
RETURN i.id, i.pillar, i.name ORDER BY i.id
```

### 9.4 `temperature=0` và prompt gốc là bất biến của mọi phép đo

Mọi phép đo gọi LLM phải dùng `ADJUDICATE_SYSTEM` **nguyên văn** và `temperature=0`
(`test/test_esg_kg_llm.py` đã ghim hình dạng request này). Sửa prompt là đo một hệ khác, và
số cũ không so được với số mới.

---

## 10. Chi phí và thứ tự thực thi

| # | Việc | Chi phí LLM | Ra được gì |
|---|---|---|---|
| 1 | §2.3 claim trùng lặp · §5 C4 · §7 E1–E4 · §4.3 B2 hoán vị | **0** | Nhất quán, p-value, đóng góp thành phần |
| 2 | §4.2 B1 negative control | 191 | **Kill-test + lift so với ngẫu nhiên** |
| 3 | §3 MR-2, MR-4 (thuần regex, không nhiễu) | 382 | Logical soundness + kiểm chứng P8 |
| 4 | §3 MR-3, MR-6 | 382 | Định danh chủ thể, kháng nhiễu |
| 5 | §5 C1 test–retest ×3 | 573 | Krippendorff α |
| 6 | §3 MR-1, MR-5 (cần template cẩn thận) | 382 | Hiểu nội dung, ổn định ngữ nghĩa |
| 7 | §6 chạy step05d → κ hội tụ | budget riêng | Convergent validity |

**Tổng nếu làm hết mục 1–6: ~1.910 lệnh gọi ≈ 55% một lần chạy step07 gốc.**

Nếu chỉ đủ thời gian cho một việc: **làm mục 2**. Nếu đủ cho hai: **mục 1 + 2**.

---

## 11. Giới hạn trung thực của thiết kế này

1. **Không có metric nào ở đây là accuracy.** Một hệ thống có thể vượt mọi bài test ở trên
   mà vẫn sai một cách hệ thống — nếu nó sai *nhất quán* và sai *có hướng đúng*. Đây là
   trần cứng của đánh giá không nhãn, không phải khiếm khuyết của thiết kế.
2. **§3 và §5 phụ thuộc vào LLM còn truy cập được.** OpenAI hiện là provider duy nhất
   (Gemini 403 vĩnh viễn). Mất nó thì §3, §4.2, §5 C1–C2 đều dừng.
3. **§2.3 cỡ mẫu 23 nhóm** — chỉ báo bổ trợ, không phải metric chính.
4. **§4.2 B1 giả định "cặp ngẫu nhiên hầu hết vô quan"** là đúng. Với conduct pool chỉ 124
   node và phần lớn là KPI tài chính, một tỉ lệ cặp ngẫu nhiên có thể *thật sự* liên quan.
   Điều này làm specificity bị **ước lượng thấp** — tức metric thiên về phía bất lợi cho hệ
   thống. Đó là hướng thiên lệch an toàn, nhưng phải nói ra.
5. **Không metric nào ở đây cứu được vấn đề gốc**: phía conduct chỉ chiếm 2% đồ thị, và
   chưa có một `Controversy`/`Penalty` nào từ nguồn độc lập. Đánh giá tốt hơn không thay
   được dữ liệu còn thiếu.

---

## 12. Tham chiếu

**Học thuật**

- Ribeiro et al. (2020), *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList*,
  ACL — [aclanthology.org/2020.acl-main.442.pdf](https://aclanthology.org/2020.acl-main.442.pdf)
  — khung MFT / INV / DIR ở §3.1
- *Bidirectional Empowerment of Metamorphic Testing and Large Language Models: A Systematic
  Survey* — [arxiv.org/html/2605.13898v1](https://arxiv.org/html/2605.13898v1) — oracle
  problem và metamorphic relation cho LLM
- *LGMT: Logic-Grounded Metamorphic Testing for Evaluating the Reasoning Reliability of LLMs*
  — [arxiv.org/pdf/2605.23965](https://arxiv.org/pdf/2605.23965)
- *Detecting Greenwashing: A NLP Literature Survey* —
  [arxiv.org/pdf/2502.07541](https://arxiv.org/pdf/2502.07541) — xác nhận lĩnh vực **chưa có**
  dataset kiểm chứng, benchmark, hay giao thức đánh giá
- Diggelmann et al. (2020), *CLIMATE-FEVER* —
  [arxiv.org/pdf/2012.00614](https://arxiv.org/pdf/2012.00614) — mỏ neo kỳ vọng: κ giữa
  **người** chỉ 0,684; model huấn luyện trên FEVER đạt label-accuracy **38,78%** trên đó.
  Trích khi bị hỏi "sao độ chính xác thấp thế" — bài toán ở đây khó hơn (tiếng Việt, không
  gold label, evidence tự crawl)
- *RAGAS: Automated Evaluation of RAG* —
  [arxiv.org/html/2309.15217v1](https://arxiv.org/html/2309.15217v1) — họ metric
  reference-free; `faithfulness` áp được lên trường `rationale` có sẵn trong mọi dossier

**Trong repo**

- [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §1.1 — ràng buộc không-ground-truth
- [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) §3 P8, §4 Q1–Q8
- [`STANDARD_INDICATOR_AXIS.md`](./STANDARD_INDICATOR_AXIS.md) §2.5 — vì sao bác bỏ điểm
  cấp công ty
- [`CROSSCHECK_EXPANSION.md`](./CROSSCHECK_EXPANSION.md) — `kpi_gap` là ghost signal
- `SOFTMAX_SCORING.md` — `assessment_scores` **không phải** xác suất greenwashing.
  ⚠ File này hiện **không có trong working tree** (bị xoá kèm các sửa đổi chưa commit,
  2026-07-28); bản trong `git HEAD` khôi phục được bằng
  `git show a64aeb5^:docs/SOFTMAX_SCORING.md`  (file đã bị xoá khỏi repo, không còn ở HEAD)
