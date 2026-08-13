# Báo cáo Đánh giá Hệ thống Graph-RAG (không nhãn)

*Sinh tự động lúc 2026-08-08T04:24:57+00:00 — `python evalu/run_evaluation.py`*

> Hệ thống là **Decision-Support System**, không phải bộ phân loại greenwashing. Không tồn tại nhãn chuẩn, nên mọi con số dưới đây là **chỉ số nội bộ (intrinsic)** đo tính nhất quán của pipeline — KHÔNG phải accuracy so với sự thật.

## 0. Phạm vi dữ liệu đo

| Hạng mục | Giá trị |
|---|---|
| Từ vựng ESG neo được (M1.1) | 417 cụm từ |
| Số câu đã quét (báo cáo) | KHÔNG ĐO ĐƯỢC |
| Số câu đã quét (tin tức) | 174,256 |
| Đồ thị đã phân giải | 10,634 node / 14,744 cạnh |
| Bộ ba đã kiểm định | 14,500 |
| Hồ sơ đối soát | 464 claim / 5 mã CK |
| Mã chứng khoán | AAA, ACC, ACG, ADP, AGG |
| Thời gian chạy | 16.8s |

## 1. Tổng hợp chỉ số nội bộ theo module (§2)

| Mã | Chỉ số | Giá trị | Tử/Mẫu | Trạng thái |
|---|---|---:|---:|:--:|
| M1.1r | ESG Signal-to-Noise Ratio — báo cáo | — | — | info |
| M1.2r | Paragraph Source Provenance Rate — báo cáo | — | — | info |
| M1.1n | ESG Signal-to-Noise Ratio — tin tức | 62.14% | 47,990 / 77,229 | info |
| M1.2n | Paragraph Source Provenance Rate — tin tức | 100.00% | 174,256 / 174,256 | PASS |
| M2.1 | Temporal Metadata Completeness | 93.02% | 21,620 / 23,243 | FAIL |
| M2.2 | Schema Compliance Rate | 100.00% | 14,744 / 14,744 | PASS |
| M2.3 | Value Preservation Guard | 100.00% | 500 / 500 | PASS |
| M3.1 | Timeless Identity Violation Rate | 0.00% | 0 / 14 | PASS |
| M3.2 | Oversimplification & Cluster Conciseness | 0.47% | 10 / 2,135 | info |
| M4.1 | Standard Indicator Alignment Coverage | 50.53% | 718 / 1,421 | info |
| M4.2 | Zero-Report Self-Praise Exclusion | 100.00% | 1 / 1 | PASS |
| M5.1 | Evidence Asymmetry & Abstention Rate | 96.55% | 448 / 464 | info |
| M5.2 | Self-Verification Exclusion Rate | 0.00% | 0 / 19 | info |
| NC.1 | Same-Company Evidence Rate | 100.00% | 24 / 24 | PASS |
| NC.2 | Same-Feed Specificity vs Chance | 100.00% | 24 / 24 | PASS |

## 2. Chi tiết từng module

### 1. Thu thập & Phân loại ESG

**M1.1r — ESG Signal-to-Noise Ratio — báo cáo**  
Giá trị: **—** · Mục tiêu: cao hơn = ít câu tiếp thị chung chung lọt qua bộ phân loại

*Chỉ số này dùng để làm gì:* Bộ phân loại ViDeBERTa gán esg=true theo ngữ nghĩa câu, nên văn tiếp thị rỗng ('hướng tới phát triển bền vững', 'tầm nhìn trở thành doanh nghiệp hàng đầu') vẫn lọt qua. Chỉ số này đo phần câu đã lọt qua mà còn neo được vào một cụm từ trong từ vựng KPI/GRI có kiểm soát — tức phần thực sự dùng được cho các khâu sau.

*Cách đọc:* Thấp = nhiều câu vào pipeline nhưng không mang nội dung ESG đo được, làm loãng đầu vào của khâu trích xuất KPI. Không có ngưỡng chuẩn; dùng để so sánh giữa các lần chạy hoặc giữa hai nguồn (báo cáo vs tin tức).

