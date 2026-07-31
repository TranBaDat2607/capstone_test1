# GRAPH_IMPROVEMENT_PLAN.md

Kế hoạch cải thiện chất lượng/cấu trúc đồ thị ESG-KG, viết cho hai ràng buộc đã xác nhận:

- **Được phép chạy lại toàn bộ pipeline cho AAA** (kể cả `extract` / `extract_triples`) để kiểm chứng.
- **Sẽ scale lên nhiều công ty** sau khi cấu trúc được sửa.

Tài liệu này là *engineering checklist*, cùng loại với `ENTITY_RESOLUTION_PLAN.md` — không phải mô tả code đang có.
Mỗi mục có: Vấn đề → Bằng chứng → Cách làm → Chi phí → Rủi ro → Cách xác minh.

> **Quy ước bắt buộc:** mọi mục dưới đây tuân theo working rule TDD trong `CLAUDE.md` —
> viết test trước (`test/test_*.py`, plain `assert`, offline), chạy thấy đỏ, rồi mới viết code.

---

## 0. Nguồn số liệu — cái gì đã kiểm chứng, cái gì chưa

Phân biệt này quan trọng, vì kế hoạch không nên đứng trên số chưa xác minh.

**Đã đo trực tiếp từ artifact trong repo** (`graph_output/resolved/resolved_graph.json`,
`graph_output/quality/quality_report_after-gri-merge.json`,
`graph_output/crosscheck/aaa_crosscheck_stats.json`, `config/schema.json`):

| Chỉ số | Giá trị | Ghi chú |
|---|---:|---|
| Nodes / Edges | 10.425 / 14.402 | file hiện tại trên đĩa |
| Hub = node 0 `CTCP Nhựa An Phát Xanh` | **9.511** | **66,0% toàn bộ cạnh** chạm hub |
| Median degree / tỉ lệ lá | 1 / 75,8% | |
| Organization có degree = 1 | 228 / 438 | |
| Q7(c) masked-answerable | 34,8% | |
| Q7(d) claim→conduct structural | **8,0%** | trên 1.217 claim |
| Q7(e) T2 degree ≥ 2 | 19,9% | |
| Conduct pool | 124 node | MediaReport 16 + KPIObs 108 (theo retrieval) |
| Claim không có candidate nào | 345 / 1.093 = **31,6%** | |
| Claim `unverified_insufficient_evidence` | 1.001 / 1.093 = **91,6%** | |
| LLM call / edge | 3.461 ÷ 152 = **22,8** | |
| Location dư thừa / Authority dư thừa | 52 / 8 | theo `q3_conciseness` |
| Cạnh KHÔNG chạm hub | 4.891 = 34,0% | vùng duy nhất pivot có thể sống |
| Node thuộc lớp T1 "chia sẻ được" | 1.010 / 10.425 = **9,7%** | bề mặt join liên công ty |

**Chưa kiểm chứng được trong repo này** — lấy từ `graph_deepening_to_agent_research.md`,
mà hai file nguồn của nó (`GRAPH_DEPTH_AND_AGENT_READINESS.md`, `SSRL_REASONING_ASSESSMENT.md`)
trỏ tới `c:/cap/capstone_test1/` và **không có trong repo**:

- R1 reachability ≤ 3 hop = 46,8%
- R1′ hub-free reachability = 26,9%
- Relation entropy = 0,714 · to-many ratio = 13,1%

→ **Mục A2 bên dưới tồn tại chính là để tự đo lại ba số này trong `report/quality.py`.**
Trước khi có kết quả đó, không dùng chúng làm cổng go/no-go.

---

## 1. Ba phát hiện định hình toàn bộ kế hoạch

### 1.1 Dossier đã trả tiền được bảo vệ bởi `claim_id` — và chỉ bởi nó

Đo bằng chính hàm resolve của `load/neo4j_sync.py` trên dossier thật:

```
claim resolution tiers   : {'stable_id': 1093}    ← 100% qua claim_id
evidence resolution tiers: {'text': 209}          ← 100% qua (class, node_text)
                            positional: 0
```

Nghĩa là **đánh số lại node không phá dossier** — 3.461 lần gọi LLM đã trả tiền vẫn tái gắn đúng.
Thêm nữa, binding theo vị trí *đã hỏng sẵn*: `resolved_graph_stats.json` ghi 10.356 node còn file
hiện tại có 10.425; evidence `node_index` 10238 giờ trỏ vào một `MediaReport` trong khi dossier ghi
`KPIObservation`. Ta đang sống nhờ hai tier stable-id.

