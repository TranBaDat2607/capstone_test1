# Capstone Report — Working Draft v0.1

> **Đọc trước khi dùng (tiếng Việt).**
>
> Bản nháp này bám đúng cấu trúc file mẫu `AIP491_ENGLISH__1_.pdf` (AIP491 Group 2) nhưng
> nội dung đã được viết lại cho **dự án của bạn** — Graph-RAG phát hiện greenwashing ở doanh
> nghiệp xây dựng/VLXD/BĐS Việt Nam, không phải ESG-QA cho ngân hàng.
>
> Quy ước đánh dấu trong file:
> - **[REAL]** — số liệu / mô tả đã lấy từ artifact thật trong repo, dùng được ngay.
> - **[TODO-RUN]** — chỗ cần chạy thêm một bước rồi mới điền số; đã ghi rõ lệnh chạy.
> - **[WRITE]** — chỗ cần bạn tự viết (văn phong, ý kiến, phần dành riêng cho nhóm).
>
> Xem thêm mục cuối file: **"§X. Ghi chú cho nhóm"** — phần chênh lệch quan trọng nhất
> giữa báo cáo mẫu và báo cáo của bạn (mẫu có ground truth, bạn thì **cố tình không có**).

---

## Title page

**Design and Implementation of a Temporal Knowledge-Graph System for Evidence-Grounded
Greenwashing Analysis of Vietnamese Listed Companies**

AIP491 — Group [WRITE] · FPT University · Hanoi, [WRITE]/2026

[WRITE: tên + MSSV thành viên, giảng viên hướng dẫn]

---

## Abstract

Environmental, Social and Governance (ESG) disclosure has become a central input to investment,
regulatory and reputational judgement, yet it suffers from a structural asymmetry: a company both
authors and benefits from its own sustainability narrative. This creates a persistent risk of
*greenwashing* — reporting that overstates environmental or social performance relative to actual
conduct. Existing automated ESG systems largely read the report alone, and therefore inherit
exactly the bias they should be detecting.

This thesis presents a temporal knowledge-graph (KG) system that makes greenwashing analysis
*falsifiable* by construction. The system ingests two deliberately independent evidence channels
into a single graph: the **claim side**, drawn from annual and sustainability reports published by
the company, and the **conduct side**, drawn from independent Vietnamese news media. Both channels
are extracted into one temporally-versioned schema of 28 node classes and ~50 directed edge labels,
under a design in which time lives on edges and event nodes while entity identity remains timeless,
and in which every node retains sentence-level provenance (`source_pdf`, `page`, `sentence_index`)
back to the sentence that produced it.

The system comprises five modules: (i) a **dual-standard indicator metadata layer** that normalises
both the Vietnamese regulatory vocabulary (Circular 96/2020/TT-BTC, Decision 2171/QĐ-BTC, QCVN 09,
the SSC–IFC guide) and 145 GRI disclosure codes into a machine-readable axis with a confirmed
crosswalk between them; (ii) a **claim-side report pipeline** combining layout-aware PDF
linearisation, Vietnamese-aware sentence segmentation and a fine-tuned ViDeBERTa multi-label ESG
classifier; (iii) a **conduct-side news pipeline** built on the same schema but a distinct
extraction prompt; (iv) a **temporal KG construction stage** using structured-output LLM triple
extraction followed by offline schema validation, deterministic entity resolution, provenance
stamping and indicator-axis materialisation; and (v) a **claim–conduct cross-check stage** that
retrieves conduct-side candidates for each sustainability claim and produces an LLM-adjudicated,
provenance-carrying advisory dossier.

Because no ground-truth greenwashing labels exist for Vietnamese listed companies, the system
deliberately emits **evidence and an advisory assessment, never a greenwashing score or verdict**,
and is evaluated under a label-free protocol: an eight-attribute graph quality instrument (Q1–Q8)
measured before and after each design change. On a corpus of 13 annual reports and 30 independent
news articles for a listed plastics-and-construction-materials issuer, the resulting graph contains
10,425 nodes and 14,402 edges. Two controlled ablations show that the temporal-integrity redesign
reduced schema consistency violations from 1,098 to 1, and that materialising the standard-indicator
axis raised the share of masked-answerable queries from 26.3% to 34.8% while cutting graph leaves
from 82.2% to 75.8%. Cross-checking 1,093 extracted claims against the conduct pool produced 3,461
adjudicated claim–evidence pairs, yielding 70 apparently-supported and 22 apparently-contradicted
claims, with 1,001 claims explicitly returned as *unverified — insufficient evidence* rather than
silently assumed clean.

**Keywords:** Greenwashing, ESG disclosure, Temporal Knowledge Graph, GRI Standards, Circular
96/2020/TT-BTC, Vietnamese NLP, Evidence-grounded reasoning, Large Language Models

---

## Contents / List of Figures

[Auto-generated; giữ nguyên format mẫu.]

**Figures cần vẽ** (map sang `docs/PIPELINE_DIAGRAMS.md` + `diagram/` đã có sẵn):

| # | Figure | Nguồn |
|---|---|---|
| 1 | System architecture overview (5 modules) | `docs/PIPELINE_DIAGRAMS.md` fig.1 |
| 2 | Dual-standard indicator metadata pipeline | vẽ mới |
| 3 | Example page of a GRI standard PDF + a TT96 article | screenshot |
| 4 | Layout-aware PDF linearisation & disclosure segmentation | vẽ mới |
| 5 | Claim-side report processing pipeline | `docs/PIPELINE_DIAGRAMS.md` fig.3 |
| 6 | ViDeBERTa multi-label ESG classification | vẽ mới |
| 7 | Conduct-side news ingestion pipeline | `docs/PIPELINE_DIAGRAMS.md` fig.2 |
| 8 | Temporal KG schema: T1/T2/T3 tiers | `docs/PIPELINE_DIAGRAMS.md` fig.8 |
| 9 | Triple extraction → validation → resolution chain | `docs/PIPELINE_DIAGRAMS.md` fig.5–6 |
| 10 | Entity resolution stages A–D | `docs/ENTITY_RESOLUTION.md` |
| 11 | Standard-indicator axis materialisation | `docs/STANDARD_INDICATOR_AXIS.md` |
| 12 | Claim–conduct cross-check pipeline | `docs/PIPELINE_DIAGRAMS.md` fig.7 |
| 13 | ESG Evidence View UI (3-column) | screenshot `api/main.py` |
| 14 | Q1–Q8 before/after ablation bar chart | từ §5.2, §5.3 |

---

# 1. Introduction

## 1.1 Motivation

[WRITE — sườn 6 đoạn, mỗi đoạn 1 luận điểm; giữ mật độ trích dẫn như mẫu (~1–2 ref/đoạn).]

**Đoạn 1 — ESG disclosure đã thành nguồn thông tin trung tâm.** Giống mẫu: từ practice ngoại vi →
input chính cho investor/regulator. Trích literature review về ESG disclosure.

**Đoạn 2 — Bối cảnh Việt Nam có khung pháp lý riêng, không chỉ GRI.** Đây là điểm khác biệt của
bạn so với mẫu: Thông tư 96/2020/TT-BTC bắt buộc công bố thông tin ESG trong báo cáo thường niên
của công ty niêm yết; Quyết định 2171/QĐ-BTC (Sổ tay hướng dẫn báo cáo phát thải khí nhà kính);
QCVN 09 (quy chuẩn công trình xây dựng sử dụng năng lượng hiệu quả); bộ hướng dẫn SSC–IFC. Một hệ
thống chỉ biết GRI sẽ không đọc được ngôn ngữ mà doanh nghiệp Việt Nam thực sự dùng.

**Đoạn 3 — Vì sao chọn ngành xây dựng / VLXD / bất động sản.** Ngành phát thải và tiêu thụ tài
nguyên cao, chịu QCVN 09, có KPI vật lý (năng lượng, nước, chất thải, vật liệu tái chế) nên các
tuyên bố ESG *về nguyên tắc là kiểm chứng được* — khác với ngành dịch vụ nơi phần lớn công bố là
định tính. Đây là lý do phương pháp luận, không phải lý do tiện lợi.

