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

---

## 8. Schema đồ thị (`config/schema.json`)

**Nguồn sự thật duy nhất** của đồ thị: **28 lớp node**, **76 edge spec** ứng với **48 nhãn cạnh** khác
nhau. File nhỏ (22 KB) nhưng mọi stage đều validate theo nó.

### 8.1 Cấu trúc file

```json
{
  "nodes": [
    {"class": "Organization",
     "properties": ["name", "industry", "valid_from", "valid_to", "is_current"],
     "identity_keys": ["name"]}
  ],
  "edges": [
    {"label": "usesMaterial", "source_class": "Product", "target_class": "Material",
     "temporal_properties": ["valid_from", "valid_to", "recorded_at"]}
  ]
}
```

Một nhãn cạnh **có thể xuất hiện với nhiều cặp `(source_class, target_class)` hợp lệ**; validator coi
**bất kỳ cặp khớp** là hợp lệ và **tự đảo chiều** khi chiều bị ngược (step 03 phase 1).

### 8.2 Mô hình ba tầng T1 / T2 / T3

```
                            [T1 — IDENTITY / vô thời gian]
        (Organization)          (Facility)          (StandardIndicator)
        khoá timeless           khoá timeless        trục TT96 / GRI
              │                      │                       ▲
              │ claims               │ observedAtFacility     │ alignsWithIndicator /
              ▼                      ▼                       │ measuredUnder
   (SustainabilityClaim)      (KPIObservation) ──────────────┘
      [T3 — ASSERTION]         [T2 — OBSERVATION]
```

**T1 — Identity (thực thể, vô thời gian).**
`Organization`, `Person`, `Facility`, `Product`, `Material`, `Standard`, `StandardIndicator`,
`Certification`, `Regulation`, `Location`, `Authority`, `Country`, `Community`, `ClaimKeyword`.
Quy tắc: `identity_keys` **timeless**; lịch sử đổi thuộc tính lưu ở `temporal_versions` + cạnh
`supersedes`.

**T2 — Event / Observation (quan sát, sự kiện thực tế).**
`KPIObservation`, `Emission`, `Waste`, `Controversy`, `Penalty`, `MediaReport`, `Investment`,
`ThirdPartyVerification`, `Project`, `CarbonOffsetProject`.
Quy tắc: `valid_from` / `valid_to` / `recorded_at` là **thuộc tính bản chất** của node. Ba lớp
`KPIObservation` / `Emission` / `Waste` **hợp lệ khi mang thời gian trong `identity_keys`** — chúng được
version **theo từng quan sát**, khác hoàn toàn thực thể T1.

**T3 — Assertion (tuyên bố, mục tiêu của doanh nghiệp).**
`SustainabilityClaim`, `Goal`, `Initiative`, `ScienceBasedTarget`.
Quy tắc: đại diện phát biểu chủ quan; nối T1 `Organization` qua `claims`, `setsGoal`.

`test/test_schema_contract.py` kiểm **cả hai chiều** của P1 (T1 timeless **và** T2 observation **giữ
được** khoá thời gian) và kiểm mọi class thuộc **đúng một** tầng. **Bản đồ tầng được IMPORT từ
`report/quality.py`, không khai lại** — bản sao thứ hai sẽ trôi khỏi schema lint mà pipeline đang dùng.

### 8.3 28 lớp node

`Organization`, `Person`, `Facility`, `Product`, `Material`, `Emission`, `Waste`, `KPIObservation`,
`Standard`, `StandardIndicator`, `Certification`, `Regulation`, `Initiative`, `Goal`,
`SustainabilityClaim`, `ThirdPartyVerification`, `CarbonOffsetProject`, `ScienceBasedTarget`,
`Controversy`, `Penalty`, `MediaReport`, `Community`, `Location`, `Authority`, `Country`, `ClaimKeyword`,
`Investment`, `Project`.

### 8.4 48 nhãn cạnh

`adoptsStandard`, `aimsForCertification`, `alignsWithIndicator`, `claims`, `contradictedBy`,
`contradictedByMedia`, `enforcedBy`, `equivalentTo`, `generatesEmission`, `generatesWaste`, `hasKeyword`,
`holdsCertification`, `impactsCommunity`, `investedIn`, `investsIn`, `involvedIn`, `isIn`, `issuedBy`,
`locatedIn`, `manufacturedAt`, `measuredUnder`, `mentionsFacility`, `mentionsOrganization`,
`mentionsProduct`, `observedAtFacility`, `offsetsWith`, `ownedBy`, `owns`, `ownsFacility`, `partOf`,
`partnersWith`, `producedBy`, `publishesReport`, `reducesEmission`, `reducesWaste`, `reportedBy`,
`reportsKPI`, `setsGoal`, `sourcedFrom`, `subjectToPenalty`, `subjectToRegulation`, `supersedes`,
`suppliedBy`, `takesPartIn`, `targetsScienceBased`, `usesMaterial`, `verifiedBy`, `worksAt`.

Nhóm theo vai trò:

| Nhóm | Nhãn |
|---|---|
| Cấu trúc doanh nghiệp | `owns`, `ownedBy`, `ownsFacility`, `worksAt`, `partnersWith`, `locatedIn`, `isIn` |
| Chuỗi giá trị / sản phẩm | `producedBy`, `usesMaterial`, `suppliedBy`, `sourcedFrom`, `manufacturedAt` |
| Tuyên bố & mục tiêu (T3) | `claims`, `setsGoal`, `takesPartIn`, `targetsScienceBased`, `aimsForCertification`, `hasKeyword` |
| Quan sát & tác động (T2) | `reportsKPI`, `generatesEmission`, `generatesWaste`, `reducesEmission`, `reducesWaste`, `observedAtFacility`, `impactsCommunity`, `investsIn`, `investedIn`, `offsetsWith` |
| Chuẩn & pháp quy | `adoptsStandard`, `subjectToRegulation`, `holdsCertification`, `issuedBy`, `partOf`, `equivalentTo`, `measuredUnder`, `alignsWithIndicator` |
| Phía conduct / tin tức | `mentionsOrganization`, `mentionsFacility`, `mentionsProduct`, `publishesReport`, `reportedBy`, `involvedIn`, `subjectToPenalty`, `enforcedBy` |
| Đối soát (step 07 ghi) | `verifiedBy`, `contradictedBy`, `contradictedByMedia` |
| Thời gian | `supersedes` |

`mentionsFacility` (MediaReport → Facility \| Location) là bổ sung gần đây (mục C2/B2): schema trước đó
cho MediaReport neo vào `Organization` hoặc `Product` nhưng **không có cách neo trực tiếp vào facility
hay địa điểm** mà bài báo thật sự nêu — đó chính là lý do Q7(e) của lớp MediaReport thấp. Khoá bởi
`test/test_mentions_facility_edge.py`.

### 8.5 Các bất biến schema mà validation phụ thuộc

1. **Ở bước trích xuất (02/03):** mọi node mang `valid_from`, `valid_to`, `is_current`; mọi cạnh mang
   `temporal_metadata`.
2. **Ở đồ thị đã phân giải (05+):** thời gian sống trên **cạnh + node T2/T3** (P2); node T1 vô thời gian,
   lịch sử ở `temporal_versions`.
3. **Ngày là ISO `YYYY[-MM[-DD]]`** (step 03 phase 1.5); một chuỗi version có version mở thì có **đúng
   một** `is_current=true` (P4, kiểm ở step 05).
4. **Mỗi node có `identity_keys`** dùng để tính stable entity id (dedup/versioning). **Danh tính T1 là
   timeless (P1)** — `quality` lint điều này.
5. **Lớp observation từ tin tức** (`KPIObservation`, `Controversy`, `Penalty`, `MediaReport`) mang cờ
   **bắt buộc** `date_uncertain`: `false` khi bài báo nêu ngày/kỳ rõ ràng cho *chính fact đó*, `true` khi
   prompt news của step 02 phải lấy ngày publish làm proxy — **không bao giờ âm thầm giả định năm publish**.
   Step 07 biến cờ này thành **caveat** trên bất kỳ hồ sơ nào có bằng chứng ngày bất định.

### 8.6 Quy tắc khi sửa `schema.json`

Chạy `python test/test_schema_contract.py` sau **bất kỳ** lần sửa tay. Nếu thay đổi ảnh hưởng
step 03/03b/03c/05/05b/05c/08 thì chạy thêm `python test/test_temporal_invariants.py`. Và luôn có ảnh
`quality --label before-… / after-…`.

---

## 9. Trục chỉ tiêu TT96 / GRI

Đây là phần làm cho hệ thống **đối chiếu được với khung công bố thông tin thực tế của Việt Nam**, thay vì
chỉ so khớp từ khoá.

### 9.1 `kpi_build/` — 35 KPI tiếng Việt, trích **nguyên văn** kèm provenance

Pipeline chạy-một-lần `01_…` → `06_…`:

| Script | Việc |
|---|---|
| `01_download_sources.py` | tải văn bản gốc |
| `02_extract_section6.py` | trích Mục 6 (công bố thông tin môi trường & xã hội) |
| `03_download_sector_sources.py` | tải nguồn theo ngành |
| `04_extract_sector_kpis.py` | trích KPI theo ngành |
| `05_build_kpi_definitions.py` | hợp thành `kpi_definitions_construction.json` |
| `06_enrich_kpis.py` | bổ sung đơn vị / mô tả |

Bốn nguồn pháp quy/hướng dẫn:

| Mã | Văn bản |
|---|---|
| `TT96-*` | **Thông tư 96/2020/TT-BTC** — công bố thông tin trên thị trường chứng khoán |
| `QD2171-*` | **Quyết định 2171/QĐ-TTg** |
| `QCVN09-*` | **QCVN 09** (quy chuẩn kỹ thuật) |
| `SSCIFC-*` | Hướng dẫn công bố thông tin **môi trường & xã hội** của **UBCKNN (SSC) – IFC** |

Kết quả: **35 KPI**, mỗi KPI mang một block `source` (văn bản, trang, đoạn nguyên văn). Đây là **vốn từ
KPI có kiểm soát** mà step 01 dùng làm schema trích xuất. Coi như **dữ liệu sinh ra**: rất ít khi phải
dựng lại.

### 9.2 `gri/` — 136 mã chỉ tiêu GRI từ 42 PDF chuẩn

- `gri/crawl_full_gri.py` tải 42 PDF vào `gri/full_gri/Full set of GRI Standards - English/` và trích ra
  `gri/full_gri/json/`.
- `gri/build_gri_catalog.py` hợp thành **`config/gri_catalog.json`**: **136 mã** GRI với `title_vi` /
  `title_en`, `pillar`, `units`, `tt96_equivalent`, `versions[]`, và `sha256` từng PDF.
- **KHÔNG phải một pipeline stage** (nó không đọc output nào của pipeline, nên khác `step04b`, không tạo
  vòng phụ thuộc). Dựng lại bằng tay sau khi sửa crawl/crosswalk, rồi **commit JSON đã sinh**.

> **Quy tắc "chủ sở hữu" phải biết trước khi sửa:** JSON của một chuẩn GRI **cũng liệt kê lại disclosure
> thuộc chuẩn KHÁC** (các chuẩn ngành GRI 11–14 và bản viết lại 2024/25 GRI 101–103 đều làm vậy). Vì thế
> một disclosure được quy cho **chuẩn mà `standard_id` là tiền tố của nó** — hàm `standard_of()` — chứ
> **không** cho file nào đọc trước. Trước khi có quy tắc này, `sorted(glob(...))` quyết định chủ sở hữu và
> `"gri_101"` sắp trước `"gri_2"`, nên **`GRI 2-27` từng bị publish với title/PDF/sha256/version của GRI
> 101 Biodiversity**: **80 trong 136** entry bị quy sai và **31 title** bị méo. `pillar` đi theo cùng
> quyết định đó (đọc từ nguồn qua `PILLAR_MAP`, **không** đoán theo hình dạng mã chỉ tiêu). Khoá bởi
> `test/test_gri_catalog_build.py`.

### 9.3 `config/standard_crosswalk.json` — TT96/SSC-IFC → GRI

Dữ liệu **do người curate và review**. Nó ở `config/` (**không** nằm trong
`kpi_definitions_construction.json`, vì file đó bị `kpi_build/` ghi đè tại chỗ). Step 05c **chỉ** phát
cạnh `equivalentTo` cho dòng `status == "confirmed"`; dòng trong `needs_review` bị bỏ qua đến khi có
người xác nhận. Bản nháp do LLM dựng từ các họ chủ đề GRI, nhưng **phải có người đối chiếu** với sổ tay
SSC-IFC trước khi flip sang `confirmed` — độ mịn của mã GRI (ví dụ 305-1 Scope 1) không tự động tương
đương một chỉ tiêu TT96.

### 9.4 Trục chỉ tiêu trong đồ thị — ai gán, ai không được đoán

| Bước | Ai làm | Ghi gì |
|---|---|---|
| Gán `kpi_id` cho KPIObservation | **step 03c** (offline, alias + fuzzy) | thuộc tính `kpi_id` + `kpi_id_method` |
| Dựng node `StandardIndicator` + cạnh | **step 05c** (offline) | `partOf`, `measuredUnder` (đọc `kpi_id`, **không đoán**), `equivalentTo` (chỉ confirmed), `alignsWithIndicator` **tầng keyword** (cụm dài nhất thắng) |
| `alignsWithIndicator` phần còn lại | **step 05d** (LLM, tuỳ chọn) | `alignment_method=llm` — phân loại chủ đề, **không** phải phán quyết |
| `pillar` của indicator | **step 05c restamp** từ file có quyền nói | `kpi_definitions_construction.json` (VN) / `gri_catalog.json` (GRI); id không được phủ thì **giữ nguyên** |

**Tầng keyword "cụm dài nhất thắng" (longest-phrase matching)** là thứ gán được phần lớn cạnh
`alignsWithIndicator` cho hàng nghìn tuyên bố văn xuôi mà **không tốn một token LLM** — hiện có **807**
cạnh `alignsWithIndicator` trong đồ thị, trong đó **649** do lần chạy 05c gần nhất sinh (§12.3).

**Vì sao trục này quan trọng cho lõi phân tích:** `StandardIndicator` là **điểm nối** để step 07 lấy ứng
viên bằng chứng bằng **join 2 hop**:

```
claim --alignsWithIndicator--> (StandardIndicator) <--measuredUnder-- conduct(news)
```

LLM khi đó chỉ còn phải quyết định *supports/contradicts*, **không** phải quyết định *có liên quan hay
không* — đó là khác biệt lớn về chất lượng adjudication (nhưng xem §16.5: trên dữ liệu hiện tại tầng này
đang cho **0 cặp**).

---

## 10. Đối soát chéo Claim ↔ Conduct — lõi phân tích (step 07)

`esg_kg/crosscheck/claims_vs_conduct.py` (900 dòng) là **lõi** của toàn bộ dự án. Nó đọc
`resolved_graph.json`, và với **mỗi `SustainabilityClaim`** của issuer, đi tìm bằng chứng conduct
supports/contradicts, rồi phát ra **hồ sơ bằng chứng có tính tư vấn**.

