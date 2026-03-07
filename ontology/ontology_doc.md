# Vn-ESG-Graph Ontology — Tài liệu Kỹ thuật v2.0.0

> Cập nhật: 2026-03-07 | Phiên bản Schema: 2.0.0  
> Chuẩn tham chiếu: GRI Universal Standards 2021, TT96/2020 + TT08/2026/TT-BTC, ISSB IFRS S1/S2, QĐ 21/2025/QĐ-TTg

---

## 1. Tổng Quan

Ontology này là **hợp đồng dữ liệu (Data Contract)** của toàn bộ hệ thống Vn-ESG-Graph. Nó định nghĩa:

- **10 Entity Types** — các loại đối tượng tồn tại trong Knowledge Graph
- **12 Relation Types** — các loại quan hệ (cạnh trong đồ thị) giữa các đối tượng
- **Global relation properties** — các trường bắt buộc trên mọi relation

Mọi dữ liệu được pipeline trích xuất từ PDF báo cáo ESG đều phải tuân theo cấu trúc này trước khi được nạp vào Neo4j.

---

## 2. Entity Types

### 2.1 Company — Doanh nghiệp

Đại diện cho một doanh nghiệp niêm yết tại Việt Nam có công bố thông tin ESG.

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | Định danh duy nhất (VD: `COMP_FPT`) |
| `name` | string | ✅ | Tên đầy đủ |
| `ticker` | string | ✅ | Mã chứng khoán (VD: `FPT`) |
| `exchange` | string | | `HOSE` / `HNX` / `UPCoM` |
| `industry` | string | | Ngành nghề |
| `vnsi_listed` | boolean | | Có trong danh mục VNSI (HOSE) |
| `is_subsidiary` | boolean | | Là công ty con |

---

### 2.2 Metric — Chỉ số ESG đo lường được

Số liệu định lượng thực tế, bao phủ cả 3 trụ cột **E / S / G**.

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | VD: `METRIC_CO2_SCOPE1_2023` |
| `name` | string | ✅ | Tên chỉ số |
| `pillar` | string | ✅ | `E` / `S` / `G` |
| `category` | string | ✅ | Xem bảng category bên dưới |
| `gri_code` | string | | Mã GRI tương ứng (VD: `GRI 305-1`) |
| `issb_code` | string | | Mã IFRS S2 tương ứng |
| `value` | number | ✅ | Giá trị số |
| `unit` | string | ✅ | Đơn vị đo |
| `year` | integer | ✅ | Năm báo cáo |
| `is_green_taxonomy_aligned` | boolean | | Thuộc danh mục QĐ 21/2025 |

**Danh mục category theo pillar:**

| Pillar | Category | GRI Reference |
|--------|---------|--------------|
| E | Emissions | GRI 305-1/2/3 |
| E | Energy | GRI 302-1/2 |
| E | Water | GRI 303-3 |
| E | Waste | GRI 306-3 |
| E | Biodiversity | GRI 101 (2024) |
| S | Employment | GRI 401-1, 404-1 |
| S | Health_Safety | GRI 403-9 |
| S | Diversity | GRI 405-1 |
| S | Community | GRI 413-1 |
| G | Anti_corruption | GRI 205-3 |
| G | Board_Governance | GRI 2-9 |
| G | Transparency | GRI 2-26 |

> ⚠️ **Ghi chú GRI 2026**: GRI 302 và GRI 305 vẫn hiệu lực song song trong giai đoạn chuyển tiếp. GRI 102 (Climate) & GRI 103 (Energy) ra tháng 6/2025, bắt buộc từ 01/01/2027.

---

### 2.3 Target — Mục tiêu cam kết dài hạn

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | VD: `TGT_NETZERO_2050` |
| `name` | string | ✅ | Tên mục tiêu |
| `pillar` | string | ✅ | `E` / `S` / `G` |
| `target_year` | integer | | Năm mục tiêu |
| `baseline_year` | integer | | Năm gốc |
| `baseline_value` | number | | Giá trị gốc để so sánh |
| `baseline_unit` | string | | Đơn vị giá trị gốc |
| `description` | string | | Mô tả chi tiết |

---

### 2.4 Regulation — Quy định pháp lý

| Thuộc tính | Kiểu | Mô tả |
|-----------|------|-------|
| `id` | string | VD: `REG_TT96_2020` |
| `name` | string | Tên đầy đủ văn bản |
| `issuer` | string | Cơ quan ban hành |
| `effective_date` | string | Ngày hiệu lực (ISO 8601) |
| `amended_by` | string | ID văn bản sửa đổi (nếu có) |
| `scope` | string | Phạm vi áp dụng |
| `is_mandatory` | boolean | Bắt buộc hay khuyến nghị |

**Các Regulation mẫu quan trọng:**

