# src_module/ — module-architecture refactor target

Thư mục **rỗng về logic** để đón code refactor từ `src/`. Code cũ trong `src/`
vẫn chạy nguyên vẹn; ta chỉ **chuyển từng stage một** sang đây.

- Package thật: [`esg_kg/`](esg_kg/) — tên gợi ý, đổi thoải mái trước khi bắt đầu.
- Bản thiết kế + bảng ánh xạ file cũ → module mới: [`esg_kg/DESIGN.md`](esg_kg/DESIGN.md).
- Thứ tự chạy (thay cho tiền tố `stepNN_`): [`esg_kg/pipeline.py`](esg_kg/pipeline.py).

Trạng thái hiện tại: mới có khung package (các `__init__.py` + doc). Chưa
chuyển dòng code nghiệp vụ nào. Xem DESIGN.md §"Thứ tự refactor đề xuất".