Đây là **phép nghịch đảo trong-đồ-thị** của các bước detection ở bản tham chiếu: ở đó claim là **một dòng
CSV bên ngoài** được chấm điểm với gold label; ở đây claim là **node đã nằm trong đồ thị**, đối soát với
node conduct **cũng đã nằm trong đồ thị**, sinh ra **liên kết bằng chứng có tính tư vấn** — không ground
truth, không tuyên bố accuracy.

### 10.1 Năm bước (6a → 6d)

```
6a  retrieve   lấy ứng viên conduct cho mỗi claim
6b  adjudicate LLM quyết định supports / contradicts / irrelevant   ← BẮT BUỘC
6c  link       ghi cạnh hợp lệ theo schema: verifiedBy / contradictedBy / contradictedByMedia
6c-guard       self-verification guard: domain của chính doanh nghiệp KHÔNG được tạo verifiedBy
6d  dossier    hồ sơ: bằng chứng + rationale + caveats + assessment tư vấn
```

### 10.2 6a — Truy hồi ứng viên (deterministic mặc định)

Kho conduct = node thuộc `CONDUCT_CLASSES` = {`Controversy`, `Penalty`, `MediaReport`, `KPIObservation`,
`ThirdPartyVerification`} **và** có `source_type == "news"`.

Ba điều kiện lọc:

| Điều kiện | Chi tiết | Tham số |
|---|---|---|
| **Cùng issuer** | scope theo tiền tố `<TICKER>__` của `source_doc`; node không parse được ticker (fixture tổng hợp, nguồn không phải crawler) thì **giữ lại** chứ không loại | – |
| **Trùng chủ đề (VN-aware)** | tokenize tiếng Việt bằng `underthesea` + **cổng tối thiểu số token trùng** | `--min-topic-overlap` (mặc định **2**) |
| **Cửa sổ thời gian** | conduct được phép sớm hơn claim tối đa `window_before` năm, và muộn hơn `window_after` năm | `--window-before` **1**, `--window-after` **50** |

Xếp hạng và ngân sách: `--top-k` (mặc định **8**) ứng viên/claim. Tầng chỉ tiêu được **cộng điểm rất
lớn** (`INDICATOR_BOOST = 1000`) để cặp join-qua-indicator **luôn** xếp trên cặp chỉ trùng token khi cắt
theo ngân sách LLM. `--embed` bật xếp hạng bằng embedding (tuỳ chọn, mặc định tắt).

> **Sửa lỗi nhiễm chéo — 2026-08-07, commit `7c108f9`.** §6a **luôn** được ghi là "cùng issuer + trùng
> chủ đề + cửa sổ thời gian", nhưng **nửa "cùng issuer" chưa bao giờ được thực thi**: kho conduct trải
> **mọi mã CK** đã crawl. Hệ quả là một token trùng tầm thường (ví dụ `phieu` dùng chung giữa "phiếu bầu"
> và "cổ phiếu" sau khi `cổ` bị bỏ như stopword) có thể **kéo Penalty của công ty khác vào hồ sơ của
> issuer này**. Cùng commit đó thêm: tokenize tiếng Việt bằng underthesea + cổng `min_topic_overlap`, và
> siết `ADJUDICATE_SYSTEM` để **yêu cầu bằng chứng khớp đúng chủ đề cụ thể** của claim, không chỉ "cả hai
> đều liên quan ESG/quản trị" — đóng lại kiểu **lập luận vầng hào quang (halo reasoning)** đã thấy trong
> rationale thực tế. Xem §16.1 để biết vì sao **hồ sơ hiện có trên đĩa vẫn là hồ sơ TRƯỚC bản sửa**.

### 10.3 6b — Adjudication là BẮT BUỘC, không có fallback tất định

- **Không** có `--no-llm`. Nếu không có provider khả dụng, stage **abort ngay từ đầu**.
- Provider do registry riêng của `Adjudicator` chọn: `--provider-order` (mặc định `gemini`; nhận
  `gemini` / `deepseek` / `openai`, dạng danh sách phẩy nếu muốn cascade).
- Giới hạn quota/chi phí bằng `--max-llm-pairs`, **không** bằng cách rơi về chế độ tất định.
- Adjudicate **song song** (`ThreadPoolExecutor`), kết quả cache content-addressed (§4.3) → chạy lại
  **miễn phí và tái lập**.
- `ADJUDICATE_SYSTEM` là **hành vi đã trả tiền, không phải văn phong**: đổi chữ vẫn "chạy" nhưng làm đổi
  **mọi verdict** stage này từng sinh ra → bị pin **byte-for-byte** trong `test/test_esg_kg_crosscheck.py`.
- `_parse_verdict` có guard `isinstance(out, dict)`: `json.loads("[]")` thành công (trả list, không phải
  dict) và dòng sau gọi `.get()` sẽ raise — trước khi có guard, một reply lạ-nhưng-parse-được bị **xếp
  sai thành "provider failure"** thay vì "reply không dùng được, no-op".

### 10.4 6c — Cạnh liên kết và guard độc lập

Cạnh ghi ra đều **hợp lệ theo schema** và đều mang `llm_suggested=true` (attributable, chạy lại được):
`verifiedBy`, `contradictedBy`, `contradictedByMedia`.

**Self-verification guard (§6.4):** nếu "bằng chứng độc lập" cho tuyên bố của AAA lại đến từ
`aaa.com.vn` thì đó vẫn là **báo cáo tự công bố**, chỉ đổi định dạng. Guard chặn **không cho** domain
thuộc chính doanh nghiệp tạo cạnh `verifiedBy`; những trường hợp đó đi vào
`flagged_non_independent_support` → cạnh `llm_flagged_support` ở lớp advisory.

Mâu thuẫn dựa trên `KPIObservation` **chỉ nằm trong hồ sơ**, vì schema không có cạnh contradiction
Claim→KPIObservation hợp lệ — step 08 mới đưa chúng vào Neo4j dưới dạng cạnh advisory `llm_contradicts`.

### 10.5 6d — Hồ sơ (dossier) và ba nhãn tư vấn

Output: `graph_output/crosscheck/<ticker>_claim_assessments.json` + `<ticker>_crosscheck_stats.json`
(+ `crosscheck_edges.json`).

| Nhãn | Nghĩa |
|---|---|
| `appears_supported` | có bằng chứng độc lập ủng hộ |
| `appears_contradicted` | có bằng chứng độc lập mâu thuẫn |
| `unverified_insufficient_evidence` | **không đủ** bằng chứng độc lập để kết luận |

**Ưu tiên khi map assessment: mâu thuẫn thắng ủng hộ** trong cùng một hồ sơ (được pin bằng fixture tổng
hợp trong test).

Mỗi hồ sơ luôn mang:
- `assessment_is_advisory = true`;
- `caveats[]` — trong đó có caveat **ngày bất định** khi bằng chứng có `date_uncertain=true`;
- `signals` — `structural_contradiction`, `kpi_gap`;
- `coverage_caveat`: *"Thin independent conduct — absence of contradiction is NOT exoneration."*

> **Hai signal `kpi_gap` / `structural_contradiction` hiện là *ghost signal*:** chúng có mặt trong hồ sơ
> nhưng step 07 chưa bao giờ **ghi** giá trị khác mặc định (mọi hồ sơ mẫu đều `structural_contradiction=false`,
> `kpi_gap=none`). Đây là phát hiện D1 của tài liệu mở rộng cross-check, và vẫn là **đề xuất chưa làm**.

Cờ khác: `--dry-run` (chạy LLM nhưng **không ghi gì** — dùng để xem trước cặp), `--to-neo4j` (ghi cạnh
trực tiếp vào Neo4j), `--ticker`, `--model`, `--rate-limit`.

### 10.6 Ví dụ thật từ hồ sơ trên đĩa (minh hoạ cả điểm mạnh và lỗi đã sửa)

Trích `graph_output/crosscheck/aaa_claim_ledger.md` (sinh **trước** bản sửa 2026-08-07):

```
### claim_4b15ccc97f6d18d5 — [2017-09-21, report] — AAA_2017 p.68
> "trao tặng số tiền 30.000.000 đồng để ủng hộ đồng bào miền Trung thiệt hại do cơn bão số 10."
Assessment: appears_contradicted (advisory)
 ✗ Penalty (conf 0.90, 2025, nhadautu.vn; AGG: ...bị phạt vì thao túng cổ phiếu):
   "Phạt tiền 3 tỷ đồng ... thao túng thị trường chứng khoán cổ phiếu AGG"
```

Đây là **ví dụ sách giáo khoa** cho hai lỗi mà bản sửa 2026-08-07 nhắm vào: (1) bằng chứng đến từ **feed
của AGG** nhưng bị dùng để kết luận về **AAA** (nhiễm chéo issuer); (2) rationale lập luận theo kiểu
**vầng hào quang** ("thao túng thị trường không phù hợp với hình ảnh tích cực") thay vì khớp **đúng chủ
đề cụ thể** của tuyên bố (cứu trợ bão lụt). Cả hai đã được xử lý trong code, **nhưng hồ sơ chưa chạy
lại** — §16.1.

---

## 11. Lớp Neo4j, sổ nhật ký tuyên bố và giao diện Web

### 11.1 Hạ tầng

`docker-compose.yml` dựng **Neo4j 5 Enterprise** (license dev miễn phí cho học thuật/không thương mại) —
chọn Enterprise để cả nhóm dùng **một user riêng** (`greenwashing`) và **một database có tên**
(`greenwashingkg`); Community chỉ có user `neo4j` và db mặc định.

```bash
docker compose up -d                      # bolt :8687 (map từ 7687), HTTP UI :8474
# chờ healthy, rồi bootstrap MỘT LẦN (idempotent):
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher
python src/run.py neo4j_load --clear      # nạp đồ thị
```

`neo4j/init.cypher` tạo database `greenwashingkg`, user `greenwashing` (với `SET HOME DATABASE`, nên
loader ghi đúng chỗ dù không truyền `--database`), và grant `admin` (đủ cho instance dev/capstone; server
dùng chung thì nên thu hẹp bằng role riêng).

`./neo4j_data:/data` giữ database qua các lần restart, **git-ignored** và **không bao giờ đồng bộ qua
Hugging Face** — một volume DB đang sống không copy an toàn được; dựng lại bằng `neo4j_load`.

### 11.2 Hai lớp trong Neo4j

| Lớp | Ghi bởi | Nội dung | Có LLM? |
|---|---|---|---|
| **Đồ thị nền** | step 06 `neo4j_load` | node/cạnh đã phân giải + `temporal_metadata` + chuỗi version | Không |
| **Lớp advisory** | step 08 `neo4j_sync` | `assessment` / `caveats` / `signals` trên claim + cạnh `llm_supports` / `llm_contradicts` / `llm_flagged_support` | Không (dùng lại hồ sơ đã trả tiền) |

Ranh giới này là **P5**: advisory phải **tách biệt và gắn cờ**, không bao giờ lẫn vào fact đã trích.

### 11.3 Vì sao Neo4j có nhiều node hơn `resolved_graph.json`

Kiểm chứng trực tiếp trên instance đang chạy (2026-08-07):

| | `resolved_graph.json` | Neo4j | Chênh |
|---|---|---|---|
| node | 10.634 | **13.181** | +2.547 |
| cạnh/quan hệ | 14.744 | **17.291** | +2.547 |
| `supersedes` | 30 | **2.577** | +2.547 |

Chênh lệch **khớp chính xác**: `temporal_versions` trên node được **bung thành chuỗi version node** cộng
đúng số cạnh `supersedes` tương ứng. Ví dụ `Organization`: 564 trong file → **1.615** trong Neo4j (phần
dư là version node). Nhãn `_Entity` gắn trên **cả 13.181** node.

Vì vậy, khi báo cáo số liệu, **luôn nói rõ đang đếm ở đâu**. Con số "chuẩn" để so sánh giữa các lần chạy
pipeline là con số của `resolved_graph.json`.

### 11.4 `neo4j/crosscheck_queries.cypher`

Bộ truy vấn cho analyst: liệt kê claim theo assessment, tìm claim có mâu thuẫn mà không có xác nhận độc
lập, đi ngược từ một bằng chứng về tuyên bố, xem chuỗi version của một thực thể…

### 11.5 Sổ nhật ký tuyên bố (step 09)

`python src/run.py claim_ledger` render sổ **từ Neo4j** (phải chạy `neo4j_sync` trước). Cấu trúc:
header (bảng đếm theo assessment + tóm tắt conduct độc lập + cảnh báo độ phủ) → các mục
`appears_contradicted` → `appears_supported` → `unverified`. Mỗi mục có: `claim_id`, ngày + kênh, trích
dẫn **trang báo cáo gốc**, đoạn tuyên bố, assessment, danh sách bằng chứng (class, confidence, năm,
domain, tiêu đề bài, đoạn text), `rationale`, `signals`, `caveat`.

`--review-queue` cho ra đúng hàng đợi cần người xem: **có mâu thuẫn mà không có xác nhận độc lập**.

### 11.6 ESG Evidence View (`api/` + `frontend/`)

```bash
python api/main.py        # http://localhost:8000
```

- `api/main.py` (120 dòng) là **`http.server` thuần stdlib** — cố ý không FastAPI/Flask để tránh lệch
  version framework. Endpoint: `GET /api/companies`, `GET /api/evidence/{ticker}?year=YYYY`, phục vụ
  static `frontend/` (có year filter + cache control).
- `api/evidence_service.py` (308 dòng) chứa **toàn bộ** truy cập dữ liệu, đọc **Neo4j sống** (đồ thị nền
  step 06 + lớp advisory step 08). **Neo4j là BẮT BUỘC** — mock data đã bị bỏ; helper truy vấn raise
  `RuntimeError` kèm hướng dẫn tiếng Việt nếu không kết nối được.
- **`frontend/` đóng băng**: mọi thay đổi nguồn dữ liệu chỉ được sửa trong `evidence_service.py`, không
  sửa frontend.

**Giao diện 3 cột × 3 trụ cột.** Ba trụ cột: 🌿 **Môi trường**, 👥 **Xã hội**, 🏛 **Quản trị** — lấy
**trực tiếp** từ `StandardIndicator.pillar` của cạnh `alignsWithIndicator`, **không đoán**. Ba cột:

| Cột | Nguồn |
|---|---|
| **Verified** (đã xác nhận) | claim có `assessment == "appears_supported"` |
| **Contradicted** (thực tế khác biệt) | claim có `assessment == "appears_contradicted"` |
| **Missing** (chưa đối soát) | hiện **để trống** — deferred |

**Nới lỏng thử nghiệm (2026-08-07):** trước đây **chỉ** claim có cạnh `alignsWithIndicator` mới hiển thị.
Nay `evidence_service` cũng surface claim verified/contradicted **không có** cạnh đó, nhưng pillar khi ấy
là **đoán theo từ khoá** trên chính text của claim và mọi thẻ như vậy bị stamp `standard_id="NGOÀI-KHUNG"`
để UI **hiển thị rõ** là ngoài khung chỉ tiêu — chứ không trình bày như thể có indicator bảo chứng. Đây
là ngoại lệ **có kiểm soát** với nguyên tắc "không đoán pillar", và nó tự khai báo trên giao diện.

**Bug pillar đã sửa cùng commit `7c108f9`:** node `StandardIndicator` của ASEAN CG Scorecard báo **chữ
mục nội bộ (A/B/C/D)** làm `pillar`, và fallback của UI âm thầm dồn chúng vào **Môi trường**. Nay được
patch về `"Quản trị"`.

