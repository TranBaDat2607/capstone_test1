# Chiến lược gán nhãn — cái gì được gán, cái gì bị cấm, và vì sao

> **Trạng thái: QUYẾT ĐỊNH THIẾT KẾ + ĐỀ XUẤT THI HÀNH.** Phần §1–§4 là *phân tích hiện trạng
> đã kiểm chứng trên repo* (có trích dẫn file/dòng/commit). Phần §5–§9 là *thiết kế chưa
> triển khai* — chưa có dòng code nào hiện thực chúng.
>
> **Vai trò của file này:** trả lời câu hỏi *"label trong dự án này là gì, và tôi được phép
> gán cái nào"*. Nó là tài liệu **quyết định** (why). Sổ tay thao tác cho người ngồi gán nhãn
> (how) nằm ở [`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md).
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §1.1 (ràng buộc không-ground-truth —
> gốc của mọi giới hạn dưới đây) · [`proposals/EVALUATION_WITHOUT_LABELS.md`](./proposals/EVALUATION_WITHOUT_LABELS.md)
> §1.1 (tài liệu **cấm** metric dựa trên nhãn tay — §4 giải mâu thuẫn này) ·
> [`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) (stage sinh ra thứ được gán nhãn)

---

## 0. Tóm tắt cho người bận rộn

| Câu hỏi | Trả lời ngắn |
|---|---|
| "Label" trong dự án này là gì? | **Không phải một thứ — có 5 tầng khác nhau** (§1). Chọn sai tầng là hỏng cả phần đánh giá. |
| Nên gán tầng nào? | **L4 — phán xử cặp `(claim, evidence)`** thành `supports / contradicts / irrelevant`. Đây là tầng duy nhất vừa có ý nghĩa vừa phòng thủ được. |
| Tuyệt đối không gán cái nào? | **L5 — greenwashing cấp công ty.** Bị chính `SYSTEM_DESIGN.md` §1.1 và §12 bác bỏ, không phải ý kiến cá nhân. |
| Dự án đã có nhãn tay chưa? | **Rồi — 30 case** trong `config/evaluation/ablation_cases.json`. Nhưng code đọc nó đã bị xoá 2026-07-28, file đang **mồ côi** (§3). |
| Có mâu thuẫn tài liệu không? | **Có, và phải giải trước khi gán.** `proposals/EVALUATION_WITHOUT_LABELS.md` §1.1 viết *"Đừng dùng"* metric nhãn tay. §4 phân giải: cái bị cấm là **nhãn greenwashing** và **tuyên bố accuracy**, không phải nhãn link. |
| Chặn kỹ thuật phải sửa trước | `claims_vs_conduct.py:550` **vứt bỏ** mọi verdict `irrelevant`. Không sửa thì không lấy mẫu được lớp âm ⇒ chỉ đo được precision, không đo được recall (§6). |
| Cỡ mẫu cần | **≈190 cặp** → khoảng tin cậy ±6 điểm phần trăm. 30 cặp hiện tại cho ±15 ⇒ chỉ minh hoạ (§7). |
| Câu được phát biểu | *"Tầng adjudication đồng ý với người gán ở X% (CI …), κ tự-đồng-ý 0,86"* — **không bao giờ** *"phát hiện greenwashing chính xác X%"* (§8). |

---

## 1. Năm tầng nhãn trong dự án — bảng phân định

Nguồn gây nhầm lẫn lớn nhất: chữ "label" xuất hiện ở 5 chỗ khác nhau trong pipeline, với 5
không gian nhãn khác nhau và 5 mức chính đáng khác nhau.

