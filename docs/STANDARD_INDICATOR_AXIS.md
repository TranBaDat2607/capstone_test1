# Trục chuẩn TT96/GRI — tầng chỉ tiêu `StandardIndicator` cho graph greenwashing

> **Trạng thái (2026-07-20): ĐÃ TRIỂN KHAI (offline).** Các stage step03c/step04b/step05c/step05d
> đã build + kiểm chứng offline trên dữ liệu AAA; schema, step00, step08 đã cập nhật;
> `test/test_temporal_invariants.py` có case cho chúng. Kết quả before/after
> (`graph_output/quality/quality_report_{before,after}_indicator_axis.md`): KPIObservation
> deg≥2 **5.3% → 16.9%**, T2 deg≥2 **10.1% → 19.9%**, masked-answerable **26.3% → 34.8%**,
> claim→conduct structural **8.0% → 8.0% (không đổi — confound đã được xử lý, xem §7)**; hub
> vẫn là Organization (không chỉ tiêu nào thành hub). **Còn lại là bước chạy của người dùng:**
> (a) duyệt `config/standard_crosswalk.json` (đang toàn `needs_review`) rồi đặt `status=confirmed`
> để phát cạnh TT96→GRI; (b) duyệt `config/standards_registry.json`; (c) `step06 --clear` +
> `step08` khi Neo4j chạy; (d) `step05d` là lần chạy tốn tiền tùy chọn. **Lưu ý dữ liệu:** trên
> AAA hiện tại, tier-1 retrieval (§6) cho **0 cặp** vì cả 108 news-KPI đều là nhiễu tài chính
> (không có `kpi_id` ESG) — trục đã nối đúng end-to-end nhưng conduct-side rỗng; re-run step07
> tốn tiền lúc này sẽ ra y hệt kết quả cũ. Nút thắt thật vẫn là nuôi kênh news (§4), đúng như
> §7 cảnh báo.
>
> Ngôn ngữ: tiếng Việt, mã/định danh giữ tiếng Anh
> theo convention của repo. Sơ đồ trực quan của thiết kế này:
> https://claude.ai/code/artifact/b47d74f9-c7d1-459a-ac9d-640058804fde
>
> **Tiêu chí thiết kế (quan trọng, chi phối toàn bộ §3 và §5):** đây **không phải** một patch
> vá graph AAA hiện có. Đây là các **stage thường trực của pipeline**. Tiêu chí nghiệm thu là:
> *chạy step01 → step09 từ đầu trên một công ty mới, chưa từng có dữ liệu, phải ra graph đã có
> sẵn đầy đủ cạnh KPI/Claim → StandardIndicator → Regulation và TT96 → GRI, không cần thao tác
> tay hay script vá nào.* Mọi lựa chọn dưới đây được cân bằng theo tiêu chí đó, chứ không theo
> tiêu chí "tránh cho team phải re-run" như bản nháp đầu.
>
> Quan hệ với các doc khác: đây là phần **mở rộng mức graph** của
> `CROSSCHECK_EXPANSION.md` — doc đó chủ trương thay đổi tối thiểu (mức property/cặp-cạnh,
> không class mới) và đặt nền `step03c_canonicalize_kpis.py`; doc này bổ sung **một class mới
> có chủ đích** (`StandardIndicator`) để vật chất hóa vocabulary 35 KPI thành node trong graph.
> Phân công dứt khoát: **step03c canonical hóa `kpi_type` → mã chỉ tiêu** (mức validated),
> **step05c vật chất hóa mã đó thành node + edge** (mức resolved). step03c phủ được bao nhiêu
> thì trục chỉ tiêu rộng bấy nhiêu — hai việc nối tiếp nhau, không thay thế nhau.

---

## 1. Câu hỏi xuất phát và chẩn đoán (đã kiểm chứng trên dữ liệu AAA, 2026-07-19)

Câu hỏi đặt ra: *"claim, KPI và mọi quan hệ đi ra khỏi node Organization AAA chưa tuân theo
GRI và TT96; dù đã đưa `kpi_definitions_construction.json` và `config/schema.json` vào,
graph không có quan hệ nào giữa node standard với node claim/KPI — đây có phải lỗ hổng
thiết kế không?"*

**Trả lời: có, nhưng lỗ hổng nằm ở schema chứ không phải ở extraction.** Kiểm chứng trực tiếp
trên `graph_output/resolved/resolved_graph.json`:

| # | Phát hiện | Số liệu |
|---|---|---|
| C1 | `kpi_type` **đã** mang vocabulary chuẩn — step01 đưa 35 định nghĩa vào prompt và Gemini match thật — nhưng chỉ là **string property** trên `KPIObservation`, không phải edge. Trong Neo4j không traverse được từ KPI sang chuẩn | 484/4.906 KPIObservation có mã chuẩn: 346 `TT96-*`, 138 `SSCIFC-*`; top: `TT96-6.6.1` (89), `TT96-6.7.2` (49), `SSCIFC-S2` (42), `TT96-6.2.1` (39) |
| C2 | Phần lớn KPI rơi ngoài vocabulary do escape hatch `"other"` trong prompt step01 (dòng ~214) — extractor nhặt cả KPI tài chính thuần | 810 node `other` + hàng trăm loại tự đặt tên (`Revenue` 87, `Financial Asset` 111, `Cash Flow` 46…) |
| C3 | Node `Standard`/`Regulation` hiện có là **mention do LLM nhặt từ văn bản**, không phải reference chuẩn hóa: lẫn chuẩn kế toán, luật thuế; GRI tồn tại ≥4 biến thể chưa được entity resolution gộp (`GRI Standards`, `GRI Standard`, `GRI Sustainability Reporting Standards`, `Global Reporting Initiative (GRI)`); TT96 có 2 biến thể Việt/Anh | 436 node; nối Organization qua `adoptsStandard` (317), `subjectToRegulation` (310), `issuedBy` (22), `supersedes` (4) |
| C4 | **0 edge** giữa Standard/Regulation và bất kỳ Claim/KPIObservation nào | đếm trực tiếp: 0 |
| C5 | **Nguyên nhân gốc:** `config/schema.json` không định nghĩa cặp (source_class, target_class) nào nối KPIObservation/SustainabilityClaim với Standard/Regulation → validator step03 loại mọi triple như vậy kể cả khi LLM sinh ra. Extractor hoàn hảo cũng không tạo được liên kết này | schema edges: không có cặp hợp lệ nào |

