# Đánh giá hệ thống — khung không nhãn (label-free evaluation)

*Số liệu đọc từ `evaluation_report` sinh lúc 2026-08-08T04:24:57+00:00.*

## 1. Vì sao không có precision / recall / F1

Không tồn tại bộ dữ liệu greenwashing **có nhãn** cho doanh nghiệp niêm yết Việt Nam. Không có nhãn thì không có ma trận nhầm lẫn, và mọi con số dạng *accuracy* đều là bịa. Khung này vì thế đo ba thứ **đo được**, theo thứ tự tăng dần về sức thuyết phục:

1. **Chỉ số nội bộ (M1–M5)** — hệ thống có làm đúng điều nó tự tuyên bố không: truy nguyên được, hợp schema, không bịa giá trị, không tự xác minh. Điểm yếu cố hữu: chúng chỉ đối chiếu hệ thống **với thiết kế của chính nó**, nên không cái nào có thể FAIL một cách thú vị.
2. **Negative control (NC.1, NC.2)** — phép kiểm **có thể làm hệ thống trượt**, kèm giả thuyết không và một thống kê (lift) để bác bỏ nó.
3. **Tầng chuyên gia** — rubric Likert 5 điểm + độ đồng thuận (Gwet AC2 / Krippendorff α). Bộ máy đã sẵn sàng; chưa có phiếu chấm thật nên **không** báo số nào ở đây.

> Hệ thống là **Decision-Support System**, không phải bộ phân loại greenwashing. Đầu ra là hồ sơ bằng chứng + đánh giá tư vấn, không phải phán quyết.

## 2. Thiết lập thực nghiệm

| Hạng mục | Giá trị |
|---|---|
| Từ vựng ESG neo được (M1.1) | 417 cụm từ |
| Số câu đã quét (báo cáo) | KHÔNG ĐO ĐƯỢC |
| Số câu đã quét (tin tức) | 174,256 |
| Đồ thị đã phân giải | 10,634 node / 14,744 cạnh |
| Bộ ba đã kiểm định | 14,500 |
| Hồ sơ đối soát | 464 claim / 5 mã CK |
| Mã chứng khoán | AAA, ACC, ACG, ADP, AGG |
| Thời gian chạy | 16.8s |

**Ký hiệu dùng trong các công thức:**

| Ký hiệu | Nghĩa |
|---|---|
| `S_r, S_n` | tập câu đã gán nhãn của kênh báo cáo / kênh tin tức |
| `esg(s)` | cờ nhị phân do ViDeBERTa-v3-ESG gán cho câu s |
| `L` | từ vựng ESG có kiểm soát (TT96 / QĐ2171 / QCVN09 / GRI), đã fold dấu |
| `G = (V, E)` | đồ thị đã phân giải, `graph_output/resolved/resolved_graph.json` |
| `V_T1` | node thực thể bền vững (Organization, Facility, …) — danh tính vô thời gian |
| `V_T2∪T3` | node sự kiện/quan sát (KPIObservation, Penalty, MediaReport, …) |
| `Σ` | tập bộ ba hợp lệ (predicate, lớp nguồn, lớp đích) khai trong `config/schema.json` |
| `τ(e)` | `temporal_metadata` của cạnh e |
| `D` | tập hồ sơ đối soát (dossier), một phần tử cho mỗi SustainabilityClaim |
| `a(d)` | kết luận tư vấn của hồ sơ d ∈ {appears_supported, appears_contradicted, unverified_insufficient_evidence} |
| `feed(x)` | mã CK mà bằng chứng x được thu thập dưới đó, suy từ tiền tố `source_doc = <TICKER>__<domain>__<hash>` |
| `ticker(d)` | mã CK của doanh nghiệp phát ra tuyên bố trong hồ sơ d |

## 3. Kết quả