| # | Tầng | Đơn vị gán nhãn | Không gian nhãn | Hiện trạng trong repo | Tự gán tay? |
|---|---|---|---|---|---|
| **L1** | Phân loại câu ESG | 1 câu | `E` / `S` / `G` / `Neutral` (multi-label, sigmoid) | ViDeBERTa-v3-ESG tự gán → `data/labeled/`. `data_processing/esg_classifier.py` | ✅ Được — chỉ để **đo** classifier, cỡ mẫu nhỏ |
| **L2** | Trích xuất triple | 1 trang | triple hợp lệ / không hợp lệ theo schema | Tự động: `unfixable_triples.json` từ `build_validated` | ⚠️ Chỉ khi cần đo riêng step02 |
| **L3** | Gộp thực thể | 1 cặp entity | `same` / `different` | Stage A/B/C của `entities`; hàng `needs_review` | ✅ Khách quan cao, rẻ, ít tranh cãi |
| **L4** | **Phán xử claim ↔ conduct** | **1 cặp `(claim, evidence)`** | **`supports` / `contradicts` / `irrelevant`** | `ADJUDICATE_SYSTEM` (`claims_vs_conduct.py:156–171`) + **30 nhãn tay đã có** | ⭐ **Tầng nên làm** |
| **L5** | Greenwashing cấp công ty | 1 công ty | `greenwashing` / `not_greenwashing` | **Không tồn tại — bị bác bỏ có chủ đích** | ❌ **Cấm** |

### 1.1 Vì sao L5 bị cấm

Không phải khuyến nghị, mà là ràng buộc thiết kế đã chốt. `SYSTEM_DESIGN.md` §1.1:

- hệ thống **không phải classifier** và **không phát ra greenwashing score**;
- đầu ra là *bằng chứng + ý kiến cố vấn* (`assessment_is_advisory: true`), **không bao giờ** là phán quyết;
- §12 nêu rủi ro danh tiếng/pháp lý khi đặt tên doanh nghiệp thật cạnh một nhãn buộc tội.

Tự gán L5 nghĩa là **tự chế ra "sự thật" rồi tự chấm mình đúng theo sự thật đó**. Đó là lỗi
phương pháp không vá được bằng cỡ mẫu hay thống kê.

### 1.2 Vì sao L4 là lựa chọn đúng

L4 không hỏi *"công ty này có greenwashing không"* (câu hỏi không có oracle) mà hỏi *"cái link
bằng chứng này có đúng không"* (câu hỏi về quan hệ giữa **hai đoạn text**, có tiêu chí kiểm được).

Nó cũng là tầng duy nhất trong 5 tầng mà:

- hệ thống **đã** có một định nghĩa nhãn tường minh bằng chữ (`ADJUDICATE_SYSTEM`) để người gán bám theo;
- đã có **tiền lệ** trong chính repo (§3);
- `SYSTEM_DESIGN.md` §10 đã **dự trù sẵn** trong bảng đánh giá, dòng *"Manual link-precision"*,
  với ghi chú *"explicitly **not** accuracy vs. a greenwashing gold set"*.

---

## 2. Định nghĩa nhãn L4 — bản rút gọn

