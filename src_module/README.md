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

## Cách chạy

```bash
python src_module/run.py --list                      # mọi stage + đã dời hay chưa
python src_module/run.py quality --label baseline    # chạy stage (từ REPO ROOT)
cd src_module && python -m esg_kg.report.quality --label baseline   # tương đương
```

`run.py` là file duy nhất chạm `sys.path`, và đọc bảng stage từ `pipeline.py` nên
`--list` luôn nói thật về tiến độ. **Không cần `pip install`.** Đường dẫn output
neo theo `REPO_ROOT` (marker-based) nên không phụ thuộc cwd. Stage chưa dời thì
`run.py` in ra đúng lệnh `src/` cần chạy. Lý do chọn cách này: DESIGN.md §3.

Bảng phân biệt **ba** trạng thái, không phải hai: `ready` (đã dời), `still src/…`
(chưa dời), và `(not ported)` — **cố ý không dời**, bị loại khỏi mẫu số vì nếu tính
vào thì tiến độ migrate vĩnh viễn không thể đạt 100%.

## Cách làm việc

Test-first, luôn luôn (xem CLAUDE.md → "Working rule: Test-Driven Development").
Mỗi module `core/` mới **phải có arm trong `test/test_esg_kg_equivalence.py` trước
khi được trích** — thêm arm, chạy, thấy đỏ, rồi mới viết code. Với một **stage**,
arm so ba thứ: hằng số module, từng hàm, và output đã render.

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
| `core/dates.py` | ✅ `ISO_DATE_RE`, `normalize_date_string`, `date_start_key` |
| `core/` còn lại | ⏳ `identity` (đang chặn `step05b`) → `io_jsonl` → `text` → `llm` |
| `report/quality.py` | ✅ stage đầu tiên được dời (từ `step00`), chạy được |
| Stage kế tiếp | ⏳ `step03c` → `step04b` (đã đủ điều kiện, DESIGN.md §4 bước 3) |
| `step07b` (softmax) | ⛔ **không dời** — UI `frontend/`+`api/` không đọc; giữ chạy ở `src/` (DESIGN.md §4.1) |

`src/` **vẫn là pipeline chạy thật**; mới đúng một stage chạy được từ đây, và bản
`src/step00_graph_quality_report.py` vẫn còn (nợ đã ghi: DESIGN.md §6.1).