| Mã | Chỉ số | Giá trị | Tử / Mẫu | Trạng thái |
|---|---|---:|---:|:--:|
| M1.1r | ESG Signal-to-Noise Ratio — báo cáo | KHÔNG ĐO ĐƯỢC | — | — |
| M1.2r | Paragraph Source Provenance Rate — báo cáo | KHÔNG ĐO ĐƯỢC | — | — |
| M1.1n | ESG Signal-to-Noise Ratio — tin tức | 62.14% | 47,990 / 77,229 | — |
| M1.2n | Paragraph Source Provenance Rate — tin tức | 100.00% | 174,256 / 174,256 | PASS |
| M2.1 | Temporal Metadata Completeness | 93.02% | 21,620 / 23,243 | FAIL |
| M2.2 | Schema Compliance Rate | 100.00% | 14,744 / 14,744 | PASS |
| M2.3 | Value Preservation Guard | 100.00% | 500 / 500 | PASS |
| M3.1 | Timeless Identity Violation Rate | 0.00% | 0 / 14 | PASS |
| M3.2 | Oversimplification & Cluster Conciseness | 0.47% | 10 / 2,135 | — |
| M4.1 | Standard Indicator Alignment Coverage | 50.53% | 718 / 1,421 | — |
| M4.2 | Zero-Report Self-Praise Exclusion | 100.00% | 1 / 1 | PASS |
| M5.1 | Evidence Asymmetry & Abstention Rate | 96.55% | 448 / 464 | — |
| M5.2 | Self-Verification Exclusion Rate | 0.00% | 0 / 19 | — |
| NC.1 | Same-Company Evidence Rate | 100.00% | 24 / 24 | PASS |
| NC.2 | Same-Feed Specificity vs Chance | 100.00% | 24 / 24 | PASS |

## 4. Định nghĩa chỉ số

### 1. Thu thập & Phân loại ESG

#### M1.1r — ESG Signal-to-Noise Ratio — báo cáo

Tỷ lệ câu được classifier nhận là ESG mà còn neo được vào một cụm từ trong từ vựng chuẩn — phần tín hiệu thực sự dùng được cho khâu sau.

```
M1.1 = |{s ∈ S : esg(s) = 1 ∧ ∃t ∈ L, t ⊑ fold(text(s))}| / |{s ∈ S : esg(s) = 1}|
```

**Kết quả:** *KHÔNG ĐO ĐƯỢC* · mục tiêu: cao hơn = ít câu tiếp thị chung chung lọt qua bộ phân loại

> KHÔNG ĐO ĐƯỢC — thiếu artifact: data\labeled\classified\all_sentences_classified.jsonl not found. Lấy về bằng: python src/esg_kg/core/datasync.py pull

**Xây dựng từ:** `data/labeled/classified/all_sentences_classified.jsonl`, stream một lượt. L dựng bởi `evalu/lexicon.py` từ `kpi_definitions_construction.json` (35 KPI + cụm con), `config/kpi_type_aliases.json` và `config/gri_catalog.json`; so khớp bằng `LexiconMatcher` trên chuỗi đã fold dấu.

**Vì sao cần:** Classifier gán nhãn theo ngữ nghĩa câu, nên văn tiếp thị rỗng ('hướng tới phát triển bền vững') vẫn lọt qua. Chỉ số này tách phần *đo được* khỏi phần *hứa hẹn*, tức chất lượng đầu vào của khâu trích xuất KPI.

#### M1.2r — Paragraph Source Provenance Rate — báo cáo

Tỷ lệ câu giữ nguyên đủ ba toạ độ nguồn qua toàn bộ pipeline.

```
M1.2 = |{s ∈ S : source_pdf(s) ≠ ⊥ ∧ page(s) ≠ ⊥ ∧ sentence_index(s) ≠ ⊥}| / |S|
```

**Kết quả:** *KHÔNG ĐO ĐƯỢC* · mục tiêu: 100%

> KHÔNG ĐO ĐƯỢC — thiếu artifact: data\labeled\classified\all_sentences_classified.jsonl not found. Lấy về bằng: python src/esg_kg/core/datasync.py pull

**Xây dựng từ:** Cùng một lượt stream với M1.1. Kiểm `is not None` chứ không kiểm truthiness — `page = 0` là một toạ độ thật, không phải khuyết.

**Vì sao cần:** Điều kiện tiên quyết của toàn hệ: một thẻ trên giao diện nói 'doanh nghiệp X mâu thuẫn' mà không chỉ được về đúng trang báo cáo thì không kiểm chứng được, và không được phép hiển thị.