**Đoạn 4 — Vấn đề cốt lõi: bất đối xứng người nói / người hưởng lợi.** Doanh nghiệp vừa viết vừa
hưởng lợi từ narrative của chính mình. Mọi hệ thống chỉ đọc báo cáo (kể cả RAG/KG-RAG hiện đại)
đều thừa hưởng đúng cái thiên lệch mà lẽ ra nó phải phát hiện. Trích literature về greenwashing.

**Đoạn 5 — Vì sao RAG thuần không đủ.** RAG trả về đoạn văn liên quan; greenwashing là câu hỏi về
*mâu thuẫn giữa hai nguồn ở hai thời điểm khác nhau*. Cần: (a) kênh bằng chứng độc lập, (b) biểu
diễn có thời gian để so 2021-tuyên-bố với 2024-hành-vi, (c) provenance tới từng câu để người dùng
tự kiểm chứng. Ba yêu cầu này đẩy thẳng tới temporal knowledge graph.

**Đoạn 6 — Chốt: đề xuất của luận văn.** Một temporal KG hai kênh + tầng cross-check tạo ra hồ sơ
bằng chứng có tính tư vấn (advisory dossier), **cố tình không** sinh ra điểm số greenwashing.

## 1.2 Objectives

Viết dạng bullet như mẫu, 4 gạch:

- To design a **temporal ESG knowledge graph schema** for Vietnamese listed companies in which
  entity identity is timeless, observations and events carry validity intervals, and every node
  retains sentence-level provenance to its source document and page.
- To build a **two-channel ingestion pipeline** that populates this graph from two structurally
  independent sources — company-authored reports (the claim side) and independent Vietnamese news
  media (the conduct side) — under one schema and one identity space.
- To align the graph to a **dual-standard indicator axis** covering both the Vietnamese regulatory
  ESG vocabulary and the GRI Standards, with an explicit crosswalk between them.
- To implement and evaluate an **evidence-grounded claim–conduct cross-check** that produces
  auditable, provenance-carrying advisory assessments, and to evaluate the whole system under a
  **label-free protocol** appropriate to a domain where no ground-truth greenwashing labels exist.

## 1.3 Contributions

[Mẫu không có mục này — nhưng nên thêm, vì đây là chỗ ghi điểm với hội đồng.]

1. A temporal ESG KG schema (28 node classes / ~50 edge labels) with eight explicit design
   principles (P1–P8) and a machine-checkable invariant set; the P1 "timeless T1 identity" rule and
   the T1/T2/T3 tier partition are enforced by an offline linter rather than by convention.
2. The first (to our knowledge) ESG knowledge graph for Vietnamese listed companies that ingests an
   *independent conduct channel* alongside the report channel and keeps the two distinguishable at
   query time via a `source_type` stamp on every node and edge.
3. A dual-standard indicator axis unifying Circular 96/2020/TT-BTC and the GRI Standards through a
   confirmed-only crosswalk, materialised as graph structure (`measuredUnder`, `alignsWithIndicator`,
   `equivalentTo`) rather than as an offline lookup table.
4. A label-free evaluation instrument (Q1–Q8) that makes design changes measurable in a domain with
   no ground truth, demonstrated on two controlled before/after ablations.
5. A deliberate negative design decision, documented and defended: the system emits evidence and an
   advisory assessment but **never a greenwashing score**, because no label exists that such a score
   could be validated against.

---

# 2. Related Work

Bốn tiểu mục (mẫu chỉ có hai — bạn cần bốn vì phạm vi rộng hơn). Mỗi tiểu mục kết bằng một câu
"gap" dẫn sang phần sau.

## 2.1 Automated ESG Assessment from Sustainability Reports

[WRITE] Từ text-mining trên báo cáo GRI → thuộc tính văn bản (độ dài, tone, boilerplate, readability)
tương quan với ESG rating → khung đánh giá dựa trên LLM. Kết: các công trình này cho ra **đánh giá
mức doanh nghiệp**, người dùng không soi được claim nào đứng sau con số. *Gap: thiếu phân tích ở
mức từng tuyên bố.*

## 2.2 Greenwashing Detection

[WRITE] Đây là tiểu mục mẫu **không có** và là phần lõi của bạn. Ba hướng trong literature:
(a) *disclosure-only* — đo khoảng cách giữa lượng nói và điểm ESG bên thứ ba, hạn chế: điểm ESG
bên thứ ba tự nó cũng suy ra từ disclosure; (b) *claim-vs-outcome* — so tuyên bố với dữ liệu phát
thải/kiểm toán độc lập, hạn chế: dữ liệu này gần như không tồn tại ở thị trường Việt Nam;
(c) *linguistic-cue* — huấn luyện phân loại trên đặc trưng ngôn ngữ mơ hồ. Kết: cả ba hướng đều
vướng chung một chỗ — **không có nhãn greenwashing thật**. Đây chính là lý do luận văn định vị
output là *advisory evidence*, không phải *classification*. (Xem `docs/EVALUATION_WITHOUT_LABELS.md`
§8 để lấy danh sách các metric nhóm đã thử và loại bỏ — rất nên đưa vào đây, hội đồng đánh giá cao
việc báo cáo cả hướng đã chết.)

## 2.3 Knowledge Graphs and Temporal Representation for Corporate Disclosure

[WRITE] KG cho biểu diễn thực thể–quan hệ và multi-hop reasoning; LLM prompting-based KG
construction; temporal KG (bi-temporal model: valid time vs transaction time) và versioning. Kết:
phần lớn KG-ESG hiện có là *atemporal*, nên không diễn đạt được "công ty hứa X năm 2021 và làm
ngược lại năm 2024" — mà đó chính là hình dạng của greenwashing. *Gap: thiếu chiều thời gian.*

## 2.4 Document Parsing and Vietnamese NLP for ESG Documents

[WRITE] Parsing: từ OCR truyền thống → mô hình layout-aware/vision-language (Nougat, Marker/Surya,
olmOCR, Docling) chuyển PDF phức tạp thành Markdown giữ heading/bảng/thứ tự đọc. Vietnamese NLP:
underthesea cho tách câu/tokenize; PhoBERT/ViDeBERTa cho biểu diễn tiếng Việt; đặc thù dấu thanh
và từ ghép khiến pipeline tiếng Anh áp thẳng vào sẽ hỏng. *Gap: chưa có công trình nào ghép
layout-aware parsing + ViDeBERTa + temporal KG cho ESG tiếng Việt.*

## 2.5 Positioning of This Work

Một đoạn 5–6 câu chốt: công trình này nằm ở giao của 2.2 và 2.3, dùng 2.4 làm nền kỹ thuật, và
khác 2.1 ở chỗ đơn vị phân tích là **một tuyên bố** chứ không phải **một doanh nghiệp**.

---

# 3. Methodology

## 3.1 Overview of the System

*Figure 1.* Kiến trúc năm module. Text mở đầu viết đúng nhịp của mẫu §3.1 — một đoạn, mỗi câu giới
thiệu một module và trỏ tới tiểu mục tương ứng:

> As shown in Figure 1, the system consists of five modules. The **Indicator Metadata Module**
> (§3.2) normalises Vietnamese ESG regulation and the GRI Standards into a single machine-readable
> indicator axis. The **Claim-Side Report Processing Module** (§3.3) converts company-published PDF
> reports into ESG-labelled, page-anchored sentences. The **Conduct-Side News Module** (§3.4) builds
> a structurally independent evidence channel from Vietnamese news media using the same schema. The
> **Temporal Knowledge Graph Module** (§3.5) fuses both channels into one temporally-versioned,
> entity-resolved graph. Finally, the **Claim–Conduct Cross-Check Module** (§3.6) retrieves conduct
> evidence for each sustainability claim and produces an auditable advisory dossier.

Một đoạn nữa nêu **nguyên tắc xuyên suốt**: sentence-level traceability được bảo toàn qua *mọi*
stage, nên mọi kết luận cuối cùng đều truy ngược được về một câu ở một trang của một file PDF cụ
thể. Đây là ràng buộc thiết kế, không phải tính năng phụ.

---

## 3.2 Indicator Metadata Module

*Figure 2, 3, 4.* Mục tiêu: biến hai bộ tài liệu chuẩn không đồng nhất — văn bản pháp quy Việt Nam
và GRI Standards — thành **một trục chỉ số** máy đọc được, mà mọi KPI và mọi tuyên bố sau này neo
vào.

