# So sánh Graph-RAG với RAG thường trên tầng retrieval — thiết kế thí nghiệm

> **Trạng thái: ĐỀ XUẤT, chưa triển khai.** Không có dòng code nào trong repo hiện thực
> phép đo ở đây. Đọc như một *thiết kế thí nghiệm*, cùng loại với
> `docs/EVALUATION_WITHOUT_LABELS.md`, `docs/CROSSCHECK_EXPANSION.md`. Ví dụ số ở §4 là
> **minh hoạ** (bịa để giải thích cách tính), không phải số đo thật — dossier thật
> (`graph_output/crosscheck/aaa_claim_assessments.json`) hiện chưa có trên máy dùng để viết
> tài liệu này (chưa `datasync.py pull`).
>
> **Lịch sử sửa:** bản đầu chỉ có Phương pháp A (SERR trên 92 dossier graph đã tìm ra
> evidence) — sau khi rà lại, phát hiện đây là **selection bias / điều kiện hoá theo chính
> thành công của graph** (tương đương survivorship bias): mẫu chỉ gồm case graph đã thắng,
> nên phép đo về cấu trúc **không thể** cho ra kết quả bất lợi cho graph. Phương pháp B (hai
> chiều, không điều kiện theo phương pháp nào) được thêm làm phương pháp **chính**; Phương
> pháp A hạ xuống thành pilot rẻ, chỉ dùng minh hoạ chứ không dùng để kết luận.
>
> **Đọc trước:** [`docs/TEMPORAL_KG_DESIGN.md`](docs/TEMPORAL_KG_DESIGN.md) §4 (Q7(d) — đo
> đồ thị có đường cấu trúc tới conduct hay không) · [`docs/EVALUATION_WITHOUT_LABELS.md`](docs/EVALUATION_WITHOUT_LABELS.md)
> (khung đánh giá không nhãn tổng thể; §4 negative control dùng chung ý tưởng lift/so-với-baseline)

---

## 0. Vì sao cần tài liệu này — Q7(d) không trả lời được câu hỏi này

`quality.py`'s Q7(d) đo: *"đồ thị TỰ NÓ có đường cấu trúc (không qua hub) nối claim tới
conduct hay không"* — một câu hỏi **nội bộ đồ thị**, không có baseline nào để so sánh.

Câu hỏi thật sự cần trả lời cho luận điểm "tại sao xây Graph-RAG thay vì RAG thường" là
khác hẳn: **"Trên cùng một tập claim, ai tìm ra evidence đúng nhiều hơn — graph traversal
hay RAG thuần cosine similarity?"** — một so sánh hai phương pháp, phải đo **không điều
kiện theo việc phương pháp nào đã thành công**, nếu không kết quả sẽ thiên lệch có hệ thống
(xem §2.3).

---

## 1. Snapshot hiện trạng (số liệu thật, đo 2026-07-28, nguồn: `docs/EVALUATION_WITHOUT_LABELS.md` §2)

| Đại lượng | Giá trị |
|---|---|
| Tổng claim (`SustainabilityClaim`) | 1.093 |
| Conduct pool (ứng viên evidence) | 124 (108 `KPIObservation` + 16 `MediaReport`) |
| Cặp ứng viên retrieval hiện tại xét (graph traversal) | 3.461 |
| Evidence được giữ lại (adjudicated supports/contradicts) | 191 (yield 5,5%) |
| Claim có ≥1 evidence (graph tìm ra) | 92 (8,4%) |
| Claim `unverified_insufficient_evidence` | 1.001 (91,6%) |
| Q7(d) — claim có đường cấu trúc hub-free tới conduct | 8% |

**Ngân sách retrieval trung bình mỗi claim** = 3.461 / 1.093 ≈ **3,2 ứng viên/claim** — dùng
làm `k` (top-k) khi mô phỏng RAG baseline, để so sánh đúng ngân sách hệ thống thật đang chi,
không phải một số tuỳ chọn.

---

## 2. Phương pháp A — SERR (pilot rẻ, MỘT CHIỀU, có thiên lệch — không dùng để kết luận)

### 2.1 Định nghĩa