#### M1.1n — ESG Signal-to-Noise Ratio — tin tức

Tỷ lệ câu được classifier nhận là ESG mà còn neo được vào một cụm từ trong từ vựng chuẩn — phần tín hiệu thực sự dùng được cho khâu sau.

```
M1.1 = |{s ∈ S : esg(s) = 1 ∧ ∃t ∈ L, t ⊑ fold(text(s))}| / |{s ∈ S : esg(s) = 1}|
```

**Kết quả:** **62.14%** (47,990 / 77,229) · mục tiêu: cao hơn = ít câu tiếp thị chung chung lọt qua bộ phân loại

**Xây dựng từ:** `data/labeled/news_labeled/all_news_sentences_classified.jsonl`, stream một lượt. L dựng bởi `evalu/lexicon.py` từ `kpi_definitions_construction.json` (35 KPI + cụm con), `config/kpi_type_aliases.json` và `config/gri_catalog.json`; so khớp bằng `LexiconMatcher` trên chuỗi đã fold dấu.

**Vì sao cần:** Classifier gán nhãn theo ngữ nghĩa câu, nên văn tiếp thị rỗng ('hướng tới phát triển bền vững') vẫn lọt qua. Chỉ số này tách phần *đo được* khỏi phần *hứa hẹn*, tức chất lượng đầu vào của khâu trích xuất KPI.

#### M1.2n — Paragraph Source Provenance Rate — tin tức

Tỷ lệ câu giữ nguyên đủ ba toạ độ nguồn qua toàn bộ pipeline.

```
M1.2 = |{s ∈ S : source_pdf(s) ≠ ⊥ ∧ page(s) ≠ ⊥ ∧ sentence_index(s) ≠ ⊥}| / |S|
```

**Kết quả:** **100.00%** (174,256 / 174,256) · mục tiêu: 100%

**Xây dựng từ:** Cùng một lượt stream với M1.1. Kiểm `is not None` chứ không kiểm truthiness — `page = 0` là một toạ độ thật, không phải khuyết.

**Vì sao cần:** Điều kiện tiên quyết của toàn hệ: một thẻ trên giao diện nói 'doanh nghiệp X mâu thuẫn' mà không chỉ được về đúng trang báo cáo thì không kiểm chứng được, và không được phép hiển thị.

### 2. Trích xuất Triplet & KPI

#### M2.1 — Temporal Metadata Completeness

Phần đồ thị thực sự tham gia được vào suy luận theo thời gian.

```
M2.1 = ( |{e ∈ E : {valid_from, valid_to, recorded_at} ⊆ dom(τ(e)) ∧ τ(e).valid_from ≠ ⊥}| + |{v ∈ V_T2∪T3 : valid_from(v) ≠ ⊥}| ) / ( |E| + |V_T2∪T3| )
```

**Kết quả:** **93.02%** (21,620 / 23,243) · mục tiêu: 100%

**Xây dựng từ:** `resolved_graph.json`. Node T1 bị loại khỏi mẫu số theo P2 (danh tính vô thời gian). `valid_to = ⊥` được tính là **khoảng mở**, không phải khuyết — chỉ kiểm sự *có mặt* của khoá.

**Vì sao cần:** Câu hỏi greenwashing luôn mang mốc thời gian ('cam kết 2021 vs hành vi 2023'). Cạnh không có `valid_from` thì không trả lời được câu hỏi đó. Phạt khoảng mở sẽ đẩy pipeline đi **bịa ngày kết thúc**, nên định nghĩa cố ý không phạt.

#### M2.2 — Schema Compliance Rate

Tỷ lệ cạnh có bộ ba (predicate, lớp nguồn, lớp đích) hợp lệ theo schema.

```
M2.2 = |{e ∈ E : (pred(e), cls(src(e)), cls(tgt(e))) ∈ Σ}| / |E|
```

**Kết quả:** **100.00%** (14,744 / 14,744) · mục tiêu: 100% (0 vi phạm)

**Xây dựng từ:** `resolved_graph.json` × `config/schema.json`. Một nhãn cạnh có thể hợp lệ với **nhiều** cặp lớp; khớp bất kỳ cặp nào là hợp lệ.

