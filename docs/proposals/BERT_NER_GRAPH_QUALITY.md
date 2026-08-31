# BERT / NER cho chất lượng đồ thị — dùng ở đâu, và ở đâu thì KHÔNG

> **Trạng thái:** phân tích quyết định (Vấn đề 3, optional). Kết luận trước, lý do sau.
> Đọc cùng `docs/CROSSCHECK_EXPANSION.md` (nơi các công cụ này được tiêu thụ).

## 0. Kết luận nhanh

| Ứng dụng | Quyết định | Lý do một dòng |
|---|---|---|
| **Sentence-embedding local (BERT-class, CPU)** thay `gemini-embedding-001` trong step05 Stage B | ✅ **NÊN — giá trị cao nhất** | Gỡ đúng chỗ đang **billing-blocked**; EmeraldMind đã làm y hệt trên CPU |
| **NER tiếng Việt (underthesea)** hỗ trợ anchoring news → Facility/Organization | ✅ **NÊN — rẻ nhất** | Dependency **đã có sẵn** trong pipeline, không thêm torch |
| Fine-tune BERT phân loại greenwashing | ❌ **KHÔNG** | Không có nhãn — vi phạm chính tiền đề §1.1 của đồ án |
| NER/BERT thay LLM extraction (step02) | ❌ **KHÔNG** | NER cho span thực thể, không cho triple có schema + thời gian |

Cả hai mục "NÊN" đều là **cải thiện hạ tầng cho Vấn đề 2**, không phải hướng nghiên cứu
mới — đúng khẩu vị của một tháng cuối: rủi ro thấp, gỡ nghẽn thật.

## 1. Bối cảnh ràng buộc (vì sao phân tích này khác sách vở)

- `gemini-embedding-001` **đang bị chặn billing** → step05 hiện chạy `--no-llm`
  (Stage A + B.1), tức entity resolution đang mất nguyên tầng blocking bằng embedding
  (Stage B.2) và tầng adjudication (Stage C).
- Máy **không có GPU**; torch cố ý không nằm trong `requirements.txt` (quy ước dự án —
  cài local khi cần, như đường CPU của `esg_classifier.py`).
- Còn **1 tháng** — mọi đề xuất phải đo được bằng công cụ sẵn có (`step00`,
  `resolved_stats`) và không phá quy ước layout/execution style.

## 2. ✅ Đề xuất 1: embedding local cho step05 Stage B (và step07 retrieval nếu kịp)

**Vấn đề gỡ được:** Stage B.2 của `step05_resolve_entities.py` cần cosine similarity
giữa tên/mô tả entity — đang chết vì Gemini embedding bị chặn. Đây là chỗ **duy nhất**
trong pipeline mà một mô hình BERT-class thay thế được dịch vụ trả phí *một-một*.

**Tiền lệ ngay trong reference:** EmeraldMind chạy
`SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")` **trên CPU** cho toàn bộ retrieval
(`classification_utils.py:42`) — không GPU, không API. Trích dẫn được khi bảo vệ.

**Lựa chọn model (theo thứ tự ưu tiên):**

| Model | Kích thước | Ghi chú |
|---|---|---|
| `bkai-foundation-models/vietnamese-bi-encoder` | ~135M | Tối ưu tiếng Việt, chạy CPU được |
| `paraphrase-multilingual-MiniLM-L12-v2` | ~118M | Nhẹ, đa ngữ, an toàn nếu model VN lỗi |
| `keepitreal/vietnamese-sbert` | ~135M | Phương án dự phòng cùng hạng |

Quy mô bài toán nhỏ (vài nghìn entity name, mỗi tên < 30 token) → CPU encode toàn bộ
trong vài phút, **một lần rồi cache** — hoàn toàn khả thi không GPU.

**Cách cài vào code (ít xâm lấn):** thêm provider embedding thứ hai trong step05 sau
Gemini: `--embedding-provider gemini|local` (mặc định thử gemini, fail → gợi ý local
chứ không tự đổi). Torch + sentence-transformers cài local như quy ước hiện có, **không**
thêm vào `requirements.txt`; ghi chú cài đặt vào README như đường ViDeBERTa-CPU.

**Đo lường:** chạy lại step05 với Stage B bật → so `resolved_graph_stats.json` +
`step00 --label resolve-localemb` với baseline: số cặp merge thêm, Q2 conciseness, và
số `needs_review` giảm. Đây là con số "trước/sau" cụ thể cho slide bảo vệ.

**Mở rộng nếu kịp (không bắt buộc):** cùng encoder đó thay token-overlap ở step07 6a
(xếp hạng candidate bằng cosine) — chung một model, không thêm chi phí mới. Chỉ làm ở
tuần 3-4 nếu phần chính đã xong.

