# PROJECT OVERVIEW — Greenwashing Detection via Graph-RAG (Vietnamese Listed Companies)

> **Tài liệu mô tả toàn bộ dự án ở mức chi tiết đủ để một người mới đọc xong là làm việc được.**
> Nó được viết để tự đủ: bài toán, kiến trúc, từng stage, schema đồ thị, trục chỉ tiêu TT96/GRI, cơ chế
> đối soát chéo, lớp Neo4j, giao diện Web, khung đánh giá không nhãn, bộ test, quy trình vận hành, số
> liệu thực đo, nợ kỹ thuật và hướng mở rộng.
>
> **Trạng thái tài liệu:** viết lại ngày **2026-08-07**, đối chiếu trực tiếp với code và artifact trên
> đĩa tại commit `c4c9f42` (HEAD). Mọi con số ở §12 đều được **đo lại trong ngày**, kèm nguồn và thời
> điểm; con số nào thuộc một lần chạy cũ đều được đánh dấu rõ là cũ chứ không trình bày như hiện trạng.

---

## Mục lục

| § | Nội dung |
|---|---|
| 1 | Tóm tắt điều hành — hệ thống này là gì, không là gì |
| 2 | Bài toán khoa học & ràng buộc "không có nhãn" |
| 3 | Bản đồ repository — từng thư mục, vai trò, nguyên tắc bố cục |
| 4 | Ngăn xếp công nghệ & cấu hình LLM |
| 5 | Kênh A — Báo cáo thường niên → câu ESG có nhãn |
| 6 | Kênh B — Tin tức độc lập (phía *hành vi*) |
| 7 | Kênh C — 16 stage dựng Temporal KG (`src/esg_kg`) |
| 8 | Schema đồ thị: 28 lớp node, 48 nhãn cạnh, mô hình T1/T2/T3, các nguyên tắc P1–P8 |
| 9 | Trục chỉ tiêu TT96 / GRI (`kpi_build/`, `gri/`, step 03c + 05c) |
| 10 | Đối soát chéo Claim ↔ Conduct — lõi phân tích (step 07) |
| 11 | Lớp Neo4j: đồ thị nền + lớp advisory + sổ nhật ký tuyên bố + giao diện Web |
| 12 | Số liệu thực đo hiện tại (2026-08-07) |
| 13 | Khung đánh giá không nhãn (`evalu/`) |
| 14 | Kiểm thử & quy tắc TDD |
| 15 | Vận hành: cài đặt, secrets, đồng bộ dữ liệu, thứ tự chạy, chi phí |
| 16 | Giới hạn đã biết & nợ kỹ thuật — **đọc trước khi trích dẫn bất kỳ kết quả nào** |
| 17 | Mở rộng: thêm một doanh nghiệp / scale toàn ngành |
| 18 | Thuật ngữ & bản đồ tài liệu |

---

## 1. Tóm tắt điều hành

### 1.1 Một câu

Hệ thống **Graph-RAG** dựng **đồ thị tri thức ESG có chiều thời gian (temporal knowledge graph)** cho
doanh nghiệp niêm yết Việt Nam ngành **Xây dựng – Vật liệu xây dựng – Bất động sản** (kèm Nhựa & Bao
bì), để **đối chiếu điều doanh nghiệp *tuyên bố*** (báo cáo thường niên) với **điều doanh nghiệp *làm***
(tin tức độc lập, quyết định xử phạt), rồi **xuất hồ sơ bằng chứng + đánh giá tư vấn** để con người
quyết định.

### 1.2 Hai phía của bài toán

| | Phía **Claim** (tuyên bố) | Phía **Conduct** (hành vi) |
|---|---|---|
| Nguồn | Báo cáo thường niên (BCTN) — doanh nghiệp tự công bố | Tin tức báo chí, quyết định xử phạt, kiểm toán bên thứ ba |
| Lớp node tiêu biểu | `SustainabilityClaim`, `Goal`, `Initiative`, `Certification` | `MediaReport`, `Penalty`, `Controversy`, `KPIObservation` (source_type=news) |
| Câu hỏi | "Họ **nói** gì?" | "Thực tế **xảy ra** gì?" |
| Đích | Cùng nằm trong **một** đồ thị, nối được qua trục chỉ tiêu TT96/GRI và qua cạnh `verifiedBy` / `contradictedBy` / `contradictedByMedia` |

Khác biệt kiến trúc so với Graph-RAG thông thường (và so với bản tham chiếu `EmeraldMind/`): **tuyên bố
không phải một dòng CSV bên ngoài đem đi truy vấn đồ thị** — nó là **node nằm trong chính đồ thị**, nên
phát hiện khoảng cách claim↔conduct trở thành **bài toán liên kết nội đồ thị** (in-graph linking), chứ
không phải retrieve-rồi-classify.

| Khía cạnh | Cách làm tham chiếu (EmeraldMind) | Dự án này |
|---|---|---|
| Tuyên bố | Dòng CSV bên ngoài | Node `SustainabilityClaim` **bên trong KG** |
| Bằng chứng | KG chỉ chứa báo cáo doanh nghiệp | KG chứa **cả** report (claim) **và** news (conduct) |
| Cơ chế | Embed query → retrieve → classify | **Liên kết nội đồ thị** claim ↔ conduct → adjudicate |
| Nhãn giám sát | Có gold label → báo accuracy | **Không nhãn** → hồ sơ bằng chứng + negative control |
| Đầu ra | Nhãn phân loại mỗi claim | **Hồ sơ bằng chứng + đánh giá tư vấn**, không kết án tự động |

### 1.3 Ranh giới sản phẩm — điều hệ thống KHÔNG làm

> **Không tồn tại bộ dữ liệu greenwashing có nhãn (ground truth) cho doanh nghiệp Việt Nam.**

Hệ quả, được tôn trọng xuyên suốt code:

- **KHÔNG** có "điểm greenwashing", **KHÔNG** phân loại nhị phân, **KHÔNG** quy kết.
- Đầu ra là **hồ sơ (dossier)**: bằng chứng gốc + trích dẫn trang/URL + một trong ba nhãn tư vấn
  `appears_supported` / `appears_contradicted` / `unverified_insufficient_evidence`, **luôn** kèm
  `assessment_is_advisory=true` và caveat.
- Quyết định cuối cùng thuộc **kiểm toán viên / nhà đầu tư / chuyên gia** → **Decision-Support System**,
  không phải classifier.
- Vì không có nhãn nên **không** có precision/recall/F1 về greenwashing. `evalu/` đo *tính nhất quán nội
  bộ* và *độ phủ*, cộng một **negative control** có khả năng thật sự FAIL (§13.3).

Hai stage từng đi ngược nguyên tắc này đã bị **xoá hẳn khỏi dự án**, không phải hoãn: `step07b`
(softmax evidence-balance score) và `step10` (báo cáo evaluation P6 không nhãn) — xem §7.6.

### 1.4 Quy mô hiện tại (đo 2026-08-07 — chi tiết ở §12)

| Hạng mục | Giá trị |
|---|---|
| Corpus BCTN đã phân loại ESG | **197 doanh nghiệp**, 873.756 câu, 303.723 câu `esg=true` |
| Corpus tin tức đã phân loại ESG | **115 mã CK**, 174.256 câu, 77.229 câu `esg=true` |
| Tài liệu đã trích thành đồ thị trang | **137** (46 BCTN + 91 bài báo), 3.957 file trang |
| Đồ thị đã phân giải (`resolved_graph.json`) | **10.634 node / 14.744 cạnh** |
| Neo4j đang chạy | **13.181 node / 17.291 quan hệ** (đã bung version chain) |
| Hồ sơ đối soát | **464 claim / 5 mã CK** (AAA, ACC, ACG, ADP, AGG) |
| Code | ~35.600 dòng Python, trong đó **45 file test** / ~14.700 dòng |
| Snapshot dữ liệu trên Hugging Face | revision `902fcf84`, ~**19 GB** |

---

## 2. Bài toán khoa học & ràng buộc "không có nhãn"

### 2.1 Đo greenwashing thế nào khi không có nhãn?

Greenwashing = khoảng cách giữa **thông tin công bố** và **hành vi thực tế**. Không đo trực tiếp được
"có greenwashing hay không" nếu thiếu nhãn, nhưng **đo được ba thứ**:

1. **Khoảng cách có bằng chứng** — một tuyên bố cụ thể, tại một mốc thời gian cụ thể, mâu thuẫn với một
   bằng chứng độc lập cụ thể (có URL, có ngày). Đây là *phát hiện*, không phải *phán quyết*.
2. **Sự im lặng** — tuyên bố không có bất kỳ bằng chứng độc lập nào để đối chứng
   (`unverified_insufficient_evidence`). Đây là **thuộc tính của kho dữ liệu**, không phải của doanh
   nghiệp; hệ thống buộc phải nói rõ điều đó (caveat *"absence of contradiction is NOT exoneration"*).
   Trên dữ liệu hiện tại tỷ lệ này là **73,49%** — cao, và **không được** trình bày như một chỉ tiêu
   cần giảm (§13.2, M5.1).
3. **Tính nhất quán nội bộ của chính pipeline** — tuyên bố có truy được về trang gốc, ngày tháng có
   chuẩn hoá được, thực thể có bị vỡ thành nhiều node… (§13).

### 2.2 Vì sao phải là đồ thị *có chiều thời gian*

Câu hỏi cốt lõi luôn mang mốc thời gian: *"Năm 2021 cam kết X; năm 2023 hành vi thực tế là Y; khoảng
cách bao nhiêu?"* Đồ thị không có thời gian không trả lời được. Vì vậy:

- **Ở bước trích xuất (step 02/03):** mọi node mang `valid_from` / `valid_to` / `is_current`; mọi cạnh
  mang `temporal_metadata` (`valid_from`, `valid_to`, `recorded_at`).
