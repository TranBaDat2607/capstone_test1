# Đánh giá 3 hướng bổ sung tầng multi-hop reasoning (SSRL) cho hệ thống Graph-RAG greenwashing

> **Trạng thái:** Tài liệu tư vấn / phản biện thiết kế, viết ngày **2026-07-27**.
> Không phải đặc tả triển khai. Đặc tả triển khai của tầng suy luận (step11–13) là
> `SSRL_REASONING_LAYER.md` — **file đó hiện KHÔNG tồn tại trong repo** dù `CLAUDE.md` và
> `TEMPORAL_KG_DESIGN.md` đều trỏ tới nó; tài liệu này viết dựa trên phần nội dung của nó
> được trích dẫn lại trong `TEMPORAL_KG_DESIGN.md`.
>
> **Câu hỏi được đặt ra:** đánh giá 3 hướng — (1) cải thiện cấu trúc KG để reasoning tốt hơn,
> (2) triển khai multi-hop reasoning trên graph, (3) tìm metric đánh giá trước/sau cải thiện
> phù hợp với hệ thống hiện tại.
>
> **Căn cứ:** bài báo *Knowledge Graph Reasoning with Self-supervised Reinforcement Learning*
> (arXiv:2405.13640v2, IEEE 2025) · `SYSTEM_DESIGN.md` · `TEMPORAL_KG_DESIGN.md` (P1–P8, Q1–Q8)
> · `src/step00_graph_quality_report.py` · `src/step10_evaluate.py` · và **đo trực tiếp** trên
> `graph_output/resolved/resolved_graph.json` (build 2026-07-26, 10.423 node / 14.399 cạnh).
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) · [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md)

---

## Mục lục

