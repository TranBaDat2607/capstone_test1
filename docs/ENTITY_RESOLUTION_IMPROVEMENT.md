# Báo cáo Cải tiến thuật toán Entity Resolution sử dụng Thông tin Cấu trúc Đồ thị (Bước 4)

Tài liệu này trình bày chi tiết về giải pháp cải tiến thuật toán Phân giải Thực thể (Entity Resolution) tại Bước 4 (`step04_build_issuer_registry.py`) trong hệ thống phát hiện greenwashing bằng Graph-RAG. 

---

## 1. Đặt vấn đề và Hạn chế của Thuật toán cũ

Trong quy trình xây dựng Temporal ESG Knowledge Graph, **Bước 4 (Issuer Registry Bootstrap)** đóng vai trò tiền đề để xác định các biến thể tên gọi của doanh nghiệp báo cáo (Issuer) nhằm phục vụ việc gộp nút (entity merging) ở Bước 5. 

### Hạn chế của thuật toán cũ:
Thuật toán cũ dựa trên **Lexical Similarity (độ tương đồng từ vựng)** để đưa ra quyết định:
*   Nếu tên biến thể chứa đầy đủ các từ cốt lõi (core tokens) của doanh nghiệp (ví dụ: `{"an", "phat", "xanh"}` đối với Nhựa An Phát Xanh) và không chứa các từ phân biệt (qualifiers như `holdings`, `affiliate`): Hệ thống tự động xếp làm **Alias**.
*   Nếu tên biến thể có sự tương đồng trung gian (ví dụ: chia sẻ $\ge 2$ core tokens như `{"an", "phat"}`): Hệ thống không thể tự đưa ra quyết định và bắt buộc phải đưa vào danh sách **Needs Review** để con người duyệt thủ công.

### Hậu quả:
*   Các thực thể viết tắt hoặc các tên gọi khác biệt lớn về mặt từ vựng (ví dụ: `Nhựa An Phát` hoặc các dạng tiếng Anh viết tắt) nhưng thực chất là cùng một công ty sẽ bị đẩy vào hàng đợi duyệt thủ công, làm tăng gánh nặng công việc (human-in-the-loop).
*   Các thực thể là công ty con hoặc công ty mẹ có độ tương đồng từ vựng rất cao (ví dụ: `An Phát Complex` hoặc `An Phát Holdings`) cũng bị đẩy vào hàng đợi duyệt mặc dù chúng là các pháp nhân hoàn toàn độc lập cần loại trừ.

---

## 2. Giải pháp Cải tiến: Tích hợp Graph Structural Information

Giải pháp đề xuất tích hợp **Graph Structural Information (thông tin cấu trúc đồ thị)** để tự động hóa việc đưa ra quyết định đối với các trường hợp từ vựng mơ hồ (ambiguous cases). Ý tưởng cốt lõi là: **Các thực thể giống nhau sẽ có hành vi/quan hệ lân cận trong đồ thị giống nhau.**

### 2.1 Xây dựng Chữ ký Đồ thị (Graph Signature)
Với mỗi nút Organization $O$ trong danh sách các bộ ba đồ thị thô ($triples$), chữ ký đồ thị $Signature(O)$ được định nghĩa là tập hợp các cặp:
$$Signature(O) = \{ (Relation\_Direction, Neighbor\_Identifier) \}$$
Trong đó:
*   Nếu $O$ là chủ thể ($subject$) của quan hệ $P$ hướng tới đối tượng $X$: thêm $(P, Identifier(X))$ vào chữ ký.
*   Nếu $O$ là đối tượng ($object$) của quan hệ $P$ bắt nguồn từ chủ thể $Y$: thêm $(\text{"<-"} + P, Identifier(Y))$ vào chữ ký (để phân biệt chiều của quan hệ).
*   $Identifier(Node)$ là chuỗi thuộc tính định danh đặc trưng nhất của nút lân cận (quét theo thứ tự ưu tiên: `name` $\rightarrow$ `kpi_type` $\rightarrow$ `title` $\rightarrow$ các khóa định danh khác).

### 2.2 Độ đo tương đồng Weighted Jaccard Similarity
Không phải tất cả các quan hệ trong đồ thị đều mang giá trị nhận diện như nhau. Ví dụ, một quan hệ bị phạt tiền (`subjectToPenalty`) hay đạt chứng nhận (`holdsCertification`) mang tính đặc trưng nhận diện pháp nhân cao hơn nhiều so với việc chỉ xuất bản một báo cáo thường niên (`publishesReport`).

Do đó, chúng tôi áp dụng **Weighted Jaccard Similarity**:
$$Similarity(A, B) = \frac{\sum_{x \in A \cap B} w(x)}{\sum_{y \in A \cup B} w(y)}$$

Trong đó, trọng số của từng quan hệ $w(x)$ được định nghĩa thông qua bảng cấu hình trọng số hệ thống (`RELATION_WEIGHTS`):
*   **Trọng số rất cao (3.0)**: `subjectToPenalty` (Phạt hành chính/môi trường - dấu hiệu nhận diện cực mạnh).
*   **Trọng số cao (2.5)**: `holdsCertification` (Chứng nhận chất lượng/môi trường).
*   **Trọng số trung bình (2.0)**: `reportsKPI` (Báo cáo chỉ số KPI), `claims` (Tuyên bố phát triển bền vững), `setsGoal` (Đặt mục tiêu).
*   **Trọng số thấp (1.0)**: `publishesReport` (Xuất bản báo cáo), `locatedIn` (Vị trí địa lý).