Cho tập `P` = các cặp `(claim, evidence)` mà **graph traversal tìm ra VÀ reviewer con người
xác nhận đúng** (từ 92 dossier `appears_supported`/`appears_contradicted`).

Với mỗi cặp `(c, e) ∈ P`: tính `cos(c, e)`, xếp hạng `e` trong 124 node conduct pool theo
cosine similarity với `c`, so `rank(c,e)` với `k=3`.

```
SERR = |{(c,e) ∈ P : rank(c,e) > k}| / |P|
```

Báo cáo kèm Wilson 95% CI vì `|P|` nhỏ.

### 2.2 Vì sao dùng RANK thay vì ngưỡng cosine cố định

Không có ngưỡng cosine "chuẩn" chung cho mọi embedding model/miền dữ liệu. Dùng rank so với
đúng ngân sách retrieval hệ thống thật đang dùng (k≈3) loại bỏ vấn đề chọn ngưỡng tuỳ ý.

### 2.3 ⚠ Vì sao đây KHÔNG PHẢI phép đo khách quan — chỉ dùng làm pilot minh hoạ

`P` được xây từ 92 dossier **graph đã thành công tìm ra evidence** — tức là đã điều kiện
hoá mẫu theo chính kết quả của phương pháp đang được đánh giá. Hệ quả:

- SERR chỉ trả lời được *"trong case graph THẮNG, RAG có thắng theo không"* — về cấu trúc,
  câu hỏi này **không thể nào** cho ra kết luận bất lợi cho graph.
- Nó không bao giờ nhìn vào 1.001 claim `unverified_insufficient_evidence` — nơi RAG thuần
  cosine similarity có thể tìm ra evidence mà graph traversal bỏ lỡ (graph đòi hỏi có cạnh
  cấu trúc nối liền — điều kiện chặt hơn "giống nghĩa", nên có thể bỏ sót case văn bản rất
  giống nhau nhưng thực thể chưa được entity-resolution gộp đúng).
- Nói cách khác: SERR đo được 1/2 câu chuyện (RAG bỏ lỡ gì so với graph), không đo được nửa
  duy nhất có thể phản bác được lập luận "graph tốt hơn" (graph bỏ lỡ gì so với RAG).

**Dùng SERR để làm gì thì được:** một pilot rẻ (~92+124 lệnh gọi embedding), chạy trước để
có trực giác/ví dụ cụ thể đưa vào bài viết (như §4). **Không dùng SERR một mình để kết
luận** "graph hơn RAG" trong luận văn — chỉ Phương pháp B (§3) mới đủ tư cách kết luận.

### 2.4 Script (phác thảo, tái dùng hạ tầng có sẵn)

```python
import json, numpy as np
from esg_kg.resolve.entities import embed_texts, DEFAULT_EMBED_MODEL, DEFAULT_EMBED_DIM
from esg_kg.core.llm import RateLimiter
from google import genai

K = 3
dossier = json.load(open("graph_output/crosscheck/aaa_claim_assessments.json", encoding="utf-8"))
resolved = json.load(open("graph_output/resolved/resolved_graph.json", encoding="utf-8"))
conduct_nodes = [n for n in resolved["nodes"] if n["class"] in ("KPIObservation", "MediaReport")]

reviewed = json.load(open("scratchpad/review_results.json", encoding="utf-8"))
P = [r for r in reviewed if r["reviewer_verdict"] == "agree"]

client = genai.Client()
rate_limiter = RateLimiter(rate=10)
claim_embs = embed_texts([p["claim_text"] for p in P], client, DEFAULT_EMBED_MODEL, DEFAULT_EMBED_DIM, rate_limiter, batch=20)
conduct_embs = embed_texts([n.get("description") or n.get("text", "") for n in conduct_nodes], client, DEFAULT_EMBED_MODEL, DEFAULT_EMBED_DIM, rate_limiter, batch=20)

exclusive = 0
for i, p in enumerate(P):
    sims = conduct_embs @ claim_embs[i]
    order = np.argsort(-sims)
    e_idx = next(j for j, n in enumerate(conduct_nodes) if n["_node_key"] == p["evidence_node_key"])
    rank = int(np.where(order == e_idx)[0][0]) + 1
    if rank > K:
        exclusive += 1
print(f"SERR (pilot, one-directional) = {exclusive/len(P):.1%} ({exclusive}/{len(P)})")
```

