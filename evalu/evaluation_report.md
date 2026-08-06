# Báo cáo đánh giá hệ thống Graph-RAG phát hiện greenwashing

*Tạo lúc 2026-08-06T15:42:06+00:00 · khung tham chiếu: evalu.pdf §1-§3 (metric table + Likert rubric)*

> **Nguyên tắc của báo cáo này:** mọi con số đều đọc từ artifact trên đĩa. Metric không đo được thì ghi thẳng là **KHÔNG ĐO ĐƯỢC** kèm lý do và chi phí để đo — không có giá trị mặc định, không có số benchmark thay thế.

## 0. Phạm vi dữ liệu được đánh giá

| Artifact | Giá trị |
|---|---|
| Đồ thị đã resolve | 10,425 node · 14,402 cạnh |
| Sửa đổi lần cuối | `2026-08-01T15:03:38+00:00` |
| Hồ sơ claim (dossier) | 1,093 |
| Doanh nghiệp trong corpus | AAA (1 tổ chức duy nhất) |
| Tài liệu đã trích xuất thành đồ thị | **43** = 13 báo cáo thường niên + 30 bài báo |
| Năm của các báo cáo | 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020, 2021, 2022, 2023, 2025 |
| Câu `esg=true` của pilot AAA | 5,927 |
| Tỷ trọng node đến từ tin tức | **2.0%** (208/10,425) |
| Corpus quét ngành — đã phân loại, **CHƯA** vào đồ thị | 303,723 câu `esg=true` (1.216 tài liệu) |
| Snapshot dữ liệu | `nammovuivui-capstone/capstone` @ `23d5a8901ceb` (đẩy 2026-08-01T15:38:01+00:00) |

> **Toàn bộ báo cáo này mô tả MỘT doanh nghiệp** — AAA. Mọi con số bên dưới là của pilot đó, không phải của toàn ngành. Corpus quét ngành 1.216 tài liệu đã được phân loại ESG nhưng chưa từng chạy qua bước trích xuất đồ thị, nên không đóng góp node nào và không nằm trong bất kỳ mẫu số nào ngoài dòng SNR được ghi rõ là "quét ngành".

---
## 1. Tầng 1 — 11 chỉ số kiểm soát pipeline (evalu.pdf §1–§5)


### Giai đoạn 1 — Thu thập & phân loại ESG

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| ESG Signal-to-Noise Ratio (SNR) | **0.0658** (6.6%) | 390 / 5,927 | `data/labeled/{annual_labeled,news_labeled}/*.jsonl` |
| Paragraph Source Provenance Rate | **0.9816** (98.2%) | 6,258 / 6,375 | `esg_kg.report.quality.q6_provenance + provenance_patch_stats.json` |

- *ESG Signal-to-Noise Ratio (SNR)*: Tín hiệu = câu esg=true có con số KÈM ĐƠN VỊ, hoặc có thuật ngữ thuộc bộ từ vựng kiểm soát (TT96/GRI). Nhiễu = văn cam kết chung chung không kèm phép đo nào. Phạm vi là 53 tài liệu của pilot AAA (13 báo cáo thường niên + 40 bài báo); corpus quét ngành báo cáo riêng.

- *Paragraph Source Provenance Rate*: Tỷ lệ node mang dấu vết nguồn mà step05b truy ngược được về đúng tài liệu + số trang.

### Giai đoạn 2 — Trích xuất triplet & KPI

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Temporal Metadata Completeness (C_temporal) | **0.9690** (96.9%) | 13,956 / 14,402 | `esg_kg.report.quality.q5_timeliness` |
| Schema Compliance Rate (C_schema) | **1.0000** (100.0%) | 14,402 / 14,402 | `esg_kg.report.quality.q2_consistency` |
| Value Preservation Guard | **KHÔNG ĐO ĐƯỢC** | — | `src/esg_kg/graph/fix_triples.py::preserve_property_values` |