---

## 12. Số liệu thực đo hiện tại

> **Cách đọc mục này.** Mọi con số dưới đây được đo lại ngày **2026-08-07** từ artifact trên đĩa, hoặc
> query trực tiếp Neo4j đang chạy. Chỗ nào là kết quả của một lần chạy **cũ hơn** artifact hiện tại thì
> được ghi rõ thời điểm và cảnh báo. Đây là *hiện trạng*, không phải *mục tiêu*.

### 12.1 Kho dữ liệu trên đĩa

| Đường dẫn | Số file | Dung lượng | Nội dung |
|---|---:|---:|---|
| `data/raw/annual_report/` | 1.420 | 16.949 MB | PDF BCTN đã tải + đã giải nén |
| `data/raw/annual_reports_sample/` | 14 | 108 MB | mẫu để test nhanh |
| `data/interim/sentences/` | 6 | 537 MB | mọi câu, chưa lọc ESG |
| `data/labeled/classified/` | 1 | 401 MB | `all_sentences_classified.jsonl` — **corpus BCTN toàn ngành** |
| `data/labeled/news_labeled/` | 2 | 187 MB | `all_news_sentences_classified.jsonl` — **corpus tin tức** |
| `data/interim/news_preprocessed/` | 3 | 64 MB | sau P1 (chuẩn hoá ngày, bỏ boilerplate) |
| `data/outputs/esg_extracted/` | 10 | 618 MB | record ESG đã trim cho Graph-RAG |
| `data/outputs/news/` | 116 | 164 MB | JSONL tin tức theo mã CK + `coverage.csv` |
| `kpi_output/` | 4.227 | 6 MB | KPI theo từng trang (step 01) |
| `graph_output/graphs/` | 3.957 | 29 MB | đồ thị theo từng trang (step 02) |
| `graph_output/validated/` | – | 26 MB | `all_validated_triples.json` (16,5 MB), `unfixable_triples.json` (937 KB), `phase2_repairs.json` (57 KB) |
| `graph_output/resolved/` | – | 12 MB | `resolved_graph.json` (11,6 MB) + các file stats |
| `graph_output/crosscheck/` | – | 2,5 MB | hồ sơ, stats, cache adjudication, log theo mã CK |
| `graph_output/quality/` | – | 732 KB | 12 cặp báo cáo `.json` + `.md` theo label |
| `graph_output/debug_outputs_per_page/` | – | 44 MB | prompt/response thô theo trang (để chẩn đoán) |

Snapshot Hugging Face: `nammovuivui-capstone/capstone`, revision **`902fcf84`**, pushed
**2026-08-07T06:50 UTC**, `code_commit = 7c108f9`, **~18.969 MB (~19 GB)**.

### 12.2 Corpus đã phân loại ESG

| Kênh | Doanh nghiệp / mã CK | Câu | Câu `esg=true` | Tỷ lệ |
|---|---:|---:|---:|---:|
| Báo cáo thường niên | **197** | 873.756 | 303.723 | 34,8% |
| Tin tức | **115** | 174.256 | 77.229 | 44,3% |

Tài liệu **đã trích thành đồ thị trang**: **137** thư mục doc = **46 BCTN** + **91 bài báo**.

- BCTN đã trích: các năm của **AAA** (2011–2025), **ACC** (2012–2026), **ACG** (2022–2026),
  **ADP** (2024–2026), **AGG** (2021).
- Tin tức đã trích, theo mã CK: **AAA 42**, **ACG 22**, **ACC 14**, **AGG 9**, **ADP 4**.
- **47 domain tin tức** khác nhau; nhiều nhất: `tinnhanhchungkhoan.vn` (11), `vietstock.vn` (7),
  `baodautu.vn` (6), `nhadautu.vn` (5), `dnse.com.vn` (4), `doanhnhan.baophapluat.vn` (4),
  `finance.vietstock.vn` (4), `cafef.vn` (3).

> **Khoảng cách quan trọng:** corpus **phân loại câu** đã ở mức toàn ngành (197 DN / 115 mã), nhưng
> **đồ thị mới dựng cho 5 mã CK** (AAA, ACC, ACG, ADP, AGG). Đây là chênh lệch chủ ý (chi phí LLM), nhưng
> phải nói rõ mỗi khi trích dẫn quy mô — xem §17.

### 12.3 Đồ thị đã phân giải (`resolved_graph.json`, ghi 2026-08-07 08:07)

**10.634 node / 14.744 cạnh.**

Node theo lớp:

| Lớp | Số | | Lớp | Số |
|---|---:|---|---|---:|
| `KPIObservation` | 6.560 | | `MediaReport` | 127 |
| `Organization` | 564 | | `Product` | 126 |
| `Goal` | 511 | | `Certification` | 78 |
| `SustainabilityClaim` | 481 | | `Material` | 50 |
| `Initiative` | 429 | | `Community` | 37 |
| `Location` | 237 | | `Authority` | 36 |
| `Person` | 225 | | `Country` | 18 |
| `Standard` | 223 | | `Emission` | 17 |
| `StandardIndicator` | 190 | | `Penalty` | 11 |
| `Investment` | 185 | | `Waste` | 11 |
| `Regulation` | 179 | | `ThirdPartyVerification` | 2 |
| `Facility` | 172 | | `ScienceBasedTarget` | 2 |
| `Project` | 163 | | | |

Cạnh (top 20): `reportsKPI` 6.569 · `measuredUnder` 1.338 · `worksAt` 835 · `alignsWithIndicator` 807 ·
`setsGoal` 558 · `locatedIn` 554 · `takesPartIn` 484 · `claims` 480 · `partnersWith` 350 ·
`adoptsStandard` 328 · `observedAtFacility` 302 · `subjectToRegulation` 247 · `owns` 222 ·
`investsIn` 190 · `partOf` 189 · `isIn` 165 · `producedBy` 156 · `ownsFacility` 142 · `ownedBy` 128 ·
`holdsCertification` 88.

**Quá trình phân giải** (`resolved_graph_stats.json`):

| Bước | Con số |
|---|---:|
| Đầu vào: triple | 14.500 |
| Đầu vào: node đồ thị | 13.770 (entity 6.261 + observation 7.509) |
| Sau gộp theo `identity_keys` | 11.049 |
| Thành viên issuer đã gộp | 644 (trên **5 cluster issuer**) |
| Sau gộp theo signature đã normalize | 3.254 cluster entity |
| So sánh LLM / khớp LLM | **0 / 0** (`no_llm = true` — Stage B/C đang ngủ) |
| Cluster entity cuối cùng | 3.212 |
| **Đầu ra step 05** | **10.608 node / 12.726 cạnh** (giảm 3.162 node, **-23,0%**) |
| Registry issuer | 86 alias, 52 exclusion |
| Tham số | `similarity_threshold=0.92`, `gemini-embedding-001` dim 768, `gemini-2.5-flash` |

**Trục chỉ tiêu do step 05c thêm** (`indicator_axis_stats.json`): +26 node (16 `StandardIndicator` VN,
8 `StandardIndicator(GRI)`, 1 `doc:Regulation`, 1 `doc:Standard`) và **+2.018 cạnh**: `measuredUnder`
1.300, `alignsWithIndicator` **649**, `partOf` 43, `equivalentTo` 26. `pillar_restamped` = **71**
(phần lớn là `GRI 2-*` / `GRI 3-*` từ `"GRI 2"` → `"Quản trị"`). `penalty_self_reported_zero` = **1**
(đúng một Penalty tự khai 0 bị chặn khỏi trục conduct). `unmapped_kpi_ids`: `TT96-6.6.6` × 3.

Chỉ tiêu được đo nhiều nhất (`measuredUnder`): `TT96-6.6.1` 204 · `SSCIFC-S1` 150 · `TT96-6.2.1` 115 ·
`TT96-6.6.3` 77 · `TT96-6.1.1` 68. Chỉ tiêu được **tuyên bố** gán nhiều nhất (`alignsWithIndicator`):
`GRI 2-9` 130 · `GRI 301-1` 83 · `TT96-6.7.1` 82 · `GRI 2-29` 68 · `GRI 201-1` 64.

**Canonicalize KPI** (`kpi_canonical_stats.json`): 7.324 lần xuất hiện được vá, 7.127 node KPI khác
nhau, **mapped 1.464 (20,5%)**, unmapped 5.663. Phân rã theo `kpi_id_method`: `rejected_unit` **3.094**
(KPI tài chính bị từ chối *có chủ đích*), `no_match` **2.486** (lỗ thật của từ điển alias — đây mới là
backlog), `kpi_type` 1.421, `no_title` 51, `alias_contains` 39, `unit_mismatch` 32, `alias_exact` 3,
`fuzzy_93` 1. Goal: 572 goal khác nhau, 135 đã có `target_date`, backfill được **1**, 436 không tìm thấy
năm.

### 12.4 Báo cáo chất lượng Q1–Q8 (chạy mới, label `overview_20260807`)

Trên đúng đồ thị 10.634 node / 14.744 cạnh:

| Q | Chỉ số |
|---|---|
| **Q1 Accuracy** | tên chưa NFC: **0**; tên vỡ do OCR: **3** |
| **Q2 Consistency** | **7 vi phạm** (cạnh sai schema **0**, ngày không ISO 2, `from>to` 1, chuỗi `is_current` sai 3, version bị tách do format 1, thiếu `date_uncertain` **0**, lớp T1 có thời gian trong identity **0**) |
| **Q3 Conciseness** | T1 trùng còn dư: **10**; node `Standard`: 223 |
| **Q4 Completeness** | Controversy **0** / Penalty **11** / MediaReport **127** / KPI news **298** |
| **Q5 Timeliness** | cạnh có `valid_from` **96,5%**; T2 có `valid_from` **92,1%**; T2 news có `date_uncertain` **100,0%** |
| **Q6 Provenance** | node có `source_type` **99,5%**; KPI có `source_id` parse được **68,6%** |
| **Q7 Traversability** | median degree **1,0**; node lá **67,1%**; masked-answerable **45,2%**; claim→conduct qua cạnh cấu trúc **3,3%**; T2 degree≥2 **25,2%** |
| **Q8 Independence** | conduct theo kênh: report **94**, news **342** |

Neo T2 theo lớp (Q7(e)): `Emission` 17 node **100%** · `Penalty` 11 **90,9%** · `Initiative` 429 **45,5%**
· `Project` 163 **42,9%** · `Investment` 185 **34,6%** · `KPIObservation` 6.560 **23,0%** ·
`MediaReport` 127 **19,7%** · `Waste` 11 **0%** · `ThirdPartyVerification` 2 **0%**.

**Hub cluster (A1)** — mỗi issuer là một ngôi sao riêng, đúng như thiết kế `metric/hub.py` dự đoán:

| Mã CK | Node hub | Degree |
|---|---:|---:|
| AAA | 1 | **5.389** |
| ACG | 1 | 1.976 |
| ACC | 1 | 1.029 |
| ADP | 1 | 933 |
| AGG | 1 | 856 |

**R5 (max hub-cluster degree) = 5.389** → **KHÔNG đạt** cổng ≤ 500. Đây chính là lý do `export_kgc` tồn
tại (§7.3).

**Reasoning readiness:** R1 (cạnh masked suy lại được ≤ 3 hop) **45,1%** (14.744 cạnh) · R1' (hub-free)
**26,1%** (2.222 cạnh) · R1_trainable (loại quan hệ suy biến, hiện là `reportsKPI`) **63,3%** (8.175
cạnh) · R7 (metapath dài 3 hub-free, support ≥ 50) **325 metapath**.

**Standards registry:** **5 / 386** cách viết `Standard`/`Regulation` khác nhau đã được curate. Bảy mục
đang được gợi ý bổ sung, đáng chú ý `"GRI"` (degree **54**, gợi ý *include*).

**So sánh với lần chạy trước** (`with_news_5co_20260806`, đồ thị 6.918 node / 9.797 cạnh):

| | 2026-08-06 | 2026-08-07 | Nhận xét |
|---|---|---|---|
| Kích thước | 6.918 / 9.797 | 10.634 / 14.744 | đồ thị lớn hơn ~54% |
| Q2 vi phạm | 6 | 7 | gần như không đổi (tốt: không tăng theo quy mô) |
| Q5 cạnh có `valid_from` | 95,8% | 96,5% | cải thiện nhẹ |
| Q6 KPI `source_id` parse được | 76,9% | 68,6% | **xấu đi** — corpus mới có quy ước `source_id` khác |
| Q7 claim→conduct cấu trúc | 44,6% | **3,3%** | **sụt rất mạnh** — xem §16.4 |
| R5 | 5.300 | 5.389 | vẫn không đạt |
| Standards curate | 5/259 | 5/386 | tử số không tăng, mẫu số tăng |

### 12.5 Đối soát chéo — 5 mã CK (hồ sơ ghi 2026-08-06 23:32)

| Mã CK | Tên | Claim | Cặp ứng viên | supported | contradicted | unverified | Cạnh ghi |
|---|---|---:|---:|---:|---:|---:|---:|
| AAA | CTCP Nhựa An Phát Xanh | 36 | 288 | 6 | 2 | 28 | 1 |
| ACC | CTCP Bê tông Becamex | 14 | 112 | 4 | 0 | 10 | 4 |
| ACG | CTCP Gỗ An Cường | 301 | 2.406 | 21 | 47 | 233 | 47 |
| ADP | CTCP Sơn Á Đông | 69 | 534 | 11 | 11 | 47 | 22 |
| AGG | CTCP ĐT&PT BĐS An Gia | 44 | 352 | 9 | 12 | 23 | 26 |
| **Tổng** | | **464** | **3.692** | **51** | **72** | **341** | **100** |

Tham số mọi lần chạy: `top_k=8`, `window_before=1`, `window_after=50`. Kho conduct: **342 node**
(`KPIObservation` 298, `MediaReport` 41, `Penalty` 3). `indicator_tier_pairs = 0` ở **cả 5 mã** — tầng
join qua chỉ tiêu **chưa đóng góp cặp nào** (§16.5), dù 20/36 claim của AAA và 216/301 claim của ACG
**có** cạnh indicator.

> ⚠ **Hồ sơ này ĐÃ CŨ so với code và so với đồ thị.** Ba dấu hiệu: (1) `edges_by_provider` ghi
> `"openai"` — provider đã bị gỡ hẳn ngày 2026-08-04 rồi mới thêm lại 2026-08-06, tức hồ sơ thuộc giai
> đoạn trước; (2) file ghi 2026-08-06 23:32 còn `resolved_graph.json` ghi **2026-08-07 08:07**; (3) bản
> sửa nhiễm chéo issuer + tokenizer VN + siết prompt là commit **2026-08-07**. **Phải chạy lại step 07
> (và 08, 09) trước khi trích dẫn bất kỳ con số đối soát nào** — §16.1.

### 12.6 Quy mô code

| Nhóm | File | Dòng |
|---|---:|---:|
| `src/` (`esg_kg` + `run.py`) | 44 | 11.730 |
| `test/` | 45 | 14.670 |
| `evalu/` | 13 | 3.596 |
| `crawl_data/` | 4 | 2.010 |
| `esg_news_crawler/` | 12 | 979 |
| `kpi_build/` | 8 | 870 |
| `data_processing/` | 7 | 826 |
| `gri/` | 2 | 493 |
| `api/` | 3 | 429 |
| **Tổng** | **138** | **35.603** |

