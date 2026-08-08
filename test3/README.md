# So sánh Graph-RAG với RAG thường

Cùng một câu bằng chứng đưa vào hai hệ, mỗi hệ trả về một câu claim và một nhãn quan hệ,
rồi đo xem hai kết quả khác nhau ra sao.

```
                    ┌─→ [A] Graph-RAG  : truy xuất trên resolved_graph.json ─┐
evidence_text ──────┤                                                        ├─→ CÙNG reranker ─→ so sánh
                    └─→ [B] RAG thường : BM25 + dense + RRF (ragtest/) ──────┘
                                              ↓
                        CÙNG MỘT Adjudicator của step07 chấm nhãn cho cả hai
                              supports | contradicts | irrelevant
```

Hai chữ **CÙNG** viết hoa ở trên là toàn bộ tính hợp lệ của phép so. Xem mục 4.

---

## 1. Chạy thế nào

```bash
# kiểm tra offline trước (không tốn tiền, không cần mạng)
python test3/test_compare_metrics.py
python test3/test_graph_rag_arm.py

# chạy thử 10 dòng
python test3/compare_graphrag_vs_rag.py --limit 10

# chạy đủ 220 dòng  (~2,5-3 tiếng — độ trễ LLM ở bước rerank là nút thắt)
python test3/compare_graphrag_vs_rag.py
```

Kết quả ghi vào `test3/`:

| file | nội dung |
|---|---|
| **`graphrag_vs_rag.xlsx`** | **bảng Excel** — mỗi dòng một câu bằng chứng, claim hai bên, nhãn hai bên, điểm giống nhau |
| `graphrag_vs_rag.csv` | y hệt, dạng CSV (UTF-8 BOM, Excel Windows đọc đúng tiếng Việt) |
| `graphrag_vs_rag.json` | y hệt, kèm phần `summary` đã tổng hợp |
| **`graphrag_vs_rag_report.md`** | **báo cáo đọc được** — các bảng số kèm cách đọc và giới hạn |
| `graphrag_vs_rag_rag_queries.jsonl` | log đầy đủ của `ragtest/query.py`, mỗi dòng một truy vấn |

Cờ hay dùng: `--limit N` · `--no-rerank` (tắt rerank ở **cả hai** nhánh) ·
`--nc-sample N` (đối chứng âm chạy trên N dòng, mặc định 60; `0` = tất cả) ·
`--graph-top-k` / `--top-k` / `--pool` · `--model` · `--rate-limit` (mặc định 120 lệnh/phút).

**Chi phí:** mỗi dòng ≈ 2 lệnh rerank + 2 lệnh chấm nhãn, cộng 2 lệnh đối chứng âm cho
60 dòng đầu. 220 dòng ≈ **1.000 lệnh gọi LLM**. Vector nhúng có cache nên chạy lại rẻ hơn.

---

## 2. Các file code

| file | việc của nó |
|---|---|
| `graph_rag_arm.py` | **nhánh A** — truy xuất evidence → claim trên đồ thị |
| `compare_metrics.py` | **dụng cụ đo** — word matching, cosine, kappa, McNemar, bootstrap CI |
| `compare_graphrag_vs_rag.py` | **driver** — chạy hai nhánh, chấm nhãn, tính số, xuất Excel + báo cáo |
| `test_graph_rag_arm.py` | test offline cho nhánh A (20 khẳng định) |
| `test_compare_metrics.py` | test offline cho dụng cụ đo (46 khẳng định) |

Driver dùng lại 3 hàm từ `test2/build_evidence_claim_sheet.py` (dựng câu query, tra ngược
`evidence_text` → node). Import chứ không chép. **Đừng xoá `test2/`.**

---

## 3. Hai nhánh làm gì

### Nhánh A — Graph-RAG (`graph_rag_arm.py`)

Đi trên đồ thị, đúng cơ chế `step07` (`claims_vs_conduct.py:586-660`) nhưng chạy **ngược
chiều** (step07 đi claim → evidence; ở đây đi evidence → claim). Hai tầng:

**Tầng 1 — trục chỉ tiêu, nối cấu trúc 2 bước:**
```
evidence --measuredUnder--> StandardIndicator <--alignsWithIndicator-- claim
```
Tầng này **bỏ qua** điều kiện trùng chữ — đây mới là thứ đồ thị làm được mà BM25/vector
không làm được: claim *"giảm phát thải"* và KPI *"12.450 tCO2e"* không chung chữ nào
nhưng cùng treo dưới một chỉ tiêu. Điểm cộng `INDICATOR_BOOST = 1000` để cặp nối qua chỉ
tiêu luôn xếp trên cặp chỉ trùng chữ.

**Tầng 2 — trùng token chủ đề tiếng Việt** (ngưỡng ≥ 2 token chung) + cửa sổ thời gian.

Claim chỉ lấy trong phạm vi **cùng doanh nghiệp** (`Organization --claims--> SustainabilityClaim`).

> ⚠️ **Trên tập 220 câu này, tầng 1 đóng góp 0.** Xem mục 5 — đây là phát hiện quan
> trọng nhất của cả bài, không phải lỗi cài đặt.

### Nhánh B — RAG thường (`ragtest/`)

Câu query = `evidence_text` + `description` + `valid_from` (ghép ở `test2/`, bỏ phần
trùng lặp). Rồi BM25 + dense, hợp nhất bằng RRF.

### Bước chung của cả hai nhánh

Ứng viên của **cả hai** nhánh đi qua **cùng một `LLMReranker`**, rồi claim top-1 của mỗi
bên được **cùng một `Adjudicator` của step07** chấm nhãn (cùng prompt `ADJUDICATE_SYSTEM`,
cùng model, `temperature=0`).

---

## 4. Vì sao phải cân bằng — chỗ này từng sai

Bản đầu tiên của tôi **sai**, và người dùng phát hiện đúng: nhánh graph lúc đó truy vấn
đơn giản hơn hẳn nhánh RAG. Hai nhánh khác nhau ở **3 điểm** chứ không phải 1:

| | nhánh A (cũ) | nhánh B (cũ) |
|---|---|---|
| sinh ứng viên | trùng token — đếm giao, **không IDF**, không chuẩn hoá độ dài | BM25 (có IDF) |
| kênh ngữ nghĩa | ❌ | ✅ dense 1536 chiều |
| LLM rerank | ❌ | ✅ |

Chỉ cần một trong ba lệch là chênh lệch đo ra **không quy được cho đồ thị** — nó có thể
chỉ là *"reranker thì tốt hơn"*.

