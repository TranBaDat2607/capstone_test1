# ESG Evidence View — Tài liệu Kiến trúc Giao diện & API

Tài liệu này mô tả chi tiết thiết kế, kiến trúc, tính năng giao diện và hướng dẫn sử dụng cho tính năng **ESG Evidence View** — giao diện xác thực tuyên bố ESG của doanh nghiệp theo cấu trúc 3 cột.

---

## 1. Tổng quan & Mục tiêu

**ESG Evidence View** cung cấp góc nhìn đối soát trực quan giữa các **tuyên bố trong Báo cáo Thường niên** của doanh nghiệp với **bằng chứng thực tế từ cơ quan độc lập**, đối chiếu theo khung chỉ tiêu **Thông tư 96/2020/TT-BTC (TT96)** và **GRI Standards**.

### 3 Cột Xác thực chính:
1. ✅ **Những điều công ty đã thực hiện đúng**: Tuyên bố của công ty được xác nhận bởi đơn vị độc lập (PwC, SGS, Bộ/Sở TN&MT...).
2. ❌ **Những điều công ty nói nhưng thực tế khác**: Tuyên bố của công ty bị phát hiện mâu thuẫn hoặc vi phạm thực tế.
3. ⚠️ **Những điều bắt buộc phải công bố nhưng bị bỏ qua**: Các chỉ tiêu TT96/GRI bắt buộc khai báo nhưng bị doanh nghiệp ẩn đi hoặc không đề cập.

---

## 2. Các Tính năng Giao diện (UI Features)

1. **Thanh Tìm kiếm Autocomplete Công ty (Top Search Bar)**:
   - Đặt trên cùng của trang với giao diện màu xanh nhạt mềm mại `#f0f4fa` chuẩn thiết kế.
   - Hỗ trợ gõ mã chứng khoán (Ticker) hoặc tên tiếng Việt (VNM, AAA, HPG, FPT, MSN...).

2. **Bộ lọc Theo Năm Báo cáo (Company Year Selector)**:
   - Đặt ngay trong dòng Header bên cạnh tên công ty (VD: `Vinamilk (VNM)`).
   - Đảm bảo tính rõ ràng: bộ lọc năm trực thuộc báo cáo của công ty đang xem, không bị hiểu nhầm với ô tìm kiếm tổng.
   - Cho phép chọn xem toàn bộ giai đoạn (`2022 - 2024`) hoặc xem riêng biệt từng năm (`2024`, `2023`, `2022`).

3. **Nút Mở rộng / Thu gọn Danh sách ("Xem thêm ˅" / "Thu gọn ˄")**:
   - Ban đầu mỗi cột hiển thị 2 thẻ (cards) để giữ bố cục gọn gàng.
   - Xuất hiện nút **"Xem thêm ˅"** màu xanh lá khi số thẻ vượt quá 2.
   - Bấm để xem toàn bộ danh sách các câu thỏa mãn cột đó và có thể thu gọn lại.

4. **Khoảng cách Thẻ Thoáng đẹp**:
   - Khoảng cách chiều dọc giữa các thẻ card được tối ưu 24px, giúp dễ đọc và theo dõi thông tin.

---

## 3. Kiến trúc Hệ thống & Cấu trúc Thư mục

Ứng dụng được thiết kế theo mô hình **Tách biệt Frontend + API (Decoupled Frontend-API)**:

```
capstone_test1/
├── api/                          # Backend API Layer
│   ├── __init__.py
│   ├── main.py                   # Pure Python HTTP Server (serve API + static UI)
│   └── evidence_service.py       # Quản lý registry công ty & mapper dữ liệu TT96/GRI với filter theo năm
│
├── frontend/                     # Presentation Layer (Vanilla Web)
│   ├── index.html                # Semantic HTML5 layout
│   ├── css/
│   │   └── style.css             # UI styling 3 cột, nút Xem thêm, Search bar
│   └── js/
        └── app.js                # Autocomplete Search, Year Filter, Dynamic Expand/Collapse
```

---

## 4. Chi tiết API Specification

### 4.1 Danh sách Công ty & Tìm kiếm
- **Endpoint**: `GET /api/companies`
- **Query Parameter**: `q` *(string, optional)* — Từ khóa tìm kiếm (Ticker hoặc Tên công ty)

### 4.2 Bằng chứng ESG Theo Công ty & Theo Năm
- **Endpoint**: `GET /api/evidence/{ticker}`
- **Query Parameter**: `year` *(string, optional)* — Năm báo cáo cụ thể (VD: `2023`, `2022`)

---

## 5. Hướng dẫn Vận hành

Từ thư mục gốc dự án:
```bash
python api/main.py
```

Truy cập: 👉 **`http://localhost:8000`**