### 2.3 Cơ chế Issuer Anchor an toàn chống lan truyền lỗi
Để tránh hiện tượng lan truyền lỗi phân loại sai từ bước từ vựng vào chữ ký Issuer, chữ ký đại diện của Issuer ($issuer\_signature$) được xây dựng bằng cách gộp chữ ký của tên chính thức ($official\_name$) và **chỉ** các biến thể có độ tin cậy tuyệt đối (khớp chính xác với $ticker$ normalized hoặc tên chính thức normalized). 

Các biến thể có độ tương đồng từ vựng thấp hoặc trung bình sẽ không được phép đóng góp vào chữ ký của Issuer.

---

## 3. Logic Quyết định Phân loại Mới

Đối với mỗi thực thể Organization $O$ trong đồ thị:
1.  **Nếu lexical similarity là High (Confident)**: Giữ nguyên hành vi cũ (Tự động đưa vào **Alias**).
2.  **Nếu lexical similarity là Ambiguous (chia sẻ $\ge 2$ core tokens)**: Tiến hành tính toán độ tương đồng đồ thị $Sim = Similarity(Signature(O), issuer\_signature)$:
    *   **$Sim > \theta_{upper}$ (mặc định 0.8)**: Tự động phân loại làm **Alias**.
    *   **$Sim < \theta_{lower}$ (mặc định 0.2)**: Tự động phân loại làm **Exclusion** (Loại trừ).
    *   **$\theta_{lower} \le Sim \le \theta_{upper}$**: Đưa vào **Needs Review** để con người xác nhận.
3.  **Các tham số ngưỡng** ($\theta_{upper}, \theta_{lower}$) được thiết lập dưới dạng siêu tham số (hyperparameters) cấu hình qua CLI dòng lệnh (`--graph-sim-upper` và `--graph-sim-lower`) để dễ dàng điều chỉnh thực nghiệm trên tập kiểm chứng (validation dataset).

---

## 4. Kết quả Thực nghiệm và Bảng so sánh (AAA Case Study)

Dưới đây là kết quả đối chiếu giữa thuật toán cũ và mới khi chạy trên tập dữ liệu đồ thị mô phỏng thực tế của Công ty Cổ phần Nhựa An Phát Xanh (mã CK: **AAA**):

| Thực thể Organization cần phân loại | Phân loại của Thuật toán Cũ | Phân loại của Thuật toán Mới | Kết quả đánh giá Weighted Jaccard | Giải thích hành vi hệ thống |
| :--- | :--- | :--- | :---: | :--- |
| **Công ty Cổ phần Nhựa An Phát Xanh** | **ALIAS** (Tự động) | **ALIAS** (Tự động) | *Anchor* | Tên chính thức của Issuer. |
| **AAA** | **ALIAS** (Tự động) | **ALIAS** (Tự động) | *Anchor* | Tên ticker viết tắt (độ tin cậy tuyệt đối). |
| **Công ty CP Nhựa An Phát Xanh** | **ALIAS** (Tự động) | **ALIAS** (Tự động) | *confident* | Khớp hoàn toàn core tokens (`an`, `phat`, `xanh`). |
| **Nhựa An Phát** | <span style="color:orange">**NEEDS REVIEW**</span> | <span style="color:green">**ALIAS** (Tự động)</span> | **0.818** | Shares `reportsKPI` & `holdsCertification` với Issuer $\rightarrow$ Tự động gộp. |
| **An Phát Holdings** | **EXCLUDE** (Tự động) | **EXCLUDE** (Tự động) | **0.000** | Bị loại trừ sớm nhờ exclusion seed. |
| **Công ty An Phát Complex** | <span style="color:orange">**NEEDS REVIEW**</span> | <span style="color:red">**EXCLUDE** (Tự động)</span> | **0.000** | Không chia sẻ quan hệ ESG nào với Issuer $\rightarrow$ Tự động loại trừ. |

---

## 5. Đánh giá kỹ thuật và Đóng gói hệ thống

1.  **Hiệu năng thực thi**: Việc tính toán chữ ký đồ thị được tối ưu hóa thông qua cơ chế cache toàn cục một lần duy nhất. Độ phức tạp thời gian đạt mức tuyến tính $O(N)$ với $N$ là tổng số lượng quan hệ lân cận trong đồ thị, đảm bảo hệ thống có khả năng mở rộng tốt khi xử lý đồ thị quy mô lớn.
2.  **Đóng gói độc lập**: Mọi thay đổi logic thuật toán đều nằm trọn vẹn bên trong tệp `step04_build_issuer_registry.py`. Định dạng đầu ra của registry hoàn toàn không đổi, bảo toàn **100% tính tương thích ngược** với Bước 5 (`step05_resolve_entities.py`) và toàn bộ pipeline Graph-RAG phía sau.
