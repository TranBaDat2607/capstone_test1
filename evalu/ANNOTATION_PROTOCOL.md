# Protocol Annotation Mù — Đối soát Claim ↔ Bằng chứng

**Phiên bản 1.0 — cố định trước khi nhìn bất kỳ kết quả nào.**

Tài liệu này phải được viết xong *trước* buổi chấm. Nếu sau khi thấy kết quả mà
tiêu chí bị sửa, toàn bộ phép đo mất giá trị và phải chấm lại từ đầu với mẫu mới.

---

## 1. Mục tiêu

Không tồn tại nhãn chuẩn (gold standard) về greenwashing cho doanh nghiệp niêm
yết Việt Nam. Vì vậy hệ thống **không thể** báo cáo precision so với sự thật.

Nó **có thể** báo cáo precision so với một annotation của con người, mù và tái
lập được, trên chính đầu ra của nó. Đó là mục tiêu duy nhất của protocol này.

**Đo được:** precision của các phán quyết dương tính (`supports` / `contradicts`).

**KHÔNG đo được:** recall. Các cặp bị adjudicator gán `irrelevant` không hề được
ghi vào hồ sơ (`claims_vs_conduct.py` dòng 614), nên không có cách nào biết hệ
thống đã bỏ sót bằng chứng nào. Nêu bất kỳ con số recall nào là overclaim.

---

## 2. Tổng thể và cỡ mẫu

| | |
|---|---|
| Đơn vị phân tích | một cặp (tuyên bố, bằng chứng) hệ thống đã trích dẫn |
| Tổng thể | **226** cặp (99 supporting + 127 contradicting) trên 5 mã CK |
| Cỡ mẫu | **200** (88,5% tổng thể) |
| Cách lấy | phân tầng theo (mã CK × loại phán quyết), tối thiểu 1 cặp/tầng |
| Seed | **42** — cố định, tái lập được bằng `--seed 42` |
| Cặp bẫy | **20** trộn thêm (xem §5), không tính vào precision |
| Tổng số dòng phải chấm | **220** |

> Với `--n-pairs 226` thì thành **census** — sai số lấy mẫu bằng 0, và phát biểu
> mạnh hơn: "chúng tôi annotate toàn bộ bằng chứng hệ thống trích dẫn". Chỉ tốn
> thêm 26 dòng.

Lệnh sinh phiếu:

```bash
python evalu/run_evaluation.py --make-annotation --n-pairs 200 --decoys 20 --seed 42
```

---

## 3. Điều kiện mù

Người chấm **chỉ** nhìn thấy 6 cột: `pair_id`, `claim_company`, `claim_text`,
`evidence_text`, `evidence_kind_label`, `evidence_date`.

Người chấm **không** nhìn thấy: kết luận của hệ thống, loại phán quyết, mã CK
của bằng chứng, điểm tin cậy, lập luận của LLM, hay bất cứ gì cho biết cặp này
là thật hay bẫy.

Điều kiện này được **cưỡng chế bằng code**, không phải bằng kỷ luật: `build_sheet`
dựng mỗi dòng từ đúng danh sách trắng `DISPLAY_FIELDS`, và
`test_evalu_annotation.py::test_sheet_is_blind` sẽ đỏ nếu có trường nào rò rỉ.

**Cấm tuyệt đối trong lúc chấm:** mở `graph_output/crosscheck/`, mở giao diện
ESG Evidence View, hoặc tra `pair_id` ở bất kỳ đâu.

---

## 4. Định nghĩa nhãn

Với mỗi dòng, điền **2 cột**.

### Cột `relation` — bằng chứng nói gì về tuyên bố?

| Nhãn | Khi nào chọn |
|---|---|
| `supports` | Bằng chứng khẳng định, xác nhận, hoặc cung cấp số liệu **phù hợp** với nội dung tuyên bố. |
| `contradicts` | Bằng chứng phủ định, mâu thuẫn, hoặc cung cấp số liệu **trái ngược** với tuyên bố. |
| `irrelevant` | Bằng chứng không liên quan, hoặc chỉ trùng chủ đề chung chung mà không nói gì về nội dung cụ thể của tuyên bố. |

**Quy tắc thận trọng:** phân vân giữa `supports` và `irrelevant` → chọn
`irrelevant`. Phân vân giữa `contradicts` và `irrelevant` → chọn `irrelevant`.
Quy tắc này lệch về phía *bất lợi cho hệ thống*, để precision báo cáo là cận dưới
chứ không phải cận trên.

**Các ca đã quyết trước:**

- Bằng chứng chỉ *trùng chủ đề* (cùng nói về "phát thải") nhưng không xác nhận
  hay phủ định điều tuyên bố nói → `irrelevant`.
- Tuyên bố hướng tương lai ("cam kết đến 2050") + bằng chứng về hiện tại →
  `supports` chỉ khi bằng chứng cho thấy tiến độ thực hiện đúng cam kết đó;
  ngược lại `irrelevant`.
