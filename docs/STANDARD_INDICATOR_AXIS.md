# Trục chuẩn TT96/GRI — tầng chỉ tiêu `StandardIndicator` cho graph greenwashing

> Tài liệu thiết kế (đề xuất, chưa triển khai). Ngôn ngữ: tiếng Việt, mã/định danh giữ tiếng Anh
> theo convention của repo. Sơ đồ trực quan của thiết kế này:
> https://claude.ai/code/artifact/b47d74f9-c7d1-459a-ac9d-640058804fde
>
> Quan hệ với các doc khác: đây là phần **mở rộng mức graph** của
> `CROSSCHECK_EXPANSION.md` — doc đó chủ trương thay đổi tối thiểu (mức property/cặp-cạnh,
> không class mới) và đặt nền `step03c_canonicalize_kpis.py`; doc này bổ sung **một class mới
> có chủ đích** (`StandardIndicator`) để vật chất hóa vocabulary 35 KPI thành node trong graph.
> step03c càng canonical hóa được nhiều `kpi_type` thì tầng chỉ tiêu càng phủ rộng — hai việc
> cộng hưởng, không thay thế nhau.

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

| Edge | Source → Target | Cách sinh | Giai đoạn |
|---|---|---|---|
| `measuredUnder` | KPIObservation / Emission / Penalty → StandardIndicator | offline, map 1-1 theo `kpi_type`; Emission → TT96-6.1.x; Penalty → TT96-6.5.x | **GĐ 1 · 0 đ** |
| `alignsWithIndicator` | SustainabilityClaim / Goal / Initiative (+ Controversy, MediaReport nếu cần) → StandardIndicator | classify văn tự do về mục TT96 6.x — LLM hoặc keyword qua `pillar`/`ClaimKeyword` | GĐ 2 · LLM |
| `partOf` *(tái dùng)* | StandardIndicator → Standard / Regulation | offline, từ block `source` của từng định nghĩa | **GĐ 1 · 0 đ** |
| `equivalentTo` | StandardIndicator → StandardIndicator (GRI) | sau khi enrich field `gri_mapping` vào `kpi_definitions_construction.json` (vd. TT96-6.1.1 ↔ GRI 305-1/305-2 — mapping có trong SSC-IFC guide) | GĐ 3 · enrich |

Mỗi cặp thêm vào `schema.json` với `temporal_properties` chuẩn
(`valid_from`/`valid_to`/`recorded_at`) như mọi edge khác.

### 3.3 Phạm vi nối — lọc theo 18 relationship của AAA

| Nhóm | Relationship (count AAA) | Quyết định |
|---|---|---|
| **Nối ngay, deterministic** | `reportsKPI` (4.420) → chỉ 484 node có mã chuẩn; `generatesEmission` (Emission: 24 node) → TT96-6.1.x; `subjectToPenalty` (4) → TT96-6.5.x | GĐ 1. Penalty là mắt xích giá trị nhất: bằng chứng conduct gắn thẳng vào chỉ tiêu công ty phải tự khai |
| **Nối sau, cần LLM/keyword** | `claims` (1.093), `setsGoal` (712), `targetsScienceBased`, `takesPartIn` (470 — TT96 yêu cầu báo cáo "sáng kiến" tại 6.1.2/6.3.2/6.3.3) | GĐ 2. Claim là điều kiện để cross-check theo từng chỉ tiêu |
| **Không nối** | `ownsFacility`, `locatedIn`, `partnersWith`, `impactsCommunity`, `investsIn`, `owns`, `publishesReport`, `supersedes` | Thực thể/quan hệ ngữ cảnh — chuẩn không "định nghĩa" nhà máy hay đối tác; nối chỉ tạo hub nhiễu |
| **Trường hợp biên** | `adoptsStandard` (304) / `subjectToRegulation` (284): đã trỏ vào Standard — việc cần là gộp mention trùng về node canonical, không phải nối thêm. `holdsCertification` (84): tùy chọn `certifiesComplianceWith` sau, không phục vụ trực tiếp greenwashing | dọn dẹp song hành |

---

## 4. Hiện trạng kênh news và `source_type` (bối cảnh dữ liệu cho GĐ 1)

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

### 5.1 GĐ 0 — schema + đo trước/sau (0 đ)

1. Thêm class `StandardIndicator` (§3.1) và các cặp edge GĐ 1 (§3.2) vào `config/schema.json`.
2. `python src/step00_graph_quality_report.py --label before_indicator_axis` (chuẩn quy trình
   before/after của `TEMPORAL_KG_DESIGN.md` §4).

### 5.2 GĐ 1 — `src/step05c_link_standard_indicators.py` (offline, NO LLM, 0 đ)

Patch **sau resolve** cùng họ step05b (chạy sau step05b, trước step06). Chọn mức resolved
thay vì mức validated (kiểu step03b) vì: (a) không bắt team re-run step05; (b) node chỉ tiêu
là canonical sẵn, không cần resolution; (c) tôn trọng bất biến **append-only, không bao giờ
reorder node** (`_node_key` của step06 và `node_index` của dossier là positional — xem
`PROVENANCE_PATCH.md`).

```
Input : graph_output/resolved/resolved_graph.json
        kpi_definitions_construction.json
Output: resolved_graph.json (patched in place, append-only)
        graph_output/resolved/indicator_axis_stats.json
Flags : --dry-run, --defs <path>, --stats-out <path>
```

