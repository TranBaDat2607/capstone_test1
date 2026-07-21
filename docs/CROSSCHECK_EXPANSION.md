# Cross-check Expansion — khai thác cam kết khả phủ chứng (KPI / Goal / Penalty) và định tuyến bằng chứng qua đồ thị

> **Trạng thái:** đề xuất thiết kế (chưa cài đặt). Vấn đề 2 trong kế hoạch cải thiện
> trước bảo vệ lần 1. Đọc cùng `docs/SOFTMAX_SCORING.md` (tiêu thụ các tín hiệu sinh ra
> ở đây) và `docs/BERT_NER_GRAPH_QUALITY.md` (công cụ NER/embedding hỗ trợ phần anchoring).

## 1. Chẩn đoán hiện trạng (đã kiểm chứng trên code + dữ liệu AAA)

| # | Phát hiện | Bằng chứng |
|---|---|---|
| D1 | `kpi_gap` và `structural_contradiction` là **tín hiệu "ma"**: step08/step09 đọc-ghi chúng, nhưng step07 **không bao giờ ghi key `signals`** vào dossier → 1.093/1.093 claim AAA có `kpi_gap=false` vĩnh viễn | dossier keys thiếu `signals`; grep step07 không có `kpi_gap` |
| D2 | Retrieval 6a của step07 là **token-overlap toàn cục**: pool = mọi node news thuộc `CONDUCT_CLASSES`, không luôn-kèm KPI/Penalty, không đi qua cấu trúc đồ thị (Facility/công ty con) | `step07:403-441` |
| D3 | Schema **đã có** `Goal.target_date` nhưng extraction gần như không điền (mẫu AAA: "95% export target" không có năm; nhiều goal khẩu hiệu) → không kiểm được "hứa mà không làm" | `config/schema.json` vs mẫu node Goal trong Neo4j |
| D4 | KPI hai phía không nối được với nhau: report-side có `kpi_type` từ vocabulary 35 KPI (step01), news-side là text tự do từ prompt step02 → **không có khóa join** để so số | schema KPIObservation; kiểm tra mẫu |
| D5 | Sự kiện news (Controversy/Penalty/MediaReport) **không neo được vào Facility** — schema chỉ có `observedAtFacility` cho KPIObservation; trong khi báo chí đưa tin theo *nhà máy* chứ không theo *tuyên bố* | schema edges; P3 anchoring 5,3% |
| D6 | AAA: 22 contradicted / 70 supported / 1.001 unverified — phần lớn "mù" không phải vì công ty sạch mà vì bằng chứng độc lập mỏng + retrieval hẹp | `aaa_crosscheck_stats.json` |

Khung phân loại đã thống nhất: **Nhóm 1** = cam kết khả phủ chứng (đơn vị kiểm tra);
**Nhóm 2** = khớp nối dẫn bằng chứng (không kiểm tra trực tiếp, dùng để định tuyến);
Nhóm 3 = ngữ cảnh (bỏ qua). Ba dạng greenwashing tương ứng ba cơ chế kiểm:
*nói mơ hồ* (ngữ nghĩa, LLM — đã có), *số liệu sai* (định lượng, offline), *hứa không
làm* (thời gian, offline). Hai cơ chế sau là phần bổ sung dưới đây — **cả hai đều
NO-LLM**, phù hợp ràng buộc Gemini bị chặn + 1 tháng deadline.

## 2. Bộ sinh tín hiệu offline (`src/step07b_enrich_dossiers.py`) — sửa D1

Script offline mới (NO LLM, NO DB; cùng script với softmax scoring), đọc
`resolved_graph.json` + dossier, ghi `signals` vào từng dossier item:

```json
"signals": {
  "structural_contradiction": false,
  "kpi_gap":        {"kpi_type": "...", "report_value": 120.0, "news_value": 210.0,
                     "period": "2023", "relative_gap": 0.75}  | false,
  "broken_promise": {"goal": "...", "target_date": "2023", "checked_at": "2026",
                     "achievement_evidence": null}            | false
}
```

### 2.1 `kpi_gap` — số tự công bố lệch số độc lập (phụ thuộc §4.1)

```
với mỗi claim C của issuer:
  K_report = KPIObservation source_type=report cùng trang/câu nguồn hoặc cùng chủ đề với C
  K_news   = KPIObservation source_type=news của issuer (sau canonical hóa §4.1)
  match (k_r, k_n) khi: cùng kpi_type canonical AND kỳ giao nhau (year/period)
  nếu |v_r − v_n| / max(|v_r|, ε) > θ (mặc định θ=0.2, sau chuẩn hóa đơn vị §4.1)
      → kpi_gap trên C, kèm cặp giá trị làm bằng chứng hiển thị
ngoài ra: Penalty phía news cùng miền KPI (nước thải/khí thải/…) với KPI report
      → kpi_gap dạng "penalty-in-domain" (yếu hơn, đánh dấu riêng)
```