| ID | Văn bản | Ghi chú |
|----|---------|---------|
| `REG_TT96_2020` | TT 96/2020/TT-BTC | Công bố ESG cho công ty niêm yết |
| `REG_TT08_2026` | TT 08/2026/TT-BTC (03/02/2026) | Sửa đổi TT96, align ISSB/GRI — **mới nhất** |
| `REG_GREEN_TAXONOMY_2025` | QĐ 21/2025/QĐ-TTg | Vietnam Green Taxonomy 2025-2030 |

---

### 2.5 Project — Dự án ESG

| Thuộc tính | Kiểu | Mô tả |
|-----------|------|-------|
| `id` | string | VD: `PRJ_SOLAR_FPT` |
| `name` | string | Tên dự án |
| `pillar` | string | `E` / `S` / `G` |
| `start_year`, `end_year` | integer | Thời gian |
| `budget_vnd` | number | Ngân sách (VNĐ) |
| `status` | string | `Planned` / `In Progress` / `Completed` / `Cancelled` |
| `green_taxonomy_category` | string | Phân loại theo QĐ 21/2025 |

---

### 2.6 Claim — Tuyên bố ESG ⭐

**Entity quan trọng nhất cho Greenwashing Detection.** Là các tuyên bố định tính tích cực của doanh nghiệp chưa được kiểm chứng bởi số liệu.

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | VD: `CLM_E_001` |
| `text` | string | ✅ | Nội dung tuyên bố trích từ báo cáo |
| `pillar` | string | ✅ | `E` / `S` / `G` |
| `sentiment` | string | ✅ | `Positive` / `Neutral` / `Negative` |
| `page_ref` | integer | | Trang trong báo cáo gốc |
| `year` | integer | | Năm báo cáo |

---

### 2.7 DataPoint — Số liệu thực tế từ bảng biểu

Khác với `Metric` (chỉ số được chuẩn hóa GRI), `DataPoint` là số liệu thô trích xuất trực tiếp từ bảng biểu, chưa qua chuẩn hóa.

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | VD: `DP_E_001` |
| `description` | string | ✅ | Mô tả số liệu |
| `value` | number | ✅ | Giá trị |
| `unit` | string | ✅ | Đơn vị |
| `year` | integer | ✅ | Năm |
| `page_ref` | integer | | Trang trong PDF |
| `table_ref` | string | | Ký hiệu bảng (VD: `Table 5.2`) |
| `data_type` | string | | `Actual` / `Restated` / `Estimated` |

---

### 2.8 NewsEvent — Tin tức từ nguồn bên ngoài

| Thuộc tính | Kiểu | Mô tả |
|-----------|------|-------|
| `id` | string | VD: `NEWS_E_001` |
| `headline` | string | Tiêu đề bài báo |
| `source` | string | Tên tờ báo (VD: `VnExpress`) |
| `url` | string | Đường dẫn |
| `published_at` | string | Ngày đăng (ISO 8601) |
| `sentiment` | string | `Positive` / `Neutral` / `Negative` |
| `pillar` | string | `E` / `S` / `G` / `Mixed` |

---

### 2.9 Report — Tài liệu báo cáo gốc (PDF)

| Thuộc tính | Kiểu | Mô tả |
|-----------|------|-------|
| `id` | string | VD: `RPT_FPT_ESG_2023` |
| `title` | string | Tên báo cáo |
| `type` | string | `ESG Report` / `Annual Report` / `Sustainability Report` |
| `year` | integer | Năm |
| `filename` | string | Tên file PDF |
| `language` | string | `vi` / `en` / `vi_en` |
| `gri_aligned` | boolean | Báo cáo theo GRI hay không |
| `issb_aligned` | boolean | Báo cáo theo ISSB hay không |

---

### 2.10 AuditResult — Kết quả kiểm toán Greenwashing ⭐

Output cuối cùng của Agent AI, được Dashboard hiển thị.

| Thuộc tính | Kiểu | Bắt buộc | Mô tả |
|-----------|------|----------|-------|
| `id` | string | ✅ | VD: `AUDIT_FPT_2023` |
| `company_id` | string | ✅ | Liên kết với Company |
| `report_id` | string | ✅ | Liên kết với Report |
| `audited_at` | string | ✅ | Ngày chạy audit |
| `trust_score` | number [0–1] | ✅ | Điểm tin cậy tổng hợp |
| `greenwashing_risk` | string | ✅ | `Low` / `Medium` / `High` |
| `total_claims` | integer | ✅ | Tổng số tuyên bố |
| `supported_claims` | integer | ✅ | Được xác nhận bởi DataPoint |
| `flagged_claims` | integer | ✅ | Bị gắn cờ (mâu thuẫn/thiếu bằng chứng) |
| `e_score` | number [0–1] | | Điểm E riêng |
| `s_score` | number [0–1] | | Điểm S riêng |
| `g_score` | number [0–1] | | Điểm G riêng |
| `summary` | string | | Mô tả ngắn kết quả audit |

> **Công thức trust_score**: `supported_claims / total_claims`  
> **Ngưỡng risk**: Low ≥ 0.8 | Medium 0.5–0.8 | High < 0.5

---

## 3. Relation Types