*Hạn chế:* KHÔNG phải độ chính xác của bộ phân loại. Giá trị phụ thuộc mạnh vào cách dựng từ vựng: đổi cách dựng làm con số nhảy từ 4% lên 50%. Đây là chỉ số yếu nhất trong bộ, không nên trích dẫn như một kết quả độc lập.


**M1.2r — Paragraph Source Provenance Rate — báo cáo**  
Giá trị: **—** · Mục tiêu: 100%

*Chỉ số này dùng để làm gì:* Mỗi câu phải giữ nguyên toạ độ nguồn (source_pdf, page, sentence_index) qua toàn bộ pipeline. Đây là điều kiện để mọi node trong đồ thị truy ngược được về đúng trang, đúng câu trong báo cáo gốc — nền tảng của toàn bộ tính minh bạch mà hệ thống hứa hẹn với kiểm toán viên.

*Cách đọc:* Phải đạt 100%. Dưới 100% nghĩa là có tuyên bố hiển thị trên giao diện mà không dẫn được về nguồn, tức mất khả năng kiểm chứng.

*Hạn chế:* Gần như tất yếu đạt 100% vì pipeline chỉ sao chép cơ học ba trường này. Giá trị của nó là làm lưới chắn hồi quy, không phải là bằng chứng chất lượng.


**M1.1n — ESG Signal-to-Noise Ratio — tin tức**  
Giá trị: **62.14%** (47,990/77,229) · Mục tiêu: cao hơn = ít câu tiếp thị chung chung lọt qua bộ phân loại

*Chỉ số này dùng để làm gì:* Bộ phân loại ViDeBERTa gán esg=true theo ngữ nghĩa câu, nên văn tiếp thị rỗng ('hướng tới phát triển bền vững', 'tầm nhìn trở thành doanh nghiệp hàng đầu') vẫn lọt qua. Chỉ số này đo phần câu đã lọt qua mà còn neo được vào một cụm từ trong từ vựng KPI/GRI có kiểm soát — tức phần thực sự dùng được cho các khâu sau.

*Cách đọc:* Thấp = nhiều câu vào pipeline nhưng không mang nội dung ESG đo được, làm loãng đầu vào của khâu trích xuất KPI. Không có ngưỡng chuẩn; dùng để so sánh giữa các lần chạy hoặc giữa hai nguồn (báo cáo vs tin tức).

*Hạn chế:* KHÔNG phải độ chính xác của bộ phân loại. Giá trị phụ thuộc mạnh vào cách dựng từ vựng: đổi cách dựng làm con số nhảy từ 4% lên 50%. Đây là chỉ số yếu nhất trong bộ, không nên trích dẫn như một kết quả độc lập.


**M1.2n — Paragraph Source Provenance Rate — tin tức**  
Giá trị: **100.00%** (174,256/174,256) · Mục tiêu: 100%

*Chỉ số này dùng để làm gì:* Mỗi câu phải giữ nguyên toạ độ nguồn (source_pdf, page, sentence_index) qua toàn bộ pipeline. Đây là điều kiện để mọi node trong đồ thị truy ngược được về đúng trang, đúng câu trong báo cáo gốc — nền tảng của toàn bộ tính minh bạch mà hệ thống hứa hẹn với kiểm toán viên.

*Cách đọc:* Phải đạt 100%. Dưới 100% nghĩa là có tuyên bố hiển thị trên giao diện mà không dẫn được về nguồn, tức mất khả năng kiểm chứng.

*Hạn chế:* Gần như tất yếu đạt 100% vì pipeline chỉ sao chép cơ học ba trường này. Giá trị của nó là làm lưới chắn hồi quy, không phải là bằng chứng chất lượng.


### 2. Trích xuất Triplet & KPI

**M2.1 — Temporal Metadata Completeness**  
Giá trị: **93.02%** (21,620/23,243) · Mục tiêu: 100%

*Chỉ số này dùng để làm gì:* Đo phần đồ thị thực sự tham gia được vào suy luận theo thời gian. Một cạnh không có valid_from thì không trả lời được câu hỏi cốt lõi của bài toán greenwashing: doanh nghiệp tuyên bố năm nào, hành vi xảy ra năm nào, và khoảng cách giữa hai mốc đó là bao nhiêu.

