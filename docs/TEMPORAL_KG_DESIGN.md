# Nguyên tắc thiết kế Temporal Knowledge Graph cho hệ thống bằng chứng greenwashing

> **Trạng thái (cập nhật 2026-07-15): ĐÃ TRIỂN KHAI các phần thuộc pipeline hiện có.**
> Cụ thể: **⓪** `src/step00_graph_quality_report.py` đo Q1–Q8 (baseline + after trong
> `graph_output/quality/`); **P1** `identity_keys` đã sửa trong `config/schema.json`
> (Location GIỮ `country`); **P2** step05 giữ `valid_from` trên node T2, schema-doc đã
> sửa khớp; **P3** prompt step02 (report + news) đã thêm luật neo ≥ 2 + vá offline bằng
> `src/step03b_anchor_kpi_facilities.py`; **P4** step03 có pha bất biến thời gian
> (`--renormalize`) và step05 ép bất biến `is_current`/gộp version theo mốc ngày.
> Kết quả đo sau khi rebuild offline: Q2 vi phạm 1.098 → **1** (một lỗi dữ liệu
> `valid_from>valid_to` thật, được cảnh báo đúng thiết kế); `Standard` 331 → 215 node;
> T2 có `valid_from` 0% → 87,7%; KPI bậc ≥ 2 4,1% → 5,3% (vá offline chỉ phủ được các
> KPI có câu nguồn — đạt mốc ≥ 30% cần trích xuất lại bằng prompt P3 mới).
> **P5/P6/P7-mở-rộng/P8** là ràng buộc thiết kế cho step11/12/13 (tầng SSRL) — các
> script đó **chưa tồn tại**, nên chưa có code để áp; đã được ghi thành ràng buộc trong
> `SSRL_REASONING_LAYER.md` (§4.6, §4.7, §5.3, §7.2) để bắt buộc tuân thủ khi xây.
> Các con số "hiện trạng" bên dưới là số đo **trước** khi sửa (build 2026-07-04), giữ
> nguyên làm ảnh chụp baseline.
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) ·
> [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) ·
> [`SSRL_REASONING_LAYER.md`](./SSRL_REASONING_LAYER.md)
>
> **Vai trò của tài liệu này:** `SSRL_REASONING_LAYER.md` chẩn đoán *triệu chứng* (đồ thị
> hình sao, 20,3% cạnh huấn luyện được) và đề xuất *thuốc* (sửa `identity_keys`, reify
> keyword, đa công ty). Tài liệu này trả lời câu hỏi sâu hơn: **những nguyên tắc thiết kế
> temporal-KG nào đã bị vi phạm để sinh ra các triệu chứng đó**, và **bộ thuộc tính chất
> lượng (quality attributes) nào** phải được theo dõi để đồ thị vừa đúng về nghiệp vụ
> (bằng chứng greenwashing kiểm toán được) vừa **suy luận được bằng SSRL** — chứ không chỉ
> truy vấn được bằng Cypher.

---

## 0. Tóm tắt cho người bận rộn (TL;DR)

| Câu hỏi | Trả lời ngắn |
|---|---|
| Tài liệu này thêm gì so với SSRL doc? | **8 nguyên tắc thiết kế** (P1–P8) + **bộ thuộc tính chất lượng đo được** — biến các sửa chữa rời rạc của Phase 0 thành một khung thiết kế có tên, có chuẩn, có cổng kiểm tra. |
| Phát hiện mới quan trọng nhất? | **(1)** Node sự kiện thiếu neo: chỉ **4,1%** `KPIObservation` có bậc ≥ 2 — trong khi `Investment` (được reify đúng cách, 2 neo) đạt **50,4%**. Sửa tại **prompt step02** rẻ hơn mọi cách hậu kỳ. **(2)** Hub AAA bậc **9.564** tự nó phá vỡ action space của RL walker — SSRL doc mới chỉ lo hub từ khóa. **(3)** BFS sinh nhãn của SSRL **phải chịu cùng mặt nạ thời gian** với lúc suy luận, nếu không SL dạy agent những đường đi mà RL bị cấm. |
| "Temporal action masking" (§7.2 SSRL doc) có mới không? | **Không hoàn toàn** — TITer/TimeTraveler (EMNLP 2021) đã ràng buộc action space theo thời gian trên TKG. Phần mới thật sự: **kết hợp nhãn BFS dày của SSRL với mặt nạ bitemporal** (`recorded_at` — "biết được lúc nào", không chỉ "xảy ra lúc nào"). Cần định vị lại đóng góp trước khi bảo vệ. |
| Lỗi dữ liệu mới tìm thấy? | `temporal_versions` chứa **nhiều version cùng `is_current=true`** do lệch định dạng ngày ("2011" vs "2011-01-01") — vi phạm bất biến bitemporal; cần ràng buộc toàn vẹn thời gian (P4). |
| Quality attribute mới cho bài toán này? | **Traversability (mức độ "đi được")** — median degree, % truy vấn che-cạnh trả lời được, % claim→conduct qua đường CẤU TRÚC. Văn liệu KG-quality (Zaveri et al.) không có nó; với hệ path-reasoning nó là thuộc tính sống còn. |