- *Temporal Metadata Completeness (C_temporal)*: Số cạnh mang temporal_metadata.valid_from. Trong đồ thị ĐÃ RESOLVE, thời gian sống trên cạnh và node T2 (P2), nên thực thể T1 đúng ra phải phi thời gian và không nằm trong mẫu số.

- *Schema Compliance Rate (C_schema)*: Số cạnh có bộ ba (lớp chủ thể, vị từ, lớp đối tượng) hợp lệ theo schema.

> **Value Preservation Guard — KHÔNG ĐO ĐƯỢC.** Bộ đếm số giá trị bị chặn chỉ được ghi ra log, không bao giờ lưu vào file stats. Muốn có tỷ lệ thì phải chạy lại bước sửa lỗi LLM step03 phase 2 (có tính phí). Đã kiểm chứng như một bất biến, không phải như một tỷ lệ.

### Giai đoạn 3 — Hợp nhất thực thể

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Timeless Identity Violation Rate (V_identity) | **0.0000** (0.0%) | 0 / 14 | `esg_kg.report.quality.q2_consistency (schema-level P1 lint)` |
| Cluster Conciseness (C_concise) | **0.9740** (97.4%) | 2,325 / 2,387 | `esg_kg.report.quality.q3_conciseness` |

- *Timeless Identity Violation Rate (V_identity)*: Số lớp thực thể T1 có trường thời gian nằm trong identity_keys. Mục tiêu là 0 — định danh T1 bắt buộc phi thời gian (P1).

- *Cluster Conciseness (C_concise)*: CHỈ đo vỡ cụm (under-merging): các node T1 trùng tên sau chuẩn hoá qua Stage A/B/C/D. Gộp nhầm (over-merging) cần nhãn nên KHÔNG đo ở đây.

### Giai đoạn 4 — Trục chỉ tiêu TT96/GRI

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Standard Indicator Alignment Coverage | **0.2564** (25.6%) | 624 / 2,434 | `graph_output/resolved/resolved_graph.json` |
| Zero-Report Self-Praise Exclusion | **1.0000** (100.0%) | 4 / 4 | `graph_output/resolved/resolved_graph.json + indicator_axis_stats.json` |

- *Standard Indicator Alignment Coverage*: Số node Claim/Goal/Initiative có cạnh alignsWithIndicator. Trục KPI (measuredUnder) báo cáo riêng — nó lấy từ kpi_id của bước canonicalize, không phải từ khớp cụm từ.

- *Zero-Report Self-Praise Exclusion*: BẤT BIẾN, không phải tỷ lệ — toàn đồ thị chỉ có 4 node Penalty với amount = 0. Báo cáo dưới dạng đếm.

### Giai đoạn 5 — Đối soát chéo claim ↔ conduct

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Evidence Asymmetry & Abstention Rate | **0.9158** (91.6%) | 1,001 / 1,093 | `graph_output/crosscheck/aaa_claim_assessments.json` |
| Self-Verification Exclusion Rate | **0.0978** (9.8%) | 18 / 184 | `graph_output/crosscheck/aaa_claim_assessments.json` |

- *Evidence Asymmetry & Abstention Rate*: Từ chối kết luận là hành vi được thiết kế khi thiếu bằng chứng độc lập. Chỉ số này đo độ mỏng của kho dữ liệu, không đo chất lượng model.

- *Self-Verification Exclusion Rate*: Tỷ lệ phán quyết 'supports' của LLM bị từ chối cấp cạnh verifiedBy vì domain của bằng chứng thuộc về chính doanh nghiệp.

#### Chi tiết SNR — chỉ số nhạy với định nghĩa "có căn cứ"

| Định nghĩa | SNR |
|---|---|
| Chặt: có số **kèm đơn vị đo** hoặc thuật ngữ TT96/GRI | **0.0658** (390/5,927) |
| Lỏng: có **bất kỳ chữ số nào** (cận trên) | 0.3563 (2,112/5,927) |
| Corpus quét ngành (đã phân loại, **chưa** vào đồ thị) | 0.0959 (29,133/303,723) |