---

## 3. Phương pháp B — So sánh hai chiều, không thiên lệch (KHUYẾN NGHỊ CHÍNH)

### 3.1 Nguyên tắc: không điều kiện mẫu theo phương pháp nào

Lấy mẫu claim **độc lập với việc graph hay RAG có tìm ra gì hay không** — chạy cả hai
phương pháp trên cùng mẫu, rồi mới biết ai tìm ra gì. Đây là thiết kế duy nhất có thể ra
kết quả **bất lợi cho graph** — dấu hiệu của một phép đo khách quan, không phải nguỵ biện
có số đính kèm.

### 3.2 Các bước

```
Bước 1  Lấy mẫu NGẪU NHIÊN ~100-150 claim từ toàn bộ 1.093 (không lọc theo graph có tìm ra
        evidence hay không — bao gồm cả claim đang là unverified_insufficient_evidence).
Bước 2  Với MỖI claim trong mẫu, sinh 2 tập ứng viên ĐỘC LẬP:
          G = candidate hiện tại từ graph traversal (retrieval stage thật của step07)
          R = top-k (k=3, theo ngân sách §1) node conduct xếp hạng bằng cosine similarity
              thuần (claim_text vs evidence_text, embed_texts() có sẵn)
Bước 3  Hợp nhất U = G ∪ R (loại trùng theo _node_key), XÁO TRỘN THỨ TỰ và ẨN NGUỒN GỐC
        (không cho reviewer biết candidate đến từ G hay R — tránh thiên kiến reviewer).
Bước 4  Reviewer chấm supports/contradicts/irrelevant cho từng cặp (claim, candidate) trong U.
Bước 5  Tính, trên tập "đúng" = cặp reviewer xác nhận supports hoặc contradicts thật:
          recall_graph = |đúng ∩ G| / |đúng ∩ U|
          recall_RAG   = |đúng ∩ R| / |đúng ∩ U|
          unique_graph = |đúng ∩ G \ R| / |đúng ∩ U|   (chỉ graph tìm ra)
          unique_RAG   = |đúng ∩ R \ G| / |đúng ∩ U|   (chỉ RAG tìm ra)
        Báo cáo cả 4 số, kèm Wilson 95% CI.
```

### 3.3 Vì sao thiết kế này chữa được lỗi của Phương pháp A

- Mẫu claim (Bước 1) không phụ thuộc phương pháp nào → không còn survivorship bias.
- `U` là hợp của CẢ HAI tập ứng viên → reviewer có cơ hội thấy case chỉ RAG tìm ra (điều
  Phương pháp A cấu trúc không cho phép nhìn thấy).
- Ẩn nguồn gốc trước khi reviewer chấm → loại thiên kiến "biết đây là graph nên có xu hướng
  tin hơn".
- Kết quả có thể là `recall_RAG > recall_graph` — nếu xảy ra, đó là phát hiện thật (vd graph
  đang bỏ sót vì thiếu cạnh cấu trúc, entity resolution chưa gộp đúng) và vẫn đáng báo cáo,
  đúng tinh thần "dự báo hỏng có kiểm chứng vẫn tốt hơn số đẹp không ai tin" của
  `docs/EVALUATION_WITHOUT_LABELS.md` §3.3.

### 3.4 Chi phí

~125 claim × (|G| trung bình 3,2 + k=3 RAG, trừ phần trùng) ≈ **300-500 cặp cần reviewer
chấm** — lớn hơn Phương pháp A (92 dossier có sẵn) nhưng vẫn nhỏ hơn nhiều so với chạy lại
toàn bộ step07 gốc (3.461 cặp × LLM). Không tốn thêm LLM nếu adjudication verdict của G lấy
lại từ dossier có sẵn (chỉ cần LLM cho phần R mới, ước tính ~375 lệnh gọi).

---

## 4. Ví dụ minh hoạ — tính tay cho MỘT claim (số liệu bịa, không phải số thật)