Kỳ vọng thực tế: tín hiệu này **hiếm** (báo chí VN ít đăng số liệu so sánh được) — nói
thẳng điều đó khi bảo vệ; khi nó bắn thì là bằng chứng mạnh nhất hệ thống có.

### 2.2 `broken_promise` — lời hứa quá hạn không có bằng chứng hoàn thành (phụ thuộc §4.2)

Đây là kiểm tra **dùng đúng trục thời gian của temporal KG** — điểm khác biệt của đồ án:

```
với mỗi Goal / ScienceBasedTarget của issuer có target_date:
  nếu target_date + 1 năm ân hạn < năm hiện tại:
    tìm bằng chứng hoàn thành: (a) claim "đã đạt/hoàn thành" cùng chủ đề có năm ≥ target,
      (b) KPIObservation kỳ ≥ target đạt ngưỡng metric, (c) ThirdPartyVerification
    không có → broken_promise trên các claim cùng nguồn câu / cùng chủ đề với Goal đó
```

Không có bằng chứng hoàn thành ≠ chắc chắn thất hứa (coverage caveat vẫn áp dụng) — vì
vậy nó là **signal** đẩy logit trong softmax, không phải verdict.

### 2.3 `structural_contradiction` — mâu thuẫn cấu trúc có sẵn trong đồ thị

```
issuer -subjectToRegulation-> R  AND  issuer -subjectToPenalty-> P
  với P cùng miền chủ đề với R (token/embedding match mô tả)
→ đặt structural_contradiction=true cho các claim tuyên bố tuân thủ/cam kết thuộc miền đó
```

AAA có 284 cạnh `subjectToRegulation` và 4 `subjectToPenalty` — tập giao nhỏ, tính trong
mili-giây, nhưng lấp đúng cái tên tín hiệu đã hứa trong docs/CLAIM_LEDGER.md.

## 3. Mở rộng retrieval 6a của step07 — sửa D2 (học từ EmeraldMind, có điều chỉnh)

EmeraldMind (`src/utils/classification_utils.py` của họ): truy theo **class mà claim đề
cập** + `ALWAYS_INCLUDE_CLASSES = [KPIObservation, Penalty]` + biến thể multi-hop trả về
`shortestPath`. Áp dụng vào step07:

1. **Always-include (rẻ nhất, làm trước):** mọi claim luôn nhận thêm vào candidate set:
   top-3 `KPIObservation` news + **toàn bộ** `Penalty` news của issuer (AAA chỉ có 4 —
   chi phí không đáng kể). Lý do EmeraldMind đã nêu đúng: claim thường không nhắc số
   liệu, nhưng bằng chứng định lượng là thứ đáng đối chiếu nhất.
2. **Định tuyến qua Nhóm 2 (issuer-scope bằng cấu trúc thay vì toàn cục):** pool conduct
   của một issuer = node news trong ≤ k hop (k=2) từ Organization qua các cạnh
   `{ownsFacility, owns, investsIn, partnersWith, mentionsOrganization, observedAtFacility}`.
   Mỗi evidence ghi kèm `via_path` (chuỗi cạnh, kiểu EmeraldMind trả path) — hai lợi ích:
   sai phạm của **công ty con / nhà máy / khoản đầu tư** tự động thành conduct của mẹ
   (đúng ý "Investment có sai phạm"), và path là lời giải thích trực quan khi demo
   ("bằng chứng này liên quan vì: AAA —owns→ Cty con X —subjectToPenalty→ P").
3. **(Tùy chọn, sau khi có embedding local — xem BERT_NER_GRAPH_QUALITY.md §2):** thay
   token-overlap bằng cosine embedding khi xếp hạng candidate. Chỉ làm nếu còn thời gian;
   token-overlap tiếng Việt hoạt động chấp nhận được ở quy mô pool hiện tại.

Lưu ý chi phí: mở rộng candidate → nhiều cặp LLM hơn ở 6b (OpenAI). Giữ `--max-llm-pairs`
làm van; ưu tiên ngân sách cho các cặp luôn-kèm (Penalty trước, KPI sau).

## 4. Thay đổi kiến trúc graph — **tối thiểu, mức property/cặp-cạnh, KHÔNG thêm class mới**

Nguyên tắc: 1 tháng không đủ cho một schema migration; mọi thay đổi phải backward-
compatible (node cũ thiếu property mới vẫn hợp lệ) và đo được bằng
`step00 --label before/after` (đúng quy trình đã thiết kế).

### 4.1 Canonical hóa KPI (khóa join cho `kpi_gap`) — sửa D4 — **quan trọng nhất**

- **Script offline mới `src/step03c_canonicalize_kpis.py`** (NO LLM): map `kpi_type`/
  `title` của mọi KPIObservation (cả 2 phía) về vocabulary 35 KPI trong
  `kpi_definitions_construction.json` bằng alias tiếng Việt + rapidfuzz; ghi thêm
  properties: `kpi_id` (canonical), `unit_normalized`, `value_normalized`
  (tấn→tấn, %→tỷ lệ, nghìn m³→m³, …), `period` (ISO). Node không map được → giữ nguyên,
  đánh `kpi_id=null` (không phá dữ liệu cũ).