Chuẩn phương pháp trong tài liệu cũng nói vậy. Bài đánh giá hệ thống *RAG vs. GraphRAG*
([arXiv 2502.11371](https://arxiv.org/html/2502.11371v3)) đánh giá hai hệ **dưới cùng cấu
hình khi có thể** và **cân bằng ngân sách chính**; họ còn giảm tham số GraphRAG và chuẩn
hoá prompt về một bản chung — sau khi cân bằng thì GraphRAG *tăng* điểm, và chính điều đó
chứng minh phép so công bằng. Họ cũng **tách truy xuất khỏi sinh câu**: lưu bằng chứng mỗi
hệ truy ra rồi dùng **một script sinh chung** (ở đây là `Adjudicator` dùng chung).

[VentureBeat](https://venturebeat.com/orchestration/stop-graphing-everything-when-graphrag-actually-beats-vector-rag)
nói thẳng cái bẫy: *"nhiều thất bại truy xuất bắt nguồn từ cắt chunk sai, thiếu metadata,
viết lại truy vấn kém, hoặc **không có reranking** — không cái nào đồ thị sửa được."*

**Đã sửa:** nhánh graph giờ dùng **cùng reranker**. Khác biệt duy nhất còn lại là **bộ
sinh ứng viên**. Việc sửa này không hình thức — chạy thử cho thấy reranker **đổi claim
top-1 của nhánh graph ở 3/4 dòng**.

Hai cột `graph_claim_norerank` và `graph_rerank_changed` trong Excel giữ lại kết quả
*trước* rerank, để đo riêng đóng góp của reranker cho nhánh graph.

> **Dự báo cần biết trước:** cùng bài arXiv 2502.11371 ghi nhận RAG thường **vẫn thắng**
> ở câu hỏi một bước, thiên chi tiết, *kể cả khi GraphRAG có rerank*. Bài toán ở đây —
> một câu bằng chứng đi tìm một câu claim khớp — chính là dạng đó. Nếu RAG thắng, đó là
> kết quả **đúng như lý thuyết dự báo**, không phải bằng chứng đồ thị vô dụng.

---

## 5. Phát hiện lớn nhất: tầng nối cấu trúc đang chết

Chạy trên 220 câu: **158 kết quả, 100% từ tầng 2 (trùng token). Tầng 1 đóng góp 0.**
Truy tới tận gốc:

| lớp bằng chứng | số node | vì sao không nối được qua chỉ tiêu |
|---|---|---|
| MediaReport | 53 | lớp này **không mang** cạnh `measuredUnder` theo schema |
| KPIObservation (news) | 82 | **0/82** có cạnh đó — 1.309 cạnh `measuredUnder` nằm ở KPI phía **báo cáo** |
| Penalty | 85 | có, nhưng **cả 85 trỏ vào đúng 1 chỉ tiêu**: *"Tổng tiền phạt vi phạm môi trường"* — mà **0 claim** nào gắn vào đó |

Dòng cuối có lý do rất người: **không doanh nghiệp nào tuyên bố "chúng tôi bị phạt vi
phạm môi trường"**, nên đầu claim của chỉ tiêu đó trống rỗng.

Bản thân trục chỉ tiêu **lành**: 292/464 claim có `alignsWithIndicator`, 95 chỉ tiêu có
claim, 24 chỉ tiêu được cả hai loại cạnh trỏ tới. Vấn đề là **hai nửa không gặp nhau ở
đúng tập bằng chứng này**.

**Hệ quả khi đọc số:** nhánh A ở đây thực chất là *trùng token tiếng Việt + khoanh doanh
nghiệp + cửa sổ thời gian + rerank*, **không phải** Graph-RAG đúng nghĩa. Báo cáo tự sinh
cũng in cảnh báo này ở mục 1b.

---

## 6. Đọc các con số thế nào

### Mục 1 — Độ phủ (trục X)
Nhánh B gần như luôn 100% (BM25 luôn trả về gì đó); nhánh A thấp hơn vì chỉ nối khi có
quan hệ thật trên đồ thị.

> **Coverage một mình không nói lên chất lượng.** Nhánh trả nhiều hơn có thể vì tìm ra
> bằng chứng thật, cũng có thể chỉ vì **dễ dãi hơn** — hai giả thuyết cho ra cùng một con
> số. Phải đọc kèm mục 4 của báo cáo (đối chứng âm).

### Mục 2 — Hai câu claim giống nhau đến đâu

| metric | đo gì | lưu ý |
|---|---|---|
| **token F1** | trùng nhau bao nhiêu **từ** | có hướng: precision ≠ recall khi hai câu dài ngắn khác nhau |
| **Jaccard** | \|giao\|/\|hợp\| trên tập từ | đối xứng, **không nhìn thứ tự** |
| **ROUGE-L** | chuỗi con chung dài nhất | **có nhìn thứ tự từ** |
| **cosine** | giống nhau về **ngữ nghĩa** | bắt được cặp khác chữ nhưng cùng ý |

Giữ cả Jaccard lẫn ROUGE-L là có lý do: hai câu đảo hết trật tự từ vẫn cho Jaccard = 1
nhưng ROUGE-L < 1. Tiếng Việt phụ thuộc trật tự từ nhiều nên khác biệt đó đáng giữ.

Mỗi số kèm **khoảng tin cậy 95%** (bootstrap có seed — chạy lại ra đúng khoảng đó).

Giống nhau **cao** = hai hệ hội tụ cùng một câu. **Thấp** = đi hai hướng khác hẳn. Bản
thân con số **không nói hệ nào đúng hơn**.

### Mục 3 — Nhãn quan hệ

- **Ma trận nhầm lẫn 3×3**: hàng = nhãn nhánh graph, cột = nhãn nhánh rag.
- **Đồng thuận thô**: % số dòng hai bên cùng nhãn.
- **Cohen's kappa**: đồng thuận **đã trừ may rủi**. Quan trọng hơn đồng thuận thô — hai
  hệ cùng trả `irrelevant` cho 90% số dòng cho đồng thuận 0,9 dù chẳng bên nào phân biệt
  được gì. Kappa = `None` nghĩa là **không xác định** (một nhánh chỉ ra một nhãn duy
  nhất), **không phải** bằng 0.
- **McNemar**: kiểm định ghép cặp cho câu hỏi *"nhánh nào hay kết luận khác `irrelevant`
  hơn"* — tức **nhánh nào dễ dãi hơn**. Chỉ hai ô lệch `b`, `c` mang thông tin. Hệ quả:
  **lực kiểm định phụ thuộc `b+c`, không phụ thuộc 220**. Cần `b+c ≳ 25`; nếu `b+c` bằng
  0–1 thì kết luận đúng là *"hai hệ không khác nhau ở điểm này"*, chứ không phải "thua".

### Mục 4 — Đối chứng âm (trục Y) ⚠️ đừng tắt

Ghép mỗi câu bằng chứng với một claim **ngẫu nhiên** cùng doanh nghiệp, cho cùng
Adjudicator chấm. Cặp ngẫu nhiên đúng ra phải bị chấm `irrelevant` — tỷ lệ làm đúng gọi
là **specificity**. Cách đọc:

| độ phủ | specificity | kết luận |
|---|---|---|
| ↑ | ≈ giữ nguyên hoặc ↑ | ✅ cải thiện thật |
| ↑ | ↓ mạnh | ⚠️ **bẫy dễ dãi** — báo cáo như đánh đổi kèm số, không gọi là cải thiện |
| ≈ | ↑ | ⚠️ nghiêm khắc hơn nhưng không tìm thêm được gì |
| ↓ | ↓ | ❌ tệ hơn cả hai trục |

---

## 7. Những gì bộ số này **không** nói được

**Không có ground truth.** `sheet_A.json` / `sheet_B.json` đều 220/220 `relation = null` —
chưa ai chấm. Nên tất cả ở đây đo **hai hệ khác nhau ra sao**, tuyệt đối không đo được
**hệ nào đúng hơn**. Muốn có accuracy thì phải chấm nhãn tay trước.

Repo cấm hẳn một nhóm metric vì **đã thử và chết** (`docs/EVALUATION_WITHOUT_LABELS.md`
§8) — không cái nào xuất hiện ở đây: accuracy/precision/recall/F1 đối với sự thật, link
precision, recall vét cạn, kappa người–người, kappa người–LLM, ECE/Brier trên
`confidence`, RAGAS Context Recall, điểm greenwashing cấp doanh nghiệp.

Giới hạn khác:

- **Cặp ngẫu nhiên ở mục 4 có thể tình cờ liên quan thật**, nên specificity bị ước lượng
  **thấp hơn** thực tế — lệch về phía bất lợi cho hệ, tức là an toàn, nhưng phải nói ra.
- Nhánh A khoanh claim theo issuer, nhánh B lọc theo ticker. **Cùng phạm vi**, so được.
- Dossier `graph_output/crosscheck/` chỉ có **21 evidence link / 464 claim**, 20/21 thuộc
  ACG. Vì vậy nhánh A **truy xuất lại từ đồ thị**, không đọc dossier — đọc dossier chỉ
  phủ được 21 dòng.
- `sheet_A` sinh lúc 14:48 còn dossier chạy lại lúc 20:40; join theo `pair_id` chỉ còn
  **15/220**. Lý do nữa để không dùng dossier. `sheet_A` ở đây **chỉ là kho câu bằng
  chứng** — không dùng nhãn, không dùng `pair_id` để nối.

---

## 8. Cần biết trước khi chạy

- **Endpoint chấm nhãn**: mặc định lấy `OPENAI_BASE_URL` trong `.env` (cùng host GLM mà
  ragtest dùng), model `glm-5.2`. Nếu để step07 mặc định gọi OpenAI thật thì key trong
  `.env` bị từ chối và **toàn bộ nhãn rỗng mà không báo lỗi rõ** — đã gặp đúng lỗi này
  lần chạy đầu, nay đã xử lý.
- **Ô nhãn rỗng ≠ `irrelevant`.** Rỗng = nhánh đó **không truy xuất được claim nào**;
  `irrelevant` = có claim nhưng bộ chấm phán không liên quan. Gộp hai thứ này lại sẽ
  khiến một nhánh phủ kém trông như một nhánh nghiêm khắc.
- **`test2/` đang có 3 test fail** (không ảnh hưởng `test3/`): phần `description` lấy
  `title` bù và phần dedup chuỗi con trong `build_query` đã bị gỡ khỏi module nhưng test
  vẫn còn giữ. Câu query ra **giống hệt nhau** ở cả hai phiên bản nên lần chạy này không
  bị ảnh hưởng.