Đáng chú ý: **dòng test (14.670) nhiều hơn dòng pipeline (11.730)** — hệ quả trực tiếp của quy tắc TDD ở
§14.

---

## 13. Khung đánh giá không nhãn (`evalu/`)

`evalu/` hiện thực hoá *"Khung Đánh giá Toàn diện và Định hướng Cải tiến Học thuật cho Hệ thống Graph-RAG
Phát hiện Greenwashing Không Nhãn"*. **Hoàn toàn offline**: không LLM, không Neo4j, không mạng; mọi truy
cập artifact là **chỉ đọc**, nên chạy lại bao nhiêu lần cũng không làm hỏng kết quả của một stage tốn tiền.

```bash
python evalu/run_evaluation.py                      # đầy đủ → evalu/out/
python evalu/run_evaluation.py --quick              # bỏ quét corpus ~380 MB
python evalu/run_evaluation.py --max-sentences 50000
python evalu/run_evaluation.py --make-sheet --rater-id ceo01 --panel ceo --n-claims 30
python evalu/run_evaluation.py --make-annotation --n-pairs 200 --decoys 20 --seed 42
python evalu/run_evaluation.py --ballots "evalu/out/ballots/*.json"
python evalu/export_docx.py evalu/out/evaluation_report_final.md
```

### 13.1 Bốn tầng

| Tầng | Nội dung | Module | Chạy được ngay? |
|---|---|---|---|
| §2 | **11 chỉ số nội bộ**, không cần nhãn | `metrics.py` | ✅ tự động |
| NC | **Negative control** — phép kiểm CÓ THỂ FAIL | `negative_control.py` | ✅ tự động |
| Ablation | So sánh **baseline truy hồi** (BM25 / random / token / indicator) | `retrieval_eval.py` | ✅ tự động |
| §3–§4 | **Rubric Likert 5 điểm × 4 khía cạnh × 3 hội đồng** + độ đồng thuận (Fleiss κ, Cohen κ, Krippendorff α, Gwet AC1/AC2) | `rubric.py`, `iaa.py`, `annotation.py` | ⏸ cần người chấm |

### 13.2 Mười một chỉ số §2 — kết quả và **giới hạn tự khai**

Kết quả lần chạy **2026-08-07T04:56 UTC** (`evalu/out/evaluation_report_final.md`, 58,5s):

| Mã | Chỉ số | Giá trị | Tử/Mẫu | Trạng thái |
|---|---|---:|---:|:--:|
| M1.1r | ESG Signal-to-Noise — báo cáo | 50,34% | 152.896 / 303.723 | info |
| M1.2r | Provenance Rate — báo cáo | **100,00%** | 873.756 / 873.756 | PASS |
| M1.1n | ESG Signal-to-Noise — tin tức | 62,04% | 47.913 / 77.229 | info |
| M1.2n | Provenance Rate — tin tức | **100,00%** | 174.256 / 174.256 | PASS |
| M2.1 | Temporal Metadata Completeness | 93,02% | 21.620 / 23.243 | **FAIL** |
| M2.2 | Schema Compliance Rate | 100,00% | 14.744 / 14.744 | PASS |
| M2.3 | Value Preservation Guard | 100,00% | 6.426 / 6.426 | PASS |
| M3.1 | Timeless Identity Violation Rate | 0,00% | 0 / 14 | PASS |
| M3.2 | Oversimplification & Cluster Conciseness | 0,47% | 10 / 2.135 | info |
| M4.1 | Standard Indicator Alignment Coverage | 50,53% | 718 / 1.421 | info |
| M4.2 | Zero-Report Self-Praise Exclusion | 100,00% | 1 / 1 | PASS |
| M5.1 | Evidence Asymmetry & Abstention Rate | 73,49% | 341 / 464 | info |
| M5.2 | Self-Verification Exclusion Rate | 0,00% | 0 / 99 | info |
| NC.1 | Same-Company Evidence Rate | 28,76% | 65 / 226 | **FAIL** |
| NC.2 | Same-Feed Specificity vs Chance | 28,76% | 65 / 226 | **FAIL** |

Điểm làm nên giá trị học thuật của bộ này là **mỗi chỉ số tự khai giới hạn của chính nó**. Vài giới hạn
quan trọng nhất, chép nguyên ý:

- **M1.1 là chỉ số yếu nhất trong bộ, không nên trích dẫn như kết quả độc lập.** Nó KHÔNG phải độ chính
  xác của classifier; giá trị phụ thuộc mạnh vào cách dựng từ vựng — **đổi cách dựng làm con số nhảy từ
  4% lên 50%**.
- **M1.2 gần như tất yếu đạt 100%** vì pipeline chỉ sao chép cơ học ba trường provenance. Giá trị của nó
  là **lưới chắn hồi quy**, không phải bằng chứng chất lượng.
- **M2.2 gần như tất yếu đạt 100%**: `fix_triples` **cưỡng chế** schema và đẩy cái không sửa được sang
  `unfixable_triples.json`. Đo độ tuân thủ trên đầu ra của chính validator thì không nói lên chất lượng.
  Con số đáng báo cáo kèm là **tỷ lệ bị loại** (số triple trong `unfixable_triples.json`) — **hiện chưa
  có trong báo cáo**.
- **M3.2 là CẬN DƯỚI và dễ gây yên tâm sai**: nó dùng chính `normalize_name` mà resolver dùng, nên chỉ
  thấy được thứ resolver *lẽ ra* gộp được bằng khoá của chính nó. Nó **MÙ** với thất bại thật —
  *"Công ty CP Nhựa An Phát"* vs *"An Phát Holdings"* sẽ không bị phát hiện. Mức trùng lặp thật gần như
  chắc chắn cao hơn nhiều.
- **M4.1 chỉ có ĐỘ PHỦ, không có ĐỘ CHÍNH XÁC.** Một bộ khớp *ngu hơn*, gán bừa chỉ tiêu cho mọi tuyên
  bố, sẽ đạt 100%. Vì vậy "cao hơn" **KHÔNG** đương nhiên là "tốt hơn"; muốn dùng được thì phải kiểm tay
  ~50 cạnh để có vế precision.
- **M5.1 (abstention 73,49%) là thuộc tính của DỮ LIỆU, không phải của thuật toán.** Cách sửa là **crawl
  thêm tin**, KHÔNG PHẢI nới ngưỡng phán quyết — nới ngưỡng chỉ đổi *im lặng trung thực* lấy *tiếng ồn*.
  **Đừng bao giờ trình bày như chỉ tiêu cần giảm.**
- **M5.2 = 0% có HAI cách hiểu trái ngược:** (a) không có bằng chứng tự công bố nào lọt vào — tốt; hoặc
  (b) guard là **code chết, chưa từng chạy**. Trên dữ liệu hiện tại guard chưa kích hoạt lần nào, nên chỉ
  số này **KHÔNG chứng minh** guard hoạt động.
- **M2.1 (93,02%) FAIL, và phần hụt được liệt kê chi tiết thay vì làm đẹp:** cạnh thiếu thời gian theo
  predicate — `alignsWithIndicator` 413, `partOf` 43, `worksAt` 30, `equivalentTo` 26, `reportsKPI` 2,
  còn lại 3; node thiếu `valid_from` theo lớp — `Goal` 511, `Initiative` 429, `Project` 163,
  `KPIObservation` 2, `Investment` 1. Mẫu số **lấy từ `config/schema.json`**, không phải danh sách cứng:
  schema khai `temporal_properties` cho **cả 76 edge spec** và `valid_from` cho **mọi lớp T2/T3** — nên
  phần hụt là **sai lệch thật so với hợp đồng schema**. Nếu một số lớp *cố ý* để thời gian sống trên cạnh
  (`Goal` qua `setsGoal`) thì phải **sửa schema**, không phải sửa chỉ số.

Bốn quyết định thiết kế của `evalu/` đáng biết trước khi sửa:

1. **`0/0` trả về `None`, không phải `0.0`.** "Không có bằng chứng nào để loại" và "loại sạch mọi bằng
   chứng" là hai kết luận **ngược nhau**; gộp cả hai thành 0 là báo cáo sai.
2. **Mẫu số M2.1 lấy từ schema** (đã nói ở trên).
3. **M4.2: "cạnh conduct" nghĩa là cạnh trục chỉ tiêu, không phải mọi cạnh kề.**
   `Organization -subjectToPenalty-> Penalty` chỉ ghi nhận *doanh nghiệp đã công bố*, và mọi Penalty tự
   khai 0 đều **hợp lệ** khi có cạnh này. Chỉ `measuredUnder` / `alignsWithIndicator` mới biến lời tự
   khen "bị phạt 0 lần" thành bằng chứng conduct. Phiên bản đầu đếm mọi cạnh kề và **đã báo sai một node
   mà pipeline xử lý hoàn toàn đúng**.
4. **Gwet AC2 là hệ số chính của tầng chuyên gia, không phải Kappa** — xem §13.4.

Bản đồ tầng T1/T2/T3 và danh sách trường thời gian P1 được **import từ `esg_kg.report.quality`**, không
khai lại — bản sao thứ hai sẽ trôi khỏi schema lint mà chính pipeline đang dùng.

### 13.3 Negative control — phép kiểm **có thể làm hệ thống trượt**

Đây là phần quan trọng nhất về mặt học thuật. Mọi chỉ số M1–M5 chỉ **đối chiếu hệ thống với thiết kế của
chính nó** → không cái nào có thể FAIL một cách thú vị → không cái nào chứng minh được hệ thống *hoạt
động*. Negative control thì có thể.

**Câu hỏi duy nhất:** *khi hệ thống trích một bản tin làm bằng chứng cho tuyên bố của doanh nghiệp T, bản
tin đó có thật sự nói về T không?*

**Giả thuyết không:** truy hồi **không mang tín hiệu công ty nào** — bằng chứng được rút ngẫu nhiên từ
kho conduct toàn cục. Dưới giả thuyết đó, tỷ lệ bằng chứng của T đến từ feed của T **đúng bằng** tỷ trọng
feed đó trong kho. `lift = quan sát / kỳ vọng`; `lift ≈ 1` nghĩa là **không bác bỏ được** giả thuyết
không, tức không kết luận nào phía sau được đọc như "đặc thù cho doanh nghiệp này"; `lift ≥ 2` mới coi là
có tín hiệu thật; `lift < 1` là **tệ hơn cả ngẫu nhiên**.

Cách quy thuộc: crawler ghi một file/mã CK, step 02 stamp `source_doc = "<TICKER>__<domain>__<hash>"` →
tiền tố là **feed** bài được thu dưới. Node từ BCTN dùng quy ước khác, không có tiền tố ticker → quy về
`None` chứ **không đoán**.

**Feed ≠ chủ thể**, nên audit tách **hai** thứ khác nhau:

- **cross-feed** — bài đến từ feed của công ty khác;
- **cross-feed AND unmentioned** — ...và **cũng không hề nhắc tên** doanh nghiệp đang xét trong phần text
  mà LLM thực sự nhìn thấy.

**Chỉ cái thứ hai là không thể bào chữa.** Giữ chúng tách nhau rất quan trọng: một "bản sửa" đơn giản là
bỏ hết bằng chứng cross-feed cũng sẽ **loại luôn** những bài viết chính đáng về T mà tình cờ được crawl
dưới feed của U.

**Kết quả: NC.1 = NC.2 = 28,76% (65/226) — FAIL.** Dòng cần đọc trước tiên là `cross_feed_unmentioned`,
và đặc biệt là `contradicting_evidence` trong `by_kind` — **mâu thuẫn là output chính của hệ thống, nên
một mâu thuẫn chéo công ty là một cáo buộc greenwashing sai gán cho một doanh nghiệp có thật, nêu đích
danh.** Ví dụ cụ thể ở §10.6.

Đây chính là phép đo đã **phát hiện** lỗi mà commit `7c108f9` (2026-08-07) sửa. Giá trị 28,76% là **của
lần chạy TRƯỚC bản sửa**; phải chạy lại step 07 rồi chạy lại `evalu` mới biết bản sửa hiệu quả đến đâu
(§16.1). Giới hạn tự khai: kho conduct hiện rất nhỏ (44 node / 5 mã), nên lift theo từng mã có **phương
sai lớn** — đọc con số tổng, và đọc `by_ticker` như dấu hiệu định tính chứ đừng như ước lượng điểm.

### 13.4 So sánh baseline truy hồi (`retrieval_eval.py`)

`metrics.py` đo *tính nhất quán nội bộ* — đó là **system testing, không phải evaluation**. Module này trả
lời câu mà hội đồng thật sự hỏi: **Graph-RAG truy hồi bằng chứng tốt hơn phương pháp đơn giản hơn bao
nhiêu?** Cùng hình dạng với capstone AIP491 (ESG QA cho ngân hàng VN): chạy các arm rồi báo Recall@k /
Precision@k.

Các arm: `random` (sàn — phương pháp nào không thắng nổi nó là không hoạt động) · `bm25` (từ vựng, không
đồ thị) · `token_overlap` (chính scorer tier-2 của pipeline, bỏ đồ thị) · `indicator_only` (chỉ join 2 hop
qua `StandardIndicator`) · `token_plus_indicator` (**đúng những gì hệ thống làm hôm nay**) · các arm
`*_scoped` (giới hạn trong feed tin tức của chính claimant).

Helper truy hồi được **import từ chính pipeline** (`topic_tokens`, `node_text`, `node_year`, …) chứ không
viết lại — viết lại là đo *bản giống* hệ thống thay vì đo hệ thống.

Kết quả (`evalu/out/retrieval_baselines.json`, gold = `proxy_same_company`, 360 claim):

| Arm | R@3 | P@3 | R@5 | P@5 | R@10 | P@10 |
|---|---:|---:|---:|---:|---:|---:|
| `random` | 0,174 | 0,356 | 0,298 | 0,359 | 0,620 | 0,360 |
| `bm25` | 0,235 | 0,463 | 0,340 | 0,413 | 0,522 | 0,339 |
| `token_overlap` | 0,204 | 0,417 | 0,308 | 0,384 | 0,502 | 0,326 |
| `indicator_only` | **0,000** | **0,000** | 0,000 | 0,000 | 0,000 | 0,000 |
| `token_plus_indicator` (hệ thống hôm nay) | 0,204 | 0,417 | 0,308 | 0,384 | 0,502 | 0,326 |
| `token_plus_indicator_scoped` | **0,401** | **0,812** | **0,540** | **0,700** | 0,636 | 0,436 |
| `bm25_scoped` | 0,401 | 0,812 | 0,540 | 0,700 | 0,636 | 0,436 |

Ba kết luận đọc thẳng từ bảng:

1. **`indicator_only` = 0 tuyệt đối** → tầng join qua chỉ tiêu **hiện không đóng góp gì** (khớp với
   `indicator_tier_pairs = 0` trong mọi file stats ở §12.5). Đây là lỗ hổng lớn nhất, xem §16.5.
2. **`token_plus_indicator` bằng ĐÚNG `token_overlap`** → xác nhận điều trên: toàn bộ tín hiệu hiện đến
   từ trùng token.
