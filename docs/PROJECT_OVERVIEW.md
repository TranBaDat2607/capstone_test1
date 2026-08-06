# 📋 PROJECT OVERVIEW — Greenwashing Detection via Graph-RAG System

> **Tài liệu tổng hợp toàn bộ thông tin dự án.** Đọc file này để hiểu trọn vẹn kiến trúc, pipeline, công nghệ, mô hình dữ liệu đồ thị tri thức (Temporal KG), cơ chế đối soát chéo (Cross-check), giao diện Web ESG Evidence View, và **hướng dẫn chi tiết để nâng cấp, cải thiện hoặc scale data cho nhiều doanh nghiệp mới**.
>
> **Cập nhật mới nhất:** 2026-08-05 — đồng bộ lại với codebase sau khi hoàn tất **refactor `src/esg_kg/`** (16/16 stage, chạy qua dispatcher `python src/run.py`), gỡ bỏ 3 stage (04b / 07b / 10), bổ sung **BLOCK** `build_validated` / `build_resolved`, stage **`export_kgc`**, đường dẫn **provider OpenAI** cho các stage LLM, và cơ chế **đồng bộ dữ liệu qua Hugging Face** (`data_version.json`).
>
> **Cảnh báo khi đọc số liệu:** mọi thống kê đồ thị trong tài liệu này là của **bản pilot 1 doanh nghiệp (AAA)**. Corpus đã mở rộng lên **115 doanh nghiệp** ở tầng phân loại câu, nhưng đồ thị **chưa được dựng lại cho toàn ngành** — xem §9.

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

Hệ quả trực tiếp trong code: stage **step10 (P6 evaluation)** và **step07b (softmax evidence-balance score)** đã bị **gỡ bỏ khỏi dự án** (2026-07-28 / 2026-07-29) vì cả hai đều là hình thức "đo bằng điểm số" mà không có ground truth để neo vào. Xem §5.3.

---

## 2. Cập nhật Kiến trúc Mới nhất (2026-07/08)

### 2.1 Refactor `src/` phẳng → package `src/esg_kg/` (HOÀN TẤT)

Trước đây stage C là **một file phẳng cho mỗi bước**: `src/step00_*.py` … `src/step10_*.py`. Toàn bộ đã được refactor thành package thật và **cây cũ đã bị xóa hẳn ngày 2026-07-29**.

- Chạy qua **dispatcher duy nhất**: `python src/run.py <stage> [args]` (từ repo root).
- `python src/run.py --list` là **nguồn sự thật sống** về danh sách stage — nó đọc từ import system, không phải từ danh sách chép tay.
- Tiền tố `stepNN_` chỉ còn là **nhãn lịch sử** (`old_step` trong `esg_kg/pipeline.py`), giữ lại vì nó mã hóa thứ tự chạy và vẫn dùng được: `python src/run.py 05b`.
- **Không còn file `src/stepNN_*.py` nào tồn tại.** Mọi câu trong `docs/` nhắc tới đường dẫn dạng đó là mô tả cây cũ, không phải code hiện tại.
- Các stage dùng chung helper qua `esg_kg/core/`: `paths`, `io_jsonl`, `llm`, `schema`, `naming`, `dates`, `identity`, `graph_patch`. **Không stage nào import nội bộ của stage khác nữa.**

### 2.2 BLOCK — gộp các stage cùng ghi một artifact

Quy tắc (DESIGN.md §5.7): *khi N stage cùng đọc-rồi-ghi một file, chúng không phải N stage — chúng là một.* File trung gian vốn là state nội bộ bị rò rỉ thành contract, và chạy lại stage đầu sẽ **âm thầm phá hủy** kết quả các stage sau đã thêm vào (kể cả kết quả đã trả tiền LLM).

| Block | Thành phần | Artifact ghi **một lần** |
|---|---|---|
| `build_validated` | 03 → 03b → 03c | `graph_output/validated/all_validated_triples.json` |
| `build_resolved` | 05 → 05b → 05c | `graph_output/resolved/resolved_graph.json` |

Hai ràng buộc bảo đảm an toàn: **(1)** mọi stage thành viên vẫn chạy riêng được (mất khả năng chạy lẻ = mất khả năng chẩn đoán); **(2)** chỉ cache kết quả **có trả phí và không tất định** (LLM repair ở 03, LLM adjudication Stage C ở 05), không cache embedding (chỉ tốn tiền chứ vẫn tất định).

### 2.3 Stage mới: `export_kgc` (step11, phần hub-decomposition)

Đọc `resolved_graph.json` **CHỈ ĐỌC** và ghi ra một artifact **hoàn toàn tách biệt** `graph_output/export_kgc/` phục vụ view export cho SSRL/RL — **không bao giờ** patch `resolved_graph.json` hay Neo4j (ranh giới P6).

Mỗi cụm `Organization` khớp `config/issuer_registry.json` có tổng bậc vượt `--max-bucket-degree` (mặc định 500) sẽ được phân rã: các cạnh gom vào node tổng hợp `HubBucket` khóa theo `(năm, predicate)`. Đo trên đồ thị AAA thật: **bậc lớn nhất 9,511 → 542** (357 bucket). `HubBucket` **không** được thêm vào `config/schema.json` — nó là artifact dựng dataset, không phải thực thể T1/T2/T3.

### 2.4 Đường dẫn provider OpenAI cho các stage LLM

Do **Gemini đang bị chặn thanh toán**, code đã dịch chuyển sang OpenAI ở những chỗ có lựa chọn:

- `extract`, `extract_triples`, `fix_triples`, `entities` nhận cờ **`--provider {gemini,openai}`** (mặc định vẫn `gemini`, nên lệnh cũ không đổi). Thêm cờ này để chạy được end-to-end trên `gpt-4o-mini` (hoặc endpoint tương thích OpenAI qua `--openai-base-url`) trong lúc Gemini bị chặn.
- `claims_vs_conduct` (step07): **OpenAI là provider DUY NHẤT còn lại** — hỗ trợ Gemini đã bị gỡ hẳn vì project sau `GEMINI_API_KEY` trả 403 vĩnh viễn. Truyền `gemini` sẽ chỉ ghi log "Unknown adjudication provider — ignored". **Đừng lên kế hoạch fallback Gemini ở đây.**
- `entities` thường được chạy với `--no-llm` (chỉ Stage A + B.1 — không embedding blocking, không adjudication).

