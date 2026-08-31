# 📋 PROJECT OVERVIEW — Greenwashing Detection via Graph-RAG System

> **Tài liệu tổng hợp toàn bộ thông tin dự án.** Đọc file này để hiểu trọn vẹn kiến trúc, pipeline, công nghệ, mô hình dữ liệu đồ thị tri thức (Temporal KG), cơ chế đối soát chéo (Cross-check), giao diện Web ESG Evidence View, và **hướng dẫn chi tiết để nâng cấp, cải thiện hoặc scale data cho nhiều doanh nghiệp mới**.
>
> **Cập nhật mới nhất:** 2026-07-26 (Hoàn thành tích hợp GRI Catalog, NLP Smart Matcher, 3 trụ cột ESG trên Neo4j & Web UI).

---

## 1. Giới thiệu Dự án

### 1.1 Tên dự án
**Greenwashing Detection — Graph-RAG System**

### 1.2 Mô tả tổng quan
Hệ thống **Graph-RAG pipeline** phát hiện dấu hiệu greenwashing (tẩy xanh) ở các doanh nghiệp niêm yết Việt Nam, tập trung vào ngành **Xây dựng / Vật liệu Xây dựng / Bất động sản / Nhựa & Bao bì**. System thực hiện:

1. **Thu thập & Phân loại câu ESG:** Tách câu từ **báo cáo thường niên** (BCTN) và phân loại ESG đa nhãn bằng mô hình **ViDeBERTa-v3-ESG**.
2. **Thu thập Bằng chứng Độc lập:** Crawl tin tức báo chí, quyết định xử phạt, báo cáo kiểm toán độc lập.
3. **Xây dựng Đồ thị Tri thức Thời gian (Temporal Knowledge Graph):** Tự động trích xuất các bộ ba thực thể-quan hệ (triplets), KPI, mốc thời gian bitemporal (`valid_from`, `valid_to`, `recorded_at`).
4. **Chuẩn hóa Chỉ tiêu Quốc tế & Trong nước (StandardIndicator Axis):** Ánh xạ tuyên bố và KPI về hệ chỉ tiêu **Thông tư 96/2020/TT-BTC** và **GRI Standards (Global Reporting Initiative)**.
5. **Đối soát Chéo (Cross-check Adjudication):** Liên kết nội đồ thị giữa *Tuyên bố (Claim)* và *Hành vi thực tế (Conduct)* để phát hiện khoảng cách thông tin.
6. **Hồ sơ Bằng chứng & Giao diện Web (ESG Evidence View):** Xuất hồ sơ đối soát kèm tư vấn (*advisory assessment*) hiển thị trực quan 3 cột (Đã xác nhận / Mâu thuẫn / Chưa đối soát) trên Web UI.

### 1.3 Đặc điểm cốt lõi khác biệt

| Khía cạnh | Thiết kế truyền thống (EmeraldMind) | Dự án này |
|---|---|---|
| Tuyên bố (claim) | Dòng CSV bên ngoài | Node `SustainabilityClaim` **bên trong KG** |
| Bằng chứng | KG chỉ chứa báo cáo doanh nghiệp | KG chứa **cả** tuyên bố (reports) **và** hành vi thực tế (news) |
| Cơ chế phát hiện | Embed query → retrieve → classify | **Liên kết nội đồ thị** claim ↔ conduct → adjudicate |
| Nhãn giám sát | Có gold labels → accuracy | **Không nhãn** → case studies + link-precision |
| Đầu ra | Label phân loại mỗi claim | **Hồ sơ bằng chứng + đánh giá tư vấn** — không kết án tự động |

### 1.4 Ràng buộc thiết kế quan trọng nhất
> **Không tồn tại bộ dữ liệu greenwashing có nhãn cho doanh nghiệp Việt Nam.**

Do đó hệ thống:
- **KHÔNG** phải bộ phân loại điểm greenwashing tự động, **KHÔNG** phán xét hay quy kết tội danh.
- Xuất: **(a)** bằng chứng độc lập kèm trích dẫn gốc (provenance), **(b)** đánh giá tư vấn LLM: `appears_supported` / `appears_contradicted` / `unverified_insufficient_evidence`.
- Quyết định cuối cùng thuộc về **chuyên gia kiểm toán / nhà đầu tư / con người** (Decision-Support System).

---

## 2. Cập nhật Kiến trúc Mới nhất (GRI Catalog & NLP Smart Matcher)

Thực hiện chuẩn hóa theo phản hồi thiết kế (`feedback-gri-catalog.md`):

1. **Chuẩn hóa Catalog GRI phẳng (`config/gri_catalog.json`):**
   - Chuyển cấu trúc cây rườm rà thành bảng tra cứu phẳng keyed theo mã chỉ tiêu chuẩn (ví dụ `"GRI 305-1"`, `"GRI 405-1"`).
   - Định dạng `versions` là danh sách các phiên bản chuẩn.
   - Chuẩn hóa tên Trụ cột tiếng Việt nhất quán: `"Môi trường"`, `"Xã hội"`, `"Quản trị"`.
   - Tự động biên dịch từ 42 file chuẩn GRI chi tiết thành 136 mã chỉ số GRI hoàn chỉnh.