---

## 2. Các phương án đã cân nhắc và bác bỏ

### 2.1 Nối *tất cả* các loại node quanh AAA vào Standard — **bác bỏ**

AAA có 18 loại relationship đi ra (`reportsKPI` 4.420, `claims` 1.093, `setsGoal` 712,
`takesPartIn` 470, `ownsFacility` 342, …). Nguyên tắc lọc: **"TT96/GRI có yêu cầu doanh
nghiệp báo cáo nội dung này không?"** — chỉ node mang *nội dung công bố thông tin* mới nối;
node thực thể ngữ cảnh (Facility, Location, đối tác, Investment, …) thì không. Nối bừa tạo
hub node nhiễu — vi phạm chính tiêu chí hub-free Q7 mà step00 đang đo — và không thêm được
suy luận nào.

### 2.2 Chia node chuẩn theo *loại node kết nối vào* (1 node cho KPI, 1 node cho Emission, …) — **bác bỏ**

- **Phá vỡ join point:** claim về phát thải và KPI phát thải sẽ treo vào hai node khác nhau,
  muốn so sánh lại phải thêm hop + logic — quay về đúng vấn đề cần giải.
- **Vi phạm P1** (`TEMPORAL_KG_DESIGN.md`): identity node T1 phải phản ánh thực thể có thật.
  "TT96 phiên bản dành cho KPI" là artifact của topology, không phải thực thể; entity
  resolution không biết resolve mention nào về "bản TT96 nào".

### 2.3 Dồn ngữ nghĩa vào relationship label (1 node TT96 to, label kiểu `reportsKPIUnder_TT96_6_1_1`) — **bác bỏ**

- Bùng nổ label: 35 chỉ tiêu × vài class nguồn = cả trăm label trong `schema.json`.
- Chỉ tiêu không mang property được: `TT96-6.1.1` có `name`, `definition`, `pillar`,
  `section`, `excerpt` nguồn (đều sẵn trong `kpi_definitions_construction.json`) — phải sống
  trên node.
- 1 node TT96 hứng ~500+ edge = hub node → hỏng Q7 và path-reasoning (SSRL) sau này.
- Query theo chỉ tiêu thành scan theo relationship type thay vì match node.

### 2.4 Xóa cross-check step07, nối thẳng KPI/Emission/Penalty/Goal vào news — **bác bỏ**

Hiểu nhầm cần gỡ: **news không phải node để nối vào** — bài báo qua `step02 --source news`
đã *trở thành* chính các node `KPIObservation`/`Penalty`/`Controversy`/`MediaReport` với
`source_type=news` (provenance URL/tiêu đề do step05b dập). Câu hỏi thật là *claim-side và
conduct-side gặp nhau và phán xử ra sao*.

- Tầng chỉ tiêu cho **đồng vị trí cấu trúc**, không phải **phán xử ngữ nghĩa**. Claim
  *"giảm 20% phát thải KNK đến 2025"* và KPI news *"12.450 tCO2e năm 2024"* cùng treo vào
  TT96-6.1.1 — supports hay contradicts phụ thuộc hướng biến động, baseline, khung thời gian,
  `date_uncertain`. Đó là việc của LLM adjudication trong step07 (bắt buộc theo thiết kế,
  không có deterministic fallback — xem `CLAIM_CONDUCT_CROSSCHECK.md`).
- Nối cứng `supports/contradicts` bằng rule = nướng *phán đoán* vào graph nền như thể là
  *sự kiện* — trái nguyên tắc tách extraction khỏi analysis; phán đoán sai phải extract lại
  toàn bộ, còn hiện tại lớp advisory (`llm_suggested=true`) re-run được rẻ.
- Điều nên thay đổi thật sự là **khối retrieval của step07** (xem §6), không phải sự tồn tại
  của nó.

### 2.5 Vì sao kiến trúc claim-centric cross-check được giữ (bối cảnh)

Greenwashing = khoảng cách giữa *lời nói* và *việc làm*; đơn vị nhỏ nhất mang tính lừa dối là
**lời tuyên bố** → claim là đơn vị phân tích. Các kiến trúc thay thế đều thua:

- *Chấm điểm cấp công ty:* không có ground truth để validate; rủi ro quy chụp ("AAA
  greenwashing 80%" là cáo buộc, "claim X bị bài Y mâu thuẫn" là sự kiện kiểm chứng được);
  dữ liệu hai kênh lệch khối lượng nghiêm trọng (4.785 KPI report vs 108 KPI news) nên mọi
  phép trung bình bị phía tự khai nhấn chìm. Claim-centric miễn nhiễm: conduct thưa → claim
  "unverified" (trạng thái trung thực), không phải điểm số sai.
- *Đối chiếu số liệu đối xứng report↔news:* là data reconciliation, không phải greenwashing —
  thiếu mỏ neo "công ty đã hứa/khẳng định".
- Claim-centric còn khớp người dùng cuối (claim ledger đọc như hồ sơ analyst, dẫn nguồn
  trang/bài) và cho phép đánh giá trung thực khi không có nhãn (step10 đo linking machinery).

**Điểm mù của claim-centric — và là lý do tồn tại của tầng chỉ tiêu:** nó chỉ bắt được
greenwashing *có phát ngôn*. Hai dạng lọt lưới: (a) **greenwashing bằng im lặng** (selective
disclosure — né khai chỉ tiêu bất lợi; không có claim thì không có gì để cross-check);
(b) **conduct xấu không đối ứng claim cụ thể** (án phạt lơ lửng, hiện chỉ vớt qua
`--review-queue`). Tầng chỉ tiêu vá đúng hai chỗ này: chỉ tiêu bắt buộc trống `measuredUnder`
là tín hiệu không cần claim; Penalty treo vào TT96-6.5.1 có chỗ đứng cấu trúc thay vì lơ lửng.

---

## 3. Thiết kế chọn: 2 tầng — văn bản → chỉ tiêu, node mang identity, label mang vai trò

Trục chia đúng là **cấu trúc nội tại của chuẩn**, không phải topology cục bộ của graph:

```
(Regulation "TT 96/2020")  ◄──partOf── (StandardIndicator TT96-6.1.1 "Tổng phát thải KNK")
                                            ▲              ▲               ▲
                              measuredUnder │  measuredUnder│    alignsWithIndicator
                                            │              │               │
                                    (KPIObservation)   (Emission)   (SustainabilityClaim)

(StandardIndicator TT96-6.1.1) ──equivalentTo──► (StandardIndicator GRI 305-1)   [giai đoạn 3]
```

- **Tầng văn bản** (4–5 node): TT 96/2020, QĐ 2171, QCVN 09, SSC-IFC, GRI — dùng class
  `Standard`/`Regulation` sẵn có; đồng thời là node canonical để về sau gộp các mention
  `adoptsStandard` lộn xộn (C3).
- **Tầng chỉ tiêu** (~35 node): sinh deterministic từ `kpi_definitions_construction.json`
  (mỗi định nghĩa có sẵn `id`, `name`, `definition`, `pillar`, `source.document`,
  `source.section`). Không qua LLM → không nhiễu mention.
- **Node TT96-6.1.1 là JOIN POINT:** mọi bằng chứng claim-side lẫn conduct-side của cùng một
  chỉ tiêu hội tụ về một node; phép so claim↔conduct là so hai nhánh `source_type` khác nhau
  tại node đó.

### 3.1 Class mới trong `config/schema.json`

```json
{
  "class": "StandardIndicator",
  "properties": ["id", "name", "definition", "pillar", "section",
                 "source_document", "valid_from", "valid_to", "is_current"],
  "identity_keys": ["id"]
}
```

T1 timeless đúng P1: identity là mã chỉ tiêu, **không** có time field trong `identity_keys`
(step00 lint sẽ pass). Tách class riêng thay vì nhét vào `Standard` để phân biệt rõ node
reference chuẩn hóa với node mention do LLM extract.

### 3.2 Edge mới — chỉ 3 label + tái dùng `partOf`

| Edge | Source → Target | Cách sinh | Stage sở hữu |
|---|---|---|---|
| `partOf` *(tái dùng)* | StandardIndicator → Standard / Regulation | offline, từ block `source.document` của từng định nghĩa | **step05c · 0 đ** |
| `measuredUnder` | KPIObservation / Emission / Penalty → StandardIndicator | offline, map 1-1 theo `kpi_type` (đã canonical hóa ở step03c); Emission → TT96-6.1.x theo `category`/`scope`; Penalty → TT96-6.5.x (xem cảnh báo §5.3) | **step05c · 0 đ** |
| `equivalentTo` | StandardIndicator (TT96) → StandardIndicator (GRI) | offline, đọc crosswalk `config/standard_crosswalk.json` (vd. TT96-6.1.1 ↔ GRI 305-1/305-2) | **step05c · 0 đ** |
| `alignsWithIndicator` | SustainabilityClaim / Goal / Initiative → StandardIndicator | 2 tầng: keyword tiếng Việt/Anh trên `description` (step05c, offline) → LLM cho phần dư (step05d, có budget) | step05c + step05d |

Mỗi cặp thêm vào `schema.json` với `temporal_properties` chuẩn
(`valid_from`/`valid_to`/`recorded_at`) như mọi edge khác.

**GRI không còn là "giai đoạn 3".** Bản nháp đầu hoãn GRI vì cho rằng phải enrich dữ liệu
trước. Thực tế một khi file crosswalk tồn tại thì sinh node GRI + `equivalentTo` là thuần
deterministic, cùng độ khó với `partOf` — không có lý do gì để nó không nằm trong lần chạy
đầu tiên. Với yêu cầu "chạy step01→cuối ra graph đầy đủ", GRI **phải** thuộc step05c.

### 3.3 Crosswalk GRI để ở đâu — `config/`, KHÔNG phải file định nghĩa KPI

Bản nháp đầu (§5.4 cũ) đề xuất thêm field `gri_mapping` vào từng định nghĩa trong
`kpi_definitions_construction.json`. **Sai, và sẽ mất dữ liệu:** file đó là *generated data* —
`kpi_build/05_build_kpi_definitions.py` và `kpi_build/06_enrich_kpis.py` đều ghi đè nó
in-place (`OUT = HERE.parent / "kpi_definitions_construction.json"`). Bất kỳ ai rebuild
kpi_build một lần là toàn bộ mapping GRI thủ công bay sạch, không cảnh báo.

Crosswalk là **dữ liệu curate tay, tra cứu từ SSC-IFC guide** → đúng chỗ của nó là
`config/standard_crosswalk.json`, tracked trong Git, cạnh `schema.json` và
`issuer_registry.json` (CLAUDE.md: `config/` = "schema + dictionaries"). step05c đọc *hai*
nguồn: `kpi_definitions_construction.json` cho 35 chỉ tiêu TT96/SSC-IFC (generated, verbatim)
và `config/standard_crosswalk.json` cho ánh xạ GRI (curated). Ranh giới generated/curated
giữ nguyên vẹn.

### 3.4 Phạm vi nối — lọc theo 18 relationship của AAA

| Nhóm | Relationship (count AAA) | Quyết định |
|---|---|---|
| **Nối ngay, deterministic** | `reportsKPI` (4.420) → chỉ 484 node có mã chuẩn; `generatesEmission` (Emission: 24 node) → TT96-6.1.x; `subjectToPenalty` (4) → TT96-6.5.x | step05c. Penalty *lẽ ra* là mắt xích giá trị nhất (bằng chứng conduct gắn thẳng vào chỉ tiêu công ty phải tự khai) — nhưng cả 4 node hiện có đều là "bị phạt 0 lần" tự khai, xem cảnh báo §5.3 bước 5 |
| **Nối sau, cần LLM/keyword** | `claims` (1.093), `setsGoal` (712), `targetsScienceBased`, `takesPartIn` (470 — TT96 yêu cầu báo cáo "sáng kiến" tại 6.1.2/6.3.2/6.3.3) | step05c (keyword) + step05d (LLM). Claim là điều kiện để cross-check theo từng chỉ tiêu |
| **Không nối** | `ownsFacility`, `locatedIn`, `partnersWith`, `impactsCommunity`, `investsIn`, `owns`, `publishesReport`, `supersedes` | Thực thể/quan hệ ngữ cảnh — chuẩn không "định nghĩa" nhà máy hay đối tác; nối chỉ tạo hub nhiễu |
| **Trường hợp biên** | `adoptsStandard` (304) / `subjectToRegulation` (284): đã trỏ vào Standard — việc cần là gộp mention trùng về node canonical, không phải nối thêm. `holdsCertification` (84): tùy chọn `certifiesComplianceWith` sau, không phục vụ trực tiếp greenwashing | xử lý ở step04b/step05, xem §3.5 |

### 3.5 Vị trí trong pipeline — hai điểm chèn, không phải một

Câu hỏi cốt lõi: tầng reference được bơm vào **trước** hay **sau** entity resolution? Trả lời
là **cả hai, cho hai loại node khác nhau**, vì chúng có nhu cầu ngược nhau:

| Loại node | Chèn ở đâu | Vì sao |
|---|---|---|
| **Node văn bản** (TT 96/2020, QĐ 2171, QCVN 09, SSC-IFC, GRI) — 5 node | **TRƯỚC step05**, làm frozen anchor | Chúng *có* mention trong văn bản: 436 node `Standard`/`Regulation` do LLM nhặt, GRI ≥4 biến thể, TT96 2 biến thể (C3). Ta **muốn** entity resolution gộp mention vào node canonical. Đây chính xác là bài toán mà Stage A.2 của step05 đã giải cho issuer — tái dùng cơ chế, không phát minh lại |
| **Node chỉ tiêu** (35 `StandardIndicator`) | **SAU step05** | Chúng **không** có mention tự do trong văn bản (không ai viết "TT96-6.1.1" trong báo cáo), nên resolution không có việc gì để làm. Ngược lại còn nguy hiểm: `step05` dòng 399 xếp mọi class non-observation vào `entity_idx`, nên 35 node này sẽ lọt vào Stage B (embedding) và Stage C (LLM adjudication) — nơi `TT96-6.1.1` và `TT96-6.1.2` giống nhau đến mức LLM hoàn toàn có thể gộp nhầm. Bơm sau resolve loại bỏ rủi ro này ở mức kiến trúc, không phải bằng cách "hy vọng LLM đúng" |

Ngoài ra node chỉ tiêu bơm sau resolve còn tôn trọng bất biến **append-only, không bao giờ
reorder node** (`_node_key` của step06 và `node_index` của dossier là positional — xem
`PROVENANCE_PATCH.md`), nên một lần re-run step05c không làm hỏng dossier step07 đã trả tiền.

**Thứ tự chạy đầy đủ sau thay đổi** (phần in đậm là mới):

```
step01 → step02 → step03 → step03b → **step03c** → step04 →
step05 (+ anchor chuẩn) → step05b → **step05c** → **step05d (tùy chọn, LLM)** →
step06 → step07 → step07b → step08 → step09 → step10
```

| Stage | Loại | Vai trò trong trục chỉ tiêu |
|---|---|---|
| `step03c_canonicalize_kpis.py` | offline, **mới** (đã có trong `CROSSCHECK_EXPANSION.md`) | canonical hóa `kpi_type` free-text → mã chỉ tiêu. **Đây là nơi quyết định độ phủ của cả trục**, xem §5.2 |
| `config/standards_registry.json` | **config tĩnh** (từ 2026-07-26 không còn là stage) | 5 văn bản chuẩn + alias (GRI variants, TT96 VN/EN) + exclusions + `match_patterns`/`exclude_hints`. Sửa tay rồi chạy lại step05. `step00` audit độ phủ (`standards_registry_audit`). `src/step04b_build_standards_registry.py` vẫn còn để gây lại từ đầu nhưng KHÔNG nằm trên đường chạy — nó đọc output của step05 trong khi step05 đọc output của nó (vòng lặp). Xem `src_module/esg_kg/DESIGN.md` §4.2 |
| `step05_resolve_entities.py` | sửa nhỏ | mở rộng Stage A.2: ngoài issuer anchor, thêm **standards anchor** cho class `Standard`/`Regulation` dùng registry trên; cụm này cũng FROZEN (loại khỏi Stage B/C). Giải quyết C3 vĩnh viễn, ~10 dòng, dùng lại `load_issuer_index`/`normalize_name` |
| `step05c_link_standard_indicators.py` | offline, NO LLM, **mới** | vật chất hóa 35 node chỉ tiêu + `partOf` + `measuredUnder` + `equivalentTo` (GRI) + `alignsWithIndicator` tầng keyword |
| `step05d_align_claims_to_indicators.py` | LLM, có budget, **mới, tùy chọn** | `alignsWithIndicator` cho phần claim/goal mà keyword không quyết được |

Bốn stage này đều **idempotent**: chạy lại trên graph đã có trục chỉ tiêu không nhân đôi node
hay edge (khớp theo `identity_keys`). Đó là điều kiện để chúng nằm trong pipeline thường
trực chứ không phải script chạy một lần.

**Công việc kèm theo, bắt buộc, để đây thực sự là pipeline:**

1. `CLAUDE.md` — mục "Pipeline architecture" phần C và mục "Common commands" phải liệt kê
   step03c/step04b/step05c/step05d; nếu không, người chạy tiếp theo (kể cả Claude Code) sẽ
   chạy step05b → step06 và im lặng bỏ qua trục chỉ tiêu.
2. `test/test_temporal_invariants.py` — thêm case: idempotency của step05c, bất biến
   node-order, P1 lint cho `StandardIndicator` (identity_keys không chứa time field).
3. `docs/SYSTEM_DESIGN.md` — sơ đồ end-to-end thêm tầng reference.
4. step07 phải **thực sự tiêu thụ** trục này (§6) — nếu không, ta xây một tầng edge không ai
   đọc, và mọi lợi ích trong doc này chỉ nằm trên giấy.

---

## 4. Hiện trạng kênh news và `source_type` (bối cảnh dữ liệu cho step05c)

Một class node duy nhất, phân biệt bằng property `source_type=report|news` (step02 dập).
Hai node cùng nói về một sự thật **không bao giờ bị gộp** vì `identity_keys` của
KPIObservation chứa `source_id` — đúng chủ đích observation-per-source: giữ cả hai phiên bản
mới so được claim với conduct. Số liệu thật:

| Class | report | news | thiếu source_type |
|---|---|---|---|
| KPIObservation | 4.785 | 108 | 13 (backfill mặc định `report`) |
| Emission | 24 | 0 | — |
| Penalty | 4 | **0** | — |
| Controversy | 2 | **0** | — |
| MediaReport | 75 | 16 | — |
| SustainabilityClaim | 1.217 | 0 | — |

Hàm ý quan trọng:

1. **Phía conduct đang rất mỏng.** Penalty/Controversy hiện toàn `source_type=report` — án
   phạt trong graph là do công ty *tự khai*, chưa có cái nào từ báo chí độc lập. step07 lọc
   ứng viên `source_type == "news"` (dòng ~405) nên dù `CONDUCT_CLASSES` khai báo 5 class
   (Controversy, Penalty, MediaReport, KPIObservation, ThirdPartyVerification), vòng chạy
   thật chỉ có 108 KPI news + 16 MediaReport news làm đối trọng.
2. **News-KPI cũng nhiễu tài chính** (mẫu thực: "Vốn điều lệ 30 tỷ VND", `kpi_type="charter
   capital"`) — prompt news của step02 cần siết ưu tiên Penalty/Controversy/KPI môi trường.
3. **Giới hạn edge nền của step07:** supports → `verifiedBy` (chỉ ThirdPartyVerification,
   KPIObservation); contradicts → `contradictedBy` (chỉ Controversy) / `contradictedByMedia`
   (chỉ MediaReport). "KPI news mâu thuẫn claim" hay "Penalty mâu thuẫn claim" **không có
   edge nền hợp lệ** — chỉ sống ở dossier + edge advisory `llm_contradicts` (step08). Nếu
   muốn kết luận mạnh nhất sống trong graph nền: thêm cặp
   `SustainabilityClaim --contradictedBy--> Penalty` (và cân nhắc KPIObservation) vào schema.

Dù thiết kế trục chỉ tiêu có tốt đến đâu, sức phát hiện greenwashing hiện bị chặn bởi lượng
bằng chứng conduct độc lập — mở rộng crawl news + siết prompt news ngang hàng ưu tiên với
việc xây tầng chỉ tiêu.

---

## 5. Triển khai

### 5.1 Bước 0 — schema + đo trước/sau (0 đ)

1. Thêm class `StandardIndicator` (§3.1) và 4 cặp edge (§3.2) vào `config/schema.json`.
2. `python src/step00_graph_quality_report.py --label before_indicator_axis` (chuẩn quy trình
   before/after của `TEMPORAL_KG_DESIGN.md` §4).

### 5.2 Độ phủ: sửa ở nguồn (step01) *và* ở hạ nguồn (step03c) — không phải một trong hai

Đây là chỗ khác biệt lớn nhất giữa "vá graph AAA" và "làm pipeline". Bản nháp đầu coi độ phủ
thấp (484/4.906 ≈ 10%) là hạn chế phải chịu đựng, chờ step03c gỡ dần. Với yêu cầu pipeline,
phải tách bạch hai nguồn của vấn đề:

**(a) Nguồn — `step01` prompt.** Với công ty *mới*, độ phủ do step01 quyết định hoàn toàn.
Hiện prompt có escape hatch `"other"` (dòng ~214) và không phân biệt KPI tài chính với KPI
ESG, nên extractor nhặt cả bảng cân đối kế toán. Bằng chứng trên dữ liệu AAA: trong 4.422
KPIObservation *không* có mã chuẩn, top title là "Lợi nhuận sau thuế" (30), "Doanh thu" (26),
"Tổng tài sản" (15…), và `unit` phân bố `VND` 2.024 / `tỷ đồng` 274 / `billion VND` 184 —
tức **~85% phần đuôi là KPI tài chính thuần**, nhiễu đúng nghĩa. Sửa thường trực:

- tách `indicator_id` thành **field riêng, nullable, enum đóng theo 35 mã** — không dùng chung
  ô với `kpi_type` free-text nữa (hiện `kpi_type` gánh cả hai vai, nên "Revenue" và
  "TT96-6.1.1" nằm cùng một trường);
- thêm cờ phân miền (vd. `domain: environmental|social|governance|financial`) để KPI tài chính
  được gắn nhãn thay vì bị nhồi vào `"other"` — vừa giảm nhiễu, vừa giữ lại dữ liệu.

Đây là thay đổi **output schema của step01** → chỉ có tác dụng với dữ liệu extract mới; dữ
liệu AAA hiện có phải re-run step01 (tốn tiền Gemini) mới hưởng. Không bắt buộc làm ngay,
nhưng nếu không làm thì mỗi công ty mới lại thừa hưởng đúng độ phủ 10%.

**(b) Hạ nguồn — `step03c`, và đây là phần chạy được ngay với 0 đ.** `KPIObservation` có sẵn
field **`title` trên 4.896/4.906 node** (vd. `"Chi phí điện năng"`, `"Male employees"`,
`"Tỷ lệ tham dự họp HĐQT"`) cộng với `unit`. Một từ điển deterministic
`config/kpi_type_aliases.json` map `(title, unit)` → mã chỉ tiêu sẽ nâng độ phủ **mà không
cần re-extract gì cả**. Từ điển này không phải hack tạm: văn bản tự do luôn trôi, nên lớp
alias curate tay là thành phần vĩnh viễn — cùng tinh thần với `issuer_registry.json`.

**Kỳ vọng thực tế, nói thẳng để không hứa hão:** vì phần đuôi ~85% là tài chính (map vào TT96
là *sai*, không phải là bỏ sót), phần ESG thật lẫn trong đó chỉ vài trăm node — tín hiệu nhận
biết là `unit` ∈ {`mg/L` 39, `Tấn` 38, `kWh`, `người`/`employees` ~100}. Ước lượng
**484 → ~650–900 edge `measuredUnder`, tức độ phủ ~13–18%**, không phải 100%. Con số này vẫn
đủ để query selective-disclosure (§6.2) chạy có nghĩa, nhưng đừng trình bày trục chỉ tiêu như
thể nó phủ toàn bộ KPI.

### 5.3 `src/step05c_link_standard_indicators.py` (offline, NO LLM, 0 đ)

Chạy **sau step05b, trước step06** — lý do chọn mức resolved thay vì mức validated đã trình
bày ở §3.5 (tránh Stage B/C gộp nhầm chỉ tiêu; tôn trọng bất biến node-order).

```
Input : graph_output/resolved/resolved_graph.json
        kpi_definitions_construction.json        (generated — 35 chỉ tiêu TT96/SSC-IFC)
        config/standard_crosswalk.json           (curated — ánh xạ TT96 ↔ GRI)
        config/kpi_type_aliases.json             (curated — keyword → mã chỉ tiêu)
Output: resolved_graph.json (patched in place, append-only)
        graph_output/resolved/indicator_axis_stats.json
Flags : --dry-run, --defs <path>, --crosswalk <path>, --no-gri, --no-align, --stats-out <path>
```

Thuật toán:

1. Đọc 35 định nghĩa → tạo (nếu chưa có) 35 node `StandardIndicator` + node văn bản còn thiếu
   — **append vào cuối** mảng `nodes`; idempotent theo `identity_keys`. Node văn bản bình
   thường đã tồn tại sẵn do step04b + standards anchor của step05 (§3.5); step05c chỉ tạo bù
   khi chạy trên graph chưa qua anchor.
2. Emit `partOf` chỉ tiêu → văn bản theo `source.document`.
3. Quét `KPIObservation`: `kpi_type` khớp regex `^(TT96-|QD2171|QCVN09|SSCIFC-)` → edge
   `measuredUnder`. (Phần free-text đã được step03c canonical hóa trước đó — step05c **không**
   tự đoán, nó chỉ đọc mã đã canonical. Giữ ranh giới này để lỗi map luôn truy được về
   step03c.)
4. `Emission` → `measuredUnder` TT96-6.1.1 theo `category`/`scope` (24 edge).
5. `Penalty` → TT96-6.5.x — **cẩn thận, heuristic ở bản nháp đầu bị sai.** Bản nháp viết "có
   `amount` → 6.5.2, không có → 6.5.1"; thực tế cả 4 node Penalty đều có `amount`, và mẫu
   thật là:

   ```json
   {"penalty_id": "AAA_2022_EnvPenalty_0times", "amount": 0,
    "description": "Số lần bị phạt do không tuân thủ pháp luật, quy định về bảo vệ môi trường"}
   ```

   Đây **không phải án phạt** — đây là công ty *tự khai đã bị phạt 0 lần*, tức một tuyên bố
   tuân thủ (claim), không phải bằng chứng conduct. Treo nó vào TT96-6.5.x như bằng chứng
   conduct sẽ tạo tín hiệu **ngược dấu**: một lời tự khen bị đếm như một vi phạm. Quy tắc
   đúng: `amount == 0` (hoặc `penalty_id` khớp `_0times`) → gắn cờ
   `self_reported_zero=true` và **không** emit `measuredUnder` conduct; nếu muốn giữ, emit
   như claim-side với `source_type=report` được ghi rõ. Chỉ Penalty có `amount > 0` mới là
   mắt xích conduct thật.
6. `equivalentTo`: đọc `config/standard_crosswalk.json` → sinh node `StandardIndicator` cho
   các mã GRI được tham chiếu (vd. GRI 305-1) + edge TT96 → GRI. `--no-gri` để tắt.
7. `alignsWithIndicator` tầng keyword: match `description` của `SustainabilityClaim`/`Goal`/
   `Initiative` với từ khóa tiếng Việt+Anh của từng mục 6.x. Chỉ emit khi khớp **không mơ hồ**
   (đúng 1 chỉ tiêu ứng viên); phần còn lại để step05d. Mọi edge mang
   `alignment_method=keyword` để truy vết và để đo precision riêng theo từng tầng.
8. `temporal_metadata` của edge: `valid_from` kế thừa từ node quan sát, `recorded_at` = ngày
   chạy; stamp `anchor_method=offline_indicator_map` (cùng convention step03b).
9. Backfill 13 KPIObservation thiếu `source_type` → `report`.
10. Ghi stats: node/edge tạo mới, phân bố theo chỉ tiêu, **danh sách `kpi_type` không map được
    kèm số lượng** — file này là input trực tiếp để mở rộng `kpi_type_aliases.json` vòng sau.

Sau đó: `step06 --clear` → `step00 --label after_indicator_axis` → thêm case vào
`test/test_temporal_invariants.py`. Chi phí: **0 đ**, ~40–60 node + ~700–1.000 edge mới.

### 5.4 `src/step05d_align_claims_to_indicators.py` (LLM, có budget, tùy chọn)

- Chỉ nhận phần claim/goal mà tầng keyword của step05c **không** quyết được (mơ hồ hoặc
  không khớp) — cùng triết lý budget `--max-llm-pairs` của step05/step07.
- Output vẫn là edge nền `alignsWithIndicator`, mang `alignment_method=llm`. Đây là *phân loại
  chủ đề*, không phải phán xử supports/contradicts — nên được phép nằm ở graph nền, khác với
  edge advisory của step07 (xem §2.4).
- Tách khỏi step05c để giữ nguyên convention của repo: mỗi stage hoặc "NO LLM" hoặc "LLM",
  không nửa nọ nửa kia. Pipeline chạy được đầy đủ **kể cả khi bỏ qua step05d** — chỉ là độ phủ
  `alignsWithIndicator` thấp hơn.

### 5.5 Việc dọn dẹp song hành

- Siết prompt news step02: ưu tiên Penalty/Controversy/KPI môi trường (§4.2) — hiện news-KPI
  còn nhặt "Vốn điều lệ 30 tỷ VND".
- (Việc gộp mention GRI/TT96 và việc siết prompt step01 **không còn nằm ở đây** — chúng đã
  trở thành phần chính thức của pipeline: step04b + standards anchor ở §3.5, và §5.2(a).)

---

## 6. Tương tác với step07/step07b — chỉ tiêu làm *dẫn đường*, không thay *phán xử*

Retrieval hiện tại của step07 là token-overlap toàn cục (chẩn đoán D2 của
`CROSSCHECK_EXPANSION.md`). Tầng chỉ tiêu biến retrieval thành truy vấn graph 2-hop:

```
Claim --alignsWithIndicator--> (StandardIndicator) <--measuredUnder-- conduct (source_type=news)
```

**Retrieval hai tầng:** ưu tiên đường qua chỉ tiêu khi cả hai phía đã nối; fallback về
retrieval toàn cục (+ routing k-hop của CROSSCHECK_EXPANSION §3) cho phần chưa phủ; thu hẹp
fallback dần khi độ phủ tăng. Được 3 thứ: số cặp LLM giảm mạnh (chỉ phán xử cặp cùng chỉ
tiêu); precision tăng (cặp cùng chỉ tiêu gần như luôn relevant — LLM chỉ còn quyết
supports/contradicts); dossier giải thích được ("mâu thuẫn *trên chỉ tiêu TT96-6.1.1*").
step07b có thể tính evidence-balance softmax **theo từng chỉ tiêu** thay vì gộp cả claim.
LLM adjudication vẫn bắt buộc, không đổi.

### Truy vấn mới mà thiết kế mở ra (Cypher minh họa)

```cypher
// 1. Claim và conduct cùng chỉ tiêu (input có cấu trúc cho step07)
MATCH (c:SustainabilityClaim)-[:alignsWithIndicator]->(i:StandardIndicator)
      <-[:measuredUnder]-(e {source_type: 'news'})
RETURN c, i, e;

// 2. Selective disclosure: chỉ tiêu TT96 bắt buộc mà AAA không khai
MATCH (i:StandardIndicator)-[:partOf]->(:Regulation {name: 'Thông tư 96/2020/TT-BTC'})
WHERE NOT EXISTS {
  MATCH (i)<-[:measuredUnder]-(k) WHERE k.source_type = 'report'
}
RETURN i.id, i.name;

// 3. Lệch report vs news trên cùng chỉ tiêu (khóa join cho kpi_gap của step07b)
MATCH (i:StandardIndicator)<-[:measuredUnder]-(r {source_type:'report'}),
      (i)<-[:measuredUnder]-(n {source_type:'news'})
WHERE r.year = n.year
RETURN i.id, r.value, n.value;
```

---

## 7. Giới hạn và rủi ro

| Rủi ro | Đối sách |
|---|---|
| Độ phủ khởi điểm thấp: chỉ ~10% KPIObservation có mã chuẩn, và trần thực tế chỉ ~13–18% (§5.2) | sửa cả hai đầu: step01 emit `indicator_id` enum cho dữ liệu mới, `kpi_type_aliases.json` cho dữ liệu cũ; stats của step05c liệt kê `kpi_type` chưa map để nuôi từ điển vòng sau; selective-disclosure query (§6.2) đã chạy có nghĩa với phần đã phủ |
| Claim alignment sai chủ đề → cross-check sai cặp | keyword trước (chỉ emit khi không mơ hồ), LLM sau; edge mang `alignment_method=keyword\|llm` để đo precision **riêng từng tầng** theo phương pháp step10 |
| Patch làm lệch node-order → hỏng `_node_key`/`node_index` | append-only tuyệt đối; assert trong test_temporal_invariants; step05c chạy SAU step05b |
| Nhầm node chỉ tiêu với node mention (C3) khi query | class riêng `StandardIndicator`; mention giữ nguyên class `Standard`/`Regulation`, được gộp về node canonical bởi standards anchor (§3.5) |
| Kênh news quá mỏng làm cross-check ít tác dụng thực | ưu tiên song song việc nuôi news (§4); không coi trục chỉ tiêu là thuốc chữa thiếu dữ liệu |
| **35 node chỉ tiêu trở thành hub → hỏng chính tiêu chí Q7 mà §2.3 dùng để bác bỏ phương án khác** | phân tán qua 35 node (không phải 1) đã giảm bậc đáng kể, nhưng `TT96-6.6.1` vẫn sẽ hứng ~89+ edge. Phải kiểm bằng `step00 --label after_indicator_axis` chứ không suy đoán; nếu Q7 xấu đi, cân nhắc loại class reference khỏi metric hub-free (node reference khác bản chất với node thực thể) — và ghi rõ quyết định đó vào `TEMPORAL_KG_DESIGN.md` |
| **Stage mới bị bỏ quên khi chạy pipeline** — rủi ro đặc thù của việc này là *pipeline*, không phải patch | cập nhật `CLAUDE.md` (§3.5 mục 1) là bắt buộc, không phải tùy chọn; thêm cảnh báo trong step06 khi graph không có node `StandardIndicator` nào (nhắc "đã chạy step05c chưa?") |
| Trục chỉ tiêu được xây nhưng step07 vẫn retrieval token-overlap → tầng edge không ai đọc | §6 phải được triển khai cùng đợt; tiêu chí nghiệm thu là **số cặp LLM của step07 giảm** và dossier dẫn được mã chỉ tiêu, không phải "đã có edge trong Neo4j" |

## 8. Tham chiếu

- Sơ đồ thiết kế: https://claude.ai/code/artifact/b47d74f9-c7d1-459a-ac9d-640058804fde
- `CROSSCHECK_EXPANSION.md` — step03c (khóa join KPI), retrieval routing, kế hoạch 4 tuần defense-1
- `ENTITY_RESOLUTION.md` — Stage A.2 frozen anchor, cơ chế mà standards anchor (§3.5) tái dùng
- `KPI_EXTRACTION_FROM_JSONL.md` — prompt step01, nơi sửa `indicator_id`/`domain` ở §5.2(a)
- `TEMPORAL_KG_DESIGN.md` — P1 (identity timeless), Q7 (hub-free), quy trình step00 before/after
- `PROVENANCE_PATCH.md` — bất biến node-order positional mà step05c phải tôn trọng
- `CLAIM_CONDUCT_CROSSCHECK.md` — vì sao LLM adjudication bắt buộc, self-verification guard
- `KPI_DEFINITIONS_CONSTRUCTION_BUILD.md` — nguồn gốc verbatim của 35 định nghĩa