Thuật toán:

1. Đọc 35 định nghĩa → tạo (nếu chưa có) 35 node `StandardIndicator` + 4–5 node văn bản
   (`Regulation` TT 96/2020, QĐ 2171, QCVN 09; `Standard` SSC-IFC, GRI) — **append vào cuối**
   mảng `nodes`; idempotent theo `identity_keys` (chạy lại không nhân đôi).
2. Emit edge `partOf` chỉ tiêu → văn bản theo `source.document`.
3. Quét `KPIObservation`: `kpi_type` khớp regex `^(TT96-|QD2171|QCVN09|SSCIFC-)` → edge
   `measuredUnder` (kỳ vọng 484 + phần step03c canonical hóa thêm được).
4. `Emission` → `measuredUnder` TT96-6.1.1 (24 edge); `Penalty` → TT96-6.5.1/6.5.2 (4 edge;
   heuristic: có `amount` → 6.5.2, không → 6.5.1).
5. `temporal_metadata` của edge: `valid_from` kế thừa từ node quan sát, `recorded_at` = ngày
   chạy patch; stamp `anchor_method=offline_indicator_map` (cùng convention step03b).
6. Backfill 13 KPIObservation thiếu `source_type` → `report`.
7. Ghi stats: đếm node/edge tạo mới, phân bố theo chỉ tiêu, danh sách `kpi_type` không map được.

Sau đó: re-run `step06 --clear` → `step00 --label after_indicator_axis` → thêm case vào
`test/test_temporal_invariants.py` (append-only + idempotency + node-order invariant).
Tổng chi phí GĐ 1: **0 đ**, ~40 node + ~510 edge mới.

### 5.3 GĐ 2 — `alignsWithIndicator` cho Claim/Goal/Initiative (LLM, budget nhỏ)

- Bước lọc rẻ trước: `ClaimKeyword`/`pillar` + keyword tiếng Việt của từng mục 6.x → chỉ đưa
  claim qua LLM khi mơ hồ (cùng triết lý budget `--max-llm-pairs`).
- Output là edge nền `alignsWithIndicator` (đây là *phân loại chủ đề*, không phải phán xử
  supports/contradicts — nên được phép nằm ở graph nền, khác với edge advisory step07).
- Chạy chung đợt với lần re-run step07 có kiểm soát của `CROSSCHECK_EXPANSION.md` §5 tuần 3.

### 5.4 GĐ 3 — GRI (`equivalentTo`, 0 đ sau khi enrich)

Thêm field `gri_mapping` vào từng định nghĩa trong `kpi_definitions_construction.json`
(mapping TT96 ↔ GRI lấy từ SSC-IFC guide, vd. TT96-6.1.1 ↔ GRI 305-1/305-2) → step05c đọc
field này, sinh node chỉ tiêu GRI + edge `equivalentTo`. Không đập lại gì.

### 5.5 Việc dọn dẹp song hành (không chặn GĐ 1)

- Siết prompt step01: bớt nhặt KPI tài chính thuần (810 `other` là nhiễu) — tăng độ phủ mã chuẩn.
- Thêm alias GRI/TT96 vào entity resolution để gộp các biến thể mention (C3) về node canonical.
- Siết prompt news step02: ưu tiên Penalty/Controversy/KPI môi trường (§4.2).

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
| Độ phủ khởi điểm thấp: chỉ ~10% KPIObservation có mã chuẩn → tầng chỉ tiêu mỏng lúc đầu | step03c canonical hóa nâng dần; §5.5 siết prompt step01; GĐ 1 vẫn đáng làm vì selective-disclosure query (§6.2) chạy được ngay với phần đã phủ |
| Claim alignment (GĐ 2) sai chủ đề → cross-check sai cặp | lọc keyword trước, LLM sau; edge mang `alignment_method` để truy vết; đo precision mẫu theo phương pháp step10 |
| Patch làm lệch node-order → hỏng `_node_key`/`node_index` | append-only tuyệt đối; assert trong test_temporal_invariants; step05c chạy SAU step05b |
| Nhầm node chỉ tiêu với node mention (C3) khi query | class riêng `StandardIndicator`; mention giữ nguyên class `Standard`/`Regulation` |
| Kênh news quá mỏng làm GĐ 2+cross-check ít tác dụng thực | ưu tiên song song việc nuôi news (§4); không coi trục chỉ tiêu là thuốc chữa thiếu dữ liệu |

## 8. Tham chiếu

- Sơ đồ thiết kế: https://claude.ai/code/artifact/b47d74f9-c7d1-459a-ac9d-640058804fde
- `CROSSCHECK_EXPANSION.md` — step03c (khóa join KPI), retrieval routing, kế hoạch 4 tuần defense-1
- `TEMPORAL_KG_DESIGN.md` — P1 (identity timeless), Q7 (hub-free), quy trình step00 before/after
- `PROVENANCE_PATCH.md` — bất biến node-order positional mà step05c phải tôn trọng
- `CLAIM_CONDUCT_CROSSCHECK.md` — vì sao LLM adjudication bắt buộc, self-verification guard
- `KPI_DEFINITIONS_CONSTRUCTION_BUILD.md` — nguồn gốc verbatim của 35 định nghĩa