---

## 1. Vì sao cần một khung nguyên tắc, không chỉ một danh sách sửa chữa

`SSRL_REASONING_LAYER.md` §4 liệt kê 4 việc của Phase 0 (sửa `identity_keys`, reify keyword
có trần bậc, đa công ty, vá phía conduct). Từng việc đều đúng — nhưng chúng là **hệ quả**
của một số nguyên tắc chung chưa được phát biểu. Nếu không phát biểu nguyên tắc:

1. Các lỗi cùng loại sẽ **tái sinh** khi mở rộng (ví dụ: thêm class mới với
   `identity_keys` chứa `valid_from` — đúng cái lỗi vừa sửa).
2. Không có **tiêu chí nghiệm thu** khách quan: "đồ thị tốt" nghĩa là gì, đo bằng gì, ngưỡng
   bao nhiêu — trước khi đổ tiền LLM cho 3–8 công ty.
3. Khi bảo vệ luận văn, "em sửa 4 chỗ" yếu hơn nhiều so với "em xác định 8 nguyên tắc thiết
   kế temporal-KG cho bài toán path-reasoning không nhãn, chỉ ra thiết kế cũ vi phạm nguyên
   tắc nào, đo được hậu quả, và sửa theo nguyên tắc."

Khung dưới đây tổng hợp từ ba nguồn, chọn lọc những gì **khớp với bài toán này** (đồ thị
bitemporal hai kênh nói/làm, không ground truth, suy luận đường đi SSRL):

- **Văn liệu chất lượng KG** — Zaveri et al., khung 18 chiều chất lượng linked-data
  (intrinsic / contextual / representational / accessibility).
- **Văn liệu TKG reasoning** — TITer/TimeTraveler (RL trên TKG với ràng buộc thời gian),
  khảo sát TKG representation learning, và bài báo SSRL gốc (arXiv:2405.13640).
- **Kiến trúc temporal-KG thực dụng** — Zep/Graphiti (arXiv:2501.13956): mô hình bitemporal
  (event time vs ingestion time), **vô hiệu hóa cạnh thay vì xóa**, và tổ chức đồ thị
  **ba tầng** (episode / semantic entity / community).

---

## 2. Mô hình ba tầng node — nền của mọi nguyên tắc

Phát hiện §2.2 của SSRL doc ("đồ thị của tôi là HAI đồ thị chồng lên nhau") không phải tai
nạn — nó là dấu hiệu rằng schema đang trộn **ba loại node có bản chất khác nhau** vào một
mặt phẳng. Zep tách episode/semantic/community; với bài toán greenwashing, cách tách đúng là:

| Tầng | Bản chất | Class trong `config/schema.json` | Quy tắc danh tính | Quy tắc thời gian | Vai trò với SSRL |
|---|---|---|---|---|---|
| **T1 — Identity** (thực thể bền) | "Cái gì / ai" — tồn tại độc lập với tài liệu | `Organization`, `Person`, `Facility`, `Product`, `Material`, `Location`, `Country`, `Standard`, `Regulation`, `Authority`, `Community`, `ClaimKeyword` | **Phi thời gian** (P1): khóa = tên chuẩn hóa (+ jurisdiction nếu cần) | Thuộc tính đổi ⇒ `temporal_versions` / `supersedes`; **không bao giờ** tách node theo năm quan sát | **Xương sống đi được** — action space chính của agent |
| **T2 — Event / Observation** (sự kiện, quan sát) | "Điều gì xảy ra / đo được, lúc nào" | `KPIObservation`, `Emission`, `Waste`, `Penalty`, `Controversy`, `MediaReport`, `ThirdPartyVerification`, `Investment`, `Project`, `Initiative`, `CarbonOffsetProject` | Mỗi lần xuất hiện là một node (đúng như `OBSERVATION_CLASSES` của step05) — **thời gian là một phần bản chất** | `valid_from` = lúc sự kiện xảy ra; `date_uncertain` khi phải dùng ngày đăng bài | **Đích của suy luận** — nhưng phải có **≥ 2 neo cấu trúc** (P3) mới tới được bằng nhiều đường |
| **T3 — Assertion** (phát ngôn) | "Ai đó NÓI điều gì" | `SustainabilityClaim`, `Goal`, `ScienceBasedTarget`, `Certification`* | Mỗi phát ngôn một node; gắn chặt nguồn phát ngôn | Hai mốc: thời gian nói (`recorded_at`) và thời gian nội dung nói tới (`valid_from`) | **Điểm xuất phát của truy vấn** (`(claim, contradictedBy, ?)`) |