2. **Tái sử dụng Lớp Node `StandardIndicator`:**
   - Không tạo các class thừa (`GRIDisclosure`, `GRIRequirement`, `StandardVersion`). Tất cả chỉ tiêu GRI và TT96 đều dùng chung class `StandardIndicator`.
   - Các cạnh nối giữa `SustainabilityClaim` và `StandardIndicator` được đóng dấu thuộc tính `indicator_axis = "tt96"` hoặc `"gri_fallback"`.

3. **Bộ Lọc Từ Khóa NLP Offline (NLP Smart Matcher):**
   - Thuật toán `match_keyword` trong `run.py indicators` (`src/esg_kg/resolve/indicators.py`) sử dụng chiến lược **Longest-Phrase Matching** ưu tiên cụm từ chuyên môn dài nhất.
   - Giúp tự động gán **636+ cạnh `alignsWithIndicator`** cho hàng nghìn tuyên bố văn xuôi mà **không tốn token AI LLM**.

---

## 3. Ngăn xếp Công nghệ (Technology Stack)

### 3.1 Nền tảng & Hệ thống

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Ngôn ngữ chính | **Python ≥ 3.10** | Toàn bộ pipeline code trong `src/` và `data_processing/` |
| Hệ điều hành phát triển | **Windows / PowerShell** | Hỗ trợ UTF-8 console output |
| Cơ sở dữ liệu Đồ thị | **Neo4j 5 Enterprise** | Chạy trong Docker Container. Bolt: `localhost:8687`, HTTP UI: `localhost:8474` |
| Database Name | `greenwashingkg` | User: `greenwashing`, pass dev local: `nammovuivui` |
| Web Application Server | **Pure Python HTTP Server** | `api/main.py` & `api/evidence_service.py` listening at `http://localhost:8000` |
| Web Frontend | **Vanilla HTML5 / CSS3 / JavaScript** | `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` |

### 3.2 AI/ML Models & Providers

| Model / Provider | Vai trò trong Pipeline | Ghi chú |
|---|---|---|
| **nguyen599/ViDeBERTa-v3-ESG-base** | Phân loại ESG đa nhãn (Môi trường, Xã hội, Quản trị, Trung tính) | Chạy offline GPU trên Kaggle |
| **google-genai / Gemini 2.5 Flash** | Trích xuất bộ ba, trích xuất KPI, phân giải thực thể, đối soát chéo Step 7 | Khóa cấu hình tại `GEMINI_API_KEY` trong `.env` (provider LLM duy nhất — không còn fallback OpenAI, gỡ bỏ hoàn toàn 2026-08-04) |

---

## 4. Kiến trúc Đồ thị Tri thức (Temporal KG Schema)

### 4.1 Mô hình 3 Tầng Thực thể (T1 / T2 / T3)

```
                            [T1 — IDENTITY]
       (Organization)        (Facility)         (StandardIndicator)
       Timeless key          Timeless key        TT96 / GRI Axis
             │                    │                    ▲
             │ claims             │ observedAt         │ alignsWithIndicator /
             ▼                    ▼                    │ measuredUnder
    (SustainabilityClaim)  (KPIObservation) ───────────┘
       [T3 — ASSERTION]     [T2 — OBSERVATION]
```

1. **Tầng T1 — Identity (Thực thể thời gian vĩnh cửu):**
   - Node classes: `Organization`, `Facility`, `Person`, `Product`, `Material`, `Standard`, `Regulation`, `StandardIndicator`, `Location`, `Country`, `Authority`, `Community`.
   - Quy tắc: Khóa danh tính (`identity_keys`) là **timeless** (không chứa mốc thời gian). Lịch sử thay đổi được lưu qua `temporal_versions` và cạnh `supersedes`.

2. **Tầng T2 — Event/Observation (Quan sát & Sự kiện thực tế):**
   - Node classes: `KPIObservation`, `Emission`, `Waste`, `Controversy`, `Penalty`, `MediaReport`, `Investment`, `ThirdPartyVerification`.
   - Quy tắc: Đại diện cho sự việc xảy ra tại mốc thời gian cụ thể. Thuộc tính `valid_from`, `valid_to`, `recorded_at` là thuộc tính bản chất của node.

3. **Tầng T3 — Assertion (Tuyên bố & Mục tiêu của Doanh nghiệp):**
   - Node classes: `SustainabilityClaim`, `Goal`, `Initiative`, `ScienceBasedTarget`, `Certification`, `ClaimKeyword`.
   - Quy tắc: Đại diện cho phát biểu chủ quan. Nối với T1 Organization qua cạnh `claims`, `setsGoal`.

### 4.2 Thống kê Đồ thị Thực tế trên Neo4j (AAA - CTCP Nhựa An Phát Xanh)

- **Tổng số Node:** **12,967 nodes**
- **Tổng số Cạnh (Relationships):** **16,943 relationships**
- **Số lượng Node chính:**
  - `KPIObservation`: 4,906
  - `Organization`: 1,224
  - `SustainabilityClaim`: 1,217
  - `Person`: 938
  - `Goal`: 831
  - `Facility`: 541
  - `Initiative`: 495
  - `Product`: 437
  - `Standard`: 366
  - `Regulation`: 352
  - `StandardIndicator`: 65
