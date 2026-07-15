# SSRL — Tầng suy luận (reasoning layer) cho đồ thị ESG

> **Trạng thái:** Đề xuất thiết kế (proposal). **Chưa có thay đổi nào** được thực hiện lên
> `config/schema.json`, lên đồ thị, hay lên code pipeline. Mọi con số trong tài liệu này đến
> từ **đo đạc thực tế** trên `graph_output/resolved/resolved_graph.json` hoặc từ **mô phỏng
> trên bộ nhớ** (không ghi file).
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) · [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md)
>
> **Bài báo tham chiếu:** Ma, Burns, Wang, Li, Du, El Shafey, Wang, Shafran, Soltau —
> *Knowledge Graph Reasoning with Self-supervised Reinforcement Learning* (arXiv:2405.13640v2).

---

## 0. Tóm tắt cho người bận rộn (TL;DR)

| Câu hỏi | Trả lời ngắn |
|---|---|
| Tôi đang cải tiến cái gì? | Thêm **tầng suy luận đường đi (path-based reasoning)** vào đồ thị ESG, dùng SSRL. |
| Nó cho tôi thêm năng lực gì? | Tìm **bằng chứng gián tiếp, đa bước** qua chuỗi cung ứng — thứ LLM adjudicator hiện tại **về cấu trúc không thể** làm. |
| Đầu ra có đổi không? | **Không.** Dossier / claim ledger / demo UI giữ nguyên. Chỉ thêm trường `reasoning_path` tùy chọn. |
| Vấn đề lớn nhất? | Đồ thị là **hình sao**. Chỉ **20,3%** cạnh dùng được để huấn luyện; bậc trung vị = **1**. |
| Không có nhãn thì train kiểu gì? | SSRL **không cần nhãn người**. Nhãn sinh tự động bằng **BFS trên chính các cạnh đã có**. |
| Sửa xong là đủ chưa? | **Chưa.** Đã mô phỏng: sửa schema + reify keyword (lành mạnh) vẫn **trượt cổng** trên 1 công ty. **Đa công ty là điều kiện CẦN.** |
| Bẫy lớn nhất? | **"Calo rỗng"** — làm đẹp chỉ số bằng siêu-hub từ khóa, trong khi agent chỉ học lại token-overlap. |

---

## 1. Ý tưởng thiết kế đồ thị hiện tại

### 1.1 Nguyên lý cốt lõi: đối xứng "Nói" vs "Làm"

Greenwashing là **khoảng cách giữa lời nói và hành động**. Hệ thống nạp **hai kênh độc lập**
vào **cùng một temporal knowledge graph**:

```
┌───────────────────────────────────────────────────────────────┐
│  KÊNH R — Báo cáo thường niên      →  PHÍA "NÓI" (claim side)  │
│  source_type = "report"                                        │
│  → SustainabilityClaim, Goal, KPIObservation (reported)        │
├───────────────────────────────────────────────────────────────┤
│              ↓  cùng một node Organization  ↓                  │
├───────────────────────────────────────────────────────────────┤
│  KÊNH N — Tin tức bên thứ ba       →  PHÍA "LÀM" (conduct side)│
│  source_type = "news"                                          │
│  → Controversy, Penalty, MediaReport, KPIObservation (observed)│
└───────────────────────────────────────────────────────────────┘
```

### 1.2 Ba đặc tính thiết kế

1. **Bitemporal** — node có `valid_from`/`valid_to`/`is_current`; cạnh có thêm `recorded_at`.
2. **Truy vết đến từng câu** — `source_pdf`, `page`, `sentence_index` giữ xuyên suốt.
3. **Không có ground truth** — Việt Nam không có bộ dữ liệu greenwashing gán nhãn ⇒ hệ thống
   **không** là classifier, **không** xuất điểm số, chỉ xuất **bằng chứng + nhận định tư vấn**.

---

## 2. Vấn đề: bốn phát hiện, tất cả đều đã ĐO

> **Phiên bản đồ thị:** mọi con số trong §2 đo trên
> `graph_output/resolved/resolved_graph.json` **build 2026-07-04** (10.573 node /
> 13.008 cạnh). Sau khi áp dụng Phase 0 (P1/P2/P3-offline/P4, build 2026-07-15) đồ
> thị là 10.362 node / 13.047 cạnh — so sánh trước/sau bằng
> `src/step00_graph_quality_report.py` (`graph_output/quality/`). Luôn ghi ngày build
> kèm mọi bảng số để tránh lệch giữa các lần rebuild.

### 2.1 Đồ thị là một HÌNH SAO

Đo trên đồ thị AAA (10.573 node / 13.008 cạnh / 40 quan hệ):

| Chỉ số | Giá trị |
|---|---|
| Bậc trung vị | **1** |
| Node lá (bậc = 1) | **8.798 / 10.573 = 83,2%** |
| Tỉ lệ đầu mút cạnh chạm node AAA | **36,8%** (bậc AAA = 9.564) |
| Claim tới bằng chứng **không qua** node AAA | **92 / 1.217 = 7,6%** |

⇒ **97,5% claim chỉ có ĐÚNG MỘT mẫu đường đi** tới bằng chứng:

```
SustainabilityClaim ←claims— Organization(AAA) —mentionsOrganization/reportsKPI→ ConductNode
```

Mọi ứng viên bằng chứng đều đến bằng **cùng một mẫu đường đi 2 bước** ⇒ đường đi mang **0 thông
tin phân biệt** ⇒ agent suy biến thành chấm điểm embedding node đích — đúng cái phương pháp mà
bài báo lập luận là *kém hơn* path-based.

Bài báo tự xác nhận cơ chế: mức cải thiện SSRL **tỉ lệ thuận với bậc đồ thị**.

| Dataset | # Fact | Bậc trung vị | SSRL cải thiện |
|---|---|---|---|
| FB15K-237 | 272.115 | **14** | Tốt nhất |
| NELL-995 | 154.213 | 1 | Tốt (phân bố quan hệ đều) |
| WN18RR | 86.835 | **2** | **Kém nhất** |
| **AAA của tôi** | **13.008** | **1** | *(dự đoán ≈ 0)* |