Bản đầy đủ, có cây quyết định và worked example, nằm ở
[`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md) §2–§4. Ở đây chỉ ghi ranh giới khái niệm:

| Nhãn | Nghĩa |
|---|---|
| `supports` | Bằng chứng **độc lập** củng cố đúng điều claim khẳng định (xác thực bên thứ ba, chứng nhận, chỉ số quan sát nhất quán với claim). |
| `contradicts` | Bằng chứng **nghịch** với đúng điều claim khẳng định, trong cùng kỳ (án phạt, vi phạm, bê bối, hoặc chỉ số bất lợi cùng kỳ). |
| `irrelevant` | Bằng chứng nói về chủ đề khác, hoặc là tin tài chính/thị trường trung tính, **hoặc** — quan trọng nhất — nói về *một đại lượng khác* / *một chủ thể khác* / *một kỳ khác* với claim. |

**Đơn vị gán nhãn là cặp, không phải claim.** Một claim có 5 bằng chứng ⇒ 5 dòng nhãn độc lập.

---

## 3. Tiền lệ đã có trong repo: 30 nhãn tay, hiện đang mồ côi

`config/evaluation/ablation_cases.json` — bộ gold set gán tay cho AAA:

| Nhóm | id | n | Ghi chú |
|---|---|---|---|
| `supports` | S01–S10 | 10 | tất cả `case_type=real` |
| `contradicts` | C01–C10 | 10 | tất cả `case_type=real`; C01 là worked example −42,3% doanh thu |
| `irrelevant` | IR01–IR05 | 5 | `case_type=real`, đánh dấu **HARD** — máy nói `contradicts`, người nói `irrelevant` |
| `irrelevant` | IR06–IR10 | 5 | `case_type=constructed` — **ghép nhân tạo** |

File tự khai đúng ranh giới ở §1.1:

> *"NOT a greenwashing gold set — it grades whether an evidence LINK is correct, never whether
> a company is greenwashing."*

Và `label_policy` của nó đã ghi sẵn nguyên tắc *strict-independence* mà §2 ở trên kế thừa:

> *"an evidence item must speak to the SAME thing the claim asserts."*

**Kết quả đã đo được trên bộ này** (`SYSTEM_DESIGN.md` §11, hàng P6): baseline keyword **73,3%**
vs LLM **76,7%** đồng ý với nhãn người — LLM bắt hết mâu thuẫn số học nhưng **over-reach trên
đúng 5 case `irrelevant` HARD**.

### 3.1 Trạng thái hiện tại: mồ côi

Code duy nhất đọc file này là `src/step10_evaluate.py`, **đã bị xoá 2026-07-28**
(commit `a64aeb5`, "chore: complete the step10 removal cleanup"). Kiểm bằng grep toàn repo:
file chỉ còn được nhắc ở 2 dòng văn xuôi trong `SYSTEM_DESIGN.md` (§11 và §13.2), **không dòng
code nào đọc nó**.

**Quyết định cần chốt trước khi làm gì tiếp:** hồi sinh bộ 30 case này làm hạt giống, hay bỏ và
xây mới. Khuyến nghị: **hồi sinh làm hạt giống nhưng migrate sang định dạng mù** (§5.1) — 30 case
đã gán là công sức thật, và 5 case HARD là tài sản chẩn đoán quý nhất trong đó.

### 3.2 Ba khiếm khuyết của bộ 30 case (phải sửa khi mở rộng)

1. **Không mù.** Nhãn người, verdict máy và `note` giải thích nằm chung một file. Người gán
   lượt sau nhìn thấy đáp án cũ ⇒ mọi phép đo lặp lại đều nhiễm.
2. **Lớp `irrelevant` một nửa là bịa.** 5/10 case là `case_type=constructed` — ghép nhân tạo,
   vì lý do ở §6.
3. **Cỡ mẫu 30 ⇒ khoảng tin cậy ±15 điểm phần trăm.** Đủ minh hoạ, không đủ kết luận (§7).

---

## 4. ⚠️ Giải mâu thuẫn với `proposals/EVALUATION_WITHOUT_LABELS.md`

Đây là mục quan trọng nhất của tài liệu. Hai file trong repo đang nói ngược nhau.

**`proposals/EVALUATION_WITHOUT_LABELS.md` §1.1 viết:**

> *"Tác giả tự gán nhãn là không khách quan — và sẽ bị hội đồng chất vấn đúng chỗ đó."*
> *"Ràng buộc 2 và 3 loại bỏ toàn bộ nhóm metric dựa trên mẫu gán nhãn tay: link precision,
> Cohen's κ người–người, κ người–LLM, recall vét cạn. **Đừng dùng chúng.**"*

### 4.1 Phân giải

Đọc kỹ thì cái bị bác bỏ là **hai thứ cụ thể**, không phải "gán nhãn tay" nói chung:

| Bị bác bỏ | Vẫn hợp lệ |
|---|---|
| (a) Gán nhãn **greenwashing** (L5) | Gán nhãn **tính đúng của link** (L4) |
| (b) Dùng mẫu **một người tự gán** để tuyên bố **accuracy của hệ thống** | Dùng mẫu gán nhãn làm **công cụ chẩn đoán, ablation và đối chứng**, phát biểu kèm giới hạn |

Câu bị cấm: *"hệ thống chính xác 78%"*.
Câu được phép: *"trên 190 cặp gán mù, tầng adjudication lệch với người gán ở 22% số ca, và 5 chế
độ hỏng lặp lại là …"*.

Câu thứ hai mới là thứ có giá trị học thuật — nó **mô tả hỏng ở đâu**, thứ mà không metric
không-nhãn nào ở `proposals/EVALUATION_WITHOUT_LABELS.md` §3–§7 làm được.

### 4.2 Điều kiện để phân giải này đứng vững

Không phải cứ đổi cách phát biểu là xong. Ràng buộc *"tác giả tự gán không khách quan"* là **thật**
và phải vá bằng **giao thức đo được**, không phải bằng lời hứa "tôi cẩn thận":

| Vá | Biến điểm yếu thành | Chi tiết trong [`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md) |
|---|---|---|
| Gán **mù** (không thấy verdict máy) | loại bỏ anchoring | quy tắc R5 (§5) + định dạng đề bài (§7.1) |
| Gán **2 lượt cách ≥3 ngày** → κ tự-đồng-ý | một **con số** thay cho lời tuyên bố về sự cẩn thận | §6.2, tính bằng script §8 |
| **Freeze guideline trước khi gán** | chặn p-hacking hậu nghiệm | header + nhật ký phiên bản §10 |
| Mượn **annotator thứ 2** cho 60 case → κ người–người | trả lời trực diện lời chất vấn §1.1 | §6.3 |

