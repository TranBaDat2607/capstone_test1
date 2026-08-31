# Báo cáo đánh giá hệ thống Graph-RAG phát hiện greenwashing

*Tạo lúc 2026-08-07T07:50:46+00:00 · khung tham chiếu: evalu.pdf §1-§3 (metric table + Likert rubric)*

> **Nguyên tắc của báo cáo này:** mọi con số đều đọc từ artifact trên đĩa. Metric không đo được thì ghi thẳng là **KHÔNG ĐO ĐƯỢC** kèm lý do và chi phí để đo — không có giá trị mặc định, không có số benchmark thay thế.

## 0. Phạm vi dữ liệu được đánh giá

| Artifact | Giá trị |
|---|---|
| Đồ thị đã resolve | 10,634 node · 14,744 cạnh |
| Sửa đổi lần cuối | `2026-08-07T01:07:46+00:00` |
| Hồ sơ claim (dossier) | 36 |
| Doanh nghiệp trong corpus | AAA (1 tổ chức duy nhất) |
| Tài liệu đã trích xuất thành đồ thị | **137** = 46 báo cáo thường niên + 91 bài báo |
| Năm của các báo cáo | 2011, 2012, 2013, 2013, 20130422-ACC-BCTN 2012 -1, 20130422-ACC-BCTN 2012 -2, 2014, 2014, 2014, 2015, 2016, 2016, 2016, 2017, 2017, 2018, 2018, 2018, 2019, 2019, 2020, 2020, 2021, 2021, 2021, 2021, 2022, 2022, 2022, 2022, 2023, 2023, 2023, 2024, 2024, 2024, 2024, 2025, 2025, 2025, 20250620 - AAA - Bao cao thuong nien 2024 - Ban thiet ke, 2026, 2026, 2026, v2, v2 |
| Câu `esg=true` của pilot AAA | 83,156 |
| Tỷ trọng node đến từ tin tức | **5.3%** (561/10,634) |
| Corpus quét ngành — đã phân loại, **CHƯA** vào đồ thị | 303,723 câu `esg=true` (1.216 tài liệu) |
| Snapshot dữ liệu | `nammovuivui-capstone/capstone` @ `23d5a8901ceb` (đẩy 2026-08-01T15:38:01+00:00) |

> **Toàn bộ báo cáo này mô tả MỘT doanh nghiệp** — AAA. Mọi con số bên dưới là của pilot đó, không phải của toàn ngành. Corpus quét ngành 1.216 tài liệu đã được phân loại ESG nhưng chưa từng chạy qua bước trích xuất đồ thị, nên không đóng góp node nào và không nằm trong bất kỳ mẫu số nào ngoài dòng SNR được ghi rõ là "quét ngành".

---
## 1. Tầng 1 — 11 chỉ số kiểm soát pipeline (evalu.pdf §1–§5)


### Giai đoạn 1 — Thu thập & phân loại ESG

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| ESG Signal-to-Noise Ratio (SNR) | **0.1141** (11.4%) | 9,490 / 83,156 | `data/labeled/{annual_labeled,news_labeled}/*.jsonl` |
| Paragraph Source Provenance Rate | — | 0 / 0 | `esg_kg.report.quality.q6_provenance + provenance_patch_stats.json` |

- *ESG Signal-to-Noise Ratio (SNR)*: Tín hiệu = câu esg=true có con số KÈM ĐƠN VỊ, hoặc có thuật ngữ thuộc bộ từ vựng kiểm soát (TT96/GRI). Nhiễu = văn cam kết chung chung không kèm phép đo nào. Phạm vi là 53 tài liệu của pilot AAA (13 báo cáo thường niên + 40 bài báo); corpus quét ngành báo cáo riêng.

- *Paragraph Source Provenance Rate*: Tỷ lệ node mang dấu vết nguồn mà step05b truy ngược được về đúng tài liệu + số trang.

### Giai đoạn 2 — Trích xuất triplet & KPI

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Temporal Metadata Completeness (C_temporal) | **0.9650** (96.5%) | 14,228 / 14,744 | `esg_kg.report.quality.q5_timeliness` |
| Schema Compliance Rate (C_schema) | **1.0000** (100.0%) | 14,744 / 14,744 | `esg_kg.report.quality.q2_consistency` |
| Value Preservation Guard | **KHÔNG ĐO ĐƯỢC** | — | `src/esg_kg/graph/fix_triples.py::preserve_property_values` |

- *Temporal Metadata Completeness (C_temporal)*: Số cạnh mang temporal_metadata.valid_from. Trong đồ thị ĐÃ RESOLVE, thời gian sống trên cạnh và node T2 (P2), nên thực thể T1 đúng ra phải phi thời gian và không nằm trong mẫu số.