### 2.5 Chuẩn hóa Catalog GRI & NLP Smart Matcher

1. **Catalog GRI phẳng (`config/gri_catalog.json`)** — bảng tra cứu phẳng keyed theo mã chỉ tiêu (`"GRI 305-1"`, `"GRI 405-1"`), `versions` là danh sách phiên bản, tên trụ cột tiếng Việt nhất quán (`"Môi trường"` / `"Xã hội"` / `"Quản trị"`). Biên dịch tự động từ 42 file chuẩn GRI thành **136 mã chỉ số** (bản đang commit; cây làm việc hiện có bản dựng lại **145 mã** chưa commit).
2. **Tái sử dụng class `StandardIndicator`** — không tạo class thừa (`GRIDisclosure`, `GRIRequirement`, `StandardVersion`). Chỉ tiêu GRI và TT96 dùng chung một class; cạnh nối được đóng dấu `indicator_axis = "tt96"` hoặc `"gri_fallback"`.
3. **Bộ lọc từ khóa NLP offline** — `match_keyword` trong stage `indicators` (`esg_kg/resolve/indicators.py`) dùng **Longest-Phrase Matching**, tự gán **639 cạnh `alignsWithIndicator`** cho hàng nghìn tuyên bố văn xuôi mà **không tốn token LLM**.
4. **Quy tắc sở hữu disclosure (bẫy đã sập một lần):** file JSON của một chuẩn GRI còn liệt kê lại disclosure thuộc **chuẩn khác** (GRI 11–14 và các bản viết lại 101–103 đều làm vậy). Một disclosure phải được quy về chuẩn có `standard_id` là **tiền tố** của nó (`standard_of()`), **không phải** file nào đọc trước. Sai quy tắc này từng gán nhầm **80/136** mục và làm hỏng 31 tiêu đề. Đã khóa bằng `test/test_gri_catalog_build.py`.

### 2.6 Cải thiện chất lượng đồ thị (nhánh increase-depth-of-graph)