### 2.2 ⭐ Chỉ 20,3% cạnh dùng được để huấn luyện

Đây là **chỉ số quyết định**, và là thứ tôi phát hiện muộn nhất.

Trong SSRL, một mẫu huấn luyện = **che một cạnh `(e_s, r, e_q)` rồi bắt agent tìm lại `e_q`**.
Mẫu đó **chỉ dùng được nếu sau khi che vẫn còn đường đi khác**. Nếu `e_q` là node lá bậc 1,
che xong nó thành **mồ côi** ⇒ BFS trả rỗng ⇒ **vứt mẫu**.

Đo thực tế (che cả cạnh xuôi lẫn nghịch, tìm đường thay thế ≤ 3 bước):

| Nhóm | Quan hệ | % trả lời được |
|---|---|---|
| 💀 **Lá chết** | `reportsKPI` *(37,6% tổng cạnh!)* | **3,9%** |
| | `claims` *(quan hệ quan trọng nhất)* | **1,0%** |
| | `setsGoal` | 0,8% |
| | `adoptsStandard` | 1,5% |
| | `subjectToRegulation` | 4,2% |
| ✅ **Xương sống đi được** | `observedAtFacility` | **86,7%** |
| | `locatedIn` | 70,1% |
| | `ownsFacility` | 67,5% |
| | `isIn` | 64,5% |
| | `partnersWith` | **50,8%** |
| | `producedBy` | 42,8% |
| | `holdsCertification` | 30,6% |
| | **TỔNG** | **20,3%** (2.642 / 13.008) |

**Đồ thị của tôi thực chất là HAI đồ thị chồng lên nhau:**

1. **Bộ xương cấu trúc ĐI ĐƯỢC** (`Facility`/`Location`/`Organization`/sở hữu/đối tác) — 50–87%.
2. **Đám mây node lá QUAN SÁT** (`KPIObservation`, `SustainabilityClaim`, `Goal`) treo lủng
   lẳng vào AAA — **1–4%, hoàn toàn không đi được**.

Nhóm (2) chiếm **47% tổng số cạnh**, và chính là hai lớp node mà tầng suy luận **cần** đi tới.

> Để so sánh: FB60K trong bài báo cũng chỉ có 21,3% độ phủ nhãn ở epoch 1 — **nhưng trên 268K
> fact**, tức ~57.000 mẫu dùng được. Tôi có **2.642**. Kém 20 lần.

### 2.3 Gần như không có gì để dự đoán, và phía "LÀM" mỏng

*(Số liệu cập nhật theo build 2026-07: bảng cũ ghi 0/0/16 là số của một build trước đó.)*

| Quan hệ mục tiêu | Số cạnh | | Lớp node từ tin tức | Số lượng |
|---|---|---|---|---|
| `verifiedBy` | 39 | | `Controversy` | **2** |
| `contradictedBy` | **2** | | `Penalty` | **4** |
| `contradictedByMedia` | **0** | | `MediaReport` | 91 |

Kết luận "phía LÀM mỏng" vẫn đứng vững — 2 Controversy / 4 Penalty cho một công ty
niêm yết là quá ít để suy luận. Đây là điều
[`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) §6 đã tự thừa nhận.

> **Nguyên tắc:** Tầng suy luận **không thể suy luận trên bằng chứng không tồn tại.**

### 2.4 `identity_keys` đang PHÁ VỠ cầu nối liên công ty

Đồ thị hiện tại **đã là** đồ thị đa công ty thu nhỏ: **438 node `Organization`** (AAA + công ty
con + đối tác + công ty được nhắc trong tin). Vậy các thực thể *dùng chung* có nối được hai
công ty không?

| Lớp | `identity_keys` | Node | Bậc = 1 | **Nối ≥ 2 Organization** |
|---|---|---|---|---|
| `Person` | `["name"]` | 196 | 122 | **56** ✅ |
| `Location` | `["name","country"]` | 248 | 94 | **44** ✅ |
| `Product` | `["name"]` | 215 | 120 | 31 |
| `Facility` | `["name"]` | 277 | 99 | 29 |
| `Certification` | `["name","valid_from","validity_period"]` | 144 | 57 | 19 |
| **`Regulation`** | `["name","jurisdiction"]` | 264 | 252 | **5** ❌ |
| **`Standard`** | `["name","valid_from"]` | 331 | **310 (94%)** | **2** ❌ |

`Standard` và `Regulation` đáng lẽ là **cầu nối mạnh nhất** — *mọi* công ty niêm yết VN đều áp
dụng GRI và chịu Thông tư 96/2020. Thực tế: **310/331 node `Standard` là lá cô lập**.

**Nguyên nhân:** `Standard.identity_keys = ["name","valid_from"]` ⇒ "GRI" ở báo cáo 2021 và
"GRI" ở báo cáo 2023 thành **hai node khác nhau**. Nhân 115 công ty × 5 năm ⇒ "ISO 14001" vỡ
thành hàng trăm mảnh.

> **Đây là LỖI MÔ HÌNH HÓA:** *danh tính của thực thể phải là **nó là cái gì**, không phải **ta
> tình cờ quan sát nó lúc nào**.* Đưa `valid_from` vào `identity_keys` đã trộn lẫn *danh tính*
> với *thời điểm quan sát*.

Và schema **đã có sẵn cơ chế đúng** cho chiều thời gian: `temporal_versions` + `supersedes`
([`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) §2.2). Step 5 cũng ghi rõ *"gom node trùng lặp
thành thực thể chuẩn, **giữ nguyên lịch sử thời gian**"*.

⇒ Bỏ `valid_from` khỏi khóa định danh **không mất chiều thời gian** — nó chuyển chiều đó về
đúng nơi schema đã quy định. **Đây là sửa lỗi cho nhất quán với chính thiết kế của mình**, chứ
không phải "sửa schema cho tiện chạy RL". Đó là lập luận bảo vệ mạnh nhất.

---

## 3. ⭐ Kiểm chứng bằng MÔ PHỎNG: cái gì thật, cái gì giả?