- *Schema Compliance Rate (C_schema)*: Số cạnh có bộ ba (lớp chủ thể, vị từ, lớp đối tượng) hợp lệ theo schema.

> **Value Preservation Guard — KHÔNG ĐO ĐƯỢC.** Bộ đếm số giá trị bị chặn chỉ được ghi ra log, không bao giờ lưu vào file stats. Muốn có tỷ lệ thì phải chạy lại bước sửa lỗi LLM step03 phase 2 (có tính phí). Đã kiểm chứng như một bất biến, không phải như một tỷ lệ.

### Giai đoạn 3 — Hợp nhất thực thể

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Timeless Identity Violation Rate (V_identity) | **0.0000** (0.0%) | 0 / 14 | `esg_kg.report.quality.q2_consistency (schema-level P1 lint)` |
| Cluster Conciseness (C_concise) | **0.9953** (99.5%) | 2,122 / 2,132 | `esg_kg.report.quality.q3_conciseness` |

- *Timeless Identity Violation Rate (V_identity)*: Số lớp thực thể T1 có trường thời gian nằm trong identity_keys. Mục tiêu là 0 — định danh T1 bắt buộc phi thời gian (P1).

- *Cluster Conciseness (C_concise)*: CHỈ đo vỡ cụm (under-merging): các node T1 trùng tên sau chuẩn hoá qua Stage A/B/C/D. Gộp nhầm (over-merging) cần nhãn nên KHÔNG đo ở đây.

### Giai đoạn 4 — Trục chỉ tiêu TT96/GRI

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Standard Indicator Alignment Coverage | **0.5053** (50.5%) | 718 / 1,421 | `graph_output/resolved/resolved_graph.json` |
| Zero-Report Self-Praise Exclusion | **1.0000** (100.0%) | 1 / 1 | `graph_output/resolved/resolved_graph.json + indicator_axis_stats.json` |

- *Standard Indicator Alignment Coverage*: Số node Claim/Goal/Initiative có cạnh alignsWithIndicator. Trục KPI (measuredUnder) báo cáo riêng — nó lấy từ kpi_id của bước canonicalize, không phải từ khớp cụm từ.

- *Zero-Report Self-Praise Exclusion*: BẤT BIẾN, không phải tỷ lệ — toàn đồ thị chỉ có 4 node Penalty với amount = 0. Báo cáo dưới dạng đếm.

### Giai đoạn 5 — Đối soát chéo claim ↔ conduct

| Chỉ số | Điểm | Tử/Mẫu | Nguồn dữ liệu |
|---|---|---|---|
| Evidence Asymmetry & Abstention Rate | **0.7778** (77.8%) | 28 / 36 | `graph_output/crosscheck/aaa_claim_assessments.json` |
| Self-Verification Exclusion Rate | **0.0000** (0.0%) | 0 / 6 | `graph_output/crosscheck/aaa_claim_assessments.json` |

- *Evidence Asymmetry & Abstention Rate*: Từ chối kết luận là hành vi được thiết kế khi thiếu bằng chứng độc lập. Chỉ số này đo độ mỏng của kho dữ liệu, không đo chất lượng model.

- *Self-Verification Exclusion Rate*: Tỷ lệ phán quyết 'supports' của LLM bị từ chối cấp cạnh verifiedBy vì domain của bằng chứng thuộc về chính doanh nghiệp.

#### Chi tiết SNR — chỉ số nhạy với định nghĩa "có căn cứ"

| Định nghĩa | SNR |
|---|---|
| Chặt: có số **kèm đơn vị đo** hoặc thuật ngữ TT96/GRI | **0.1141** (9,490/83,156) |
| Lỏng: có **bất kỳ chữ số nào** (cận trên) | 0.3559 (29,597/83,156) |
| Corpus quét ngành (đã phân loại, **chưa** vào đồ thị) | 0.0959 (29,133/303,723) |

Kho thuật ngữ dùng để đối chiếu: 322 mục (35 KPI TT96/QĐ2171/QCVN09/SSC-IFC + 136 mã GRI).

#### Chi tiết độ phủ trục chỉ tiêu

| Lớp node | Đã gắn chỉ tiêu | Tổng | Tỷ lệ |
|---|---|---|---|
| Goal | 248 | 511 | 48.5% |
| Initiative | 171 | 429 | 39.9% |
| SustainabilityClaim | 299 | 481 | 62.2% |
| KPIObservation (`measuredUnder`) | 1,309 | 6,560 | 20.0% |

Phân bố phương pháp gắn: `{'keyword': 807}`

---
## 2. Độ đúng trích xuất — round-trip grounding (A)

### **0.9686** (96.9%) — 4,414/4,557 giá trị KPI có mặt đúng trên trang mà chính node đó trích dẫn