- **Ở đồ thị đã phân giải (step 05+):** thời gian sống trên **cạnh** và trên **node sự kiện T2/T3**;
  thực thể T1 (doanh nghiệp, nhà máy…) là **vô thời gian**, lịch sử nằm trong `temporal_versions` và
  chuỗi cạnh `supersedes`.
- Mọi ngày canonicalize về ISO `YYYY[-MM[-DD]]`. Ngày không nhận dạng được (ví dụ "Q2 2023") **giữ
  nguyên và đánh dấu không parse được** — tuyệt đối không bịa ra ngày.
- Tin tức có thêm cờ bắt buộc `date_uncertain`: `false` khi bài báo nêu ngày/kỳ rõ ràng, `true` khi
  phải lấy ngày publish làm proxy. Step 07 chuyển cờ này thành caveat trên hồ sơ.

### 2.3 Provenance là điều kiện tiên quyết, không phải tính năng phụ

Ba trường `source_pdf`, `page`, `sentence_index` được giữ **nguyên vẹn qua mọi stage**. Không có nó thì
mọi thứ phía sau vô giá trị: một thẻ trên giao diện nói "doanh nghiệp X mâu thuẫn" mà không chỉ được về
đúng trang báo cáo thì không kiểm chứng được, và không được phép hiển thị. Metric `M1.2` trong `evalu/`
khoá tính chất này ở mức 100%; step 05b còn stamp thêm `source_doc` / `source_page` (và với tin tức là
`article_title` / `article_url` / `source_domain`) lên node để UI trích dẫn được tên bài.

### 2.4 Tám nguyên tắc thiết kế P1–P8 (rút gọn)

Các nguyên tắc này nằm rải trong docstring của từng stage và trong `report/quality.py`; đây là bản tóm:

| Mã | Nguyên tắc | Được enforce ở đâu |
|---|---|---|
| **P1** | Danh tính T1 là **vô thời gian** — không đưa trường thời gian vào `identity_keys` của lớp T1 | `quality` (lint), `test/test_schema_contract.py` |
| **P2** | Trong đồ thị đã phân giải, thời gian sống trên **cạnh + node T2/T3**, không trên T1 | step 05 (Stage D) |
| **P3** | Mọi node sự kiện T2 nên neo vào **≥ 2 thực thể T1** khi văn bản cho phép | prompt step 02 + step 03b (gazetteer) |
| **P4** | Bất biến thời gian: ngày ISO, `valid_from ≤ valid_to`, một chuỗi version chỉ có **một** `is_current=true` | step 03 phase 1.5, kiểm ở step 05 + `quality` Q2 |
| **P5** | Lớp advisory phải **tách biệt và gắn cờ**, không lẫn vào fact đã trích | step 08 (`llm_suggested=true`, `assessment_is_advisory=true`) |
| **P6** | Biến đổi ở tầng **dataset** (cạnh nghịch đảo, hub bucket) **không** được ghi vào `resolved_graph.json`/Neo4j | `export/export_kgc.py` |
| **P7** | Node/cạnh tổng hợp phải mang cờ `is_synthetic` — một bước nhảy không có câu nguồn thì không được trình bày như bước suy luận trích dẫn được | `export_kgc`, `test/test_export_kgc.py` |
| **P8** | Chỉ dùng cạnh/lớp mà `config/schema.json` đã định nghĩa; không phát sinh nhãn mới ở stage vá | step 03b, 05c (`GraphPatch`) |

---

## 3. Bản đồ repository

### 3.1 Nguyên tắc bố cục (đang được enforce)

**Code chỉ nằm trong các thư mục package**: `crawl_data/`, `data_processing/`, `esg_news_crawler/`,
`src/`, `kpi_build/`, `gri/`, `evalu/`, cặp UI `api/` + `frontend/`. Còn lại là:

- `config/` — schema + từ điển (**không** chứa dữ liệu sinh ra);
- `neo4j/` — `init.cypher` (database/user/constraint) + `crosscheck_queries.cypher` (truy vấn analyst);
- `data/` — `raw/` → `interim/` → `labeled/` → `outputs/`;
- `graph_output/`, `kpi_output/` — artifact pipeline.

**Không có file dữ liệu bên trong package code**, trừ **hai ngoại lệ có tên**: `kpi_build/` và `gri/` —
hai builder chạy-một-lần giữ PDF nguồn ngay bên cạnh code, để một chỉ tiêu luôn truy được về đúng trang
văn bản pháp quy (`gri/` mang 42 PDF GRI, ~45 MB, commit trong Git).

### 3.2 Cây thư mục và vai trò

```
capstone_test1/
├── CLAUDE.md                     Hướng dẫn nội bộ + lịch sử quyết định (85 KB — nguồn chi tiết nhất về "vì sao")
├── README.md                     Onboarding ngắn cho người mới
├── requirements.txt              Dependency (torch / huggingface_hub / rapidfuzz / python-docx CỐ Ý không có — §4.4)
├── docker-compose.yml            Neo4j 5 Enterprise: bolt :8687, HTTP :8474
├── data_version.json             ★ TRACKED trong Git — pin revision snapshot dữ liệu trên Hugging Face
│
├── config/                       Schema + từ điển
│   ├── schema.json               ★ NGUỒN SỰ THẬT: 28 lớp node / 76 edge spec / 48 nhãn cạnh
│   ├── company_annual_report.xlsx  Danh mục công ty (mã CK, tên, ngành, URL báo cáo)
│   ├── kpi_type_aliases.json     Từ điển canonicalize tên KPI + reject_units (step 03c)
│   ├── standards_registry.json   CONFIG TĨNH: alias/exclusion cho 5 văn bản chuẩn (TT96, QĐ2171, QCVN09, SSC-IFC, GRI)
│   ├── standard_crosswalk.json   Crosswalk TT96/SSC-IFC → GRI (chỉ dòng status=confirmed được dùng)
│   ├── gri_catalog.json          136 mã chỉ tiêu GRI (do gri/ sinh, commit vào Git)
│   ├── issuer_registry.json      Alias/exclusion của doanh nghiệp phát hành (step 04 sinh, người xác nhận tay)
│   ├── degenerate_relations.json Quan hệ suy biến — loại khỏi R1_trainable
│   ├── evaluation/               ablation_cases.json
│   └── subsidiaries/             110 file <TICKER>.json — cơ cấu công ty con/liên kết (trích bằng gemini_vision)
│
├── crawl_data/                   Thu thập BCTN
│   ├── download_reports.py       Tải theo xlsx: 5 luồng, resume, retry+backoff, tự giải nén
│   ├── extract_archives.py       Giải nén .zip/.rar/.7z (gọi UnRAR.exe / 7z.exe bên ngoài)
│   ├── crawler.py                Crawler site IR FPT (nodriver / undetected Chrome, vượt Cloudflare)
│   └── crawler_news.py           Crawler tin FPT — LEGACY/thử nghiệm, KHÔNG phải đường tin tức chính thức
│
├── data_processing/              PDF → câu → nhãn ESG (chạy bằng -m)
│   ├── pdf_extractor.py          PyMuPDF, giữ số trang + dấu tiếng Việt
│   ├── sentence_splitter.py      underthesea sent_tokenize (fallback regex)
│   ├── prepare_sentences.py      Mọi câu → JSONL (KHÔNG lọc ESG)
│   ├── esg_classifier.py         ViDeBERTa-v3-ESG multi-label (sigmoid; esg quyết định theo điểm Neutral)
│   ├── extract_esg.py            JSONL có nhãn → record gọn cho Graph-RAG
│   └── preprocess_news.py        P1: chuẩn hoá ngày công bố + bỏ boilerplate
│
├── esg_news_crawler/             Kênh tin tức (phía conduct) — package, chạy bằng -m
│   └── run.py companies.py queries.py fetch.py extract.py normalize.py config.py sources/
│
├── src/                          ★ Pipeline dựng KG
│   ├── run.py                    Dispatcher duy nhất: python src/run.py <stage>
│   ├── PIPELINE.md               Thứ tự chạy + lịch sử thiết kế (1.031 dòng)
│   └── esg_kg/
│       ├── pipeline.py           ★ Bảng STAGES / BLOCKS — nguồn sự thật cho run.py --list
│       ├── DESIGN.md             Thiết kế module + biên bản refactor (990 dòng)
│       ├── core/                 Kernel: paths, schema, naming, dates, identity, io_jsonl,
│       │                          llm, llm_cache, graph_patch, console, datasync
│       ├── kpi/                  extract (01), canonicalize (03c)
│       ├── graph/                extract_triples (02), fix_triples (03), anchor_kpi (03b),
│       │                          build_validated (KHỐI 03→03b→03c)
│       ├── registry/             issuer (04)
│       ├── resolve/              entities (05), provenance (05b), indicators (05c),
│       │                          align_claims (05d — LLM tuỳ chọn), build_resolved (KHỐI 05→05b→05c)
│       ├── load/                 neo4j_load (06), neo4j_sync (08)
│       ├── crosscheck/           claims_vs_conduct (07) — lõi phân tích
│       ├── report/               quality (00, Q1–Q8), claim_ledger (09)
│       ├── export/               export_kgc (11, một phần) — view SSRL, KHÔNG chạm resolved_graph/Neo4j
│       └── metric/               hub.py (A1), reasoning_readiness.py (R1 / R1' / R7 / R1_trainable)
│
├── kpi_build/                    Chạy-một-lần: 01→06 dựng kpi_definitions_construction.json (35 KPI)
├── gri/                          Chạy-một-lần: 42 PDF GRI → config/gri_catalog.json (136 mã)
│   └── benchmark_results/        Benchmark các bộ parser PDF
├── evalu/                        ★ Khung đánh giá không nhãn (11 metric + negative control + IAA + rubric)
│
├── api/  frontend/               ESG Evidence View — http.server thuần stdlib + UI 3 cột (frontend đóng băng)
├── neo4j/                        init.cypher + crosscheck_queries.cypher
├── test/                         45 script assert thuần, offline, miễn phí
├── notebooks/                    kaggle_esg_classify.ipynb (GPU) + test_pdf_extraction.ipynb
├── diagram/                      drawio / mermaid / puml / html các sơ đồ
├── test2/                        Thử nghiệm chuyển đổi PDF bằng Datalab (so sánh parser)
│
├── data/  graph_output/  kpi_output/   ★ git-ignored, phân phối qua Hugging Face (§15.3)
└── EmeraldMind/                  Bản tham chiếu ngoài — CHỈ ĐỌC, không thuộc dự án, git-ignored
```

