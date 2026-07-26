# Tài liệu Kỹ thuật Chi tiết GRI Master Schema (GRI Enterprise Schema Reference)

> **Loại tài liệu:** Tài liệu Mô tả Kỹ thuật Schema (Technical Specification Reference)  
> **File Schema gốc:** [`gri_schema.json`](file:///b:/capstone/newrepotest/capstone_test1/gri/full_gri/gri_schema.json)  
> **Model Python Pydantic:** [`gri_schema.py`](file:///b:/capstone/newrepotest/capstone_test1/gri/full_gri/gri_schema.py)  
> **Catalog dữ liệu:** [`manifest.json`](file:///b:/capstone/newrepotest/capstone_test1/gri/full_gri/manifest.json)

---

## 1. Tổng quan Kiến trúc Schema (Schema Overview)

`gri_schema.json` là chuẩn **JSON Schema Draft-07** quy định cấu trúc dữ liệu lưu trữ toàn bộ các tiêu chuẩn GRI Standards. Schema được thiết kế theo **Mô hình Đồ thị Tri thức 3 Tầng (3-Tier Node Architecture)** để phục vụ truy vấn Graph-RAG và kiểm tra tuân thủ bitemporal theo thời gian.

### Sơ đồ Cấu trúc Cây Dữ liệu (Schema Tree Structure)

```
GRI Standard Record (Root Object)
├── node_tier: Enum (T1 / T2 / T3)
├── standard_id: String (Khóa phi thời gian P1, VD: "GRI 305")
├── title_en / title_vi: String
├── pillar: Enum ("Universal" | "Sector" | "E — Environmental" | "S — Social" | "G — Governance")
├── series: String (VD: "Environmental (300 Series)")
├── category: String (VD: "Topic-Environmental")
│
├── temporal_validity (Object - Quản lý Bitemporal & Phiên bản)
│   ├── version_id: String (Khóa phiên bản, VD: "GRI_305_2016")
│   ├── version_year: Integer (VD: 2016)
│   ├── effective_date: String (Định dạng YYYY-MM-DD, VD: "2018-07-01")
│   ├── valid_until_year: Integer | Null
│   ├── status: Enum ("Active" | "Superseded" | "Under Revision" | "Draft")
│   ├── replaced_by_standard_id: String | Null (VD: "GRI 101")
│   └── superseded_notes: String | Null
│
├── scope (Object - Phạm vi Tác dụng & Quy tắc Áp dụng)
│   ├── target_audience: String
│   ├── sector_code: String | Null (VD: "GRI 11")
│   ├── materiality_required: Boolean
│   └── boundary_scope: String
│
├── provenance (Object - Kiểm toán Xuất xứ File Gốc)
│   ├── relative_pdf_path: String
│   ├── file_size_bytes: Integer
│   ├── page_count: Integer
│   ├── sha256: String (Mã băm kiểm tra toàn vẹn)
│   └── indexed_at: String (ISO Timestamp)
│
├── disclosures_count: Integer
└── disclosures (Array of Disclosure Objects)
    └── GRIDisclosure (Object)
        ├── disclosure_id: String (VD: "305-1")
        ├── title_en / title_vi: String
        ├── disclosure_type: Enum ("Management Approach" | "Topic-Specific" | "General Disclosures")
        ├── mandatory: Boolean
        ├── sdg_mapping / esrs_mapping / issb_mapping: Array of Strings
        ├── recommendations_en / recommendations_vi: String | Null
        └── requirements (Array of Requirement Objects)
            └── RequirementItem (Object)
                ├── requirement_id: String (Khóa khoản yêu cầu, VD: "305-1:a")
                ├── item_code: String (VD: "a", "b", "c")
                ├── description_en / description_vi: String
                ├── requirement_type: Enum ("Quantitative" | "Qualitative" | "Hybrid")
                ├── unit_of_measure: Array of Strings (VD: ["metric tons CO2e"])
                └── breakdown_dimensions: Array of Strings (VD: ["by Scope", "by facility"])
```

---

## 2. Chi tiết Mô tả từng Trường Dữ liệu (Field Specification)

### 2.1. Root Level Attributes (Khối Thuộc tính Cấp cao nhất)

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Ràng buộc / Giá trị Enum (Constraints) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|---|
| `node_tier` | `string` | **Có** | `T1 — Identity...`<br/>`T2 — Observation...`<br/>`T3 — Assertion...` | Phân tầng Node theo thiết kế Temporal KG (§2 TEMPORAL_KG_DESIGN.md). Mặc định là `T1`. | `"T1 — Identity (Thực thể bền phi thời gian)"` |
| `standard_id` | `string` | **Có** | Non-empty string | **Khóa danh tính phi thời gian (Timeless Identity Key P1)**. Không chứa năm phát hành. | `"GRI 305"` |
| `title_en` | `string` | **Có** | Non-empty string | Tên đầy đủ của tiêu chuẩn bằng Tiếng Anh. | `"Emissions"` |
| `title_vi` | `string` | **Có** | Non-empty string | Tên đầy đủ của tiêu chuẩn bằng Tiếng Việt. | `"Phát thải"` |
| `pillar` | `string` | **Có** | `Universal`<br/>`Sector`<br/>`E — Environmental`<br/>`S — Social`<br/>`G — Governance` | Phân loại theo Trụ cột ESG hoặc Nhóm Chung/Ngành. | `"E — Environmental"` |
| `series` | `string` | **Có** | String | Dòng tiêu chuẩn GRI (Universal, 200, 300, 400 Series, Sector). | `"Environmental (300 Series)"` |
| `category` | `string` | **Có** | String | Nhóm phân loại chuyên sâu (Topic-Environmental, Topic-Social...). | `"Topic-Environmental"` |
| `disclosures_count` | `integer` | Không | $\ge 0$ | Tổng số lượng chỉ số công bố (Disclosures) thuộc tiêu chuẩn này. | `7` |

---

### 2.2. Object `temporal_validity` (Quản lý Bitemporal & Phiên bản)

Object này quản lý mốc thời gian có hiệu lực và trạng thái phiên bản của tiêu chuẩn (T3 Version Node).

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|
| `version_id` | `string` | **Có** | Khóa định danh phiên bản dạng `<standard_id>:<version_year>`. | `"GRI_305_2016"` |
| `version_year` | `integer` | **Có** | Năm phát hành phiên bản tiêu chuẩn. | `2016` |
| `effective_date` | `string` | **Có** | Định dạng `YYYY-MM-DD`. Ngày bắt đầu có hiệu lực đối với Báo cáo Thường niên. | `"2018-07-01"` |
| `valid_until_year` | `integer` \| `null` | Không | Năm hết hiệu lực nếu tiêu chuẩn bị thay thế. Trả về `null` nếu còn Active. | `null` (hoặc `2025`) |
| `status` | `string` | **Có** | Enum: `Active`, `Superseded`, `Under Revision`, `Draft`. | `"Active"` |
| `replaced_by_standard_id` | `string` \| `null` | Không | Mã tiêu chuẩn mới thay thế nếu `status = "Superseded"`. | `"GRI 101"` |
| `superseded_notes` | `string` \| `null` | Không | Ghi chú về lý do và lịch sử thay thế phiên bản. | `"Replaced by GRI 101: Biodiversity 2024"` |

---

### 2.3. Object `scope` (Phạm vi Tác dụng & Quy tắc Áp dụng)

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|
| `target_audience` | `string` | **Có** | Phạm vi đối tượng áp dụng (Tất cả tổ chức / Ngành cụ thể / Theo trọng yếu). | `"Tất cả tổ chức phát thải khí nhà kính"` |
| `sector_code` | `string` \| `null` | Không | Mã ngành nếu là Sector Standard (GRI 11, 12, 13, 14...). | `"GRI 11"` |
| `materiality_required` | `boolean` | **Có** | `true` nếu yêu cầu đánh giá tính trọng yếu mới phải công bố (`false` cho GRI 1, 2). | `true` |
| `boundary_scope` | `string` | **Có** | Phạm vi ranh giới báo cáo (Nội bộ tổ chức, Scope 1, 2, 3, Chuỗi giá trị). | `"Scope 1, 2, 3 & Chuỗi giá trị"` |

---

### 2.4. Object `provenance` (Kiểm toán Xuất xứ File PDF Gốc - P7 First-Class)

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|
| `relative_pdf_path` | `string` | **Có** | Đường dẫn tương đối từ `full_gri/` tới file PDF tài liệu gốc. | `"Full set of GRI Standards - English/GRI 305_ Emissions 2016.pdf"` |
| `file_size_bytes` | `integer` | **Có** | Dung lượng file PDF (Bytes). | `1006697` |
| `page_count` | `integer` | **Có** | Tổng số trang trong tài liệu PDF. | `26` |
| `sha256` | `string` | **Có** | Mã băm SHA256 (64 ký tự hex) kiểm tra tính toàn vẹn của file PDF gốc. | `"e8b42d8fbabdec42e693db1e431690caa419dca77a20823a35fed7e9fa154732"` |
| `indexed_at` | `string` | **Có** | Mốc thời gian đánh chỉ mục hệ thống (ISO 8601 Timestamp). | `"2026-07-25T14:35:50.123456"` |

---

### 2.5. Object in `disclosures` Array (Chi tiết Chỉ số Công bố)

Danh sách `disclosures` chứa các chỉ số công bố thuộc tiêu chuẩn.

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|
| `disclosure_id` | `string` | **Có** | Khóa định danh chỉ số công bố (P1 Identity Key). | `"305-1"` |
| `title_en` | `string` | **Có** | Tên chỉ số công bố (Tiếng Anh). | `"Direct (Scope 1) GHG emissions"` |
| `title_vi` | `string` | **Có** | Tên chỉ số công bố (Tiếng Việt). | `"Phát thải khí nhà kính Trực tiếp (Phạm vi 1)"` |
| `disclosure_type` | `string` | **Có** | Enum: `Management Approach`, `Topic-Specific`, `General Disclosures`. | `"Topic-Specific"` |
| `mandatory` | `boolean` | **Có** | `true` nếu bắt buộc công bố khi tiêu chuẩn là trọng yếu. | `true` |
| `recommendations_en` | `string` \| `null` | Không | Khuyến nghị & hướng dẫn kỹ thuật của GRI (Tiếng Anh). | `"Calculate in metric tons CO2 equivalent using IPCC GWP factors."` |
| `recommendations_vi` | `string` \| `null` | Không | Khuyến nghị & hướng dẫn kỹ thuật của GRI (Tiếng Việt). | `null` |
| `sdg_mapping` | `array[string]` | Không | Danh sách mục tiêu UN SDG tương ứng. | `["SDG 12", "SDG 13"]` |
| `esrs_mapping` | `array[string]` | Không | Danh sách chỉ số ESRS Châu Âu tương ứng. | `["ESRS E1-6 Gross Scope 1 emissions"]` |
| `issb_mapping` | `array[string]` | Không | Danh sách chỉ số IFRS S1/S2 tương ứng. | `["IFRS S2 Climate-related Disclosures"]` |
| `requirements` | `array[object]` | **Có** | Danh sách các khoản yêu cầu chi tiết thuộc Disclosure này. | `[ { ... } ]` |

---

### 2.6. Object in `requirements` Array (Chi tiết Khoản Yêu cầu `RequirementItem`)

Mỗi khoản yêu cầu (a, b, c...) nằm trong mảng `requirements` của một Disclosure.

| Tên Trường (Field) | Kiểu Dữ liệu (Type) | Bắt buộc (Required) | Mô tả Chi tiết | Ví dụ (Example) |
|---|---|---|---|---|
| `requirement_id` | `string` | **Có** | Khóa định danh khoản yêu cầu dạng `<disclosure_id>:<item_code>`. | `"305-1:a"` |
| `item_code` | `string` | **Có** | Mã khoản yêu cầu trong văn bản GRI (`"a"`, `"b"`, `"c"`). | `"a"` |
| `description_en` | `string` | **Có** | Nội dung điều khoản yêu cầu (Tiếng Anh). | `"Gross direct (Scope 1) GHG emissions in metric tons of CO2 equivalent."` |
| `description_vi` | `string` \| `null` | Không | Nội dung điều khoản yêu cầu (Tiếng Việt). | `"Tổng lượng phát thải khí nhà kính trực tiếp (Scope 1)..."` |
| `requirement_type` | `string` | **Có** | Enum: `Quantitative` (KPI số liệu) \| `Qualitative` (Chính sách/Quản trị) \| `Hybrid`. | `"Quantitative"` |
| `unit_of_measure` | `array[string]` | Không | Danh sách các đơn vị đo hợp lệ cho khoản yêu cầu này. | `["metric tons CO2e", "tCO2e"]` |
| `breakdown_dimensions` | `array[string]` | Không | Danh sách các chiều phân rã bắt buộc khi báo cáo số liệu. | `["by Scope", "by facility", "by gas type"]` |

---

## 3. Quy tắc Ánh xạ Đồ thị Neo4j (Knowledge Graph Node & Edge Mapping Rules)

Khi nạp dữ liệu từ `gri_schema.json` vào Neo4j, các trường được chuyển đổi thành các Nút (Nodes) và Quan hệ (Relationships) như sau:

| Đối tượng Schema | Neo4j Label / Type | Thuộc tính chính (Properties) | Phân tầng (Node Tier) |
|---|---|---|---|
| Root Object | `(:Standard)` | `standard_id`, `title_en`, `pillar`, `series` | **T1 — Identity Node (Timeless)** |
| `temporal_validity` | `(:StandardVersion)` | `version_id`, `version_year`, `effective_date`, `status`, `sha256` | **T3 — Version Node** |
| `disclosures` item | `(:GRIDisclosure)` | `disclosure_id`, `title_en`, `disclosure_type`, `mandatory` | **T1 — Identity Node** |
| `requirements` item | `(:GRIRequirement)` | `requirement_id`, `item_code`, `requirement_type` | **T3 — Requirement Node** |
| `(:Standard) -> (:StandardVersion)` | `[:HAS_VERSION]` | `valid_from = effective_date` | Relationship |
| `(:StandardVersion) -> (:StandardVersion)` | `[:SUPERSEDES]` | `valid_from = effective_date` | Relationship |
| `(:StandardVersion) -> (:GRIDisclosure)` | `[:INCLUDES_DISCLOSURE]` | `valid_from = effective_date` | Relationship |
| `(:GRIDisclosure) -> (:GRIRequirement)` | `[:HAS_REQUIREMENT]` | — | Relationship |
| **Doanh nghiệp KPI (T2 Node)** | `(:KPIObservation)` | `valid_from`, `value`, `unit`, `source_id`, `page` | **T2 — Observation Node** |
| `(:KPIObservation) -> (:GRIRequirement)` | `[:COMPLIES_WITH]` | — (P3 Multi-anchoring) | Relationship |

---

## 4. Dữ liệu JSON Mẫu Đầy đủ (Complete JSON Sample Instance)

Dưới đây là một bản ghi mẫu hoàn chỉnh của `GRI 305` tuân thủ đúng `gri_schema.json`:

```json
{
  "node_tier": "T1 — Identity (Thực thể bền phi thời gian)",
  "standard_id": "GRI 305",
  "title_en": "Emissions",
  "title_vi": "Phát thải",
  "pillar": "E — Environmental",
  "series": "Environmental (300 Series)",
  "category": "Topic-Environmental",
  "temporal_validity": {
    "version_id": "GRI_305_2016",
    "version_year": 2016,
    "effective_date": "2018-07-01",
    "valid_until_year": null,
    "status": "Active",
    "replaced_by_standard_id": null,
    "superseded_notes": null
  },
  "scope": {
    "target_audience": "Tất cả tổ chức có hoạt động phát thải khí nhà kính",
    "sector_code": null,
    "materiality_required": true,
    "boundary_scope": "Scope 1, Scope 2, Scope 3 và Chuỗi giá trị"
  },
  "provenance": {
    "relative_pdf_path": "Full set of GRI Standards - English/GRI 305_ Emissions 2016.pdf",
    "file_size_bytes": 1006697,
    "page_count": 26,
    "sha256": "e8b42d8fbabdec42e693db1e431690caa419dca77a20823a35fed7e9fa154732",
    "indexed_at": "2026-07-25T14:35:50.123456"
  },
  "disclosures_count": 1,
  "disclosures": [
    {
      "disclosure_id": "305-1",
      "title_en": "Direct (Scope 1) GHG emissions",
      "title_vi": "Phát thải khí nhà kính Trực tiếp (Phạm vi 1)",
      "disclosure_type": "Topic-Specific",
      "mandatory": true,
      "recommendations_en": "Calculate in metric tons of CO2 equivalent using IPCC GWP values.",
      "recommendations_vi": null,
      "sdg_mapping": ["SDG 12", "SDG 13"],
      "esrs_mapping": ["ESRS E1-6 Gross Scope 1 GHG emissions"],
      "issb_mapping": ["IFRS S2 Climate-related Disclosures"],
      "requirements": [
        {
          "requirement_id": "305-1:a",
          "item_code": "a",
          "description_en": "Gross direct (Scope 1) GHG emissions in metric tons of CO2 equivalent.",
          "description_vi": "Tổng lượng phát thải khí nhà kính trực tiếp (Scope 1) tính bằng tấn CO2 tương đương.",
          "requirement_type": "Quantitative",
          "unit_of_measure": ["metric tons CO2e", "tCO2e"],
          "breakdown_dimensions": ["by Scope", "by facility", "by GHG gas type"]
        }
      ]
    }
  ]
}
```