- **Prompt step02 (news mode):** yêu cầu chọn `kpi_type` từ danh sách 35 KPI (đưa danh
  sách vào prompt, cho phép null) — extraction mới sạch từ gốc, backfill lo phần cũ.
- Schema: thêm `kpi_id`, `unit_normalized`, `value_normalized`, `period` vào property
  list của `KPIObservation` (thuần cộng thêm). **Không** đưa vào `identity_keys`.

### 4.2 `Goal.target_date` backfill — sửa D3

- Thêm vào `step03c`: regex tiếng Việt trên `name + description` của Goal:
  `(?:đến|vào|trước|tới)\s*năm\s*(20\d{2})`, `giai đoạn\s*20\d{2}\s*[-–]\s*(20\d{2})`,
  `by\s*(20\d{2})` → điền `target_date` (chỉ khi đang trống). Không cần LLM.
- Prompt step02: nhấn mạnh bắt buộc trích `target_date` khi câu nguồn có mốc thời gian.
- Goal không có target_date sau backfill → **không** vào kiểm tra broken_promise
  (khẩu hiệu không phải lời hứa — nói rõ điều này khi bảo vệ).

### 4.3 Neo sự kiện news vào Facility — sửa D5

- Schema: **mở rộng cặp hợp lệ** của cạnh `observedAtFacility` (validator đã hỗ trợ một
  nhãn nhiều cặp): thêm `(Controversy, Facility)`, `(Penalty, Facility)`,
  `(MediaReport, Facility)`.
- Mở rộng `step03b_anchor_kpi_facilities.py` (gazetteer offline sẵn có) để quét cả câu
  nguồn của 3 class sự kiện news → cạnh `observedAtFacility`, tag
  `anchor_method=offline_gazetteer` như hiện tại. Kết hợp NER (BERT_NER_GRAPH_QUALITY.md
  §3) để tăng recall gazetteer. Tác dụng kép: nâng chỉ số P3 (5,3% → mục tiêu >15%) và
  cấp đường đi cho định tuyến §3.2.

### 4.4 Truy vết nguồn cho node news (phục vụ cả UI)

- `step02 --source news` (extraction mới) + backfill trong `step03c` (join `source_id` →
  JSONL labeled): ghi `article_url`, `publish_date`, `source_domain` thành property trực
  tiếp trên node news. Sửa luôn "lời hứa traceability bị gãy ở dặm cuối" ở lớp hiển thị
  (card không có link tới nguồn).

## 5. Kế hoạch 4 tuần (deadline bảo vệ lần 1 ≈ 2026-08-18)

| Tuần | Việc | Chi phí LLM |
|---|---|---|
| 1 | `step03c` (KPI canonical + Goal backfill) → `step07b` (signals + softmax) → chạy trên dossier AAA sẵn có; `step00 --label` before/after | **0 đ** |
| 2 | step08/09/app: sync + hiển thị scores, signals thật, link nguồn (§4.4); schema pairs §4.3 + mở rộng step03b | **0 đ** |
| 3 | Retrieval §3 (always-include + routing k-hop) → **chạy lại step07 MỘT lần** cho AAA với budget kiểm soát → step07b → so sánh 22/70/1001 trước-sau | OpenAI, 1 lần, có `--max-llm-pairs` |
| 4 | step10: thêm arm sensitivity cho softmax + case study broken_promise/kpi_gap; tổng duyệt demo + soạn Q&A hội đồng | ~0 đ (arm 30-case đã cache) |

Nguyên tắc xuyên suốt: **mọi thứ mới đều phải chạy lại được miễn phí** (chỉ tuần 3 tốn
tiền, đúng 1 lần); tuần nào cũng chốt được một deliverable demo được — nếu cháy tiến độ,
cắt từ dưới lên (§3.3 → §3.2 → §4.3) mà không sập phần đã xong.

## 6. Rủi ro chính

| Rủi ro | Ứng phó |
|---|---|
| `kpi_gap` không bắn phát nào trên AAA (báo chí không có số) | Vẫn bảo vệ được: cơ chế + penalty-in-domain fallback + demo bằng 1 cặp synthetic được đánh dấu rõ trong step10 làm minh họa |
| Goal backfill điền sai năm (regex bắt nhầm năm quá khứ trong mô tả) | Chỉ nhận năm > `valid_from`; sample review 30 goal thủ công trước khi bật broken_promise |
| Mở rộng routing kéo bằng chứng lạc chủ đề (công ty con khác ngành) | `via_path` + vẫn qua cửa token-overlap và LLM adjudication như cũ; routing chỉ mở rộng *pool*, không tự tạo verdict |
| Chạy lại step07 vượt ngân sách | Always-include Penalty trước (4 node), KPI top-3 sau; `--max-llm-pairs` giữ nguyên trần cũ |