### 3.3 `EmeraldMind/` — bản tham chiếu, không phải code của dự án

`EmeraldMind/` là một implementation Graph-RAG bên ngoài, có `.git` và secrets riêng, bị loại khỏi Git
của dự án này (`.gitignore`). **Không sửa, không tính là file của dự án** (không liệt kê, không refactor,
không đếm). Quan hệ thực tế: stage 1→2→3 của `src/esg_kg` **port sát** `EmeraldMind/src/EmeraldKG/`;
stage 4 (entity resolution), 5 (Neo4j load), 6 (cross-check) là **thiết kế lại có chủ ý** — vì đầu vào
ở đây là **JSONL đã có nhãn** (không phải PDF) và **một `GEMINI_API_KEY`** (không phải pool nhiều key).

### 3.4 Hai lối chạy — không được trộn

| Nhóm | Cách chạy | Ví dụ |
|---|---|---|
| `data_processing/`, `esg_news_crawler/` | package, chạy `-m` | `python -m data_processing.extract_esg` |
| `src/esg_kg/` | dispatcher, từ repo root | `python src/run.py quality --label baseline` |
| `evalu/` | script trực tiếp | `python evalu/run_evaluation.py` |

`python src/run.py --list` in bảng stage, **đọc từ `esg_kg/pipeline.py` qua import system** chứ không
phải danh sách chép tay — nên nó không bao giờ lệch với thực tế. Hiện tại: **16/16 stage ready**.

**Lưu ý khi đọc lịch sử:** cây phẳng cũ `src/stepNN_*.py` (một file một stage) **đã bị xoá hẳn ngày
2026-07-29**, refactor hoàn tất. Mọi đường dẫn dạng `src/step07_*.py` trong comment/tài liệu là **nhãn
lịch sử**, không phải file đang tồn tại. Nhãn `stepNN` vẫn được giữ vì nó mã hoá **thứ tự chạy** và
`python src/run.py 05b` vẫn resolve theo nó.

---

## 4. Ngăn xếp công nghệ & cấu hình LLM

### 4.1 Nền tảng

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Ngôn ngữ | **Python ≥ 3.10** (host đang dùng 3.12) | ~35.600 dòng |
| Hệ điều hành phát triển | **Windows 11 / PowerShell** | `core/console.py` bật UTF-8 cho stdout (chỉ trên win32, lỗi bị swallow có chủ ý) |
| Trích xuất PDF | **PyMuPDF (fitz)** | giữ số trang + dấu tiếng Việt |
| Tách câu | **underthesea** `sent_tokenize` | xử lý "TP.HCM", "Q.1", "1.500"… ; fallback regex nếu thiếu lib |
| Bóc nội dung web | **trafilatura** (+ `httpx[http2]`, `beautifulsoup4`, `lxml`) | bỏ boilerplate, lấy title + publish date |
| Phân loại ESG | **`nguyen599/ViDeBERTa-v3-ESG-base`** (`transformers`) | multi-label E/S/G/Neutral; chạy GPU trên Kaggle |
| Đồ thị | **Neo4j 5 Enterprise** (Docker) | bolt `localhost:8687`, UI `localhost:8474`, db `greenwashingkg`, user `greenwashing` |
| Driver | `neo4j>=5.0` | |
| Web API | **`http.server` thuần stdlib** | cố ý không FastAPI/Flask để khỏi lệch version framework |
| Web UI | **Vanilla HTML5 / CSS3 / JS** | `frontend/` — **đóng băng**, mọi thay đổi dữ liệu chỉ sửa `api/evidence_service.py` |
| Phân phối dữ liệu | **Hugging Face dataset repo** (`huggingface_hub`, import lazy) | org `nammovuivui-capstone`, pin qua `data_version.json` |
| Số học | `numpy` (chỉ cho embedding cosine ở step 05) | `evalu/iaa.py` **không** dùng numpy để chạy được trên bare clone |

### 4.2 LLM — provider, model, và lịch sử đổi provider

Nguồn sự thật: `src/esg_kg/core/llm.py` (450 dòng docstring + code) và `.env.example`.

**Mặc định hiện tại: Gemini.** `DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")` —
đổi model cho **mọi** stage Gemini chỉ cần sửa **một dòng** trong `.env`, không sửa code. Cờ `--model`
của từng stage vẫn override được.

Ba provider hiện có trong `core/llm.py`, cùng contract `call(system, user) -> str`:

| Class | Tên | Model mặc định | Dùng ở đâu |
|---|---|---|---|
| `_GeminiProvider` | `gemini` | `gemini-2.5-flash-lite` | mặc định mọi nơi |
| `_DeepSeekProvider` | `deepseek` | `deepseek-v4-flash` | **tuỳ chọn** cho `align_claims`, `claims_vs_conduct`, `extract_triples` |
| `_OpenAIProvider` | `openai` | `gpt-4o-mini` | **chỉ** `claims_vs_conduct` (`--provider-order openai`) |

Cả DeepSeek và OpenAI đều gọi REST tương thích OpenAI qua `requests` — **không** kéo lại SDK `openai`
làm dependency.

**Cơ chế chọn provider — hai đường khác nhau, cố ý:**

- `align_claims` và `extract_triples` dùng factory `build_llm_provider()` (`--provider gemini|deepseek`,
  hoặc env `LLM_PROVIDER`, đọc **mới mỗi lần gọi** chứ không đóng băng lúc import).
- `claims_vs_conduct` giữ **registry riêng** trong class `Adjudicator` (`--provider-order`, mặc định
  `gemini`; nhận `gemini`/`deepseek`/`openai`, dạng danh sách phẩy nếu muốn cascade) — vì `Adjudicator`
  là **logic stage** (prompt + parse verdict), không phải kernel. Tên lạ sẽ bị log
  *"Unknown adjudication provider — ignored"*.
- `extract` / `fix_triples` / `entities` **chỉ Gemini**: chúng gọi `build_gemini_client()` trực tiếp và
  dùng **explicit context caching** riêng của Gemini (`GeminiContextCache`) — DeepSeek/OpenAI không có
  tương đương, nên làm chúng swappable là một redesign lớn hơn.

**Lịch sử cần biết trước khi "dọn dẹp" code provider:**

| Thời điểm | Việc |
|---|---|
| 2026-07-27 → 2026-08-04 | Project Gemini bị **billing-block (403)** → chạy OpenAI cho `extract`/`extract_triples`/`fix_triples`/`entities`, và OpenAI là provider **duy nhất** cho `claims_vs_conduct`/`align_claims` |
| 2026-08-04 | Gemini thông trở lại → **gỡ OpenAI hoàn toàn**, không giữ fallback (xoá `_OpenAIProvider`, mọi cờ `--provider openai`, và dependency `openai`) |
| 2026-08-06 | Thêm `_DeepSeekProvider` — **là lựa chọn thay thế bạn tự bật**, không phải cascade bắt buộc; Gemini vẫn là mặc định |
| 2026-08-06 | Thêm lại `_OpenAIProvider`, **chỉ cho `claims_vs_conduct`** (`--provider-order openai`), qua REST, không SDK |

Bài học: **đừng thêm lại một fallback provider mà chưa kiểm tra Gemini có đang bị block hay không.**

### 4.3 Ba lớp cache — biết cái nào được cache, cái nào không

| Cache | Nằm ở | Cache cái gì | Vì sao |
|---|---|---|---|
| `GeminiContextCache` | `core/llm.py` | Explicit context caching của Gemini cho `extract` / `extract_triples` / `fix_triples` | Giảm token phần prompt lặp lại (schema, định nghĩa KPI) |
| `ContentCache` (`core/llm_cache.py`) | dùng chung | Kết quả LLM **đã trả tiền**, khoá bằng **sha256 nội dung** (không phải vị trí trong batch) | Chạy lại phải **miễn phí và tái lập** |
| `RepairCache` / `AdjudicationCache` / cache của `Adjudicator` | `build_validated.py`, `build_resolved.py`, `claims_vs_conduct.py` | phase-2 repair (step 03), verdict same-entity (step 05 Stage C), verdict adjudication (step 07) | Đều là wrapper mỏng trên `ContentCache`, giữ nguyên format file cũ nên cache cũ vẫn hit |

Nguyên tắc phân biệt (DESIGN.md §5.7): **chỉ cache kết quả *đã trả tiền và không tất định*.** Embedding
ở step 05 Stage B tuy có phí nhưng **tất định** → cố ý **không** cache, vì độ phức tạp thêm không đáng.
Khoá bằng nội dung chứ không bằng vị trí, vì ranh giới batch và thứ tự ứng viên đổi giữa các lần chạy —
khoá theo vị trí sẽ trả kết quả của call này cho call khác.

`ContentCache` có lock quanh truy cập dict vì step 07 adjudicate song song bằng `ThreadPoolExecutor`;
lock chỉ bảo vệ đọc/ghi bộ nhớ, **không** serialize lời gọi mạng.

### 4.4 Dependency cố ý KHÔNG có trong `requirements.txt`

Mỗi cái đều degrade êm để bare clone vẫn chạy được:

| Package | Ai cần | Không có thì sao |
|---|---|---|
| `torch` | `data_processing/esg_classifier.py` (CPU) | Phân loại ESG chạy GPU trên Kaggle qua `notebooks/kaggle_esg_classify.ipynb`; chỉ cài local khi muốn test CPU |
| `huggingface_hub` | `core/datasync.py` | Import lazy — công cụ đồng bộ vẫn chạy trên clone trắng, chỉ báo lỗi khi thực sự cần |
| `rapidfuzz` | tầng fuzzy của step 03c | Tự tắt tầng fuzzy kèm cảnh báo, các tầng còn lại vẫn chạy |
| `python-docx` | `evalu/export_docx.py` | Chỉ lệnh export .docx bị mất; toàn bộ evaluation vẫn chạy |

### 4.5 Secrets & biến môi trường

Copy `.env.example` → `.env` (đã git-ignore, **không bao giờ commit**). Mọi stage LLM của `esg_kg` load
`.env` ở **repo root** bất kể cwd.

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Key duy nhất cho toàn bộ stage LLM |
| `GEMINI_MODEL` | – | Đổi model Gemini cho mọi stage; mặc định `gemini-2.5-flash-lite` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | – | Bật DeepSeek cho `align_claims` / `claims_vs_conduct` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | – | Bật OpenAI **chỉ** cho `claims_vs_conduct` |
| `LLM_PROVIDER` | – | Provider mặc định cho factory (`gemini` \| `deepseek`) |
| `HF_TOKEN` | – | Token Hugging Face để `pull` (read) / `push` (write) snapshot dữ liệu |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | – | Kết nối Neo4j; mặc định khớp docker-compose |

> `nammovuivui` là **password dev local**; đổi nó cho bất cứ thứ gì vượt khỏi máy cá nhân.

---

## 5. Kênh A — Báo cáo thường niên → câu ESG có nhãn

Đây là phía **claim**: những gì doanh nghiệp tự công bố.

```
config/company_annual_report.xlsx
        │
        ▼  crawl_data/download_reports.py     (5 luồng, resume, retry+backoff, tự giải nén)
data/raw/annual_report/<Ngành>/<Mã CK> - <Tên công ty>/<Mã>_<Năm>.pdf|/
        │
        ▼  python -m data_processing.prepare_sentences
        │     ├─ pdf_extractor.py     PyMuPDF → text theo trang (giữ số trang, giữ dấu)
        │     └─ sentence_splitter.py underthesea → tách câu tiếng Việt
data/interim/sentences/*.jsonl        {source_pdf, page, sentence_index, text}   ← KHÔNG lọc ESG
        │
        ▼  ViDeBERTa-v3-ESG  (GPU trên Kaggle: notebooks/kaggle_esg_classify.ipynb)
data/labeled/classified/all_sentences_classified.jsonl   + labels[] + scores{} + esg(bool)
        │
        ▼  python -m data_processing.extract_esg
data/outputs/esg_extracted/  (per-doc *_extracted.jsonl, esg_all_records.jsonl,
                              esg_by_document.json, esg_stats.json)
```

### 5.1 Vì sao KHÔNG lọc ESG bằng keyword ở bước tách câu

`prepare_sentences.py` cố ý **đưa mọi câu** cho model. Bộ lọc keyword/GRI ngày trước đã bỏ: ViDeBERTa
mới là ESG detector. Lọc trước bằng keyword sẽ giấu mất chính những câu mà model có thể bắt được, và
làm mọi phép đo signal/noise phía sau vô nghĩa.

### 5.2 Bộ phân loại ESG — chi tiết dễ sai

`nguyen599/ViDeBERTa-v3-ESG-base` là model **multi-label** (`problem_type =
multi_label_classification`), nên phải dùng **sigmoid từng nhãn**, KHÔNG dùng softmax. Nhãn:
`0 Neutral`, `1 Environmental`, `2 Social`, `3 Governance`. Một pillar được gán khi sigmoid ≥ `threshold`
(mặc định 0.45).

Điểm quan trọng: **`esg` được quyết định từ điểm `Neutral`, không từ pillar**:

```python
esg = (Neutral < neutral_threshold)     # mặc định 0.5
```

Lý do: model này phân bố xác suất kiểu softmax (các pillar + Neutral ≈ 1) và gần như không bao giờ gán
hai pillar cùng lúc, nên một câu rõ ràng là ESG có thể bị **xé tín hiệu** giữa hai pillar (ví dụ tuân
thủ luật lao động → S = 0.44, G = 0.44) và **không pillar nào vượt ngưỡng**. Neo `esg` vào Neutral cứu
được những ca đó mà vẫn loại boilerplate thật (Neutral ≈ 0.95+).

### 5.3 Chạy GPU trên Kaggle — luồng hybrid

`esg_classifier.py` cố ý **self-contained** (chỉ phụ thuộc `torch` + `transformers`) để import sạch trên
Kaggle. Quy trình: (1) chạy `prepare_sentences` ở local (CPU) → (2) upload JSONL + `esg_classifier.py`
làm Kaggle Dataset → (3) chạy `notebooks/kaggle_esg_classify.ipynb` (GPU + Internet) → (4) tải
`classified.jsonl` về `data/labeled/`.

### 5.4 ⚠ Dùng file corpus TOÀN NGÀNH, không dùng file per-company

Đây là lỗi đã xảy ra một lần, nên phải nói rõ:

- **Đúng (hiện hành):** `data/labeled/classified/all_sentences_classified.jsonl` (197 doanh nghiệp,
  873.756 câu, 303.723 câu `esg=true`) và `data/labeled/news_labeled/all_news_sentences_classified.jsonl`
  (115 mã CK, 174.256 câu, 77.229 câu `esg=true`), cùng output `extract_esg` tương ứng dưới
  `data/outputs/esg_extracted/classified/` và `.../news_labeled/`.
- **Đã bị thay thế và xoá khỏi HF (2026-08-02, commit `a7e73bd1`):** batch pilot chỉ-AAA
  (`data/labeled/annual_labeled/`, `aaa_news_classified*`, `aaa_all_sentences*`, `aaa_sentences*`). Nó
  **nhân đôi AAA** dưới quy ước tên file khác (`AAA_2013.pdf` vs `AAA_Baocaothuongnien_2012.pdf` cho
  cùng nội dung), làm tỷ trọng AAA trong `esg_all_records.jsonl` phồng lên ~2×.
- Nếu những đường dẫn đó còn trên đĩa từ một lần pull cũ → đó là **rác cần bỏ qua/xoá**, không phải
  nguồn dữ liệu thứ hai.

> **Trước khi kết luận "chỉ có AAA được gán nhãn" hoặc "thiếu corpus toàn ngành", hãy kiểm
> `data/labeled/classified/` và `data/outputs/esg_extracted/classified/` trước.**

### 5.5 Schema record đầu ra

```json
{"source_file": "...", "source_pdf": "AAA_Baocaothuongnien_2021.pdf", "page": 38,
 "sentence_index": 12, "text": "...", "labels": ["Environmental"],
 "scores": {"Neutral": 0.08, "Environmental": 0.91, "Social": 0.03, "Governance": 0.05}}
```

Một record được giữ khi `labels` không rỗng. Ba trường `source_pdf` / `page` / `sentence_index` là
**khoá truy nguyên** đi xuyên toàn bộ hệ thống (§2.3) — cũng là **khoá ghép cặp** cho thống kê paired
ở §13.5, vì `claim_id` chưa tất định giữa các lần rebuild.

---

## 6. Kênh B — Tin tức độc lập (phía *hành vi*)

Đây là phía **conduct**. Nguyên tắc trung tâm: **crawler KHÔNG lọc**. Keyword ESG/tranh chấp chỉ dùng để
**truy hồi** (đẩy những bài hiếm lên trên nhiễu giá cổ phiếu); *model phía sau* mới quyết định cái gì là
bằng chứng.

```
config/company_annual_report.xlsx
        │ companies.py   → bộ định danh mỗi công ty (mã CK — chỉ đi kèm từ khoá phân biệt,
        │                  tên pháp lý đầy đủ, tên thương hiệu đã làm sạch)
        │ queries.py     → sinh truy vấn (định danh × nhóm từ khoá ESG/controversy)
        ▼
   sources/  →  Google News RSS | Bing | DuckDuckGo        (kênh miễn phí)
        │ fetch.py   HTTP có cache đĩa, rate-limit theo domain, luân phiên UA,
        │            backoff khi 403/429/503  → chạy lại/resume rất rẻ
        │ extract.py trafilatura → title / text / publish_date
        │ normalize.py → tách câu bằng CHÍNH data_processing.sentence_splitter
        ▼
data/outputs/news/<TICKER>.jsonl  + coverage.csv
        │  {source_pdf, page, sentence_index, text} + metadata tin tức
        ▼  ViDeBERTa-v3-ESG (cùng model, cùng đường như báo cáo)
data/labeled/news_labeled/all_news_sentences_classified.jsonl
        ▼  python -m data_processing.preprocess_news         (P1)
data/interim/news_preprocessed/  + preprocess_news_stats.json
```

### 6.1 Vì sao news dùng đúng schema của báo cáo

`normalize.py` phát ra đúng bốn trường `source_pdf, page, sentence_index, text` và **import bộ tách câu
từ chính pipeline báo cáo** — bảo đảm phân đoạn câu **giống hệt**. Nhờ vậy tin tức đi qua **cùng một
đường** (classifier → extract_triples → KG) mà không cần nhánh code riêng. Với tin tức, `source_pdf`
mang dạng `<TICKER>__<domain>__<hash>` — tiền tố này về sau chính là cơ sở để **quy thuộc bằng chứng**
(§13.3) và để **scope kho conduct theo mã CK** (§10.2).