- Bằng chứng nói về công ty khác → vẫn chấm `relation` bình thường theo nội dung,
  rồi đánh `about_claim_company = false`. **Không** tự động chọn `irrelevant` chỉ
  vì sai công ty — hai câu hỏi phải độc lập, nếu không thì §6 mất ý nghĩa.

### Cột `about_claim_company` — bằng chứng có nói về đúng doanh nghiệp không?

`true` nếu bằng chứng nói về doanh nghiệp ghi ở cột `claim_company`.
`false` nếu nói về doanh nghiệp khác, hoặc nói chung chung không rõ doanh nghiệp nào.

Chỉ căn cứ vào phần text hiển thị. Không tra Google.

### Cột `note`

Tuỳ chọn. Ghi lại ca khó để đưa vào phần thảo luận.

---

## 5. Bẫy kiểm tra độ tập trung

20 dòng trong phiếu là cặp ghép ngẫu nhiên (một tuyên bố có thật + một bằng chứng
không liên quan). Chúng gần như chắc chắn phải là `irrelevant`.

Chúng **không** tính vào precision. Chúng chỉ trả lời: buổi chấm có được làm
nghiêm túc không.

**Ngưỡng:** nếu quá **3/20** bẫy bị chấm thành `supports` hoặc `contradicts`,
buổi chấm đó bị **huỷ** và phải chấm lại với mẫu mới. Ghi rõ điều này vào luận
văn nếu nó xảy ra.

---

## 6. Điều số liệu này sinh ra

```bash
python evalu/run_evaluation.py --score-annotation evalu/out/annotation/sheet_A.json \
    --filled evalu/out/annotation/sheet_A_filled.csv evalu/out/annotation/sheet_B_filled.csv
```

1. **`precision.overall`** — trong số cặp hệ thống trích dẫn, bao nhiêu phần trăm
   người chấm đồng ý. Con số luận văn đang hoàn toàn thiếu.

2. **`precision.same_company_only`** — cùng con số đó, giới hạn ở các cặp người
   chấm đánh `about_claim_company = true`. Đây là **ước lượng precision SAU khi
   sửa lỗi nhiễm chéo công ty**, tính được từ chính buổi chấm này, vì bản sửa chỉ
   *loại bớt* cặp chứ không thêm cặp mới. Một buổi chấm → hai con số → phần chênh
   chính là đóng góp định lượng.

3. **`attribution_validation`** — mức khớp giữa phán đoán của người chấm và
   heuristic `source_doc` trong `negative_control.py`. Đây là thứ biến NC.1 từ
   "heuristic của tác giả" thành "phép đo đã được người kiểm chứng".

4. **Độ đồng thuận** (khi có ≥2 người chấm) — Gwet AC1 và Krippendorff α trên cả
   `relation` lẫn `about_claim_company`. Ngưỡng Landis & Koch: ≥ 0,61 là
   *substantial*.

---

## 7. Cách khai báo trong luận văn

Bắt buộc ghi đúng như sau:

> Do không tồn tại bộ dữ liệu có nhãn, chúng tôi đánh giá precision bằng
> annotation mù của **tác giả** (và [tên người thứ hai]) trên [200/226] cặp
> (tuyên bố, bằng chứng) mà hệ thống trích dẫn, theo protocol cố định trước
> (Phụ lục X). Người chấm không nhìn thấy kết luận của hệ thống. Độ đồng thuận
> giữa hai người chấm đạt Gwet AC1 = [x] (Krippendorff α = [y]).

**Tuyệt đối không** trình bày annotation này thành "hội đồng chuyên gia
CEO / HRD / Kiểm toán". Ba hội đồng đó nằm trong `evalu/rubric.py` và là một
nghiên cứu khác, chưa được thực hiện. Gọi tên sai ở đây là gian lận nghiên cứu,
và là thứ dễ bị hội đồng hỏi tới nhất.

---

## 8. Hạn chế phải nêu

- **Precision, không có recall.** Xem §1.
- **Tác giả tự chấm.** Giảm nhẹ bằng người chấm thứ hai + chấm mù + protocol cố
  định trước, nhưng không loại bỏ được hoàn toàn.
- **n = 200.** Khoảng tin cậy 95% khoảng ±7 điểm phần trăm quanh giá trị 50%.
  Đủ để phân biệt "khoảng 30%" với "khoảng 70%"; không đủ để nói "31,2%".
- **Chỉ 5 mã CK**, và ACG chiếm 127/226 cặp. Kết quả nghiêng về ACG; nên báo cáo
  thêm bảng tách theo mã.
- **Người chấm chỉ thấy text mà hệ thống thấy** (với MediaReport là tiêu đề bài
  báo). Đây là chủ ý: chấm trên thông tin nhiều hơn hệ thống có sẽ là so sánh
  không công bằng.