**Vì sao cần:** Bắt cạnh sai lớp trước khi chúng đi vào Neo4j và vào truy hồi bằng chứng. Xem giới hạn tự khai: chỉ số này đo đầu ra của chính validator.

#### M2.3 — Value Preservation Guard

Khâu sửa lỗi bằng LLM được phép chữa HÌNH DẠNG bộ ba, nhưng không được đụng vào GIÁ TRỊ ĐO.

```
M2.3 = |{v ∈ M : ∀f ∈ F, π_f^trước(v) = π_f^sau(v)}| / |M|,  F = {value, unit, amount, quantity, target_value},  M = {v : stable_id(v) khớp cả hai phía ∧ ∃f ∈ F xuất hiện ở ít nhất một phía}
```

**Kết quả:** **100.00%** (500 / 500) · mục tiêu: 100% (LLM không được sửa giá trị/đơn vị)

**Xây dựng từ:** Phía *trước*: node trong `graph_output/graphs/<doc>/page*.json` (mang `stable_id` do step 02 stamp). Phía *sau*: node trong `all_validated_triples.json`, tính lại id bằng chính `get_stable_entity_id` của pipeline. Ba dạng vi phạm được phân biệt: `changed` / `dropped` / `invented`.

**Vì sao cần:** Một mô hình được nhắc bằng tiếng Anh rất dễ 'sửa' `tấn` → `tons` hoặc làm tròn một con số; sai lệch đó đi thẳng vào hồ sơ đối soát mà không ai thấy. Điều kiện `∃f ∈ F` giữ cho mẫu số không rỗng — 100% trên tập không có trường nào để bảo vệ là 100% vô nghĩa.

### 3. Phân giải Thực thể

#### M3.1 — Timeless Identity Violation Rate

Nguyên tắc P1: không lớp T1 nào được đưa trường thời gian vào `identity_keys`.

```
M3.1 = |{c ∈ C_T1 : identity_keys(c) ∩ TimeFields ≠ ∅}| / |C_T1|,  TimeFields = {valid_from, valid_to, date, year, validity_period, …}
```

**Kết quả:** **0.00%** (0 / 14) · mục tiêu: 0 vi phạm

**Xây dựng từ:** `config/schema.json`. Bản đồ tầng T1/T2/T3 **import từ `esg_kg.report.quality`**, không khai lại — bản sao thứ hai sẽ trôi khỏi lint mà pipeline đang thật sự dùng.

**Vì sao cần:** Nếu danh tính một doanh nghiệp phụ thuộc thời gian thì mỗi năm sinh ra một node mới, và tuyên bố 2021 không bao giờ nối được với hành vi 2023. Lớp quan sát (KPIObservation…) thì **được phép** khoá theo thời gian, nên nằm ngoài phạm vi chứ không phải ngoại lệ.

#### M3.2 — Oversimplification & Cluster Conciseness

Tỷ lệ thực thể T1 còn trùng lặp sau khi phân giải (Stage A/B/C/D).

```
M3.2 = Σ_{b ∈ B, |b| > 1} (|b| − 1) / |V_T1|,  B = phân hoạch V_T1 theo khoá (class, normalize_name(name))
```

**Kết quả:** **0.47%** (10 / 2,135) · mục tiêu: thấp hơn = ít thực thể trùng còn sót sau hợp nhất

**Xây dựng từ:** `resolved_graph.json`, gom nhóm bằng chính `normalize_name` của pipeline. Trùng khác lớp bị bỏ qua có chủ ý (một Facility và một Organization được phép trùng tên).

**Vì sao cần:** Thực thể bị vỡ làm loãng bằng chứng: tuyên bố treo vào node này, tin tức treo vào node kia, khâu đối soát không bao giờ nối được hai bên.

### 4. Ánh xạ Trục Chỉ tiêu

#### M4.1 — Standard Indicator Alignment Coverage

Độ phủ của trục chỉ tiêu TT96/GRI trên các node có thể gán chỉ tiêu.

```
M4.1 = |{v ∈ V_A : ∃e ∈ E, pred(e) = alignsWithIndicator ∧ src(e) = v}| / |V_A|,  V_A = SustainabilityClaim ∪ Goal ∪ Initiative
```

