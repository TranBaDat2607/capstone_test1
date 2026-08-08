# Graph-RAG vs RAG thường

- Số câu bằng chứng: **220**
- Model chấm nhãn (dùng chung cho cả hai nhánh): `glm-5.2`
- **Không có ground truth** — sheet_A/sheet_B đều chưa ai chấm. Bảng dưới đo hai hệ KHÁC NHAU ra sao, không đo hệ nào ĐÚNG hơn.

## 1. Độ phủ (trục X — năng suất)

| nhánh | ra được claim | tỷ lệ |
|---|---|---|
| graph | 158/220 | 71.8% |
| rag | 220/220 | 100.0% |

> Coverage một mình KHÔNG nói lên chất lượng: nhánh trả nhiều hơn có thể vì tìm được bằng chứng thật, cũng có thể chỉ vì dễ dãi hơn. Đọc kèm mục 4.

### 1a. Hai nhánh đã được cân bằng thế nào

| | nhánh A (graph) | nhánh B (rag) |
|---|---|---|
| sinh ứng viên | đồ thị: trục chỉ tiêu + trùng token | BM25 + dense, hợp nhất RRF |
| LLM rerank | ✅ CÙNG reranker | ✅ có |
| chấm nhãn | ✅ cùng Adjudicator | ✅ cùng Adjudicator |

> Cân bằng reranker là bắt buộc. Nếu một nhánh có reranker còn nhánh kia không, chênh lệch đo được là chênh lệch **của reranker**, không phải của cơ chế truy xuất — đúng cái bẫy mà bài đánh giá hệ thống RAG vs GraphRAG (arXiv 2502.11371) xử lý bằng cách chuẩn hoá cấu hình và cân bằng ngân sách giữa hai hệ.

- Reranker đổi claim top-1 của nhánh graph ở **92** dòng (0 nghĩa là đồ thị hầu như chỉ trả về 1 ứng viên, reranker không có gì để sắp).

### 1b. Nhánh graph dùng tầng nào

- tầng **trục chỉ tiêu** (nối cấu trúc 2 bước): **0**
- tầng **trùng token** chủ đề tiếng Việt: **158**

> ⚠️ **Tầng nối cấu trúc đóng góp 0.** Trên tập bằng chứng này, thứ làm nên chữ "Graph" trong Graph-RAG không kích hoạt lần nào, nên nhánh A thực chất đang là *trùng token tiếng Việt + khoanh theo doanh nghiệp + cửa sổ thời gian*. Nguyên nhân đã truy được: MediaReport theo schema không mang cạnh `measuredUnder`; KPIObservation phía tin tức không có cạnh đó (1.309 cạnh `measuredUnder` nằm ở KPI phía báo cáo); còn Penalty thì cả 85 node trỏ vào đúng một chỉ tiêu — *"Tổng tiền phạt vi phạm môi trường"* — mà không doanh nghiệp nào tuyên bố mình bị phạt, nên đầu claim của chỉ tiêu đó trống. Bản thân trục chỉ tiêu lành (292/464 claim có `alignsWithIndicator`, 95 chỉ tiêu có claim); chỉ là hai nửa không gặp nhau ở đúng tập bằng chứng này. **Đọc mọi số dưới đây với nhãn đúng đó.**

## 2. Hai câu claim giống nhau đến đâu

| metric | trung bình | KTC 95% (bootstrap) |
|---|---|---|
| token F1 | 0.240 | 0.217 – 0.265 |
| token precision | 0.357 | 0.328 – 0.386 |
| token recall | 0.212 | 0.187 – 0.239 |
| Jaccard | 0.167 | 0.145 – 0.192 |
| ROUGE-L | 0.182 | 0.159 – 0.209 |
| cosine (ngữ nghĩa) | 0.467 | 0.451 – 0.483 |

- Tính trên 158 dòng có claim ở CẢ HAI nhánh.
- Giống nhau CAO nghĩa là hai hệ hội tụ về cùng một câu; giống nhau THẤP nghĩa là chúng đi hai hướng khác hẳn. Bản thân con số không nói hệ nào đúng hơn.

## 3. Nhãn quan hệ

- Cùng chấm được: **158** dòng
- Đồng thuận thô: **75.3%**
- Cohen's kappa: **0.316**

| graph ↓ / rag → | supports | contradicts | irrelevant |
|---|---|---|---|
| **supports** | 14 | 0 | 12 |
| **contradicts** | 1 | 1 | 1 |
| **irrelevant** | 17 | 8 | 104 |

- McNemar trên 'kết luận khác irrelevant': b=13, c=25, p=0.0730
- Lực kiểm định phụ thuộc b+c=38 (cần ≳25 mới đủ nhạy).

## 4. Đối chứng âm (trục Y — kỷ luật)

Ghép mỗi câu bằng chứng với một claim NGẪU NHIÊN của cùng doanh nghiệp. Cặp ngẫu nhiên đúng ra phải bị chấm `irrelevant` — tỷ lệ làm đúng điều đó là specificity.

| nhánh | specificity | KTC 95% (Wilson) |
|---|---|---|
| graph | 45/47 = 95.7% | 85.8% – 98.8% |
| rag | 58/59 = 98.3% | 91.0% – 99.7% |

> Specificity thấp = nhánh đó gán quan hệ cho cả những cặp vô can. Coverage cao đi kèm specificity thấp là bẫy dễ dãi, phải báo cáo như đánh đổi kèm số, không được gọi là cải thiện.

## Giới hạn

- Không đo được accuracy: không có oracle. Mọi con số ở đây là tương đối giữa hai hệ.
- Nhánh graph khoanh claim theo issuer; nhánh rag lọc theo ticker. Cùng phạm vi.
- Cặp ngẫu nhiên trong mục 4 có thể tình cờ thật sự liên quan, nên specificity bị ước lượng THẤP hơn thực tế — lệch về phía bất lợi cho hệ, tức là an toàn.