Kho thuật ngữ dùng để đối chiếu: 322 mục (35 KPI TT96/QĐ2171/QCVN09/SSC-IFC + 136 mã GRI).

#### Chi tiết độ phủ trục chỉ tiêu

| Lớp node | Đã gắn chỉ tiêu | Tổng | Tỷ lệ |
|---|---|---|---|
| Goal | 204 | 722 | 28.3% |
| Initiative | 141 | 495 | 28.5% |
| SustainabilityClaim | 279 | 1,217 | 22.9% |
| KPIObservation (`measuredUnder`) | 617 | 4,906 | 12.6% |

Phân bố phương pháp gắn: `{'keyword': 639}`

---
## 2. Độ đúng trích xuất — round-trip grounding (A)

### **0.9778** (97.8%) — 3,912/4,001 giá trị KPI có mặt đúng trên trang mà chính node đó trích dẫn

> **Đây là chỉ số ĐỘ ĐÚNG thật, không phải proxy.** Văn bản gốc chính là ground truth cho câu hỏi "con số này có trong tài liệu không?", nên không cần ai gán nhãn. Nó lấp đúng lỗ hổng mà `quality.py` tự ghi nhận ở `q1_accuracy`: *"manual 30–50 node sample audit is out of scope"* — ở đây là 4,001 node, tự động.

- **89 giá trị KHÔNG tìm thấy** trên trang được trích dẫn → đây là danh sách cần soi tay.
- Không so được (đã loại khỏi mẫu số, không tính là đạt): `{'value_too_short_to_verify': 556, 'source_page_not_found': 280, 'no_value': 69}`
- Tổng node KPIObservation: 4,906

| Tài liệu nhiều sai lệch nhất | Khớp | Lệch |
|---|---|---|
| AAA_Baocaothuongnien_2020 | 308 | **24** |
| AAA_Baocaothuongnien_2016 | 215 | **18** |
| AAA_Baocaothuongnien_2021 | 291 | **12** |
| AAA_Baocaothuongnien_2023 | 166 | **12** |
| AAA_Baocaothuongnien_2022 | 207 | **9** |

Ví dụ giá trị không tìm thấy trên trang trích dẫn:

- `Vốn góp thêm` = **6000000000** VND → trích dẫn AAA_Baocaothuongnien_2012 p.2
- `Tỷ lệ cán bộ, nhân viên có trình độ từ cao đẳng trở lên` = **50** % → trích dẫn AAA_Baocaothuongnien_2014 p.17
- `Tổng giá trị đầu tư, đóng góp và hỗ trợ tài chính cho cộng đồng địa phương trong kỳ` = **1250000** VND → trích dẫn AAA_Baocaothuongnien_2015 p.26
- `Interest rate for normal business production sectors (medium/long-term)` = **11** %/year → trích dẫn AAA_Baocaothuongnien_2016 p.14
- `Total assets` = **1954765** million VND → trích dẫn AAA_Baocaothuongnien_2016 p.24

> ⚠ Khớp chỉ chứng minh con số CÓ MẶT trên trang. Nó không chứng minh con số được gán đúng chỉ tiêu, đúng kỳ hay đúng đơn vị. Vì vậy đây là CẬN TRÊN của độ đúng trích xuất.

---
## 3. Tầng 3 — đánh giá không cần nhãn ở tầng đối soát

*(theo `docs/EVALUATION_WITHOUT_LABELS.md`; toàn bộ offline, 0 đồng)*

### B2 — Kiểm định hoán vị trên số claim bị mâu thuẫn

- Quan sát thực tế: **22** claim `appears_contradicted` từ 25 mẩu bằng chứng mâu thuẫn.
- Phân phối null (1000 lần hoán vị, seed `20260806`): trung bình 24.7, khoảng [21, 25].
- **p = 0.003** (đuôi dưới).