**Kết quả:** **50.53%** (718 / 1,421) · mục tiêu: cao hơn = độ phủ TT96/GRI tốt hơn

**Xây dựng từ:** `resolved_graph.json` sau step 05c (tầng từ khoá) và, nếu có chạy, step 05d (tầng LLM).

**Vì sao cần:** Trục chỉ tiêu là mặt phẳng chung để nối *tuyên bố* với *hành vi*: không có cạnh này thì một claim không bao giờ gặp được KPI/tin tức cùng chủ đề.

#### M4.2 — Zero-Report Self-Praise Exclusion

Một lời tự khai 'số lần bị xử phạt: 0' phải được gắn cờ VÀ không được biến thành bằng chứng conduct.

```
M4.2 = |{p ∈ P_0 : self_reported_zero(p) ∧ deg_axis(p) = 0}| / |P_0|,  P_0 = {v ∈ V : cls(v) = Penalty ∧ amount(v) = 0},  deg_axis = bậc trên cạnh {measuredUnder, alignsWithIndicator}
```

**Kết quả:** **100.00%** (1 / 1) · mục tiêu: 100%

**Xây dựng từ:** `resolved_graph.json`. 'Cạnh conduct' **chỉ** gồm cạnh trục chỉ tiêu; cạnh cấu trúc `Organization -subjectToPenalty-> Penalty` KHÔNG tính — nó chỉ ghi nhận doanh nghiệp đã công bố, và mọi Penalty tự khai 0 đều hợp lệ khi có nó.

**Vì sao cần:** Đây là kiểu sai lầm mà một công cụ chống greenwashing tuyệt đối không được mắc: khuếch đại lời tự khen thành 'đã được xác minh'.

### 5. Đối soát Chéo

#### M5.1 — Evidence Asymmetry & Abstention Rate

Tỷ lệ tuyên bố mà hệ thống TỪ CHỐI kết luận vì không đủ bằng chứng độc lập.

```
M5.1 = |{d ∈ D : a(d) = unverified_insufficient_evidence}| / |D|
```

**Kết quả:** **96.55%** (448 / 464) · mục tiêu: mô tả độ mỏng của kho bằng chứng — không phải chỉ tiêu cần tối ưu

**Xây dựng từ:** `graph_output/crosscheck/*_claim_assessments.json` (đầu ra step 07).

**Vì sao cần:** Trong hệ hỗ trợ ra quyết định, **im lặng đúng lúc là một tính năng**: thà không nói còn hơn quy kết sai cho một doanh nghiệp có thật, nêu đích danh. Đây là thuộc tính của DỮ LIỆU (kho tin độc lập mỏng), không phải của thuật toán — và **không được** trình bày như chỉ tiêu cần giảm.

#### M5.2 — Self-Verification Exclusion Rate

Tỷ lệ bằng chứng-ủng-hộ bị loại vì đến từ chính tên miền của doanh nghiệp.

```
M5.2 = |Flagged| / (|Kept| + |Flagged|),  Flagged = bằng chứng ủng hộ bị guard tự-xác-minh loại, Kept = bằng chứng ủng hộ từ nguồn độc lập được giữ
```

**Kết quả:** **0.00%** (0 / 19) · mục tiêu: bằng chứng xác nhận phải đến từ nguồn độc lập

**Xây dựng từ:** Trường `flagged_non_independent_support` và `supporting_evidence` của hồ sơ step 07.

**Vì sao cần:** Doanh nghiệp không được tự xác nhận mình. Nếu 'bằng chứng độc lập' hoá ra là thông cáo trên website của chính họ thì toàn bộ kết luận sụp.

### Negative control — quy thuộc bằng chứng

#### NC.1 — Same-Company Evidence Rate

Negative control: khi hệ thống trích một bản tin làm bằng chứng cho tuyên bố của doanh nghiệp T, bản tin đó có thật sự nói về T không?

```
NC.1 = |{(d, x) : feed(x) = ticker(d)}| / |{(d, x) : feed(x) ≠ ⊥}|,  x chạy trên supporting_evidence ∪ contradicting_evidence của d
```