*Cách đọc:* Phần hụt cho biết CHÍNH XÁC chỗ nào mất khả năng so sánh theo thời gian — đọc `edge_gaps_by_predicate` và `node_gaps_by_class` chứ đừng chỉ đọc con số tổng.

*Hạn chế:* Mẫu số lấy theo hợp đồng schema (mọi edge spec khai temporal_properties, mọi lớp T2/T3 khai valid_from). Nếu một số lớp cố ý để thời gian sống trên cạnh thay vì trên node thì phải sửa schema, không phải sửa chỉ số.

Cạnh: 14,227/14,744 · Node T2/T3: 7,393/8,499
Cạnh thiếu thời gian, theo predicate: `alignsWithIndicator` = 413, `partOf` = 43, `worksAt` = 30, `equivalentTo` = 26, `reportsKPI` = 2, `subjectToRegulation` = 1, `investsIn` = 1, `adoptsStandard` = 1
Node thiếu `valid_from`, theo lớp: `Goal` = 511, `Initiative` = 429, `Project` = 163, `KPIObservation` = 2, `Investment` = 1
*Mẫu số lấy theo config/schema.json: mọi edge spec đều khai temporal_properties và mọi lớp T2/T3 đều khai valid_from. Phần hụt vì thế là sai lệch thật so với hợp đồng schema, không phải giả định của phép đo.*

**M2.2 — Schema Compliance Rate**  
Giá trị: **100.00%** (14,744/14,744) · Mục tiêu: 100% (0 vi phạm)

*Chỉ số này dùng để làm gì:* Xác nhận mọi cạnh trong đồ thị là một bộ ba (predicate, lớp nguồn, lớp đích) hợp lệ theo config/schema.json. Cạnh sai kiểu sẽ làm hỏng mọi truy vấn Cypher viết theo schema, và làm khâu đối soát bỏ sót hoặc lấy nhầm bằng chứng.

*Cách đọc:* Phải là 100%. Bất kỳ vi phạm nào cũng là lỗi cần sửa ngay.

*Hạn chế:* GẦN NHƯ TẤT YẾU đạt 100%: fix_triples cưỡng chế schema và đẩy cái không sửa được sang unfixable_triples.json. Đo độ tuân thủ trên đầu ra của chính bộ validator thì không nói lên chất lượng. Con số đáng báo cáo kèm là TỶ LỆ BỊ LOẠI (số bộ ba trong unfixable_triples.json), hiện chưa được đưa vào báo cáo này.


**M2.3 — Value Preservation Guard**  
Giá trị: **100.00%** (500/500) · Mục tiêu: 100% (LLM không được sửa giá trị/đơn vị)

*Chỉ số này dùng để làm gì:* Khâu sửa lỗi ở step03 dùng LLM để chữa HÌNH DẠNG của bộ ba (sai lớp, sai chiều cạnh, sai định dạng ngày). Nó tuyệt đối không được đụng vào GIÁ TRỊ ĐO. Một mô hình được nhắc bằng tiếng Anh rất dễ 'sửa' 'tấn' thành 'tons' hoặc làm tròn một con số — và sai lệch đó sẽ đi thẳng vào hồ sơ đối soát mà không ai thấy. Chỉ số này so sánh từng trường giá trị trước và sau khi sửa.

*Cách đọc:* Bất kỳ giá trị nào dưới 100% đều là lỗi nghiêm trọng: hệ thống đang báo cáo con số mà doanh nghiệp không hề công bố. Đọc kèm `guarded_fields_seen` để biết có bao nhiêu trường thực sự được đối chiếu — 100% trên mẫu số rỗng thì vô nghĩa.

*Hạn chế:* Chỉ so được các node ghép được stable_id ở cả hai phía; số node lệch được báo riêng ở `match_stats` thay vì bỏ qua âm thầm.

