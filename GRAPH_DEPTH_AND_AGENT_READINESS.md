# Làm gì để đồ thị "lên agent" được — và vì sao nó đang nông

> **Trạng thái:** Ghi chép tư vấn, viết ngày **2026-07-29**. Không phải đặc tả triển khai.
>
> **Nguồn:** trả lời trực tiếp cho 2 câu hỏi đặt ra khi đọc
> [`SSRL_REASONING_ASSESSMENT.md`](./SSRL_REASONING_ASSESSMENT.md):
> 1. Theo file đó thì nên **sửa graph / scale data công ty khác / sửa schema / sửa logic** —
>    cái nào để lên được agent?
> 2. Nhận xét: *"graph hiện tại đang nông và nó còn ngang phè ra 2 bên chứ không sâu."*
>
> **⚠ Cảnh báo về số liệu.** `graph_output/`, `data/`, `kpi_output/` **không có trên máy tại
> thời điểm viết** (chưa chạy `python src/data_sync.py pull`). Mọi con số hiện trạng dưới đây
> **lấy lại từ `SSRL_REASONING_ASSESSMENT.md`** (build 2026-07-26, 10.423 node / 14.399 cạnh),
> **chưa được đo lại độc lập**. Đo lại toàn bộ trước khi trích vào luận văn.
>
> **Đọc kèm:** [`SSRL_REASONING_ASSESSMENT.md`](./SSRL_REASONING_ASSESSMENT.md) ·
> [`docs/TEMPORAL_KG_DESIGN.md`](./docs/TEMPORAL_KG_DESIGN.md) (P1–P8, Q1–Q8) ·
> [`docs/STANDARD_INDICATOR_AXIS.md`](./docs/STANDARD_INDICATOR_AXIS.md)

---

## Mục lục

