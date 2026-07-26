# 📚 GRI Standards Full Database & Enterprise Schema

Thư mục này chứa cơ sở dữ liệu hoàn chỉnh của bộ tiêu chuẩn **GRI Standards (Global Reporting Initiative)** được cấu trúc hóa theo kiến trúc **Temporal Knowledge Graph** (Mô hình 3 tầng Node T1, T2, T3) phục vụ đối soát Greenwashing cho các doanh nghiệp niêm yết tại Việt Nam.

> **Tài liệu Hướng dẫn Chi tiết Kiến trúc:** [`docs/GRI_MASTER_SCHEMA_DOCUMENTATION.md`](file:///b:/capstone/newrepotest/capstone_test1/docs/GRI_MASTER_SCHEMA_DOCUMENTATION.md)  
> **Khung Nguyên tắc Temporal KG:** [`docs/TEMPORAL_KG_DESIGN.md`](file:///b:/capstone/newrepotest/capstone_test1/docs/TEMPORAL_KG_DESIGN.md)

---

## 📁 Cấu trúc Thư mục

```
gri/full_gri/
├── README.md                                    # File Hướng dẫn này
├── gri_schema.json                              # JSON Schema (Draft-07)
├── gri_schema.py                                # Python Pydantic Models & Neo4j Cypher Ingestion Generator
├── manifest.json                                # Master Catalog đánh chỉ mục 42 file PDF (SHA256, số trang)
├── Full set of GRI Standards - English/          # Thư mục gốc chứa 42 file PDF tiêu chuẩn GRI chính thức
└── json/                                        # Thư mục chứa 42 file JSON chuẩn đã trích xuất & cấu trúc
    ├── gri_1_2021.json                          # GRI 1: Foundation 2021
    ├── gri_2_2021.json                          # GRI 2: General Disclosures 2021
    ├── gri_3_2021.json                          # GRI 3: Material Topics 2021
    ├── gri_101_2024.json                        # GRI 101: Biodiversity 2024 (Mới thay thế GRI 304)
    ├── gri_102_2025.json                        # GRI 102: Climate Change 2025
    ├── gri_103_2025.json                        # GRI 103: Energy 2025
    ├── gri_11_2021.json                         # GRI 11: Oil & Gas Sector Standard 2021
    ├── gri_305_2016.json                        # GRI 305: Emissions 2016
    └── ... (tổng cộng 42 file JSON)
```

---

## 📐 Cấu trúc 3-Tier Node trong Schema

1. **Node T1 — Standard Identity (`:Standard`):** Khóa `standard_id` phi thời gian (`"GRI 305"`). Không bị phân mảnh theo năm.
2. **Node T3 — Version (`:StandardVersion`):** Khóa `version_id` (`"GRI_305_2016"`), lưu ngày có hiệu lực `effective_date`, trạng thái `status` (`Active`/`Superseded`).
3. **Node T1 — Disclosure (`:GRIDisclosure`):** Khóa `disclosure_id` (`"305-1"`).
4. **Node T3 — Requirement (`:GRIRequirement`):** Khóa `requirement_id` (`"305-1:a"`), phân loại `Quantitative` vs `Qualitative`.
5. **Node T2 — Observation (`:KPIObservation`):** KPI do LLM trích xuất từ báo cáo công ty, kết nối theo cơ chế **P3 Multi-anchoring**:
   `(:Organization)-[:REPORTS_KPI]->(:KPIObservation)-[:COMPLIES_WITH]->(:GRIRequirement)`.

---

## 🛠️ Lệnh Khởi chạy & Tái đánh chỉ mục (Re-index)

Để quét lại 42 file PDF và tái khởi tạo toàn bộ 42 file JSON + `manifest.json`:

```bash
python gri/crawl_full_gri.py
```