### 6.2 `preprocess_news.py` — đúng hai việc, không hơn

1. **Chuẩn hoá ngày:** `publish_date` của tin tức không đáng tin (placeholder `2002-01-01` của
   trafilatura, giá trị bằng ngày crawl, chuỗi rỗng). Stage này tính ngày hiệu lực đáng tin + cờ bất
   định, thêm `publish_date_normalized`, `publish_year`, `date_uncertain`.
2. **Bỏ boilerplate:** loại dòng rác bằng tín hiệu crawler đã phát ra (`company_mentioned`, `text` gần
   rỗng).

**Ngoài phạm vi có chủ ý:** KHÔNG route theo `source_domain`, KHÔNG có `news_domain_policy.json`, và
**KHÔNG** bỏ dòng `esg=false` (cổng ESG phía trên được tin cậy). Stage này **không phá huỷ**: mọi trường
gốc được giữ, chỉ **thêm** ba trường mới.

### 6.3 `crawl_data/crawler_news.py` — legacy, đừng nhầm

Đây là crawler tin **riêng cho FPT**, standalone (không phải package `-m`, không nối vào pipeline B).
Coi là công cụ legacy/thử nghiệm, **không** phải đường tin tức chính thức của hệ thống.

---

## 7. Kênh C — 16 stage dựng Temporal KG (`src/esg_kg`)

Chạy từ **repo root**: `python src/run.py <stage> [args]`. `--list` in toàn bộ bảng.

### 7.1 Sơ đồ toàn cảnh

```
data/labeled/**.jsonl  (report)          data/interim/news_preprocessed/**.jsonl  (news)
        │                                          │
        │  ┌───────────────────────────────────────┘
        ▼  ▼
   [01] extract              → kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json      (LLM)
        ▼
   [02] extract_triples      → graph_output/graphs/<pdf_stem>/page{N}.json        (LLM)
        │                        (+ page{N}_bugged.json, page{N}_malformed.txt)
        │                        --source report | news  → stamp source_type
        ▼
   ╔═ KHỐI build_validated ═════════════════════════════════════════════════╗
   ║  [03]  fix_triples   validate + auto-swap chiều cạnh + ISO date + LLM  ║
   ║  [03b] anchor_kpi    gazetteer: KPIObservation --observedAtFacility--> ║
   ║  [03c] canonicalize  gán kpi_id từ 35 chỉ tiêu + backfill target_date  ║
   ║  → graph_output/validated/all_validated_triples.json  (ghi ĐÚNG 1 LẦN) ║
   ╚════════════════════════════════════════════════════════════════════════╝
        ▼
   [04] issuer               → config/issuer_registry.json     (chạy-một-lần, người xác nhận)
        ▼
   ╔═ KHỐI build_resolved ══════════════════════════════════════════════════╗
   ║  [05]  entities      Stage A (định danh + anchor issuer/standards)     ║
   ║                      Stage B (blocking VN + embedding), Stage C (LLM), ║
   ║                      Stage D (consolidate → temporal_versions)         ║
   ║  [05b] provenance    stamp source_doc / source_page / article_*        ║
   ║  [05c] indicators    dựng trục chỉ tiêu TT96/GRI (StandardIndicator)   ║
   ║  → graph_output/resolved/resolved_graph.json           (ghi ĐÚNG 1 LẦN)║
   ╚════════════════════════════════════════════════════════════════════════╝
        ├──▶ [05d] align_claims   (LLM, TUỲ CHỌN, có ngân sách) — vá tại chỗ
        ├──▶ [11]  export_kgc     → graph_output/export_kgc/  (view SSRL, KHÔNG chạm bản gốc)
        ▼
   [06] neo4j_load           → Neo4j (đồ thị nền, bung version chain)
        ▼
   [07] claims_vs_conduct    → graph_output/crosscheck/<ticker>_claim_assessments.json  (LLM BẮT BUỘC)
        ▼
   [08] neo4j_sync           → Neo4j lớp advisory (KHÔNG LLM — dùng lại hồ sơ đã trả tiền)
        ▼
   [09] claim_ledger         → stdout + <ticker>_claim_ledger.md   (chỉ đọc Neo4j)
        ▼
   api/main.py               → ESG Evidence View  http://localhost:8000

   [00] quality              → graph_output/quality/quality_report_<label>.{json,md}
                                (offline, KHÔNG LLM/DB — chạy TRƯỚC và SAU mọi thay đổi)
```

### 7.2 Khái niệm **KHỐI (BLOCK)** — vì sao tồn tại

Luật sinh ra khối (DESIGN.md §5.7): **khi N stage đều *đọc rồi ghi* cùng một artifact thì chúng không
phải N stage, chúng là một.** File trung gian khi đó không phải deliverable — nó là *trạng thái nội bộ*
bị rò ra thành *hợp đồng*, và chạy lại stage đầu sẽ **âm thầm phá** những gì stage sau đã thêm, kể cả
những thứ **đã trả tiền**.

Con số cụ thể của khối 03 (ghi trong docstring `build_validated.py`):

```
14.492  phase 1, offline           → rebuild miễn phí
+   90  phase 2, LLM               → ĐÃ TRẢ TIỀN, và không tất định
+   95  03b gazetteer anchors      → rebuild miễn phí
= 14.677 triple  (+ 683 kpi_id stamp từ 03c)
```

Chạy lại `fix_triples` một mình sẽ `write_text()` đè toàn bộ — mất anchor của 03b, mất stamp của 03c,
mất 90 repair đã trả tiền, **không một cảnh báo nào**. Khối giải quyết bằng cách truyền graph **trong bộ
nhớ** và ghi artifact **đúng một lần** ở cuối.

Hai luật giữ cho khối an toàn:

1. **Vẫn giữ đủ entry point từng stage** — mất khả năng chạy một stage riêng là mất khả năng chẩn đoán nó.
2. **Chỉ cache kết quả *đã trả tiền và không tất định*** (repair LLM, verdict adjudication), tuyệt đối
   không cache thứ "có phí nhưng tất định" (embedding).

`05d` **cố ý không** thuộc khối 05: nó tuỳ chọn, có ngân sách, và vá tại chỗ **sau** khi khối chạy xong.
Khối phải sinh ra `resolved_graph.json` đúng và đủ khi 05d hoàn toàn vắng mặt.

### 7.3 Chi tiết từng stage

#### `[00] quality` — `esg_kg.report.quality` (offline, KHÔNG LLM/DB)

Đo **Q1–Q8** của đồ thị đã phân giải, ghi `graph_output/quality/quality_report_<label>.{json,md}`.
**Chạy TRƯỚC và SAU mọi thay đổi schema/pipeline** với `--label` khác nhau, để mỗi lần sửa đều có ảnh
before/after đo được.

| Q | Đo gì |
|---|---|
| Q1 Accuracy | phần máy kiểm được: tên chưa NFC, tên bị vỡ do OCR |
| Q2 Consistency | cạnh hợp lệ theo schema + bất biến thời gian P4 + lint P1 (không có trường thời gian trong `identity_keys` của T1) |
| Q3 Conciseness | thực thể T1 trùng lặp theo tên đã normalize |
| Q4 Completeness | đếm node phía conduct (Controversy / Penalty / MediaReport / KPI news) |
| Q5 Timeliness | % cạnh có `valid_from`; độ phủ `date_uncertain` trên T2 news |
| Q6 Provenance | độ phủ `source_type` / `source_id` |
| Q7 Traversability | (a) median degree, (b) % node lá, (c) % truy vấn masked trả lời được ≤ 3 hop, (d) % claim tới được conduct qua đường có ≥ 1 cạnh cấu trúc, (e) % node T2 có degree ≥ 2 |
| Q8 Independence | bằng chứng conduct theo kênh (report vs news) |

Thêm ba khối phụ: **hub cluster (A1)** qua `metric/hub.py`, **reasoning readiness** R1 / R1' /
R1_trainable / R7 qua `metric/reasoning_readiness.py`, và **standards registry audit** (liệt kê cách viết
`Standard`/`Regulation` chưa được curate).

Cờ: `--label <name>`, `--skip-slow` (bỏ Q7(c)/(d) và R1/R7 vì nặng BFS), `--max-hops`,
`--standards-registry`.

> **Về `metric/hub.py`:** "hub" của đồ thị một công ty **không phải một node** — nó là **mọi node thuộc
> định danh của một issuer**, kể cả bản trùng còn sót sau phân giải. Coi hub là "node có degree cao nhất
> toàn cục" chỉ đúng khi `issuer_registry.json` có đúng một công ty; thêm công ty thứ hai là mỗi issuer
> tạo một ngôi sao riêng và không cái nào là max toàn cục nữa. Vì thế hub được xác định **theo registry**.

#### `[01] extract` — `esg_kg.kpi.extract` (LLM, chỉ Gemini)

Mỗi trang: text trang (dựng lại bằng cách nhóm câu theo `(source_pdf, page)`) + 35 định nghĩa KPI trong
`kpi_definitions_construction.json` → **structured output** → danh sách `KPIObservation` có kiểu.

- **Chỉ gửi trang có ≥ 1 câu `esg=true`** (nhưng gửi **toàn văn** trang đó); trang khác ghi file rỗng.
- Output: `kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json` — một file/trang.
- **Idempotent:** file đã tồn tại thì skip, không gọi lại client.
- Không có cờ `--provider` (đường `--provider openai` giai đoạn 2026-07-29→08-04 đã bị gỡ hẳn).

#### `[02] extract_triples` — `esg_kg.graph.extract_triples` (LLM)

Mỗi trang: text trang + KPI trang (từ step 01) + `config/schema.json` → **triple có chiều thời gian** →
đồ thị `{nodes, edges}`.

- `--source report` (mặc định) dùng **prompt phía claim**; `--source news` dùng **prompt phía conduct**
  (Controversy / MediaReport / Penalty / `KPIObservation` quan sát được). Mọi node/cạnh được stamp
  `source_type=report|news`.
