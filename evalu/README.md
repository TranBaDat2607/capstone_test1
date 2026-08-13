# Khung Đánh giá và Đo lường Mô hình (Evaluation Framework) - Project Capstone

Tài liệu này tổng hợp toàn bộ các kỹ thuật đánh giá, tiêu chí kiểm soát chất lượng không nhãn (Unlabeled Quality Controls), khung Rubric 5 điểm Likert, và bộ công cụ đo lường độ đồng thuận chuyên gia (Inter-Annotator Agreement - IAA) được tích hợp trong dự án **Graph-RAG Phát hiện Greenwashing**.

Tất cả mã nguồn, dữ liệu thử nghiệm và báo cáo kết quả đánh giá được tổ chức trong thư mục `evalu/`.

---

## 1. Cấu trúc Thư mục `evalu/`

```
evalu/
├── README.md                           # Hướng dẫn & Lý thuyết kỹ thuật Evaluation
├── evalu_pipeline_metrics.py           # Bộ 11 chỉ số kiểm soát chất lượng pipeline (Stage 1 - Stage 5)
├── evalu_grounding.py                  # A — round-trip grounding: giá trị KPI có thật trên trang nó trích dẫn không
├── evalu_labelfree.py                  # Đánh giá không nhãn tầng đối soát: hoán vị B2/B2b, D (P8), E (ablation), nhất quán claim trùng, yield truy hồi
├── evalu_iaa_engine.py                 # Động cơ toán học đo chỉ số IAA (Fleiss' Kappa, Krippendorff's Alpha, Gwet's AC1/AC2)
├── evalu_likert_rubric.py              # Bộ tiêu chí Rubric Likert 5 điểm & Đánh giá Chuyên gia
├── sample_expert_annotations.json      # Mẫu đánh giá từ các chuyên gia (CEO, HRD, Auditor)
├── run_evaluation.py                   # Script chạy đánh giá tự động toàn bộ hệ thống
├── evaluation_report.json              # Kết quả đánh giá chi tiết (Dạng JSON)
└── evaluation_report.md                # Báo cáo tổng hợp đánh giá (Dạng Markdown)
```

---

## 2. Phần 1: Mục tiêu Kiểm soát Không Nhãn (Unlabeled Quality Controls)

Do bài toán greenwashing tại Việt Nam chưa có tập dữ liệu nhãn chuẩn (ground-truth), hệ thống sử dụng **11 chỉ số kiểm soát chất lượng không nhãn** áp dụng trên 5 giai đoạn chính của Pipeline:

### Giai đoạn 1: Thu thập & Phân loại ESG (Ingestion & Classification)
1. **ESG Signal-to-Noise Ratio (SNR)**:
   - Công thức: `SNR = (Số câu ESG có căn cứ) / (Tổng số câu esg=true)`
   - Ý nghĩa: Tỷ lệ các câu chứa thuật ngữ/con số ESG có căn cứ so với tổng số câu được ViDeBERTa phân loại esg=true. Lọc bỏ văn xuôi tiếp thị chung chung.
2. **Paragraph Source Provenance Rate**:
   - Công thức: `Provenance Rate = (Số câu có tọa độ nguồn) / (Tổng số câu)`
   - Ý nghĩa: Đảm bảo 100% câu trích xuất giữ nguyên tọa độ nguồn (source_pdf, page, sentence_index).

### Giai đoạn 2: Trích xuất Triplet & KPI (Extraction)
3. **Temporal Metadata Completeness (C_temporal)**:
   - Tỷ lệ node và cạnh mang đủ bộ ba thuộc tính thời gian: valid_from, valid_to, recorded_at.
4. **Schema Compliance Rate (C_schema)**:
   - Tỷ lệ cặp node-edge tuân thủ đúng định dạng dữ liệu ISO Date và khai báo trong config/schema.json (0 vi phạm).
5. **Value Preservation Guard**:
   - Kiểm tra hash/CRC của thuộc tính định lượng trước và sau bước LLM Repair, cấm LLM tự ý biến đổi số liệu hoặc đơn vị.

### Giai đoạn 3: Định danh Thực thể (Entity Resolution)
6. **Timeless Identity Violation Rate (V_identity)**:
   - Kiểm tra các class T1 (như Organization, Facility) tuyệt đối không chứa thuộc tính thời gian trong identity_keys.
7. **Oversimplification & Cluster Conciseness Rate (C_concise)**:
   - Tỷ lệ trùng lặp thực thể sau các bước hợp nhất Stage A/B/C/D nhằm phát hiện vỡ cụm (under-merging) hoặc gộp nhầm (over-merging).

