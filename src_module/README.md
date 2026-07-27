# src_module/ — module-architecture refactor target

Đích đến của đợt refactor từ `src/`. Code cũ trong `src/` **vẫn là pipeline đang
chạy thật**; ta chuyển **từng stage một** sang đây, không big-bang.

- **Sơ đồ pipeline (bắt đầu từ đây nếu thấy rối): [`PIPELINE.md`](PIPELINE.md)**
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

Hỏi trước khi phân loại: *stage sau có thật đang dọn hậu quả không?* Nếu nó đang làm
**một việc khác về bản chất** (vd `step03c`: tra từ điển tất định, tách khỏi lời gọi
LLM bất định của `step01`) thì không cần ngoại lệ nào, và ép nó ngược lên stage sớm là
làm hỏng thiết kế — DESIGN.md §5.2.1.

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
python test/test_esg_kg_anchor_kpi.py     # lát cắt step03b: core/identity + graph/anchor_kpi
python test/test_esg_kg_provenance.py     # lát cắt step05b: resolve/provenance
python test/test_temporal_invariants.py   # bộ test sẵn có của src/, phải luôn xanh
```

⚠️ **Bẫy khi viết arm cho một stage vá tại chỗ**: artifact trên đĩa **đã bị chính stage
đó vá rồi**. Hỏi đúng một câu — *gặp lại phần nó tự sinh, stage bỏ qua hay tính lại?*
`05c`/`03b` **bỏ qua** ⇒ chạy lại là no-op và arm so hai kết quả rỗng mà vẫn in PASS, phải
dựng lại input trước-khi-vá (`strip_axis`, `strip_anchors`). `05b` **tính lại** ⇒ arm trên
file sống đã thật; strip (`strip_provenance`) ở đó dùng để chứng minh stage không đọc
output của chính nó. Cả ba trường hợp đều strip **đúng phần stage tự sinh**, không strip
theo nhãn cạnh hay tên key. Chi tiết + bảng ba ca: [`PIPELINE.md`](PIPELINE.md) §3.

## Trạng thái

| Phần | Trạng thái |
|---|---|
| `core/paths.py` | ✅ `REPO_ROOT` neo bằng marker + hằng gốc + `load_env()` |
| `core/schema.py` | ✅ `load_schema_sets`, `validate_triple`, `get_identity_keys` |
| `core/naming.py` | ✅ `normalize_name`, `name_tokens`, `merge_preserving_edits` |
| `core/dates.py` | ✅ `ISO_DATE_RE`, `normalize_date_string`, `date_start_key` |
| `core/console.py` | ✅ `ensure_utf8_stdout` — gọi ở **đầu `main()`**, không phải `__main__` (DESIGN.md §6.2) |
| `core/graph_patch.py` | ✅ `GraphPatch`, `temporal_md` — gỡ khỏi `step05c` để `step05d` import từ kernel, không từ một stage |
| `core/identity.py` | ✅ `parse_source_id`, `get_stable_entity_id`, `PROVENANCE_CLASSES` — gỡ khỏi `step03b`/`step02` (cùng lý do trên); mở khoá `step05b` |
| `core/` còn lại | ⏳ `llm` (**chặn 4 stage**: `03`, `05`, `07`, `05d` — rồi kéo theo `08`/`10`) → `io_jsonl` (chặn `01`/`02`) → `text`. Bản đồ đầy đủ: [`PIPELINE.md`](PIPELINE.md) §2.1 |
| `report/quality.py` | ✅ stage đầu tiên được dời (từ `step00`), chạy được |
| `kpi/canonicalize.py` | ✅ dời từ `step03c`; arm so **5 214 KPIObservation thật** giữa hai cây |
| `resolve/indicators.py` | ✅ dời từ `step05c`; diff 15+/115− **0 dòng logic mới**; arm dựng lại 67 chỉ số + 1 346 cạnh trên đồ thị thật đã strip |
| `graph/anchor_kpi.py` | ✅ dời từ `step03b` (2026-07-27); diff 17+/20− **0 dòng logic**; arm dựng lại 95 anchor trên corpus đã strip + nhánh hub-guard + idempotency. Test riêng: `test/test_esg_kg_anchor_kpi.py` |
| `resolve/provenance.py` | ✅ dời từ `step05b` (2026-07-27); diff 18+/8− **0 dòng logic** — stage đầu tiên dời mà **không phải trích thêm `core/`** nào; arm so 6 258 dấu trên đồ thị thật + arm strip chứng minh stage không đọc output của chính nó + fixture nhánh `extraction`. Test riêng: `test/test_esg_kg_provenance.py` |
| `registry/standards.py` | ⛔ **không dời** — `step04b` đọc output của `step05` (vòng lặp) và lần quét đồ thị đóng góp 0; registry thành config tĩnh, `step00` audit độ phủ (DESIGN.md §4.2) |
| Stage kế tiếp | 🟢 còn **ba** stage đủ điều kiện: `step04`, `step06`, `step09` — nhưng `06`/`09` đọc Neo4j nên arm tương đương yếu hẳn, còn `04` thuộc lô hub làm cuối. Ứng viên có lưới an toàn mạnh nhất (`step05b`) đã dời xong, nên bước đáng làm tiếp là **`core/llm.py`** (mở khoá 4 stage) — PIPELINE.md §2.1 |
| `step07b` (softmax) | ⛔ **không dời** — UI `frontend/`+`api/` không đọc; giữ chạy ở `src/` (DESIGN.md §4.1) |

`src/` **vẫn là pipeline chạy thật**; mới ba stage chạy được từ đây, và bản
`src/step00_graph_quality_report.py` vẫn còn (nợ đã ghi: DESIGN.md §6.1).
