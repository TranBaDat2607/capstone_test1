# Feedback: `gri_schema.json` + `GRI_SCHEMA_DOCUMENTATION.md`

**Về việc:** rà soát hai file GRI schema, đối chiếu với `config/schema.json` và
`docs/STANDARD_INDICATOR_AXIS.md` của pipeline hiện tại.
**Số liệu đo trên:** `graph_output/resolved/resolved_graph.json` (build 2026-07-21).
**Kết luận ngắn:** hướng đúng, nội dung dùng được gần như toàn bộ; cần đổi **định dạng
đầu ra** và sửa 4 điểm tích hợp. Không cần làm lại từ đầu.

---

## 1. Hướng của bạn đúng — và có số liệu chứng minh

35 chỉ tiêu `StandardIndicator` hiện có trong graph phân bố theo trụ cột:

| Trụ cột | Số chỉ tiêu |
|---|---|
| Môi trường | 20 |
| Xã hội | 14 |
| **Quản trị** | **1** |

Và chỉ tiêu "Quản trị" duy nhất đó là `TT96-6.8.1 Huy động vốn xanh` — tức tài chính
xanh, **không phải quản trị doanh nghiệp**.

Nghĩa là hiện **không có chỉ tiêu nào** cho: giám sát của HĐQT, đạo đức / chống tham
nhũng, đa dạng trong ban lãnh đạo, cơ chế khiếu nại, tác động kinh tế gián tiếp, đánh
giá nhà cung cấp.

Kiểm chứng trên claim thật chưa gắn được indicator:

| Claim trong graph | GRI phủ | TT96 / SSC-IFC |
|---|---|---|
| "HĐQT thực hiện tốt vai trò giám sát công bố thông tin" | GRI 2-14 | ❌ không có |
| "tác động kinh tế gián tiếp" | GRI 203 | ❌ không có |
| "IR department operated effectively" | GRI 2-29 | ❌ không có |
| "Thông tin về loại cổ phần được công bố đầy đủ" | GRI 2-1 / 2-6 | ❌ không có |

**Kết luận: GRI catalog là thứ cần thiết, không phải nice-to-have.** Toàn bộ nội dung
bạn thu thập — song ngữ EN/VI, `pillar`, text từng disclosure, `unit_of_measure`,
`requirement_type`, mapping SDG/ESRS/ISSB — giữ nguyên giá trị.

Độ phủ `alignsWithIndicator` hiện tại để tham khảo:

| Class | Đã gắn / Tổng | % |
|---|---|---|
| SustainabilityClaim | 35 / 1.217 | 2,9% |
| Goal | 15 / 722 | 2,1% |
| Initiative | 23 / 495 | 4,6% |

---

## 2. Thay đổi cấu trúc duy nhất (nhưng quan trọng)

**Đừng tạo class node mới (`GRIDisclosure`, `GRIRequirement`, `StandardVersion`).
Dùng lại class `StandardIndicator` đã có.**

Lý do: trục chỉ tiêu hoạt động được là nhờ **một join point duy nhất** — claim và bằng
chứng conduct cùng treo vào một node thì mới so được với nhau
(`docs/STANDARD_INDICATOR_AXIS.md` §3 và §6). Nếu claim đi vào `GRIDisclosure`, KPI đi
vào `GRIRequirement`, còn KPI TT96 vẫn ở `StandardIndicator`, ta có **ba vocabulary**
và đường claim→conduct đứt ở giữa.

Các cạnh cần dùng **đã tồn tại sẵn** trong `config/schema.json`, không phải thêm gì:

```
SustainabilityClaim / Goal / Initiative  --alignsWithIndicator-->  StandardIndicator
KPIObservation / Emission / Penalty      --measuredUnder------->   StandardIndicator
StandardIndicator                        --partOf-------------->   Standard / Regulation
StandardIndicator (TT96)                 --equivalentTo------->    StandardIndicator (GRI)
```

`alignsWithIndicator` **không quan tâm** target là TT96 hay GRI. Node GRI chỉ là một
`StandardIndicator` với `source_document: "GRI Standards"`. Nên yêu cầu *"claim tham
chiếu GRI khi không có TT96"* **chạy được mà không sửa schema dòng nào**.

Cũng bỏ giúp `COMPLIES_WITH` — dự án cố ý không phát biểu phán quyết tuân thủ (không có
ground truth; xem `docs/SYSTEM_DESIGN.md`). Cạnh tương ứng là `measuredUnder`, mang
nghĩa "số này được đo dưới chỉ tiêu kia", không phải "tuân thủ chỉ tiêu kia".