Số trường được canh giữ thực tế: 992 (trên các trường `value`, `unit`, `amount`, `quantity`, `target_value`) — mẫu số chỉ tính node thực sự mang giá trị đo, nên 100% ở đây không phải kết quả rỗng
Ghép node trước/sau sửa: 937 khớp · 9 chỉ có trước · 9,525 chỉ có sau
*Mẫu số chỉ gồm node ghép được cả hai phía — 275 file trang / 6 tài liệu có mặt trên đĩa. Đọc kèm dòng 'Ghép node trước/sau sửa' bên trên: `chỉ có sau` lớn nghĩa là phía trang chưa được pull đủ, không phải node bị mất.*

### 3. Phân giải Thực thể

**M3.1 — Timeless Identity Violation Rate**  
Giá trị: **0.00%** (0/14) · Mục tiêu: 0 vi phạm

*Chỉ số này dùng để làm gì:* Nguyên tắc P1: danh tính của thực thể T1 (Doanh nghiệp, Nhà máy, Người...) phải VĨNH CỬU. Nếu identity_keys chứa trường thời gian, cùng một công ty sẽ bị tách thành nhiều thực thể khác nhau theo từng năm — lịch sử vỡ vụn, và mọi so sánh nhiều năm trở nên vô nghĩa.

*Cách đọc:* Phải bằng 0. Một vi phạm cũng đủ làm hỏng phân giải thực thể.

*Hạn chế:* Đây là lint trên một file config viết tay, tức một unit test chứ không phải phép đánh giá hệ thống. Giá trị 0 là kỳ vọng mặc định, không phải thành tích. test/test_schema_contract.py đã kiểm điều này.


**M3.2 — Oversimplification & Cluster Conciseness**  
Giá trị: **0.47%** (10/2,135) · Mục tiêu: thấp hơn = ít thực thể trùng còn sót sau hợp nhất

*Chỉ số này dùng để làm gì:* Sau khi phân giải thực thể (Stage A/B/C/D), cùng một doanh nghiệp không được còn tồn tại dưới nhiều node. Thực thể bị vỡ làm loãng bằng chứng: tuyên bố treo vào node này, tin tức treo vào node kia, và khâu đối soát không bao giờ nối được hai bên.

*Cách đọc:* Càng thấp càng tốt. Đọc `clusters` để thấy chính xác cặp nào chưa gộp.

*Hạn chế:* QUAN TRỌNG — con số này là CẬN DƯỚI và dễ gây yên tâm sai. Nó dùng chính normalize_name mà bộ phân giải dùng, nên chỉ thấy được thứ resolver lẽ ra gộp được bằng khoá của chính nó. Nó MÙ với thất bại thật: 'Công ty CP Nhựa An Phát' vs 'An Phát Holdings' sẽ không bị phát hiện. Mức trùng lặp thật gần như chắc chắn cao hơn nhiều.

Cụm trùng lớn nhất: `Location`×3, `Location`×2, `Location`×2, `Location`×2, `Location`×2

### 4. Ánh xạ Trục Chỉ tiêu

**M4.1 — Standard Indicator Alignment Coverage**  
Giá trị: **50.53%** (718/1,421) · Mục tiêu: cao hơn = độ phủ TT96/GRI tốt hơn

*Chỉ số này dùng để làm gì:* Chỉ những tuyên bố có cạnh alignsWithIndicator mới hiển thị được trên giao diện ESG Evidence View, vì cột trụ cột E/S/G đọc trực tiếp từ StandardIndicator.pillar. Chỉ số này đo phần tuyên bố thực sự vào được trục chỉ tiêu TT96/GRI — phần còn lại vô hình với người dùng cuối.

*Cách đọc:* Thấp = nhiều tuyên bố nằm ngoài tầm nhìn của giao diện. Đọc `by_class` để biết hụt ở Claim, Goal hay Initiative.

*Hạn chế:* CHỈ CÓ ĐỘ PHỦ, KHÔNG CÓ ĐỘ CHÍNH XÁC. Một bộ khớp ngu hơn, gán bừa chỉ tiêu cho mọi tuyên bố, sẽ đạt 100%. Vì vậy 'cao hơn' KHÔNG đương nhiên là 'tốt hơn'. Muốn dùng được con số này thì phải kiểm tay một mẫu ~50 cạnh để có vế precision đi kèm.

Theo lớp: `Goal` 248/511, `Initiative` 171/429, `SustainabilityClaim` 299/481