### 3.2.1 Source corpora

Hai corpus, xử lý song song và bằng cùng một khuôn:

**(a) Vietnamese regulatory corpus.** Circular 96/2020/TT-BTC (công bố thông tin trên thị trường
chứng khoán, phụ lục IV yêu cầu báo cáo tác động môi trường – xã hội), Decision 2171/QĐ-BTC, QCVN
09:2013/BXD, và bộ hướng dẫn ESG SSC–IFC. Pipeline `kpi_build/` (các bước `01_…`→`06_…`) tải
nguyên bản, trích **verbatim** và sinh ra `kpi_definitions_construction.json`: **35 KPI** [REAL],
mỗi KPI mang một khối `source` ghi rõ văn bản, điều/khoản và trang — nên mỗi chỉ số truy ngược được
về đúng dòng trong văn bản gốc.

**(b) GRI corpus.** 42 tài liệu GRI Standards (universal GRI 1/2/3, sector standards GRI 11–14, và
topic-specific series 200/300/400), tổng ~45 MB PDF, được version-control cùng repo để đảm bảo
tính tái lập.

### 3.2.2 Layout-aware document linearisation

> **[Đây là mục bạn muốn "làm cho ngon". Viết đúng sự thật, bằng ngôn ngữ chuẩn — xem §X.2 cuối
> file để hiểu vì sao bản này đã đủ mạnh mà không cần bịa.]**

GRI standards are published as visually complex PDFs: two-column layouts, requirement boxes,
sidebars, footnotes and disclosure tables interleaved on the same page. Classical text extractors
that iterate over positional text runs (e.g. PyMuPDF) recover characters but not *structure* — a
requirement box merges into body prose, a disclosure table collapses into an unordered token
stream, and the hierarchical relationship between a disclosure code and its guidance is lost. Since
every downstream stage keys on the disclosure unit, structural loss at this stage propagates
irrecoverably.

We therefore linearise each standard with **Marker** [cite: Paruchuri et al., `marker` / Surya],
a layout-aware document conversion pipeline that composes a layout-detection model, an
order-detection model, a table-recognition model and an OCR model over a text-first extraction
backbone, emitting Markdown that preserves heading hierarchy, list structure and table cell
boundaries. Marker belongs to the same generation of neural document-parsing systems as Nougat,
Docling and olmOCR [cite], all of which replace geometry heuristics with learned layout
understanding; we selected Marker for its explicit table reconstruction and its Markdown target,
which retains exactly the heading hierarchy our segmenter consumes. Conversion is executed through
the hosted Datalab inference endpoint with a three-worker concurrency bound and exponential backoff
on HTTP 429, and every conversion result is **content-addressed and cached to disk**
(`gri/full_gri/markdown_cache/`) so that the corpus is converted exactly once and every subsequent
build of the catalogue is byte-reproducible from the cache without re-invoking the model.

Formally, let $S$ be a GRI standard PDF of $P$ pages. Linearisation produces an ordered Markdown
token sequence

$$ M(S) \;=\; m_1 \oplus m_2 \oplus \cdots \oplus m_P $$

in which each $m_p$ retains block type (heading level, paragraph, list item, table) and reading
order, and $\oplus$ denotes order-preserving concatenation.

### 3.2.3 Disclosure segmentation

The linearised Markdown is segmented into **disclosure units** by a deterministic parser over the
heading hierarchy and the GRI disclosure-code pattern `GRI\s+\d+-\d+`. Because Markdown preserves
heading depth, segmentation is a structural operation rather than a similarity-based guess: a
disclosure boundary is a heading that introduces a disclosure code, and its unit extends to the
next same-or-higher-level heading. This yields a collection

$$ D(S) \;=\; \{ d_1, d_2, \dots, d_n \} $$

where each $d_i$ pairs one disclosure code with its requirements and guidance.

### 3.2.4 The ownership rule (a non-obvious correctness constraint)

[Mục này rất nên giữ — nó cho thấy nhóm hiểu dữ liệu, không chỉ chạy được code.]

GRI standards *re-list disclosures that belong to other standards*: the sector standards GRI 11–14
and the 2024/25 rewrites GRI 101–103 each reproduce disclosures owned by topic standards. A naive
"first file wins" attribution therefore mis-assigns ownership. We attribute each disclosure to the
standard whose `standard_id` is a prefix of the disclosure code — a rule we denote
$\mathrm{standard\_of}(\cdot)$ — never to whichever source file was read first. In our corpus this
rule is not cosmetic: applying it corrected the attribution of **80 of 136 entries** and repaired
**31 mangled titles** [REAL — `test/test_gri_catalog_build.py`, CLAUDE.md §D2]. The constraint is
pinned by a regression test rather than left to reviewer vigilance.

### 3.2.5 Catalogue schema and provenance

The module emits `config/gri_catalog.json`: **145 GRI disclosure codes** [REAL], each a record

$$ C_i = \langle \texttt{code},\ \texttt{title\_en},\ \texttt{title\_vi},\ \texttt{pillar},\
\texttt{requirement\_type},\ \texttt{units},\ \texttt{tt96\_equivalent},\ \texttt{versions},\
\texttt{provenance} \rangle $$

with pillar distribution **Governance 59 / Environmental 51 / Social 35** [REAL] and **20 codes
carrying a confirmed TT96 equivalent** [REAL]. Provenance is a `(source_pdf, page, sha256)` triple:
the SHA-256 of the source PDF is stored per record, so a claim traced back to a GRI requirement can
be verified against the exact document revision that produced it. `versions[]` records each
standard's version year, effective date and status, which is what allows the graph to state that a
2016 disclosure was superseded by a 2020 revision — a temporal fact, not a static label.

### 3.2.6 The dual-standard crosswalk

`config/standard_crosswalk.json` maps Vietnamese regulatory indicators to GRI codes. Only rows
explicitly marked *confirmed* are materialised as `equivalentTo` edges; draft rows are retained for
review but excluded from the graph unless `--trust-draft-crosswalk` is passed. This is a **precision-
over-recall** decision: a wrong equivalence silently mis-attributes evidence to the wrong regulatory
requirement, which is a worse failure than an absent edge.

---

## 3.3 Claim-Side Report Processing Module

*Figure 5, 6.* Mục tiêu: từ PDF báo cáo thường niên → tập câu đã gán nhãn ESG, mỗi câu neo được về
trang.

### 3.3.1 Corpus acquisition

`crawl_data/download_reports.py` tải báo cáo thường niên theo danh sách công ty trong
`config/company_annual_report.xlsx`. Downloader chạy đa luồng, **resumable** (dừng giữa chừng chạy
lại không tải lại file cũ) và có bước giải nén `.rar`/`.7z`. [REAL — corpus thô hiện có
**1,416 file PDF**.]

### 3.3.2 Text extraction with page anchoring