> **Đây là chỉ số ĐỘ ĐÚNG thật, không phải proxy.** Văn bản gốc chính là ground truth cho câu hỏi "con số này có trong tài liệu không?", nên không cần ai gán nhãn. Nó lấp đúng lỗ hổng mà `quality.py` tự ghi nhận ở `q1_accuracy`: *"manual 30–50 node sample audit is out of scope"* — ở đây là 4,557 node, tự động.

- **143 giá trị KHÔNG tìm thấy** trên trang được trích dẫn → đây là danh sách cần soi tay.
- Không so được (đã loại khỏi mẫu số, không tính là đạt): `{'no_value': 1467, 'value_too_short_to_verify': 536}`
- Tổng node KPIObservation: 6,560

| Tài liệu nhiều sai lệch nhất | Khớp | Lệch |
|---|---|---|
| AAA_2016 | 281 | **85** |
| AAA_2017 | 462 | **8** |
| AAA_2023 | 116 | **8** |
| AAA_2022 | 157 | **6** |
| AAA_Baocaothuongnien_2024 | 149 | **6** |

Ví dụ giá trị không tìm thấy trên trang trích dẫn:

- `Tỷ lệ lao động nữ trong Ban Điều hành` = **60.0** % → trích dẫn 20250620 - AAA - Bao cao thuong nien 2024 - Ban thiet ke p.45
- `Tỷ lệ lao động nữ trong Hội đồng Quản trị` = **60.0** % → trích dẫn 20250620 - AAA - Bao cao thuong nien 2024 - Ban thiet ke p.45
- `Tuân thủ các yêu cầu của hệ thống kiểm soát và quản trị nội bộ` = **100.0** % → trích dẫn AAA_2013 p.29
- `Tỷ lệ phần trăm (%) lao động có trình độ từ cao đẳng trở lên` = **50.0** % → trích dẫn AAA_2014 p.17
- `Lãi suất cho vay sản xuất kinh doanh thông thường` = **11.0** %/năm → trích dẫn AAA_2016 p.14

> ⚠ Khớp chỉ chứng minh con số CÓ MẶT trên trang. Nó không chứng minh con số được gán đúng chỉ tiêu, đúng kỳ hay đúng đơn vị. Vì vậy đây là CẬN TRÊN của độ đúng trích xuất.

---
## 3. Tầng 3 — đánh giá không cần nhãn ở tầng đối soát

*(theo `docs/proposals/EVALUATION_WITHOUT_LABELS.md`; toàn bộ offline, 0 đồng)*

### B2 — Kiểm định hoán vị trên số claim bị mâu thuẫn

- Quan sát thực tế: **2** claim `appears_contradicted` từ 2 mẩu bằng chứng mâu thuẫn.
- Phân phối null (1000 lần hoán vị, seed `20260806`): trung bình 1.97, khoảng [1, 2].
- **p = 1.0** (đuôi dưới).

> Đuôi DƯỚI mới là đuôi có ý nghĩa — xem docstring. p là tỷ lệ các lần rải ngẫu nhiên mà dồn mâu thuẫn vào ít claim đúng bằng mức hệ thống đã làm.

### B2b — Cặp (claim, bằng chứng) được giữ có mạch lạc hơn ghép ngẫu nhiên không?

| Thống kê | Quan sát | Null (ngẫu nhiên) | p |
|---|---|---|---|
| Chồng lấp từ vựng (Jaccard) | **0.1325** | 0.0584 | **0.001** |
| Khoảng cách năm trung bình | 6.125 năm | 6.125 năm | 1.0 |

> ⚠ Có phần luẩn quẩn: tầng retrieval vốn đã chọn theo chồng lấp từ vựng và cửa sổ năm. Vì vậy chỉ kết luận được rằng 'tập được giữ tách xa hơn nữa so với việc ghép lại ngẫu nhiên trong cùng bể đó'.

> **Kết quả âm cần ghi nhận:** bằng chứng được giữ **không** gần claim về mặt thời gian hơn mức ngẫu nhiên (p = 1.0). Chiều thời gian hiện không đóng góp gì cho việc ghép cặp — chỉ có chiều từ vựng.

### D — Bằng chứng đi SAU claim (kiểm nguyên tắc P8)

| Vai trò bằng chứng | Vi phạm | So sánh được | Tỷ lệ |
|---|---|---|---|
| `contradicts` (vi phạm P8 trực tiếp) | **2** | 2 | **100.0%** |
| `supports` (nhẹ hơn, xem ghi chú) | 6 | 6 | 100.0% |

- Khoảng cách lớn nhất: **+15 năm**.
- Phân bố (năm bằng chứng − năm claim): `{'3': 2, '4': 2, '5': 1, '7': 1, '8': 1, '15': 1}`