**Với 4 điều này, `proposals/EVALUATION_WITHOUT_LABELS.md` §1.1 ràng buộc 2 và 3 không còn áp dụng nguyên
vẹn** — ràng buộc 2 ("không có chuyên gia gán nhãn") được hạ xuống thành "có annotator thứ hai
không chuyên, κ được báo cáo", và ràng buộc 3 ("tự gán không khách quan") được thay bằng một
khoảng tin cậy có κ đi kèm. Phải ghi rõ sự thay đổi này vào `proposals/EVALUATION_WITHOUT_LABELS.md` §8
(bảng "metric đã chết") khi bộ nhãn hoàn thành, nếu không hai file lại lệch nhau lần nữa.

### 4.3 Quan hệ với thiết kế không-nhãn — bổ sung, không thay thế

Bộ nhãn L4 **không thay thế** §3–§7 của `proposals/EVALUATION_WITHOUT_LABELS.md`. Nó bổ sung theo hai hướng:

- **Metamorphic test (§3 file kia)** đo *tính nhất quán logic* — hệ có tự mâu thuẫn không. Bộ nhãn
  đo *tính đúng của link*. Hai đại lượng khác nhau, không thay nhau được.
- **Negative control (§4.2 file kia)** hiện **giả định** cặp ngẫu nhiên hầu hết vô quan, và §11.4
  tự thừa nhận đó là điểm yếu (*"một tỉ lệ cặp ngẫu nhiên có thể thật sự liên quan"*). Gán nhãn tay
  cho chính tầng cặp ngẫu nhiên (§6, tầng 5) **biến giả định thành số đo** ⇒ nâng cấp thẳng metric
  mạnh nhất của file kia.

---

## 5. Thiết kế bộ nhãn

### 5.1 Nguyên tắc: tách đề bài khỏi đáp án

```
config/evaluation/
  ablation_cases.json                     # DI SẢN — 30 case, giữ nguyên, không sửa
  gold_links_aaa_items.jsonl              # ĐỀ BÀI — tuyệt đối không chứa trường nhãn nào
  gold_links_aaa_labels_<annotator>_p1.jsonl   # đáp án lượt 1
  gold_links_aaa_labels_<annotator>_p2.jsonl   # đáp án lượt 2
  gold_links_aaa_final.jsonl              # sau adjudication — bộ dùng để đo
```

Lý do tách: bộ 30 case cũ **không thể** dùng để đo lại vì nhãn nằm cùng file với đề (§3.2).
Tách ra là điều kiện cần để mọi phép đo lặp lại còn giá trị.