3. **Scoping theo feed của chính công ty là cải thiện lớn nhất** (P@3: 0,417 → **0,812**, gần gấp đôi).
   Chính vì thế mà `*_scoped` arm tồn tại: negative control phát hiện kho conduct là **toàn cục**, nên
   scoping là một thay đổi **phải đo, không được giả định**. Bản sửa 2026-08-07 (§10.2) đưa scoping này
   vào pipeline thật.
   Lưu ý trung thực: `bm25_scoped` **bằng đúng** `token_plus_indicator_scoped` — sau khi scope, phương
   pháp lexical đơn giản đã ngang hệ thống, nên **lợi ích ở đây thuộc về scoping, không thuộc về đồ thị**.
4. `gold = proxy_same_company` là **gold proxy**, không phải nhãn chuyên gia — đọc như so sánh tương đối
   giữa các arm, không phải chất lượng tuyệt đối.

### 13.5 Tầng chuyên gia: rubric, annotation mù, và độ đồng thuận

**Chưa thu thập phiếu chấm nào.** Bộ công cụ đã sẵn sàng và — quan trọng — **được chứng minh đúng trên
phiếu tổng hợp** trước khi có người chấm, thay vì debug live trong buổi annotation.

- **`rubric.py`** — rubric **4 khía cạnh × Likert 5 điểm**, **3 hội đồng** (panel), bộ sinh phiếu trống,
  pipeline đồng thuận (`consensus()` với weighted median + hàng đợi mâu thuẫn), ngưỡng đồng thuận 0,61.
  Module này giữ **instrument**, **không giữ điểm** — nhờ vậy rubric có thể được review/versioned/ship
  cùng luận văn trước khi một chuyên gia ngồi vào.
- **`annotation.py` + `ANNOTATION_PROTOCOL.md` v1.0** — annotation **mù**, cố định **trước khi nhìn kết
  quả**. Bốn điều kiện: (1) protocol cố định trước; (2) người chấm **không thấy** verdict của hệ thống;
  (3) báo cáo là *author annotation*, **không bao giờ** là *expert panel*; (4) người chấm thứ hai chấm
  cùng bộ item để **đo được độ đồng thuận**. Điều kiện (2) được **enforce bằng code**, không bằng kỷ
  luật: `build_sheet` dựng item từ **whitelist tường minh** các trường hiển thị, nên verdict không thể
  rò vào nếu sau này ai đó thêm key ở thượng nguồn (`test_sheet_is_blind` khoá lại).
  Tổng thể: **226 cặp** (99 supporting + 127 contradicting) trên 5 mã CK; mẫu **200** (88,5%) phân tầng
  theo `(mã CK × loại phán quyết)`, seed **42**, cộng **20 cặp bẫy (decoy)** không tính vào precision →
  **220 dòng** phải chấm. Với `--n-pairs 226` thì thành **census** (sai số lấy mẫu bằng 0).
  **Đo được: PRECISION của các phán quyết dương tính. KHÔNG đo được: recall** — cặp bị adjudicator gán
  `irrelevant` **không hề** được ghi vào hồ sơ, nên không có cách nào biết hệ thống bỏ sót gì. Nêu bất kỳ
  con số recall nào là **overclaim**.
- **`iaa.py`** — bốn hệ số, vì **không hệ số nào một mình sống nổi với dữ liệu này**:

  | Hệ số | Dùng cho |
  |---|---|
  | `fleiss_kappa` | arm gán nhãn câu ESG thô (E/S/G/Neutral khá cân) |
  | `cohen_kappa` | 2 rater, nominal — giữ **chủ yếu để BÁO CÁO CHO THẤY** prevalence paradox cạnh AC1 |
  | `krippendorff_alpha` | xử lý rating thiếu **native** + hỗ trợ trọng số ordinal → mặc định đúng cho lưới Likert 1..5 mà không phải chuyên gia nào cũng điền đủ |
  | `gwet_ac1` / `gwet_ac2` | **hệ số chính** của tầng cross-check |

  **Vì sao Gwet, không phải Kappa:** phần lớn claim rơi vào `unverified_insufficient_evidence`. Khi nhãn
  lệch cực đoan, chance-agreement của Kappa tiệm cận 1 và hệ số **sụp về ~0 dù observed agreement > 95%**
  (*prevalence paradox*). Gwet neo chance theo prevalence nên bền vững.
  `test_gwet_ac1_survives_prevalence_paradox` pin **đúng** tình huống đó: cùng một bộ dữ liệu cho
  **AC1 = 0,931** nhưng **Cohen κ = 0,539**.
  Với Krippendorff α, giá trị kỳ vọng trong test được **dẫn tay từ định nghĩa ma trận trùng hợp** (ghi đủ
  bước) thay vì chép hằng số từ bài báo — và test pin luôn **ma trận trung gian**, nên khi sai còn biết
  sai ở đâu.
  **Không dùng numpy** — batch annotation chỉ vài trăm dòng, và bare clone phải chạy được.

### 13.6 Giới hạn phải nêu khi trích dẫn báo cáo `evalu/`

Bốn dòng này nằm ngay trong báo cáo sinh tự động, và nên được chép nguyên vào bất kỳ slide/luận văn nào:

- Không có ground truth ⇒ **không có precision/recall/F1 về greenwashing**.
- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, **không** đo **tính đúng**.
- Tỷ lệ abstention cao phản ánh **kho tin tức độc lập còn mỏng**, không phải lỗi thuật toán.
- M1.1 (SNR) đo mức độ *neo được vào từ vựng KPI/GRI*, **không** phải độ chính xác của bộ phân loại ESG.

---

## 14. Kiểm thử & quy tắc TDD

### 14.1 Quy tắc làm việc (áp dụng cho MỌI code từ nay)

> **Viết test trước. Chạy nó. Thấy nó fail. Rồi mới viết code.**
> Không dòng production code nào được land mà không có một test fail đòi nó.

Vòng lặp cho mỗi đơn vị công việc:

1. **Red** — viết test nhỏ nhất diễn tả hành vi kế tiếp, chạy, xác nhận nó fail **vì đúng lý do mong đợi**
   (một test pass trước khi code tồn tại là test **không kiểm gì cả**).
2. **Green** — code tối thiểu để pass. Không thêm tính năng "tiện tay".
3. **Refactor** — dọn dẹp khi test còn xanh, chạy lại.

### 14.2 Quy ước

- **`assert` thuần, KHÔNG pytest** — repo không có harness pytest/linter. Một test là **một file chạy
  được** dưới `test/`, in pass/fail và **exit non-zero khi fail**.
- **Test phải offline** — không LLM, không Neo4j, không mạng. Chạy trên artifact thật đã có trên đĩa
  (`config/schema.json`, `graph_output/…`). Điều này giữ cho test **miễn phí và tái lập**;
  **tuyệt đối không verify bằng cách chạy lại một stage tốn tiền.**
- Chạy từ repo root: `python test/<name>.py`.
- **Non-vacuity là yêu cầu, không phải điều tốt-nếu-có.** Nhiều test có "arm đối chứng" chứng minh phép so
  sánh không tầm thường đúng — ví dụ khối 03/05: chuỗi stage rời phải ghi artifact **3 lần**, khối phải
  ghi **đúng 1 lần**; nếu không có arm đó thì "đúng 1 lần" có thể đúng một cách vô nghĩa.

### 14.3 Bản đồ 45 file test

**Hợp đồng schema & bất biến thời gian**