\* `Certification` nằm giữa T1/T3: *chứng chỉ ISO 14001* (loại chứng chỉ) là T1;
*việc AAA được cấp ISO 14001 giai đoạn 2021–2024* là một assertion/event. Cách xử lý đúng:
node `Certification` = T1 (khóa `["name"]`), còn thời hạn nằm trên **cạnh**
`holdsCertification.temporal_metadata` — xem P2.

Giá trị của bảng này: **mỗi tầng có quy tắc riêng** về khóa danh tính, versioning, và vai
trò trong action space. Mọi nguyên tắc P1–P8 dưới đây đều là hệ quả của việc tôn trọng ranh
giới ba tầng.

---

## 3. Tám nguyên tắc thiết kế (P1–P8)

Mỗi nguyên tắc: phát biểu → bằng chứng đo được → thay đổi cụ thể → ý nghĩa với SSRL.

### P1 — Danh tính phi thời gian (identity is timeless)

> **Node T1 được định danh bởi NÓ LÀ GÌ, không bao giờ bởi ta thấy nó lúc nào.**

- **Bằng chứng vi phạm (đo được):** `Standard.identity_keys = ["name","valid_from"]` ⇒
  310/331 node `Standard` (94%) là lá cô lập; "GRI" mỗi năm báo cáo một node
  (SSRL doc §2.4 — đã xác nhận đúng trên schema hiện tại).
- **Thay đổi:** như SSRL doc §4.1 (`Standard`/`Certification` → `["name"]`;
  `Regulation`/`Location` → chuẩn hóa tên). **Bổ sung 2 điểm SSRL doc chưa nói:**
  1. **`Location` nên GIỮ `country`** trong khóa. AAA có hoạt động xuất khẩu / công ty con
     nước ngoài; bỏ `country` sẽ gộp nhầm địa danh trùng tên xuyên quốc gia. Rủi ro gộp
     nhầm nội địa (2 xã trùng tên khác tỉnh) xử lý bằng chuẩn hóa `region`, không phải bằng
     cách bỏ khóa.
  2. Phát biểu thành **quy tắc cho class tương lai**: mọi class T1 mới **cấm** đưa trường
     thời gian vào `identity_keys`. Đây là bất biến thiết kế, không phải sửa chữa một lần.
- **Với SSRL:** node T1 hợp nhất là **cầu nối liên công ty** — điều kiện cần của Phase 0.

### P2 — Thời gian sống trên PHÁT BIỂU, không trên thực thể

> **Một fact tạm thời là một cạnh mang `temporal_metadata` (mô hình quadruple
> `(s, r, o, t)` của TKG), hoặc một node T2/T3. Node T1 không mang thời gian.**

