# Kết quả gán nhãn mù — độ đồng thuận và precision của adjudicator

> **NGUỒN CHUẨN LÀ `evalu/`** (nay đã ở trong repo này, không còn phải kéo riêng từ nhánh
> `wip/gri-parser-and-eval` — xem commit `bb7093b`), không phải file này.
> `evalu/annotation.py` (dựng phiếu + `score()`), `evalu/iaa.py` (độ đồng thuận),
> `evalu/ANNOTATION_PROTOCOL.md` (protocol, cố định trước khi nhìn kết quả).
> File này chỉ tóm tắt số đã chạy ra trên phiên **226/200-cặp gốc** và ghi lại các
> bẫy diễn giải. **Đừng tự tính lại bằng tay** — bản tự dựng lại đầu tiên đã sai đúng ba
> chỗ, ghi ở §6.
>
> ⚠️ **2026-08-13 (issue #17):** `sheetA.xlsx`/`sheetB.xlsx`/`sheetC.xlsx` đã bị xoá khỏi
> working tree — luận văn nay chỉ báo cáo phiên chấm **43-cặp mới nhất** (dossier hiện tại,
> sau bản vá P1 2026-08-13), không còn dùng số của phiên 226/200-cặp này nữa. Số liệu
> BÊN DƯỚI vẫn là **bản ghi lịch sử đúng, không đổi** — chỉ là ba file nguồn không còn nằm
> sẵn trên working tree. Khôi phục nếu cần: `git show bb7093b:sheetA.xlsx > sheetA.xlsx`
> (tương tự cho `sheetB.xlsx`/`sheetC.xlsx`). Phiên 43-cặp mới có nguồn tái tạo riêng:
> `sheetA_43pairs_filled.xlsx` / `sheetB_43pairs_filled.xlsx` + `evalu/score_census_43.py`.
> `notebooks/eda/annotation_agreement.py` đã bị xoá cùng đợt này — xem §6.
>
> ```bash
> python evalu/run_evaluation.py --score-annotation evalu/out/annotation/sheet_A.json \
>     --filled sheetA.xlsx sheetB.xlsx
> ```

---

## 1. Phiếu gồm những gì

| | |
|---|---|
| Tổng thể | **226** cặp hệ thống đã trích dẫn (99 supporting + 127 contradicting), 5 mã CK |
| Mẫu | **200** (88,5%), phân tầng theo (mã × loại phán quyết), seed 42 |
| Cặp bẫy | **20** — attention check, **không** tính vào precision |
| Tổng dòng phải chấm | **220** |
| Người chấm | **hai chuyên gia ngoài nhóm tác giả**, mỗi người đủ 220/220 — xem §1a |
| `sheetC.xlsx` | cùng template, chưa chấm |
| `llm_current_pairs.xlsx` | **toàn bộ 226 cặp** — bản census, không phải template khác |

Điều kiện mù được **cưỡng chế bằng code**: `build_sheet` chỉ dựng dòng từ danh sách trắng
`DISPLAY_FIELDS`, `test_sheet_is_blind` đỏ nếu có trường nào rò rỉ phán quyết của hệ.

## 1a. Ai đã chấm — và vì sao điều này thay đổi vị thế của kết quả

| Phiếu | Người chấm | Chức danh | Vì sao năng lực liên quan |
|---|---|---|---|
| `sheetA` | **Thái Anh Tuấn** | Tổng Giám đốc, Phúc Lộc Group | Điều hành doanh nghiệp xây dựng thuộc đúng ngành của bộ dữ liệu; là người ký duyệt chính loại công bố mà hệ thống này đánh giá |
| `sheetB` | **Đỗ Kim Ngọc** | Giám đốc khối Khách hàng Doanh nghiệp, VPBank | Thẩm định doanh nghiệp vay vốn trong ngành này hằng ngày; nghề nghiệp là đối chiếu điều doanh nghiệp tự nói với bằng chứng độc lập |

Cả hai **độc lập với nhóm tác giả** và độc lập với nhau. Điều này giải toả hai ràng buộc mà
toàn bộ khung đánh giá không-nhãn được dựng quanh (`EVALUATION_WITHOUT_LABELS.md` §1.1):
*"không có chuyên gia gán nhãn"* và *"tác giả tự gán nhãn thì không khách quan"*.

> ⚠️ **Hai điều bắt buộc phải giữ.**
> 1. Đây **vẫn không phải** hội đồng CEO/HRD/Kiểm toán trong `evalu/rubric.py` — đó là công
>    cụ khác (rubric Likert 4 chiều, đồng thuận có trọng số theo chuyên môn) và **chưa hề
>    được thực hiện**. Việc một người chấm đang là Tổng Giám đốc không biến phiên này thành
>    hội đồng đó. Cảnh báo ở `ANNOTATION_PROTOCOL.md` §7 về chỗ này vẫn nguyên hiệu lực.
> 2. `ANNOTATION_PROTOCOL.md` §7 đang bắt buộc khai báo là *"annotation mù của tác giả"* —
>    **câu đó nay sai sự thật** và cần một phụ lục ghi nhận nguồn gốc thật. Quy tắc freeze
>    cấm đổi **tiêu chí**, không cấm ghi nhận **ai đã chấm**. Phụ lục đó chưa được thêm vì
>    file nằm trên nhánh `wip/gri-parser-and-eval`, chưa merge.
>
> Nêu đích danh trong luận văn cần **văn bản đồng ý của cả hai** — luận văn là tài liệu công khai.

**Attention check:** ngưỡng huỷ phiên là **> 3/20** cặp bẫy bị chấm thành supports/contradicts.
Thực tế **2/20 ở cả hai người** → phiên chấm **hợp lệ**. (Đáng chú ý: hai người trượt đúng
cùng 2 cặp — nhiều khả năng 2 cặp "bẫy" đó tình cờ liên quan thật, đúng như `_make_decoys`
tự dè chừng khi viết "near-certainly irrelevant".)

---

## 2. Độ đồng thuận — **báo cáo trên 200 cặp thật, không phải 220**

Cặp bẫy quá dễ (hai người đồng ý 20/20), nên để chung sẽ thổi phồng mọi chỉ số.

| Trường | n | Gwet AC1 | Krippendorff α | Cohen κ | Kết luận |
|---|---|---|---|---|---|
| `relation` | 200 | **0,818** | 0,696 | 0,698 | ✅ đạt ngưỡng *substantial* |
| `about_claim_company` | 200 | **0,480** | 0,346 | 0,401 | ❌ **không đạt** |
| *(cùng số, gồm cả bẫy)* | 220 | 0,837 | 0,712 | 0,714 | — chỉ để đối chiếu |

Protocol §6.4 yêu cầu **Gwet AC1 và Krippendorff α** làm số headline, không phải Cohen κ.

> ⚠️ **Cột `about_claim_company` không được mang một con số nào vào luận văn.** AC1 = 0,480
> là *moderate*, dưới ngưỡng. Hai người trả lời "Yes" 105 vs 42 lần trên cùng một tập.

---

## 3. Precision (`evalu.annotation.score`)

| | Người chấm A | Người chấm B |
|---|---|---|
| `precision.overall` | **26,5 %** (53/200) | **35,0 %** (70/200) |
| — theo `supporting_evidence` | 52,3 % (45/86) | 69,8 % (60/86) |
| — theo `contradicting_evidence` | **7,0 %** (8/114) | **8,8 %** (10/114) |
| `precision.same_company_only` | **55,8 %** (53/95) | **56,8 %** (21/37) |
| `attribution_validation` | 81,5 % (163/200) | 88,5 % (177/200) |

**Không có recall.** Cặp bị adjudicator gán `irrelevant` không bao giờ được ghi vào hồ sơ
(`claims_vs_conduct.py`), nên không có cách nào biết hệ bỏ sót gì. Nêu recall là overclaim.

---

## 4. Nửa "sau khi vá" **đã có sẵn** — hai đường độc lập

Bản vá `7c108f9` (2026-08-07) sửa ba thứ: khoanh conduct pool theo issuer, tokenize VN +
cổng `min-topic-overlap`, siết `ADJUDICATE_SYSTEM` chống halo reasoning. Tác động đã đo được
mà **không cần chấm lại và không tốn tiền**:

1. **`precision.same_company_only`** — giới hạn ở các cặp người chấm đánh là *đúng doanh
   nghiệp*. Đây chính là ước lượng precision sau khi vá, tính được từ đúng phiên chấm này
   **vì bản vá chỉ loại bớt cặp, không thêm cặp mới**: 26,5% → 55,8% (A), 35,0% → 56,8% (B).
2. **NC.1 / NC.2** — từ **28,76 % FAIL → 100 % PASS**, `cross_feed = 0`
   (`evalu/out/1.text`, `evalu/out/evaluation_report_nc_postfix.md`).

Cần biết khi lập kế hoạch: hồ sơ **sau khi vá** hiện chỉ còn **24** cặp bằng chứng được
trích dẫn (so với 226 trước khi vá). Hệ sau khi vá dè dặt hơn rất nhiều — nên một phiên
chấm census sau khi vá sẽ chỉ có ~24 dòng, không phải 226.

> **Cập nhật 2026-08-13:** một bản vá riêng (P1, salt cache key) đưa số cặp trích dẫn lên
> **43** (37 supporting + 6 contradicting), không phải 24. Phiên census 43-cặp đó đã được
> chấm mù thật (không phải dự đoán như đoạn trên) — kết quả nằm trong
> `capstone_report/main.tex` §4.4, tái tạo bằng `evalu/score_census_43.py`, không phải ở
> file này.

---

## 5. Cái tập nhãn này KHÔNG chấm điểm được

**Không dùng `sheetA`/`sheetB` để chấm hai nhánh trong `graphrag_vs_rag.xlsx`.** Ba file
chung 220 `pair_id` và chung `evidence_text`, nhưng hai nhánh truy hồi ra **loại đối tượng
khác nhau**: `sheetA.claim_text` khớp `graph_claim` 37/220 và `rag_claim` 1/220. Nhánh graph
xếp hạng trên **node `SustainabilityClaim`** của đồ thị; nhánh RAG xếp hạng trên **câu ESG
thô** trong `esg_all_records.jsonl`. Muốn so về tính đúng thì phải mở một phiên chấm mới
trên chính `graph_claim` và `rag_claim`.

---

## 6. Ba lỗi của bản tự dựng lại đầu tiên — ghi lại để không lặp

Trước khi `evalu/` được đẩy lên, bản phân tích đầu tiên (nối ngược qua
`adjudication_cache_openai*.json`) đã sai ba chỗ, tất cả đều theo hướng **tự tin quá mức**:

| Sai | Đúng |
|---|---|
| κ = 0,714 trên 220 dòng | 220 gồm **20 cặp bẫy**; số đúng là AC1 = 0,818 / κ = 0,698 trên **200** |
| "Nửa sau khi vá còn thiếu, phải chạy lại tốn tiền" | Đã có sẵn hai đường, xem §4 |
| Sau đó lại sửa quá đà thành "annotation mù của **tác giả**" | Cũng sai — người chấm là **hai chuyên gia ngoài**, xem §1a. Lần đầu tôi gọi "gold standard" là quá mạnh; lần sau tôi tin protocol §7 hơn thực tế và hạ xuống quá thấp |

Bài học: **repo có sẵn package đánh giá thì đọc nó trước khi tự tính.** Bản tự dựng lại tái
tạo được phần dễ (khớp gần đúng precision theo loại: 7,0% vs 6,2%) nhưng bỏ sót cặp bẫy,
ngưỡng huỷ phiên, và đúng chỉ số mà protocol yêu cầu.

`notebooks/eda/annotation_agreement.py` là bản tự dựng đó, giữ lại vì lúc viết `evalu/`
chưa merge vào `main`. `evalu/` nay đã có sẵn trong repo và là công cụ dùng thật
(`evalu/score_census_43.py` cho phiên 43-cặp) — file tự dựng đã bị xoá 2026-08-13, đúng
kế hoạch ghi ở trên.