**M4.2 — Zero-Report Self-Praise Exclusion**  
Giá trị: **100.00%** (1/1) · Mục tiêu: 100%

*Chỉ số này dùng để làm gì:* Trong báo cáo thường niên, câu 'Số lần bị xử phạt vi phạm: 0' là doanh nghiệp TỰ KHAI, không phải bằng chứng độc lập. Nếu hệ thống biến nó thành cạnh conduct trên trục chỉ tiêu, nó sẽ tự động khuếch đại lời tự khen thành 'đã được xác minh' — đúng kiểu sai lầm mà một công cụ chống greenwashing tuyệt đối không được mắc.

*Cách đọc:* Phải 100%. Mỗi Penalty amount=0 phải được gắn cờ self_reported_zero VÀ không có cạnh measuredUnder/alignsWithIndicator.

*Hạn chế:* Cỡ mẫu cực nhỏ (thường chỉ 1-2 node trong toàn đồ thị). Đây là phép kiểm hồi quy, không phải một thống kê.


### 5. Đối soát Chéo

**M5.1 — Evidence Asymmetry & Abstention Rate**  
Giá trị: **96.55%** (448/464) · Mục tiêu: mô tả độ mỏng của kho bằng chứng — không phải chỉ tiêu cần tối ưu

*Chỉ số này dùng để làm gì:* Đo phần tuyên bố mà hệ thống TỪ CHỐI kết luận vì không đủ bằng chứng độc lập. Trong một hệ hỗ trợ ra quyết định, biết im lặng đúng lúc là một tính năng: thà không nói còn hơn quy kết sai cho một doanh nghiệp có thật, nêu đích danh.

*Cách đọc:* Đây là thuộc tính của DỮ LIỆU, không phải của thuật toán. Cao nghĩa là kho tin tức độc lập quá mỏng. Cách sửa là crawl thêm tin, KHÔNG PHẢI nới lỏng ngưỡng phán quyết — nới ngưỡng chỉ đổi im lặng trung thực lấy tiếng ồn.

*Hạn chế:* Đừng bao giờ trình bày như chỉ tiêu cần giảm. Một hệ thống dễ dãi hơn sẽ có abstention thấp hơn mà chất lượng tệ hơn.

Phân bố kết luận: `unverified_insufficient_evidence` = 448, `appears_supported` = 13, `appears_contradicted` = 3

**M5.2 — Self-Verification Exclusion Rate**  
Giá trị: **0.00%** (0/19) · Mục tiêu: bằng chứng xác nhận phải đến từ nguồn độc lập

*Chỉ số này dùng để làm gì:* Doanh nghiệp không được tự xác nhận mình. Nếu 'bằng chứng độc lập' cho tuyên bố của AAA lại đến từ aaa.com.vn thì đó vẫn là báo cáo tự công bố, chỉ đổi định dạng. Chỉ số này đo phần bằng chứng bị guard loại vì đến từ domain của chính doanh nghiệp.

*Cách đọc:* Giá trị 0 có HAI cách hiểu trái ngược nhau: (a) không có bằng chứng tự công bố nào lọt vào — tốt; hoặc (b) guard là code chết, chưa từng chạy. Phải kiểm bằng cách khác mới phân biệt được.

*Hạn chế:* Trên dữ liệu hiện tại guard chưa kích hoạt lần nào, nên chỉ số này KHÔNG chứng minh được là guard hoạt động. Nó chỉ ghi nhận rằng chưa có tình huống nào cần đến nó.


### Negative control — quy thuộc bằng chứng

**NC.1 — Same-Company Evidence Rate**  
Giá trị: **100.00%** (24/24) · Mục tiêu: 100% (bằng chứng phải nói về chính doanh nghiệp bị xét)

*Chỉ số này dùng để làm gì:* Đây là phép kiểm CÓ THỂ LÀM HỆ THỐNG TRƯỢT — khác với toàn bộ nhóm M1-M5, vốn chỉ đối chiếu hệ thống với thiết kế của chính nó. Nó hỏi một câu duy nhất: khi hệ thống trích một bản tin làm bằng chứng cho tuyên bố của doanh nghiệp T, bản tin đó có thật sự nói về T không? Nếu không, mọi kết luận phía sau đều vô giá trị, bất kể LLM lập luận hay đến đâu.