> Đuôi DƯỚI mới là đuôi có ý nghĩa — xem docstring. p là tỷ lệ các lần rải ngẫu nhiên mà dồn mâu thuẫn vào ít claim đúng bằng mức hệ thống đã làm.

### B2b — Cặp (claim, bằng chứng) được giữ có mạch lạc hơn ghép ngẫu nhiên không?

| Thống kê | Quan sát | Null (ngẫu nhiên) | p |
|---|---|---|---|
| Chồng lấp từ vựng (Jaccard) | **0.1086** | 0.0154 | **0.001** |
| Khoảng cách năm trung bình | 6.172 năm | 5.822 năm | 0.994 |

> ⚠ Có phần luẩn quẩn: tầng retrieval vốn đã chọn theo chồng lấp từ vựng và cửa sổ năm. Vì vậy chỉ kết luận được rằng 'tập được giữ tách xa hơn nữa so với việc ghép lại ngẫu nhiên trong cùng bể đó'.

> **Kết quả âm cần ghi nhận:** bằng chứng được giữ **không** gần claim về mặt thời gian hơn mức ngẫu nhiên (p = 0.994). Chiều thời gian hiện không đóng góp gì cho việc ghép cặp — chỉ có chiều từ vựng.

### D — Bằng chứng đi SAU claim (kiểm nguyên tắc P8)

| Vai trò bằng chứng | Vi phạm | So sánh được | Tỷ lệ |
|---|---|---|---|
| `contradicts` (vi phạm P8 trực tiếp) | **22** | 25 | **88.0%** |
| `supports` (nhẹ hơn, xem ghi chú) | 129 | 166 | 77.7% |

- Khoảng cách lớn nhất: **+14 năm**.
- Phân bố (năm bằng chứng − năm claim): `{'-14': 1, '-13': 2, '-11': 1, '-10': 1, '-9': 5, '-8': 3, '-7': 2, '-6': 4, '-5': 2, '-4': 10, '-3': 5, '-1': 2, '0': 2, '1': 5, '2': 3, '3': 7, '4': 18, '5': 32, '6': 21, '7': 10, '8': 12, '9': 16, '10': 14, '11': 4, '12': 1, '13': 5, '14': 3}`

Các mâu thuẫn lệch thời gian nặng nhất:

- **+13 năm** — claim 2012 bị bác bỏ bằng bằng chứng 2025: "Actively sought investment sources to effectively use capital from shareholders and investors."
- **+13 năm** — claim 2012 bị bác bỏ bằng bằng chứng 2025: "Uses recycled raw materials to ensure less waste."
- **+10 năm** — claim 2015 bị bác bỏ bằng bằng chứng 2025: "Purchases raw materials and goods from domestic and international suppliers for production and business activi"

> Với một MÂU THUẪN, bằng chứng có năm sau claim là vi phạm P8 trực tiếp. Với một SUPPORT thì nhẹ hơn — bài báo 2016 có thể tường thuật hợp lệ một sự kiện 2015 — nên hai tỷ lệ được tách riêng và không được cộng gộp.

> ⚠ 100% evidence mang date_uncertain=true, tức năm thường là ngày đăng bài dùng làm proxy. Vì vậy đây là CẬN TRÊN của tỷ lệ vi phạm, không phải con số chính xác.

> **Vì sao kết luận này vững:** ba đường độc lập cùng chỉ về một chỗ — (1) B2b cho thấy khoảng cách năm của cặp được giữ không tốt hơn ghép ngẫu nhiên, (2) D cho thấy phần lớn mâu thuẫn dùng bằng chứng đi sau, (3) tham số `window_after` đang để 50 năm. `docs/EVALUATION_WITHOUT_LABELS.md` §3.3 đã **dự báo trước** MR-4 sẽ hỏng nặng; D xác nhận dự báo đó mà không tốn một lệnh gọi LLM nào.