Schema từng dòng và ý nghĩa từng trường: [`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md) §7.

### 5.2 Ràng buộc kiểm tự động (TDD — `CLAUDE.md` bắt buộc)

Theo quy tắc TDD của repo, **viết `test/test_gold_links.py` trước, chạy, thấy fail, rồi mới sinh
dữ liệu**. Test phải khẳng định:

| # | Khẳng định | Bắt lỗi gì |
|---|---|---|
| 1 | `gold_links_aaa_items.jsonl` **không chứa** bất kỳ trường nào trong `{label, label_pass1, label_pass2, label_final, reference_verdict, verdict, confidence, rationale, note}` | **Rò rỉ đáp án** — test quan trọng nhất |
| 2 | Mọi nhãn ∈ `{supports, contradicts, irrelevant}` | Nhãn gõ sai / lớp thứ 4 |
| 3 | `id` duy nhất; cặp `(claim_id, evidence_key)` duy nhất | Gán trùng ⇒ thổi phồng n |
| 4 | Mọi `claim_id` tồn tại trong dossier | Cặp bịa / lệch phiên bản artifact |
| 5 | Không lớp nào < 10% mẫu | Phân bố suy biến ⇒ κ vô nghĩa |
| 6 | Số dòng `_p1` == `_p2` == `_items` | Gán thiếu lượt |

Test chạy offline, plain `assert`, exit non-zero khi fail, chạy từ repo root — đúng khuôn
`test/test_temporal_invariants.py`.

---

## 6. ⚠️ Chặn kỹ thuật: verdict `irrelevant` đang bị vứt bỏ

**Phát hiện khi đọc code.** `src/esg_kg/crosscheck/claims_vs_conduct.py:550`:

```python
if v not in ("supports", "contradicts"):   # irrelevant → adjudicated, no edge
    continue
```

Verdict `irrelevant` **được LLM trả về và đã trả tiền**, nhưng bị bỏ qua — không vào dossier,
không vào cạnh, không vào file nào.

### 6.1 Hệ quả

Theo `proposals/EVALUATION_WITHOUT_LABELS.md` §2.2 (đo 2026-07-28 — **kiểm lại trên artifact hiện tại
trước khi lấy mẫu**):

- 3.461 cặp ứng viên được phán xử;
- chỉ **191** cặp `supports`/`contradicts` + **18** cặp `flagged_support` còn dấu vết trên đĩa;
- ⇒ khoảng **3.250 verdict `irrelevant` bốc hơi**.

Ba hệ quả trực tiếp lên việc gán nhãn:

1. **Không lấy mẫu ngẫu nhiên từ tập quyết định thật được** — chỉ còn lấy được từ positives.
2. Đó chính là lý do bộ 30 case cũ phải **bịa** `case_type=constructed` cho một nửa lớp `irrelevant`.
3. Gán nhãn chỉ trên positives ⇒ **chỉ đo được precision, mù hoàn toàn về recall**, và mọi con
   số đều thiên vị lên.

### 6.2 Sửa

Thêm đường ghi **toàn bộ** verdict (kể cả `irrelevant`) ra
`graph_output/crosscheck/<ticker>_adjudications.jsonl`, mỗi dòng: `claim_node_index`,
`claim_id`, `evidence_node_index`, `verdict`, `confidence`, `rationale`, `provider`,
`retrieval_tier`.

Khoảng 5 dòng code, **không tốn thêm tiền** nếu ghép vào lần chạy `claims_vs_conduct` kế tiếp.
Đây là việc phải làm **trước** khi lấy mẫu — không có nó thì tầng 4 và 5 của bảng §6.3 không tồn tại.

### 6.3 Lấy mẫu phân tầng

Số liệu nguồn theo `proposals/EVALUATION_WITHOUT_LABELS.md` §2.2 — **kiểm lại trước khi chạy**.

| Tầng | Nguồn | Có sẵn | Lấy | Đo được gì |
|---|---|---|---|---|
| 1 | `llm_supports` (độc lập) | 166 | 55 | Precision của `supports` |
| 2 | `llm_contradicts` | 25 | **lấy hết 25** | Lớp hiếm nhất, quý nhất — tín hiệu chính của đề tài |
| 3 | `llm_flagged_support` (guard chặn) | 18 | **lấy hết 18** | Guard tự-xác-thực có đúng không |
| 4 | `irrelevant` — cần §6.2 | ~3.250 | 60 | **Recall** — máy bỏ sót bằng chứng thật nào |
| 5 | Cặp ngẫu nhiên retrieval **không** chọn | sinh offline | 32 | Negative control **có nhãn** (nâng cấp §4.2 file kia) |
| | | | **≈190** | |

Ghi chú lấy mẫu:

- Tầng 2 và 3 **lấy toàn bộ**, không lấy mẫu — quần thể đã nhỏ hơn cỡ mẫu mong muốn.
- Tầng 1 và 4 lấy **ngẫu nhiên có seed cố định**, ghi seed vào file để tái lập.
- Tầng 5 sinh offline, không tốn LLM: lấy cặp `(claim, conduct)` bất kỳ **không** nằm trong
  3.461 cặp ứng viên.
- **Xáo trộn toàn bộ trước khi ghi `_items.jsonl`** để người gán không đoán được tầng từ vị trí.

---

## 7. Cỡ mẫu

Khoảng tin cậy Wilson 95% quanh tỉ lệ đồng ý, tính tại `p ≈ 0,78`:

| n | Nửa khoảng ± | Đánh giá |
|---|---|---|
| 30 (bộ hiện có) | ±15 điểm % | Chỉ minh hoạ. **Không kết luận được gì** |
| 100 | ±8 điểm % | Tối thiểu chấp nhận được |
| **190** | **±6 điểm %** | ⭐ **Khuyến nghị** — cân bằng công sức / độ chặt |
| 400 | ±4 điểm % | Quá sức một capstone |

Công ước tính: ~45–75 giây/cặp sau khi quen tay ⇒ 190 cặp ≈ 3–4 giờ/lượt, hai lượt ≈ 7–8 giờ,
cộng ~1 giờ adjudication. Khả thi trong một tuần làm việc rời rạc.

**Luôn báo cáo cỡ mẫu và khoảng tin cậy cùng con số.** *"78%"* trần trụi không phòng thủ được;
*"78% (CI 72–83%, n=190)"* thì được.

---

## 8. Phát biểu được gì / không được phát biểu gì

### ✅ Được

- *"Trên 190 cặp gán nhãn mù, tầng adjudication đồng ý với người gán ở 78% (Wilson CI 72–83%);
  κ tự-đồng-ý của người gán là 0,86; κ với annotator thứ hai trên 60 case là 0,71."*
- *"So với baseline keyword, tầng LLM cải thiện X điểm phần trăm (McNemar exact, p = …)."*
- *"Năm chế độ hỏng lặp lại: lệch cửa sổ thời gian, nhầm đại lượng, nhầm chủ thể (chỉ số toàn
  ngành vs của công ty), phủ định kép trong mục rủi ro, và …"*
- *"Trên 32 cặp ngẫu nhiên gán nhãn tay, specificity thật của adjudicator là …"* (nâng cấp §4.2
  của `proposals/EVALUATION_WITHOUT_LABELS.md` từ giả định thành số đo).

### ❌ Không được

- *"Hệ thống phát hiện greenwashing chính xác 78%"* — không nhãn greenwashing nào tồn tại.
- Bất kỳ câu nào ghép chữ **accuracy** với **greenwashing**.
- *"Công ty X greenwashing"* / *"không greenwashing"* — dù bộ nhãn có đẹp đến đâu.
- Suy ra kết luận cấp công ty từ nhãn cấp cặp. Chúng là hai tầng khác nhau, và §1.1 chỉ cho phép
  tầng dưới.

---

## 9. Lộ trình thi hành

| # | Việc | Chi phí | Chặn cái gì |
|---|---|---|---|
| 1 | Chốt số phận `ablation_cases.json` (hồi sinh làm hạt giống — khuyến nghị §3.1) | 0 | Toàn bộ |
| 2 | Freeze + commit [`ANNOTATION_GUIDELINE.md`](./ANNOTATION_GUIDELINE.md) | 0 | Bước 5 (freeze trước khi gán, §4.2) |
| 3 | Patch dump `irrelevant` verdict (§6.2) | ~5 dòng code | Tầng 4 + 5 của mẫu |
| 4 | Viết `test/test_gold_links.py` **trước** (§5.2), rồi sinh `_items.jsonl` phân tầng | 0, offline | Bước 5 |
| 5 | Gán lượt 1 → nghỉ ≥3 ngày → lượt 2 → tính κ tự-đồng-ý | ~8 giờ người | Bước 7 |
| 6 | Annotator thứ 2 gán 60 case → κ người–người | ~1,5 giờ người khác | — |
| 7 | Adjudication bất đồng → `gold_links_aaa_final.jsonl` → commit | ~1 giờ | — |
| 8 | Cập nhật `proposals/EVALUATION_WITHOUT_LABELS.md` §8 để hai file hết lệch (§4.2) | 0 | Tính nhất quán tài liệu |

**Nếu chỉ đủ thời gian cho một việc:** bước 3 + 4 — vì không có chúng thì bộ nhãn sinh ra đã
thiên vị ngay từ khâu lấy mẫu, và không giao thức gán nhãn nào cứu được điều đó về sau.

---

## 10. Giới hạn trung thực của thiết kế này

1. **Nhãn L4 không phải nhãn greenwashing, và không suy ra được nhãn greenwashing.** Một hệ thống
   có link chính xác 100% vẫn có thể vô dụng cho việc phát hiện greenwashing nếu kho bằng chứng
   quá mỏng — mà nó đang mỏng thật (phía conduct chiếm ~2% đồ thị).
2. **Một annotator chính vẫn là một annotator chính.** κ tự-đồng-ý cao chứng minh *tính nhất quán*,
   không chứng minh *tính đúng*. Annotator thứ hai giảm nhẹ chứ không xoá được giới hạn này.
3. **Mẫu chỉ cho AAA.** Mọi con số là của một công ty, không suy rộng ra 115 công ty trong
   `config/company_annual_report.xlsx`.
4. **Nhãn gắn với một snapshot dữ liệu.** Ghi revision trong `data_version.json` vào file nhãn;
   một lần re-extraction làm đổi `claim_id` (GitHub issue #2 chưa xong) có thể làm mồ côi bộ nhãn
   đúng như cách `ablation_cases.json` bị mồ côi (§3.1). Đây là rủi ro **đã xảy ra một lần** trong
   dự án này — đừng để lặp lại.
5. **Tầng 5 (cặp ngẫu nhiên) có thể chứa cặp thật sự liên quan.** Conduct pool chỉ 124 node nên
   xác suất trùng chủ đề không nhỏ. Điều này làm specificity bị **ước lượng thấp** — thiên lệch
   theo hướng bất lợi cho hệ thống, tức là an toàn, nhưng phải nói ra.

---

## 11. Tham chiếu

**Trong repo**

- [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §1.1 (không-ground-truth), §10 (hàng *Manual
  link-precision*), §11 P6, §12 (giới hạn & đạo đức)
- [`proposals/EVALUATION_WITHOUT_LABELS.md`](./proposals/EVALUATION_WITHOUT_LABELS.md) §1.1 (ràng buộc bị phân giải ở
  §4), §2.2 (số liệu nguồn của §6.3), §4.2 (negative control được nâng cấp), §8 (bảng metric đã chết)
- [`proposals/AGENT_AB_EVALUATION.md`](./proposals/AGENT_AB_EVALUATION.md) §3.3 (pre-registration — cơ sở của "freeze
  guideline"), §2 (bẫy nới lỏng)
- [`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) — stage sinh ra cặp được gán nhãn
- `config/evaluation/ablation_cases.json` — 30 case tiền lệ
- `src/esg_kg/crosscheck/claims_vs_conduct.py:156–171` (`ADJUDICATE_SYSTEM`), `:550` (chỗ vứt
  `irrelevant`)