**Claim** (`claim_id: c-0412`, năm 2022):
> "AAA đã đầu tư hệ thống xử lý nước thải đạt chuẩn tại nhà máy An Phát 2"

**Evidence graph tìm ra** (qua đường cấu trúc, KHÔNG qua hub):
```
SustainabilityClaim(c-0412)
   --alignsWithIndicator-->  StandardIndicator(TT96-4.2 "Xử lý nước thải")
   <--measuredUnder--        KPIObservation("Trạm XLNT công suất 500m³/ngày, vận hành Q3/2022")
   --observedAtFacility-->   Facility("Nhà máy An Phát 2")
   <--enforcedBy--            Penalty("Phạt 120tr do nước thải sau xử lý vượt quy chuẩn cột B, 11/2022")
```
Evidence text cuối cùng: *"Nhà máy An Phát 2 bị xử phạt 120 triệu đồng do thông số nước thải
sau xử lý vượt quy chuẩn kỹ thuật quốc gia, kiểm tra tháng 11/2022"* → verdict hệ thống:
`appears_contradicted`. Reviewer xác nhận: **đúng**. Evidence không chứa cụm nào giống claim
("nước thải" là từ chung duy nhất; "đạt chuẩn" đối nghịch "vượt chuẩn") — ví dụ điển hình
cho case RAG thuần cosine dễ bỏ lỡ.

**Minh hoạ Phương pháp A (SERR)** cho cặp này: `cos = 0,31`, hạng 58/124, `k=3` → structural-exclusive = TRUE.

**Minh hoạ Phương pháp B** cho claim này: `G = {Penalty(120tr)}` (graph tìm ra), giả sử
`R = {KPIObservation("chi phí đầu tư môi trường 2022"), KPIObservation("doanh thu 2022"), Goal("mục tiêu ESG 2025")}`
(RAG top-3 theo cosine, vì các văn bản này dùng nhiều từ giống claim hơn dù không liên quan
trực tiếp) → reviewer chấm cả 4 candidate trong `U`: chỉ `Penalty(120tr)` được xác nhận
đúng → `recall_graph = 1/1 = 100%`, `recall_RAG = 0/1 = 0%` cho riêng claim này — nhưng đây
chỉ là 1 điểm dữ liệu, kết luận thật phải tổng hợp trên cả mẫu ~125 claim.

---

## 5. Cách đọc kết quả Phương pháp B — các kịch bản có thể xảy ra

| Kết quả | Ý nghĩa |
|---|---|
| `recall_graph` cao, `unique_graph` cao, `recall_RAG` thấp | Graph đóng góp thật và mạnh — lập luận "cần graph" có số liệu ủng hộ, không chỉ pilot. |
| `recall_graph ≈ recall_RAG`, `unique_graph` thấp | Graph không vượt trội ở tầng tìm evidence (giá trị của graph nằm ở chỗ khác — vd cột "Missing"/phủ định đóng mà RAG không làm được về nguyên tắc, đã bàn trong hội thoại trước). |
| `recall_RAG > recall_graph` | Phát hiện thật, đáng báo cáo: graph traversal đang bỏ sót case RAG tìm được — thường do thiếu cạnh cấu trúc hoặc entity resolution chưa gộp đúng thực thể; chỉ ra hướng cải thiện cụ thể. |

Dù kết quả là gì, đều phát biểu được — không có kịch bản nào "phá" luận văn, chỉ có kịch
bản chỉ ra chính xác graph đóng góp ở đâu.

---

## 6. Giới hạn còn lại (áp dụng cho cả 2 phương pháp)

- Reviewer chỉ phán trên candidate đã có trong `U` — không tìm bằng chứng ngoài `U` bằng tay
  (vẫn là oracle problem, không giải quyết được bằng thiết kế này).
- `k=3` cho RAG baseline là xấp xỉ ngân sách hệ thống thật; nếu muốn robust hơn, chạy thêm
  `k=5`/`k=10` để xem kết luận có đổi không.
- Cần 1 reviewer độc lập, đã bàn ở phần review-protocol trước trong hội thoại — độ mạnh của
  kết luận phụ thuộc nền tảng chuyên môn của người đó.