### E — Ablation cửa sổ thời gian truy hồi

| `window_after` | supports | contradicts | Tổng bằng chứng | Claim còn bằng chứng |
|---|---|---|---|---|
| 0 năm | 37 | 3 | 40 | 25 |
| 1 năm | 41 | 4 | 45 | 30 |
| 2 năm | 43 | 5 | 48 | 33 |
| 3 năm | 50 | 5 | 55 | 39 |
| 5 năm | 94 | 11 | 105 | 62 |
| 10 năm | 155 | 23 | 178 | 85 |
| 50 năm ← **hiện tại** | 166 | 25 | 191 | 92 |

> Cửa sổ hiện tại cho phép bằng chứng đi sau claim tới 50 năm. Bảng này cho biết siết lại thì còn giữ được bao nhiêu bằng chứng.

> ⚠ Chỉ phát lại được những mẩu bằng chứng ĐÃ được giữ, nên đây là cận trên: nó không cho biết cửa sổ hẹp hơn sẽ đẩy thêm cặp mới nào vào top-k.

### Tính nhất quán trên claim trùng lặp

- **0.9565** — 22/23 nhóm claim trùng lặp cho cùng một kết luận.
- Khoảng tin cậy Wilson 95%: `[0.7901, 0.9923]` (mẫu nhỏ — đọc theo khoảng, không đọc theo tỷ lệ trần).
- ❗ Bất nhất: "largest plastic packaging exporter in vietnam" → `appears_supported` vs `unverified_insufficient_evidence` (năm [2020, 2023]).

### Hiệu suất tầng truy hồi (thay cho "Context Precision@k")

- **0.0604** — giữ lại 209/3,461 cặp ứng viên.
- Phân rã: `{'supporting_evidence': 166, 'contradicting_evidence': 25, 'flagged_non_independent_support': 18}`
- 106/1,093 claim có ít nhất một mẩu bằng chứng.

> ⚠ "Liên quan" ở đây chính là phán quyết của adjudicator, nên đây là lấy chính model đã phán xử để chấm điểm tầng truy hồi. Mang tính chẩn đoán, không phải kiểm định độc lập.

### Bất đồng nội bộ giữa điểm offline và phán quyết LLM

- **0.0604** — 66/1093 hồ sơ.

### Phổ `confidence` của LLM (ghi nhận, không phải điểm số)

- Phân bố: `{'0.8': 109, '0.9': 99, '1.0': 1}` → chỉ **3** giá trị phân biệt, thấp nhất 0.8.
- Quá ít giá trị phân biệt để hiệu chuẩn — ghi nhận như một phát hiện, không phải một metric. Calibration đã chết ở đây (docs/EVALUATION_WITHOUT_LABELS.md §8).

---
## 3. Những gì KHÔNG ĐO ĐƯỢC — và cần gì để đo