| File | Khoá gì |
|---|---|
| `test_schema_contract.py` | `config/schema.json`: P1 **cả hai chiều** (T1 identity timeless / T2 observation **GIỮ** khoá thời gian), mọi class thuộc đúng một tầng, cặp cạnh trục chỉ tiêu. Bản đồ tầng **import từ step00**, không khai lại. **Chạy sau MỌI lần sửa tay schema.** |
| `test_temporal_invariants.py` | canonicalize ngày, bất biến thời gian, parse `source_id`, DSU consolidate, khớp provenance theo tầng + bất biến thứ tự node, canonicalize `kpi_id`, sinh cạnh trục chỉ tiêu, resolve `stable_id`/`claim_id` của step 08. **Chạy sau khi sửa 03/03b/03c/05/05b/05c/08.** |
| `test_claim_id_deterministic.py` | `claim_id` **tất định** (issue #2 / C1): cùng câu nguồn → cùng id; uniqueness kiểm trên đồ thị thật (non-vacuous) |
| `test_mentions_facility_edge.py` | cạnh `MediaReport --mentionsFacility--> Facility\|Location` (C2/B2) |
| `test_indicator_axis.py` | chạy `run()` thật của 05c trên workspace tạm: Penalty tự khai 0 **KHÔNG** có cạnh conduct, ranh giới `kpi_id`-không-phải-`kpi_type`, cổng crosswalk confirmed, append-only + idempotency ở mức stage |
| `test_entities_partial_key_merge.py` | hành vi gộp khi `identity_keys` khớp một phần |

**Guard hành vi đã trả tiền (prompt & giá trị)**

| File | Khoá gì |
|---|---|
| `test_step02_language_guard.py` | hai template prompt step 02 **yêu cầu output tiếng Việt** và **không** tự mô hình hoá drift trong ví dụ của chính chúng (issue #6); red trên prompt chưa fix |
| `test_step01_step07_language_guard.py` | cùng loại guard cho step 01 và step 07 |
| `test_step03_llm_value_guard.py` | step 03 phase 2 được sửa **HÌNH DẠNG** nhưng **không** dịch/định dạng lại/bịa/xoá **GIÁ TRỊ** (`preserve_property_values`). Kiểm **cả hành vi** (guard restore/drop/permit đúng trường) **và wiring** (LLM stub cố tình phá, chạy qua `process_all_files` thật, đọc lại artifact) |

**Tương đương & hồi quy cho từng stage** (mỗi file gắn với một "slice" migration)

`test_esg_kg_equivalence.py` (core/ + toàn bộ `quality`) · `test_esg_kg_extract.py` (01) ·
`test_esg_kg_extract_triples.py` (02) · `test_esg_kg_fix_triples.py` (03) ·
`test_esg_kg_anchor_kpi.py` (03b) · `test_esg_kg_validated_block.py` (KHỐI 03) ·
`test_esg_kg_issuer.py` (04) · `test_esg_kg_entities.py` (05) · `test_esg_kg_provenance.py` (05b) ·
`test_esg_kg_resolve_block.py` (KHỐI 05) · `test_esg_kg_align_claims.py` (05d) ·
`test_esg_kg_crosscheck.py` (07) · `test_esg_kg_neo4j_load.py` (06) · `test_esg_kg_neo4j_sync.py` (08) ·
`test_esg_kg_claim_ledger.py` (09) · `test_export_kgc.py` (11).

Vài chi tiết đáng biết vì chúng dạy cách test thứ đắt tiền mà không tốn tiền:

- **`test_esg_kg_crosscheck.py`** — chạy **toàn bộ** đường retrieval + adjudication (stub) + dossier trên
  đồ thị thật, so sánh dossier/stats/edges (mask đúng một trường không tất định: `recorded_at`). Pin
  `ADJUDICATE_SYSTEM` byte-for-byte, pin **self-verification guard** (domain của chính công ty **không bao
  giờ** được có cạnh `verifiedBy`), pin **ưu tiên mâu thuẫn thắng ủng hộ**.
- **`test_esg_kg_neo4j_load.py` / `_neo4j_sync.py`** — driver Neo4j **giả** ghi lại **từng chuỗi Cypher +
  dict tham số** và **không thực thi gì**, nên so sánh được **byte-for-byte** hàng chục lời gọi thật mà
  **không cần database sống**. `neo4j_load` khó hơn: nó đi qua `session.execute_write(lambda tx: ...)` và
  **đọc lại** (`.single()`, iterate), nên session/tx giả phải trả lời **cả hai** dạng gọi và **cả** dạng
  đọc.
- **`test_esg_kg_claim_ledger.py`** — đây là stage **ĐỌC** Neo4j, nên driver "chỉ ghi lại lời gọi" sẽ cho
  arm **rỗng nghĩa**: driver giả ở đây phải **trả về DỮ LIỆU GIẢ THẬT** — một queue 4 result set theo
  **đúng thứ tự** 4 lời gọi `session.run()` — để so sánh được **cả Cypher lẫn dossier** được lắp ra.
- **`test_esg_kg_llm.py`** — không cần artifact nào, chạy trên bare clone. Đẩy throttle qua **FAKE CLOCK**
  (không bao giờ sleep thật) và **pin hình dạng REQUEST ĐÃ TRẢ TIỀN**: `temperature=0`,
  `response_format=json_object`, cách chia system/user, và `wait_if_needed` **TRƯỚC** khi create — đó là
  **hành vi**, không phải style: bỏ một cái vẫn "chạy" mà âm thầm đổi mọi verdict.
- **`test_esg_kg_llm_cache.py` / `test_esg_kg_gemini_cache.py`** — pin `ContentCache` (khoá theo nội dung,
  hit lại trong cùng process trước khi có I/O đĩa, thread-safe) và context cache của Gemini.
- **`test_esg_kg_validated_block.py` / `test_esg_kg_resolve_block.py`** — arm chính chứng minh khối ghi
  artifact **đúng một lần**, cộng **arm đối chứng** (chuỗi rời ghi 3 lần) để "đúng 1 lần" không đúng một
  cách tầm thường; cộng arm **cache**: lần chạy thứ hai gọi LLM **ZERO lần** và tái tạo **y hệt** artifact.
- **`test_export_kgc.py`** — chứng minh tính chất quan trọng cho scale: node/cạnh của một mã CK bị bucket
  **không bao giờ rò** sang mã CK khác; input-purity (không mutate tại chỗ); determinism (2 lần chạy,
  output byte-identical); mọi node/cạnh mới mang `is_synthetic` (P7); và `"HubBucket"` **không bao giờ**
  xuất hiện trong `config/schema.json`. Arm corpus thật còn assert **bytes của `resolved_graph.json` trên
  đĩa không đổi** sau khi stage chạy — chính là điểm của thiết kế export-only.

**Đo lường & audit**

`test_quality_hub_set.py` (tập hub multi-issuer) · `test_reasoning_readiness_metrics.py` (R1/R1'/R7/
R1_trainable) · `test_standards_audit.py` (một cách viết GRI chưa curate **phải** hiện ra; một chuẩn kế
toán ngoài phạm vi **không** được hiện — bộ lọc nhiễu làm mục này đọc được; exclusion đã curate **vẫn
đóng**; và `canonical_name` **không bao giờ** bị báo là unknown) · `test_gri_catalog_build.py` (quy tắc
`standard_of()`, pillar từ `PILLAR_MAP`, provenance khớp chuẩn được quy thuộc, GRI 306 bản 2016+2020 vẫn
merge).

**Hạ tầng & vận hành**

`test_console_utf8.py` (`ensure_utf8_stdout` **và WIRING** — `main()` thật sự gọi nó, **không gì** gọi lúc
import; đóng lỗ mà test tương đương không thấy vì nó không bao giờ execute `main()`) ·
`test_data_sync_scope.py` (pull **bị scope** vào đúng 3 folder, nên **không thể** ghi đè file tracked ở
repo root — đó chính là cách `.gitattributes` của Hub từng bị commit vào đây) ·
`test_esg_kg_datasync.py` (constants, scoping push/pull, status; `huggingface_hub` bị thay bằng recorder,
không chạm mạng) · `test_pipeline_table.py` (mọi nhãn `old_step` well-formed + unique, short name không
trùng, thành viên khối đều là stage đã migrate, và stage **sẽ KHÔNG BAO GIỜ** được port phải render **như
vậy** thay vì "chưa" — nếu không sẽ giữ việc chết trong hàng đợi mãi mãi).

**Test cho `evalu/`**

`test_evalu_metrics.py` (18 nhóm) · `test_evalu_iaa.py` (12 nhóm) · `test_evalu_rubric.py` (11 nhóm) ·
`test_evalu_annotation.py` · `test_evalu_negative_control.py` · `test_evalu_retrieval.py` ·
`test_evalu_export_docx.py`.
Tất cả offline. **Chỉ số được kiểm trên fixture TỔNG HỢP có đáp án tính tay, không phải trên đồ thị thật**
— một chỉ số chỉ kiểm bằng dữ liệu sống sẽ pass với **bất kỳ** thứ gì đồ thị chứa, tức là **không kiểm gì
cả**.

### 14.4 Test tốn tiền — cố ý tách riêng

`test/test_esg_kg_integration_llm.py` và `test/test_esg_kg_system_llm.py` gọi LLM **thật**, được gate sau
`RUN_LLM_INTEGRATION_TESTS=1` / `RUN_LLM_SYSTEM_TEST=1`. Chúng **tốn tiền** và **cố ý KHÔNG** thuộc bộ
miễn phí/offline.

### 14.5 Chạy bộ test nào khi sửa gì

| Sửa gì | Chạy |
|---|---|
| `config/schema.json` | `test_schema_contract.py` (+ `test_temporal_invariants.py` nếu ảnh hưởng 03/05/08) |
| bất kỳ helper trong `core/` | `test_esg_kg_equivalence.py` |
| step 03 / 03b / 03c / 05 / 05b / 05c / 08 | `test_temporal_invariants.py` + file `test_esg_kg_<stage>.py` tương ứng |
| prompt bất kỳ | file language-guard tương ứng + test tương đương của stage |
| `report/quality.py` | `test_esg_kg_equivalence.py` + `test_standards_audit.py` + `test_quality_hub_set.py` |
| `gri/` | `test_gri_catalog_build.py` |
| `evalu/` | 7 file `test_evalu_*.py` |
| `metric/hub.py` | `test_quality_hub_set.py` + `test_export_kgc.py` |

---

## 15. Vận hành

### 15.1 Cài đặt từ đầu (thành viên mới — 4 bước)

Dữ liệu sinh ra (`data/`, `graph_output/`, `kpi_output/`) **không nằm trong Git**. Nó đi qua một
Hugging Face dataset repo **riêng tư**, nên bạn **không** phải chạy lại các stage đắt: trích xuất LLM tốn
tiền, gán nhãn ESG cần GPU, và **crawl tin tức không tái lập được** (web thay đổi).

```bash
# 1. Code + dependencies
git clone <repo-url> && cd capstone_test1
pip install -r requirements.txt

# 2. Secrets — KHÔNG BAO GIỜ chia sẻ qua Git hay qua dataset repo; dùng key CỦA BẠN
cp .env.example .env      # rồi điền GEMINI_API_KEY

# 3. Dữ liệu — land đúng snapshot mà commit này được build trên đó
#    Xin maintainer invite vào org `nammovuivui-capstone` TRƯỚC (repo private; HF trả 404
#    dù bạn có token nếu chưa được invite). Token fine-grained cần scope org.
hf auth login             # hoặc đặt HF_TOKEN trong .env (read token là đủ)
python src/esg_kg/core/datasync.py pull

# 4. Neo4j — dựng LẠI ở local, KHÔNG tải về (volume DB đang sống không copy an toàn được)
docker compose up -d
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher
python src/run.py neo4j_load --clear      # vài phút, KHÔNG LLM
```

**Verify:** `python src/run.py claim_ledger` phải render được sổ nhật ký AAA.

### 15.2 Thứ tự chạy đầy đủ (từ dữ liệu thô)

```bash
# ── Kênh A: BCTN → câu ESG có nhãn ─────────────────────────────────────────────
python crawl_data/download_reports.py config/company_annual_report.xlsx
python -m data_processing.prepare_sentences \
    --input "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
#   → upload JSONL + esg_classifier.py lên Kaggle, chạy notebooks/kaggle_esg_classify.ipynb (GPU)
#   → tải kết quả về data/labeled/
python -m data_processing.extract_esg

# ── Kênh B: tin tức (phía conduct) ────────────────────────────────────────────
python -m esg_news_crawler.run --ticker AAA --limit 1     # hoặc bỏ --ticker để chạy 115 công ty
#   → phân loại ESG (cùng model, cùng notebook) → data/labeled/news_labeled/
python -m data_processing.preprocess_news

# ── Kênh C: dựng Temporal KG ──────────────────────────────────────────────────
python src/run.py --list                                  # xem toàn bộ stage
python src/run.py quality --label baseline                # ẢNH TRƯỚC (offline, miễn phí)

python src/run.py extract         -i <labeled.jsonl>                        # LLM
python src/run.py extract_triples -i <report_labeled.jsonl>                 # LLM, claim side
python src/run.py extract_triples -i <news_preprocessed.jsonl> --source news # LLM, conduct side

python src/run.py build_validated --dry-run   # KHỐI 03→03b→03c, xem trước
python src/run.py build_validated             # ghi all_validated_triples.json ĐÚNG 1 LẦN
python src/run.py fix_triples --renormalize    # (tuỳ chọn) chỉ pass P4 trên file đã có, không LLM

python src/run.py issuer                       # chạy-một-lần → rồi NGƯỜI xác nhận needs_review
python gri/build_gri_catalog.py                # chạy-một-lần → commit config/gri_catalog.json

python src/run.py build_resolved --dry-run     # KHỐI 05→05b→05c, xem trước
python src/run.py build_resolved               # ghi resolved_graph.json ĐÚNG 1 LẦN
python src/run.py align_claims --dry-run       # (tuỳ chọn, LLM) rồi --max-llm-pairs N
python src/run.py export_kgc --dry-run         # (tuỳ chọn) view SSRL

python src/run.py quality --label after-change # ẢNH SAU — so với baseline

docker compose up -d
python src/run.py neo4j_load --clear           # → Neo4j
python src/run.py claims_vs_conduct --dry-run  # LLM, xem trước, không ghi
python src/run.py claims_vs_conduct            # → graph_output/crosscheck/
python src/run.py neo4j_sync                   # → lớp advisory (KHÔNG LLM)
python src/run.py claim_ledger                 # sổ nhật ký (chỉ đọc Neo4j)
python src/run.py claim_ledger --review-queue --markdown

python api/main.py                             # UI http://localhost:8000

# ── Đánh giá ──────────────────────────────────────────────────────────────────
python evalu/run_evaluation.py                 # → evalu/out/
```

### 15.3 Đồng bộ dữ liệu qua Hugging Face — chi tiết dễ mất dữ liệu

```bash
python src/esg_kg/core/datasync.py status      # pinned vs local, cảnh báo drift
python src/esg_kg/core/datasync.py pull        # lấy đúng revision trong data_version.json
python src/esg_kg/core/datasync.py push        # sau khi rebuild: upload + re-pin (cần `write` trong org)
git add data_version.json && git commit -m "data: refresh snapshot" && git push
```

**Vì sao không dùng Git:** đây là ~19 GB artifact sinh ra — Git xử lý rất tệ (binary delta phình history
mãi mãi, GitHub hard-block file > 100 MB). Chúng bị git-ignore; dataset repo mang chúng.

**Vì sao không dùng "một folder Drive chung":** thất bại thật sự gây đau là **lệch phiên bản dữ liệu ↔
code** — đồng đội pull code ở commit X trong khi folder chung đang ở state Y, và những lỗi sau đó cực khó
hiểu. Vì thế revision đã push được **PIN vào `data_version.json`**, và file này **được track trong Git**.
Checkout một commit cũ → `pull` → khôi phục đúng dữ liệu đi cùng nó. Đây cũng là điều làm cho so sánh
*baseline vs sau-Phase-0* **tái lập được**.

**Bốn cạm bẫy phải biết:**

1. **Ai push thì phải commit `data_version.json` NGAY TRONG CÙNG LẦN LÀM.** Một snapshot đã push mà pin
   chưa commit là **vô hình**: cả nhóm tiếp tục pull revision cũ, **không có lỗi nào cả**.
2. **`git pull` TRƯỚC khi push**, để xung đột pin nổi lên ở Git chứ không phải âm thầm ghi đè snapshot của
   người khác.
3. **`pull` và `push` đều bị scope bằng `ALLOW_PATTERNS`** vào đúng 3 folder. Lý do: `local_dir` **là repo
   CODE**, nên một `pull` không scope sẽ ghi **file root của dataset** lên file đang được track — đó chính
   là cách `.gitattributes` của Hub từng bị commit vào repo này (và vì thế repo này giờ route
   `*.png/jpg/zip/parquet` qua Git LFS). Khoá bởi `test_data_sync_scope.py`.
4. **`neo4j_data/` KHÔNG BAO GIỜ được đồng bộ** — dựng lại bằng `neo4j_load`.

**Cố ý KHÔNG phân phối:** `.env` (secrets — mỗi người dùng key riêng để quota/billing quy được về từng
người) và `neo4j_data/`.

### 15.4 Chi phí & những chỗ tiêu tiền

| Stage | Có phí? | Cách kiểm soát |
|---|---|---|
| `extract` (01) | ✅ LLM | chỉ gửi trang có ≥ 1 câu `esg=true`; idempotent (file tồn tại → skip); Gemini context cache |
| `extract_triples` (02) | ✅ LLM | `--doc`, `--limit-docs`, `--dry-run`; context cache (Gemini) |
| `fix_triples` (03) phase 2 | ✅ LLM | chỉ triple invalid; **cache content-addressed** → chạy lại **miễn phí** |
| `entities` (05) Stage B/C | ✅ (đang ngủ) | mặc định `--no-llm`; `--max-llm-pairs`; Stage C có cache |
| `align_claims` (05d) | ✅ LLM | **tuỳ chọn**; `--max-llm-pairs`, `--dry-run` |
| `claims_vs_conduct` (07) | ✅ LLM **BẮT BUỘC** | `--max-llm-pairs`, `--dry-run`; cache content-addressed |
| 00, 03b, 03c, 04, 05b, 05c, 06, 08, 09, 11, `evalu/` | ❌ miễn phí | offline hoặc chỉ DB |

**Nguyên tắc số một về chi phí:** *không bao giờ chạy lại một stage đắt để lấy dữ liệu mà đồng đội đã
push.* `pull` nó.

**Nguyên tắc số hai:** không bao giờ verify bằng cách chạy lại một stage có phí — dùng `--dry-run` /
`--no-llm` / bộ test offline.

### 15.5 Môi trường Windows — những chỗ vướng thực tế

- Host là **Windows / PowerShell**. Giải nén `.rar`/`.7z` trong `crawl_data/extract_archives.py` **gọi
  binary ngoài** (UnRAR.exe / 7z.exe) → phải cài **WinRAR + 7-Zip** riêng.
- Console Windows mặc định code page ANSI (cp1252 trên host này), nên các ký tự `→`, `≥` và dấu tiếng Việt
  làm `print` crash. `core/console.py` giải quyết, và **cố ý swallow lỗi**: file artifact luôn được ghi
  với `encoding="utf-8"` nên **chưa bao giờ** có nguy cơ — chỉ có echo terminal là hỏng, và crash một
  report **đã ghi xong lên đĩa** thì thuần là nhiễu.
- `data/` hiện ~19 GB — cân nhắc dung lượng ổ trước khi `pull`.

---

## 16. Giới hạn đã biết & nợ kỹ thuật

> **Đọc mục này trước khi trích dẫn bất kỳ kết quả nào.** Đây là bản kê trung thực hiện trạng ngày
> 2026-08-07, xếp theo mức ảnh hưởng.

### 16.1 ⚠ Hồ sơ đối soát trên đĩa đã CŨ so với code và so với đồ thị

Ba bằng chứng: (a) `*_crosscheck_stats.json` ghi `edges_by_provider: {"openai": …}` — provider bị gỡ hẳn
2026-08-04, thêm lại 2026-08-06, nên hồ sơ thuộc giai đoạn **trước** đó; (b) hồ sơ ghi **2026-08-06
23:32**, còn `resolved_graph.json` ghi **2026-08-07 08:07**; (c) bản sửa **nhiễm chéo issuer + tokenizer
VN + siết `ADJUDICATE_SYSTEM`** là commit `7c108f9` ngày **2026-08-07**.

**Hệ quả:** mọi con số ở §12.5, ví dụ ở §10.6, và **NC.1/NC.2 = 28,76%** ở §13.3 đều thuộc **trước bản
sửa**. Việc cần làm, theo đúng thứ tự:

```bash
python src/run.py claims_vs_conduct --ticker AAA     # ... rồi ACC, ACG, ADP, AGG   (CÓ PHÍ)
python src/run.py neo4j_sync
python src/run.py claim_ledger
python evalu/run_evaluation.py                        # đo lại NC.1/NC.2 sau bản sửa
```

Chưa chạy lại thì **không được** dùng những con số đó để nói về hệ thống hiện tại — theo cả hai chiều
(chúng có thể tệ hơn *hoặc* tốt hơn thực tế).

#### Cập nhật 2026-08-07: đã thử chạy lại, CHƯA XONG — bốn phát hiện chặn

**(a) Bản sửa `7c108f9` không nằm trên nhánh làm việc.** Nó chỉ có trên `main`/`origin/main`, không phải
`wip/gri-parser-and-eval` (nơi có `evalu/`). Không nhánh nào một mình chạy được cả 5 bước. Đã **cherry-pick**
sang nhánh này: `core/llm_cache.py`, `crosscheck/claims_vs_conduct.py`, `load/neo4j_sync.py`,
`api/evidence_service.py` + 2 file test; `core/llm.py` được **bổ sung** (không thay thế)
`DEFAULT_MODEL` / `DEEPSEEK_DEFAULT_MODEL` / `OPENAI_DEFAULT_MODEL` / `build_gemini_client` /
`_GeminiProvider` / `_DeepSeekProvider`, giữ nguyên `_OpenAIProvider` (bản SDK có `base_url`) và
`_OpenAIEmbeddingProvider` / `openai_json_call` mà các stage khác của nhánh vẫn import — hai nhánh đã
refactor `_OpenAIProvider` theo hai hướng **không tương thích**, nên nuốt trọn `llm.py` của `main` sẽ làm
hỏng `entities` và `kpi/extract`. Test: 27 + 9 + 13 nhóm đều PASS.

**(b) Cache adjudication KHÔNG băm `ADJUDICATE_SYSTEM`.** `ContentCache.key = sha256(json.dumps(parts))`
với `parts = (claim_text, evidence_text, evidence_meta)`. Vì `7c108f9` có **siết** prompt đó, mọi entry
ghi trước bản sửa sẽ được phục vụ dưới prompt mới → verdict cũ. Các file `adjudication_cache*.json` cũ
(ghi 2026-08-06 23:32) **đã bị xoá** trước khi chạy. Ai chạy lại sau này phải làm đúng vậy, hoặc `--no-cache`.

**(c) Không còn provider nào chạy nổi 401 cặp.** `OPENAI_API_KEY` trong `.env` **rỗng**. Gemini thì
**không còn 403** như mục này từng ghi — mà là **404**: `gemini-2.5-flash*` đã bị gỡ khỏi key này;
`gemini-flash-latest` (→ `gemini-3.6-flash`) gọi được, nhưng quota free tier chỉ **5 request/phút** và đã
cạn. Hạ xuống 4 RPM / 1 worker vẫn 429 ngay. Kết quả: chỉ **ACC hoàn tất thật** (2/2 lời gọi OK); AAA 7/23;
ACG, ADP, AGG **0** lời gọi thành công. Hồ sơ hỏng đã **không** để lại trên đĩa — đã khôi phục bản pre-fix,
giữ lại cache 23 verdict hợp lệ để lần chạy sau rẻ hơn. **Cần một OPENAI_API_KEY thật (hoặc Gemini có
billing) mới chạy tiếp được.**

**(d) Đã đo trước khi trả tiền — bản sửa có tác dụng rất lớn.** Chạy stage thật với provider giả (miễn phí,
kỹ thuật của `test_esg_kg_crosscheck.py`), ghi ra thư mục tạm:

| | claims | pool trước | pool sau | cặp trước | cặp sau | |
|---|---|---|---|---|---|---|
| AAA | 36 | 342 | 68 | 288 | 23 | −92% |
| ACC | 14 | 342 | 52 | 112 | 2 | −98% |
| ACG | 301 | 342 | 190 | 2.406 | 359 | −85% |
| ADP | 69 | 342 | 3 | 534 | 9 | −98% |
| AGG | 44 | 342 | 29 | 352 | 8 | −98% |
| **TỔNG** | | | | **3.692** | **401** | **−89%** |

`conduct_pool = 342` cho **cả 5 mã** trước bản sửa là bằng chứng trực tiếp của lỗi nhiễm chéo: không hề có
scoping theo issuer, mọi công ty đối soát với **cùng một rổ tin**. Sau bản sửa mỗi mã có rổ riêng.

Và trên ACC — mã duy nhất chạy trọn — **cả 4 verdict `appears_supported` đều biến mất**, thành
`unverified_insufficient_evidence` (14/14 claim khớp `claim_id`, 4 claim đổi verdict). Tức bốn "bằng chứng
ủng hộ" đó được dựng trên tin của công ty khác. Đây đúng là thứ NC.1/NC.2 = 28,76% đang bắt, và là lý do
**không được** trích 28,76% như số liệu của hệ thống hiện tại.

#### (e) ĐÃ CHẠY XONG — NC.1/NC.2 sau bản sửa: 28,76% → 100%, nhưng phải đọc kèm mẫu số

Cả 5 mã đã chạy lại step 07 → `neo4j_sync` → `claim_ledger` → đo lại negative control:

| | TRƯỚC (gpt-4o-mini, chưa sửa) | SAU (glm-5.2, đã sửa) |
|---|---|---|
| **NC.1** Same-Company Evidence Rate | **28,76%** (65/226) — FAIL | **100,00%** (21/21) — **PASS** |
| `cross_feed` | 161 | **0** |
| `cross_feed_unmentioned` | 161 | **0** |
| **NC.2** Same-Feed Specificity | 28,76% — FAIL | **100,00%** — **PASS** |
| kỳ vọng nếu bốc ngẫu nhiên | 28,88% | 39,83% |
| **lift** (quan sát / kỳ vọng) | **0,996** | **2,511** |

`by_kind` sau bản sửa: `supporting_evidence` 17/17 same-feed, `contradicting_evidence` 4/4 same-feed —
**không còn một cáo buộc mâu thuẫn chéo công ty nào**, so với 100 cái trước đó.

**Nhưng đây KHÔNG phải một chiến thắng sạch, và không được trích 100% mà bỏ phần này:**

1. **Mẫu số sụp từ 226 xuống 21 trích dẫn.** Hệ thống hết trích nhầm chủ yếu vì nó gần như **không còn
   trích gì**. 100% trên 21 trích dẫn là một cơ sở mỏng; chính `limitation` của NC.2 đã cảnh báo kho
   conduct 44 node / 5 mã cho phương sai rất lớn, nên đọc `lift = 2,511` như dấu hiệu định tính, không
   phải ước lượng điểm.
2. **Đổi luôn adjudicator** (gpt-4o-mini → glm-5.2 qua endpoint OpenAI-compatible), nên so sánh này
   **hai biến cùng đổi**, không cô lập được bản sửa. NC.1/NC.2 đo nguồn gốc bằng chứng (thuộc tầng
   retrieval, nơi bản sửa tác động) nên ít nhạy với model hơn phân bố verdict — nhưng vẫn phải ghi.
3. ~~Độ phủ chưa trọn~~ — **đã trọn:** cả 5 mã phủ **100%** số cặp ứng viên (401 cặp; ACG 359/359),
   **0 lỗi provider**. 32 cặp ACG từng hỏng ở lượt trước (endpoint hết số dư, HTTP 402) đã được xét ở
   lượt sau và **toàn bộ trả `irrelevant`**, nên không thêm trích dẫn nào — NC.1/NC.2 **không đổi** khi
   bổ sung chúng. Đây là một dấu hiệu tốt về độ ổn định: kết luận không phụ thuộc vào 8% cặp còn thiếu.
4. Nguyên nhân sâu xa của mẫu số 21 chính là **§16.5**: rổ conduct phía news gần như toàn KPI tài chính,
   nên phần lớn verdict là `irrelevant` và rất ít cạnh liên kết được ghi (21 advisory edge trên 464 claim).

**Kết luận trung thực:** bản sửa đã loại sạch nhiễm chéo — negative control chuyển từ FAIL sang PASS và
đó là kết quả thật. Nhưng hệ thống hiện **nói rất ít**, và cái ít đó đúng; nó chưa chứng minh được là
**nói nhiều và vẫn đúng**. Muốn khẳng định điều sau thì phải sửa §16.5 trước (kênh tin hành vi ESG),
rồi đo lại trên mẫu số lớn hơn.

Số liệu chi tiết: `evalu/out/evaluation_report_nc_postfix.json`.

### 16.2 Corpus phân loại (197 DN) >> corpus đã dựng đồ thị (5 mã CK)

Chênh lệch chủ ý vì chi phí LLM, nhưng phải luôn nói rõ. Đồ thị hiện chỉ có **AAA, ACC, ACG, ADP, AGG**.
Mọi phát biểu kiểu "hệ thống bao phủ 197 doanh nghiệp" là **sai** — bao phủ 197 DN ở **tầng phân loại
câu**, và 5 mã ở **tầng đồ thị + đối soát**.

### 16.3 `anchor_kpi` (03b) hiện ra 0 anchor

`anchor_patch_stats.json`: cả **6.661** `KPIObservation` đều `kpi_without_resolvable_sentence` — `source_id`
không resolve được về corpus JSONL (quy ước tên file của corpus toàn ngành khác với lúc stage này được
viết). Gazetteer vẫn dựng 151 tên facility. Nguyên tắc **P3** vì thế đang chỉ được thực thi qua prompt
step 02, không có lưới vá offline. Liên quan: **Q6 "KPI có `source_id` parse được" tụt từ 76,9% → 68,6%**.

### 16.4 Q7 "claim→conduct qua cạnh cấu trúc" sụt 44,6% → 3,3%

Đây là **sụt lớn nhất** giữa hai lần chạy `quality` (2026-08-06 → 2026-08-07). Đồ thị lớn hơn 54% nhưng
đường đi cấu trúc từ claim tới conduct gần như biến mất. Chưa chẩn đoán xong; nghi vấn hàng đầu là cùng
gốc với §16.3 và §16.5 (KPI news không neo được vào trục chỉ tiêu → không còn đường 2-hop). **Cần điều tra
trước khi dựng đồ thị cho công ty thứ 6.**

### 16.5 Tầng join qua chỉ tiêu đang cho 0 cặp

Hai nguồn độc lập cùng chỉ ra một điều: `indicator_tier_pairs = 0` ở **cả 5** file stats (§12.5), và arm
`indicator_only` trong ablation truy hồi cho **0,000 ở mọi k** (§13.4). Nghĩa là toàn bộ tín hiệu retrieval
hiện đến từ **trùng token**, còn `token_plus_indicator` bằng **đúng** `token_overlap`.

Đây là lỗ hổng đáng sửa nhất, vì tầng chỉ tiêu chính là phần *"đồ thị"* trong Graph-RAG. Giả thuyết: KPI
phía **news** không nhận được `kpi_id` (nên không có `measuredUnder`), trong khi claim thì **có** cạnh
`alignsWithIndicator` (216/301 với ACG) — hai đầu của phép join không gặp nhau. Kiểm bằng cách đếm
`measuredUnder` trên node có `source_type=news`.

#### Đã đo — 2026-08-07. Giả thuyết ĐÚNG, nhưng nguyên nhân gốc sâu hơn một lỗi nối dây

| Đo trên `graph_output/resolved/resolved_graph.json` | Kết quả |
|---|---|
| `measuredUnder` xuất phát từ node `source_type=news` | **0** trên `KPIObservation` (chỉ 3 trên `Penalty`) |
| Phân rã toàn bộ 1.338 cạnh `measuredUnder` | 1.311 `KPIObservation`/report · 17 `Emission`/report · 7 `Penalty`/report · 3 `Penalty`/news |
| `KPIObservation` phía news mang `kpi_id` | **0 / 298** |
| `kpi_id_method` của đúng 298 node đó | `rejected_unit` 179 + `no_match` 119 (không node nào match) |

Phía conduct **không có đầu vào nào** để join, vì KPI trích từ tin tức gần như toàn là **chỉ số tài
chính**: `revenue` 22, `net profit` 14, `ownership percentage` 11, `stock price` 11, `total assets` 7,
`vốn điều lệ` 7, `inventory` 6, `gross profit margin` 4, `short-term debt` 3… — mà `canonicalize` (03c)
**cố ý loại** KPI tài chính VND (nguyên tắc "precision over recall" của stage đó, xem §7).

**Vậy đây không phải lỗi nối dây ở tầng chỉ tiêu, mà là lỗi ở tầng DỮ LIỆU:** kênh tin tức đang trả về
tin **tài chính / chứng khoán**, không phải tin **hành vi ESG**. Không có `measuredUnder` phía news thì
tầng chỉ tiêu không thể sinh cặp nào, và `token_plus_indicator` mãi bằng `token_overlap`.

**KHÔNG sửa nhanh được — ghi nhận là hạn chế đã biết.** Ba đường đi, không đường nào rẻ:

1. Sửa truy vấn crawl để lấy tin **hành vi** ESG (môi trường, lao động, xử phạt) thay vì tin tài chính,
   rồi crawl lại → phân loại lại → trích xuất lại. **CÓ PHÍ**, và là đường duy nhất thực sự sửa được.
2. Mở rộng từ vựng chỉ tiêu sang KPI tài chính — **bác bỏ**: phá đúng cái guarantee precision của 03c và
   sinh join sai (gán `revenue` vào một chỉ tiêu ESG là bịa quan hệ).
3. Chấp nhận, và trình bày trung thực rằng phần retrieval hiện chạy **hoàn toàn trên trùng token**.

Vẫn đúng sau bản sửa `7c108f9`: log step 07 in `0 indicator←conduct(news) link(s)` và
`indicator_tier_pairs = 0` trong mọi file stats sinh ra sau bản sửa. Bản sửa nhiễm chéo **không** chạm
tới lỗ hổng này — hai vấn đề độc lập.

### 16.6 R5 không đạt: hub của issuer

**R5 = 5.389** so với cổng ≤ 500. Thêm công ty **không** giải quyết (mỗi công ty thêm ngôi sao riêng —
đúng như bảng hub 5 mã ở §12.4 cho thấy). `export_kgc` giảm được cho **view xuất ra** (9.511 → 542 trong
lần đo trên AAA) nhưng **cố ý không** sửa đồ thị thật (P6). Nếu tầng suy luận đường đi (SSRL) được xây,
đây là ràng buộc phải giải quyết ở tầng dataset.

### 16.7 M2.1 FAIL (93,02%) — nợ hợp đồng schema

Phần hụt tập trung ở cạnh trục chỉ tiêu (`alignsWithIndicator` 413, `partOf` 43, `equivalentTo` 26) và ở
`Goal` 511 / `Initiative` 429 / `Project` 163 (thời gian sống trên cạnh `setsGoal` thay vì trên node).
**Quyết định phải ra:** hoặc sinh trường thời gian cho các cạnh/node này, **hoặc sửa `schema.json`** để
nó phản ánh đúng thiết kế (`temporal_properties` không áp cho cạnh trục chỉ tiêu). Hiện tại schema nói một
điều, dữ liệu làm một điều khác — và chỉ số đang báo đúng.

### 16.8 Standards registry: 5/386 cách viết được curate

`"GRI"` với degree **54** đang chờ được include. Sửa: thêm alias vào `config/standards_registry.json` rồi
chạy lại `entities`. Đây là công việc tay, rẻ, và ảnh hưởng trực tiếp Q3 (conciseness).

### 16.9 Ghost signals & guard chưa từng kích hoạt

- `kpi_gap` / `structural_contradiction` có mặt trong hồ sơ nhưng step 07 **chưa bao giờ ghi** giá trị
  khác mặc định (phát hiện D1).
- **M5.2 = 0/99**: self-verification guard **chưa kích hoạt lần nào** trên dữ liệu hiện tại → chỉ số
  **không chứng minh** guard hoạt động (test có pin hành vi của guard, nhưng dữ liệu sống chưa gặp tình
  huống cần nó).
- Cột **"Missing"** trên UI đang **để trống** (deferred).
- `Controversy` = **0 node** trong toàn đồ thị (Q4) — lớp conduct mạnh nhất về mặt ngữ nghĩa lại chưa có
  dữ liệu.

### 16.10 Stage B/C của entity resolution đang ngủ

`llm_comparisons = 0`, `llm_matches = 0` vì `--no-llm` là chế độ chạy bình thường. Hệ quả: dedup hiện chỉ
dựa trên khoá tất định + signature đã normalize. **M3.2 = 0,47% là CẬN DƯỚI** và **mù** với thất bại thật
kiểu *"Công ty CP Nhựa An Phát"* vs *"An Phát Holdings"*. Đừng đọc 0,47% như "đồ thị gần như không trùng
lặp".

### 16.11 Tài liệu bị thiếu / đã xoá khỏi working tree

- `GRAPH_IMPROVEMENT_PLAN.md` được **nhiều docstring và test tham chiếu** (mục A1/A2/A3, B2, B4, C1, C2)
  nhưng **không tồn tại trong repo** — không tracked, không untracked. Nội dung của nó chỉ còn sống trong
  docstring của `export_kgc.py`, `metric/*.py` và các test tương ứng.
- `docs/SSRL_REASONING_LAYER.md` được tham chiếu nhưng **không có**; tầng suy luận đường đi (step 11–13)
  **chưa được xây**.
- Phần lớn `docs/*.md` **đã bị xoá khỏi working tree** nhưng **vẫn còn trong Git** — lấy lại bằng:

  ```bash
  git checkout -- docs/          # phục hồi toàn bộ
  git show HEAD:docs/SYSTEM_DESIGN.md > docs/SYSTEM_DESIGN.md   # phục hồi một file
  ```

  Danh sách file còn trong Git ở §18.2.

### 16.12 Những chỗ "đừng tự dọn dẹp"

| Thứ | Vì sao đừng |
|---|---|
| Hai hàm `node_text` (05d vs 07) | Signature khác nhau có chủ ý; gộp sẽ **âm thầm viết lại prompt đã trả tiền** |
| `DEFAULT_RATE_LIMIT` khai ở nhiều module | Cùng bằng 10 là **tình cờ**; import chung sẽ ghép hai giá trị độc lập |
| `ADJUDICATE_SYSTEM`, `BATCH_FIX_PROMPT`, 2 template step 02 | Là **hành vi đã trả tiền**; đổi chữ vẫn chạy nhưng đổi mọi kết quả. Đã bị pin byte-for-byte trong test |
| `get_stable_entity_id` (2 default + `strip().lower()`) | Đổi là đồ thị **âm thầm re-partition** |
| `normalize_date_string` trả `(value, parseable)` | `None` phía sau là **hợp đồng**, không phải bug được che |
| Thứ tự mảng node của `resolved_graph.json` | step 06 khoá Neo4j theo **chỉ số mảng**, hồ sơ step 07 index theo **vị trí** |
| `kpi_type` | **Không bao giờ** ghi đè — đó là nguyên văn trên trang báo cáo |
| `HubBucket` không có trong `schema.json` | Nó là artifact dựng dataset, không phải thực thể T1/T2/T3 |
| `core/console.py` swallow lỗi | Có chủ ý (§15.5) |

### 16.13 Việc đã sẵn sàng nhưng chờ điều kiện

- **Trích lại toàn bộ đồ thị (full re-extraction, DESIGN.md §5.4)** — mục tiêu dài hạn mà refactor mở
  đường. Điều kiện chặn là **`claim_id` tất định (issue #2)** — mục này **ĐÃ LAND** (§7.3, khoá bởi
  `test_claim_id_deterministic.py`), nên rào cản chính đã được giải quyết; vẫn cần lên kế hoạch vì nó
  invalidate hồ sơ đã trả tiền.
- **Tầng chuyên gia của `evalu/`** — instrument sẵn sàng, chưa thu phiếu nào. Chỉ cần người chấm.
- **Annotation mù** — protocol v1.0 cố định, script sinh phiếu sẵn; chạy được ngay khi hồ sơ được refresh
  (§16.1). Lưu ý phải sinh phiếu **từ hồ sơ mới**, không phải hồ sơ cũ.

---

## 17. Mở rộng: thêm một doanh nghiệp / scale toàn ngành

### 17.1 Checklist thêm một mã CK vào đồ thị

```bash
TICKER=XYZ
# 1. BCTN — phải đã có trong data/raw/annual_report/ (hoặc tải qua download_reports.py)
# 2. Câu → nhãn ESG: đã nằm trong corpus toàn ngành nếu mã này thuộc 197 DN đã phân loại.
#    Kiểm: grep mã CK trong data/labeled/classified/all_sentences_classified.jsonl
# 3. Tin tức (phía conduct) — BẮT BUỘC, không có thì mọi claim sẽ là unverified
python -m esg_news_crawler.run --ticker $TICKER
#    → phân loại ESG (Kaggle) → data/labeled/news_labeled/
python -m data_processing.preprocess_news

# 4. Trích xuất (CÓ PHÍ)
python src/run.py extract         --doc $TICKER
python src/run.py extract_triples --doc $TICKER --source report
python src/run.py extract_triples -i <news_preprocessed cho $TICKER> --source news

# 5. Validate + phân giải
python src/run.py build_validated
python src/run.py issuer                 # thêm alias/exclusion cho mã mới → NGƯỜI xác nhận needs_review
python src/run.py build_resolved

# 6. Ảnh chất lượng TRƯỚC/SAU
python src/run.py quality --label with_${TICKER}

# 7. Nạp + đối soát + trình bày
python src/run.py neo4j_load --clear
python src/run.py claims_vs_conduct --ticker $TICKER      # CÓ PHÍ
python src/run.py neo4j_sync
python src/run.py claim_ledger

# 8. Push snapshot + PIN (cùng một lần làm!)
python src/esg_kg/core/datasync.py push
git add data_version.json && git commit -m "data: add $TICKER" && git push
```

**Bước 3 là bước dễ bị bỏ nhất và cũng là bước quyết định.** Không có tin tức thì đồ thị chỉ có phía
claim, mọi tuyên bố sẽ là `unverified_insufficient_evidence`, và hệ thống **không nói gì** về công ty đó
— đúng nhưng vô dụng.

**Bước 6 bắt buộc:** so `quality` trước/sau. Nếu Q2 (vi phạm) hoặc Q3 (trùng lặp) tăng bất thường, hoặc
`issuer_registry` sinh nhiều `needs_review` chưa xác nhận, thì phải xử lý **trước khi** chạy stage tốn tiền.

### 17.2 Điều gì scale được, điều gì không

| Scale tốt | Ghi chú |
|---|---|
| Phân loại ESG | GPU Kaggle, đã chạy 197 DN / 873k câu |
| Crawl tin tức | Có cache đĩa + rate-limit; resume rẻ; nhưng **không tái lập** (web đổi) |
| Stage offline (00, 03b, 03c, 05b, 05c, 06, 08, 09, 11) | Chi phí chỉ là CPU |
| `metric/hub.py`, `export_kgc` | **Đã** thiết kế cho multi-issuer từ đầu (theo registry, không phải argmax degree) |

| Scale kém / cần chú ý | Ghi chú |
|---|---|
| Trích xuất LLM (01, 02) | Chi phí **tuyến tính theo số trang** — đây là ràng buộc thật |
| Đối soát (07) | Chi phí ~ số claim × top_k; ACG một mình đã 2.406 cặp |
| R5 / hub | **Xấu đi** khi thêm công ty (mỗi công ty thêm một ngôi sao) — không tự khỏi |
| Q7 traversability | median degree đã 1,0 và 67% node là lá; thêm công ty **không** tự làm đồ thị liên thông hơn |
| Standards registry | 5/386 cách viết được curate — mẫu số **tăng theo** số công ty |

### 17.3 Ba việc nên làm trước khi mở rộng thêm

1. **Chạy lại step 07/08/09 + `evalu`** để có baseline **sau** bản sửa nhiễm chéo (§16.1). Không có baseline
   đúng thì không biết việc mở rộng làm tốt lên hay xấu đi.
2. **Chẩn đoán §16.5 (tầng chỉ tiêu = 0 cặp) và §16.4 (Q7 sụt)** — cả hai đều **không** tự khỏi khi thêm
   dữ liệu, và cả hai đều làm suy giảm chính phần "đồ thị" của Graph-RAG.
3. **Sửa §16.3 (`anchor_kpi` = 0)** hoặc quyết định chính thức rằng P3 chỉ được thực thi qua prompt
   step 02 — rồi ghi quyết định đó vào tài liệu.

---

## 18. Thuật ngữ & bản đồ tài liệu

### 18.1 Thuật ngữ

| Thuật ngữ | Nghĩa trong dự án này |
|---|---|
| **Claim / Conduct** | Phía *tuyên bố* (BCTN) / phía *hành vi* (tin tức độc lập) |
| **Dossier (hồ sơ)** | Output của step 07: bằng chứng + rationale + caveats + assessment tư vấn cho một claim |
| **Advisory** | Ý kiến do LLM hỗ trợ, **luôn gắn cờ**, không phải fact và không phải phán quyết |
| **Issuer** | Doanh nghiệp phát hành báo cáo — cluster **đóng băng** trong entity resolution |
| **T1 / T2 / T3** | Tầng thực thể vô thời gian / quan sát-sự kiện / tuyên bố-mục tiêu |
| **BLOCK (KHỐI)** | Nhiều stage gộp thành một đơn vị ghi artifact **đúng một lần** (§7.2) |
| **Trục chỉ tiêu (indicator axis)** | Cấu trúc `StandardIndicator` nối claim ↔ KPI theo TT96/GRI |
| **TT96** | Thông tư 96/2020/TT-BTC |
| **GRI** | Global Reporting Initiative |
| **SSC-IFC** | Hướng dẫn công bố thông tin môi trường & xã hội của UBCKNN – IFC |
| **Q1–Q8** | 8 thuộc tính chất lượng đồ thị do `quality` (step 00) đo |
| **P1–P8** | 8 nguyên tắc thiết kế temporal KG (§2.4) |
| **R1 / R1' / R5 / R7** | Chỉ số reasoning-readiness (§12.4) |
| **M1.1–M5.2 / NC.1–NC.2** | 11 chỉ số nội bộ + 2 negative control của `evalu/` (§13) |
| **Negative control** | Phép kiểm **có thể FAIL** — bằng chứng có thật sự nói về công ty đang xét? (§13.3) |
| **Prevalence paradox** | Kappa sụp về ~0 khi nhãn lệch cực đoan dù observed agreement > 95% → dùng Gwet AC1/AC2 |
| **`stable_id`** | Id thực thể tính từ `identity_keys` — khoá của mọi dedup và mọi match provenance tầng 3 |
| **`source_id`** | `<source_pdf>_<page>_<sentence_index>` — khoá truy nguyên về câu gốc |
| **Ghost signal** | Trường signal có trong hồ sơ nhưng chưa bao giờ được ghi giá trị (§16.9) |
| **Halo reasoning** | Kiểu lập luận sai: "cả hai đều liên quan ESG nên mâu thuẫn" thay vì khớp đúng chủ đề (§10.2) |

### 18.2 Tài liệu khác trong repo

**Đang có trên đĩa và nên đọc:**

| File | Nội dung |
|---|---|
| `CLAUDE.md` | **Chi tiết nhất về "vì sao"** — 85 KB lịch sử quyết định, cạm bẫy, bản đồ test đầy đủ |
| `README.md` | Onboarding ngắn |
| `src/PIPELINE.md` | Thứ tự chạy + lịch sử refactor (1.031 dòng): §1 toàn cảnh, §2 bảng stage & phụ thuộc symbol, §3 các KHỐI, §4 ba stage bị xoá, §5 đề xuất chưa làm, §7 closeout |
| `src/esg_kg/DESIGN.md` | Thiết kế module (990 dòng): §1 vấn đề cốt lõi, §4 chiến lược migrate, §5.1 luật "vá ở stage sớm nhất", §5.7 luật KHỐI, §6 lưới an toàn, §7 closeout |
| `src/README.md` | Quy tắc làm việc trong `src/` |
| `evalu/README.md` | Khung đánh giá — 3 tầng, 11 chỉ số, 4 quyết định thiết kế |
| `evalu/ANNOTATION_PROTOCOL.md` | Protocol annotation mù v1.0 (cố định trước khi chấm) |
| `ENTITY_RESOLUTION_PLAN.md` | Checklist kỹ thuật của step 04/05 |
| `feedback-gri-catalog.md` | Phản hồi thiết kế đã dẫn tới `gri_catalog.json` phẳng |
| `esg_news_crawler/README.md`, `kpi_build/README.md`, `gri/README.md` | Từng subsystem |
| `docs/GRAPH_LOAD_NEO4J.md` | Thiết kế step 06 |
| `docs/Khung Đánh Giá Graph-RAG.docx` | Khung đánh giá gốc mà `evalu/` hiện thực hoá |
| `diagram/` | 10 sơ đồ (drawio / mermaid / puml / html) |

**Còn trong Git nhưng đã xoá khỏi working tree** — `git checkout -- docs/` để phục hồi:

`docs/SYSTEM_DESIGN.md` (thiết kế end-to-end — **nên đọc đầu tiên** nếu phục hồi) ·
`docs/TEMPORAL_KG_DESIGN.md` (P1–P8 + Q1–Q8) · `docs/SCHEMA_EXPLAINED.md` ·
`docs/KPI_EXTRACTION_FROM_JSONL.md` · `docs/TRIPLET_EXTRACTION_FROM_JSONL.md` ·
`docs/TRIPLET_VALIDATION.md` · `docs/PROVENANCE_PATCH.md` · `docs/ENTITY_RESOLUTION.md` ·
`docs/ENTITY_RESOLUTION_IMPROVEMENT.md` · `docs/CLAIM_CONDUCT_CROSSCHECK.md` · `docs/CLAIM_LEDGER.md` ·
`docs/STANDARD_INDICATOR_AXIS.md` · `docs/ESG_EVIDENCE_VIEW.md` · `docs/REAL_DATA_INTEGRATION_GUIDE.md` ·
`docs/GRI_SCHEMA_DOCUMENTATION.md` · `docs/KPI_DEFINITIONS_CONSTRUCTION_BUILD.md` ·
`docs/PIPELINE_DIAGRAMS.md` · `docs/PIPELINE_UNIFIED.md` · `docs/LABELING_STRATEGY.md` ·
`docs/NEWS_CRAWLER_OPTIMIZATION.md` · `docs/ANNOTATION_GUIDELINE.md` ·
`docs/EVALUATION_WITHOUT_LABELS.md` · `docs/AGENT_AB_EVALUATION.md` · `docs/CROSSCHECK_EXPANSION.md` ·
`docs/BERT_NER_GRAPH_QUALITY.md` · `docs/VIETNAM_IMPROVEMENT_PLAN.md`.

**Lưu ý:** 5 file cuối là **ĐỀ XUẤT, không phải mô tả code đang có** — `CROSSCHECK_EXPANSION.md` (generator
`signals`, retrieval định tuyến qua đồ thị, và phát hiện D1 về ghost signal), `BERT_NER_GRAPH_QUALITY.md`
(embedding CPU local thay `gemini-embedding-001`, NER underthesea để neo tin tức; **bác bỏ tường minh**
việc fine-tune một classifier greenwashing vì không có nhãn), `EVALUATION_WITHOUT_LABELS.md` (§8 liệt kê
các metric **đã thử và đã chết** — đọc trước khi đề xuất metric mới), `AGENT_AB_EVALUATION.md` (McNemar
ghép cặp trên vi phạm metamorphic, luôn kèm negative-control specificity để một agent chỉ *dễ dãi hơn*
không đọc thành *tốt hơn*), `VIETNAM_IMPROVEMENT_PLAN.md`.

**Được tham chiếu nhưng KHÔNG tồn tại:** `GRAPH_IMPROVEMENT_PLAN.md`, `docs/SSRL_REASONING_LAYER.md`,
`docs/SOFTMAX_SCORING.md` (stage sinh ra nó đã bị xoá — §7.6).

### 18.3 Nếu bạn chỉ có 15 phút

1. §1.3 — **ranh giới sản phẩm** (không có điểm greenwashing).
2. §7.1 — **sơ đồ pipeline**.
3. §10 — **lõi phân tích** và bản sửa nhiễm chéo.
4. §16.1 → §16.5 — **năm giới hạn** phải biết trước khi tin bất kỳ con số nào.
5. `python src/run.py --list` + `python src/run.py quality --label thu_nghiem`.

---

> *Tài liệu này được viết bằng cách đối chiếu trực tiếp code, artifact trên đĩa và Neo4j đang chạy ngày
> 2026-08-07 (commit `c4c9f42`). Khi nâng cấp kiến trúc hoặc chạy lại một stage sinh ra số liệu ở §12,
> hãy cập nhật lại mục đó **kèm ngày đo** — một con số không có ngày trong dự án này là một con số không
> dùng được.*

