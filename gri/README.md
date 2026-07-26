# 📚 GRI Standards Database — Global Reporting Initiative

Bộ dữ liệu cấu trúc các chỉ số tiêu chuẩn **GRI (Global Reporting Initiative Standards)** phục vụ đối soát, trích xuất KPI và xây dựng Knowledge Graph cho hệ thống Graph-RAG ESG.

> **Nguồn dữ liệu chính thức:** Trích xuất trực tiếp từ file [gri-content-index-template-2021.xlsx](file:///b:/capstone/newrepotest/capstone_test1/gri/gri-content-index-template-2021.xlsx) (Version 1.3, January 2026) do GRI phát hành.

---

## 📊 Tổng quan

| Chỉ số | Giá trị |
|---|---|
| Tổng số tiêu chuẩn | **24 Tiêu chuẩn** (8E + 8S + 8G) |
| Tổng số chỉ số công bố (Disclosures) | **104 Chỉ số** |
| Phân loại | **E** (Environmental) · **S** (Social) · **G** (Governance) |

---

## 📁 Cấu trúc Thư mục (theo ESG Pillars)

```
gri/
├── README.md
├── gri-content-index-template-2021.xlsx     # File Excel gốc từ GRI
├── gri_standards_summary.json               # Master Registry Index
│
├── E/                                       # 🌿 Environmental (Môi trường)
│   ├── gri_301_materials_2016.json           #   GRI 301: Materials (3 disclosures)
│   ├── gri_302_energy_2016.json              #   GRI 302: Energy (5 disclosures)
│   ├── gri_303_water_and_effluents_2018.json #   GRI 303: Water & Effluents (5 disclosures)
│   ├── gri_304_biodiversity_2016.json        #   GRI 304: Biodiversity (4 disclosures)
│   ├── gri_305_emissions_2016.json           #   GRI 305: Emissions (7 disclosures)
│   ├── gri_306_waste_2020.json               #   GRI 306: Waste (5 disclosures)
│   ├── gri_307_environmental_compliance_2016.json  #   GRI 307: Environmental Compliance (1 disclosure)
│   └── gri_308_supplier_environmental_assessment_2016.json  #   GRI 308: Supplier Env. Assessment (2 disclosures)
│
├── S/                                       # 👥 Social (Xã hội)
│   ├── gri_401_employment_2016.json          #   GRI 401: Employment (3 disclosures)
│   ├── gri_402_labor_management_relations_2016.json  #   GRI 402: Labor/Mgmt Relations (1 disclosure)
│   ├── gri_403_occupational_health_and_safety_2018.json  #   GRI 403: OHS (10 disclosures)
│   ├── gri_404_training_and_education_2016.json  #   GRI 404: Training & Education (3 disclosures)
│   ├── gri_405_diversity_and_equal_opportunity_2016.json  #   GRI 405: Diversity (2 disclosures)
│   ├── gri_406_non_discrimination_2016.json  #   GRI 406: Non-discrimination (1 disclosure)
│   ├── gri_413_local_communities_2016.json   #   GRI 413: Local Communities (2 disclosures)
│   └── gri_414_supplier_social_assessment_2016.json  #   GRI 414: Supplier Social Assessment (2 disclosures)
│
└── G/                                       # 🏛️ Governance (Quản trị)
    ├── gri_2_general_disclosures_2021.json   #   GRI 2: General Disclosures (30 disclosures)
    ├── gri_3_material_topics_2021.json       #   GRI 3: Material Topics (3 disclosures)
    ├── gri_201_economic_performance_2016.json #   GRI 201: Economic Performance (4 disclosures)
    ├── gri_203_indirect_economic_impacts_2016.json  #   GRI 203: Indirect Economic Impacts (2 disclosures)
    ├── gri_204_procurement_practices_2016.json  #   GRI 204: Procurement Practices (1 disclosure)
    ├── gri_205_anti_corruption_2016.json     #   GRI 205: Anti-corruption (3 disclosures)
    ├── gri_206_anti_competitive_behavior_2016.json  #   GRI 206: Anti-competitive Behavior (1 disclosure)
    └── gri_207_tax_2019.json                 #   GRI 207: Tax (4 disclosures)
```

---

## 📋 Bảng tổng hợp theo trụ cột ESG

### 🌿 E — Environmental (Môi trường) — 8 tiêu chuẩn, 32 disclosures

| Mã | Tên Tiêu chuẩn | Disclosures |
|---|---|---|
| GRI 301 | Nguyên vật liệu 2016 | 3 |
| GRI 302 | Năng lượng 2016 | 5 |
| GRI 303 | Tài nguyên nước và Nước thải 2018 | 5 |
| GRI 304 | Đa dạng sinh học 2016 | 4 |
| GRI 305 | Phát thải 2016 | 7 |
| GRI 306 | Chất thải 2020 | 5 |
| GRI 307 | Tuân thủ môi trường 2016 | 1 |
| GRI 308 | Đánh giá môi trường nhà cung cấp 2016 | 2 |

### 👥 S — Social (Xã hội) — 8 tiêu chuẩn, 24 disclosures

| Mã | Tên Tiêu chuẩn | Disclosures |
|---|---|---|
| GRI 401 | Việc làm 2016 | 3 |
| GRI 402 | Quan hệ lao động / Ban quản lý 2016 | 1 |
| GRI 403 | An toàn và Sức khỏe nghề nghiệp 2018 | 10 |
| GRI 404 | Đào tạo và Giáo dục 2016 | 3 |
| GRI 405 | Đa dạng và Bình đẳng cơ hội 2016 | 2 |
| GRI 406 | Chống phân biệt đối xử 2016 | 1 |
| GRI 413 | Cộng đồng địa phương 2016 | 2 |
| GRI 414 | Đánh giá xã hội nhà cung cấp 2016 | 2 |

### 🏛️ G — Governance (Quản trị) — 8 tiêu chuẩn, 48 disclosures

| Mã | Tên Tiêu chuẩn | Disclosures |
|---|---|---|
| GRI 2 | Công bố thông tin chung 2021 | 30 |
| GRI 3 | Các chủ đề trọng yếu 2021 | 3 |
| GRI 201 | Hiệu quả kinh tế 2016 | 4 |
| GRI 203 | Tác động kinh tế gián tiếp 2016 | 2 |
| GRI 204 | Thực hành mua sắm 2016 | 1 |
| GRI 205 | Chống tham nhũng 2016 | 3 |
| GRI 206 | Hành vi chống cạnh tranh 2016 | 1 |
| GRI 207 | Thuế 2019 | 4 |

---

## 🔗 Ghi chú

- **GRI 208**: Không tồn tại trong hệ thống GRI chính thức — đã bỏ qua.
- **GRI 304** (Biodiversity): Đã bị thay thế bởi GRI 101 Biodiversity 2024 trong bản Excel mới nhất, nhưng vẫn giữ lại theo yêu cầu dự án.
- **GRI 307** (Environmental Compliance): Đã được gộp vào Disclosure 2-27 trong phiên bản mới, nhưng vẫn giữ lại theo yêu cầu dự án.
- Dữ liệu song ngữ Anh-Việt cho mỗi disclosure hỗ trợ LLM trích xuất KPI từ Báo cáo Thường niên tiếng Việt.