- **`claim_id` tất định** ở `extract_triples` (C1, issue #2) — điều kiện tiên quyết để có thể trích xuất lại toàn bộ đồ thị mà không làm hỏng các dossier đã trả tiền.
- **Merge entity theo khớp một phần identity-key** ở `entities` (B1).
- **Cạnh `mentionsFacility`** vào schema; `MediaReport` được neo ngay ở thời điểm trích xuất (C2/B2).

---

## 3. Ngăn xếp Công nghệ (Technology Stack)

### 3.1 Nền tảng & Hệ thống

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Ngôn ngữ chính | **Python ≥ 3.10** | Pipeline trong `src/esg_kg/`, `data_processing/`, `esg_news_crawler/`, `crawl_data/` |
| Hệ điều hành phát triển | **Windows / PowerShell** | Hỗ trợ UTF-8 console output (`ensure_utf8_stdout`) |
| Cơ sở dữ liệu Đồ thị | **Neo4j 5 Enterprise** | Docker (`docker-compose.yml`). Bolt: `localhost:8687`, HTTP UI: `localhost:8474` |
| Database Name | `greenwashingkg` | User: `greenwashing`, pass dev local: `nammovuivui` (đổi trước khi dùng ngoài local) |
| Web Application Server | **Pure Python `http.server`** | `api/main.py` + `api/evidence_service.py` tại `http://localhost:8000` — cố tình **không** dùng FastAPI/Flask để tránh lệch phiên bản framework |
| Web Frontend | **Vanilla HTML5 / CSS3 / JavaScript** | `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` |
| Đồng bộ dữ liệu sinh ra | **Hugging Face Dataset repo** | `nammovuivui-capstone/capstone`, pin revision trong `data_version.json` (§7) |
| Giải nén archive | **UnRAR.exe / 7z.exe** | `crawl_data/extract_archives.py` gọi ra ngoài — cài WinRAR + 7-Zip riêng |

### 3.2 AI/ML Models & Providers

| Model / Provider | Vai trò trong Pipeline | Ghi chú |
|---|---|---|
| **nguyen599/ViDeBERTa-v3-ESG-base** | Phân loại ESG đa nhãn (Môi trường / Xã hội / Quản trị / Trung tính) | Chạy GPU trên Kaggle (`notebooks/kaggle_esg_classify.ipynb`); bản CPU cùng logic ở `data_processing/esg_classifier.py`. **Torch cố tình không có trong `requirements.txt`** |
| **google-genai / `gemini-2.5-flash`** | Trích xuất KPI (01), trích xuất triplet (02), sửa triplet (03), adjudication entity resolution (05) | `GEMINI_API_KEY` trong `.env`. **Hiện đang bị chặn thanh toán** |
| **`gemini-embedding-001`** (768 chiều) | Blocking ngữ nghĩa Stage B của entity resolution | Cùng trạng thái chặn; thực tế đang chạy `entities --no-llm` |
| **OpenAI `gpt-4o-mini`** | **Provider duy nhất** cho đối soát chéo (07); provider tùy chọn cho 01/02/03/05 và `align_claims` (05d) | `OPENAI_API_KEY` trong `.env`; `--openai-base-url` cho endpoint tương thích OpenAI |

### 3.3 Dependency cố tình *không* khai báo (import lười)

Mỗi thư viện dưới đây suy biến nhẹ nhàng khi vắng mặt, để một bản clone trắng vẫn chạy được — **cài theo nhu cầu, đừng thêm vào `requirements.txt`**:

| Thư viện | Dùng ở | Khi thiếu |
|---|---|---|
| `huggingface_hub` | `esg_kg/core/datasync.py` | Chỉ mất tính năng đồng bộ dữ liệu |
| `rapidfuzz` | tầng fuzzy của stage `canonicalize` | Tắt tầng fuzzy kèm cảnh báo |
| `openai` | `claims_vs_conduct`, và các stage chạy `--provider openai` | Chỉ mất đường dẫn OpenAI |
| `torch` | `data_processing/esg_classifier.py` (bản CPU) | Dùng notebook Kaggle thay thế |

---

## 4. Kiến trúc Đồ thị Tri thức (Temporal KG Schema)

Nguồn sự thật duy nhất: **`config/schema.json`** — ~28 node class và ~50 nhãn cạnh có hướng.

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

> **Bảng phân tầng dưới đây chép từ `T1_CLASSES` / `T2_CLASSES` / `T3_CLASSES` trong `esg_kg/report/quality.py`** — đó là nơi khai báo duy nhất. `test/test_schema_contract.py` **import** bảng này từ step00 (không khai báo lại) và assert mọi class thuộc **đúng một** tầng. Nếu sửa tầng, sửa ở code trước.

1. **Tầng T1 — Identity (Thực thể thời gian vĩnh cửu):**
   - Node classes: `Organization`, `Person`, `Facility`, `Product`, `Material`, `Location`, `Country`, `Standard`, `Regulation`, `Authority`, `Community`, `ClaimKeyword`, `Certification`, `StandardIndicator`.
   - Quy tắc **P1**: khóa danh tính (`identity_keys`) là **timeless** — **không bao giờ** đưa trường thời gian (`valid_from`, `valid_to`, `is_current`, `recorded_at`, `date`, `year`, `target_year`, `baseline_year`, `validity_period`) vào `identity_keys` của class T1. Stage `quality` (step00) lint điều này cho **mọi** class T1, không chỉ vài class cố định. Lịch sử thay đổi lưu qua `temporal_versions` + cạnh `supersedes`.
   - `StandardIndicator` là **từ vựng có kiểm soát** sinh từ `kpi_definitions_construction.json` / `gri_catalog.json`, không phải thực thể trích từ văn bản. Nó **cố tình có bậc cao** (mọi KPI của một chỉ tiêu treo vào một node) nên bị **loại khỏi các chỉ số hub/path của Q7** — tính vào sẽ là đo từ vựng chứ không đo đồ thị.

2. **Tầng T2 — Event/Observation (Quan sát & Sự kiện thực tế):**
   - Node classes: `KPIObservation`, `Emission`, `Waste`, `Penalty`, `Controversy`, `MediaReport`, `ThirdPartyVerification`, `Investment`, `Project`, `Initiative`, `CarbonOffsetProject`.
   - Các class quan sát **hợp lệ khi mang thời gian trong identity_keys** và được version theo từng quan sát (khác hẳn T1: T1 chỉ version khi thuộc tính đổi).
   - Class quan sát **từ tin tức** (`KPIObservation`, `Controversy`, `Penalty`, `MediaReport`) bắt buộc có cờ `date_uncertain`: `false` khi bài báo nêu mốc thời gian rõ ràng, `true` khi phải lấy ngày đăng bài làm proxy (**không bao giờ âm thầm giả định năm đăng**). Step07 chuyển cờ này thành **caveat** trên dossier.

3. **Tầng T3 — Assertion (Tuyên bố & Mục tiêu của Doanh nghiệp):**
   - Node classes: `SustainabilityClaim`, `Goal`, `ScienceBasedTarget`.
   - Nối với T1 `Organization` qua cạnh `claims`, `setsGoal`.
   - *Lưu ý:* `Initiative`, `Certification`, `ClaimKeyword` **không** ở T3 (tài liệu bản cũ xếp nhầm) — theo code chúng lần lượt thuộc T2 / T1 / T1.

**Bất biến thời gian khác:** ở bước trích xuất (02/03) **mọi node** mang `valid_from` / `valid_to` / `is_current`, **mọi cạnh** mang `temporal_metadata`. Sang đồ thị **đã resolve** (05+), thời gian chỉ sống trên **cạnh và node T2/T3** (P2) — node thực thể T1 là timeless. Ngày ở dạng ISO chuẩn `YYYY[-MM[-DD]]` (03 phase 1.5); một chuỗi version còn mở có **đúng một** `is_current=true` (P4).

### 4.2 Thống kê Đồ thị Thực tế — bản pilot AAA (CTCP Nhựa An Phát Xanh)

> Số liệu dưới đây đọc trực tiếp từ `graph_output/resolved/resolved_graph.json` (build 2026-07-26). Đây là **đồ thị đã resolve**, chưa nạp Neo4j — số node trên Neo4j **cao hơn** vì loader sinh thêm chuỗi version node cho các class supersedes-legal, và step08 còn đắp thêm lớp advisory.

**Tổng quan:** **10,425 node / 14,402 cạnh** (đầu vào 14,677 triple → giảm 26.2% node nhờ entity resolution; 3,790 cụm thực thể cuối cùng).

| Node class | Số lượng | | Nhãn cạnh | Số lượng |
|---|---:|---|---|---:|
| `KPIObservation` | 4,906 | | `reportsKPI` | 4,890 |
| `SustainabilityClaim` | 1,217 | | `claims` | 1,215 |
| `Goal` | 722 | | `setsGoal` | 784 |
| `Initiative` | 495 | | `locatedIn` | 743 |
| `Organization` | 438 | | `worksAt` | 742 |
| `Investment` | 282 | | `measuredUnder` | 641 |
| `Facility` | 277 | | **`alignsWithIndicator`** | **639** |
| `Project` | 255 | | `takesPartIn` | 553 |
| `Location` | 248 | | `ownsFacility` | 424 |
| `Regulation` | 220 | | `producedBy` | 320 |
| `Product` | 215 | | `adoptsStandard` | 315 |
| `Standard` | 212 | | `subjectToRegulation` | 306 |
| `Person` | 196 | | `observedAtFacility` | 304 |
| `ClaimKeyword` | 141 | | `investsIn` | 298 |
| `Community` | 110 | | `isIn` | 295 |
| `Certification` | 92 | | `partnersWith` | 236 |
| `MediaReport` | 91 | | `holdsCertification` | 166 |
| `Material` | 74 | | `hasKeyword` | 163 |
| **`StandardIndicator`** | **67** | | `impactsCommunity` | 147 |
| `Authority` | 58 | | `partOf` | 102 |

**Trục chỉ tiêu (`StandardIndicator`, 67 node):** TT96 Phụ lục IV Mục 6: **19** · SSC-IFC: **14** · GRI Standards: **32** · QĐ 2171: **1** · QCVN 09: **1**.
Phân bố trụ cột: Môi trường **31** · Xã hội **22** · Quản trị **14**.

**639 cạnh `alignsWithIndicator`** đi từ: `SustainabilityClaim` 284 · `Goal` 206 · `Initiative` 149 — và trỏ tới chỉ tiêu thuộc trụ cột: Quản trị **285** · Môi trường **184** · Xã hội **170**.

**Cạnh đối soát (sinh bởi step07, lưu ở `graph_output/crosscheck/crosscheck_edges.json`, không nằm trong `resolved_graph.json`):** tổng **152** cạnh — `verifiedBy` **151**, `contradictedByMedia` **1**.

### 4.3 Kết quả đối soát chéo (AAA)

Từ `graph_output/crosscheck/aaa_crosscheck_stats.json`:

| Chỉ số | Giá trị |
|---|---:|
| Tổng tuyên bố đưa vào đối soát | 1,093 |
| Kho bằng chứng conduct | 124 (`KPIObservation` 108, `MediaReport` 16) |
| Tuyên bố có ứng viên bằng chứng | 748 (3,461 cặp, TB 3.17 ứng viên/claim) |
| `unverified_insufficient_evidence` | **1,001** |
| `appears_supported` | **70** |
| `appears_contradicted` | **22** |
| Lượt adjudication LLM | 3,461 (openai, 0 lỗi) |

> **Caveat bắt buộc kèm mọi báo cáo:** bằng chứng conduct độc lập còn **mỏng** — *vắng mâu thuẫn KHÔNG phải là minh oan* (`docs/SYSTEM_DESIGN.md` §8.3). Đây chính là lý do 91.6% tuyên bố rơi vào `unverified`.

### 4.4 Báo cáo chất lượng đồ thị (Q1–Q8, offline)

Stage `quality` chấm 8 thuộc tính chất lượng, chạy **trước và sau** mọi thay đổi schema/pipeline với `--label`. Ảnh chụp gần nhất (`after-pillar-fix`):

| # | Thuộc tính | Số liệu chính |
|---|---|---|
| Q1 | Accuracy | tên không chuẩn NFC: 0; tên vỡ OCR: 51 |
| Q2 | Consistency | **1** vi phạm (cạnh sai schema 0, ngày không ISO 0, from>to **1**, chuỗi is_current hỏng 0, T1 mang thời gian trong identity 0) |
| Q3 | Conciseness | node T1 trùng dư: 62; `Standard`: 212 |
| Q4 | Completeness | Controversy 2 / Penalty 4 / MediaReport 91 / KPI từ news 108 |
| Q5 | Timeliness | cạnh có `valid_from` 96.9%; node T2 có `valid_from` 87.7%; T2 từ news có `date_uncertain` **100%** |
| Q6 | Provenance | node có `source_type` 98.9%; KPI có `source_id` phân tích được 32.9% |
| Q7 | Traversability | bậc trung vị 1; node lá 70.7%; masked-answerable 41.3%; claim→conduct cấu trúc 8.0%; T2 bậc≥2 21.6% |
| Q8 | Independence | conduct theo kênh: report 81 / news 124 |

---

## 5. Quy trình Pipeline Chi tiết

### 5.1 Sơ đồ tổng thể

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          1. KÊNH INPUT DỮ LIỆU                              │
│  Channel R (Reports): BCTN PDF → PyMuPDF → underthesea → ViDeBERTa ESG      │
│  Channel N (News):    News Crawler → trafilatura → Preprocess → ViDeBERTa   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              2. PIPELINE GRAPH-RAG  (python src/run.py <stage>)             │
│                                                                             │
│  quality          (00)  Báo cáo chất lượng Q1–Q8 (offline, không LLM/DB)    │
│  extract          (01)  Trích xuất KPI theo trang (LLM)                     │
│  extract_triples  (02)  Trích xuất triplet (--source report | news) (LLM)   │
│  ┌── BLOCK build_validated ────────────────────────────────────────────┐   │
│  │ fix_triples   (03)  Validate + sửa hướng cạnh + chuẩn hóa ngày ISO   │   │
│  │ anchor_kpi    (03b) Neo KPI → Facility bằng gazetteer (offline)      │   │
│  │ canonicalize  (03c) Gán kpi_id chuẩn từ bộ 35 chỉ tiêu (offline)     │   │
│  └──────────────── ghi all_validated_triples.json MỘT LẦN ─────────────┘   │
│  issuer           (04)  Dựng issuer_registry.json (run-once, người xác nhận)│
│  ┌── BLOCK build_resolved ─────────────────────────────────────────────┐   │
│  │ entities      (05)  Entity resolution (Stage A→B→C→D)                │   │
│  │ provenance    (05b) Đóng dấu source_doc / source_page (offline)      │   │
│  │ indicators    (05c) Trục chỉ tiêu TT96 + GRI Catalog (offline)       │   │
│  └──────────────── ghi resolved_graph.json MỘT LẦN ────────────────────┘   │
│  align_claims     (05d) Gán chỉ tiêu cho claim còn sót (LLM, TÙY CHỌN)      │
│  export_kgc       (11)  Phân rã hub → view export SSRL (offline, CHỈ ĐỌC)   │
│  neo4j_load       (06)  Nạp property graph vào Neo4j                        │
│  claims_vs_conduct(07)  ĐỐI SOÁT CHÉO — LÕI PHÂN TÍCH (LLM bắt buộc)        │
│  neo4j_sync       (08)  Đẩy lớp advisory vào Neo4j (không LLM)              │
│  claim_ledger     (09)  Xuất Sổ nhật ký Tuyên bố (chỉ đọc Neo4j)            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     3. LỚP HIỂN THỊ WEB APP (ESG Evidence View)             │
│  Python Server: `python api/main.py` ➔ http://localhost:8000                │
│  Giao diện 3 cột: Đã xác minh (Verified) | Mâu thuẫn (Contradicted) | Thiếu │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Bảng stage (16/16 sẵn sàng — `python src/run.py --list`)

| step | Tên stage | Module | Ghi chú |
|---|---|---|---|
| 00 | `quality` | `esg_kg.report.quality` | offline; chạy TRƯỚC và SAU mọi thay đổi |
| 01 | `extract` | `esg_kg.kpi.extract` | LLM |
| 02 | `extract_triples` | `esg_kg.graph.extract_triples` | LLM; `--source report\|news` |
| 03 | `fix_triples` | `esg_kg.graph.fix_triples` | validate + repair + aggregate |
| 03b | `anchor_kpi` | `esg_kg.graph.anchor_kpi` | offline; sau 03, trước 03c |
| 03c | `canonicalize` | `esg_kg.kpi.canonicalize` | offline; sau 03b, trước 04 |
| 04 | `issuer` | `esg_kg.registry.issuer` | run-once; ghi file config **có người sửa tay** |
| 05 | `entities` | `esg_kg.resolve.entities` | entity resolution |
| 05b | `provenance` | `esg_kg.resolve.provenance` | offline; sau 05 |
| 05c | `indicators` | `esg_kg.resolve.indicators` | offline; sau 05b |
| 05d | `align_claims` | `esg_kg.resolve.align_claims` | **LLM tùy chọn**; sau 05c |
| 06 | `neo4j_load` | `esg_kg.load.neo4j_load` | cần Neo4j đang chạy |
| 07 | `claims_vs_conduct` | `esg_kg.crosscheck.claims_vs_conduct` | LLM **bắt buộc**, không có fallback tất định |
| 08 | `neo4j_sync` | `esg_kg.load.neo4j_sync` | lớp advisory → Neo4j |
| 09 | `claim_ledger` | `esg_kg.report.claim_ledger` | **chỉ đọc Neo4j**; chạy sau 08 |
| 11 | `export_kgc` | `esg_kg.export.export_kgc` | offline; chạy sau `build_resolved` |

**Không phải stage:**
- `config/standards_registry.json` — **config tĩnh**, sửa tay. Không script nào sinh ra nó; stage `quality` có mục `standards_registry_audit` báo cáo các cách viết chưa được phủ.
- `gri/build_gri_catalog.py` — builder run-once cho `config/gri_catalog.json`. Nó **không đọc output pipeline nào** nên không tạo vòng lặp; dựng lại bằng tay rồi commit JSON đã sinh.
- `esg_kg/core/datasync.py` — tiện ích đồng bộ dữ liệu (§7).

### 5.3 Ba stage đã bị GỠ BỎ (không có lệnh thay thế)

| Stage cũ | Ngày gỡ | Lý do |
|---|---|---|
| `step10` — báo cáo đánh giá P6 | 2026-07-28 | Dự án bỏ hẳn kiểu đo coverage/case-study/ablation không ground truth khỏi danh mục sản phẩm |
| `step04b` — reseed standards registry | 2026-07-29 | Nó đọc output của step05 trong khi step05 đọc output của nó (**vòng lặp**), và mọi alias vốn là seed hardcode |
| `step07b` — điểm softmax evidence-balance | 2026-07-29 | Không màn hình nào trên UI đọc `assessment_scores`; `assessment` phân loại từ step07 luôn là output chính |

### 5.4 Chi tiết đáng lưu ý trong từng stage

- **`extract` (01):** chỉ gửi lên LLM các trang có ≥1 câu `esg=true`; dùng `kpi_definitions_construction.json` làm từ vựng KPI có kiểm soát.
- **`fix_triples` (03):** Phase 1 offline (đảo hướng cạnh + validate schema) → Phase 1.5 offline (chuẩn hóa ngày ISO, cảnh báo `valid_from > valid_to`, mặc định `date_uncertain` cho node T2 từ news) → Phase 2 LLM (sửa lô triple sai) → Phase 3 gộp. Cờ `--renormalize` chỉ chạy Phase 1.5 trên file đã có, **không tốn LLM**.
  - **Chốt an toàn:** Phase 2 được phép sửa **HÌNH DẠNG** (class/predicate/trường thời gian) nhưng **không bao giờ** được dịch/định dạng lại/bịa/bỏ **GIÁ TRỊ** thuộc tính (`preserve_property_values`). Quan trọng vì step02 nay xuất tên/tiêu đề **tiếng Việt** (issue #6): model sửa lỗi được ra lệnh bằng tiếng Anh mà "sửa" một cái tên VN sẽ âm thầm tách một thực thể thành hai ở step05.
- **`canonicalize` (03c):** gán `kpi_id` chuẩn từ bộ 35 chỉ tiêu, **ghi thuộc tính MỚI, không bao giờ ghi đè `kpi_type`** (vốn nằm trong `identity_keys` → giữ nguyên thứ tự node → các dossier đã trả tiền vẫn còn giá trị). Ưu tiên **precision hơn recall**: KPI tài chính bằng VND bị từ chối chứ không ép ánh xạ.
- **`entities` (05):** Stage A khớp `identity_keys` tất định + **neo cứng issuer** (`issuer_registry.json`) + **neo cứng standards** (`standards_registry.json`) → Stage B blocking nhận biết tiếng Việt (chữ ký chuẩn hóa + cosine embedding) → Stage C adjudication LLM có ngân sách → Stage D hợp nhất. `--no-llm` bỏ B+C.
- **`provenance` (05b):** khớp node claim/evidence ngược về file `graph_output/graphs/<doc>/page{N}.json` theo **4 tầng ưu tiên** rồi đóng dấu `source_doc`/`source_page` (+ `article_title`/`url`/`domain` cho tài liệu news). **Không bao giờ đảo thứ tự node** — `neo4j_load` và dossier đánh chỉ số theo vị trí mảng.
- **`indicators` (05c):** APPEND-ONLY (assert phần đầu node/edge cũ không đổi). Sinh `partOf`, `measuredUnder` (đọc `kpi_id` từ 03c — **không đoán ở đây**), `equivalentTo` (chỉ dòng crosswalk đã xác nhận), và tầng từ khóa của `alignsWithIndicator`. **`Penalty` có `amount == 0`** = doanh nghiệp tự khai "bị phạt 0 lần" → gắn cờ `self_reported_zero`, **KHÔNG** sinh cạnh conduct.
- **`claims_vs_conduct` (07):** với mỗi `SustainabilityClaim`, truy hồi ứng viên phía conduct → LLM phán supports/contradicts/irrelevant → ghi cạnh `verifiedBy` / `contradictedBy*`. Có **chốt tự-xác-minh**: loại bỏ cạnh "verify" mà bằng chứng đến từ chính tên miền của doanh nghiệp. Xuất **dossier tư vấn — KHÔNG có điểm/nhãn greenwashing**.

### 5.5 Lệnh thường dùng

```bash
pip install -r requirements.txt

# 0. Lấy snapshot dữ liệu ứng với commit này (thay vì chạy lại pipeline)
python src/esg_kg/core/datasync.py status      # đang pin gì vs local có gì
python src/esg_kg/core/datasync.py pull        # tải revision trong data_version.json
python src/esg_kg/core/datasync.py push        # sau khi build lại: upload + pin lại (cần quyền write)
                                               #   rồi: git add data_version.json && git commit

# A. BCTN → câu ESG có nhãn
python -m data_processing.prepare_sentences --input "<file.pdf>" --output "data/interim/sentences/x.jsonl"
python -m data_processing.extract_esg

# B. Tin tức (phía conduct)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news

# C. Labeled JSONL → Temporal KG (chạy từ repo root, theo thứ tự)
python src/run.py --list
python src/run.py quality --label baseline
python src/run.py extract -i <labeled.jsonl>
python src/run.py extract_triples -i <report_labeled.jsonl>                  # phía claim
python src/run.py extract_triples -i <news_preprocessed.jsonl> --source news # phía conduct
python src/run.py build_validated --dry-run                                  # BLOCK 03→03b→03c
python src/run.py issuer                                                     # rồi xác nhận needs_review bằng tay
python gri/build_gri_catalog.py                                              # builder run-once, commit JSON sinh ra
python src/run.py build_resolved --dry-run                                   # BLOCK 05→05b→05c
python src/run.py align_claims --dry-run                                     # tùy chọn (LLM)
python src/run.py export_kgc --dry-run                                       # xem trước thống kê phân rã hub
docker compose up -d                                                          # Neo4j :8687 (chạy neo4j/init.cypher một lần)
python src/run.py neo4j_load --clear
python src/run.py claims_vs_conduct --dry-run                                # xem trước cặp claim↔conduct
python src/run.py claims_vs_conduct
python src/run.py neo4j_sync
python src/run.py claim_ledger --review-queue --markdown

python api/main.py                                                            # UI tại http://localhost:8000
```

**Cờ hữu ích:** `--doc <substr>`, `--limit-docs N`, `--all`, `--all-pages`, `--dry-run`;
`--provider {gemini,openai}` (trên 01/02/03/05, mặc định `gemini`) kèm `--openai-model` / `--openai-base-url`;
`quality`: `--label`, `--skip-slow`, `--max-hops`; `fix_triples`: `--renormalize`;
`canonicalize`: `--aliases`, `--fuzzy-threshold`, `--no-goals`; `indicators`: `--crosswalk`, `--no-gri`, `--no-align`;
`entities`: `--no-llm`, `--similarity-threshold`, `--max-llm-pairs`; `export_kgc`: `--max-bucket-degree`;
`neo4j_load`: `--clear`, `--no-versions`, `--database`, `--strict`;
`claims_vs_conduct`: `--max-llm-pairs`, `--provider-order` (mặc định `openai`), `--to-neo4j`;
`claim_ledger`: `--review-queue`, `--assessment`, `--claim-id`, `--markdown`.

---

## 6. Bố cục Repo (nguyên tắc được thực thi)

**Code chỉ sống trong các thư mục package:** `crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`, `kpi_build/`, `gri/`, và cặp UI `api/` + `frontend/`. Mọi thứ còn lại là `config/` (schema + từ điển), `neo4j/` (`init.cypher` + `crosscheck_queries.cypher`), hoặc `data/` (`raw/` → `interim/` → `labeled/` → `outputs/`).

**Không để file dữ liệu bên trong package code** — trừ hai ngoại lệ có tên: `kpi_build/` và `gri/`, cả hai đều là builder run-once giữ nguồn ngay cạnh code để truy vết được một khẳng định về tới trang gốc (`gri/` mang 42 PDF chuẩn GRI, ~45 MB, trong Git).

**Hai kiểu thực thi — không được trộn:**
- `data_processing/` và `esg_news_crawler/` là **package**, chạy dạng module: `python -m data_processing.extract_esg`.
- `src/esg_kg/` chạy từ repo root qua dispatcher: `python src/run.py <stage>`.

**`EmeraldMind/` là tham chiếu CHỈ ĐỌC — KHÔNG thuộc dự án này.** Đừng sửa, đừng liệt kê, đừng tính là file dự án. Nó bị loại khỏi git (`.gitignore`) vì có `.git` và secrets riêng.

**Truy vết cấp câu** (`source_pdf`, `page`, `sentence_index`) được giữ xuyên suốt mọi stage để mỗi node đồ thị truy ngược về nguồn — **giữ nguyên, đừng làm đứt**.

---

## 7. Dữ liệu & Đồng bộ qua Hugging Face

Dữ liệu sinh ra **phân phối qua Hugging Face, không qua Git**. `data/`, `graph_output/`, `kpi_output/` bị git-ignore và ship dưới dạng HF dataset repo `nammovuivui-capstone/capstone`.

- Revision đã đẩy được **pin trong `data_version.json`, và file này CÓ trong Git** — nên checkout một commit là khôi phục được đúng bộ dữ liệu đi kèm code đó (điều kiện để so sánh baseline vs sau-thay-đổi có thể tái lập).
- **Đừng chạy lại một stage đắt tiền để lấy dữ liệu đồng đội đã đẩy — hãy `pull`.**
- Cần `HF_TOKEN` trong `.env` (hoặc `hf auth login`). Repo nằm trong **org**, không phải namespace cá nhân — HF không có tính năng collaborator cho repo thuộc user, nên org là cách duy nhất chia sẻ repo private; bạn phải được mời vào (`read` để pull, `write` để push) nếu không sẽ 404.
- **Ai push cũng phải commit `data_version.json` ngay trong lần đó** — snapshot đã đẩy mà không commit pin thì vô hình: cả nhóm tiếp tục pull revision cũ mà không có lỗi nào báo. `git pull` trước khi push để xung đột pin nổi lên ở Git thay vì âm thầm ghi đè snapshot của người khác.
- `neo4j_data/` **không bao giờ** được đồng bộ — dựng lại bằng `neo4j_load`.
- Cả `push` và `pull` đều bị giới hạn bằng `ALLOW_PATTERNS` đúng ba thư mục trên: `local_dir` là **repo CODE**, nên một cú pull không giới hạn sẽ ghi file gốc của dataset đè lên file đang được track (đó chính là cách `.gitattributes` của Hub lọt vào repo này, và là lý do repo nay route `*.png/jpg/zip/parquet` qua Git LFS). Đã khóa bằng `test/test_data_sync_scope.py`.

### 7.1 Quy mô corpus hiện tại

| Tầng | Hiện có |
|---|---|
| BCTN thô | **1,410 PDF** của **115 doanh nghiệp** (`data/raw/annual_report/Xây dựng - VLXD - BĐS/`) |
| Câu đã phân loại ESG | `data/labeled/classified/all_sentences_classified.jsonl` (~400 MB, toàn ngành) |
| Tin tức | **115 file** `data/outputs/news/<TICKER>.jsonl` + `coverage.csv` |
| Đồ thị đã dựng | **Chỉ AAA** — `graph_output/` local là pilot 1 doanh nghiệp (build 2026-07-26) |

> Commit `05cad84` đã **xóa `kpi_output/` và `graph_output/` khỏi Hub** vì chúng là tàn dư của pilot AAA và có trước lần push toàn ngành. Do `resolved_graph.json` / `all_validated_triples.json` là **append-only**, để lại sẽ trộn đồ thị AAA cũ với bản dựng lại toàn corpus. `graph_output/` trên máy local vì thế **cũ hơn** snapshot đang pin.

---

## 8. Giao diện Web ESG Evidence View (`api/` + `frontend/`)

### 8.1 Kiến trúc

`api/main.py` là **`http.server` thuần thư viện chuẩn** (cố tình không FastAPI/Flask) phục vụ REST endpoint và static `frontend/` tại `http://localhost:8000`. **Toàn bộ truy cập dữ liệu nằm trong `api/evidence_service.py`**, đọc **Neo4j trực tiếp** (đồ thị nền từ step06 + lớp advisory từ step08).

- **Không còn mock data; Neo4j là BẮT BUỘC** — các helper truy vấn ném `RuntimeError` nếu không kết nối được.
- **Chỉ tuyên bố có cạnh `alignsWithIndicator` mới được hiển thị**, nên trụ cột E/S/G của mỗi thẻ lấy **trực tiếp từ `StandardIndicator.pillar`** chứ không đoán.
- Frontend (`index.html` + `css/style.css` + `js/app.js`) **cố tình bị đóng băng**: theo `docs/REAL_DATA_INTEGRATION_GUIDE.md`, mọi thay đổi nguồn dữ liệu chỉ được sửa trong `evidence_service.py`.

### 8.2 Giao diện 3 Cột Đối soát

Mỗi trụ cột ESG hiển thị 3 cột bằng chứng:

1. **Đã xác nhận (Verified)** — tuyên bố được bằng chứng độc lập ủng hộ.
2. **Thực tế khác biệt (Contradicted)** — tuyên bố mâu thuẫn trực tiếp với bằng chứng.
3. **Chưa đối soát (Missing Evidence)** — chưa tìm được bằng chứng độc lập để đối chứng.

Số tuyên bố **có neo chỉ tiêu** (tức là số đủ điều kiện hiển thị) theo trụ cột của chỉ tiêu được neo, trên đồ thị AAA:

| Trụ cột | Cạnh `alignsWithIndicator` | Ví dụ chỉ tiêu |
|---|---:|---|
| 🏛 Quản trị | **285** | `GRI 2-9` cơ cấu HĐQT, `GRI 2-14`, `GRI 2-29`, `GRI 205-1` chống tham nhũng |
| 🌿 Môi trường | **184** | `GRI 303-4` nước thải, chỉ tiêu TT96 Mục 6.1–6.5 |
| 👥 Xã hội | **170** | an toàn lao động, tỷ lệ nữ quản lý, đào tạo, an sinh cộng đồng (TT96 6.6.x) |

---

## 9. Trạng thái hiện tại & Việc cần làm tiếp

### 9.1 Đã xong
- ✅ Refactor `src/esg_kg/` — 16/16 stage, dispatcher `run.py`, 2 block.
- ✅ Trục chỉ tiêu TT96 + GRI Catalog (136 mã đang commit), NLP Smart Matcher.
- ✅ Đối soát chéo end-to-end + lớp advisory Neo4j + claim ledger + Web UI đọc Neo4j thật.
- ✅ Đồng bộ dữ liệu HF có pin revision.
- ✅ `claim_id` tất định (issue #2) — mở khóa khả năng trích xuất lại toàn đồ thị.
- ✅ Corpus mở rộng: 1,410 BCTN / 115 doanh nghiệp đã phân loại câu ESG.

### 9.2 Đang chờ / chưa làm
- ⏳ **Dựng lại đồ thị cho toàn ngành 115 doanh nghiệp** — hiện `graph_output/` vẫn là pilot AAA. Đây là việc tốn LLM lớn nhất còn lại, và đang bị chặn bởi tình trạng billing của Gemini (xem §2.4 về đường dẫn OpenAI).
- ⏳ **Gemini bị chặn thanh toán** — `entities` chạy `--no-llm` (mất Stage B blocking ngữ nghĩa + Stage C adjudication); embedding `gemini-embedding-001` không dùng được. `docs/BERT_NER_GRAPH_QUALITY.md` phân tích phương án thay bằng sentence-embedding CPU local.
- ⏳ **Bằng chứng conduct còn mỏng** — chỉ 124 node conduct cho 1,093 claim ở AAA, khiến 91.6% claim ở trạng thái `unverified`. Đây là nút thắt chất lượng lớn nhất của hệ thống, không phải nút thắt kỹ thuật.
- ⏳ **`config/gri_catalog.json` đã dựng lại (145 mã) nhưng chưa commit** — cùng với các thay đổi trong `gri/`.
- ❌ **Tầng suy luận theo đường đi (SSRL, step 11–13) chưa được xây** — `docs/SSRL_REASONING_LAYER.md` được `TEMPORAL_KG_DESIGN.md` tham chiếu nhưng **không có trong repo**. `export_kgc` mới chỉ là mảnh hub-decomposition chuẩn bị cho nó.
- ❌ **Tín hiệu `kpi_gap` / `structural_contradiction` là tín hiệu "ma"** — step07 chưa bao giờ ghi chúng (phát hiện D1 trong `docs/CROSSCHECK_EXPANSION.md`).

---

## 10. Quy tắc làm việc: TDD (áp dụng cho MỌI code từ nay)

**Viết test trước. Chạy nó. Thấy nó fail. Rồi mới viết code.** Không có production code nào được vào repo mà không có một test fail đòi hỏi nó.

Quy ước (theo `test/test_temporal_invariants.py`, tiền lệ có sẵn):
- **Script `assert` thuần, không pytest** — repo không có harness pytest/linter. Một test là file chạy được dưới `test/`, in pass/fail và exit khác 0 khi fail.
- **Test phải offline** — không LLM, không Neo4j, không network. Chúng chạy trên artifact thật đã có trên đĩa. **Không bao giờ kiểm chứng bằng cách chạy lại một stage tốn tiền.**
- Chạy từ repo root: `python test/<name>.py`.

Kỹ thuật lặp lại nhiều lần trong repo: **để test một stage tốn tiền/cần mạng miễn phí, hãy stub BÊN DƯỚI lớp trừu tượng** (`_OpenAIProvider`, `google.genai.Client`, `GraphDatabase`) — logic thật vẫn chạy, chỉ I/O là giả (thường trả lời tất định theo CRC của prompt).

Bộ test chính (danh sách đầy đủ kèm mô tả chi tiết ở `CLAUDE.md`):

```bash
python test/test_temporal_invariants.py    # bất biến thời gian P3/P4, provenance, kpi_id, trục chỉ tiêu
python test/test_schema_contract.py        # config/schema.json: P1 hai chiều, phân tầng, cặp cạnh hợp lệ
python test/test_indicator_axis.py         # 05c chạy thật trên workspace tạm: Penalty=0, append-only, idempotency
python test/test_gri_catalog_build.py      # quy tắc sở hữu disclosure của GRI (§2.5 mục 4)
python test/test_data_sync_scope.py        # datasync pull không thể ghi đè file repo được track
python test/test_export_kgc.py             # hub decomposition: không rò rỉ giữa ticker, tất định, is_synthetic
python test/test_pipeline_table.py         # bảng stage: nhãn old_step hợp lệ/duy nhất, thành viên block
python test/test_step02_language_guard.py  # prompt 02 bắt buộc output tiếng Việt (issue #6)
python test/test_step03_llm_value_guard.py # 03 phase 2 sửa HÌNH DẠNG, không đụng GIÁ TRỊ
# … cùng bộ test tương đương cho từng stage đã migrate: test_esg_kg_*.py
```

---

## 11. Bản đồ Tài liệu

**Đọc trước tiên:** `docs/SYSTEM_DESIGN.md` — thiết kế hệ thống end-to-end cuối cùng (thế đối xứng claim ↔ conduct, nhánh news→graph, và chủ trương "bằng chứng + đánh giá tư vấn, KHÔNG có điểm/phán quyết greenwashing").

| Tài liệu | Nội dung |
|---|---|
| `TEMPORAL_KG_DESIGN.md` | 8 nguyên tắc P1–P8 + 8 thuộc tính chất lượng Q1–Q8. **Đọc trước khi sửa schema, prompt 02, stage 03 hoặc 05** |
| `SCHEMA_EXPLAINED.md` | Lý do đằng sau `config/schema.json` |
| `STANDARD_INDICATOR_AXIS.md` | Trục chỉ tiêu TT96/GRI (03c + 05c) |
| `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`, `TRIPLET_VALIDATION.md` | Stage 01 / 02 / 03 |
| `PROVENANCE_PATCH.md` | Stage 05b — đóng dấu source_doc/source_page |
| `ENTITY_RESOLUTION.md` | Stage 05 — **vì sao là thiết kế lại, không phải port** |
| `GRAPH_LOAD_NEO4J.md` | Stage 06 |
| `CLAIM_CONDUCT_CROSSCHECK.md` | Stage 07 — lõi phân tích |
| `CLAIM_LEDGER.md` | Stage 08 + 09 + Cypher cho analyst |
| `ESG_EVIDENCE_VIEW.md`, `REAL_DATA_INTEGRATION_GUIDE.md` | UI 3 cột và quy tắc "chỉ sửa `evidence_service.py`" |
| `GRI_SCHEMA_DOCUMENTATION.md` | Hình dạng `gri/full_gri/json/*.json` và `config/gri_catalog.json` |
| `KPI_DEFINITIONS_CONSTRUCTION_BUILD.md` | Builder `kpi_build/` |
| `NEWS_CRAWLER_OPTIMIZATION.md` | Crawler độc lập `crawl_data/crawler_news.py` (**không phải** đường news chính thức) |
| `PIPELINE_DIAGRAMS.md`, `PIPELINE_UNIFIED.md` | 10 hình kiến trúc — **hình dạng pipeline vẫn đúng, nhưng tên stage là tên `src/` cũ**; xem `src/PIPELINE.md` cho tên hiện hành |
| `src/esg_kg/DESIGN.md`, `src/PIPELINE.md` | **Hồ sơ lưu trữ đầy đủ của refactor** (§7 ở cả hai ghi lại phần closeout) |

**Là ĐỀ XUẤT, không phải mô tả code đang có:** `CROSSCHECK_EXPANSION.md`, `BERT_NER_GRAPH_QUALITY.md`, `EVALUATION_WITHOUT_LABELS.md`, `AGENT_AB_EVALUATION.md`, `ENTITY_RESOLUTION_IMPROVEMENT.md`, `VIETNAM_IMPROVEMENT_PLAN.md`.

**Được tham chiếu nhưng KHÔNG có trong repo:** `docs/SSRL_REASONING_LAYER.md`.

---

> *Tài liệu này được cập nhật đồng bộ với cấu trúc codebase thực tế của dự án tại thời điểm 2026-08-05. Khi thực hiện nâng cấp kiến trúc, hãy cập nhật lại thông tin vào tài liệu này — và nhớ chạy `python src/run.py --list` để lấy bảng stage mới nhất thay vì chép tay.*