---

## 3. Đổi định dạng bàn giao

Từ `gri_schema.json` (JSON Schema mô tả đồ thị) → **`config/gri_catalog.json`**: bảng
tra cứu phẳng, khóa theo mã chỉ tiêu.

```jsonc
{
  "GRI 305-1": {
    "gri_standard": "GRI 305",
    "standard_title_en": "Emissions",
    "title_en": "Direct (Scope 1) GHG emissions",
    "title_vi": "Phát thải khí nhà kính trực tiếp (Phạm vi 1)",
    "pillar": "Môi trường",
    "definition_vi": "...",
    "requirement_type": "Quantitative",
    "units": ["tCO2e", "metric tons CO2e"],
    "tt96_equivalent": "TT96-6.1.1",
    "superseded_by": null,
    "source_pdf": "GRI 305_ Emissions 2016.pdf",
    "sha256": "...",
    "page": 12
  }
}
```

Ba chi tiết bắt buộc:

1. **Khóa phải là `"GRI 305-1"`** (có prefix + dấu cách), không phải `"305-1"`.
   `src/step05c_link_standard_indicators.py:212` tạo node với `identity_keys: ["id"]`
   theo đúng dạng này; lệch dạng sẽ sinh node trùng lặp.
2. **`versions` phải là mảng, không phải object đơn.** Bản hiện tại để
   `temporal_validity` là object *required* ở root ⇒ một bản ghi chỉ chứa được một
   version. GRI 305 có bản sửa thì phải nhân đôi `standard_id` — đúng lỗi P1 (danh tính
   phi thời gian) mà tài liệu tự nhận là tuân thủ.
3. **`version_id` đang mâu thuẫn:** phần mô tả ghi format `<standard_id>:<version_year>`
   (→ `"GRI 305:2016"`) nhưng example ghi `"GRI_305_2016"`. Mâu thuẫn này có ở **cả hai
   file**, mà đây là khóa danh tính nên phải chốt một dạng duy nhất.

---

## 4. Lỗi tích hợp sẽ làm hỏng UI nếu không sửa

**`pillar` phải dùng đúng bộ giá trị tiếng Việt đang có trong graph:**
`"Môi trường"` / `"Xã hội"` / `"Quản trị"` — **không phải** `"E — Environmental"` /
`"S — Social"` / `"G — Governance"`.

Lý do: 35 chỉ tiêu hiện tại đều dùng nhãn tiếng Việt, và ESG Evidence View lấy E/S/G của
mỗi thẻ claim từ `StandardIndicator.pillar` (`docs/ESG_EVIDENCE_VIEW.md`). Nếu node GRI
mang `"E — Environmental"` còn node TT96 mang `"Môi trường"`, UI sẽ hiện **hai nhóm trụ
cột riêng cho cùng một trụ cột**.

Liên quan: `step05c:215` hiện hard-code `"pillar": None` cho node GRI. Chưa lộ vì đang
có 0 node GRI trong graph — nhưng ngay khi bật GRI lên, mọi node sẽ `pillar=None` và UI
sẽ trống. Vì vậy `pillar` phải sẵn sàng **cùng lúc** với việc bật GRI, không phải sau.

---

## 5. Ưu tiên phạm vi: làm trục G và kinh tế trước

Đừng làm đều cả bộ GRI. Thứ tự theo giá trị thực tế:

| Ưu tiên | Nhóm GRI | Vì sao |
|---|---|---|
| **1** | GRI 2 (General Disclosures), GRI 205 (Anti-corruption), GRI 405 (Diversity), GRI 203 (Indirect Economic Impacts) | **TT96 không có gì cả** ở trục G và kinh tế — phần GRI mở khóa 100%, không trùng lặp |
| 2 | GRI 308 / 414 (đánh giá nhà cung cấp) | Chuỗi cung ứng, TT96 cũng không có |
| 3 | GRI 302 / 303 / 305 / 306 (năng lượng, nước, phát thải, chất thải) | TT96 **đã phủ** — giá trị ở đây là `equivalentTo` để đối chiếu quốc tế, không phải mở rộng độ phủ |