**Kết quả:** **100.00%** (24 / 24) · mục tiêu: 100% (bằng chứng phải nói về chính doanh nghiệp bị xét)

**Xây dựng từ:** Hồ sơ step 07 × `resolved_graph.json` (`node_index` → node) × `config/issuer_registry.json` (biến thể tên mỗi issuer). Quy thuộc bằng tiền tố `source_doc`; `cross_feed_unmentioned` còn kiểm xem văn bản mà LLM **thực sự nhìn thấy** có nhắc tên doanh nghiệp không.

**Vì sao cần:** Đây là phép kiểm **CÓ THỂ LÀM HỆ THỐNG TRƯỢT** — khác toàn bộ nhóm M1–M5 vốn chỉ đối chiếu hệ thống với thiết kế của chính nó, nên không cái nào FAIL một cách thú vị, nên không cái nào chứng minh được hệ thống *hoạt động*. Nếu bằng chứng không nói về đúng công ty thì mọi kết luận phía sau vô giá trị, bất kể LLM lập luận hay đến đâu.

### Negative control — độ đặc hiệu theo công ty

#### NC.2 — Same-Feed Specificity vs Chance

Biến NC.1 thành một phép kiểm giả thuyết có đối chứng: truy hồi có mang tín hiệu *công ty* hay chỉ đang khớp *chủ đề*?

```
H₀: bằng chứng được rút ngẫu nhiên đều từ kho conduct toàn cục.  E[same-feed | H₀] = Σ_T (|Pool_T| / |Pool|)·c_T / Σ_T c_T,  observed = Σ_T same_T / Σ_T c_T,  lift = observed / E[·| H₀]
```

**Kết quả:** **100.00%** (24 / 24) · mục tiêu: lift >> 1 (nếu ~1 thì truy hồi không mang tín hiệu công ty nào)

**Xây dựng từ:** `Pool_T` = số node conduct (Controversy/Penalty/MediaReport, `source_type = news`) thuộc feed của mã T; `c_T` = số trích dẫn hệ thống thực sự dùng cho các tuyên bố của T.

**Vì sao cần:** NC.1 = 100% tự nó chưa đủ: nếu kho chỉ có tin của một công ty thì bốc ngẫu nhiên cũng ra 100%. `lift ≈ 1` nghĩa là **không bác bỏ được H₀** — truy hồi không phân biệt được với bốc ngẫu nhiên; `lift ≥ 2` mới coi là có tín hiệu thật; `lift < 1` là tệ hơn cả ngẫu nhiên.

## 5. Kiểm định giả thuyết của negative control

- Quan sát: **100.00%** same-feed trên 24 trích dẫn.
- Kỳ vọng dưới H₀ (bốc ngẫu nhiên từ kho 44 node conduct): **39.96%**.
- **lift = 2.50** → bác bỏ được H₀ (ngưỡng lift ≥ 2): truy hồi mang tín hiệu công ty.

Phân bố kho theo mã: `{'AAA': 7, 'ACC': 9, 'ACG': 18, 'ADP': 2, 'AGG': 8}`.

## 6. Giới hạn & đe doạ tính hợp lệ

Mỗi chỉ số tự khai giới hạn của chính nó; đây là bản gom, **phải đọc kèm bất kỳ con số nào được trích ra ngoài tài liệu này**.