> ⚠ **Hệ quả sống còn cho việc chạy lại AAA:** `claim_id` do LLM sinh ra ở `extract_triples`.
> Chạy lại step02 khi `claim_id` **chưa** deterministic sẽ sinh ra bộ id mới → tier 1 chết →
> toàn bộ 1.093 dossier mất neo → phải trả lại 3.461 lượt adjudication.
> **C1 (deterministic `claim_id`, GitHub issue #2) là điều kiện tiên quyết, không phải tuỳ chọn.**

### 1.2 Claim và conduct gần như không giao nhau về thời gian

```
Claim (1.217):   2021:248  2023:198  2020:190  2022:175  2018:106  2025:73  2017:66 ...  (2011→2025)
Conduct (news):  2025:71   2026:29   2024:8    + 80 node KHÔNG có năm          (2024→2026)
```

Mọi kỹ thuật "pivot theo thời gian" (gộp cạnh theo `ReportingPeriod`) chỉ tạo đường
`claim(Y) → Period(Y) → conduct(Y)` khi hai phía **cùng có Y**. Hiện giao nhau thực chất chỉ ở 2025
≈ 73 claim ≈ 6%.

→ Làm sâu cấu trúc sẽ nâng R1 / R5 / Q7(c) / Q7(e). **Nó sẽ không nâng Q7(d) bao nhiêu.**
Chỉ có thêm dữ liệu conduct đúng khoảng 2015–2023 (mục C4) mới nâng được Q7(d).
Cần nói rõ điều này khi báo cáo, đừng gộp hai loại cải thiện làm một.

### 1.3 "Hub" hiện là MAX của đúng một node → bẫy đo khi scale

`report/quality.py:479-481` chọn **một** node degree lớn nhất, và Q7(d) loại trừ đúng chỉ số đó
(`d_definition`: `excluded hub = node 0`).

Khi có 5 công ty, ta **không** có một hub to hơn, cũng **không** có trung bình degree các công ty —
ta có **N ngôi sao rời nhau**, vì `extract_triples` chạy theo từng trang và thực thể duy nhất xuất
hiện trên mọi trang là issuer của tài liệu đó. AAA: 13 báo cáo → 9.511 cạnh hub ≈ **730 cạnh/báo cáo**
(ước lượng tuyến tính từ AAA, chưa kiểm chứng trên công ty khác).

Hệ quả, chiếu theo tốc độ đó:

| Chỉ số | Hiện tại (1 cty) | ~5 công ty | Scale có sửa được không? |
|---|---:|---:|---|
| Max degree (cổng R5 ≤ 500) | 9.511 | vẫn ~9.511 | ❌ **không** — R5 là cổng MAX |
| Median degree (đích ≥ 4) | 1 | vẫn 1 | ❌ **không** — mỗi cty thêm một sao đầy lá |
| Nodes / Edges | 10,4K / 14,4K | ~38K / ~50K | ✅ |
| R1′ hub-free | 26,9%* | tăng | ⚠ **tăng giả** nếu chưa làm A1 |

Bẫy: với 5 công ty mà vẫn loại trừ mỗi node 0, đường
`claim AAA → Standard → hub công ty B → KPI của B` sẽ **bị tính là hub-free structural**.
R1′ sẽ tăng đúng vào ngày thêm công ty, vì lý do không liên quan tới chiều sâu đồ thị.

→ **A1 phải xong TRƯỚC khi scale**, nếu không so sánh trước/sau là vô nghĩa.

---

## 2. Nhóm A — Sửa thước đo trước (offline, 0đ)

Không có nhóm này thì mọi cải thiện sau đều không chứng minh được.

### A1. Hub = TẬP hợp, không phải một node ⚠ chặn scaling

- **Vấn đề:** hub là max một node; Q7(d) loại trừ một chỉ số.
- **Bằng chứng:** §1.3.
- **Cách làm:** trong `src/esg_kg/report/quality.py`
  - `largest_hub` → `hubs`: danh sách cụm issuer + degree từng cụm.
  - `R5 = max(degree)` trên toàn tập hub, không phải một node.
  - Q7(d): loại trừ **toàn bộ cụm issuer** (theo `config/issuer_registry.json`, mở rộng cho
    nhiều issuer), không chỉ node có degree cao nhất.
- **Chi phí:** offline, 0đ, ~0,5 ngày.
- **Rủi ro:** Q7(d) sẽ **giảm** so với 8,0% khi loại cả cụm — đó là con số đúng hơn, không phải hồi quy.
  Ghi rõ trong báo cáo.
- **Xác minh:** `test/test_quality_hub_set.py` — fixture tổng hợp 2 issuer; assert đường đi qua hub
  của issuer thứ hai **không** được tính hub-free.

### A2. Bổ sung R1 / R1′ / R7 vào quality report

- **Vấn đề:** ba chỉ số cổng của lộ trình agent hiện không tự đo được trong repo (§0).
- **Cách làm:** thêm vào `quality.py`
  - `R1` = % truy vấn `(es, r, ?)` tới được đáp án trong ≤ 3 hop.
  - `R1′` = như trên nhưng cấm toàn bộ cụm hub (dùng lại A1).
  - `R7` = số metapath độ dài 3, hub-free, support ≥ 50.
  - `R1_trainable` = R1 sau khi loại quan hệ thoái hoá (xem A3).
- **Chi phí:** offline, 0đ, ~1 ngày. Đặt sau cờ `--skip-slow` như Q7(c)/(d) vì BFS nặng.
- **Xác minh:** `test/test_reasoning_readiness_metrics.py` trên đồ thị tổng hợp nhỏ có đáp án tính tay.

### A3. Lọc quan hệ thoái hoá khỏi tập truy vấn huấn luyện

- **Vấn đề:** `reportsKPI` chiếm 4.420/9.511 cạnh hub. Đây là liệt kê, không phải suy luận.
- **Cách làm:** danh sách `DEGENERATE_RELATIONS` trong config; `R1_trainable` và bộ dữ liệu
  export sau này đều loại chúng. Vẫn giữ trong đồ thị phục vụ — chỉ loại khỏi *đo và huấn luyện*.
- **Chi phí:** 0đ.

**Cổng A:** chạy `python src/run.py quality --label pre-deepening` và commit. Đây là cột "TRƯỚC".

---

## 3. Nhóm B — Cải thiện offline, KHÔNG cần trích xuất lại

Toàn bộ nhóm này chạy trên `all_validated_triples.json` sẵn có. Không tốn LLM.

### B1. Sửa `identity_signature` để gộp node khoá thiếu (dedupe thật)

- **Vấn đề:** 52 Location + 8 Authority trùng tên vẫn tồn tại dù Stage B.1 có chuẩn hoá tên.
- **Bằng chứng — nguyên nhân gốc đã xác định.** `resolve/entities.py:185` dựng chữ ký từ **toàn bộ**
  `identity_keys`, nên node điền thiếu khoá không bao giờ khớp:

  ```
  node 14   "hải dương" → ("Location", ("hai duong", "hai duong", "viet nam"))
  node 3444 "hải dương" → ("Location", ("hai duong", "",          ""))
  ```

- **Cách làm:** thêm tầng **subsumption** vào Stage B.1: cùng class, cùng tên chuẩn hoá, và tập
  giá trị khoá khác rỗng của node này là **tập con** của node kia → gộp. Chạy được dưới `--no-llm`.
- **Chi phí:** ~20 dòng + test, offline, 0đ.
- **Rủi ro:** gộp nhầm hai địa danh trùng tên khác tỉnh. Giảm thiểu: chỉ gộp khi không có khoá nào
  *mâu thuẫn* (khác rỗng và khác nhau), chứ không phải chỉ "thiếu".
- **Xác minh:** `test/test_entities_partial_key_merge.py` — case "hải dương" gộp; case
  "Location(name=X, region=A)" vs "Location(name=X, region=B)" **không** gộp.

### B2. Neo phía conduct (Q7(e): 4 lớp đang 0–9,9%)

| Lớp | Node | degree ≥ 2 | Cạnh cần |
|---|---:|---:|---|
| Penalty | 4 | 0% | `Penalty → enforcedBy → Authority` |
| MediaReport | 91 | 9,9% | `MediaReport → mentionsFacility → Facility\|Location` |
| Controversy | 2 | 0% | cần thêm dữ liệu (C4) |
| ThirdPartyVerification | 24 | 0% | cần thêm dữ liệu (C4) |

- **Điểm rẻ hơn tài liệu gốc nói:** `enforcedBy | Penalty -> Authority` **đã hợp lệ trong
  `config/schema.json`** — không cần sửa schema, chỉ cần sinh cạnh.
  `mentionsFacility` thì **chưa có** (schema mới chỉ có `mentionsOrganization`, `mentionsProduct`)
  → cần thêm cặp cạnh + chạy lại `test/test_schema_contract.py`.
- **Cách làm:** stage offline mới `src/esg_kg/graph/anchor_conduct.py`, đúng khuôn mẫu đã có của
  `graph/anchor_kpi.py` (gazetteer tên thực thể đã có trong đồ thị, đối chiếu câu nguồn qua
  `source_id` → labeled JSONL), gắn `anchor_method=offline_gazetteer`.
- **Chi phí:** offline, 0đ, ~1,5 ngày.
- **Xác minh:** `test/test_anchor_conduct.py` — dựng lại `test_esg_kg_anchor_kpi.py`, gồm cả
  `strip_anchors()` để arm không rỗng, và arm idempotency.

### B3. Dựng lại sạch `resolved_graph.json`

- **Vấn đề:** file hiện tại là kết quả tích tụ append-only nhiều lần chạy, không tái lập được
  (đã ghi nhận: 639 vs 624 `alignsWithIndicator`); số node lệch với file stats của chính nó (§1.1).
- **Cách làm:** `python src/run.py build_resolved` một lần sạch sau khi B1+B2 xong.
  Sau đó `neo4j_load --clear` + `neo4j_sync`.
- **Chi phí:** offline, 0đ (`entities --no-llm`).
- **Rủi ro:** node đánh số lại → **đã chứng minh an toàn ở §1.1** (dossier tái gắn 100%).
  Vẫn nên chạy `neo4j_sync --dry-run` trước và kiểm log tier: phải là `stable_id`/`text`, không được
  rơi xuống `positional`.
- **Xác minh:** so `quality --label after-dedupe` với `pre-deepening`; Q3 surplus phải về ~0.

### B4. Phân rã hub — làm ở TẦNG EXPORT, không sửa `resolved_graph.json` ✅ ĐÃ LÀM (2026-07-30)

- **Mâu thuẫn trong tài liệu gốc:** §4.2 vừa nói "rewire cạnh cũ qua node period" vừa nói
  "phải append-only, KHÔNG sửa step05". Hai điều này loại trừ nhau —
  `core/graph_patch.py:82` (`assert_append_only`) tồn tại đúng để chặn việc đó, vì `neo4j_load`
  khoá node theo chỉ số mảng. Giữ append-only ⇒ cạnh trực tiếp còn nguyên ⇒ hub vẫn 9.511 ⇒ R5 **không** nhúc nhích.
- **Cách giải quyết:** đưa việc reification vào **view export**
  (`src/esg_kg/export/export_kgc.py`, đăng ký là stage `11` trong `pipeline.py` —
  `python src/run.py export_kgc`), đúng nơi đã dự kiến thêm cạnh đảo `_inv` "chỉ trong
  dataset, không vào Neo4j". Tái dùng nguyên `esg_kg/metric/hub.py` (A1) để xác định cụm
  hub — không tự viết lại logic phát hiện hub — nên "hub" của stage này luôn khớp
  R5/Q7(d) của `quality.py`. Tránh được toàn bộ: append-only, thứ tự node, reload Neo4j,
  vô hiệu hoá dossier — đã xác nhận `resolved_graph.json` **byte-identical** trước/sau khi
  chạy `export_kgc` trên corpus AAA thật.
- **Số liệu đo THẬT trên `resolved_graph.json` hiện tại** (v1 chỉ bucket theo
  `(year, predicate)`, KHÔNG escalate khoá thứ ba — quyết định có chủ đích, xem dưới):

  ```
  Trước: 1 cụm hub (AAA), degree 9.511 (66% tổng số cạnh)
  Sau:   357 bucket, bucket lớn nhất 541 (dự đoán ban đầu trong tài liệu: 359 bucket / max 541 — khớp gần đúng)
  max_degree_after = 542 (= 541 thành viên + 1 cạnh bucketOf về hub)
  threshold_met = False (1 bucket vẫn vượt 500 — được báo cáo trung thực trong stats,
                          không cố ép cho khớp)
  ```

  Giảm degree tối đa từ 9.511 → 542, tức giảm **94,3%**, dù chưa đạt tuyệt đối ngưỡng
  R5 ≤ 500. Người dùng đã xác nhận: không đạt đúng 500 vẫn là cải thiện chấp nhận được,
  nên **không escalate khoá thứ ba (`source_doc`) trong v1** — có thể làm sau nếu cần ép
  bucket 2022×reportsKPI xuống dưới ngưỡng.
- **Chi phí thực tế:** offline, 0đ, đã xong trong 1 phiên làm việc (thấp hơn ước tính ~2 ngày
  ban đầu nhờ tái dùng `metric/hub.py` có sẵn từ A1 thay vì viết lại logic cụm hub).
- **Kiểm chứng:** `test/test_export_kgc.py` (7 arm, tất cả PASS) — bao gồm: cụm dưới
  ngưỡng không bị đụng, không rò rỉ bucket giữa 2 issuer (tính chất sống còn khi scale
  nhiều công ty — nhóm D), input không bị mutate, output xác định (chạy 2 lần ra kết quả
  giống hệt), mọi node/cạnh mới đều gắn cờ `is_synthetic` (P7 — chặng qua bucket không có
  câu nguồn thật, không được trình bày như một bước suy luận trích dẫn được), `HubBucket`
  không bao giờ xuất hiện trong `config/schema.json` (không phải thực thể T1/T2/T3), và
  arm corpus thật xác nhận `resolved_graph.json` không bị ghi đè.

---

## 4. Nhóm C — Cần chạy lại AAA (đã được phép)

### C1. `claim_id` deterministic — TIÊN QUYẾT, làm trước mọi lần chạy lại step02 ⚠

- **Vấn đề:** `claim_id` hiện do LLM tự đặt.
- **Bằng chứng:** §1.1 — nó đang là thứ duy nhất giữ 1.093 dossier còn neo được.
- **Cách làm:** sinh `claim_id` bằng hàm thuần từ nội dung + provenance
  (ví dụ hash của `source_doc` + `page` + `sentence_index` + text chuẩn hoá), thay vì để LLM đặt.
  Đây chính là GitHub issue #2 mà `CLAUDE.md` đã ghi là cổng chặn re-extraction.
- **Chi phí:** ~1 ngày + test.
- **Xác minh:** `test/test_claim_id_deterministic.py` — cùng câu nguồn, hai lần chạy khác nhau
  (kể cả LLM trả text khác) phải ra cùng `claim_id`; và `claim_id` phải duy nhất trên corpus thật
  (hiện 1.217/1.217 duy nhất — không được làm tệ đi).
- **Không có C1 thì không được chạy lại `extract_triples`.**

### C2. Neo ngay tại lúc trích xuất, thay vì vá offline

- **Vấn đề:** B2 là gazetteer hậu kỳ, recall hạn chế bởi khớp chuỗi.
- **Cách làm:** bổ sung vào prompt `extract_triples` yêu cầu phát ra trực tiếp
  `observedAtFacility`, `enforcedBy`, `mentionsFacility` khi câu nguồn có nêu.
  `CLAUDE.md` đã ghi nhận hướng này ("New extractions get anchors from the extract_triples prompt instead").
- **Rủi ro:** đụng prompt trả phí. Bắt buộc pin lại byte-for-byte theo khuôn
  `test/test_step02_language_guard.py` và giữ ràng buộc tiếng Việt của issue #6.
- **Xác minh:** so Q7(e) trước/sau trên cùng tập tài liệu.

### C3. Giảm thiên lệch hình sao ngay từ prompt (điều tra, chưa phải quyết định)

- **Vấn đề gốc:** trích xuất theo trang ⇒ thực thể duy nhất trên mọi trang là issuer ⇒ mọi cạnh
  đổ về issuer. Hiện **chỉ 34,0% cạnh không chạm hub**.
- **Việc cần làm trước tiên là ĐO, không phải sửa:** kiểm xem prompt hiện tại có đang *khuyến khích*
  triple lấy issuer làm chủ ngữ hay không, và bao nhiêu % triple giữa hai thực thể **không phải**
  issuer đang bị bỏ sót (ví dụ `Facility locatedIn Location`, `Product manufacturedAt Facility`,
  `Person worksAt Organization`).
- **Đích đo được:** nâng tỉ lệ cạnh không chạm hub từ 34,0% lên ≥ 45%.
- **Rủi ro:** đây là thay đổi prompt sâu nhất trong kế hoạch; làm sau cùng trong nhóm C,
  và chỉ khi A2 đã cho thấy R1/R1′ còn thiếu nhiều sau B.

### C4. Bổ sung conduct đúng khoảng thời gian 2015–2023

- **Vấn đề:** §1.2 — conduct dồn vào 2025–2026 trong khi claim dồn vào 2018–2023.
  Cộng với 31,6% claim không có candidate và 91,6% claim `unverified`.
- **Đây là nút thắt thật của sản phẩm**, không phải nút thắt của retriever: không retriever nào
  tìm được bằng chứng không tồn tại trong đồ thị.
- **Cách làm:** `esg_news_crawler` với khoảng ngày mục tiêu 2015–2023 cho AAA; sau đó
  `preprocess_news` → `extract_triples --source news`.
- **Chi phí:** crawl + LLM (dùng `--provider openai` vì Gemini đang bị chặn billing).
- **Xác minh:** Q4 conduct pool > 124; Q7(d) tăng — đây là **mục duy nhất trong kế hoạch có thể
  nâng Q7(d) một cách thực chất**.

---

## 5. Nhóm D — Scaling nhiều công ty

### D1. Sàng lọc công ty ứng viên bằng số node T1 dùng chung (làm TRƯỚC khi crawl)

- **Bề mặt join đã đo:** chỉ 9,7% node (1.010/10.425) nằm ở lớp có thể trùng giữa hai công ty:

  ```
  StandardIndicator  67   ← 35 node là trục TT96/GRI cố định: chắc chắn dùng chung
  Location          248   ← tỉnh/thành trùng; cơ sở riêng thì không
  Regulation        220   ← quy định VN: khả năng trùng cao
  Standard          212   ← ISO...: cao
  Certification      92   ← cao
  Material           74   ← trung bình
  Authority          58   ← cơ quan nhà nước: cao
  Country            39   ← chắc chắn trùng
  ```

- **Xương sống pivot mạnh nhất đã có sẵn:** trục chỉ số hiện mang 639 `alignsWithIndicator` +
  641 `measuredUnder`, đều hub-free — chính nó đã kéo Q7(c) từ 25,1% lên 34,9%.
  Thêm công ty tức là dồn thêm tải lên đúng xương sống này.
- **Cách làm:** script offline đếm số tên chuẩn hoá trùng giữa AAA và từng ứng viên,
  **trước** khi tải báo cáo. Chọn theo số pivot dùng chung, không theo vốn hoá.
- **Chi phí:** 0đ.

### D2. Phân biệt "bằng chứng conduct" và "so sánh ngang hàng" trong `claims_vs_conduct`

- **Vấn đề ngữ nghĩa:** đường liên công ty `claim AAA → TT96-6.1.1 ← KPI công ty B` là
  **so sánh ngang hàng**, không phải bằng chứng về hành vi của AAA. Tự nó không thể
  supports/contradicts một claim của AAA.
- **Cách làm:** retrieval khi phục vụ phải **giới hạn theo công ty**, hoặc gắn nhãn loại bằng chứng
  `peer_benchmark` tách khỏi `conduct`. Ngược lại, khi **huấn luyện** walker thì đường liên công ty
  hoàn toàn dùng được (link prediction có ground truth miễn phí).
- **Rủi ro nếu bỏ qua:** đốt ngân sách adjudication cho candidate không trả lời được câu hỏi,
  và làm hỏng framing advisory trong `docs/SYSTEM_DESIGN.md`.

### D3. Đo lại và chốt cổng

Sau mỗi công ty thêm vào: chạy `quality --label after-<n>-companies`, theo dõi R1, R1′ (đã sửa theo A1), R5, R7, Q7(d).

---

## 6. Không làm / hoãn

| Việc | Lý do |
|---|---|
| Rewire hub **bên trong** `resolved_graph.json` | Phá `assert_append_only` + khoá node theo chỉ số mảng của `neo4j_load`. Làm ở tầng export (B4). |
| Xây `export_kgc` / `train_ssrl` / `reason_and_serve` ngay | Chưa qua cổng R1. Xây trước là xây trên đồ thị vi phạm tiền đề. |
| Dựa vào "novelty bitemporal" | `recorded_at` có mặt 100% cạnh nhưng chỉ trùng năm với `valid_from` **65,5%**, và giá trị phổ biến nhất là năm báo cáo + `2026-07-21` (ngày chạy pipeline, 749 cạnh do stage `indicators` đóng dấu). Đây là timestamp **dẫn xuất**, chưa phải trục knowledge-time độc lập. Muốn giữ luận điểm này thì phải lấy `recorded_at` từ ngày công bố thật trước đã. |
| Kỳ vọng scaling sửa được median degree / R5 | §1.3 — cả hai đều không nhúc nhích khi thêm công ty. |
| Dùng R1 = 46,8% / R1′ = 26,9% làm cổng | Chưa tự đo được trong repo (§0). Chờ A2. |

---

## 7. Thứ tự thực thi và cổng

```
A1 → A2 → A3            [đo, offline, ~1,5 ngày]
   └─ CHỐT: quality --label pre-deepening   ← cột "TRƯỚC", commit lại

B1 → B2 → B3            [sửa offline, ~3 ngày, 0đ]
   └─ CHỐT: quality --label after-offline-fixes
      Kỳ vọng: Q3 surplus → ~0 · Q7(e) tăng · Q7(d) gần như đứng yên (§1.2)

C1                      [tiên quyết, ~1 ngày]  ⚠ KHÔNG chạy lại step02 trước khi xong
   └─ C2 → C4 → (C3 nếu A2 cho thấy còn thiếu)
      └─ CHỐT: quality --label after-rerun-aaa
         Kỳ vọng: Q7(d) tăng thật nhờ C4

B4 ✅ ĐÃ LÀM             [phân rã hub ở tầng export — python src/run.py export_kgc]
   └─ CHỐT: max degree 9.511 → 542 (357 bucket, -94,3%), threshold_met=False (chấp nhận được)

D1 → (scale 3–5 cty) → D2 → D3
   └─ CỔNG CUỐI: R1 ≥ 80%, R1′ ≥ 50%, R5 ≤ 500
      Nếu không đạt: DỪNG, không xây tầng agent.
```

---

## 8. Giao thức đo và kiểm thử

- Mọi thay đổi đều chạy `quality` với `--label` trước và sau; commit cả hai file JSON/MD.
- Test viết trước, offline, plain `assert`, chạy từ repo root — không LLM, không Neo4j, không mạng.
- Đụng vào step03/03b/03c/05/05b/05c/08 ⇒ chạy lại `test/test_temporal_invariants.py`.
- Sửa `config/schema.json` (mục B2 cần) ⇒ chạy lại `test/test_schema_contract.py`.
- Sửa helper trong `core/` ⇒ chạy lại `test/test_esg_kg_equivalence.py`.
- Trước mỗi lần `neo4j_sync` sau khi đánh số lại node: chạy `--dry-run` và **kiểm log tier** —
  phải là `stable_id` / `text`, không được rơi xuống `positional`.

### Lệnh hay dùng

```bash
python src/run.py quality --label pre-deepening          # cột TRƯỚC
python src/run.py build_resolved --dry-run               # xem trước, rồi bỏ --dry-run
python src/run.py neo4j_load --clear
python src/run.py neo4j_sync --dry-run                   # kiểm tier trước khi ghi thật
python src/run.py quality --label after-offline-fixes    # cột SAU
```

---

## 9. Tóm tắt: điều gì cải thiện được cái gì

| Nhóm | Nâng được | KHÔNG nâng được |
|---|---|---|
| A (đo) | độ tin cậy của mọi so sánh sau đó | bản thân đồ thị |
| B (offline) | Q3, Q7(e), R5 (qua B4), median degree | Q7(d) — thiếu dữ liệu, không thiếu cấu trúc |
| C (chạy lại AAA) | Q7(e) qua C2, **Q7(d) qua C4**, an toàn re-run qua C1 | R5, median degree |
| D (scale) | R1′, R7, to-many ratio, số truy vấn huấn luyện | **R5 và median degree** (§1.3) |

Thông điệp khi báo cáo: **B và D sửa cấu trúc; chỉ C4 sửa được độ phủ bằng chứng.**
Tách bạch hai loại cải thiện này là điểm mạnh của bài, không phải điểm yếu — nó cho thấy đã đo được
chính xác cái gì cấu trúc không tự giải quyết nổi.