> **Quy tắc bắt buộc**: Mọi relation instance trong `sample_instances.json` và dữ liệu thật đều phải có 3 trường sau:
> ```json
> "extracted_at": "2026-03-07",
> "confidence_score": 0.92,
> "extraction_method": "RE_Model"
> ```
> `extraction_method` nhận một trong: `RE_Model` | `Rule-based` | `Manual` | `LLM_Constraint`

---

### Bảng tổng hợp 12 Relation Types

| Relation | Từ → Đến | Luồng nghiệp vụ | Ghi chú |
|----------|---------|----------------|---------|
| `has_emission` | Company → Metric | Chỉ số E/S/G | Dùng cho cả 3 pillars |
| `targets_reduction` | Company → Target | Cam kết | |
| `complies_with` | Company → Regulation | Tuân thủ | |
| `violates` | Company → Regulation | **Greenwashing signal** | Mâu thuẫn với `complies_with` |
| `subsidiary_of` | Company → Company | Cấu trúc tập đoàn | Phân tích ESG chuỗi cung ứng |
| `invests_in` | Company → Project | Đầu tư xanh | |
| `claims_reduction` | Company → Claim | Tuyên bố → cần audit | |
| `supported_by` | Claim → DataPoint | ✅ Claim hợp lệ | Số liệu xác nhận tuyên bố |
| `contradicted_by` | Claim → NewsEvent | 🚨 Greenwashing flag | Tin tức phủ nhận tuyên bố |
| `extracted_from` | Metric/DataPoint/Claim → Report | Truy xuất nguồn | |
| `mentions` | Report → Company | Liên kết tài liệu | |
| `audited_by` | Company → AuditResult | Output pipeline | Feed vào Dashboard |

---

## 4. Ba Luồng Nghiệp Vụ Chính

### Luồng 1 — Trích xuất Chỉ số (Metrics)
```
PDF → Parser → DataPoint/Metric → extracted_from → Report
Company --[has_emission]--> Metric
```

### Luồng 2 — Tuân thủ & Cam kết
```
Company --[complies_with / violates]--> Regulation
Company --[targets_reduction]---------> Target
Company --[invests_in]----------------> Project
```

### Luồng 3 — Greenwashing Detection (Agent AI)
```
Company --[claims_reduction]---> Claim
                                    |
               ┌────────────────────┴────────────────────────┐
               ↓                                             ↓
    [supported_by] → DataPoint                 [contradicted_by] → NewsEvent
    (✅ trust += 1)                              (🚨 trust -= 1, flag raised)
               └──────────────────── ──────────────────────────┘
                                    ↓
                              AuditResult
                   trust_score / risk_level / summary
                                    ↓
                               Dashboard
```

---

## 5. Quy Ước Đặt ID

| Entity | Prefix | Ví dụ |
|--------|--------|-------|
| Company | `COMP_` | `COMP_FPT` |
| Metric | `METRIC_` | `METRIC_CO2_SCOPE1_2023` |
| Target | `TGT_` | `TGT_NETZERO_2050` |
| Regulation | `REG_` | `REG_TT96_2020` |
| Project | `PRJ_` | `PRJ_SOLAR_FPT` |
| Claim | `CLM_[E/S/G]_` | `CLM_E_001` |
| DataPoint | `DP_[E/S/G]_` | `DP_E_001` |
| NewsEvent | `NEWS_[E/S/G]_` | `NEWS_E_001` |
| Report | `RPT_` | `RPT_FPT_ESG_2023` |
| AuditResult | `AUDIT_` | `AUDIT_FPT_2023` |
| Relation | `REL_` | `REL_001` |

---

## 6. Cấu Trúc File

```
ontology/
├── ontology_schema.json   # Định nghĩa Entity Types + Relation Types (v2.0.0)
├── sample_instances.json  # Dữ liệu mẫu FPT ESG 2023 (29 entities, 23 relations)
├── ontology_doc.md        # Tài liệu kỹ thuật này
└── README.md              # Giới thiệu nhanh
```

---

## 7. Chuẩn Tham Chiếu

| Tài liệu | Link | Ghi chú |
|---------|------|---------|
| GRI Standards | [globalreporting.org](https://www.globalreporting.org) | GRI 302/305 còn hiệu lực 2026; GRI 102/103 effective 2027 |
| TT 96/2020/TT-BTC | Bộ Tài chính | Công bố ESG niêm yết, hiệu lực 01/01/2021 |
| TT 08/2026/TT-BTC | Bộ Tài chính | Sửa đổi TT96, ban hành 03/02/2026 — **mới nhất** |
| QĐ 21/2025/QĐ-TTg | Thủ tướng CP | Vietnam Green Taxonomy 2025–2030 |
| ISSB IFRS S1/S2 | [ifrs.org](https://www.ifrs.org) | Chuẩn quốc tế mới, TT08/2026 hướng tới align |
| VNSI | [hsx.vn](https://www.hsx.vn) | Chỉ số bền vững HOSE, 20 cổ phiếu, cập nhật tháng 7/năm |