Trước khi sửa bất cứ thứ gì, tôi **mô phỏng trên bộ nhớ** để xem từng thay đổi có tác dụng gì.
Đây là phần quan trọng nhất của tài liệu — vì nó **tự phản biện chính đề xuất này**.

### 3.1 Thí nghiệm 1 — Sửa `identity_keys` MỘT MÌNH: gần như VÔ ÍCH (trên 1 công ty)

Mô phỏng gộp `Standard`/`Certification`/`Regulation`/`Location`/`Authority` theo tên chuẩn hóa:

| | Trước | Sau |
|---|---|---|
| Tổng truy vấn huấn luyện được | 20,3% | **20,8%** |
| Bậc trung vị | 1 | **1** |

Nhưng **từng quan hệ thì đúng như dự đoán**:

| Quan hệ | Trước | Sau | |
|---|---|---|---|
| `holdsCertification` | 30,6% | **44,7%** | +14 điểm |
| `subjectToRegulation` | 4,2% | **9,1%** | ×2,2 |
| `adoptsStandard` | 1,5% | **3,2%** | ×2,1 |
| `reportsKPI` | 3,9% | 3,9% | không đổi |

**Vì sao tổng không nhúc nhích?**

1. **Bị pha loãng** — `reportsKPI` chiếm 37,6% tổng cạnh và đứng im ở 3,9%.
2. **Trên 1 công ty không có gì để hội tụ TỚI** — chỉ tìm được 260 node trùng. Nội bộ AAA,
   "ISO 14001" xuất hiện vài lần ⇒ bậc 3. Với 115 công ty ⇒ bậc ~115.

> ⇒ **Sửa `identity_keys` là ĐIỀU KIỆN CẦN, nhưng lợi ích chỉ hiện ra ở quy mô đa công ty.**
> Hiệu ứng hội tụ **nhân lên theo số công ty**. Đo trên 1 công ty là đo trong điều kiện nó
> không thể phát huy.

### 3.2 Thí nghiệm 2 — Reify keyword: LỢI ÍCH PHẦN LỚN LÀ GIẢ

Mô phỏng: cho `SustainabilityClaim`, `KPIObservation`, `MediaReport`, `Goal`… cùng trỏ vào một
kho `ClaimKeyword` dùng chung. Quét **trần bậc của node từ khóa** (`df_max`):

| Trần bậc từ khóa | Cạnh keyword | Bậc hub max | `claims` | `reportsKPI` | **TỔNG** | **Bậc trung vị** | **claim→conduct (không qua hub)** |
|---|---|---|---|---|---|---|---|
| **≤ 20** *(lành mạnh)* | 8.330 | 20 | 71,6% | 17,6% | **36,5%** | **1** | **16,0%** |
| ≤ 50 | 15.067 | 50 | 85,7% | 38,6% | 47,1% | 2 | 27,3% |
| **≤ 400** *(bừa bãi)* | 35.905 | **346** | 97,9% | 90,0% | **68,4%** | **4** | **71,8%** |

**Mọi con số đẹp đều tăng đơn điệu theo kích thước hub.** Kết quả ấn tượng "68,4% / bậc 4 /
71,8%" **chỉ tồn tại khi cho phép một từ khóa nối tới 346 node**.

> ⚠️ **Nói thẳng: điều đó KHÔNG làm đồ thị đặc hơn — nó chỉ THAY một cái hub (AAA, bậc 9.564)
> bằng vài chục hub từ khóa (bậc ~346).** Từ hình sao thành hình sao rậm hơn.

### 3.3 ⚠️ Bẫy "CALO RỖNG" (empty calories) — phải hiểu rõ

Đường đi mới mà keyword tạo ra trông như sau:

```
Claim C  —hasKeyword→  "moi_truong"  —hasKeyword⁻¹→  KPI K
```

Đường này nói gì? Nó nói: *"C và K cùng chứa từ 'môi trường'."*

Đó **chính xác** là tín hiệu token-overlap mà **step07 ĐÃ tính rồi**. Ta chỉ mã hóa lại nó
thành cấu trúc đồ thị. Một agent RL huấn luyện trên đó sẽ học được… **cách tái tạo
token-overlap, bằng con đường vòng đắt gấp nghìn lần.**

> **Calo rỗng = chỉ số topology đẹp lên, nhưng NĂNG LỰC SUY LUẬN KHÔNG TĂNG.**
> Bỏ 4 tuần + 1 GPU để xây lại thứ 20 dòng Python đã làm.

**Thông tin THẬT SỰ MỚI chỉ đến từ BỘ XƯƠNG CẤU TRÚC:**

```
C1 —claims⁻¹→ O_AAA —partnersWith→ O_SUP —subjectToPenalty→ P1
                     └────────── KHÔNG có từ khóa nào chung ──────────┘
```

Claim *"chuỗi cung ứng xanh"* và Penalty *"xả thải vượt chuẩn"* **không chia sẻ token nào**.
Chỉ có **cấu trúc chuỗi cung ứng** nối chúng. **Đó** mới là thứ LLM adjudicator không làm được.
**Đó** mới là đóng góp.

Và các quan hệ đó (`partnersWith` 50,8%, `ownsFacility` 67,5%, `observedAtFacility` 86,7%) chỉ
trở nên **giàu** khi có **nhiều công ty**.

### 3.4 Ba kết luận đã được kiểm chứng bằng số

1. **Reify keyword là cần thiết và có giá trị thật — nhưng PHẢI có trần bậc** (đề xuất
   `df ≤ 20`). `claims` đi từ **1,0% → 71,6%** là cải thiện **thật**, và đó là quan hệ quan
   trọng nhất. Bỏ trần là tự lừa mình.
2. **MỘT CÔNG TY KHÔNG BAO GIỜ ĐỦ.** Với thiết lập trung thực (`df ≤ 20`), cổng vẫn trượt:
   bậc trung vị **1**, claim→conduct chỉ **16,0%**. Đây giờ là kết luận **đã đo**, không còn là
   phỏng đoán. **Đa công ty là điều kiện CẦN, không phải tùy chọn.**
3. **Cổng kiểm tra phải đổi chỉ số** (xem §6.1) — "tổng % trả lời được" có thể bị **thổi phồng
   bằng hub rác**.

