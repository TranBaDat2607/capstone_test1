# src_module/ — module-architecture refactor target

Đích đến của đợt refactor từ `src/`. Code cũ trong `src/` **vẫn là pipeline đang
chạy thật**; ta chuyển **từng stage một** sang đây, không big-bang.

- Package thật: [`esg_kg/`](esg_kg/)
- Bản thiết kế + bảng ánh xạ file cũ → module mới: [`esg_kg/DESIGN.md`](esg_kg/DESIGN.md)
- Thứ tự chạy (thay cho tiền tố `stepNN_`): [`esg_kg/pipeline.py`](esg_kg/pipeline.py)

## Hai việc song song, KHÔNG được trộn vào nhau

Đợt này làm cùng lúc hai mục tiêu, và chúng có luật ngược nhau — trộn vào một
commit là mất luôn lưới an toàn:

| | Mục tiêu | Hành vi chương trình | Test tương đương |
|---|---|---|---|
| **Refactor** | dời code sang kiến trúc module | **không đổi** (trích nguyên văn) | phải XANH |
| **Sửa lỗi** | sửa khiếm khuyết thật | **đổi có chủ đích** | vẫn XANH, vì sửa **cả hai cây** cùng commit |

Chi tiết quy trình: DESIGN.md §5.3.

## Nguyên tắc sửa lỗi: vá ở stage sớm nhất

Không để module phía sau đi dọn hậu quả của module phía trước. Stage sau chỉ được
xử lý bù khi thuộc một trong ba ngoại lệ có tên — **E1** (backfill dữ liệu đã đóng
băng, bản sửa thật đã ở stage sớm), **E2** (stage sớm về cấu trúc không thể biết),
**E3** (stage sớm cố ý giữ bất định thay vì đoán bừa) — và phải ghi rõ ngoại lệ nào
trong docstring của stage. Bảng phân loại hiện trạng `src/` + trường hợp vi phạm đã
tìm thấy: DESIGN.md §5.1–5.2.

## Cách làm việc

Test-first, luôn luôn (xem CLAUDE.md → "Working rule: Test-Driven Development").
Mỗi module `core/` mới **phải có arm trong `test/test_esg_kg_equivalence.py` trước
khi được trích** — thêm arm, chạy, thấy đỏ, rồi mới viết code.

```bash
python test/test_esg_kg_equivalence.py    # lưới chống lệch giữa src/ và esg_kg
python test/test_temporal_invariants.py   # bộ test sẵn có của src/, phải luôn xanh
```

## Trạng thái

| Phần | Trạng thái |
|---|---|
| `core/paths.py` | ✅ `REPO_ROOT` neo bằng marker + hằng gốc + `load_env()` |
| `core/schema.py` | ✅ `load_schema_sets`, `validate_triple`, `get_identity_keys` |
| `core/naming.py` | ✅ `normalize_name`, `name_tokens`, `merge_preserving_edits` |
| `core/` còn lại | ⏳ `dates` → `io_jsonl` → `identity` → `text` → `llm` |
| Các stage | ⏳ chưa dời stage nào; `step00` sẽ là stage đầu tiên đủ điều kiện, ngay sau `core/dates.py` |

Chưa có stage nào chạy được từ đây — `src/` vẫn là đường chạy duy nhất.