### Giai đoạn 4: Trục Chỉ số Chuẩn (Indicator Axis)
8. **Standard Indicator Alignment Coverage**:
   - Tỷ lệ tuyên bố (T3) nối thành công cạnh alignsWithIndicator tới Thông tư 96 (TT96) hoặc bộ chỉ số GRI Catalog.
9. **Zero-Report Self-Praise Exclusion**:
   - Kiểm tra logic phạt: Penalty có amount = 0 phải gán nhãn self_reported_zero, ngăn chặn hệ thống tự sinh cạnh vi phạm giả.

### Giai đoạn 5: Đối soát Chéo (Cross-check Claims vs Conduct)
10. **Evidence Asymmetry & Abstention Rate**:
    - Tỷ lệ tuyên bố chuyển sang trạng thái unverified_insufficient_evidence do thiếu chứng cứ báo chí độc lập.
11. **Self-Verification Exclusion Rate**:
    - Tỷ lệ loại bỏ các cạnh verifiedBy mà nguồn chứng cứ đến từ chính domain của doanh nghiệp.

---

## 3. Phần 2: Khung Đánh giá Rubric Thang đo Likert 5 Điểm

Khung đánh giá chuyên gia dựa trên 4 khía cạnh cốt lõi (Likert 1 - Rất kém đến 5 - Rất tốt):

| Khía cạnh Đánh giá | Mức 1 (Unacceptable) | Mức 3 (Acceptable) | Mức 5 (Excellent / Production-Ready) |
|---|---|---|---|
| **1. Độ chính xác Căn cứ (Grounding)** | Bị suy diễn sai lệch so me với bản gốc; xuất hiện ảo giác (hallucination). | Trích xuất đúng nội dung chính nhưng bị sót ngữ cảnh hoặc làm tròn số sai nhẹ. | Trích xuất chính xác tuyệt đối từng con số, đơn vị tính, mốc thời gian từ gốc. |
| **2. Chất lượng Đối soát (Adjudication)** | Đánh giá tư vấn sai bối cảnh (gán appears_supported cho 2 tin mâu thuẫn). | Tư vấn đúng hướng nhưng giải thích bằng ngôn ngữ tự nhiên còn chung chung. | Lập luận đối soát sắc bén, chỉ rõ khoảng cách gap giữa Claim và Conduct. |
| **3. Minh bạch Nguồn gốc (Provenance)** | Không thể truy xuất trích dẫn; link nguồn hỏng hoặc sai trang. | Chỉ đúng tài liệu nhưng lệch số trang hoặc số câu. | Cung cấp chính xác tuyệt đối tên tài liệu, số trang, số câu và URL gốc. |
| **4. Hỗ trợ Ra Quyết định (Decision Utility)** | Bằng chứng gây nhiễu, làm tốn thêm thời gian đọc lại tài liệu thô. | Giúp tổng hợp cơ bản, giảm 30-50% thời gian nhưng vẫn cần kiểm tra thủ công. | Tổng hợp hồ sơ sắc nét, làm nổi bật ngay mâu thuẫn cốt lõi, giảm >70% thời gian. |

---

## 4. Phần 3: Độ Đồng thuận Chuyên gia (Inter-Annotator Agreement - IAA)

Đánh giá định tính từ nhiều chuyên gia (CEO, HRD, Kiểm toán viên) được chuẩn hóa thông qua 3 chỉ số toán học:

### 1. Fleiss' Kappa
Áp dụng cho phân loại định danh câu ESG thô:
- Công thức: `Kappa = (P_bar - P_e_bar) / (1 - P_e_bar)`
- Trong đó P_bar là tỷ lệ đồng thuận quan sát, P_e_bar là tỷ lệ kỳ vọng ngẫu nhiên.

### 2. Krippendorff's Alpha
Áp dụng cho thang đo Likert thứ bậc (Ordinal 1-5), hỗ trợ xử lý dữ liệu thiếu:
- Công thức: `Alpha = 1 - (D_o / D_e)`
- Kết hợp với hàm trọng số bình phương (Quadratic Weights) để phạt nặng sự chênh lệch lớn giữa các điểm chấm (ví dụ: lệch giữa 1 và 5).