- **Số lượng Cạnh đối soát quan trọng:**
  - `alignsWithIndicator`: **636 cạnh** (nối Claim/KPI ➔ Chỉ tiêu TT96/GRI)
  - `reportsKPI`: 4,890
  - `claims`: 1,215
  - `measuredUnder`: 641
  - `verifiedBy` / `llm_supports`: 166
  - `contradictedBy` / `llm_contradicts`: 25
  - `equivalentTo` (TT96 ↔ GRI crosswalk): 26

---

## 5. Quy trình Pipeline Chi tiết (Step 00 ➔ Step 10)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          1. KÊNH INPUT DỮ LIỆU                              │
│  Channel R (Reports): BCTN PDF → PyMuPDF → underthesea → ViDeBERTa ESG       │
│  Channel N (News):    News Crawler → trafilatura → Preprocess → ViDeBERTa    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    2. PIPELINE GRAPH-RAG (src/)                             │
│                                                                             │
│  Step 00 ➔ Graph Quality Report (Kiểm tra Q1-Q8 offline)                    │
│  Step 01 ➔ Extract KPIs (Gemini 2.0 Flash)                                  │
│  Step 02 ➔ Extract Triplets (--source report / --source news)               │
│  Step 03 ➔ Validate & Repair Triplets (Auto-fix + ISO Date Canonicalize)    │
│  Step 03b➔ Anchor KPI → Facility (Gazetteer matching)                       │
│  Step 03c➔ Canonicalize KPIs (Ánh xạ 35 mã KPI chuẩn)                       │
│  Step 04 ➔ Build Issuer Registry (Danh mục công ty niêm yết)                │
│  Step 04b➔ Build Standards Registry (Danh mục tiêu chuẩn TT96/GRI)           │
│  Step 05 ➔ Entity Resolution (4 Stage: A Deterministic → B Blocking        │
│             → C LLM Adjudicate → D Consolidate)                             │
│  Step 05b➔ Stamp Provenance (Gán source_doc, source_page offline)           │
│  Step 05c➔ Link Standard Indicators (Tích hợp GRI Catalog + NLP Matcher)    │
│  Step 05d➔ Align Claims to Indicators (LLM Semantic Alignment - Optional)   │
│  Step 06 ➔ Load Graph to Neo4j (Nạp Property Graph vào Neo4j)              │
│  Step 07 ➔ Cross-check Claims vs Conduct (THE ANALYTICAL CORE)             │
│  Step 07b➔ Enrich Dossiers (Tính điểm Softmax Balance & Caveats)            │
│  Step 08 ➔ Sync Cross-check to Neo4j (Đẩy advisory layer vào Neo4j)         │
│  Step 09 ➔ Report Claim Ledger (Xuất Sổ nhật ký Tuyên bố)                   │
│  Step 10 ➔ Evaluate (Đánh giá Coverage, Case Studies, Ablation)             │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     3. LỚP HIỂN THỊ WEB APP (ESG Evidence View)             │
│  Python Server: `python api/main.py` ➔ http://localhost:8000                │
│  Giao diện 3 cột: Đã xác minh (Verified) | Mâu thuẫn (Contradicted) | Thiếu │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Giao diện Web ESG Evidence View (`api/main.py`)

### 6.1 Cấu trúc Giao diện 3 Cột Đối soát
Khi truy cập `http://localhost:8000`, hệ thống cung cấp giao diện trực quan cho nhà đầu tư và kiểm toán viên:

1. **🌿 Môi trường (Environment):** Hiển thị 78+ tuyên bố.
   - **Đã xác nhận (Verified):** Tuyên bố được báo chí/bên thứ ba xác nhận (ví dụ: Sản xuất xanh, chứng nhận bao bì sinh học).
   - **Thực tế khác biệt (Contradicted - Greenwashing Alert):** Tuyên bố mâu thuẫn trực tiếp với bằng chứng (ví dụ: Tuyên bố công suất 108,000 tấn/năm trong khi báo cáo xuất khẩu thực tế chỉ đạt 96,000 tấn/năm).
   - **Chưa đối soát (Missing Evidence):** Tuyên bố chưa tìm thấy bằng chứng độc lập để đối chứng.
2. **👥 Xã hội (Social):** Hiển thị 52+ tuyên bố về an toàn lao động, tỷ lệ nữ quản lý, đào tạo và an sinh cộng đồng.
3. **🏛 Quản trị (Governance):** Hiển thị đầy đủ các tuyên bố về cơ cấu HĐQT (`GRI 2-9`), quản trị rủi ro (`GRI 2-14`), quan hệ nhà đầu tư (`GRI 2-29`), và đạo đức chống tham nhũng (`GRI 205-1`).

---

> *Tài liệu này được cập nhật hoàn chỉnh và đồng bộ 100% với cấu trúc codebase thực tế của dự án. Khi thực hiện nâng cấp kiến trúc, hãy cập nhật lại thông tin vào tài liệu này.*