*Cách đọc:* Đọc `cross_feed_unmentioned` trước tiên: đó là số bằng chứng vừa đến từ feed công ty khác, vừa không hề nhắc tên doanh nghiệp đang xét trong phần text mà LLM thực sự nhìn thấy. Đặc biệt chú ý dòng `contradicting_evidence` trong `by_kind` — mâu thuẫn là đầu ra chính của hệ thống, nên một mâu thuẫn chéo công ty là một cáo buộc greenwashing sai gán cho một doanh nghiệp có thật, nêu đích danh.

*Hạn chế:* Quy thuộc dựa trên tiền tố ticker trong source_doc, tức 'bài này được crawl dưới feed của ai'. Một bài trong feed công ty khác mà có nhắc tên doanh nghiệp đang xét thì VẪN hợp lệ — hai trường hợp được tách riêng, không gộp làm một.

*cross_feed_unmentioned là con số quyết định: bài đến từ feed công ty khác VÀ không hề nhắc tên doanh nghiệp đang xét trong phần text mà LLM thực sự nhìn thấy.*

### Negative control — độ đặc hiệu theo công ty

**NC.2 — Same-Feed Specificity vs Chance**  
Giá trị: **100.00%** (24/24) · Mục tiêu: lift >> 1 (nếu ~1 thì truy hồi không mang tín hiệu công ty nào)

*Chỉ số này dùng để làm gì:* Biến NC.1 thành một phép kiểm giả thuyết có đối chứng. Giả thuyết không: bằng chứng được rút NGẪU NHIÊN từ kho conduct toàn cục, không phụ thuộc doanh nghiệp. Dưới giả thuyết đó, tỷ lệ bằng chứng của công ty T đến từ feed của T đúng bằng tỷ trọng feed đó trong kho. So sánh quan sát với kỳ vọng cho biết truy hồi có mang tín hiệu công ty hay chỉ đang khớp chủ đề.

*Cách đọc:* lift = quan sát / kỳ vọng.  lift ≈ 1 nghĩa là KHÔNG bác bỏ được giả thuyết không: truy hồi không phân biệt được với bốc ngẫu nhiên, và không kết luận nào phía sau được phép đọc như 'đặc thù cho doanh nghiệp này'. lift ≥ 2 mới coi là có tín hiệu thật. lift < 1 là tệ hơn cả ngẫu nhiên.

*Hạn chế:* Kho conduct hiện rất nhỏ (44 node / 5 mã), nên lift theo từng mã có phương sai lớn — đọc con số tổng, và đọc `by_ticker` như dấu hiệu định tính chứ đừng như ước lượng điểm.


## 3. Tầng đánh giá chuyên gia (§3) và độ đồng thuận (§4)

**Chưa thu thập phiếu chấm nào.** Bộ công cụ đã sẵn sàng: `evalu/rubric.py` chứa rubric 4 khía cạnh × thang Likert 5 điểm, 3 nhóm hội đồng, bộ sinh phiếu trống và pipeline đồng thuận (Gwet AC2 / Krippendorff α, ngưỡng 0.61).

Sinh phiếu trống:

```bash
python evalu/run_evaluation.py --make-sheet --rater-id ceo01 --panel ceo --n-claims 30
```

Hệ số chính: **gwet_ac2** — Phân bố nhãn lệch mạnh về unverified_insufficient_evidence khiến chance-agreement của Kappa tiệm cận 1 và hệ số sụp về 0 (prevalence paradox). Gwet neo chance theo prevalence nên bền vững.

## 4. Giới hạn cần nêu khi trích dẫn báo cáo này

- Không có ground truth ⇒ không có precision/recall/F1 về greenwashing.
- Chỉ số nội bộ đo **tính nhất quán và độ phủ**, không đo **tính đúng**.
- Tỷ lệ abstention cao phản ánh kho tin tức độc lập còn mỏng, không phải lỗi thuật toán.
- M1.1 (SNR) đo mức độ *neo được vào từ vựng KPI/GRI*, không phải độ chính xác của bộ phân loại ESG.