PyMuPDF được dùng ở kênh này (khác với §3.2.2), vì báo cáo thường niên Việt Nam chủ yếu là PDF
text-native và yêu cầu ở đây khác: cái ta cần là **số trang chính xác cho từng câu**, không phải
tái tạo bảng. Chi phí xử lý một corpus 1,416 file cũng khiến giải pháp neural per-page không khả
thi ở kênh này. [WRITE: nói rõ trade-off này — hội đồng sẽ hỏi "sao hai kênh dùng hai parser
khác nhau?", và câu trả lời "hai kênh có hai yêu cầu khác nhau" là câu trả lời đúng.]
Bộ trích xuất giữ nguyên dấu tiếng Việt (chuẩn hoá NFC) và gắn số trang vào từng block.

### 3.3.3 Vietnamese-aware sentence segmentation

Tách câu bằng `underthesea`. Lý do không dùng rule chấm-câu: tiếng Việt trong báo cáo tài chính dày
đặc số thập phân (`1.234,5`), viết tắt (`TNHH`, `CP`, `TP.`), và dấu chấm trong tên riêng — rule
naive tách sai chỗ. Đầu ra là `data/interim/sentences/*.jsonl`, **mỗi record một câu**, mang bộ ba
truy vết `(source_pdf, page, sentence_index)` — bộ ba này được giữ nguyên đến tận node cuối cùng
trong đồ thị.

### 3.3.4 Multi-label ESG classification with ViDeBERTa

Mỗi câu được phân loại đa nhãn vào `{E, S, G, Neutral}` bằng **ViDeBERTa-v3** fine-tune trên nhãn
ESG. Multi-label (không phải multi-class) vì một câu hoàn toàn có thể vừa mang tính môi trường vừa
mang tính quản trị — ví dụ "Hội đồng quản trị phê duyệt kế hoạch giảm phát thải" là G và E.

[TODO-RUN — cần điền: kiến trúc cụ thể, số epoch, lr, batch size, tập train/val, và **F1 per
label**. Xem `notebooks/kaggle_esg_classify.ipynb` (chạy GPU) và `data_processing/esg_classifier.py`.
Nếu chưa có bảng F1 thì đây là số liệu cần chạy sớm nhất — hội đồng chắc chắn hỏi.]

Kết quả đổ vào `data/labeled/`, rồi `data_processing.extract_esg` cắt gọn thành bản ghi
Graph-RAG-ready ở `data/outputs/esg_extracted/`.

---

## 3.4 Conduct-Side News Module

*Figure 7.* **Đây là đóng góp phân biệt luận văn này với mọi hệ thống ESG chỉ-đọc-báo-cáo.**

### 3.4.1 Design rationale

Nếu bằng chứng phản biện lại đến từ chính báo cáo, hệ thống không thể phát hiện greenwashing — nó
chỉ kiểm tra tính nhất quán nội bộ của một văn bản do bên có lợi ích viết ra. Kênh conduct vì vậy
phải **độc lập về cấu trúc**: khác tác giả, khác động cơ xuất bản, khác quy trình biên tập.

### 3.4.2 Pipeline

`esg_news_crawler.run` chạy chuỗi: companies → query generation → Google News RSS / Bing /
DuckDuckGo → fetch (cache đĩa, rate-limited) → extract nội dung bằng `trafilatura` → normalise về
**đúng schema câu của kênh báo cáo**. Việc dùng chung schema là cố ý: nó cho phép hai kênh vào cùng
một không gian định danh mà vẫn phân biệt được nhờ stamp `source_type`.

Tin tức đi qua **cùng bộ phân loại ViDeBERTa** (`data/labeled/news_labeled/`) rồi qua
`data_processing.preprocess_news` để chuẩn hoá ngày xuất bản (`publish_date_normalized`,
`publish_year`, `date_uncertain`) và loại boilerplate.

### 3.4.3 The `date_uncertain` contract

Một quyết định thiết kế nhỏ nhưng quan trọng cho tính trung thực: khi bài báo **không** nêu mốc
thời gian tường minh cho một sự kiện, hệ thống dùng ngày xuất bản làm proxy nhưng **bắt buộc** đánh
dấu `date_uncertain = true`. Cờ này đi theo bằng chứng đến tận hồ sơ cuối cùng và hiện ra thành một
caveat cho người đọc. Hệ thống không bao giờ âm thầm giả định năm.

### 3.4.4 Self-verification guard

Bài viết đến từ tên miền do chính công ty sở hữu (`aaa.com`, `anphatholdings.vn`, …) **không** được
tính là bằng chứng độc lập. Cross-check stage loại các cạnh `verifiedBy` phát sinh từ nguồn
own-domain và ghi chúng vào `flagged_non_independent_support` — nghĩa là chúng vẫn hiển thị cho
người đọc, nhưng không được tính là xác nhận. [REAL — cơ chế có thật trong
`esg_kg/crosscheck/claims_vs_conduct.py`, có test bao phủ.]

---

## 3.5 Temporal Knowledge Graph Module

*Figure 8, 9, 10, 11.* Module dài nhất — nên chia rõ 6 tiểu mục.

### 3.5.1 Schema and the T1/T2/T3 tier model

`config/schema.json` là single source of truth: **~28 node class** và **~50 edge label**. Các class
được phân hoạch vào ba tầng (mỗi class thuộc **đúng một** tầng, có test kiểm):

| Tier | Nghĩa | Ví dụ class | Thời gian sống ở đâu |
|---|---|---|---|
| **T1** | Thực thể bền vững | Organization, Facility, Person, Standard, Location | **Không** — identity phi thời gian; lịch sử ở `temporal_versions` + cạnh `supersedes` |
| **T2** | Quan sát & sự kiện | KPIObservation, Emission, Waste, Controversy, Penalty, MediaReport | Trên chính node (`valid_from`/`valid_to`) |
| **T3** | Phát ngôn & chuẩn mực | SustainabilityClaim, Goal, Initiative, StandardIndicator | Trên node + trên cạnh |

### 3.5.2 The eight design principles (P1–P8)

Tóm tắt từ `docs/TEMPORAL_KG_DESIGN.md` — nên đưa thành **một bảng** trong báo cáo, mỗi principle
một dòng: phát biểu / lý do / cách enforce. Ba cái đắt nhất về mặt thiết kế:

- **P1 — T1 identity is timeless.** Không được đưa trường thời gian (`valid_from`, `year`, `date`,
  `validity_period`) vào `identity_keys` của một class T1. Vi phạm P1 khiến cùng một công ty tách
  thành N thực thể khác nhau theo năm, phá vỡ toàn bộ khả năng suy luận liên năm. Được **lint tự
  động** bởi stage `quality`, không phải bởi quy ước.
- **P2 — In the resolved graph, time lives on edges and on T2/T3 nodes**, không nằm trên node T1.
- **P4 — Canonical ISO dates.** Mọi mốc thời gian chuẩn hoá về `YYYY[-MM[-DD]]`; một version chain
  có version mở phải có **đúng một** `is_current = true`.

### 3.5.3 LLM triple extraction

Với mỗi trang có ≥1 câu `esg=true`, hệ thống dựng prompt gồm: page text + KPI của trang đó +
`config/schema.json`, và yêu cầu LLM sinh **structured output** (typed JSON) gồm node + edge có
gắn temporal metadata. Hai prompt template khác nhau:

- `--source report` → prompt phía claim (SustainabilityClaim, Goal, Initiative, reported KPIObservation)
- `--source news` → prompt phía conduct (Controversy, MediaReport, Penalty, observed KPIObservation)

Mọi node/edge được stamp `source_type = report|news` ngay ở bước này.

**Language guard.** Cả hai template **bắt buộc output tiếng Việt** cho các trường `name`/`title`/
`description`. Lý do: nếu model dịch tên riêng sang tiếng Anh ở một trang và giữ tiếng Việt ở trang
khác, bước entity resolution sẽ tách một thực thể thành hai. Ràng buộc này được pin byte-for-byte
bằng test (`test/test_step02_language_guard.py`) vì một prompt bị viết lại "vô hại" vẫn chạy được
nhưng làm đổi mọi kết quả trích xuất.

### 3.5.4 Offline validation and repair

Ba phase, và điểm đáng viết vào báo cáo là **thứ tự** của chúng:

- **Phase 1 (offline)** — đảo chiều các cạnh bị sinh ngược, validate theo schema. Một edge label có
  thể hợp lệ với **nhiều** cặp `(source_class, target_class)`; validator chấp nhận bất kỳ cặp nào
  khớp và tự đảo chiều nếu phát hiện ngược.
- **Phase 1.5 (offline, P4)** — chuẩn hoá ngày về ISO, cảnh báo `valid_from > valid_to`, gán mặc
  định `date_uncertain` cho node T2 phía news.
- **Phase 2 (LLM)** — chỉ những triple *vẫn* không hợp lệ sau hai phase offline mới được gửi cho
  LLM sửa theo batch. Thiết kế này giữ chi phí LLM tỉ lệ với **lỗi**, không tỉ lệ với **dữ liệu**.

**Value-preservation guard.** LLM ở Phase 2 được phép sửa *hình dạng* của triple (class, predicate,
trường thời gian) nhưng **tuyệt đối không** được dịch, định dạng lại, bịa thêm hay bỏ bớt *giá trị*
của property. Ràng buộc này được cưỡng chế bằng code (`preserve_property_values`), không chỉ bằng
prompt: sau khi LLM trả về, giá trị property được khôi phục từ bản gốc. Không có guard này, một
model được hướng dẫn bằng tiếng Anh sẽ "sửa" một tên tiếng Việt và âm thầm tách một thực thể thành
hai ở stage sau.

### 3.5.5 Entity resolution

Bốn stage (chi tiết `docs/ENTITY_RESOLUTION.md` — lưu ý đây là **redesign** chứ không phải port):

- **Stage A — deterministic merge** theo `identity_keys`, cộng hai neo *đóng băng*: **issuer anchor**
  (`config/issuer_registry.json`, gom mọi biến thể tên của chính doanh nghiệp phát hành) và
  **standards anchor** (`config/standards_registry.json`, gom ≥4 cách viết của "GRI" và cả hai
  biến thể VN/EN của TT96 về **một** node chuẩn).
- **Stage B — blocking** theo chữ ký chuẩn hoá tiếng Việt + cosine trên embedding.
- **Stage C — LLM adjudication** cho các cặp mơ hồ, có budget trần.
- **Stage D — consolidate** bằng disjoint-set union, giữ nguyên lịch sử temporal.

[REAL — chế độ vận hành hiện tại là `--no-llm` (chỉ Stage A + B.1) do khoá Gemini bị chặn billing;
**cần nói rõ điều này trong báo cáo** ở phần Limitations, đừng mô tả Stage B/C như đang chạy.]

Kết quả: `resolved_graph.json` gồm **10,425 node / 14,402 edge** [REAL], phân bố class:

| Class | Nodes | | Class | Nodes |
|---|---:|---|---|---:|
| KPIObservation | 4,906 | | Location | 248 |
| SustainabilityClaim | 1,217 | | Regulation | 220 |
| Goal | 722 | | Product | 215 |
| Initiative | 495 | | Standard | 212 |
| Organization | 438 | | Person | 196 |
| Investment | 282 | | ClaimKeyword | 141 |
| Facility | 277 | | Community | 110 |
| Project | 255 | | MediaReport | 91 |

Phân bố nguồn: **report 10,100 / news 208 / chưa stamp 117** [REAL] — con số này chính là bằng
chứng định lượng cho caveat "kênh conduct mỏng" ở §6.

### 3.5.6 Provenance patch and indicator axis

- **Provenance patch** — gán `source_doc`/`source_page` (và `article_title`/`url`/`domain` cho node
  từ news) bằng cơ chế **4 tầng ưu tiên**: parse trực tiếp `source_id` → tra index `source_id` khớp
  chính xác → tính lại stable id → khớp token `_pageNN_`. Ràng buộc bất biến: **không bao giờ đổi
  thứ tự node** (Neo4j load key theo chỉ số mảng).
- **Indicator axis** — materialise ~35 node `StandardIndicator` và bốn loại cạnh: `partOf`
  (indicator → document), `measuredUnder` (KPIObservation/Emission → indicator, đọc từ `kpi_id` đã
  canonical hoá, **không đoán**), `equivalentTo` (TT96 ↔ GRI, chỉ rows confirmed), và tầng keyword
  của `alignsWithIndicator` (Claim/Goal/Initiative → indicator, cụm khớp dài nhất thắng).
  Giai đoạn này **append-only** và tự assert điều đó.

**Self-reported-zero rule.** Một `Penalty` với `amount == 0` là doanh nghiệp **tự khai** "không bị
phạt lần nào" — nó bị gắn cờ `self_reported_zero` và **không** sinh cạnh conduct. Đây đúng là hình
dạng nguy hiểm nhất trong bài toán greenwashing: một tuyên bố tự khai được đếm nhầm thành bằng chứng
độc lập.

### 3.5.7 Graph materialisation in Neo4j

Load `{nodes, edges}` thành property graph. Node key theo chỉ số mảng (đã resolve, không dedupe
lại); edge MERGE theo `_edge_key` có thành phần thời gian nên các cạnh nhiều năm không đè lên nhau;
`temporal_versions` trở thành chuỗi node version nối bằng `supersedes` với các class thuộc diện
supersedes-legal, còn lại lưu dạng JSON property.

---

## 3.6 Claim–Conduct Cross-Check Module

*Figure 12.* Lõi phân tích.

### 3.6.1 Formulation

Với mỗi `SustainabilityClaim` $c$, hệ thống lấy tập ứng viên phía conduct $E(c)$, rồi với từng cặp
$(c, e)$, LLM adjudicate ra một trong ba nhãn:

$$ y(c,e) \in \{\textsf{supports},\ \textsf{contradicts},\ \textsf{irrelevant}\} $$

kèm confidence và **rationale bằng ngôn ngữ tự nhiên**. Rationale là bắt buộc: nó là thứ người phân
tích đọc để quyết định có đồng ý với hệ thống hay không.

### 3.6.2 Retrieval

Ứng viên được lấy bằng cửa sổ thời gian **bất đối xứng**: `window_before = 1`, `window_after = 50`
[REAL]. Bất đối xứng là có chủ đích — một tuyên bố năm 2012 có thể bị phản bác bởi hành vi năm 2020,
nhưng gần như không thể bị phản bác bởi hành vi năm 2005. Tham số `top_k = 8`.

### 3.6.3 Adjudication and aggregation

LLM adjudication là **bắt buộc, không có fallback tất định** — nếu không có provider khả dụng,
stage abort ngay từ đầu thay vì âm thầm suy giảm sang heuristic. [REAL — provider hiện tại là
OpenAI `gpt-4o-mini`; hỗ trợ Gemini đã bị **gỡ bỏ hẳn** khỏi stage này vì project sau
`GEMINI_API_KEY` bị 403 vĩnh viễn. Viết đúng như vậy trong báo cáo.]

Kết quả tổng hợp thành ba nhãn khuyến nghị: `appears_supported`, `appears_contradicted`,
`unverified_insufficient_evidence`. Ưu tiên: **mâu thuẫn thắng ủng hộ** trong cùng một hồ sơ.

### 3.6.4 The advisory dossier

Mỗi claim sinh ra một bản ghi gồm: `claim_id`, `claim_text`, `year`, `assessment`,
`assessment_is_advisory: true`, danh sách `supporting_evidence` / `contradicting_evidence` (mỗi
item có `node_index`, `class`, `text`, `confidence`, `rationale`, `date_uncertain`, `independent`),
`flagged_non_independent_support`, và một danh sách `caveats`.

**Caveat luôn có mặt trong mọi hồ sơ**, không có ngoại lệ:

> `"No ground-truth greenwashing label exists; this is an advisory opinion."`

### 3.6.5 Presentation layer

Hai bề mặt: (a) **claim ledger** — bảng theo công ty, sắp signal-first (contradicted → supported →
unverified), render **chỉ từ Neo4j**; (b) **ESG Evidence View** — UI ba cột TT96/GRI, `api/main.py`
là HTTP server thuần standard-library, đọc live Neo4j; chỉ hiển thị claim có cạnh
`alignsWithIndicator`, nên cột E/S/G của mỗi thẻ đọc từ `StandardIndicator.pillar` chứ không đoán.

---

# 4. Dataset

**Table 1. Dataset components.** [REAL trừ dòng đánh dấu]

| Component | Source | Size | Role |
|---|---|---|---|
| GRI standards corpus | GRI (official) | 42 PDFs → **145 disclosure codes** | Indicator axis (international) |
| VN regulatory corpus | TT96/2020, QĐ 2171, QCVN 09, SSC–IFC | **35 KPI definitions** | Indicator axis (national) |
| Crosswalk | Hand-curated, confirmed-only | **20 GRI codes with TT96 equivalent** | Dual-standard linking |
| Raw report corpus | Company annual reports (sector-wide) | **1,416 PDFs** downloaded | Ingestion pool |
| Claim-side corpus (analysed) | AAA annual reports **2011–2025** | **13 documents** | Claim channel |
| Conduct-side corpus | Vietnamese news media | **30 articles**, 22 distinct domains | Conduct channel |
| Resolved graph | Output of §3.5 | **10,425 nodes / 14,402 edges** | Analysis substrate |
| Claim set | Extracted `SustainabilityClaim` | **1,093 claims** cross-checked | Evaluation unit |

**Table 2. Node distribution by tier and channel.** [REAL — số ở §3.5.5]

**Corpus depth vs breadth.** Kể thẳng: corpus phân tích sâu hiện tập trung vào **một issuer (AAA)**
với chuỗi thời gian 15 năm, trong khi corpus thô đã có 1,416 PDF toàn ngành. Đây là lựa chọn có ý
thức — độ sâu thời gian là điều kiện cần để phát hiện mâu thuẫn claim↔conduct liên năm, mà độ sâu
thời gian đắt hơn độ rộng. [WRITE: nếu kịp chạy thêm 2–3 issuer nữa trước bảo vệ thì cực kỳ nên,
vì nó biến "case study" thành "multi-issuer evaluation". Pipeline đã hỗ trợ multi-issuer sẵn
(`esg_kg/metric/hub.py`, `export_kgc`).]

**News domain independence.** 30 bài từ 22 domain khác nhau (vietstock.vn, tinnhanhchungkhoan.vn,
vneconomy.vn, thoibaotaichinhvietnam.vn, …), trong đó các domain do chính công ty sở hữu
(`aaa.com`, `anphatholdings.vn`, `aneco.com.vn`) được đánh dấu **non-independent** và loại khỏi
đường xác nhận theo §3.4.4. [REAL]

---

# 5. Experiments and Results

## 5.1 Evaluation Design under Absence of Ground Truth

> **Đây là mục quan trọng nhất của cả báo cáo, và là chỗ bạn khác báo cáo mẫu nhiều nhất.**
> Mẫu có 120 câu hỏi expert-annotated → báo accuracy 88.14%. Bạn **không có** nhãn greenwashing, và
> **không được** bịa ra. Cách xử lý đúng: biến "không có nhãn" từ điểm yếu thành một **đóng góp
> phương pháp luận**. Viết mục này cho tốt thì hội đồng sẽ đánh giá cao hơn là một con số accuracy
> không ai kiểm chứng được.

Viết theo ba tầng:

**(a) Vì sao không có ground truth.** Không tồn tại tập nhãn greenwashing cho doanh nghiệp niêm yết
Việt Nam. Điểm ESG bên thứ ba không dùng làm nhãn được vì phần lớn chúng cũng được suy ra từ chính
disclosure — dùng chúng làm ground truth là lập luận vòng. Vì vậy hệ thống **không sinh điểm số**,
và việc đánh giá phải chuyển sang các thuộc tính đo được mà không cần nhãn.

**(b) Instrument: Q1–Q8 graph quality attributes.** Tám thuộc tính, đo hoàn toàn offline bởi stage
`quality` (không LLM, không DB), chạy `--label <tên>` trước và sau mỗi thay đổi thiết kế:

| # | Attribute | Đo cái gì |
|---|---|---|
| Q1 | Accuracy | tên non-NFC, tên hỏng do OCR |
| Q2 | Consistency | cạnh phi pháp, ngày không ISO, `from > to`, chuỗi `is_current` hỏng, version tách do format, thiếu `date_uncertain`, class T1 có thời gian trong identity |
| Q3 | Conciseness | số node T1 trùng dư |
| Q4 | Completeness | độ phủ kênh conduct (Controversy / Penalty / MediaReport / news KPI) |
| Q5 | Timeliness | tỉ lệ cạnh & node T2 có `valid_from`; tỉ lệ node T2 news có `date_uncertain` |
| Q6 | Provenance | tỉ lệ node có `source_type`; tỉ lệ KPI có `source_id` parse được |
| Q7 | Traversability | median degree, tỉ lệ lá, tỉ lệ truy vấn masked-answerable, tỉ lệ claim→conduct đi được bằng cấu trúc, tỉ lệ node T2 có degree ≥ 2 |
| Q8 | Independence | phân bố bằng chứng conduct theo kênh |

**(c) Các thiết kế đánh giá không-nhãn còn lại** (mô tả như *future work có thiết kế sẵn*, đừng mô
tả như đã chạy — xem `docs/EVALUATION_WITHOUT_LABELS.md` và `docs/AGENT_AB_EVALUATION.md`):
quan hệ metamorphic (paraphrase một claim không được làm đổi verdict), negative control +
permutation p-value (ghép claim với bằng chứng của công ty khác thì tỉ lệ "contradicted" phải sập
về mức ngẫu nhiên), và Krippendorff α cho độ đồng thuận giữa nhiều lần adjudicate.
[TODO-RUN — nếu chạy được **negative control** thôi cũng đã rất mạnh: nó chứng minh hệ thống không
chỉ đang gán nhãn bừa. Chi phí thấp nhất trong ba cái.]

---

## 5.2 Ablation A — Temporal Integrity Redesign (Phase 0)

**Thiết lập.** Cùng corpus, cùng LLM, chỉ đổi phần xử lý thời gian offline (chuẩn hoá ISO, sửa
chuỗi version, mặc định `date_uncertain`, gỡ trường thời gian khỏi `identity_keys` của class T1).
Đo bằng `quality --label baseline` và `quality --label after-phase0`.

**Table 3. Effect of the Phase-0 temporal redesign.** [REAL — cả hai cột từ artifact trong repo]

| Metric | Baseline | After Phase 0 | Δ |
|---|---:|---:|---|
| Graph size (nodes / edges) | 10,573 / 13,008 | 10,362 / 13,047 | −211 / +39 |
| **Q2 total consistency violations** | **1,098** | **1** | **−99.9%** |
| — broken `is_current` chains | 660 | 0 | −660 |
| — format-split versions | 312 | 0 | −312 |
| — missing `date_uncertain` | 124 | 0 | −124 |
| — T1 classes with time in identity | 2 | 0 | −2 |
| Q3 surplus duplicate T1 nodes | 271 | 60 | −78% |
| Q5 T2 nodes with `valid_from` | 0.0% | 87.7% | +87.7pp |
| Q5 news T2 with `date_uncertain` | 0.0% | 100.0% | +100pp |
| Q7 leaves | 83.2% | 82.2% | −1.0pp |
| Q7 masked-answerable | 25.1% | 26.3% | +1.2pp |

**Diễn giải để viết.** Ba điểm:
1. Việc **giảm node** (10,573 → 10,362) mà **tăng cạnh** là dấu hiệu đúng của hợp nhất: 211 node
   trùng bị gộp, và các cạnh vốn phân tán trên các bản sao nay quy về một thực thể.
2. Q3 giảm 78% số node T1 trùng dư là **hệ quả trực tiếp** của P1 (gỡ thời gian khỏi identity) —
   trước đó cùng một tổ chức bị tách theo từng năm.
3. Con số 87.7% (không phải 100%) ở Q5 là trung thực: phần còn lại là các node T2 mà tài liệu gốc
   thực sự không nêu mốc thời gian nào. Hệ thống bỏ trống thay vì bịa. **Đừng làm tròn lên.**

---

## 5.3 Ablation B — Standard-Indicator Axis Materialisation

**Thiết lập.** Cùng graph đã resolve, chỉ bật/tắt bước materialise trục chỉ số (§3.5.6).

**Table 4. Effect of materialising the indicator axis.** [REAL]

| Metric | Before | After | Δ |
|---|---:|---:|---|
| Nodes / edges | 10,362 / 13,047 | 10,393 / 13,790 | +31 / +743 |
| Q7 leaves | 82.2% | **75.8%** | **−6.4pp** |
| Q7 masked-answerable | 26.3% | **34.8%** | **+8.5pp** |
| Q7 T2 nodes with degree ≥ 2 | 10.1% | **19.9%** | **+9.8pp** |
| Q7 median degree | 1.0 | 1 | — |
| Q2 violations | 1 | 1 | 0 |

**Diễn giải để viết.** +31 node mang lại +743 cạnh — tức mỗi node chỉ số trung bình nối ~24 quan
sát/tuyên bố. Tỉ lệ node T2 có degree ≥ 2 **gần gấp đôi**: trước đó phần lớn quan sát KPI là lá
treo, không tham gia được vào bất kỳ đường suy luận nào. Đây chính là cơ chế biến một "túi quan sát"
thành một đồ thị **đi được**. Và Q2 giữ nguyên ở 1 chứng minh bước này **append-only** đúng như
thiết kế — không phá vỡ bất biến nào.

**Table 5. Q7(e) anchoring per T2 class (after).** [REAL]

| Class | Nodes | degree ≥ 2 |
|---|---:|---:|
| Emission | 24 | 100.0% |
| Project | 255 | 53.3% |
| Investment | 282 | 50.4% |
| KPIObservation | 4,906 | 16.9% |
| Initiative | 495 | 14.7% |
| Waste | 15 | 13.3% |
| MediaReport | 91 | 9.9% |
| Controversy | 2 | 0.0% |
| Penalty | 4 | 0.0% |
| ThirdPartyVerification | 24 | 0.0% |

Bảng này nên đưa vào kèm một câu thẳng thắn: Controversy/Penalty/ThirdPartyVerification ở 0% neo
là **hạn chế đã biết**, và nguyên nhân là kênh conduct mỏng (§6), không phải lỗi thuật toán neo.

---

## 5.4 Cross-Check Results

**Table 6. Claim–conduct cross-check on AAA.** [REAL — toàn bộ từ `aaa_crosscheck_stats.json`]

| Quantity | Value |
|---|---:|
| Sustainability claims extracted | 1,093 |
| Conduct pool | 124 (MediaReport 16 + KPIObservation 108) |
| Claims with ≥1 candidate | 748 (68.4%) |
| Candidate claim–evidence pairs | 3,461 |
| Avg. candidates per claim | 3.17 |
| LLM adjudications performed | 3,461 (0 failures) |
| Linking edges written | 152 |
| → `appears_supported` | 70 |
| → `appears_contradicted` | 22 |
| → `unverified_insufficient_evidence` | 1,001 |

**Cách trình bày con số 1,001 — đọc kỹ chỗ này.** Đừng viết nó như thất bại. Viết nó như **hành vi
thiết kế**: 91.6% claim được trả về "chưa kiểm chứng được" vì corpus conduct độc lập cho một doanh
nghiệp niêm yết cỡ trung ở Việt Nam **thực sự mỏng** — 30 bài báo cho 15 năm. Một hệ thống trung
thực phải nói "tôi không biết"; một hệ thống bịa ra phán quyết cho cả 1,093 claim mới là hệ thống
đáng lo. Câu chốt nên là caveat mà chính hệ thống in ra:

> *Thin independent conduct — absence of contradiction is NOT exoneration.*

---

## 5.5 Qualitative Case Studies

Ba case, format giống mẫu §5.3 (câu hỏi → output → nhận xét). [REAL — cả ba lấy từ dossier thật]

**Case 1 — Supported (social/labour).**
Claim (AR 2012): *"Company implements monthly, quarterly, and annual bonus systems to motivate
employees."* → `appears_supported`, conf 0.90. Bằng chứng: `KPIObservation` "Employee stock bonus
payout for 2024 profits — 114.5 tỷ VND". Nhận xét: hệ thống nối được một cam kết chính sách 2012
với một quan sát chi trả thực tế 2024 — đúng loại suy luận liên năm mà biểu diễn temporal tồn tại
để phục vụ. Caveat tự động: `date_uncertain` trên bằng chứng.

**Case 2 — Contradicted (governance/capital).**
Claim (AR 2012): *"Actively sought investment sources to effectively use capital from shareholders
and investors."* → `appears_contradicted`. Bằng chứng phản: "Total assets change −11.5% (2025-06-30)",
conf 0.90. Đồng thời có bằng chứng thuận (Nhà máy số 6, 500.6 tỷ VND, 2016), nên hồ sơ mang caveat
*"Evidence is mixed"* và theo quy tắc ưu tiên, mâu thuẫn thắng.

**Case 3 — Unverified.**
Claim (AR 2011) về hoạt động xã hội, từ thiện, tặng quà. → `unverified_insufficient_evidence`, không
có ứng viên nào. Nhận xét: loại claim định tính, không có KPI đo được và không có tin tức độc lập
đưa tin. Đây là **hình dạng điển hình** của 1,001 claim chưa kiểm chứng được, và cũng là ranh giới
năng lực thật của hệ thống.

---

## 5.6 Error Analysis

Theo đúng format E1–E5 của mẫu. Bốn nhóm lỗi quan sát được (mỗi nhóm cần bạn soi thêm ~10–20 hồ sơ
để ước lượng % — [TODO-RUN], nhưng bản chất lỗi thì đã xác định được từ dữ liệu hiện có):

**E1 — Temporal-distance mismatch.** Adjudicator ghép một claim 2012 với bằng chứng 2025 (Case 2)
mà không chiết khấu theo khoảng cách thời gian. Cửa sổ `window_after = 50` là quá rộng để không
kèm hàm suy giảm. *Hướng sửa: thêm trọng số suy giảm theo khoảng cách năm vào bước tổng hợp.*

**E2 — Generic-claim over-matching.** Các claim rất chung ("nỗ lực phát triển bền vững") ghép được
với gần như mọi KPI, tạo cả support lẫn contradiction giả. *Hướng sửa: lọc theo độ đặc hiệu của
claim trước khi retrieve; các claim dưới ngưỡng đặc hiệu nên bị route thẳng sang `unverified`.*

**E3 — Sparse conduct channel.** Nguyên nhân trội của 1,001 `unverified`. Không phải lỗi thuật
toán. *Hướng sửa: mở rộng kênh conduct — dữ liệu xử phạt hành chính, công bố của Sở/UBCK, dữ liệu
quan trắc môi trường.*

**E4 — `date_uncertain` propagation.** Phần lớn bằng chứng phía news phải dùng ngày xuất bản làm
proxy, nên caveat "uncertain date" xuất hiện dày đặc và mất dần sức cảnh báo do quen mắt. *Hướng
sửa: trích mốc thời gian ở mức câu bằng NER thay vì rơi về ngày xuất bản của cả bài.*

[WRITE: nếu soi được 20 hồ sơ và ước lượng được % cho từng loại, làm bảng phân bố như Table 7 của
mẫu — nó nâng chất lượng phần này lên hẳn.]

---

# 6. Discussion, Limitations and Ethics

**Viết mục này tử tế. Đây là chỗ phân biệt một capstone khá và một capstone tốt.**

## 6.1 Limitations

1. **Kênh conduct mỏng.** 208/10,425 node đến từ news [REAL]. Hệ quả trực tiếp: 91.6% claim không
   kiểm chứng được. Nói thẳng, đừng giấu sau ngôn ngữ tích cực.
2. **Một issuer được phân tích sâu.** Kết quả là case study có chiều sâu thời gian, chưa phải bằng
   chứng khái quát cho toàn ngành.
3. **Không có ground truth**, nên không tồn tại precision/recall của việc *phát hiện greenwashing* —
   chỉ có các thuộc tính chất lượng đồ thị và tính nhất quán nội tại.
4. **Entity resolution đang chạy giảm cấp** (`--no-llm`: chỉ Stage A + B.1) do ràng buộc billing.
   Stage B (embedding blocking) và Stage C (LLM adjudication) đã hiện thực và có test, nhưng không
   bật trong kết quả báo cáo. **Phải nói rõ**, vì con số Q3 (60 node T1 trùng dư) sẽ khác nếu bật.
5. **Phụ thuộc LLM thương mại.** Adjudication chạy trên `gpt-4o-mini`; kết quả không tái lập
   bit-for-bit qua các phiên bản model.
6. **Không có đánh giá con người có hệ thống.** Chưa có nhiều annotator độc lập chấm lại các
   verdict, nên chưa có inter-annotator agreement.

## 6.2 Ethical considerations

**Đây là mục mẫu không có và bạn bắt buộc phải có** — hệ thống của bạn đưa ra phát biểu về hành vi
của **doanh nghiệp có thật, đang niêm yết**.

- **Advisory, không phán quyết.** Mọi output mang cờ `assessment_is_advisory: true` và caveat
  "không tồn tại nhãn ground truth". Hệ thống **không** sinh điểm greenwashing, cố ý.
- **Vắng mặt mâu thuẫn ≠ trong sạch.** Đã cứng hoá thành caveat trong mọi thống kê xuất ra.
- **Provenance là biện pháp bảo vệ, không phải tính năng.** Vì mọi phát biểu truy được về (file,
  trang, câu), một cáo buộc sai luôn có thể bị người đọc bác bỏ bằng cách mở đúng trang đó.
- **Guard tự-xác-nhận.** Nội dung do chính công ty xuất bản không được tính là bằng chứng độc lập.
- **Rủi ro dùng sai.** Nếu ai đó bỏ qua các caveat và đọc "appears_contradicted" như kết luận, hệ
  thống có thể gây thiệt hại danh tiếng không đáng có. Vì vậy claim ledger sắp signal-first **kèm**
  coverage caveat ngay đầu bảng, không phải ở footnote.

---

# 7. Conclusion

[WRITE — bám sườn mẫu §6, 3 đoạn]

Đoạn 1: nhắc lại bài toán và cách tiếp cận (temporal KG hai kênh, năm module).
Đoạn 2: kết quả chính, dùng số thật — 10,425 node / 14,402 edge; Q2 violations 1,098 → 1;
masked-answerable 26.3% → 34.8%; 1,093 claim cross-check, 3,461 adjudication, 70 supported /
22 contradicted / 1,001 unverified.
Đoạn 3: hướng phát triển — mở rộng kênh conduct (xử phạt hành chính, quan trắc môi trường), nhân
rộng ra nhiều issuer, chạy negative-control + metamorphic evaluation, và tầng suy luận theo đường
đi trên đồ thị.

---

# References

[WRITE] Tối thiểu ~30 ref để ngang mẫu (42 ref). Bộ khung theo nhóm:

**ESG & greenwashing:** ESG disclosure literature review; ESG–financial performance meta-analysis;
greenwashing definition & measurement; ESG rating divergence.
**Vietnamese regulation:** Thông tư 96/2020/TT-BTC; Quyết định 2171/QĐ-BTC; QCVN 09:2013/BXD;
SSC–IFC ESG guide.
**Standards:** GRI Universal Standards 2021; GRI topic standards.
**Document parsing:** PyMuPDF; Marker/Surya; olmOCR; Nougat; Docling.
**Vietnamese NLP:** underthesea; PhoBERT; ViDeBERTa.
**KG & temporal KG:** Hogan et al. *Knowledge Graphs* (ACM CSUR 2021); bi-temporal data models;
LLM-based KG construction (Trajanoska et al.; Carta et al.); Neo4j.
**RAG & LLM:** Lewis et al. RAG; structured output / constrained decoding; LLM-as-a-judge;
hallucination trong high-stakes domains.
**Evaluation:** metamorphic testing; permutation test; Krippendorff α; FEVER.

---

# Appendix

- **A.** Graph schema — 28 node classes, ~50 edge labels, T1/T2/T3 tier assignment
  (từ `config/schema.json`).
- **B.** Extraction prompt templates — claim-side và conduct-side, kèm ràng buộc ngôn ngữ
  (từ `esg_kg/graph/extract_triples.py`).
- **C.** Adjudication prompt + output schema của cross-check
  (từ `esg_kg/crosscheck/claims_vs_conduct.py`).
- **D.** Indicator metadata schema — record GRI catalogue + record KPI definition, kèm khối
  provenance/sha256.
- **E.** Ví dụ advisory dossier đầy đủ — 1 supported, 1 contradicted, 1 unverified (Case 1–3).
- **F.** Neo4j constraints (`neo4j/init.cypher`) + truy vấn phân tích
  (`neo4j/crosscheck_queries.cypher`).

---
---

# §X. Ghi chú cho nhóm (không đưa vào báo cáo)

## X.1 Bốn khác biệt lớn nhất so với báo cáo mẫu

| | Mẫu (Group 2) | Của bạn |
|---|---|---|
| **Bài toán** | ESG Question Answering | Greenwashing analysis (claim ↔ conduct) |
| **Nguồn bằng chứng** | Chỉ báo cáo doanh nghiệp | **Hai kênh độc lập** ← điểm mạnh nhất |
| **Chiều thời gian** | Không (KG atemporal) | **Temporal KG, T1/T2/T3, P1–P8** ← điểm mạnh thứ hai |
| **Đánh giá** | 120 câu hỏi expert → accuracy 88.14% | **Không có ground truth** → Q1–Q8 + ablation ← điểm yếu, phải xử lý khéo |

Ba việc cần làm để bù cột cuối:
1. **Chạy negative control** (rẻ nhất, mạnh nhất): ghép claim của AAA với conduct pool của một công
   ty khác, đo tỉ lệ `appears_contradicted`. Nếu nó sập gần về 0 → hệ thống có tính đặc hiệu thật.
   Nếu không sập → đó cũng là một phát hiện đáng báo cáo, và trung thực.
2. **Điền bảng F1 của ViDeBERTa** — hội đồng chắc chắn hỏi "mô hình phân loại tốt cỡ nào".
3. **Chạy thêm 2–3 issuer** nếu kịp → "case study" thành "multi-issuer evaluation".

## X.2 Về yêu cầu "fake phương pháp trích xuất GRI"

Tôi không viết vào báo cáo một phương pháp mà code không chạy. Nhưng vấn đề bạn lo — "gọi API nghe
không đủ xịn" — thì giải quyết được **mà không cần bịa**, vì ba lý do:

1. **Marker đúng là SOTA.** Datalab Marker không phải "một cái API convert PDF". Nó là bản hosted
   của `marker` — pipeline ghép layout detection + reading-order detection + table recognition +
   OCR trên nền Surya. Nó ngang hàng với olmOCR mà chính báo cáo mẫu trích dẫn ở ref [20], và
   **mạnh hơn** PyMuPDF mà chính báo cáo mẫu dùng cho GRI ở §3.2. Tức là ở đúng bước này, bạn đang
   dùng công cụ **tốt hơn nhóm mẫu** — chỉ là đang mô tả nó tệ hơn.

2. **Phần bạn tự làm mới là phần khó, và bạn đang không kể.** Marker chỉ cho ra Markdown. Còn lại
   là của bạn: disclosure segmentation theo heading hierarchy, **ownership rule** `standard_of()`
   (sửa 80/136 entry sai và 31 title hỏng — đây là một phát hiện dữ liệu thật, có test bảo vệ),
   version merging cho GRI 306 (2016 + 2020), provenance sha256 per-PDF, và crosswalk
   confirmed-only sang TT96. **Đó** là contribution. Không nhóm nào khác có ownership rule này.

3. **Bản §3.2 tôi viết ở trên đã dùng đúng ngôn ngữ học thuật** cho những gì thực sự chạy: "layout-
   aware linearisation", "composes a layout-detection model, an order-detection model, a table-
   recognition model and an OCR model", "content-addressed caching for byte-reproducible rebuilds",
   có công thức, có so sánh với Nougat/Docling/olmOCR. Đọc lại §3.2.2 — nó không hề "nhẹ ký" hơn
   §3.3 của báo cáo mẫu, và mọi câu trong đó đều đúng sự thật.

**Nếu vẫn muốn mạnh hơn nữa, đây là cách làm cho lời khẳng định trở thành sự thật** (chi phí ~1
buổi, và nó cho bạn thêm nguyên một bảng kết quả):

> Chạy PyMuPDF thuần trên đúng 42 PDF GRI, parse bằng cùng segmenter, rồi đo **disclosure-code
> recall** của cả hai parser so với GRI content index chính thức (`gri/gri-content-index-template-2021.xlsx`
> — file đã có sẵn trong repo). Ra một bảng hai dòng. Lúc đó câu "we selected a layout-aware parser
> over positional text extraction" không còn là lời tuyên bố — nó là **kết quả đo được**, và bạn có
> thêm một ablation nữa cho §5.

Tôi có thể viết script đo đó nếu bạn muốn — nói một tiếng.

## X.3 Thứ tự nên viết

1. §3 Methodology (dài nhất, và bạn đã có `docs/` đầy đủ để bám)
2. §4 Dataset + §5.2–5.4 (số đã có sẵn, chỉ việc điền)
3. §5.1 Evaluation design (khó nhất về lập luận — viết khi đầu còn tỉnh)
4. §6 Limitations + Ethics
5. §1 Introduction + §7 Conclusion (viết cuối, khi đã biết chính xác mình có gì)
6. §2 Related Work (song song, ai cũng làm được)