## 3. ✅ Đề xuất 2: NER tiếng Việt cho anchoring news (underthesea — đã có sẵn)

**Vấn đề gỡ được:** sự kiện news không neo được vào Facility/Organization con
(P3 = 5,3%; `mentionsOrganization` của AAA chỉ có 30). Gazetteer của step03b match
chuỗi thô nên hụt các biến thể tên ("NM Nhựa An Phát 6", "nhà máy số 6 của An Phát").

**Giải pháp:** `underthesea.ner()` — **đã là dependency** của sentence_splitter, không
cần torch, chạy CPU tức thì:

1. Trong bước mở rộng step03b (CROSSCHECK_EXPANSION.md §4.3): chạy NER trên câu nguồn
   của mỗi node news → lấy các span `ORG`/`LOC` → match những span đó (thay vì cả câu)
   với gazetteer Facility/issuer-alias bằng rapidfuzz → tăng recall cạnh
   `observedAtFacility` / `mentionsOrganization` mà vẫn giữ precision (chỉ match phần
   câu là thực thể thật).
2. Bonus lọc nhiễu crawler: bài news mà NER không tìm thấy ORG nào khớp alias issuer
   (`issuer_registry.json`) → cờ `off_target=true` để hạ ưu tiên trong retrieval —
   giảm bài lạc đề mà Google News RSS hay trả về.

**Chi phí:** ~nửa ngày code trong khuôn step03b hiện có. Đo bằng: % KPI/event có anchor
(P3), số cạnh `mentionsOrganization` mới, sample review 30 cạnh.

**Giới hạn nói trước với hội đồng:** NER của underthesea là CRF/BiLSTM đời cũ, F1 tiếng
Việt ~0.85-0.90 trên tin tức chuẩn — đủ cho vai *bộ lọc ứng viên trước fuzzy-match*
(sai thì chỉ mất một match, có gazetteer chặn cuối), không đủ cho vai trích xuất chính.

## 4. ❌ Từ chối 1: fine-tune BERT phân loại greenwashing

Lý do từ chối — dùng được nguyên văn khi hội đồng hỏi "sao không train một classifier":

1. **Không có nhãn.** Tiền đề trung tâm của đồ án (SYSTEM_DESIGN §1.1) là *không tồn tại
   ground truth greenwashing cho công ty niêm yết VN*. Fine-tune cần nghìn nhãn; nhãn
   tự bịa → model học lại thiên kiến của người bịa — đúng cái bẫy mà kiến trúc
   "evidence + advisory" được thiết kế để né. EmeraldData của EmeraldMind là
   **semi-synthetic tiếng Anh**, không chuyển được sang tiếng Việt trong 1 tháng.
2. **Sai bài toán.** Đầu ra của đồ án là *bằng chứng có truy vết + phân bố cân bằng
   bằng chứng* (SOFTMAX_SCORING.md), không phải nhãn nhị phân từ black-box. Một BERT
   classifier dù đúng cũng không trả lời được "vì sao" — mất luôn ưu thế cạnh tranh của
   Graph-RAG so với LLM thuần mà chính bài EmeraldMind dùng làm luận điểm chính.
3. **Thực dụng:** không GPU (ViDeBERTa hiện phải chạy trên Kaggle), 1 tháng, và mọi
   điểm số fine-tune sẽ bị hỏi "test set nào?" — câu không có đáp án tốt khi không có nhãn.

## 5. ❌ Từ chối 2: NER/BERT thay LLM extraction ở step02

NER trả về *span thực thể phẳng* (`ORG`, `LOC`, `PER`…). step02 cần *triple có schema*:
class trong ~28 loại, quan hệ trong ~50 nhãn, property map, `valid_from/valid_to`,
`date_uncertain`. Khoảng cách đó là cả một hệ relation-extraction + temporal-tagging
tiếng Việt — không tồn tại off-the-shelf, không xây nổi trong 1 tháng, và nếu xây thì
chất lượng chắc chắn dưới LLM extraction hiện tại (đã có validation + repair ở step03).
NER chỉ đúng vai ở §3: **hậu kiểm và neo đậu**, không phải trích xuất.

## 6. Tóm tắt effort

| Việc | Effort | Phụ thuộc | Khi nào |
|---|---|---|---|
| NER anchoring (§3) | ~0.5–1 ngày | không (underthesea sẵn) | Tuần 2 (cùng §4.3 của CROSSCHECK_EXPANSION) |
| Embedding local step05 (§2) | ~1–2 ngày (cài torch CPU + provider + rerun + đo) | cài torch local | Tuần 2–3 |
| Embedding cho step07 retrieval | ~0.5 ngày | §2 xong | Tuần 3–4, chỉ nếu dư thời gian |
