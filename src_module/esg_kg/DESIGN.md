# esg_kg — thiết kế module cho `src/`

Bản thiết kế bố cục package để refactor 19 file `src/step*.py` (+ `data_sync.py`)
sang kiến trúc module, làm **tăng dần từng stage một**. Mọi ánh xạ dưới đây dựa
trên đồ thị import thật của `src/` (không đoán).

## 1. Vấn đề cốt lõi phải xử lý TRƯỚC

Các file `step*.py` đang **kiêm hai vai**: vừa là một stage pipeline, vừa là thư
viện tiện ích cho các stage sau. Đồ thị import thật:

| File cũ | Symbol dùng chung bị "nhốt" bên trong | Số nơi import |
|---|---|---|
| `step01_extract_kpi` | `REPO_ROOT`, `build_page_text`, `load_pages_from_jsonl` | **~11** |
| `step03_fix_invalid_triplets` | `load_schema_sets`, `validate_triple`, `date_start_key` | 7 |
| `step04_build_issuer_registry` | `normalize_name`, `name_tokens`, `merge_preserving_edits` | 6 |
| `step02_extract_triplet` | `RateLimiter`, `get_identity_keys`, `PROVENANCE_CLASSES`, `stamp_provenance` | 4 |
| `step03b`, `step05c`, `step07` | `parse_source_id`; `GraphPatch`/`temporal_md`; `node_text`/`_OpenAIProvider` | 1–2 |

Hệ quả: không thể chuyển `step05` sang module mới mà không kéo theo step01–04, vì
nó import trực tiếp từ các file anh em. **`core/` gỡ đúng nút thắt này** — sau khi
tách, mỗi stage chỉ phụ thuộc `esg_kg.core` và di chuyển được độc lập.

Phát hiện thêm: `node_text` **định nghĩa trùng** ở `step05d:63` và `step07:133` →
gom về `core/text.py`, xoá bản trùng.

## 2. Bố cục đề xuất

```
src_module/esg_kg/
  core/                # KERNEL dùng chung — tách ra TRƯỚC TIÊN
    paths.py           #  REPO_ROOT, DEFAULT_* dirs            <- step01:36-44
    io_jsonl.py        #  load_pages_from_jsonl, build_page_text, page_has_esg  <- step01:97-124
    schema.py          #  load_schema_sets, validate_triple    <- step03:150,260
                       #  get_identity_keys                    <- step02:100
    naming.py          #  normalize_name, name_tokens, merge_preserving_edits  <- step04:138,158,399
    dates.py           #  date_start_key (+ canonicalize ISO)  <- step03:130
    identity.py        #  parse_source_id                      <- step03b:98
                       #  PROVENANCE_CLASSES, stable_id        <- step02
    text.py            #  node_text  (DEDUPE 2 bản)            <- step05d:63 + step07:133
    llm.py             #  RateLimiter                          <- step02:70
                       #  _Provider/_OpenAIProvider cascade    <- step07:284
    datasync.py        #  HF snapshot pull/push                <- src/data_sync.py

  kpi/                 extract.py(step01)  canonicalize.py(step03c)
  graph/               extract_triples.py(step02)  fix_triples.py(step03)  anchor_kpi.py(step03b)
  registry/            issuer.py(step04)  standards.py(step04b)
  resolve/             entities.py(step05)  provenance.py(step05b)  indicators.py(step05c)  align_claims.py(step05d)
  load/                neo4j_load.py(step06)  neo4j_sync.py(step08)
  crosscheck/          claims_vs_conduct.py(step07)  enrich_dossiers.py(step07b)
  report/              quality.py(step00)  claim_ledger.py(step09)  evaluate.py(step10)

  pipeline.py          # thứ tự chạy (thay cho tiền tố stepNN_)
```

Nguyên tắc nhóm: theo **vai trò trong pipeline**, không theo số thứ tự. Số thứ tự
chạy chuyển vào `pipeline.py::STAGES` (giữ nguyên tri thức của tiền tố `stepNN_`).

Vài lựa chọn tên có chủ đích:
- `load/` **không** đặt tên `neo4j/`: repo đã có thư mục `neo4j/` (file .cypher) và
  tên `neo4j` còn che khuất import driver `neo4j`.
- `report/` gom cả `step00` (quality) dù nó chạy ĐẦU tiên — nhóm theo vai trò
  (phân tích offline, read-only), không theo vị trí chạy.

## 3. Cách chạy sau refactor (quyết định phải chốt SỚM)

Hiện `src/` chạy kiểu standalone, dựa vào việc Python tự đặt thư mục script lên
`sys.path` rồi `from step0X import ...`. Sang package thì import thành
`from esg_kg.core.schema import load_schema_sets`, và stage chạy bằng
`python -m esg_kg.kpi.extract` (từ trong `src_module/`) — **không** chạy trực tiếp
file nữa. Cần chốt trước khi chuyển file đầu tiên:

- Chạy `python -m esg_kg.<pkg>.<mod>` từ `src_module/`, hoặc thêm `pyproject.toml`
  với `console_scripts` để có lệnh gọn.
- `REPO_ROOT` hiện là `parents[1]` của file. Trong bố cục mới file nằm sâu hơn
  (`esg_kg/kpi/extract.py`), nên `core/paths.py` phải tính lại độ sâu — hoặc
  neo `REPO_ROOT` bằng biến môi trường / marker file (khuyến nghị: tìm ngược lên
  tới thư mục chứa `config/` + `.git`). Đây là bẫy dễ sai nhất khi di chuyển.

## 4. Thứ tự refactor đề xuất (giảm rủi ro cho kiểu "từng bước một")

1. **`core/paths.py` trước tiên** — chuyển đúng `REPO_ROOT` (nhỏ, cơ học, được
   import nhiều nhất). Sửa các nơi import `REPO_ROOT` trỏ về `esg_kg.core.paths`,
   chạy `python test/test_temporal_invariants.py` → xanh là đã chứng minh khung
   package + cách xử lý path hoạt động ("walking skeleton").
2. **Phần còn lại của `core/`** — schema, naming, dates, identity, io_jsonl, llm,
   text. Sau bước này coupling step→step bị cắt.
3. **Các stage LÁ** (không ai import): step00, step03c, step04b, step05, step05b,
   step05d, step06, step07b, step08, step09, step10, data_sync — chuyển an toàn,
   không làm gãy downstream.
4. **Các stage HUB cuối cùng**: step04 → step03 → step02 → step01 — lúc này phần
   dùng chung đã ở `core/`, phần còn lại chỉ là entrypoint mỏng.

## 5. Lưới an toàn & mắt xích yếu

- `test/test_temporal_invariants.py` import theo **cùng kiểu bare-module**
  (`from step03_... import ...`). Nó là lưới hồi quy DUY NHẤT — cập nhật import
  của nó **đồng bộ** với mỗi lần chuyển, và chạy lại sau mỗi bước.
- **Mắt xích yếu nhất**: `REPO_ROOT` đổi độ sâu thư mục (§3) + cơ chế `sys.path`.
  Sai ở đây làm mọi đường dẫn `data/`, `config/`, `graph_output/` trỏ sai mà
  không báo lỗi ngay. Xử lý dứt điểm ở bước 1 trước khi đi tiếp.