Các mâu thuẫn lệch thời gian nặng nhất:

- **+15 năm** — claim 2015 bị bác bỏ bằng bằng chứng 2030: "Sản phẩm bao bì tự hủy thân thiện với môi trường"
- **+8 năm** — claim 2017 bị bác bỏ bằng bằng chứng 2025: "trao tặng số tiền 30.000.000 đồng để ủng hộ đồng bào miền Trung thiệt hại do cơn bão số 10."

> Với một MÂU THUẪN, bằng chứng có năm sau claim là vi phạm P8 trực tiếp. Với một SUPPORT thì nhẹ hơn — bài báo 2016 có thể tường thuật hợp lệ một sự kiện 2015 — nên hai tỷ lệ được tách riêng và không được cộng gộp.

> ⚠ 100% evidence mang date_uncertain=true, tức năm thường là ngày đăng bài dùng làm proxy. Vì vậy đây là CẬN TRÊN của tỷ lệ vi phạm, không phải con số chính xác.

> **Vì sao kết luận này vững:** ba đường độc lập cùng chỉ về một chỗ — (1) B2b cho thấy khoảng cách năm của cặp được giữ không tốt hơn ghép ngẫu nhiên, (2) D cho thấy phần lớn mâu thuẫn dùng bằng chứng đi sau, (3) tham số `window_after` đang để 50 năm. `docs/proposals/EVALUATION_WITHOUT_LABELS.md` §3.3 đã **dự báo trước** MR-4 sẽ hỏng nặng; D xác nhận dự báo đó mà không tốn một lệnh gọi LLM nào.

### E — Ablation cửa sổ thời gian truy hồi

| `window_after` | supports | contradicts | Tổng bằng chứng | Claim còn bằng chứng |
|---|---|---|---|---|
| 0 năm | 0 | 0 | 0 | 0 |
| 1 năm | 0 | 0 | 0 | 0 |
| 2 năm | 0 | 0 | 0 | 0 |
| 3 năm | 2 | 0 | 2 | 2 |
| 5 năm | 5 | 0 | 5 | 5 |
| 10 năm | 6 | 1 | 7 | 7 |
| 50 năm ← **hiện tại** | 6 | 2 | 8 | 8 |

> Cửa sổ hiện tại cho phép bằng chứng đi sau claim tới 50 năm. Bảng này cho biết siết lại thì còn giữ được bao nhiêu bằng chứng.

> ⚠ Chỉ phát lại được những mẩu bằng chứng ĐÃ được giữ, nên đây là cận trên: nó không cho biết cửa sổ hẹp hơn sẽ đẩy thêm cặp mới nào vào top-k.

### Tính nhất quán trên claim trùng lặp

- **1.0000** — 2/2 nhóm claim trùng lặp cho cùng một kết luận.
- Khoảng tin cậy Wilson 95%: `[0.3424, 1.0]` (mẫu nhỏ — đọc theo khoảng, không đọc theo tỷ lệ trần).

### Hiệu suất tầng truy hồi (thay cho "Context Precision@k")

- **0.0278** — giữ lại 8/288 cặp ứng viên.
- Phân rã: `{'supporting_evidence': 6, 'contradicting_evidence': 2}`
- 8/36 claim có ít nhất một mẩu bằng chứng.

> ⚠ "Liên quan" ở đây chính là phán quyết của adjudicator, nên đây là lấy chính model đã phán xử để chấm điểm tầng truy hồi. Mang tính chẩn đoán, không phải kiểm định độc lập.

### Bất đồng nội bộ giữa điểm offline và phán quyết LLM

- **0.0000** — 0/36 hồ sơ.

### Phổ `confidence` của LLM (ghi nhận, không phải điểm số)

- Phân bố: `{'0.8': 4, '0.9': 4}` → chỉ **2** giá trị phân biệt, thấp nhất 0.8.
- Quá ít giá trị phân biệt để hiệu chuẩn — ghi nhận như một phát hiện, không phải một metric. Calibration đã chết ở đây (docs/proposals/EVALUATION_WITHOUT_LABELS.md §8).

---
## 3. Những gì KHÔNG ĐO ĐƯỢC — và cần gì để đo

| Chỉ số | Vì sao chưa đo được | Chi phí để đo |
|---|---|---|
| RAGAS Context Recall | Cần tập ground-truth về những bằng chứng LẼ RA phải được truy hồi. Không có nhãn nào tồn tại — đó chính là tiền đề của đề tài. Đã ghi nhận là metric chết trong docs/proposals/EVALUATION_WITHOUT_LABELS.md §8. | gán nhãn thủ công tập bằng chứng vét cạn cho từng claim |
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