- **Bằng chứng rằng đồ thị THỰC TẾ đã vận hành như vậy:** đo trên resolved graph —
  **99,9% cạnh có `temporal_metadata.valid_from`**, trong khi **0% node** có `valid_from`
  trong `properties` (thời gian node chỉ còn trong `temporal_versions` của 794 node).
  Tức là: schema *tuyên bố* "mọi node bitemporal" ([`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) §2.1)
  nhưng dữ liệu thật đã hội tụ về "thời gian trên cạnh". **P2 hợp thức hóa thực tế đó** thay
  vì để schema và dữ liệu mâu thuẫn ngầm.
- **Thay đổi:** khi bỏ `valid_from` khỏi khóa của `Standard`/`Certification`, thời hạn
  chuyển về đúng chỗ: `adoptsStandard` / `holdsCertification` **cạnh** mang
  `valid_from`/`valid_to` (đã có sẵn trong schema — không cần cạnh mới). Node T2 giữ
  `valid_from` như thuộc tính bản chất (ngày sự kiện). Cập nhật `SCHEMA_EXPLAINED.md` §2.1
  cho khớp: bitemporal đầy đủ là bất biến của **cạnh và node T2**, không phải của mọi node.
- **Với SSRL:** đây chính là điều kiện để **mặt nạ thời gian trên action space** (P8) hoạt
  động — agent lọc hành động theo `temporal_metadata` của cạnh, thống nhất một nơi duy nhất.

### P3 — Node sự kiện phải có ≥ 2 neo cấu trúc (n-ary event anchoring) ⭐ mới

> **Mỗi node T2 khi trích xuất phải được neo vào ÍT NHẤT HAI node T1 khác nhau bất cứ khi
> nào văn bản cho phép: tổ chức + (cơ sở | địa điểm | cơ quan | sản phẩm | đối tác).**

Đây là nguyên tắc **quan trọng nhất mà SSRL doc chưa có**, và nó tấn công thẳng gốc rễ của
"83,2% node là lá":

- **Bằng chứng (đo mới trên resolved graph):**

| Class T2 | Node | Bậc ≥ 2 | Vì sao |
|---|---|---|---|
| `KPIObservation` | 4.906 | **4,1%** | prompt step01/02 chỉ tạo `Organization —reportsKPI→ KPI`, dừng ở đó |
| `Goal` | 722 | 6,4% | chỉ `setsGoal` |
| `SustainabilityClaim` | 1.217 | 8,5% | chỉ `claims` (+ 163 `hasKeyword`) |
| `MediaReport` | 91 | 9,9% | chỉ `mentionsOrganization` |
| **`Investment`** | **282** | **50,4%** | được **reify đúng cách**: khóa `[investor, investee, date]`, nối cả 2 đầu |

  `Investment` là **bằng chứng nội tại** rằng mô hình neo-đa-chiều hoạt động ngay trong
  chính đồ thị này: cùng một pipeline, cùng một LLM, node được thiết kế 2 neo thì 50% đi
  được, node thiết kế 1 neo thì 4% đi được.
- **Thay đổi (rẻ nhất toàn Phase 0 tính trên tác dụng):** sửa **prompt step02** (cả bản
  report lẫn news): với mỗi node T2, *bắt buộc thử* phát các cạnh neo đã có sẵn trong schema
  — `observedAtFacility` (KPI→Facility, hiện 86,7% trả lời được!), `locatedIn`,
  `enforcedBy` (Penalty→Authority), `mentionsProduct`, `manufacturedAt` — khi câu văn nêu
  tên cơ sở/địa điểm/cơ quan. Không thêm class, không thêm nhãn cạnh mới; chỉ yêu cầu LLM
  dùng đủ những cạnh schema đã định nghĩa. Với dữ liệu ĐÃ trích xuất, có thể vá một phần
  offline: câu gốc còn nguyên (`source_id` → sentence), một pass regex/gazetteer tìm tên
  `Facility`/`Location` đã có trong đồ thị xuất hiện trong câu của KPI lá.
- **Với SSRL:** mỗi neo thứ hai tạo **một đường đi thay thế THẬT** (qua cấu trúc, không qua
  keyword) đến đúng lớp node "đám mây lá" — tăng trực tiếp mẫu huấn luyện dùng được
  (§2.2 SSRL doc) và tăng chỉ số cổng "% claim→conduct qua đường cấu trúc" (§6.1) **mà
  không dính bẫy calo rỗng** (§3.3): neo `observedAtFacility` mang thông tin token-overlap
  KHÔNG có.

### P4 — Toàn vẹn thời gian là ràng buộc cứng, không phải quy ước

> **Các bất biến bitemporal phải được kiểm tra bằng máy ở step03, như schema-validation:**
> `valid_from ≤ valid_to`; mỗi chuỗi version có **đúng một** `is_current=true`;
> ngày phải qua chuẩn hóa một định dạng; `date_uncertain` bắt buộc trên node T2 từ news.

- **Bằng chứng vi phạm (tìm thấy khi đo):** node AAA có `temporal_versions` chứa **hai
  version cùng `is_current=true`, cùng `valid_to=null`**, chỉ khác định dạng ngày
  ("2011" vs "2011-01-01") — cùng một fact bị tách thành hai version giả. Đây đúng loại lỗi
  làm hỏng cả truy vấn Cypher lẫn nhãn BFS (hai node/version cho một thực thể = đường đi
  giả).
- **Thay đổi:** thêm một **pha kiểm tra bất biến thời gian** vào step03 (thuần offline, 0đ):
  chuẩn hóa ISO `YYYY[-MM[-DD]]`, ép bất biến `is_current`, cảnh báo `valid_from > valid_to`,
  và **từ chối gộp version chỉ-khác-định-dạng-ngày**. Nguyên tắc "vô hiệu hóa, không xóa"
  (Zep): khi fact mới mâu thuẫn fact cũ, đóng `valid_to` của cũ — pipeline đã có `supersedes`
  cho việc này, chỉ cần dùng nhất quán.
- **Với SSRL:** nhãn BFS sinh trên đồ thị có version giả sẽ dạy agent những "đường tắt"
  không tồn tại; RL rất giỏi khai thác lỗi dữ liệu kiểu này (reward hacking trên đồ thị bẩn).

### P5 — Quản trị bậc (degree governance): mọi hub đều phải có chính sách

> **Không node nào được vào action space mà không có chính sách bậc: trần bậc, loại khỏi
> action space, hoặc chọn hành động theo kiểu phân cấp (relation-first).**

SSRL doc đã xử lý một nửa: trần `df ≤ 20` cho keyword hub (§3.2) và loại `Standard`/
`Regulation` toàn cục khỏi action space (§4.5). **Nửa còn thiếu — nghiêm trọng hơn:**

- **Hub lớn nhất là chính node ISSUER: AAA bậc 9.564.** Gần như mọi đường đi hữu ích
  (claim → … → conduct) đều phải **bước qua node AAA ở hop đầu tiên** (`claims⁻¹`).
  MINERVA/MultiHopKG khi gặp node bậc lớn sẽ **cắt/lấy mẫu action space** (thường
  200–400 hành động). Lấy mẫu đều trên 9.564 láng giềng ⇒ xác suất giữ được đúng láng giềng
  dẫn tới bằng chứng ≈ vài %. **Agent chết ở hop 1, trước khi kịp học bất cứ gì.** Đa công
  ty làm điều này **tệ hơn**, không đỡ hơn (mỗi issuer một siêu-hub).
- **Chính sách đề xuất cho node bậc lớn:** chọn hành động **hai bước — chọn QUAN HỆ trước,
  chọn ĐÍCH sau** (factored action space): tại AAA, agent chọn 1 trong ~40 nhãn quan hệ
  (`partnersWith`? `ownsFacility`? `subjectToPenalty`?…), rồi mới chọn đích trong nhóm đó
  (vài chục node). Đây là thay đổi ở **step12 (trainer)**, không đụng đồ thị; biến bậc
  9.564 thành 40 × ~240. Phương án dự phòng đơn giản hơn: lấy mẫu láng giềng **phân tầng
  theo nhãn quan hệ** thay vì đều.
- **Với Cypher/analyst:** không đổi gì — quản trị bậc là chính sách của **tầng suy luận**,
  đồ thị Neo4j giữ nguyên đầy đủ.
- **Node reference của trục chỉ tiêu (`StandardIndicator`, 2026-07): cùng chính sách.** 35 node
  chỉ tiêu là *cố ý* bậc cao — mọi KPI của một chỉ tiêu treo vào một node là chủ đích join
  (`STANDARD_INDICATOR_AXIS.md` §3). Nhưng đó là *vocabulary*, không phải *thực thể*, nên
  step00 loại chúng khỏi metric hub-free Q7 qua hằng `REFERENCE_CLASSES` (loại khỏi hub argmax
  và khỏi đường đi Q7(d), cùng cơ chế đang loại hub issuer). Không loại thì cạnh `partOf` mới —
  vốn đã nằm trong `STRUCTURAL_EDGES` — sẽ tự thổi phồng Q7(d), làm bẩn so sánh before/after.
  Đã kiểm chứng: claim→conduct structural giữ nguyên 8.0% qua thay đổi trục chỉ tiêu. Tầng SSRL
  về sau nên áp cùng chính sách factored action space cho `StandardIndicator` như cho issuer.

### P6 — Khả năng đi hai chiều thuộc về tầng dataset, không thuộc về DB

> **Cạnh nghịch đảo (40 → 80 quan hệ) chỉ được sinh trong bộ dữ liệu KGC xuất cho
> SSRL (step11), tuyệt đối không ghi vào Neo4j hay resolved graph.**

- **Vì sao tách:** Neo4j đã đi hai chiều được bằng Cypher (`<-[:claims]-`); ghi cạnh đảo
  vào DB sẽ phá các truy vấn/thống kê hiện có và nhân đôi số cạnh của mọi tài liệu đã viết.
  Ngược lại, RL walker **cần** cạnh đảo tường minh trong action space (SSRL doc §5.2 đúng).
- **Thay đổi:** quy ước đặt tên `_inv` + cờ `is_inverse` trong file dataset của step11;
  tài liệu hóa ranh giới này ngay trong docstring step11.

### P7 — Xuất xứ là thuộc tính hạng nhất, ở mọi tầng suy luận

> **Mọi node/cạnh giữ `source_type`, `source_id`, `page`, `sentence_index`,
> `source_domain`; mọi SUY LUẬN mới (kể cả đường đi của agent) phải mang được xuất xứ
> của TỪNG CẠNH nó đi qua.**

- Pipeline hiện tại đã làm rất tốt phần node/cạnh (một điểm mạnh thật sự của thiết kế —
  giữ nguyên). **Phần mở rộng cho SSRL:** `reasoning_path` trong dossier (SSRL doc §5.7)
  phải serialize **danh sách cạnh với đầy đủ provenance từng cạnh**, không chỉ danh sách
  node — vì giá trị bán được của path-evidence là *"phóng viên kiểm tra được từng bước"*:
  mỗi bước chỉ về đúng câu văn (`source_id` → trang → câu) đã sinh ra cạnh đó.
- Đây cũng là **hàng rào chống ảo giác**: LLM adjudicator chỉ được phán xử trên văn bản
  của các node ở hai đầu đường đi — đường đi do agent tìm, văn bản do provenance cung cấp,
  LLM không tự bịa được mắt xích nào.

### P8 — Suy luận tôn trọng thời gian XUYÊN SUỐT: huấn luyện như suy luận ⭐ sửa lỗi tiềm ẩn

> **Cùng một mặt nạ thời gian phải áp cho CẢ BA nơi: (a) BFS sinh nhãn SL, (b) action
> space lúc RL, (c) action space lúc inference. Mặt nạ dùng cả hai trục: `valid_from`
> (xảy ra lúc nào) và `recorded_at` (biết được lúc nào).**

- **Lỗ hổng trong SSRL doc:** §7.2 đề xuất che action space theo thời gian lúc suy luận,
  nhưng §5.3 mô tả BFS sinh nhãn trên **toàn bộ đồ thị không mặt nạ**. Nếu vậy, giai đoạn
  SL sẽ gán nhãn `1` cho những cạnh mà lúc RL/inference agent **bị cấm đi** (vd. đường qua
  bằng chứng 2024 cho truy vấn neo ở 2021) ⇒ mâu thuẫn SL↔RL, đúng loại lệch phân phối làm
  giai đoạn SL **phản tác dụng** (bài báo SSRL đã cảnh báo SL quá tay làm giảm hiệu năng).
  **Sửa:** step11 sinh nhãn BFS trên **đồ thị con thời gian** của từng truy vấn (chỉ cạnh
  có `valid_from ≤ t_query`, và nếu dùng trục knowledge-time: `recorded_at ≤ t_query`).
- **Định vị lại tính mới (quan trọng khi bảo vệ):** ràng buộc action space theo thời gian
  trên TKG **không mới** — TITer/TimeTraveler (EMNLP 2021) đã làm (action =
  (relation, entity, timestamp), relative-time encoding, time-shaped reward). Đóng góp
  đúng của đề tài là: **(a)** đem **nhãn BFS dày của SSRL** vào thiết lập thời gian —
  bài báo SSRL gốc chỉ làm trên KG tĩnh; **(b)** mặt nạ **bitemporal hai trục** — TITer chỉ
  có event-time, không có `recorded_at` ("hồi 2021 ta ĐÃ BIẾT gì?" ≠ "hồi 2021 ĐÃ XẢY RA
  gì?" — với greenwashing, trục "biết được lúc nào" mới là trục nhân quả đúng, vì báo cáo
  2021 không thể bị buộc tội mâu thuẫn với thông tin chỉ xuất hiện 2024); **(c)** cân bằng
  nhãn theo quan hệ (SSRL doc §7.1 — bài báo gốc tự nhận là future work). Ba điểm này
  đứng vững; "temporal masking" nói chung thì không.

---

## 4. Thuộc tính chất lượng (quality attributes) — đo gì, ngưỡng nào

Chọn lọc từ khung Zaveri et al. (18 chiều) những chiều **có ý nghĩa với bài toán này**, bổ
sung 2 nhóm đặc thù (chất lượng thời gian; traversability). Mỗi thuộc tính có **chỉ số đo
bằng máy** — đề xuất gom toàn bộ vào một script mới `src/step00_graph_quality_report.py`
(chạy offline trên resolved graph, 0đ, chạy trước và sau mọi thay đổi Phase 0).

| # | Thuộc tính | Định nghĩa cho bài toán này | Chỉ số đo | Hiện trạng (đo 2026-07) | Ngưỡng/cổng đề xuất |
|---|---|---|---|---|---|
| Q1 | **Accuracy** (intrinsic) | Node/cạnh phản ánh đúng câu nguồn | tỉ lệ lỗi trên mẫu tay 30–50 node/lần; lỗi OCR trong `name` (đã thấy "MÔI TRƢỜNG" — ký tự Ư hỏng từ PDF) | chưa đo có hệ thống | pass chuẩn hóa Unicode NFC + soát mẫu ≥ 90% đúng |
| Q2 | **Consistency** | Hợp lệ theo schema + **bất biến thời gian P4** | % cạnh qua validator step03; số vi phạm `is_current`/`valid_from>valid_to`/định dạng ngày | schema-consistency đã có (step03); temporal-consistency **chưa có** — đã thấy vi phạm thật | 0 vi phạm bất biến P4 |
| Q3 | **Conciseness** (không dư thừa) | Một thực thể T1 = một node | số node T1 trùng tên chuẩn hóa; phân mảnh `Standard` | 310/331 `Standard` là lá cô lập (phân mảnh do P1) | sau P1: node T1 trùng tên ≈ 0; `Standard` distinct ≤ ~40 |
| Q4 | **Completeness** (contextual) | Đủ bằng chứng ở CẢ HAI phía nói/làm | đếm node conduct: `Controversy`/`Penalty`/`MediaReport`; coverage.csv per ticker | **2 / 4 / 91** (⚠ SSRL doc §2.3 ghi 0/0/16 — số liệu cũ, cần cập nhật lại doc) | mỗi công ty pilot: ≥ 10 node conduct độc lập (không phải PR) |
| Q5 | **Timeliness / temporal accuracy** | Fact gắn đúng thời điểm thật | % cạnh có `valid_from` (99,9% ✅); % node T2-news có `date_uncertain=true` | 99,9% cạnh có thời gian; date_uncertain đã chảy tới dossier ✅ | giữ ≥ 99%; % date_uncertain hiển thị trong mọi báo cáo |
| Q6 | **Verifiability / provenance** | Truy ngược tới câu văn | % node có `source_id`+`sentence_index` | ~100% ✅ (bất biến từ đầu pipeline) | giữ 100%; mở rộng sang `reasoning_path` (P7) |
| Q7 | **Traversability** ⭐ (mới — reasoning-readiness) | Đồ thị đủ đặc/đa đường cho path reasoning | (a) bậc trung vị; (b) % lá; (c) % truy vấn che-cạnh trả lời được; (d) **% claim→conduct qua đường có ≥1 cạnh cấu trúc** (cổng §6.1 SSRL doc); (e) % node T2 bậc ≥ 2 (P3) | (a) 1; (b) 83,2%; (c) 20,3%; (d) 16,0%; (e) KPI 4,1% | cổng đi tiếp SSRL: (d) tăng rõ rệt khi 1→3 công ty; (e) ≥ 30% sau khi sửa prompt P3 |
| Q8 | **Độc lập nguồn** (đặc thù greenwashing) | Bằng chứng "verify" phải độc lập với công ty | số cạnh `verifiedBy` bị guard chặn; % conduct node từ domain công ty | guard đã chạy (18 bị chặn ở P4) ✅ | mọi dossier hiển thị tỉ lệ PR/độc lập của evidence |

**Điểm cần nhấn:** Q7 là thuộc tính **không tồn tại trong văn liệu KG-quality cổ điển** —
nó chỉ xuất hiện khi đồ thị phải phục vụ path-based reasoning. Việc đề tài **định nghĩa và
đo** nó (SSRL doc §2 đã đo (a)–(d) mà chưa đặt tên) chính là một đóng góp phương pháp nhỏ
nhưng bảo vệ được: *"chất lượng temporal-KG cho suy luận đường đi cần thêm chiều
traversability, với 5 chỉ số đo cụ thể."*

---

## 5. Bảng đối chiếu: thiết kế hiện tại vs nguyên tắc

| Nguyên tắc | Hiện trạng | Khoảng cách | Sửa ở đâu | Chi phí |
|---|---|---|---|---|
| P1 danh tính phi thời gian | ❌ `Standard`/`Certification` khóa theo `valid_from` | 94% `Standard` phân mảnh | `config/schema.json` + chạy lại step05 `--no-llm` → step06 | 0đ, phút |
| P2 thời gian trên phát biểu | ⚠ dữ liệu đã đúng (99,9% cạnh), schema-doc nói khác | mâu thuẫn ngầm doc↔data | sửa `SCHEMA_EXPLAINED.md` §2.1 + quy ước step02 | 0đ |
| P3 neo ≥ 2 cho node T2 | ❌ KPI 4,1% bậc≥2 (Investment 50,4% chứng minh làm được) | gốc rễ của 83,2% lá | prompt step02 (report + news) + vá offline gazetteer | 0đ offline; LLM chỉ khi trích xuất mới |
| P4 toàn vẹn thời gian | ❌ chưa có check; đã thấy version giả `is_current` kép | đường đi giả, version giả | step03 thêm pha temporal-invariant | 0đ |
| P5 quản trị bậc | ⚠ SSRL doc có trần keyword; **chưa có chính sách cho hub issuer 9.564** | agent chết ở hop 1 | step12 factored action space (quan hệ trước, đích sau) | thiết kế trainer |
| P6 cạnh đảo ở tầng dataset | ✅ (chưa build, nhưng ranh giới cần ghi rõ) | — | step11 (`_inv`, `is_inverse`) | 0đ |
| P7 provenance hạng nhất | ✅ node/cạnh; ⚠ `reasoning_path` chưa đặc tả provenance từng cạnh | dossier path chưa kiểm toán được từng bước | đặc tả output step13 | 0đ |
| P8 mặt nạ thời gian xuyên suốt | ❌ SSRL doc chỉ che lúc inference; BFS nhãn chưa che; novelty cần định vị lại vs TITer | SL dạy đường bị cấm | step11 BFS trên đồ thị con thời gian; sửa SSRL doc §5.3+§7.2 | 0đ (thiết kế) |

---

## 6. Trình tự thực thi (điều chỉnh Phase 0 của SSRL doc §6.2)

Chỉ **thêm/chèn** vào trình tự đã có, không thay thế:

```
⓪  [MỚI] step00_graph_quality_report.py — đo Q1–Q8 baseline TRƯỚC khi sửa   [0đ, 1 buổi]
     → đây là "ảnh chụp trước" cho mọi so sánh trong luận văn

①  Sửa identity_keys (P1, GIỮ country cho Location) + reify keyword df≤20
     + [MỚI] pha temporal-invariant trong step03 (P4)                        [0đ]
     → chạy lại step03 → step05 --no-llm → step06 → step00 đo lại

①b [MỚI] Sửa prompt step02 theo P3 (neo ≥2 cho node T2)                      [0đ code]
     + vá offline: gazetteer Facility/Location trên câu gốc của KPI lá       [0đ]
     → Q7(e) kỳ vọng tăng mạnh nhất toàn Phase 0 mà không tốn LLM cho dữ liệu cũ

②  Port cascade OpenAI vào step01/02 (như SSRL doc — Gemini đang 403)        [1–2 ngày]

③  Pilot 3 công ty cùng ngành → full pipeline (prompt ĐÃ sửa P3
     ⇒ dữ liệu mới sinh ra đã đúng chuẩn neo, không phải vá lại)             [$$]

④  🚦 CỔNG = Q7(d): % claim→conduct qua đường cấu trúc, 1 cty (16,0%) → 3 cty
     + [MỚI] điều kiện phụ: Q7(e) ≥ 30% và Q2 = 0 vi phạm

⑤  step11/12/13 theo SSRL doc, với 3 ràng buộc mới:
     step11: BFS nhãn trên đồ thị con thời gian (P8) + cạnh đảo _inv (P6)
     step12: factored action space cho hub issuer (P5)
     step13: reasoning_path mang provenance từng cạnh (P7)
```

---

## 7. Nhận xét chất lượng về `SSRL_REASONING_LAYER.md` (kết quả review)

**Những gì đứng vững (đã kiểm chứng độc lập):** toàn bộ số liệu §2 tái lập chính xác
(10.573/13.008; bậc trung vị 1; 83,2% lá; hub 9.564; `reportsKPI` 37,6%; `verifiedBy` 39,
`contradictedBy` 2). Phương pháp tự phản biện bằng mô phỏng (§3, bẫy calo rỗng), việc đổi
chỉ số cổng sang đường-cấu-trúc (§6.1), lệnh cấm vòng lặp luẩn quẩn (§5.6), và cách đọc
đúng "self-supervised = không cần nhãn người" (§5.1) đều là những phần **mạnh, giữ nguyên**.

**Bốn điểm cần sửa/bổ sung trong SSRL doc:**

1. **§7.2 (temporal action masking)** — hạ giọng "mở rộng thực sự": TITer/TimeTraveler đã
   ràng buộc action space theo thời gian trên TKG từ 2021. Định vị lại theo P8: mới ở
   *nhãn BFS dày + mặt nạ bitemporal 2 trục (`recorded_at`) + cân bằng quan hệ*.
2. **§5.3 (BFS sinh nhãn)** — thêm ràng buộc: BFS chạy trên **đồ thị con thời gian** của
   truy vấn, nếu không SL mâu thuẫn với RL bị che (P8).
3. **§4 (danh sách sửa Phase 0)** — thiếu hai mục: **neo ≥ 2 cho node T2** (P3 — đòn rẻ
   nhất, đo được ngay bằng Q7(e)) và **chính sách hub cho chính node issuer** (P5 — trần
   keyword không cứu được action space 9.564 tại hop 1).
4. **§2.3 (số liệu conduct)** — đã cũ: đồ thị hiện tại có `Controversy` 2 / `Penalty` 4 /
   `MediaReport` 91 (không phải 0/0/16). Kết luận "phía LÀM mỏng" vẫn đúng, nhưng số cần
   cập nhật, và nên ghi kèm **phiên bản đồ thị** (ngày build) cho mọi bảng số để tránh lệch
   giữa các lần rebuild.

---

## 8. Tài liệu tham khảo

- Zaveri, A. et al. — *Quality Assessment for Linked Data: A Survey* (khung 18 chiều chất
  lượng; nhóm intrinsic/contextual/representational/accessibility).
- Sun, H. et al. — *TimeTraveler: Reinforcement Learning for Temporal Knowledge Graph
  Forecasting* (EMNLP 2021, arXiv:2109.04101) — RL walker với action space ràng buộc thời
  gian, relative-time encoding, time-shaped reward. **Phải cite khi nói về temporal masking.**
- Ma, R. et al. — *Knowledge Graph Reasoning with Self-supervised Reinforcement Learning*
  (arXiv:2405.13640) — bài báo SSRL gốc (KG tĩnh).
- Rasmussen, P. et al. — *Zep: A Temporal Knowledge Graph Architecture for Agent Memory*
  (arXiv:2501.13956) — bitemporal event/ingestion time, vô hiệu hóa cạnh thay vì xóa,
  kiến trúc subgraph ba tầng (nguồn cảm hứng cho mô hình T1/T2/T3 §2).
- Khảo sát TKG: *A Survey on Temporal Knowledge Graph: Representation Learning and
  Applications* (arXiv:2403.04782).
- Nội bộ: [`SSRL_REASONING_LAYER.md`](./SSRL_REASONING_LAYER.md) ·
  [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) · [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) ·
  [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) ·
  [`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md).

---

*Tài liệu thiết kế, cặp đôi với `SSRL_REASONING_LAYER.md`. Các nguyên tắc ⓪/P1/P2/P3/P4
đã được áp dụng lên schema và pipeline ngày 2026-07-15 (xem khối Trạng thái ở đầu tài
liệu); P5–P8 chờ step11/12/13. Mọi số liệu "hiện trạng" trong thân tài liệu đo trên
`graph_output/resolved/resolved_graph.json` build 2026-07-04 (baseline trước khi sửa);
ảnh chụp trước/sau nằm ở `graph_output/quality/`.*