| Chỉ số | Vì sao chưa đo được | Chi phí để đo |
|---|---|---|
| RAGAS Context Recall | Cần tập ground-truth về những bằng chứng LẼ RA phải được truy hồi. Không có nhãn nào tồn tại — đó chính là tiền đề của đề tài. Đã ghi nhận là metric chết trong docs/EVALUATION_WITHOUT_LABELS.md §8. | gán nhãn thủ công tập bằng chứng vét cạn cho từng claim |
| RAGAS Faithfulness | Cần phán xử xem mỗi phần giải thích có được suy ra từ chính văn bản bằng chứng hay không — tốn một lệnh gọi LLM-judge cho mỗi hồ sơ, và sẽ là tự chấm điểm mình nếu dùng lại cùng một model. Không suy ra được từ artifact. | 191 lệnh gọi judge (hoặc một model độc lập thứ hai) |
| MR-1 Negation Flip | Cần chạy lại adjudicator THẬT trên claim đã bị chèn phủ định. Chạy trên stub thì chỉ đo được chính cái stub. | ~191 lệnh gọi LLM |
| MR-2 Numeric Flip | Cần chạy lại adjudicator THẬT trên bằng chứng đã đảo dấu con số. | ~191 lệnh gọi LLM |
| MR-3 Entity Change | Cần chạy lại adjudicator THẬT với tên doanh nghiệp bị thay thế. | ~191 lệnh gọi LLM |
| MR-4 Temporal Shift (P8) | Cần chạy lại adjudicator THẬT với bằng chứng có ngày sau ngày của claim. | ~191 lệnh gọi LLM |
| B1 — Specificity trên cặp ngẫu nhiên | Đây là kill-test của cả thiết kế: cặp (claim, conduct) ghép ngẫu nhiên có bị phán là irrelevant không? Cần adjudicator THẬT chấm trên những cặp mà retrieval KHÔNG chọn. Không thể giả — module cũ đã hardcode sẵn 99/100 cho chỉ số này. | 191 lệnh gọi LLM (~5,5% một lần chạy step07) |
| Độ chọn lọc của adjudicator (cặp giữ lại vs cặp bị loại) | Sẽ khiến B2b hết vòng luẩn quẩn, nhưng step07 không lưu lại 3.270 cặp ứng viên bị loại — chỉ lưu 191 cặp được giữ. Cần tách phần retrieval trong run() thành một hàm gọi được, rồi chạy lại offline miễn phí. | 0 lệnh gọi LLM, nhưng phải refactor nhẹ claims_vs_conduct.run() |
| IAA chuyên gia (Krippendorff α / Gwet AC2) | Chưa có đánh giá của người thật. evalu/sample_expert_annotations.json chỉ chứa 4 dòng tổng hợp sẵn, không đủ để tính hệ số đồng thuận — báo cáo cũ đã in ra α=0,5143 từ chính 4 dòng này. | >=3 người chấm độc lập trên >=30 hồ sơ |
| Value Preservation Guard | Bộ đếm số giá trị bị chặn chỉ được ghi ra log, không bao giờ lưu vào file stats. Muốn có tỷ lệ thì phải chạy lại bước sửa lỗi LLM step03 phase 2 (có tính phí). Đã kiểm chứng như một bất biến, không phải như một tỷ lệ. | chạy lại step03 phase 2 (có tính phí) |
| B3 — structural negative control (cross-company) | Corpus chỉ có MỘT doanh nghiệp: mọi tài liệu đã nạp đều thuộc về issuer duy nhất trong config/issuer_registry.json, nên trong đồ thị không tồn tại conduct của công ty khác để mà lọt sang. Số 0 ở đây do corpus bảo đảm, không phải do logic retrieval. | khi nạp thêm mã cổ phiếu thứ hai vào cùng một đồ thị |

---
## 4. Tầng chuyên gia (rubric Likert 5 điểm + IAA)

**KHÔNG ĐO ĐƯỢC.** Chỉ 0/4 dòng đánh giá ứng với một hồ sơ có thật trong corpus này. File đang có là bản mẫu dựng sẵn (claim của Vinamilk, dossier_id kiểu 'claim_vnm_2023_001') — không tồn tại trong bất kỳ hồ sơ nào ở đây. Hệ số đồng thuận tính trên đó không mô tả gì về hệ thống này.

- Số dòng đánh giá tìm thấy: 4
- Số dòng khớp với hồ sơ thật trong corpus: **0**
- Điều kiện để đo: ≥ 3 người chấm độc lập trên ≥ 30 hồ sơ thật, chấm trực tiếp trên giao diện ESG Evidence View và không trao đổi trước với nhau
- Bộ máy tính α / AC2 (`evalu_iaa_engine.py`) đã sẵn sàng; cái còn thiếu là dữ liệu chấm thật, không phải code.

---
*Sinh tự động bởi `evalu/run_evaluation.py`. Ràng buộc được kiểm bởi `test/test_evalu_metrics.py`.*