- **M1.1r** — KHÔNG phải độ chính xác của bộ phân loại. Giá trị phụ thuộc mạnh vào cách dựng từ vựng: đổi cách dựng làm con số nhảy từ 4% lên 50%. Đây là chỉ số yếu nhất trong bộ, không nên trích dẫn như một kết quả độc lập.
- **M1.2r** — Gần như tất yếu đạt 100% vì pipeline chỉ sao chép cơ học ba trường này. Giá trị của nó là làm lưới chắn hồi quy, không phải là bằng chứng chất lượng.
- **M1.1n** — KHÔNG phải độ chính xác của bộ phân loại. Giá trị phụ thuộc mạnh vào cách dựng từ vựng: đổi cách dựng làm con số nhảy từ 4% lên 50%. Đây là chỉ số yếu nhất trong bộ, không nên trích dẫn như một kết quả độc lập.
- **M1.2n** — Gần như tất yếu đạt 100% vì pipeline chỉ sao chép cơ học ba trường này. Giá trị của nó là làm lưới chắn hồi quy, không phải là bằng chứng chất lượng.
- **M2.1** — Mẫu số lấy theo hợp đồng schema (mọi edge spec khai temporal_properties, mọi lớp T2/T3 khai valid_from). Nếu một số lớp cố ý để thời gian sống trên cạnh thay vì trên node thì phải sửa schema, không phải sửa chỉ số.
- **M2.2** — GẦN NHƯ TẤT YẾU đạt 100%: fix_triples cưỡng chế schema và đẩy cái không sửa được sang unfixable_triples.json. Đo độ tuân thủ trên đầu ra của chính bộ validator thì không nói lên chất lượng. Con số đáng báo cáo kèm là TỶ LỆ BỊ LOẠI (số bộ ba trong unfixable_triples.json), hiện chưa được đưa vào báo cáo này.
- **M2.3** — Chỉ so được các node ghép được stable_id ở cả hai phía; số node lệch được báo riêng ở `match_stats` thay vì bỏ qua âm thầm.
- **M3.1** — Đây là lint trên một file config viết tay, tức một unit test chứ không phải phép đánh giá hệ thống. Giá trị 0 là kỳ vọng mặc định, không phải thành tích. test/test_schema_contract.py đã kiểm điều này.
- **M3.2** — QUAN TRỌNG — con số này là CẬN DƯỚI và dễ gây yên tâm sai. Nó dùng chính normalize_name mà bộ phân giải dùng, nên chỉ thấy được thứ resolver lẽ ra gộp được bằng khoá của chính nó. Nó MÙ với thất bại thật: 'Công ty CP Nhựa An Phát' vs 'An Phát Holdings' sẽ không bị phát hiện. Mức trùng lặp thật gần như chắc chắn cao hơn nhiều.
- **M4.1** — CHỈ CÓ ĐỘ PHỦ, KHÔNG CÓ ĐỘ CHÍNH XÁC. Một bộ khớp ngu hơn, gán bừa chỉ tiêu cho mọi tuyên bố, sẽ đạt 100%. Vì vậy 'cao hơn' KHÔNG đương nhiên là 'tốt hơn'. Muốn dùng được con số này thì phải kiểm tay một mẫu ~50 cạnh để có vế precision đi kèm.
- **M4.2** — Cỡ mẫu cực nhỏ (thường chỉ 1-2 node trong toàn đồ thị). Đây là phép kiểm hồi quy, không phải một thống kê.
- **M5.1** — Đừng bao giờ trình bày như chỉ tiêu cần giảm. Một hệ thống dễ dãi hơn sẽ có abstention thấp hơn mà chất lượng tệ hơn.
- **M5.2** — Trên dữ liệu hiện tại guard chưa kích hoạt lần nào, nên chỉ số này KHÔNG chứng minh được là guard hoạt động. Nó chỉ ghi nhận rằng chưa có tình huống nào cần đến nó.
- **NC.1** — Quy thuộc dựa trên tiền tố ticker trong source_doc, tức 'bài này được crawl dưới feed của ai'. Một bài trong feed công ty khác mà có nhắc tên doanh nghiệp đang xét thì VẪN hợp lệ — hai trường hợp được tách riêng, không gộp làm một.
- **NC.2** — Kho conduct hiện rất nhỏ (44 node / 5 mã), nên lift theo từng mã có phương sai lớn — đọc con số tổng, và đọc `by_ticker` như dấu hiệu định tính chứ đừng như ước lượng điểm.

Bốn giới hạn ở tầng khung, không thuộc riêng chỉ số nào:

- Không có ground truth ⇒ **không** có precision/recall/F1 về greenwashing.
- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, **không** đo **tính đúng**.
- Tỷ lệ abstention cao phản ánh **kho tin tức độc lập còn mỏng**, không phải lỗi thuật toán.
- Đồ thị hiện chỉ phủ **5 mã CK**; corpus 197 doanh nghiệp mới dừng ở tầng phân loại câu. Mọi phát biểu 'hệ thống bao phủ 197 doanh nghiệp' là sai.
