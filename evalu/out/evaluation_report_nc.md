# Báo cáo Đánh giá Hệ thống Graph-RAG (không nhãn)

*Sinh tự động lúc 2026-08-07T04:20:22+00:00 — `python evalu/run_evaluation.py`*

> Hệ thống là **Decision-Support System**, không phải bộ phân loại greenwashing. Không tồn tại nhãn chuẩn, nên mọi con số dưới đây là **chỉ số nội bộ (intrinsic)** đo tính nhất quán của pipeline — KHÔNG phải accuracy so với sự thật.

## 0. Phạm vi dữ liệu đo

| Hạng mục | Giá trị |
|---|---|
| Đồ thị đã phân giải | 10,634 node / 14,744 cạnh |
| Hồ sơ đối soát | 464 claim / 5 mã CK |
| Mã chứng khoán | AAA, ACC, ACG, ADP, AGG |
| Thời gian chạy | 0.2s |

## 1. Tổng hợp chỉ số nội bộ theo module (§2)

| Mã | Chỉ số | Giá trị | Tử/Mẫu | Trạng thái |
|---|---|---:|---:|:--:|
| M1.1 | ESG Signal-to-Noise Ratio | — | — | info |
| M1.2 | Paragraph Source Provenance Rate | — | — | info |
| M2.1 | Temporal Metadata Completeness | 93.02% | 21,620 / 23,243 | FAIL |
| M2.2 | Schema Compliance Rate | 100.00% | 14,744 / 14,744 | PASS |
| M2.3 | Value Preservation Guard | — | — | info |
| M3.1 | Timeless Identity Violation Rate | 0.00% | 0 / 14 | PASS |
| M3.2 | Oversimplification & Cluster Conciseness | 0.47% | 10 / 2,135 | info |
| M4.1 | Standard Indicator Alignment Coverage | 50.53% | 718 / 1,421 | info |
| M4.2 | Zero-Report Self-Praise Exclusion | 100.00% | 1 / 1 | PASS |
| M5.1 | Evidence Asymmetry & Abstention Rate | 73.49% | 341 / 464 | info |
| M5.2 | Self-Verification Exclusion Rate | 0.00% | 0 / 99 | info |
| NC.1 | Same-Company Evidence Rate | 28.76% | 65 / 226 | FAIL |
| NC.2 | Same-Feed Specificity vs Chance | 28.76% | 65 / 226 | FAIL |

## 2. Chi tiết từng module

### 1. Thu thập & Phân loại ESG

**M1.1 — ESG Signal-to-Noise Ratio**  
Giá trị: **—**

*BỎ QUA — chạy với --quick*

**M1.2 — Paragraph Source Provenance Rate**  
Giá trị: **—**

*BỎ QUA — chạy với --quick*

### 2. Trích xuất Triplet & KPI

**M2.1 — Temporal Metadata Completeness**  
Giá trị: **93.02%** (21,620/23,243) · Mục tiêu: 100%

Cạnh: 14,227/14,744 · Node T2/T3: 7,393/8,499
Cạnh thiếu thời gian, theo predicate: `alignsWithIndicator` = 413, `partOf` = 43, `worksAt` = 30, `equivalentTo` = 26, `reportsKPI` = 2, `subjectToRegulation` = 1, `investsIn` = 1, `adoptsStandard` = 1
Node thiếu `valid_from`, theo lớp: `Goal` = 511, `Initiative` = 429, `Project` = 163, `KPIObservation` = 2, `Investment` = 1
*Mẫu số lấy theo config/schema.json: mọi edge spec đều khai temporal_properties và mọi lớp T2/T3 đều khai valid_from. Phần hụt vì thế là sai lệch thật so với hợp đồng schema, không phải giả định của phép đo.*

**M2.2 — Schema Compliance Rate**  
Giá trị: **100.00%** (14,744/14,744) · Mục tiêu: 100% (0 vi phạm)


**M2.3 — Value Preservation Guard**  
Giá trị: **—**

*BỎ QUA — chạy với --quick*

### 3. Phân giải Thực thể

**M3.1 — Timeless Identity Violation Rate**  
Giá trị: **0.00%** (0/14) · Mục tiêu: 0 vi phạm


**M3.2 — Oversimplification & Cluster Conciseness**  
Giá trị: **0.47%** (10/2,135) · Mục tiêu: thấp hơn = ít thực thể trùng còn sót sau hợp nhất

Cụm trùng lớn nhất: `Location`×3, `Location`×2, `Location`×2, `Location`×2, `Location`×2

### 4. Ánh xạ Trục Chỉ tiêu

**M4.1 — Standard Indicator Alignment Coverage**  
Giá trị: **50.53%** (718/1,421) · Mục tiêu: cao hơn = độ phủ TT96/GRI tốt hơn

Theo lớp: `Goal` 248/511, `Initiative` 171/429, `SustainabilityClaim` 299/481

**M4.2 — Zero-Report Self-Praise Exclusion**  
Giá trị: **100.00%** (1/1) · Mục tiêu: 100%


### 5. Đối soát Chéo

**M5.1 — Evidence Asymmetry & Abstention Rate**  
Giá trị: **73.49%** (341/464) · Mục tiêu: mô tả độ mỏng của kho bằng chứng — không phải chỉ tiêu cần tối ưu

Phân bố kết luận: `unverified_insufficient_evidence` = 341, `appears_contradicted` = 72, `appears_supported` = 51

**M5.2 — Self-Verification Exclusion Rate**  
Giá trị: **0.00%** (0/99) · Mục tiêu: bằng chứng xác nhận phải đến từ nguồn độc lập


### Negative control — quy thuộc bằng chứng

**NC.1 — Same-Company Evidence Rate**  
Giá trị: **28.76%** (65/226) · Mục tiêu: 100% (bằng chứng phải nói về chính doanh nghiệp bị xét)

*cross_feed_unmentioned là con số quyết định: bài đến từ feed công ty khác VÀ không hề nhắc tên doanh nghiệp đang xét trong phần text mà LLM thực sự nhìn thấy.*

### Negative control — độ đặc hiệu theo công ty

**NC.2 — Same-Feed Specificity vs Chance**  
Giá trị: **28.76%** (65/226) · Mục tiêu: lift >> 1 (nếu ~1 thì truy hồi không mang tín hiệu công ty nào)


## 3. Tầng đánh giá chuyên gia (§3) và độ đồng thuận (§4)

**Chưa thu thập phiếu chấm nào.** Bộ công cụ đã sẵn sàng: `evalu/rubric.py` chứa rubric 4 khía cạnh × thang Likert 5 điểm, 3 nhóm hội đồng, bộ sinh phiếu trống và pipeline đồng thuận (Gwet AC2 / Krippendorff α, ngưỡng 0.61).

Sinh phiếu trống:

```bash
python evalu/run_evaluation.py --make-sheet --rater-id ceo01 --panel ceo --n-claims 30
```

Hệ số chính: **gwet_ac2** — Phân bố nhãn lệch mạnh về unverified_insufficient_evidence khiến chance-agreement của Kappa tiệm cận 1 và hệ số sụp về 0 (prevalence paradox). Gwet neo chance theo prevalence nên bền vững.

## 4. Giới hạn cần nêu khi trích dẫn báo cáo này

- Không có ground truth ⇒ không có precision/recall/F1 về greenwashing.
- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, không đo **tính đúng**.
- Tỷ lệ abstention cao phản ánh kho tin tức độc lập còn mỏng, không phải lỗi thuật toán.
- M1.1 (SNR) đo mức độ *neo được vào từ vựng KPI/GRI*, không phải độ chính xác của bộ phân loại ESG.