- `CLAUDE.md` — quy tắc TDD, quy ước `test/`, `data_version.json`

**Học thuật**

- Diggelmann et al. (2020), *CLIMATE-FEVER* — [arxiv.org/pdf/2012.00614](https://arxiv.org/pdf/2012.00614)
  — cùng không gian nhãn 3 lớp (SUPPORTS/REFUTES/NOT_ENOUGH_INFO); 5 annotator/cặp + majority vote;
  κ **người–người chỉ 0,684** trên nhiệm vụ tương tự ⇒ mỏ neo kỳ vọng khi κ của bạn không cao
- Stammbach et al. (2023), *Environmental Claim Detection*, ACL —
  [aclanthology.org/2023.acl-short.91](https://aclanthology.org/2023.acl-short.91/) — 2.647 mẫu,
  16 chuyên gia trong ngành, guideline tường minh + adjudication: khuôn mẫu cho §5
- Thorne et al. (2018), *FEVER* — [arxiv.org/pdf/1803.05355](https://arxiv.org/pdf/1803.05355) —
  khung annotation gốc của bộ ba nhãn
- Artstein, *Inter-annotator Agreement* — [apps.dtic.mil/sti/pdfs/AD1158943.pdf](https://apps.dtic.mil/sti/pdfs/AD1158943.pdf)
  — cơ sở cho κ tự-đồng-ý và κ người–người
- *Detecting Greenwashing: A NLP Literature Survey* — [arxiv.org/pdf/2502.07541](https://arxiv.org/pdf/2502.07541)
  — xác nhận lĩnh vực **chưa có** dataset greenwashing đã kiểm chứng ⇒ §1.1 không phải thiếu sót của đề tài