- [0. Kết luận thẳng](#0-kết-luận-thẳng-trước-khi-đi-vào-3-hướng)
- [1. Hướng (1) — Cải thiện cấu trúc KG](#1-hướng-1--cải-thiện-cấu-trúc-kg)
- [2. Hướng (2) — Triển khai multi-hop reasoning](#2-hướng-2--triển-khai-multi-hop-reasoning)
- [3. Hướng (3) — Metrics đánh giá trước/sau](#3-hướng-3--metrics-đánh-giá-trướcsau)
- [4. Lộ trình đề xuất](#4-lộ-trình-đề-xuất)
- [5. Tóm tắt ý kiến](#5-tóm-tắt-ý-kiến)
- [Phụ lục A — Cách tái lập các số đo](#phụ-lục-a--cách-tái-lập-các-số-đo)
- [Phụ lục B — Bảng số liệu gốc](#phụ-lục-b--bảng-số-liệu-gốc)

---

## 0. Kết luận thẳng trước khi đi vào 3 hướng

Bài báo SSRL tự nó chỉ ra **3 điều kiện** quyết định phương pháp có ăn thua không
(§V-D, Fig. 5, Fig. 7). Cả 3 đều đo được, và đã được đo trên đồ thị hiện tại:

| Điều kiện bài báo nêu | Dataset trong bài báo | **Đồ thị của dự án** | Phán quyết |
|---|---|---|---|
| Đáp án nằm trong ≤ 3 hop | FB15K-237: **99,8%** | **46,8%** (che cạnh, mẫu 800)<br>**26,9%** nếu không đi qua hub AAA | ⛔ chặn |
| Bậc trung bình / trung vị | 2,19 – 19,74 | 2,76 / **median 1** (70,8% node bậc 1) | ⛔ chặn |
| Truy vấn to-many (nơi SSRL lãi nhiều nhất, Fig. 5) | FB15K-237 phần lớn to-many | **13,1%** to-many | ⚠ lãi nhỏ |
| Phân bố quan hệ đều (NELL đều → +6,1 Hits@1; WN18RR lệch → +0,8) | NELL-995 đều | entropy chuẩn hoá **0,714**; top-2 = **42,4%** | ⚠ giống WN18RR |

Và một con số **chưa được đo trong bất kỳ tài liệu nào của dự án**, nhưng có ảnh hưởng
quyết định: quan hệ `reportsKPI` chiếm **34,0% toàn bộ cạnh** nhưng chỉ có **44 cặp
`(es, r)` phân biệt** — tức truy vấn `(AAA, reportsKPI, ?)` có tới **4.420 đáp án đúng**.

> Truy vấn đó **không phải bài toán query answering**, nó là liệt kê.
> Nếu đưa nguyên đồ thị vào huấn luyện, **một phần ba dữ liệu là nhiễu thoái hoá**,
> và MRR / Hits@k báo cáo ra sẽ không có ý nghĩa.

### 0.1 Ý kiến tổng thể

Cả 3 hướng đều đúng hướng, nhưng **thứ tự đang được hình dung là sai**.

Hướng (3) không phải bước cuối để đo kết quả — nó phải là **bước đầu tiên**, đóng vai trò
**cổng go/no-go** cho (1); và (1) phải đạt cổng trước khi động vào (2).

Nếu build step11–13 ngay bây giờ với reachability 46,8%, **trần Hits@1 đã bị khoá dưới
~47% bởi cấu trúc đồ thị, không phải bởi mô hình** — và sẽ mất khoảng 2 tháng để phát hiện
ra điều mà một script ~30 dòng nói cho biết trong 5 phút.

### 0.2 Vì sao đây lại là tin tốt

Câu chuyện luận văn mạnh hơn hẳn so với "áp SSRL vào KG ESG":

> *"Tôi chỉ ra rằng KG dựng bằng LLM từ báo cáo ESG vi phạm các tiền đề cấu trúc của
> path-based reasoning, định lượng được sự vi phạm đó bằng một bộ chỉ số
> reasoning-readiness, sửa theo nguyên tắc, và đo lại."*

Đây là đóng góp phương pháp, chưa ai làm trên dữ liệu ESG tiếng Việt — và nó **không phụ
thuộc vào việc SSRL có thắng hay không**, nên rủi ro đề tài thấp hơn nhiều.

---

## 1. Hướng (1) — Cải thiện cấu trúc KG

Xếp hạng theo **tác động đo được / chi phí**.

### 1.1 ⭐ Phân rã hub issuer bằng node kỳ báo cáo — tác động lớn nhất, 0đ, offline

**Vấn đề đo được:** node AAA có bậc **9.511**; `(AAA, reportsKPI, ?)` có **4.420** đáp án.

Bài báo (§IV-A) nói rõ action space phải được **truncate bằng một hằng số** — MINERVA
thường cắt còn 200–400 hành động. Lấy mẫu đều 400 trên 9.511 láng giềng ⇒ xác suất giữ được
đúng láng giềng dẫn tới bằng chứng ≈ **4%**. **Agent chết ở hop 1, trước khi kịp học gì.**

`TEMPORAL_KG_DESIGN.md` **P5** đề xuất sửa ở tầng trainer (factored action space:
chọn quan hệ trước, chọn đích sau). Đồng ý — nhưng **chưa đủ**. Nên sửa **cả ở tầng đồ thị**:

```
TRƯỚC:  AAA ──reportsKPI × 4420──▶ KPIObservation

SAU:    AAA ──hasReportingPeriod──▶ ReportingPeriod(AAA, 2023) ──reportsKPI──▶ KPIObservation
                                 └─▶ ReportingPeriod(AAA, 2022) ──reportsKPI──▶ ...
```

Lợi ích:

| | Tác dụng |
|---|---|
| **Hạ bậc** | 9.511 → ~12 node năm, mỗi node bậc ~800; kết hợp factored action space còn ~40 × 20 |
| **Thêm hop có ngữ nghĩa** | Hop thời gian — đúng thứ agent cần cho bài toán bitemporal (P8), không phải hop rác |
| **Tạo đường không qua siêu-hub** | `claim(2023) → period(2023) → conduct(2023)` — chính là thứ Q7(d) đang đo và đang kẹt ở **8,0%** |
| **Chi phí** | Dựng offline từ `temporal_metadata.valid_from` đã có sẵn trên 99,1% cạnh. Không LLM, không class mới nếu tái dùng `Report` / `publishesReport` |

> ⚠ **Rủi ro bắt buộc phải xử lý.** `step06_load_graph_to_neo4j.py` khoá node theo **array
> index**, và dossier của `step07` dùng `node_index` theo **vị trí**. Chèn node vào giữa sẽ
> phá toàn bộ dossier đã trả tiền (1.093 dossier, 3.461 lần gọi LLM). Phải làm theo kiểu
> **append-only** đúng như `step05c_link_standard_indicators.py` đã làm (assert prefix
> node/edge cũ không đổi).

### 1.2 ⭐ Đa công ty — không phải "thêm dữ liệu", mà là **thứ tạo ra hop**

Với **một** công ty, **mọi** đường claim→conduct đều có dạng `claim → AAA → conduct`.
Đó là 2 hop qua một hub duy nhất — về bản chất là **retrieval, không phải reasoning**.

> Không có multi-hop reasoning nào tồn tại trên đồ thị một công ty. Agent sẽ học đúng một
> quy tắc duy nhất: *"quay về AAA rồi toả ra"*.

Multi-hop chỉ có nghĩa khi có **cầu nối T1 liên công ty**: cùng `Standard`, cùng `Location`,
cùng `Authority`, cùng `StandardIndicator`, cùng `Product`. Ví dụ một đường đi thật sự xứng
đáng gọi là reasoning:

```
AAA ─claims─▶ "nhựa thân thiện môi trường" ─alignsWithIndicator─▶ TT96-6.1.1
                                                                      ▲
                                                       measuredUnder  │
     Penalty ◀─subjectToPenalty─ Công ty B ─reportsKPI─▶ KPIObservation
```

Đây là lý do **3–5 công ty cùng ngành là điều kiện cần**, không phải "mở rộng cho đẹp".
Lộ trình trong `TEMPORAL_KG_DESIGN.md` §6 đã đặt nó ở bước ③; đề nghị **nâng lên hàng bắt
buộc**, và chọn công ty theo tiêu chí **tối đa hoá số node T1 dùng chung** (đo trước bằng
tên chuẩn hoá, 0đ) chứ không phải theo vốn hoá hay độ sẵn có của báo cáo.

### 1.3 Nới trần đo Q7(d) — hệ thống đang **mù** với chính thiết kế của nó

Đây là một lỗi **phương pháp đo**, thấy rõ trong `src/step00_graph_quality_report.py`:
hằng `REFERENCE_CLASSES` loại `StandardIndicator` khỏi đường đi Q7(d) để giữ so sánh
before/after sạch (lý do chính đáng, ghi ở P5). **Nhưng hệ quả là:**

> Trục chỉ tiêu TT96/GRI — thứ được thiết kế **để làm cầu claim→conduct** — không bao giờ
> được tính vào chỉ số đo cầu claim→conduct.

Bằng chứng từ chính các snapshot trong `graph_output/quality/`:

| Snapshot | Q7(c) masked-answerable | **Q7(d) claim→conduct structural** | Q7(e) T2 bậc ≥2 |
|---|---|---|---|
| `baseline` (2026-07-04) | 25,1% | **8,0%** | 9,2% |
| `after-phase0` (2026-07-15) | 26,3% | **8,0%** | 10,1% |
| `20260726` (sau trục chỉ tiêu) | 34,9% | **8,0%** | 19,9% |

Q7(d) **y hệt nhau ở cả 3 mốc**, trong khi `measuredUnder` đạt 98,0% và
`alignsWithIndicator` đạt 98,6% masked-answerable.

**Sửa:** giữ Q7(d) hiện tại làm chỉ số bảo thủ, **thêm Q7(d′)** = cho phép đi qua node
reference nhưng **có trần bậc** (ví dụ ≤ 200) hoặc tính phí hop cao hơn. Báo cáo **cả hai**.
Nếu không, mọi cải tiến trên trục chỉ tiêu sẽ vô hình trên bảng số của luận văn.

### 1.4 Neo T2 (P3) — tiếp tục, đà đang tốt, nhưng đang neo sai phía

Q7(e) đã đi: 4,1% → 10,1% → **19,9%** (cổng đề ra: ≥ 30%).

| Class T2 | Node | Bậc ≥ 2 (2026-07-26) | Nhận xét |
|---|---:|---:|---|
| `Emission` | 24 | **100,0%** | ✅ trục chỉ tiêu ăn ngay |
| `Project` | 255 | 53,3% | ✅ |
| `Investment` | 282 | 50,4% | ✅ reify đúng từ đầu |
| `KPIObservation` | 4.906 | 16,9% | ⚠ đang lên (4,1 → 16,9) |
| `Initiative` | 495 | 14,7% | ⚠ |
| `Waste` | 15 | 13,3% | ⚠ |
| `MediaReport` | 91 | **9,9%** | ⛔ **phía conduct** |
| `Controversy` | 2 | **0,0%** | ⛔ **phía conduct** |
| `Penalty` | 4 | **0,0%** | ⛔ **phía conduct** |
| `ThirdPartyVerification` | 24 | **0,0%** | ⛔ **phía conduct** |

Bốn class đang ở 0–10% **đúng là bốn class phía conduct** — tức phía quan trọng nhất của
bài toán greenwashing. Hai neo rẻ nhất còn bỏ trống:

- `Penalty ──enforcedBy──▶ Authority` (nhãn cạnh đã có trong schema)
- `MediaReport ──mentionsFacility / locatedIn──▶ Facility | Location`

### 1.5 Phía conduct quá mỏng — đây là ràng buộc cứng

```
Controversy  2  │  Penalty  4  │  MediaReport  91  │  news-KPIObservation  108
                        ⇒ conduct pool = 124 node
```

Không mô hình reasoning nào cứu được một tập đáp án 124 phần tử. Đây chính là lý do trong
`aaa_crosscheck_stats.json`: **1.093 claim nhưng chỉ 748 claim có candidate (68,4%)**.
Phải tăng crawl news **trước khi** nói tới reasoning.

### 1.6 Việc vặt — rẻ, nên làm luôn

| Vấn đề | Số lượng | Nguồn |
|---|---:|---|
| Node tên hỏng OCR ("MÔI TRƢỜNG") | 51 | Q1 |
| `Location` trùng tên chuẩn hoá | 52 | Q3 |
| `Authority` trùng | 8 | Q3 |
| `StandardIndicator` trùng | 2 | Q3 |

Không ảnh hưởng lớn tới reasoning, nhưng ảnh hưởng tới Q1/Q3 và tới bảng số đem đi bảo vệ.

---

## 2. Hướng (2) — Triển khai multi-hop reasoning

### 2.1 Ba quan điểm kiến trúc quan trọng nhất

#### (a) Walker là RETRIEVER, không phải JUDGE

Đừng để agent RL xuất ra `supports` / `contradicts`. Toàn bộ framing của hệ thống
(`SYSTEM_DESIGN.md` §1.1: no ground truth, advisory only, §12: không bao giờ là verdict)
sẽ sụp nếu một mạng RL đưa ra phán quyết về một công ty có tên thật.

**Vai trò đúng của step11–13:** thay thế **tầng embedding retrieval** trong `step07` §6.1 —
đưa ra *candidate + đường đi có provenance*; LLM vẫn adjudicate, con người vẫn quyết định.

Lợi ích kép:
1. Giữ nguyên framing đạo đức đã cam kết.
2. **Có ground truth để đo** — cạnh bị che thì tồn tại hoặc không tồn tại (xem §3, tầng L1).

#### (b) Làm baseline multi-hop rẻ TRƯỚC khi làm RL

Với 14.399 cạnh (so với 272.115 của FB15K-237), RL rất dễ overfit và rất khó chứng minh
cải thiện vượt nhiễu.

Đề nghị: **metapath enumeration + logistic / PathRank scoring** — BFS ≤ 3 hop, đặc trưng là
chuỗi nhãn quan hệ. Mất ~1–2 ngày, chạy CPU, không hyperparameter, không GPU.

Nó cho:
- cột **"trước cải thiện" đúng nghĩa cho reasoning** (không chỉ là retrieval);
- và nếu SSRL không thắng nổi nó → **đó là một kết quả có giá trị**, không phải thất bại.

#### (c) Ba chỗ phải dùng CÙNG một mặt nạ thời gian

Nguyên tắc **P8** trong `TEMPORAL_KG_DESIGN.md` đã bắt đúng lỗ hổng này, và nó nghiêm trọng:

- Bài báo §IV-B sinh nhãn bằng **BFS trên toàn đồ thị, không mặt nạ**.
- Nếu RL / inference lại bị che theo thời gian ⇒ **SL đang dạy agent những đường mà RL bị cấm đi**.
- Đó chính xác là loại *distributional mismatch* mà cả bài báo được viết ra để chống lại (§I).

**Bắt buộc:** BFS sinh nhãn phải chạy trên **đồ thị con thời gian của từng truy vấn**
(chỉ cạnh có `valid_from ≤ t_query`, và nếu dùng trục knowledge-time: `recorded_at ≤ t_query`).

### 2.2 Ba script, và điểm khác biệt so với bài báo

| Script | Nội dung | Khác bài báo |
|---|---|---|
| `step11_export_kgc_dataset.py` | resolved graph → train/valid/test; cạnh đảo `_inv` **chỉ trong dataset** (P6, không ghi vào Neo4j); BFS sinh nhãn trên đồ thị con thời gian (P8); **lọc quan hệ thoái hoá** (§0) | Bài báo: KG tĩnh, không lọc quan hệ, BFS toàn đồ thị |
| `step12_train_ssrl.py` | Policy LSTM (eq. 1–3) → SL warm-up (cross-entropy, eq. 6) → RL (REINFORCE, eq. 8) | **Factored action space** cho hub (P5); **cân bằng nhãn theo quan hệ** (bài báo tự nhận là future work) |
| `step13_reason_and_serve.py` | Beam search → top-k candidate + `reasoning_path` **kèm provenance từng cạnh** (P7); nạp vào `step07` như một retrieval channel | Bài báo không có provenance path |

### 2.3 Định vị đóng góp khi bảo vệ

`TEMPORAL_KG_DESIGN.md` P8 đã tự cảnh báo đúng: **temporal action masking không mới** —
TITer / TimeTraveler (EMNLP 2021, arXiv:2109.04101) đã ràng buộc action space theo thời gian
trên TKG từ 2021. **Phải cite.**

Ba điểm thật sự đứng vững:

1. **Nhãn BFS dày của SSRL trong bối cảnh thời gian** — bài báo gốc chỉ làm trên KG tĩnh.
2. **Mặt nạ bitemporal 2 trục** (`recorded_at`, không chỉ `valid_from`) — với greenwashing
   đây là trục nhân quả đúng: *báo cáo 2021 không thể bị buộc mâu thuẫn bởi tin 2024.*
   TITer chỉ có event-time.
3. **Bộ chỉ số reasoning-readiness cho KG dựng bằng LLM** — §3 dưới đây. Theo tôi đây mới là
   đóng góp mạnh nhất và dễ bảo vệ nhất.

---

## 3. Hướng (3) — Metrics đánh giá trước/sau

> Phần được yêu cầu nhấn mạnh nhất.

### 3.0 Nguyên tắc thiết kế: tách 2 trục biến thiên

Nếu vừa đổi đồ thị vừa đổi mô hình rồi báo cáo một con số, sẽ không chứng minh được gì.

```
                  │ Retrieval-only │ Metapath  │ Pure RL   │ SSRL
                  │  (hiện tại)    │ baseline  │ (MINERVA) │ (SL+RL)
──────────────────┼────────────────┼───────────┼───────────┼─────────
 G0  hiện tại     │   ← "TRƯỚC"    │           │           │
 G1  + hub split  │                │           │           │
 G2  + đa công ty │                │           │           │  ← "SAU"
```

- **Cột** đo đóng góp của hướng **(2)** — cùng đồ thị, khác mô hình.
- **Hàng** đo đóng góp của hướng **(1)** — cùng mô hình, khác đồ thị.
- **Cùng một bộ metric cho mọi ô.**

---

### 3.1 Tầng L0 — Reasoning-readiness (offline, 0đ, **là CỔNG, chạy TRƯỚC khi train**)

Mở rộng `src/step00_graph_quality_report.py`. Đây là tầng quan trọng nhất vì nó rẻ và nó
**quyết định có nên tiêu tiền vào (2) hay không**.

| Mã | Chỉ số | Định nghĩa | **Hiện tại (đã đo)** | Cổng đề xuất |
|---|---|---|---:|---:|
| **R1** ⭐ | **Answer reachability** | Che 1 cạnh, đích còn tới được trong ≤ T hop? | **46,8%** (T=3) | ≥ 80% |
| **R1′** ⭐ | **Hub-free reachability** | R1 nhưng **cấm đi qua hub issuer** | **26,9%** | ≥ 50% |
| R2 | Trainable query count | Số triple sau khi loại quan hệ thoái hoá & quan hệ < 50 instance | *cần đo* | ≥ 5.000 |
| R3 | to-many ratio | % cặp `(es,r)` có \|E_all\| > 1 | **13,1%** | ≥ 30% |
| R4 | Relation entropy | H / log R; share top-2 | **0,714**; **42,4%** | ≥ 0,80; top-2 ≤ 30% |
| R5 | Action space p99 / max | bậc ra p99 / max | 13 / **9.511** | max ≤ 500 sau factoring |
| R6 | Label feasibility | % query sinh được nhãn BFS trong budget + thời gian | *cần đo* | ≥ 90% (đối chiếu Table V bài báo) |
| Q7(a–e) | *(đã có trong step00)* | median degree / % lá / masked-answerable / claim→conduct structural / T2 bậc≥2 | 1 · 75,7% · 34,9% · **8,0%** · 19,9% | d ≥ 25%; e ≥ 30% |
| **Q7(d′)** | *(mới, §1.3)* | như Q7(d) nhưng cho qua reference node **có trần bậc** | *chưa có* | báo cáo song song với d |

> **R1 nên là chỉ số headline.**
> Nó là **chặn trên cứng của Hits@1** cho mọi path-based reasoner — agent không thể đi tới
> nơi không có đường. Nó rẻ (~30 dòng, vài giây), không cần train, không cần LLM, và nó biến
> câu *"cải thiện cấu trúc KG"* từ định tính thành định lượng.
>
> **Cặp (R1, R1′) đo trước/sau mỗi thay đổi ở §1 chính là câu trả lời trực tiếp cho yêu cầu
> "metric đánh giá trước và sau cải thiện".**

Quan hệ với Q7(c) đã có: Q7(c) *masked-answerable* khắt khe hơn (yêu cầu **quan hệ** vẫn còn
trả lời được sau khi che), R1 lỏng hơn (chỉ hỏi **đích** còn tới được không). Hai chỉ số bổ
sung nhau — R1 là trần của path walker, Q7(c) là trần của query answering theo quan hệ.

---

### 3.2 Tầng L1 — Reasoning task (chuẩn văn liệu, **có ground truth miễn phí**)

Đây là chỗ **gỡ được ràng buộc "không có ground truth"** của cả hệ thống:

> **Link prediction trên cạnh bị che CÓ ground truth** — cạnh đó tồn tại hoặc không tồn tại.
> Không cần nhãn greenwashing để đo tầng này.

Điểm này rất đáng nhấn khi bảo vệ, vì `SYSTEM_DESIGN.md` §1.1 đã đóng khung toàn bộ dự án
trong "no labeled greenwashing dataset" — tầng L1 là mảnh duy nhất **thoát** được ràng buộc đó.

**Bộ chỉ số:**

- **MRR, Hits@1 / Hits@3 / Hits@10**, chế độ **filtered** → so sánh trực tiếp với Table III
  của bài báo.
- **Chia theo quan hệ** — bắt buộc, vì entropy chỉ 0,714. Đặc biệt báo cáo các quan hệ nghiệp
  vụ: `measuredUnder`, `observedAtFacility`, `alignsWithIndicator`, `verifiedBy`.
- **Chia to-one / to-many** (đối chiếu Fig. 5 bài báo) — nơi SSRL được kỳ vọng lãi nhất.
- **Temporal split** song song với random split: train `recorded_at ≤ T`, test sau T. Đây là
  thứ biến bài toán thành TKG forecasting thật sự, chứ không chỉ KGC.

**Ngưỡng support tối thiểu — phải nói thẳng trong báo cáo:**

| Quan hệ | Số cạnh | Đánh giá được? |
|---|---:|---|
| `contradictedBy` | **2** | ⛔ không |
| `subjectToPenalty` | **4** | ⛔ không |
| `verifiedBy` | 39 | ⚠ biên |
| `measuredUnder` | 641 | ✅ |
| `alignsWithIndicator` | 636 | ✅ |
| `locatedIn` | 743 | ✅ |

Chỉ báo cáo quan hệ có **≥ 50 test triple**. Việc `contradictedBy` không đánh giá được là một
lỗ hổng sẽ bị hỏi ở buổi bảo vệ — **nói trước còn hơn bị bắt**.

> ⚠ **Kỷ luật thống kê — với quy mô này thì bắt buộc.**
> Bài báo báo cáo cải thiện **+0,6 đến +1,2 MRR**. Với test set ~1–2k triple, khoảng đó **nằm
> trong nhiễu**. Yêu cầu tối thiểu:
> - **≥ 3 seed**, báo cáo **mean ± std**;
> - **paired bootstrap / permutation test** cho mọi so sánh.
>
> Một bảng không có std sẽ bị đánh ngay ở buổi bảo vệ.

---

### 3.3 Tầng L2 — Downstream: reasoning có làm hệ thống thật tốt lên không?

Tầng trả lời câu *"so what?"*, và nó **cắm thẳng vào `src/step10_evaluate.py` đã có**.
Các con số "TRƯỚC" đã nằm sẵn trong `graph_output/crosscheck/aaa_crosscheck_stats.json`:

| Chỉ số | Nguồn "trước" đã có | **Hiện tại** | Ý nghĩa |
|---|---|---:|---|
| **Claim có candidate** | `aaa_crosscheck_stats.json` | **748 / 1.093 = 68,4%** | reasoning phải nâng con số này |
| **Evidence Recall@k / MRR** | `config/evaluation/ablation_cases.json` (30 case) | baseline 73,3% vs LLM 76,7% agreement | walker vs embedding retrieval, **cùng k** |
| **LLM call / linking edge** ⭐ | `aaa_crosscheck_stats.json` | **3.461 pair → 152 edge = 22,8 call/edge** | Gemini đang bị chặn billing — chỉ số tiền bạc này rất thuyết phục |
| **Bằng chứng mới phát hiện** | — | 0 (baseline) | # link walker tìm được mà embedding **không** đề xuất + precision thủ công trên mẫu |
| **Path auditability** (P7) | — | — | % path mà **mọi** cạnh truy được về câu nguồn → mục tiêu **100%** |
| **Path plausibility** | — | — | 50 path, ≥ 2 người chấm 3 mức, báo cáo **Cohen's / Fleiss' κ** |

> **`22,8 LLM call / edge` là chỉ số "bán được" nhất của toàn bộ luận văn.**
> Nếu walker rank tốt hơn, có thể hạ `--top-k` từ 8 xuống 3 mà giữ nguyên số edge
> ⇒ **giảm ~60% chi phí LLM**. Đó là cải thiện đo được, **có đơn vị là tiền**, và **không cần
> ground truth greenwashing**. Với một dự án đang bị billing-block, đây là lập luận mạnh.

---

### 3.4 Tầng L3 — Ablation (theo đúng khung bài báo)

1. **Số epoch SL: 0 → N** (row 0 = pure RL) → heatmap Hits@k / MRR, đối chiếu **Fig. 6**.
   Bài báo cho thấy **SL quá tay làm GIẢM hiệu năng** (FB15K-237 tốt nhất ở 3 epoch, WN18RR ở
   2) — tái lập được đường cong này là bằng chứng hiểu cơ chế, không phải chạy code người khác.
2. **Có / không temporal masking (P8)** — đây là claim novelty; không đo thì không có đóng góp.
3. **Có / không factored action space (P5)** trên hub 9.511.
4. **Từng thay đổi cấu trúc ở §1** (hub split · neo conduct · đa công ty) × cùng bộ L1
   → chính là bảng **"trước / sau cải thiện cấu trúc KG"**.
5. **SL strategy của bài báo vs DeepPath-style** (§V-E, Table VI) — nếu còn thời gian.

---

## 4. Lộ trình đề xuất

```
Tuần 1     L0 (R1–R6 + Q7d′) trên G0                → CỔNG. Rẻ nhất, quyết định nhiều nhất.
Tuần 2–3   §1.1 hub split + §1.4 neo phía conduct   → đo lại L0.  R1 có lên ≥ 80% không?
Tuần 4–6   §1.2 đa công ty (3–5 cty cùng ngành)     → đo lại L0.  R1′ có lên ≥ 50% không?

           ══════ nếu R1 < 70% ở mốc này: DỪNG, KHÔNG build step11–13 ══════

Tuần 7     Metapath baseline + dựng khung metric L1 → cột "trước" của reasoning
Tuần 8+    step11 / step12 / step13 (SSRL)          → điền nốt bảng 2 chiều, chạy L2 / L3
```

Chi phí: Tuần 1–3 **0đ** (offline, không LLM). Tuần 4–6 tốn LLM cho pipeline công ty mới.
Tuần 7 **0đ**. Tuần 8+ tốn GPU chứ không tốn LLM.

---

## 5. Tóm tắt ý kiến

**Hướng (1) — cải thiện cấu trúc KG:** đúng và **cấp thiết hơn dự kiến**. Nhưng đòn mạnh nhất
chưa nằm trong danh sách hiện tại:
- **phân rã hub 9.511 bằng node kỳ báo cáo** (§1.1) — 0đ, hạ bậc ~10×, thêm hop thời gian có nghĩa;
- **đa công ty là điều kiện tồn tại của multi-hop** (§1.2), không phải mở rộng cho đẹp;
- đang **mù với Q7(d)** do loại reference class — cần **Q7(d′)** (§1.3);
- neo T2 đang bỏ trống **đúng 4 class phía conduct** (§1.4).

**Hướng (2) — multi-hop reasoning:** khả thi về kỹ thuật, nhưng:
- **walker phải là retriever, không phải judge** — nếu không, framing advisory của cả hệ thống sụp;
- nên có **baseline metapath rẻ trước** khi đổ công vào RL, để de-risk;
- **mặt nạ thời gian phải áp đủ cả 3 chỗ** (P8) — doc nội bộ đã bắt đúng lỗi này của bài báo.

**Hướng (3) — metrics:** đây mới là phần nên làm **trước**:
- **L0 / R1 (reachability 46,8% → cổng 80%)** là chỉ số trước-sau tốt nhất cho hướng (1);
- **L1 MRR / Hits@k filtered, có std và bootstrap test** là chuẩn văn liệu cho hướng (2);
- **L2 với `22,8 LLM call/edge`** là chỉ số chứng minh giá trị thực tế, đơn vị là tiền;
- và điểm mấu chốt: **link prediction trên cạnh bị che cho ground truth miễn phí** — nó gỡ
  đúng nút thắt *"không có nhãn greenwashing"* mà cả hệ thống đang bị ràng buộc.

---

## Phụ lục A — Cách tái lập các số đo

Các số trong tài liệu này đến từ 2 nguồn:

**(a) Đã có sẵn trong repo** — không cần chạy lại:

```bash
graph_output/quality/quality_report_baseline.json        # Q1–Q8, build 2026-07-04
graph_output/quality/quality_report_after-phase0.json    # Q1–Q8, build 2026-07-15
graph_output/quality/quality_report_20260726.json        # Q1–Q8, build 2026-07-26 (mới nhất)
graph_output/crosscheck/aaa_crosscheck_stats.json        # 1093 claim, 748 có candidate, 3461 pair, 152 edge
graph_output/resolved/resolved_graph.json                # 10.423 node / 14.399 cạnh
```

**(b) Đo mới cho tài liệu này** (R1, R1′, R3, R4, R5, phân bố quan hệ) — script offline, ~5
giây, không LLM, không Neo4j. Lược đồ cạnh trong `resolved_graph.json` là
`{subject, predicate, object, temporal_metadata}` (chỉ số node là **array index**):

```python
import json, math, random, collections, statistics

G = json.load(open('graph_output/resolved/resolved_graph.json', encoding='utf-8'))
nodes, edges = G['nodes'], G['edges']

# R4 — phân bố quan hệ + entropy chuẩn hoá
lab = collections.Counter(e['predicate'] for e in edges); tot = sum(lab.values())
H = -sum((v/tot) * math.log(v/tot) for v in lab.values())
print('entropy =', H / math.log(len(lab)))

# R3 — to-many ratio
key = collections.defaultdict(set)
for e in edges:
    key[(e['subject'], e['predicate'])].add(e['object'])
many = sum(1 for v in key.values() if len(v) > 1)
print('to-many % =', 100 * many / len(key))

# R5 — bậc
deg = collections.Counter()
for e in edges:
    deg[e['subject']] += 1; deg[e['object']] += 1

# R1 / R1' — che 1 cạnh, đích còn tới được trong <= 3 hop?
adj = collections.defaultdict(list)
for i, e in enumerate(edges):
    adj[e['subject']].append((e['object'], i)); adj[e['object']].append((e['subject'], i))
HUB = max(range(len(nodes)), key=lambda i: deg.get(i, 0))     # bỏ HUB khỏi seen ⇒ R1'

def reach(s, t, ban, maxh=3, banned=()):
    frontier, seen = {s}, {s, *banned}
    for _ in range(maxh):
        nxt = set()
        for u in frontier:
            for v, ei in adj[u]:
                if ei == ban or v in seen: continue
                if v == t: return True
                seen.add(v); nxt.add(v)
        frontier = nxt
        if not frontier: return False
    return False

random.seed(0)
samp = random.sample(range(len(edges)), 800)
print('R1  =', 100 * sum(reach(edges[i]['subject'], edges[i]['object'], i) for i in samp) / 800)
print("R1' =", 100 * sum(reach(edges[i]['subject'], edges[i]['object'], i, banned=(HUB,)) for i in samp) / 800)
```

Mẫu 800 cạnh lấy **đều trên toàn bộ cạnh** (nên có ~34% là `reportsKPI`, phản ánh đúng độ khó
thực tế). `seed=0` để tái lập được.

---

## Phụ lục B — Bảng số liệu gốc

### B.1 Phân bố quan hệ (top 12 / 43 quan hệ, tổng 14.399 cạnh)

| Quan hệ | Số cạnh | % | Cặp `(es,r)` | to-many % |
|---|---:|---:|---:|---:|
| `reportsKPI` | 4.890 | **34,0%** | **44** | 75,0% |
| `claims` | 1.215 | 8,4% | 20 | 65,0% |
| `setsGoal` | 784 | 5,4% | 19 | 47,4% |
| `locatedIn` | 743 | 5,2% | 356 | 18,8% |
| `worksAt` | 742 | 5,2% | 194 | 28,9% |
| `measuredUnder` | 641 | 4,5% | 641 | 0,0% |
| `alignsWithIndicator` | 636 | 4,4% | 621 | 2,4% |
| `takesPartIn` | 553 | 3,8% | 27 | 33,3% |
| `ownsFacility` | 424 | 2,9% | — | — |
| `producedBy` | 320 | 2,2% | — | — |
| `adoptsStandard` | 315 | 2,2% | — | — |
| `subjectToRegulation` | 306 | 2,1% | — | — |

- Entropy chuẩn hoá **0,714** (R = 43 quan hệ) · top-2 = **42,4%** · top-5 = **58,2%**
- `(es, r)` phân biệt = **3.571** · to-many = **13,1%** · mean \|E_all\| = 3,63 · **max = 4.420**

> Chú ý `reportsKPI`: 4.890 cạnh nhưng chỉ 44 cặp `(es,r)` ⇒ trung bình **111 đáp án/truy vấn**,
> đỉnh **4.420**. Đây là quan hệ thoái hoá, phải loại khỏi tập huấn luyện/đánh giá (§0).

### B.2 Thống kê bậc

```
mean = 2,76   median = 1   p90 = 2   p99 = 13   max = 9.511
node bậc 0 = 1      node bậc 1 = 7.376  (70,8%)
```

### B.3 Reachability sau khi che cạnh (mẫu 800, seed 0, T = 3)

| | Tỷ lệ | Đối chiếu |
|---|---:|---|
| **R1** — đích tới được ≤ 3 hop | **46,8%** | FB15K-237 trong bài báo: **99,8%** |
| **R1′** — không đi qua hub issuer | **26,9%** | ← đây mới là "multi-hop thật sự" |

### B.4 Diễn tiến Q7 qua 3 lần build

| | baseline<br>(2026-07-04) | after-phase0<br>(2026-07-15) | 20260726<br>(mới nhất) |
|---|---:|---:|---:|
| Node / Cạnh | 10.573 / 13.008 | 10.362 / 13.047 | 10.413 / 13.836 |
| Q7(a) median degree | 1 | 1 | 1 |
| Q7(b) % lá | 83,2% | 82,2% | **75,7%** |
| Q7(c) masked-answerable | 25,1% | 26,3% | **34,9%** |
| **Q7(d) claim→conduct structural** | **8,0%** | **8,0%** | **8,0%** |
| Q7(e) T2 bậc ≥ 2 | 9,2% | 10,1% | **19,9%** |
| Hub issuer | 9.564 | 9.517 | 9.511 |
| Q2 vi phạm bất biến thời gian | 1.098 | 1 | 1 |

### B.5 Trạng thái cross-check (`aaa_crosscheck_stats.json`)

```
claims                        1.093
conduct pool                    124   (MediaReport 16 · KPIObservation 108)
claims có candidate               748   (68,4%)
candidate pairs                 3.461   (avg 3,17 / claim)
LLM adjudications               3.461   (openai, 0 failure)
linking edges written             152   ⇒ 22,8 LLM call / edge
assessments      appears_supported 70 · appears_contradicted 22 · unverified 1.001
params           top_k=8 · window_before=1 · window_after=50
```

---

## Tài liệu tham khảo

- Ma, Y., Burns, O. et al. — *Knowledge Graph Reasoning with Self-supervised Reinforcement
  Learning*, arXiv:2405.13640v2 (IEEE 2025). **Bài báo nền của đề xuất này.**
- Sun, H. et al. — *TimeTraveler: RL for Temporal Knowledge Graph Forecasting*, EMNLP 2021,
  arXiv:2109.04101. **Bắt buộc cite khi nói về temporal action masking.**
- Das, R. et al. — *MINERVA* · Lin, X.V. et al. — *MultiHopKG* (hai baseline RL của bài báo).
- Xiong, W. et al. — *DeepPath* (SSRL kiểu tổng quát, đối chứng ở §V-E bài báo).
- Zaveri, A. et al. — *Quality Assessment for Linked Data: A Survey* (khung Q1–Q8).
- Rasmussen, P. et al. — *Zep: A Temporal KG Architecture for Agent Memory*, arXiv:2501.13956.
- Nội bộ: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) · [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md)
  · [`STANDARD_INDICATOR_AXIS.md`](./STANDARD_INDICATOR_AXIS.md)
  · [`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md)
  · `SSRL_REASONING_LAYER.md` *(được tham chiếu khắp nơi nhưng **chưa tồn tại** — cần viết)*

---

*Tài liệu tư vấn, không phải đặc tả. Mọi số "hiện trạng" đo trên
`graph_output/resolved/resolved_graph.json` build **2026-07-26** (10.423 node / 14.399 cạnh).
Khi rebuild đồ thị, đo lại toàn bộ Phụ lục B trước khi trích dẫn.*