- Output: `graph_output/graphs/<pdf_stem>/page{N}.json`, kèm `page{N}_bugged.json` (triple sai schema) và
  `page{N}_malformed.txt` (reply không parse được JSON) — **giữ lại cả cái sai**, để chẩn đoán được.
- Provider: Gemini mặc định (`build_gemini_client` + `GeminiContextCache`); `--provider deepseek` (thêm
  2026-08-06) bỏ qua context cache và **luôn gửi prompt đầy đủ theo trang** (`build_page_prompt`, không
  dùng bản rút gọn `build_page_body`) — nên `--no-context-cache` là **no-op** trên đường DeepSeek.
- **Ngôn ngữ đầu ra bắt buộc là tiếng Việt** cho `name` / `title` / `description` / free text (issue #6).
  Hai template `TEMPORAL_GRAPH_PROMPT_TEMPLATE` và `NEWS_GRAPH_PROMPT_TEMPLATE` bị pin **byte-for-byte**
  trong test — đổi chữ trong prompt vẫn "chạy" nhưng làm đổi **mọi** kết quả trích xuất.
- **`claim_id` tất định** (`assign_deterministic_claim_ids` / `make_deterministic_claim_id`): trước đây
  `claim_id` là chuỗi do LLM tự nghĩ ra, nên chạy lại step 02 trên **cùng một câu** có thể sinh id khác
  → âm thầm re-partition toàn bộ hồ sơ đã trả tiền (vì `SustainabilityClaim.identity_keys == ["claim_id"]`
  và step 08 resolve claim 100% theo `stable_id`, không fallback). Đây là GitHub issue #2 / mục C1, được
  khoá bởi `test/test_claim_id_deterministic.py`.

#### `[03] fix_triples` — `esg_kg.graph.fix_triples`

| Phase | Nội dung | Chi phí |
|---|---|---|
| 1 (offline) | dựng lại triple từ đồ thị từng trang; **tự đảo chiều** subject/object khi schema khai chiều ngược; validate schema đầy đủ → valid + invalid | miễn phí |
| 1.5 (offline, P4) | canonicalize mọi ngày về ISO `YYYY[-MM[-DD]]`; cảnh báo `valid_from > valid_to`; mặc định `date_uncertain` cho node T2 news còn thiếu | miễn phí |
| 2 (LLM) | batch các triple invalid, nhờ model sửa theo schema, re-validate, giữ cái đã hợp lệ | **có phí** |
| 3 | ghi `all_validated_triples.json` + `unfixable_triples.json` | – |

- `--renormalize` chỉ áp **phase 1.5** lên file đã tổng hợp (không LLM, giữ nguyên repair cũ).
- **`preserve_property_values` — guard quan trọng nhất của stage này:** phase 2 được sửa **HÌNH DẠNG**
  (class, chiều cạnh, trường thời gian) nhưng **tuyệt đối không** được dịch/định dạng lại/bịa/xoá **GIÁ
  TRỊ ĐO**. Một model được nhắc bằng tiếng Anh rất dễ "sửa" `tấn` → `tons` hoặc làm tròn một con số, và
  sai lệch đó đi thẳng vào hồ sơ đối soát mà không ai thấy. Cache lưu **reply thô** của model, guard áp
  ở đường ra — nên cải thiện guard cũng sửa luôn các repair đã cache.
- `BATCH_FIX_PROMPT` bị pin byte-for-byte trong test, cùng lý do như prompt step 02.

#### `[03b] anchor_kpi` — `esg_kg.graph.anchor_kpi` (offline, KHÔNG LLM)

Thực thi **P3** cho dữ liệu **đã trích xuất và đã trả tiền**: (1) dựng gazetteer tên `Facility` đã có
trong đồ thị validated; (2) với mỗi `KPIObservation`, resolve câu nguồn qua `source_id`
(`<source_pdf>_<page>_<sentence_index>`) về corpus JSONL có nhãn; (3) nếu câu **nêu đúng tên** một
facility đã biết (so khớp đã normalize tiếng Việt, có biên từ) thì phát ra cạnh mà extractor **đáng lẽ**
phải tạo:

```
KPIObservation --observedAtFacility--> Facility     (anchor_method = "offline_gazetteer")
```

Không tạo lớp mới, không tạo nhãn cạnh mới (P8). Có cờ `--max-per-facility` (guard P5 chống một facility
hút hết) và `--dry-run`. Với dữ liệu **trích mới**, anchor đến từ prompt step 02 thay vì stage này.

> **Hiện trạng (2026-08-07):** trên corpus hiện tại stage này ra **0 anchor mới** —
> `anchor_patch_stats.json` cho thấy cả **6.661** `KPIObservation` đều `kpi_without_resolvable_sentence`,
> tức `source_id` không resolve được về corpus JSONL (quy ước tên file của corpus toàn ngành đã khác).
> Gazetteer vẫn dựng được 151 tên facility. Đây là một hạng mục nợ kỹ thuật, xem §16.3.

#### `[03c] canonicalize` — `esg_kg.kpi.canonicalize` (offline, KHÔNG LLM)

Gán cho mỗi `KPIObservation` một **`kpi_id` canonical** từ vốn 35 chỉ tiêu, qua
`config/kpi_type_aliases.json` + `rapidfuzz` trên tên chính thức. Cũng ghi `unit_normalized`,
`value_normalized`, `period`, và backfill `Goal.target_date` bằng regex (chỉ năm tương lai).

Hai quyết định thiết kế phải giữ:

- **Ghi `kpi_id` MỚI, KHÔNG BAO GIỜ ghi đè `kpi_type`.** Lý do là **provenance**: `kpi_type` là **nguyên
  văn** extractor đọc trên trang, `kpi_id` là mã canonical nó map tới. Ghi đè giá trị thô thì một mapping
  sai không còn truy được về điều báo cáo thật sự nói. (Lý do phụ — **không còn là ràng buộc**:
  `kpi_type` nằm trong `identity_keys`, nên ghi đè sẽ re-cluster step 05 và đánh số lại mảng node mà hồ
  sơ step 07 đang index theo vị trí; nay việc trích lại toàn bộ là mục tiêu đã lên kế hoạch nên đó là
  *chi phí đã lên lịch*, không phải veto.)
- **Precision hơn recall.** ~85% phần đuôi không map được là KPI **tài chính thuần** ("Lợi nhuận sau
  thuế", đơn vị VND). Đó không phải mapping ESG bị thiếu — đó là nhiễu bị loại đúng: `reject_units` chặn
  thẳng. Node không khớp giữ `kpi_id = null` và **được liệt kê trong file stats** để từ điển alias được
  mở rộng có chủ đích.
- **`kpi_id_method` được stamp trên mọi node** để biết **luật nào đã quyết định**: `rejected_unit` (cố ý
  từ chối KPI tài chính) khác hoàn toàn `no_match` (từ điển alias có lỗ). Chỉ cái thứ hai là backlog.

#### `[04] issuer` — `esg_kg.registry.issuer` (chạy-một-lần, offline)

Dựng nháp **registry định danh của doanh nghiệp phát hành** — thứ mà step 05 cần để gộp **mọi biến thể
tên** của issuer vào một node **một cách tất định**, không bao giờ qua embedding hay LLM (issuer là
xương sống của toàn bộ đối soát).

Nguồn: `config/company_annual_report.xlsx` (mã CK → tên chính thức) + `all_validated_triples.json`
(các biến thể tên `Organization` thực sự xuất hiện, kèm tín hiệu cấu trúc: tên nào thường là **subject**
của cạnh dạng report → đó là issuer).

Mỗi tên `Organization` được phân vào: **`aliases`** (biến thể chắc chắn của issuer), **`exclusions`**
(thực thể chắc chắn khác — công ty mẹ, công ty con), **`needs_review`** (nhập nhằng, cần người xác nhận).

Output `config/issuer_registry.json` **được track trong Git và có edit của con người** — nên
`merge_preserving_edits` bảo đảm chạy lại **giữ nguyên** alias/exclusion đã xác nhận, chỉ tên **mới
thấy** được append vào `needs_review`. `--force` mới rebuild sạch.

> `normalize_name` (trong `core/naming.py`) là helper **chịu tải nặng nhất repo**: step 04 ghi registry
> bằng nó, step 05 **dẫn lại cùng khoá** khi phân giải — hai bên phải normalize **giống hệt** hoặc anchor
> issuer sẽ âm thầm ngừng khớp.

#### `config/standards_registry.json` — CONFIG TĨNH, không phải stage

5 văn bản tham chiếu sau trục chỉ tiêu (TT96, QĐ2171, QCVN09, SSC-IFC, GRI) cùng alias/exclusion +
`match_patterns` / `exclude_hints`. Stage `entities` dùng nó ở **Stage A.3** để đóng băng ≥ 4 cách viết
của GRI và cả VN/EN của TT96 về **một node canonical**.

**Sửa bằng tay** (thêm alias rồi chạy lại `entities`). **Không có script nào sinh ra nó**: công cụ reseed
cũ (`step04b`) đã bị **xoá hẳn** ngày 2026-07-29 vì nó **đọc output của step 05 trong khi step 05 đọc
output của nó** (vòng phụ thuộc), và lần quét đó chẳng thu được gì (mọi alias đều là seed hardcode). Vai
trò kiểm-độ-phủ của nó nay do `standards_registry_audit` trong `quality` đảm nhiệm.

#### `[05] entities` — `esg_kg.resolve.entities`

Gộp **rất nhiều node thực thể trùng** trong `all_validated_triples.json` thành thực thể canonical, **giữ
nguyên lịch sử thời gian** của từng thực thể. Là **thiết kế lại** cho bối cảnh tiếng Việt/greenwashing,
không phải port.

| Stage | Nội dung | Chi phí |
|---|---|---|
| **A** | Gộp tất định: khớp **chính xác** signature `identity_keys` (cả entity và observation) + **anchor issuer ĐÓNG BĂNG** (khớp thành viên chính xác theo `issuer_registry.json`) + **anchor standards ĐÓNG BĂNG** (A.3, `standards_registry.json`) | miễn phí |
| **B** | Blocking hiểu tiếng Việt, **chỉ cho thực thể không phải issuer**: B1 gộp theo signature đã normalize (dấu / loại hình pháp lý / hoa-thường); B2 blocking cosine bằng `gemini-embedding-001` (batch, L2-normalize) | B2 có phí |
| **C** | Adjudication `gemini-2.5-flash` trên các cặp nhập nhằng, **có ngân sách** (`--max-llm-pairs`) | có phí |
| **D** | Consolidate cluster → `temporal_versions`; chọn canonical **tất định**; rewire cạnh **theo năm** (giữ cạnh nhiều năm tách biệt) | miễn phí |

- **Chế độ chạy bình thường là `--no-llm`** (chỉ Stage A + B.1) — vì Stage B/C đang **ngủ**, không phải
  vì bị block billing. **Đừng mặc định đảo cờ này mà chưa kiểm tra.**
- `resolve()` được tách thành **`resolve_graph()` (hàm thuần: không I/O, không tạo client) + `main()`**
  ngay lúc migrate, vì khối `build_resolved` cần gọi trực tiếp.
- Cluster issuer **đóng băng**: danh tính của nó **không bao giờ** phụ thuộc embedding hay LLM.

#### `[05b] provenance` — `esg_kg.resolve.provenance` (offline, KHÔNG LLM)

Bước tổng hợp ở step 03 làm mất ngữ cảnh "node này đến từ file trang nào". Nhưng các file
`graph_output/graphs/<doc>/page{N}.json` vẫn còn trên đĩa và **đường dẫn của chúng mã hoá đúng doc +
trang**. Stage này vá lại, offline:

1. Index mọi node file-trang theo `stable_id` **và** theo `properties.source_id` thô → `{(doc, page)}`.
2. Với mỗi node claim/evidence trong `resolved_graph.json` (thuộc `PROVENANCE_CLASSES` — **không bao giờ**
   thực thể T1, vì T1 xuất hiện trên hàng chục trang), khớp lại qua **4 tầng ưu tiên**:
   `source_id` parse được → index `source_id` khớp chính xác → `stable_id` tính lại → token `_pageNN_`;
   rồi stamp `source_doc` / `source_page` / `provenance_method`.
3. Với doc tin tức (`TICKER__domain__hash`), stamp thêm `article_title` / `article_url` /
   `source_domain` từ corpus JSONL news để UI trích dẫn được **tên bài**.

**Bất biến cứng: mảng node KHÔNG BAO GIỜ được thêm/bớt/đổi thứ tự** — chỉ mutate dict `properties`. Vì
step 06 khoá node Neo4j theo **chỉ số mảng** (`_node_key = f"n{i}"`) và hồ sơ step 07 tham chiếu node
theo `node_index` / `claim_node_index`; đổi thứ tự là âm thầm phá lớp advisory. Node đã có
`provenance_method="extraction"` (output step 02 mới, tự stamp) được **bỏ qua**.

> **Hiện trạng (2026-08-07):** `provenance_patch_stats.json` cho thấy **toàn bộ** node ở mọi lớp đều
> `already_stamped` và `per_method` rỗng → step 02 hiện **tự stamp provenance**, nên stage này thực tế là
> **no-op** trên corpus này. Vẫn phải chạy nó sau mỗi lần chạy lại step 05 (dữ liệu cũ có thể chưa stamp).

#### `[05c] indicators` — `esg_kg.resolve.indicators` (offline, KHÔNG LLM)

Biến vốn 35 chỉ tiêu (đang là **thuộc tính chuỗi** trên `KPIObservation`, không traverse được trong
Neo4j) thành **cấu trúc đồ thị hạng nhất**:

```
(Regulation TT96) <--partOf-- (StandardIndicator TT96-6.1.1) <--measuredUnder-- (KPIObservation)
                                     │ --alignsWithIndicator-- (SustainabilityClaim / Goal / Initiative)
                                     │ --equivalentTo-->       (StandardIndicator GRI 305-1)
```

`StandardIndicator` là **ĐIỂM NỐI**: *tuyên bố* của doanh nghiệp về một chỉ tiêu và các *KPI conduct* đo
theo chỉ tiêu đó cùng treo vào **một node**, nên step 07 so hai phía bằng cách đi **hai hop** thay vì
đoán theo trùng token.

Bốn quy tắc nghiêm:

- **CHỈ APPEND.** Chỉ thêm vào cuối `nodes[]`/`edges[]`, không đổi thứ tự/thay thế item cũ; được phép
  mutate `properties` tại chỗ (ví dụ stamp `self_reported_zero`). `GraphPatch.assert_append_only()`
  chứng minh điều đó bằng cách snapshot `id()` của mọi node/cạnh trong prefix trước khi ghi.
- **Không đoán chỉ tiêu của một KPI** — đọc `kpi_id` mà 03c đã gán. Nhờ ranh giới này, một mapping sai
  luôn truy được về 03c hoặc file alias.
- **`Penalty` có `amount == 0` là lời TỰ KHAI "bị phạt 0 lần", KHÔNG phải bằng chứng conduct.** Nối nó
  vào TT96-6.5.x sẽ biến một lời tự khen thành một vi phạm. Nó được gắn cờ `self_reported_zero` và
  **KHÔNG** có cạnh `measuredUnder`. Đây đúng là kiểu sai lầm mà một công cụ chống greenwashing tuyệt
  đối không được mắc.
- **`equivalentTo` (TT96→GRI) chỉ phát cho dòng crosswalk `status=confirmed`** do người xác nhận; dòng
  `needs_review` bị bỏ qua. `--trust-draft-crosswalk` chỉ để demo.

Ngoài ra stage **RESTAMP `StandardIndicator.pillar`** từ **file có quyền nói**:
`kpi_definitions_construction.json` cho vốn từ tiếng Việt, `config/gri_catalog.json` (`--gri-catalog`)
cho GRI — và **không bao giờ bịa**: id mà cả hai file đều không phủ thì **giữ pillar cũ**. Giao diện
Evidence View đọc thẳng thuộc tính này để xếp cột E/S/G, nên một cái đoán ở đây là người đọc thấy ngay.

#### `[05d] align_claims` — `esg_kg.resolve.align_claims` (LLM, TUỲ CHỌN, có ngân sách)

Gán `alignsWithIndicator` cho các `Claim`/`Goal`/`Initiative` mà **tầng keyword của 05c không giải được**.

- **Đây là PHÂN LOẠI CHỦ ĐỀ** ("tuyên bố này nói về chỉ tiêu TT96/SSC-IFC nào, nếu có?"),
  `alignment_method=llm` — **KHÔNG** phải phán quyết supports/contradicts. Việc xét tuyên bố có được
  thực hiện hay không thuộc lớp advisory của step 07.
- Tách khỏi 05c để mỗi stage **hoặc "KHÔNG LLM" hoặc "LLM"** rõ ràng: 05c miễn phí và chạy lại tuỳ ý,
  05d là chỗ duy nhất tốn tiền ở nhóm này.
- **Pipeline hoàn chỉnh mà không cần stage này.** Cờ: `--max-llm-pairs`, `--dry-run`, `--provider`,
  `--model`.
- Bẫy đã ghi lại: `node_text` ở đây nhận **dict properties**, còn `node_text` của step 07 nhận **cả
  node** rồi dispatch theo class. **Hợp nhất hai hàm sẽ âm thầm viết lại prompt đã trả tiền của bên kia.**
  Giữ tách biệt.

#### `[06] neo4j_load` — `esg_kg.load.neo4j_load` (KHÔNG LLM, cần Neo4j chạy)

Nạp `{nodes, edges}` đã phân giải thành property graph truy vấn được. **Thiết kế lại**, không phải port.
Hai điều tuyệt đối không được sai:

1. **Không dedup lại thực thể** — step 05 sở hữu danh tính. Id của node là **chỉ số mảng**
   (`_node_key = "n{i}"`); cạnh được rewire từ chỉ số sang khoá đó.
2. **Giữ thời gian của cạnh.** `temporal_metadata` được flatten lên quan hệ, và cạnh `MERGE` theo
   `_edge_key` **tất định có chứa trường thời gian**, nên nhiều cạnh cùng cặp nhưng khác năm **vẫn tách
   biệt** (MERGE ngây thơ sẽ gộp chúng và phá luôn chuỗi thời gian).

`temporal_versions` được materialize **đúng theo schema cho phép**: lớp nào có cạnh `supersedes` tự trỏ
hợp lệ thì bung thành **chuỗi version node** (`canonical -[:supersedes]-> mới nhất -> ... -> cũ nhất`);
lớp còn lại giữ lịch sử dưới dạng **property JSON string** để không phát cạnh sai schema. Cờ: `--clear`,
`--no-versions`, `--database`, `--strict`, `--dry-run`.

#### `[07] claims_vs_conduct` — lõi phân tích → xem §10

#### `[08] neo4j_sync` — `esg_kg.load.neo4j_sync` (KHÔNG LLM)

Step 07 lưu **bức tranh đầy đủ** chỉ trong hồ sơ JSON, nên hai thứ không tự tới Neo4j: (a) `assessment` /
`caveats` / `signals` theo từng claim (chúng là *tóm tắt tính ra*, không phải cạnh); (b) các mâu thuẫn
dựa trên `KPIObservation` (schema **không có** cạnh contradiction Claim→KPIObservation hợp lệ).

Stage này lấp khoảng trống đó **mà không tốn một token**: đọc lại hồ sơ mà lần chạy LLM đã trả tiền, rồi
MERGE vào đồ thị thành **lớp advisory được gắn cờ rõ ràng**:

- Trên node `SustainabilityClaim`: `assessment`, `assessment_is_advisory=true`, `caveats` (list),
  `structural_contradiction`, `kpi_gap`, `crosscheck_ticker`.
- Cạnh advisory Claim→node bằng chứng: `llm_supports` / `llm_contradicts` / `llm_flagged_support`, mỗi
  cạnh mang `llm_suggested=true` + `confidence` / `rationale` / `provider` / `evidence_text` /
  `evidence_class` / `source_domain` / `date` / `year` / `independent` / `date_uncertain` / `role`.

**Idempotent** (MERGE trên `_adv_key` ổn định). Việc resolve node **không** chỉ là `f"n{node_index}"`:
hồ sơ ghi *vị trí* trong mảng node, nên bất kỳ lần chạy lại step 05 nào thay đổi clustering sẽ làm vị
trí lệch — vì thế nó resolve **qua `stable_id` trước**. Cờ: `--clear-advisory`, `--dry-run`.

> **Bug đã sửa 2026-08-07 (commit `7c108f9`):** lệnh DELETE cạnh của `--clear-advisory` **không hề được
> scope**, nó khớp cạnh `llm_suggested` của **mọi mã CK trong toàn database**, dù docstring của chính nó
> nói "for this ticker". Nay đã scope theo đúng các claim trong hồ sơ đang sync.

#### `[09] claim_ledger` — `esg_kg.report.claim_ledger` (KHÔNG LLM, CHỈ đọc Neo4j)

Stage trình bày cuối cùng. Đọc lớp advisory mà step 08 đã ghi vào Neo4j và render **sổ nhật ký tuyên bố**
theo từng công ty, **ưu tiên tín hiệu**: `contradicted` → `supported` → `unverified`, luôn kèm caveat độ
phủ. **Không** gọi LLM, **không** đọc file hồ sơ JSON (nó nằm một bước phía trên).

Cờ: `--review-queue` (có mâu thuẫn mà không có xác nhận độc lập — hàng đợi cần người xem),
`--assessment`, `--claim-id`, `--limit`, `--markdown`.

#### `[11] export_kgc` — `esg_kg.export.export_kgc` (offline, KHÔNG LLM)

Hub của issuer (AAA: degree 9.511 ở lần đo trong docstring, 66% toàn bộ cạnh) là lý do **R5** (cổng
max-degree ≤ 500) **không đạt**, và thêm công ty **không** giải quyết được (mỗi công ty thêm một ngôi sao
của riêng nó). Stage này giảm max degree **cho một VIEW xuất ra để huấn luyện SSRL/RL**, bằng cách nhóm
cạnh của một hub cluster vào các node tổng hợp **`HubBucket`** khoá theo `(year, predicate)` —
**mà không bao giờ chạm** `resolved_graph.json` hay Neo4j (ranh giới P6).

- Dùng lại **chính** máy nhận diện hub multi-issuer của `metric/hub.py`, nên khái niệm "hub" ở đây luôn
  **nhất quán** với R5/Q7(d) của `quality`.
- Chỉ cluster có **tổng degree** vượt `--max-bucket-degree` (mặc định 500) bị phân rã; công ty/cluster
  nhỏ đi qua **không đổi**.
- v1 **chỉ** bucket theo `(year, predicate)`, không khoá thứ ba. Có bucket vẫn vượt ngưỡng (một tổ hợp
  năm × quan hệ quá lớn) — `--stats-out` báo **trung thực** (`buckets_over_threshold`, `threshold_met`)
  thay vì cưỡng chế cho vừa. Kết quả đã kiểm trên đồ thị AAA thật: max degree **9.511 → 542** (357
  bucket).
- **`HubBucket` KHÔNG được thêm vào `config/schema.json`** — nó là **artifact dựng dataset**, không phải
  thực thể T1/T2/T3. Mọi node/cạnh mới đều mang cờ `is_synthetic` (P7): một bước nhảy qua bucket không có
  câu nguồn, nên phải được gắn cờ, không được trình bày như một bước suy luận trích dẫn được.

### 7.4 Kernel dùng chung `esg_kg/core/`

Sau refactor, **không stage nào import internals của stage khác nữa**. Mọi thứ chia sẻ đi qua `core/`:

| Module | Nội dung | Cảnh báo |
|---|---|---|
| `paths.py` | `REPO_ROOT` + các đường dẫn dùng chung | Root tìm bằng **marker** (thư mục có cả `config/` và `.git`), không đếm số cấp cha → import từ độ sâu nào cũng đúng |
| `schema.py` | `load_schema_sets`, `validate_triple`, `get_identity_keys` | hàm thuần trên dict schema |
| `naming.py` | `normalize_name`, `name_tokens`, `merge_preserving_edits` | `normalize_name` chịu tải nặng nhất repo (§7.3 step 04) |
| `dates.py` | `ISO_DATE_RE`, `normalize_date_string`, `date_start_key` | `normalize_date_string` trả `(value, parseable)` — cách viết lạ trả về **nguyên trạng** với `parseable=False`, **không bịa ngày**. `date_start_key` chiếu ngày một phần về mốc bắt đầu ("2011" và "2011-01-01" cùng khoá) — chính là fix P4 |
| `identity.py` | `parse_source_id`, `get_stable_entity_id`, `PROVENANCE_CLASSES` | `get_stable_entity_id` là khoá mà **mọi** dedup và mọi match provenance tầng 3 chạy trên đó. Hai default của nó (thiếu class → `"Unknown"`; class không có trong map → `["name"]`) và `strip().lower()` là **hành vi**, không phải sự sạch sẽ — đổi là đồ thị **âm thầm re-partition**. Nó **cố ý KHÔNG** phải `normalize_name` |
| `io_jsonl.py` | `load_pages_from_jsonl`, `build_page_text`, `page_has_esg`, `select_documents`, `parse_company_year_from_filename` | dựng lại text theo trang từ JSONL câu |
| `llm.py` | `RateLimiter`, `DEFAULT_MODEL`, 3 provider, `build_gemini_client`, `build_llm_provider`, `GeminiContextCache` | `Adjudicator` **cố ý không** ở đây (nó là logic stage) |
| `llm_cache.py` | `ContentCache` — cache content-addressed, thread-safe | §4.3 |
| `graph_patch.py` | `GraphPatch`, `assert_append_only`, `temporal_md` | Bảo vệ bất biến "chỉ append" mà step 06 và hồ sơ step 07 phụ thuộc |
| `console.py` | `ensure_utf8_stdout` | Chỉ win32; lỗi bị **swallow có chủ ý** (mất echo terminal thì chấp nhận được, crash một report đã ghi xong lên đĩa thì không); **không bao giờ** gọi lúc import — stage gọi ở đầu `main()` |
| `datasync.py` | pull/push/status snapshot Hugging Face | Không phải stage; tự resolve `REPO_ROOT` để chạy được trên clone trắng |

> **Đổi signature của một helper trong `core/` là ảnh hưởng mọi stage import nó.** Chạy lại
> `test/test_esg_kg_equivalence.py` sau mỗi lần sửa `core/`.

### 7.5 Ba bài học refactor đáng mang sang việc khác

1. **"Hub" phải xét theo CHIỀU import, không phải theo số file import mình.** Một stage bị 7 stage khác
   import vẫn có thể là **lá** an toàn để di chuyển, nếu mọi symbol chúng lấy **đã** nằm trong `core/`.
2. **Hằng số cùng tên không phải hằng số dùng chung.** Hai module đều khai `DEFAULT_RATE_LIMIT = 10`
   trông như cơ hội de-dup nhưng không phải — import cái này vào cái kia là **âm thầm ghép** hai giá trị
   chỉ *tình cờ* bằng nhau.
3. **Hai helper cùng tên có thể cố ý khác nhau.** Repo này có **hai** hàm `node_text` (một nhận dict
   properties, một nhận cả node rồi dispatch theo class); gộp chúng sẽ **âm thầm đổi một prompt LLM đã
   trả tiền**.
4. **Muốn test một stage có phí/có mạng mà không tốn tiền: stub BÊN DƯỚI lớp trừu tượng**, không phải
   bọc quanh cả hàm. Nếu stage đi qua `_GeminiProvider` / `google.genai.Client` / một class driver DB thì
   thay **đúng attribute đó** bằng stub tất định (ví dụ trả lời theo CRC của prompt) — logic thật vẫn
   chạy, chỉ I/O là giả.

### 7.6 Ba stage đã bị XOÁ HẲN khỏi dự án (không phải "chưa port")

| Stage cũ | Vì sao xoá | Thay thế |
|---|---|---|
| `step10` (báo cáo evaluation P6) | Dự án bỏ hẳn kiểu đo coverage/case-study/ablation **không có ground truth** như một deliverable (2026-07-28) | Không có lệnh thay thế. Vai trò đánh giá nay thuộc `evalu/` (§13) — một thiết kế khác hẳn |
| `step04b` (reseed standards registry) | **Vòng phụ thuộc**: nó đọc output step 05 trong khi step 05 đọc output của nó; và lần quét chẳng thu được gì (mọi alias là seed hardcode) — 2026-07-29 | `config/standards_registry.json` là config tĩnh sửa tay; `standards_registry_audit` trong `quality` lo phần kiểm độ phủ |
| `step07b` (softmax evidence-balance score) | **Không có gì trên UI đã giao đọc `assessment_scores`/`score_components`**; nhãn `assessment` phân loại luôn là output chính — và không có ground truth cho một *xác suất* greenwashing (2026-07-29) | Không có. Hồ sơ hiện không mang `assessment_scores` nữa |

<!--APPEND-->