- [Phần I — Sửa cái gì để lên agent](#phần-i--sửa-cái-gì-để-lên-agent)
  - [1. Câu trả lời ngắn](#1-câu-trả-lời-ngắn)
  - [2. Ba điểm assessment nói đúng nhất](#2-ba-điểm-assessment-nói-đúng-nhất)
  - [3. Hai cái bẫy assessment chưa nói](#3-hai-cái-bẫy-assessment-chưa-nói)
  - [4. "Sửa graph" cụ thể là sửa file nào](#4-sửa-graph-cụ-thể-là-sửa-file-nào)
- [Phần II — Vì sao đồ thị nông và rộng](#phần-ii--vì-sao-đồ-thị-nông-và-rộng)
  - [5. Hình dạng thật](#5-hình-dạng-thật)
  - [6. Nguyên nhân gốc: trích xuất theo trang](#6-nguyên-nhân-gốc-trích-xuất-theo-trang)
  - [7. Nguyên lý làm sâu: node pivot](#7-nguyên-lý-làm-sâu-node-pivot)
  - [8. Cái KHÔNG làm nó sâu hơn](#8-cái-không-làm-nó-sâu-hơn)
  - [9. R7 — chỉ số còn thiếu để đo "sâu"](#9-r7--chỉ-số-còn-thiếu-để-đo-sâu)
- [10. Việc tiếp theo](#10-việc-tiếp-theo)

---

# Phần I — Sửa cái gì để lên agent

## 1. Câu trả lời ngắn

Không phải chọn một trong bốn. Nhưng **nút thắt không nằm ở schema, cũng không nằm ở logic** —
schema và logic hiện tại đã đủ tốt để lên agent. Nút thắt là **topology (hub) + khối lượng dữ
liệu phía conduct + số công ty**.

| Ưu tiên | Việc | Vì sao | Chi phí |
|---|---|---|---|
| **0** | Đo `R1` / `R1′` thành script trong `step00` | Cổng go/no-go. Không có nó thì 3 việc dưới không chứng minh được gì | 0đ · ~1 ngày |
| **1** | **Đa công ty (3–5 cty cùng ngành)** | Điều kiện *tồn tại* của multi-hop. Một công ty ⇒ mọi đường đi là `claim → AAA → conduct` = retrieval, không phải reasoning | LLM (đắt nhất) |
| **2** | **Phân rã hub 9.511** bằng node `ReportingPeriod` | Hạ bậc ~10×, thêm hop thời gian có ngữ nghĩa | 0đ · offline |
| **3** | **Crawl news nhiều hơn** | conduct pool = 124 node là trần cứng; 31,6% claim không có candidate nào | crawl + LLM |
| **4** | Neo 4 class phía conduct | `Penalty→Authority`, `MediaReport→Facility\|Location`; 4 class này đang ở 0–10% bậc ≥ 2 | 0đ |
| — | **Sửa schema** | Chỉ cần **1 class + 1 edge label** (`ReportingPeriod` / `hasReportingPeriod`), hoặc tái dùng `Report` / `publishesReport` là xong | ~0 |
| — | **Sửa logic** | Không sửa gì trước khi có agent. `step07` chỉ **thêm** một retrieval channel, không thay | sau |

## 2. Ba điểm assessment nói đúng nhất

**(a) Đa công ty không phải "scale cho đẹp", nó là điều kiện tồn tại.**
Với 1 công ty, agent RL sẽ học đúng một luật: *"về AAA rồi toả ra"*. Không có gì để reasoning.
Tiêu chí chọn công ty phải là **tối đa hoá số node T1 dùng chung** (cùng `Location`,
`Authority`, `Standard`, `StandardIndicator`) — đo trước bằng tên chuẩn hoá, miễn phí — chứ
**không** phải theo vốn hoá hay độ dễ tải báo cáo.

**(b) Walker là RETRIEVER, không phải JUDGE.**
Nếu để mạng RL xuất `supports` / `contradicts` thì toàn bộ framing advisory
(`docs/SYSTEM_DESIGN.md` §1.1, §12) sụp, và mất luôn ground truth miễn phí từ masked-edge
link prediction.

**(c) `22,8 LLM call / edge` là chỉ số đáng bán nhất.**
Đơn vị là tiền, không cần nhãn greenwashing, và dự án đang bị billing-block.

## 3. Hai cái bẫy assessment chưa nói

### 3.1 Split hub sẽ cho cải thiện R1′ GIẢ

`R1′` định nghĩa là *"cấm đi qua node bậc lớn nhất"*. Sau khi tách AAA thành 12 node
`ReportingPeriod`, **không còn node nào bị cấm nữa** ⇒ `R1′` nhảy vọt mà **không có hop mới
nào ra đời**.

> **Bắt buộc:** đổi định nghĩa thành **cấm cả cụm issuer** (AAA + mọi `ReportingPeriod` của
> nó) **trước khi đo lần đầu**. Nếu không, bảng before/after trong luận văn sẽ bị bắt lỗi ngay
> ở buổi bảo vệ.

### 3.2 Nên báo cáo R1 hai phiên bản

`R1` hiện đo trên mẫu **đều toàn bộ cạnh** ⇒ ~34% mẫu là `reportsKPI` — đúng cái quan hệ
thoái hoá mà §0 của assessment bảo phải loại khỏi train/test.

| Biến thể | Định nghĩa | Dùng để |
|---|---|---|
| `R1_all` | mẫu đều toàn bộ cạnh | so sánh bảo thủ với FB15K-237 (99,8%) |
| **`R1_trainable`** | chỉ trên tập quan hệ thực sự đem đi train | **trần Hits@1 thật** |

`R1_trainable` nhiều khả năng cao hơn 46,8% đáng kể — và nó mới là con số quyết định go/no-go.

## 4. "Sửa graph" cụ thể là sửa file nào

**Ràng buộc cứng:** `src/step06_load_graph_to_neo4j.py` khoá node theo **array index**, và
dossier của `src/step07_crosscheck_claims_vs_conduct.py` dùng `node_index` theo **vị trí** —
1.093 dossier đã trả tiền LLM (3.461 lượt gọi). Mọi thay đổi phải là **append-only stage
mới**, đúng khuôn `src/step05c_link_standard_indicators.py` (assert prefix node/edge cũ không
đổi). **Tuyệt đối không sửa `step05`.**

```
src/step05e_split_issuer_hub.py     (mới)  append ReportingPeriod + rewire,
                                           dựng từ temporal_metadata.valid_from (có sẵn trên 99,1% cạnh)
src/step05f_anchor_conduct.py       (mới)  Penalty→Authority, MediaReport→Facility|Location
src/step00_graph_quality_report.py  (sửa)  thêm R1 / R1′ / R2–R7 + Q7(d′) có trần bậc
config/schema.json                  (sửa)  + ReportingPeriod, + hasReportingPeriod
```

---

# Phần II — Vì sao đồ thị nông và rộng

## 5. Hình dạng thật

```
                         AAA  (bậc 9.511)
        ┌────────┬────────┬────────┬────────┬────────┐
     KPIObs    Claim    Goal   Initiative  Facility  ...
     (4.906)  (1.215)   (784)    (495)

     70,8% node bậc 1  ·  75,7% là lá  ·  median degree = 1
```

Đây là **đồ thị hình sao lưỡng phân, độ sâu 2**. "Ngang phè ra 2 bên" là mô tả đúng về mặt kỹ
thuật: chiều rộng 4.890, chiều sâu 2.

## 6. Nguyên nhân gốc: trích xuất theo trang

`step02` trích xuất **theo từng trang** (`build_page_prompt`,
`src/step02_extract_triplet_from_jsonl.py:368`; output `graph_output/graphs/<doc>/page{N}.json`).

Prompt **đã có** hẳn mục *EVENT ANCHORING RULES* bắt neo mỗi event vào ≥ 2 thực thể
(`src/step02_extract_triplet_from_jsonl.py:175-193`) — nên vấn đề **không phải prompt viết
thiếu**.

Vấn đề là: trong phạm vi **một trang**, thực thể duy nhất luôn đồng xuất hiện với mọi thứ là
chính công ty phát hành. Nhà máy tên ở trang 30, KPI ở trang 55 — LLM không bao giờ nhìn thấy
cả hai cùng lúc, nên **không có cách nào nối chúng**.

> **Trích xuất theo trang thì tất yếu sinh ra đồ thị hình sao.**
> Chiều sâu **không thể trích xuất ra được** — nó phải được **join lại sau**.

**Bằng chứng:** hai stage duy nhất từng làm đồ thị sâu lên đều là stage join hậu kỳ, offline,
**không dùng LLM**:

| Stage | Việc | Kết quả đo được |
|---|---|---|
| `step03b_anchor_kpi_facilities.py` | gazetteer neo KPI → Facility | Q7(e) bắt đầu nhúc nhích |
| `step05c_link_standard_indicators.py` | trục chỉ tiêu TT96/GRI | **Q7(c) 25,1% → 34,9%**<br>**Q7(e) 9,2% → 19,9%** |

Một stage offline, không tốn token, làm được điều mà 3 tháng crawl không làm được.
**Công thức đã được chứng minh — chỉ cần lặp lại.**

## 7. Nguyên lý làm sâu: node pivot

> Đồ thị sâu lên khi **một node lá có được cạnh thứ hai tới một node mà các lá khác cũng chạm
> vào**. Gọi node đó là **pivot**. Mọi đường đi sâu đều có dạng `lá → pivot → lá`.
> Không có pivot ⇒ mọi đường buộc phải quay về hub.

Xếp hạng pivot theo số lá hút được:

| Pivot | Số node pivot | Lá hút được | Trạng thái |
|---|---:|---:|---|
| `StandardIndicator` | ~35 | 1.277 | ✅ đã làm — **bằng chứng cơ chế đúng** |
| `ReportingPeriod` (trục thời gian) | ~12 | **4.890** | ⬜ chưa — **đòn mạnh nhất còn lại** |
| `Facility` (trục không gian) | có sẵn | vài trăm | ◐ mới dùng một phần (`step03b`) |
| `Location` | 356 | 743 | ◐ **52 node trùng tên** → dedupe = có ngay chiều sâu, 0đ |
| `Authority` (trục pháp lý) | 8 (đang trùng) | Penalty, Certification | ⬜ phía conduct đang 0% |
| Công ty khác | 3–5 | tất cả | ⬜ pivot liên công ty |

Sau khi có `ReportingPeriod`, hình dạng thành:

```
AAA ─┬─ Period(2023) ─┬─ KPIObs ─ measuredUnder ─▶ TT96-6.1.1 ◀─ alignsWith ─ Claim
     ├─ Period(2022) ─┤              └─ observedAtFacility ─▶ Nhà máy ─ locatedIn ─▶ Yên Bái
     └─ Period(2021) ─┘                                                              ▲
                                        Công ty B ─ Penalty ─ enforcedBy ─▶ Sở TNMT ─┘
```

- Bậc hub: **9.511 → ~12**
- Độ sâu: **2 → 5–6**
- Và quan trọng nhất: **xuất hiện đường đi không qua AAA** — đúng thứ `Q7(d)` đang đo và đang
  kẹt ở 8,0% qua cả 3 lần build.

## 8. Cái KHÔNG làm nó sâu hơn

Crawl thêm trang · trích thêm KPI · sửa prompt cho kỹ hơn — tất cả chỉ **làm nó rộng thêm**.

> Thêm 5.000 `KPIObservation` nữa thì hub thành 14.000 và **median degree vẫn bằng 1**.

Đây là lý do phải làm pivot **trước** khi scale dữ liệu: nếu không, mỗi công ty mới chỉ đẻ
thêm một ngôi sao rời rạc, và đồ thị 5 công ty chỉ là 5 ngôi sao cạnh nhau chứ không phải một
đồ thị sâu hơn.

## 9. R7 — chỉ số còn thiếu để đo "sâu"

`step00` hiện đo bậc trung vị và tỷ lệ lá — **cả hai đều đo *rộng*, không đo *sâu***. Đề nghị
thêm vào bộ R1–R6 của assessment:

> ### R7 — số metapath độ dài 3 có support ≥ 50 và không đi qua hub issuer

Đây mới là chỉ số nói agent **có gì để học hay không**. Nếu chỉ có 3–4 metapath như vậy thì
walker sẽ học thuộc lòng chứ không reasoning.

Dự đoán: hiện tại `R7` gần như bằng 0 ngoài `Claim → StandardIndicator ← KPIObservation`.
Nếu đo ra đúng vậy thì **bản thân con số đó là một kết luận mạnh cho luận văn** — nó định
lượng chính xác điều mà "đồ thị nông" chỉ nói được định tính.

| Mã | Chỉ số | Đo cái gì | Hiện trạng |
|---|---|---|---:|
| R1 / R1′ | reachability sau khi che cạnh | **trần Hits@1** | 46,8% / 26,9% |
| R5 | bậc p99 / max | action space | 13 / 9.511 |
| Q7(a,b) | median degree / % lá | **rộng** | 1 / 75,7% |
| **R7** | metapath-3 support ≥ 50, hub-free | **sâu** | *chưa đo* |

---

## 10. Việc tiếp theo

**Bước 0 bắt buộc:** `python src/data_sync.py pull` — graph chưa có trên máy.

Hai việc đầu tiên, cả hai đều 0đ và offline, làm trong ~1,5 ngày:

1. **Mở rộng `src/step00_graph_quality_report.py`** với `R1_all`, `R1_trainable`, `R1′`
   (định nghĩa cấm-cả-cụm-issuer theo §3.1), `R7`, và `Q7(d′)`.
   → Đây là **cổng go/no-go**, và là cột "TRƯỚC" cho mọi bảng so sánh về sau.
2. **Script đếm node T1 dùng chung giữa các công ty ứng viên** (tên chuẩn hoá,
   `Location` / `Authority` / `Standard` / `StandardIndicator`).
   → Chọn hộ công ty nào đáng crawl, tránh crawl xong 4 công ty rồi phát hiện chúng không
   chia sẻ node T1 nào.

Sau đó mới tới `src/step05e_split_issuer_hub.py` (append-only) và đo lại toàn bộ.

---

*Ghi chép tư vấn, không phải đặc tả. Mọi số "hiện trạng" trích lại từ
`SSRL_REASONING_ASSESSMENT.md` (build 2026-07-26) và **chưa được đo lại độc lập** —
xem cảnh báo đầu file.*