### 3. Gwet's AC1 / AC2 (Khắc phục Paradox Kappa)
Do dữ liệu đối soát chéo bị lệch nhãn nghiêm trọng (91.6% là unverified_insufficient_evidence), Fleiss' Kappa bị suy giảm về 0. Chỉ số Gwet's AC1 (cho định danh) và AC2 (cho Likert thứ bậc) được sử dụng để duy trì độ ổn định toán học:
- Công thức: `AC1 = (p_a - p_e) / (1 - p_e)`

---

## 5. Quy trình Phân giải Mâu thuẫn (Consensus Resolution Pipeline)

1. **Thu thập Đánh giá Độc lập**: Chuyên gia chấm độc lập trên giao diện ESG Evidence View.
2. **Tính toán IAA tự động**: Chạy thuật toán Krippendorff's Alpha và Gwet's AC2. Ngưỡng đạt: >= 0.61 (Substantial Agreement).
3. **Xác định Vùng Mâu thuẫn**: Tự động lọc các ô lệch >= 2 điểm Likert hoặc mâu thuẫn nhãn.
4. **Hội đồng Phân giải**: Thảo luận nhóm mâu thuẫn, chọn nhãn cuối theo nguyên tắc nhất trí hoặc **Weighted Median** (trọng số của Kiểm toán viên cao hơn về chuẩn mực pháp lý, trọng số CEO/HRD cao hơn về chiến lược).

---

## 6. Trạng thái đo lường thực tế (đọc trước khi trích số vào báo cáo)

Các mục 2–5 ở trên mô tả **khung lý thuyết** theo `evalu.pdf`. Không phải mục nào trong đó
cũng đo được trên hiện trạng dự án. Ranh giới thực tế:

| Nhóm | Trạng thái | Ghi chú |
|---|---|---|
| 11 chỉ số pipeline (mục 2) | **10/11 đo được**, offline, 0đ | Riêng *Value Preservation Guard* không có tỷ lệ để báo cáo — bộ đếm chỉ ghi ra log, muốn có số phải chạy lại step03 phase 2 (tính phí) |
| **A — round-trip grounding** | **đo được**, offline, 0đ | Chỉ số **độ đúng thật** duy nhất trong bộ: văn bản gốc là ground truth cho "con số này có trong tài liệu không". Lấp lỗ hổng `q1_accuracy` của `quality.py` |
| **D — bằng chứng đi sau claim** | **đo được**, offline, 0đ | Kiểm nguyên tắc P8 ngay trên phán quyết đã có. Thay được MR-4 (191 lệnh gọi LLM) bằng 0đ |
| **E — ablation cửa sổ thời gian** | **đo được**, offline, 0đ | Định lượng cái giá của việc siết `window_after` từ 50 năm xuống |
| Đánh giá không nhãn tầng đối soát | **đo được**, offline, 0đ | Hoán vị B2/B2b có p-value thật; xem `evalu_labelfree.py` |
| RAGAS (Faithfulness / Precision / Recall) | **không đo được** | Context Recall cần ground-truth — đã ghi nhận là metric chết tại `docs/EVALUATION_WITHOUT_LABELS.md` §8 |
| Metamorphic MR-1…MR-4, B1 specificity | **chưa đo** | Cần chạy adjudicator THẬT, ~191 lệnh gọi LLM mỗi phép |
| Rubric Likert + IAA (mục 3–5) | **chưa đo** | Bộ máy toán đã sẵn sàng; thiếu dữ liệu người chấm thật. `sample_expert_annotations.json` chỉ là bản mẫu dựng sẵn (claim Vinamilk), không thuộc corpus này |

Hai module cũ `evalu_ragas_metrics.py` và `evalu_metamorphic.py` **đã bị xoá**: chúng sinh
số từ hằng số cắm cứng và từ một adjudicator giả chạy trên ba doanh nghiệp không có trong
corpus, nên mọi con số chúng in ra đều không phải phép đo. `evalu_labelfree.py` thay thế
chúng bằng những gì thực sự tính được từ artifact trên đĩa.

---

## 7. Hướng dẫn Chạy Đánh giá

Chạy câu lệnh từ thư mục gốc của dự án:
```bash
python evalu/run_evaluation.py     # → evaluation_report.json + evaluation_report.md
python test/test_evalu_metrics.py  # kiểm chứng: mọi số khớp oracle độc lập, không có hằng số bịa
```

`test/test_evalu_metrics.py` là ràng buộc giữ cho báo cáo trung thực: nó tính lại từng chỉ
số bằng vòng lặp độc lập ngay trong test rồi đối chiếu, đồng thời quét mã nguồn `evalu/*.py`
để chặn các hằng số benchmark quay trở lại. Chạy nó sau mỗi lần sửa `evalu/`.