---

## 4. Cách sửa: Phase 0 — làm cho đồ thị "đi được"

### 4.1 Sửa `identity_keys` (bỏ thời gian khỏi danh tính)

| Lớp | Hiện tại | Đề xuất |
|---|---|---|
| `Standard` | `["name","valid_from"]` | `["name"]` |
| `Certification` | `["name","valid_from","validity_period"]` | `["name"]` |
| `Regulation` | `["name","jurisdiction"]` | `["name"]` + chuẩn hóa |
| `Location` | `["name","country"]` | `["name"]` + chuẩn hóa |

### 4.2 Reify `ClaimKeyword` — **có trần bậc**

Hiện `ClaimKeyword` đã tồn tại (141 node, 163 cạnh `hasKeyword`) — **nhưng chỉ claim có
keyword; node tin tức không có cái nào.** Mối liên hệ chủ đề claim↔tin **chỉ sống trong hàm
token-overlap bằng Python của step07**.

**Đề xuất:** cho phép `hasKeyword` từ `MediaReport`/`Controversy`/`KPIObservation` →
`ClaimKeyword`. Là **sửa dữ liệu thuần túy trong schema**, đúng tiền lệ
[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §4.3 đã đặt cho `source_type`.

**BẮT BUỘC: trần bậc `df ≤ 20`** (§3.2). Cạnh keyword phải được **gắn nhãn loại riêng** để
đánh giá có thể tách bạch "đường thuần keyword" khỏi "đường cấu trúc".

**Cách trình bày với giáo sư:**

> *"Em không thêm cạnh để chiều lòng agent RL. Em đang **chuyển một tín hiệu truy hồi vốn đã
> được sử dụng** ra khỏi code và đưa vào đồ thị — nơi nó **kiểm toán được và truy vấn được bằng
> Cypher**. Và em đã đo để chứng minh phần nào của lợi ích là thật, phần nào là do siêu-hub."*

### 4.3 Đa công ty — **bắt buộc**, bắt đầu bằng 3 công ty pilot cùng ngành

Chọn công ty **cùng ngành** (xây dựng / vật liệu xây dựng) — nhóm có xác suất dùng chung nhà
cung cấp, địa điểm, cơ quan quản lý cao nhất.

### 4.4 Vá lỗ hổng phía "LÀM"

Trích xuất lại các bài có `Controversy`/`Penalty` (bắt đầu từ vietnamnet.vn). **Phải làm bất kể
có SSRL hay không.**

### 4.5 ⚠️ ĐỪNG gom node quá tay

Gom `Standard`/`Regulation` thành node toàn cục ngây thơ ⇒ **siêu-hub** ("GRI", bậc ~115). Agent
sẽ học đi vòng qua chúng và sinh ra:

> AAA áp dụng GRI ← GRI ← BBB áp dụng GRI, và BBB bị phạt ⟹ ???

**Đường đi, nhưng không phải bằng chứng.** Đây là "hub problem" kinh điển của Freebase.

| ✅ Cầu nối tốt (giữ trong action space) | ❌ Cầu nối rác (loại / hạ trọng số) |
|---|---|
| Nhà cung cấp / đối tác / công ty mẹ dùng chung | "Cả hai đều theo GRI" |
| `Facility` / `Location` dùng chung (cùng KCN) | "Cả hai đều chịu Thông tư 96" |
| `Authority` dùng chung (cơ quan phạt A cũng cấp cert cho B) | Node `Country` = "Việt Nam" |
| `Person` dùng chung (HĐQT kiêm nhiệm) | Từ khóa quá phổ biến (`df > 20`) |

⇒ Gom `Standard`/`Regulation` **để đúng dữ liệu**, nhưng **loại khỏi không gian hành động**.

### 4.6 Neo ≥ 2 cho node T2 (P3 — bổ sung sau review, ĐÃ triển khai)

Mục còn thiếu **rẻ nhất tính trên tác dụng** của Phase 0: node sự kiện
(`KPIObservation` 4,1% bậc ≥ 2, trong khi `Investment` — được thiết kế 2 neo — đạt
50,4% ngay trong cùng pipeline). Sửa tại **prompt step02** (cả report lẫn news): với
mỗi node T2, bắt buộc thử phát các cạnh neo có sẵn trong schema (`observedAtFacility`,
`locatedIn`, `enforcedBy`, `mentionsProduct`, …) khi câu văn nêu tên cơ sở/địa
điểm/cơ quan. Dữ liệu đã trích xuất được vá offline bằng gazetteer
(`src/step03b_anchor_kpi_facilities.py`). Đo bằng Q7(e) của
`src/step00_graph_quality_report.py`. Chi tiết: [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) P3.

### 4.7 Chính sách bậc cho chính node issuer (P5 — bổ sung sau review)

Trần bậc keyword (§3.2) mới xử lý một nửa vấn đề hub. **Hub lớn nhất là chính node
AAA (bậc 9.564)**: gần như mọi đường đi hữu ích phải bước qua nó ở hop đầu tiên, và
MINERVA/MultiHopKG cắt/lấy mẫu action space (~200–400 hành động) ⇒ lấy mẫu đều trên
9.564 láng giềng giết agent ngay hop 1. Chính sách đề xuất cho **step12 (trainer)**,
không đụng đồ thị: chọn hành động **hai bước — chọn QUAN HỆ trước, chọn ĐÍCH sau**
(factored action space; ~40 nhãn quan hệ × vài chục đích), dự phòng là lấy mẫu láng
giềng phân tầng theo nhãn quan hệ. Chi tiết: [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) P5.

---

## 5. 🔑 Áp dụng SSRL cho bài toán KHÔNG CÓ NHÃN

### 5.1 SSRL vốn dĩ KHÔNG CẦN nhãn người gán

Chữ "self-supervised" nghĩa là: **tín hiệu huấn luyện sinh tự động từ chính cấu trúc đồ thị.**

1. Lấy một cạnh **đã có sẵn**: `(e_s, r, e_q)`.
2. **Che nó đi** (cả cạnh xuôi lẫn cạnh nghịch đảo).
3. Truy vấn agent: *"Từ `e_s`, theo quan hệ `r`, tìm đích."*
4. Agent duyệt đồ thị. Tới đúng `e_q` ⇒ được thưởng.
5. **Nhãn SL** sinh bằng **BFS**: liệt kê *toàn bộ* đường đi đúng, đánh dấu mọi cạnh trên đường
   đúng = `1`, còn lại = `0`.

**Không có con người nào gán nhãn.** Chân lý = **các cạnh vốn đã tồn tại**, do pipeline trích
xuất từ báo cáo và tin tức.

> ✅ **Ràng buộc "không có nhãn greenwashing" là TRỰC GIAO với phương pháp này.** Nó giết chết
> một classifier có giám sát, nhưng **không** cản trở SSRL. Đây là lý do mạnh nhất để chọn đúng
> bài báo này.

### 5.2 Chi tiết kỹ thuật bắt buộc: cạnh nghịch đảo

Schema có hướng cố định, và node bằng chứng thường **chĩa VÀO** `Organization`:

```
MediaReport —mentionsOrganization→ Organization      (chĩa VÀO)
Organization —subjectToPenalty→ Penalty              (chĩa RA)
```

Agent đứng ở `Organization` **không thể** đi ngược tới `MediaReport`. MINERVA/MultiHopKG luôn
thêm **cạnh nghịch đảo** (tiền xử lý chuẩn, miễn phí): 40 quan hệ → 80. Agent đi được **cả hai
chiều** nhưng vẫn **biết** mình đang đi chiều nào.

### 5.3 Ví dụ BFS sinh nhãn — rõ NODE nào, CẠNH nào

> ⚠️ **Ràng buộc P8 (bổ sung sau review — xem
> [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) P8):** BFS sinh nhãn **phải chạy
> trên ĐỒ THỊ CON THỜI GIAN của từng truy vấn** — chỉ những cạnh có
> `valid_from ≤ t_query` (và nếu dùng trục knowledge-time: `recorded_at ≤ t_query`).
> Nếu BFS chạy trên toàn bộ đồ thị không mặt nạ, giai đoạn SL sẽ gán nhãn `1` cho
> những cạnh mà lúc RL/inference agent bị cấm đi (vd. đường qua bằng chứng 2024 cho
> truy vấn neo ở 2021) ⇒ lệch phân phối SL↔RL, đúng loại lỗi làm giai đoạn SL
> **phản tác dụng** (bài báo gốc đã cảnh báo SL quá tay làm giảm hiệu năng).

#### Đồ thị con ví dụ

**NODE (thực thể):**

| Ký hiệu | Class | Nội dung |
|---|---|---|
| `O_AAA` | `Organization` | CTCP Nhựa An Phát Xanh |
| `F1` | `Facility` | Nhà máy Hải Dương |
| `F2` | `Facility` | Nhà máy Yên Bái |
| `I1` | `Initiative` | Sáng kiến giảm phát thải |
| `GRI` | `Standard` | GRI Standards |
| `ISO14001` | `Certification` | ISO 14001 |
| `ISO9001` | `Certification` | ISO 9001 |
| `L1` | `Location` | Hải Dương |

**CẠNH (quan hệ, đều có trong `schema.json`):**

```
O_AAA  —ownsFacility→        F1
O_AAA  —ownsFacility→        F2
O_AAA  —takesPartIn→         I1
O_AAA  —adoptsStandard→      GRI
F1     —holdsCertification→  ISO14001
F1     —locatedIn→           L1
F2     —holdsCertification→  ISO9001
I1     —aimsForCertification→ ISO14001

O_AAA  —holdsCertification→  ISO14001    ← ❌ CHE
O_AAA  —holdsCertification→  ISO9001     ← ❌ CHE
```

#### Truy vấn huấn luyện

```
q = (e_s = O_AAA,  r = holdsCertification,  ? )
E_all = { ISO14001, ISO9001 }        ← ĐÍCH (2 đáp án đúng = "to-many query")
```

> **"Đích" KHÔNG phải một loại node cố định.** Đích = **object của cạnh vừa bị che**. Truy vấn
> tự định nghĩa đích của nó. Che cạnh khác ⇒ đích khác.

#### BFS 4 bước

**Bước 1** — bỏ self-loop mọi node, **trừ** các node trong `E_all`.

**Bước 2** — BFS từ `O_AAA`, tìm được **3 đường đi đúng**:

```
① O_AAA —ownsFacility→ F1 —holdsCertification→  ISO14001   ✓
② O_AAA —takesPartIn→  I1 —aimsForCertification→ ISO14001  ✓
③ O_AAA —ownsFacility→ F2 —holdsCertification→  ISO9001    ✓
```

**Bước 3** — gom node trên đường đúng: `C = {F1, I1, F2}`.

**Bước 4** — sinh nhãn.

> ⚠️ **Nhãn `y_t` là vector trên KHÔNG GIAN HÀNH ĐỘNG của node `t` — tức các CẠNH ĐI RA.**
> **Nhãn nằm trên CẠNH, KHÔNG nằm trên NODE.** Đây là chỗ dễ hiểu nhầm nhất.

Nhãn tại `O_AAA`:

| # | Hành động (**CẠNH**) | Dẫn tới **NODE** | Nhãn | Vì sao |
|---|---|---|---|---|
| 0 | *self-loop* | `O_AAA` | **0** | chưa tới đích, không được đứng yên |
| 1 | `ownsFacility` | `F1` | **1** | trên đường đúng ① |
| 2 | `ownsFacility` | `F2` | **1** | trên đường đúng ③ |
| 3 | `takesPartIn` | `I1` | **1** | trên đường đúng ② |
| 4 | `adoptsStandard` | `GRI` | **0** | ngõ cụt |

⇒ `y_O_AAA = [0, 1, 1, 1, 0]`

Nhãn tại `F1`: `[self-loop → 0, holdsCertification→ISO14001 → 1, locatedIn→L1 → 0]`
⇒ `y_F1 = [0, 1, 0]`

Nhãn tại `ISO14001` (là đích): `y = [1, 0, …]` — self-loop = **1**: *"Đến rồi, ở lại đây."*

#### Vì sao SSRL hơn RL thuần

- **RL thuần:** tìm được **một** đường là được thưởng ⇒ mãi đi đường ①, không bao giờ khám phá ②.
- **SSRL:** nhãn đánh dấu **TẤT CẢ** cạnh trên **MỌI** đường đúng (`→F1` **và** `→I1` **và**
  `→F2` đều = 1) ⇒ agent học **toàn bộ vùng phủ**.

Đó chính là "information density" bài báo nói tới: mỗi bước agent học về *mọi* hành động đúng,
không chỉ một hành động được lấy mẫu.

#### ⚠️ Điều kiện sống còn

Che cạnh chỉ tạo ra mẫu dùng được **NẾU sau khi che vẫn còn đường đi khác**. Nếu `ISO14001` là
lá bậc 1 ⇒ che xong thành **mồ côi** ⇒ mẫu vứt đi. **Hiện 79,7% cạnh của tôi rơi vào trường hợp
này** (§2.2).

### 5.4 Lúc suy luận: cái ta thực sự muốn

```
q = (e_s = C1,  r = contradictedBy,  ? )
```

Agent tìm được:

```
C1 —claims⁻¹→ O_AAA —partnersWith→ O_SUP —subjectToPenalty→ P1
```

**Đích = `P1`.** Và **đường đi CHÍNH LÀ lời giải thích** đưa vào dossier:

> *"AAA tuyên bố chuỗi cung ứng xanh → nhưng đối tác Bao bì X của AAA bị phạt xả thải năm 2024."*

**LLM adjudicator hiện tại KHÔNG BAO GIỜ tìm được cái này** — nó chỉ so *văn bản claim* với
*văn bản một bản tin*, không có khả năng đi qua `O_SUP`. **Đây là đóng góp.**

### 5.5 Xử lý việc quan hệ mục tiêu quá khan hiếm

`contradictedBy` chỉ có **2 cạnh** (§2.3) ⇒ agent gần như không học được embedding cho nó.

| Cách | Đánh giá |
|---|---|
| ① Đa công ty nhân số cạnh lên | Cần, nhưng chưa đủ |
| ② **Huấn luyện trên các quan hệ ĐÔNG để chúng HỢP THÀNH đường bằng chứng** — `partnersWith`, `ownsFacility`, `subjectToPenalty`, `observedAtFacility` (chính là nhóm ✅ có 50–87% trả lời được) | ⭐ **KHUYẾN NGHỊ** — tránh hoàn toàn vấn đề khan hiếm |
| ③ Lấy 3.113 phán quyết LLM làm nhãn | ❌ **CẤM** — xem §5.6 |

Với cách ②, ta **không cần** `contradictedBy` phải đông: agent học *cách đi trong chuỗi cung
ứng*, rồi truy vấn `(O_AAA, subjectToPenalty, ?)` mở rộng 3–4 bước. **LLM vẫn giữ vai trò quan
tòa** — agent *đề xuất* `P1` kèm đường đi, LLM *phán xử* xem `P1` có thật sự mâu thuẫn với `C1`.

### 5.6 ⚠️ Bẫy vòng lặp luẩn quẩn (circularity)

> **KHÔNG BAO GIỜ** huấn luyện agent trên 3.113 phán quyết của `gpt-4o-mini` rồi **đánh giá
> bằng chính các phán quyết đó.**

Làm vậy = **chưng cất `gpt-4o-mini`** rồi đo xem mình giống `gpt-4o-mini` đến đâu ⇒
**không thể phản nghiệm (unfalsifiable)** ⇒ bị bác ngay khi bảo vệ.

**Đúng:** huấn luyện trên **cạnh cấu trúc đã trích xuất** được giữ lại (held-out) — §5.1.

### 5.7 Vị trí trong hệ thống (đầu ra KHÔNG đổi)

```
step05 resolved graph
   ├─► [MỚI] step11_build_kgc_dataset.py    đồ thị → bộ ba (e_s, r, e_q) + nhãn BFS
   ├─► [MỚI] step12_train_path_reasoner.py  SL warm-up → RL   (nền: MultiHopKG/PyTorch)
   └─► [MỚI] step13_path_evidence.py        mỗi claim: duyệt → ứng viên + ĐƯỜNG ĐI
                                                   │
step07 crosscheck ◄────────────────────────────────┘
   retrieval    = token-overlap  ∪  path-walker    ← agent ĐỀ XUẤT
   adjudication = LLM (giữ nguyên)                 ← LLM vẫn PHÁN XỬ
   dossier + "reasoning_path": [...]               ← trường cũ giữ nguyên từng byte
```

**Agent là người truy hồi và giải thích, KHÔNG BAO GIỜ là quan tòa.** Khung "tư vấn, không chấm
điểm" được giữ nguyên vẹn.

### 5.8 Đánh giá khi không có nhãn

| Mức | Chỉ số | Vì sao hợp lệ |
|---|---|---|
| **Chính** | Link prediction trên cạnh cấu trúc held-out: **Hits@1/@3/@10, MRR** | Đúng giao thức bài báo. **Không cần ground truth.** Ablation = SSRL vs RL-thuần. |
| **Phụ** ⭐ | **Recall truy hồi qua ĐƯỜNG CẤU TRÚC**: agent có tìm ra bằng chứng mà token-overlap **bỏ sót** không? | Chỉ gửi ứng viên **mới** cho LLM. **Đây là kết quả quan trọng nhất** — nó chứng minh không phải "calo rỗng" (§3.3). |
| **Bổ sung** | Bộ 30 case đã gán tay: `config/evaluation/ablation_cases.json` | Có sẵn từ P6. |

---

## 6. Kế hoạch thực thi

### 6.1 🚦 CỔNG KIỂM TRA (đã sửa lại chỉ số)

Chỉ số cũ ("tổng % truy vấn trả lời được") **bị bác bỏ** — nó **có thể bị thổi phồng bằng hub
rác** (§3.2). Cổng đúng:

> **Tỉ lệ claim tiếp cận được node conduct qua một đường đi có ÍT NHẤT MỘT CẠNH CẤU TRÚC**
> (`partnersWith`, `ownsFacility`, `observedAtFacility`, `worksAt`, `locatedIn`, `producedBy`…)
> — **KHÔNG tính đường đi thuần keyword.**

Vì chỉ đường đi cấu trúc mới mang thông tin mà token-overlap của step07 **chưa có**.

**Đường cơ sở hiện tại (1 công ty, `df ≤ 20`): 16,0%.** Mục tiêu: xem chỉ số này có **tăng rõ
rệt** khi đi từ 1 → 3 công ty không, rồi ngoại suy.

### 6.2 Trình tự

```
①  Sửa identity_keys + reify keyword (df ≤ 20)     [0đ, vài phút]
       → step05 --no-llm → step06
       ⚠ ĐỪNG kỳ vọng cổng đạt — đã mô phỏng: vẫn trượt trên 1 công ty

②  Port cascade OpenAI vào step01/02               [1–2 ngày, BẮT BUỘC]
       ⚠ step01/02/03/05 hiện CHỈ chạy Gemini, mà project Gemini đang 403 billing

③  Pilot 3 công ty CÙNG NGÀNH → full pipeline      [$$ — chi phí thật]

④  🚦 CỔNG: đo "% claim có đường CẤU TRÚC tới conduct"
       1 cty = 16,0%  →  3 cty = ?  →  ngoại suy → quyết định lên 8 hay 115
```

> **Kết quả âm tính cũng là một chương luận văn tốt.** Nếu từ 1 → 3 công ty mà chỉ số không
> nhích, bạn đã chứng minh — **bằng số liệu** — rằng *"Graph-RAG cấp công ty đơn lẻ không đủ mật
> độ cho path-based reasoning"*. Đó là một phát hiện đáng bảo vệ, và toàn bộ giá trị của Phase 0
> vẫn được giữ.

### 6.3 Ma trận chi phí LLM / embedding

**Tin tốt:** `graph_output/validated/all_validated_triples.json` (14.582 triples) **lưu đầy đủ
`properties`**, và `step05` **tự tính lại** identity signature từ schema — nó **không** tin vào
`stable_id` mà step02 ghi. ⇒ **Kết quả trích xuất LLM đã được "đóng băng" thành tài sản dùng
lại được.**

| Hạng mục Phase 0 | Cần chạy lại | LLM? | Embedding? | Chi phí |
|---|---|---|---|---|
| **Sửa `identity_keys`** | step05 (`--no-llm`) → step06 | ❌ | ❌ | **0đ**, vài phút |
| **Reify `ClaimKeyword`** | script offline mới → step06 | ❌ | ❌ | **0đ** |
| **Vá conduct (vietnamnet)** | step02 `--doc vietnamnet` → 03 → 05 → 06 | ✅ nhỏ | ❌ | vài chục call |
| **Đa công ty (3–8 DN)** | step01 + step02 **từ đầu** mỗi DN | ✅ **LỚN** | ❌ | **~95% tổng chi phí** |
| *(sau khi graph đổi)* refresh dossier | step07 → 08 → 09 | ✅ | ❌ | ~0,5 USD, ~13 phút |

**Reify keyword không tốn LLM** vì tín hiệu step07 đang dùng là **token overlap tất định**
(`name_tokens`). Nếu nó cần LLM thì nó đã không phải là *tín hiệu có sẵn*.

**Quy mô bước đa công ty:** AAA = **43 documents / 1.370 trang**. step01 và step02 gọi LLM **theo
từng trang**. 3–8 công ty ⇒ ~4.000–11.000 trang ⇒ **~8.000–22.000 LLM call**.

#### ⚠️ Blocker: step01/02/03/05 chỉ chạy được Gemini

| Step | Provider |
|---|---|
| step01 (KPI) | **chỉ `gemini-2.5-flash`** |
| step02 (triplet) | **chỉ `gemini-2.5-flash`** |
| step03 (repair) | **chỉ `gemini-2.5-flash`** |
| step05 (ER stage B/C) | **chỉ `gemini-2.5-flash` + `gemini-embedding-001`** |
| step07 (crosscheck) | ✅ cascade `gemini → openai` |

Project Gemini đang **403 billing**. ⇒ Phải **khôi phục billing Gemini** HOẶC **port cascade
multi-provider từ step07 sang step01/02** (code mẫu đã có sẵn trong repo).

#### Embedding quay lại ở đâu?

1. **step05 Stage B.2** (`gemini-embedding-001`) — hiện **tắt**. Ở quy mô đa công ty, entity
   resolution khó lên hẳn ⇒ **đây là chỗ embedding thực sự đáng tiền**. Nếu Gemini vẫn bị chặn,
   thay bằng **SentenceTransformer chạy local** (tiền lệ: EmeraldMind dùng local
   SentenceTransformer, không dùng API trả phí — ghi trong `CLAIM_CONDUCT_CROSSCHECK.md` §5).
2. **step07 `--embed`** — tùy chọn, đang tắt.
3. **SSRL — KHÔNG cần embedding API nào cả.** MINERVA/MultiHopKG **tự học** entity/relation
   embedding từ đầu bằng backprop (bài báo, công thức 1–3). Tầng SSRL **miễn phí hoàn toàn về
   API** — chỉ tốn GPU.

### 6.4 Các giai đoạn

| Giai đoạn | Thời gian | Sản phẩm | Rủi ro |
|---|---|---|---|
| **0. `identity_keys` + keyword + pilot 3 DN + vá conduct** | ~1–2 tuần | Step 7 tốt hơn; liên kết chủ đề truy vấn được bằng Cypher. **Một chương luận văn kể cả khi bỏ SSRL.** | Thấp |
| **🚦 CỔNG** (§6.1) | — | Quyết định đi tiếp hay dừng | — |
| 1. Xuất KGC dataset + baseline RL-thuần | 1–1,5 tuần | Hits@k / MRR baseline | Trung bình |
| 2. SSRL: nhãn mồi BFS + SL→RL | ~1 tuần | Tái hiện bài báo trên KG ESG | Trung bình |
| 3. Tích hợp vào step 7 | 0,5–1 tuần | `reasoning_path`; **đầu ra cũ giữ nguyên** | Thấp |
| 4. Đánh giá (§5.8) | 0,5–1 tuần | Ablation + recall study | Thấp |

**Tổng: ~4–6 tuần.**

### 6.5 Thời gian huấn luyện

Compute **không phải** nút thắt. "18–72 giờ trên V100" của bài báo là cho đồ thị 100–270K fact.

| Quy mô | Mỗi lần chạy |
|---|---|
| AAA hiện tại (13K cạnh) | ~1–3 giờ GPU *(nhưng vô nghĩa — hình sao)* |
| Đa công ty, ~15–20 DN | ~4–10 giờ GPU ← **mục tiêu thực tế** |
| Đủ 115 DN (~100–500K cạnh) | ~8–20 giờ GPU đời mới |

**Nhưng cần 5–8 lần chạy.** Bài báo cho thấy **số epoch giai đoạn SL là siêu tham số then chốt,
phụ thuộc dataset** — tối ưu lần lượt **3 / 2 / 5 / 7** epoch trên 4 bộ dữ liệu, **không có giá
trị phổ quát**, và **train SL quá nhiều thì hiệu năng GIẢM**. Dự trù **1–2 tuần GPU chạy nền**.

### 6.6 Độ khó: **8/10**

Không phải vì ML (phương pháp đặc tả rõ, code gốc có sẵn), mà vì:

1. **Khảo cổ code nghiên cứu** — MINERVA gốc là TensorFlow 1.x (lỗi thời) ⇒ **dùng nền
   MultiHopKG (PyTorch/Salesforce)**.
2. **Bắt buộc tái cấu trúc đồ thị trước** — rào cản thật sự (§3).
3. **Nhạy cảm siêu tham số** (§6.5).
4. **Rủi ro thật rằng cải thiện là nhỏ** — trên đồ thị hình sao hiện tại, đó là kết quả *nhiều
   khả năng nhất*.

---

## 7. Hai đóng góp mới so với bài báo gốc

### 7.1 Nhãn mồi cân bằng theo quan hệ

Đồ thị lệch nặng: `reportsKPI` chiếm **37,6%** tổng cạnh. Bài báo chỉ ra phân bố quan hệ lệch
**làm giảm** hiệu quả SSRL (WN18RR, FB60K) và **nói thẳng trong kết luận rằng sinh nhãn theo
phân bố quan hệ là *future work* họ chưa làm.**

### 7.2 Suy luận tôn trọng thời gian (định vị lại theo P8 của TEMPORAL_KG_DESIGN)

KG trong bài báo là **tĩnh**. Đồ thị của tôi **bitemporal**. Agent **không được** đi từ claim
2021 tới bằng chứng 2024 khi suy luận về những gì *có thể biết* vào 2021.

⚠️ **Định vị tính mới cho đúng:** ràng buộc action space theo thời gian trên TKG **không
mới** — TITer/TimeTraveler (Sun et al., EMNLP 2021, arXiv:2109.04101) đã làm từ 2021
(action = (relation, entity, timestamp), relative-time encoding, time-shaped reward) và
**phải được cite** khi trình bày phần này. Đóng góp thực sự của đề tài gồm ba điểm
(xem [`TEMPORAL_KG_DESIGN.md`](./TEMPORAL_KG_DESIGN.md) P8):

1. **Nhãn BFS dày của SSRL trong thiết lập thời gian** — bài báo SSRL gốc chỉ làm trên
   KG tĩnh; mặt nạ thời gian phải áp **đồng nhất cho cả ba nơi**: BFS sinh nhãn SL,
   action space lúc RL, và action space lúc inference (nếu không, SL dạy agent những
   đường đi mà RL bị cấm — xem ràng buộc bổ sung ở §5.3).
2. **Mặt nạ bitemporal hai trục** — TITer chỉ có event-time; đồ thị này có thêm
   `recorded_at` ("biết được lúc nào"). Với greenwashing, trục knowledge-time mới là
   trục nhân quả đúng: báo cáo 2021 không thể bị buộc tội mâu thuẫn với thông tin chỉ
   xuất hiện năm 2024.
3. **Cân bằng nhãn theo quan hệ** (§7.1) — bài báo gốc tự nhận là future work.

---

## 8. Tóm tắt luận điểm bảo vệ

1. **Vấn đề có thật và đã ĐO**, không phỏng đoán: 83,2% node là lá, bậc trung vị = 1, **97,5%
   claim chỉ có một mẫu đường đi**, và **chỉ 20,3% cạnh dùng được để huấn luyện**.
2. **Sửa schema là sửa LỖI MÔ HÌNH HÓA**, nhất quán với chính thiết kế bitemporal — *danh tính
   ≠ thời điểm quan sát* — không phải chỉnh sửa tùy tiện để phục vụ RL.
3. **Tôi đã TỰ PHẢN BIỆN đề xuất của mình bằng mô phỏng** (§3): phát hiện phần lớn lợi ích của
   reify keyword là **giả**, do siêu-hub — và sửa lại cả thiết kế lẫn chỉ số cổng kiểm tra.
4. **SSRL hợp với bài toán không nhãn**: tín hiệu sinh tự động bằng BFS trên cạnh đã có ⇒ ràng
   buộc "không ground truth" là **trực giao** với phương pháp.
5. **Đóng góp = năng lực MỚI**: bằng chứng gián tiếp đa bước qua chuỗi cung ứng, thứ LLM
   adjudicator **về cấu trúc không thể** phát hiện — cộng hai mở rộng (§7) bài báo gốc chưa làm.
6. **Có cổng kiểm tra định lượng**, và **kết quả âm tính cũng là phát hiện bảo vệ được.**

---

## 9. Tài liệu liên quan

[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) ·
[`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) ·
[`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) ·
[`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) ·
[`EVALUATION.md`](./EVALUATION.md)

**Bài báo gốc:** *Knowledge Graph Reasoning with Self-supervised Reinforcement Learning*,
arXiv:2405.13640v2 · Code: https://github.com/owenonline/Knowledge-Graph-Reasoning-with-Self-supervised-Reinforcement-Learning

---

*Tài liệu đề xuất. Chưa có thay đổi nào được áp dụng lên schema, đồ thị, hay pipeline.*