**Kỳ vọng thực tế, nói thẳng để không hứa hão:** hiện 97% claim chưa gắn indicator,
nhưng phần lớn trong đó **không phải nội dung ESG** — mẫu thật gồm "Risks related to raw
material price volatility", "Thương hiệu mạnh", "liquidity risk". GRI cũng không cứu
được những claim này. Một phần khác ("lao động được đào tạo", "BHXH, BHYT") thì
**TT96-6.6.3 / SSCIFC-S2 đã phủ** nhưng tầng keyword trượt — cần chạy `step05d` (LLM),
không cần GRI. Ước lượng GRI mở khóa được khoảng **1/4–1/3 phần ESG thật sự chưa gắn**,
tập trung ở trục G và kinh tế.

---

## 6. Việc phụ nhưng đang chặn cả trục GRI

Hiện graph có **0 node GRI và 0 cạnh `equivalentTo`**.

Nguyên nhân: `config/standard_crosswalk.json` có 23 dòng nằm trong danh sách tên là
`confirmed`, nhưng **trường `status` của cả 23 dòng đều là `needs_review`** — trong khi
`step05c:301` chỉ phát cạnh khi `status == "confirmed"`. Cổng này loại sạch 23/23 dòng.

Trường `tt96_equivalent` trong catalog (mục 3) chính là tư liệu để xác nhận 23 dòng đó
— công việc của bạn làm được **hai việc một lúc**.

Xem hiệu ứng ngay, không cần sửa gì (có cờ preview sẵn):

```bash
python src/step05c_link_standard_indicators.py --trust-draft-crosswalk --dry-run
```

---

## 7. Một trường mới cần thêm

Khi claim gắn vào GRI **vì TT96 không có**, cạnh phải mang cờ phân biệt, ví dụ
`indicator_axis = "tt96" | "gri_fallback"`.

Lý do: *"Việt Nam không quy định thì coi như doanh nghiệp theo chuẩn quốc tế"* là một
**giả định của nhóm nghiên cứu**, không phải nghĩa vụ pháp lý của doanh nghiệp. Nếu
không ghi rõ, báo cáo sẽ vô tình kết luận doanh nghiệp "thiếu sót" ở nơi luật không hề
đòi hỏi — đúng loại quy chụp mà `docs/SYSTEM_DESIGN.md` §1.1 cảnh báo.

Có cờ này thì tách được hai phát biểu rất khác nhau:

- *"AAA không công bố TT96-6.1.1 dù luật yêu cầu"* → phát hiện **tuân thủ**
- *"AAA không công bố GRI 205 chống tham nhũng — luật VN không yêu cầu, nhưng thông lệ
  quốc tế có"* → phát hiện **thông lệ**, tự nguyện

Và đây cũng là **đóng góp học thuật đứng riêng được**: chỉ ra TT96 thiếu hẳn trục G và
kinh tế so với GRI là một kết quả nghiên cứu, không chỉ là chi tiết kỹ thuật.

---

## Tóm tắt

| # | Việc | Loại |
|---|---|---|
| 1 | Đổi `gri_schema.json` → `config/gri_catalog.json`, bảng tra cứu khóa `"GRI 305-1"` | Đổi định dạng |
| 2 | Bỏ 3 class mới + 5 edge label; dùng lại `StandardIndicator` và 4 cạnh sẵn có | Cấu trúc |
| 3 | `pillar` dùng nhãn tiếng Việt `"Môi trường"/"Xã hội"/"Quản trị"` | Sửa lỗi tích hợp |
| 4 | `versions` thành mảng; chốt format `version_id`; bỏ `COMPLIES_WITH` | Sửa lỗi |
| 5 | Làm GRI 2 / 203 / 205 / 405 trước (trục G + kinh tế) | Ưu tiên |
| 6 | Thêm `tt96_equivalent` → dùng để xác nhận 23 dòng crosswalk đang kẹt | Mở khóa trục GRI |
| 7 | Thêm cờ `indicator_axis = tt96 \| gri_fallback` trên cạnh | Tính đúng đắn học thuật |

**Nội dung bạn đã thu thập giữ nguyên gần như toàn bộ — thay đổi chủ yếu nằm ở cách
đóng gói và ở 4 điểm tích hợp.**

### Tài liệu nên đọc kèm

- `docs/STANDARD_INDICATOR_AXIS.md` — thiết kế trục chỉ tiêu; §2.2/§2.3 đã cân nhắc và
  bác bỏ các phương án tách node theo chuẩn, §3.1 giải thích vì sao `StandardIndicator`
  là class riêng
- `docs/TEMPORAL_KG_DESIGN.md` — P1 (danh tính phi thời gian), Q7 (hub-free)
- `config/schema.json` — các cạnh sẵn có, dòng 741–793
