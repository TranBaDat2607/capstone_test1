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
python test/test_esg_kg_llm.py            # lát cắt core/llm: throttle + hình dạng request đã trả tiền
python test/test_esg_kg_fix_triples.py    # lát cắt step03: corpus thật + pha 2 bằng LLM giả
python test/test_esg_kg_validated_block.py # KHỐI 03→03b→03c: src/ làm oracle + "ghi đúng 1 lần"
python test/test_esg_kg_align_claims.py    # lát cắt step05d: nhánh LLM bắt buộc, chạy bằng provider giả
python test/test_esg_kg_crosscheck.py      # lát cắt step07: đòn bẩy lớn nhất, mở khoá 08+10
python test/test_pipeline_table.py        # bảng STAGES/BLOCKS + run.py --list nói thật
python test/test_temporal_invariants.py   # bộ test sẵn có của src/, phải luôn xanh
```

⚠️ **Bẫy khi viết arm cho một stage vá tại chỗ**: artifact trên đĩa **đã bị chính stage
đó vá rồi**. Hỏi đúng một câu — *gặp lại phần nó tự sinh, stage bỏ qua hay tính lại?*
`05c`/`03b` **bỏ qua** ⇒ chạy lại là no-op và arm so hai kết quả rỗng mà vẫn in PASS, phải
dựng lại input trước-khi-vá (`strip_axis`, `strip_anchors`). `05b` **tính lại** ⇒ arm trên
file sống đã thật; strip (`strip_provenance`) ở đó dùng để chứng minh stage không đọc
output của chính nó. `05d` là ca thứ tư và là ca mới: nó **bỏ qua**, nhưng artifact sống
**chưa chứa tàn dư của nó** (stage chưa từng chạy) ⇒ arm không rỗng **do dữ liệu**, không do
thiết kế — nên `strip_llm_alignments()` vẫn được viết và gọi dù hôm nay xoá 0 cạnh. Mọi
trường hợp đều strip **đúng phần stage tự sinh**, không strip theo nhãn cạnh hay tên key
(`05d` chỉ lấy `alignment_method=llm`, giữ nguyên 639 cạnh `keyword` của `05c`). Chi tiết +
bảng bốn ca: [`PIPELINE.md`](PIPELINE.md) §3.

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
| `core/llm.py` | ✅ `DEFAULT_RATE_LIMIT`, `RateLimiter` (<- `step02`) + `_Provider`, `_OpenAIProvider` (<- `step07`) — verbatim, 0 dòng logic đổi; **mở khoá 4 stage** (`03`, `05`, `07`, `05d`). `Adjudicator` cố ý ở lại `step07` — nay đã dời, và chính điều đó mở khoá `08`/`10`. Test: `test/test_esg_kg_llm.py` |
| `core/` còn lại | ⏳ `io_jsonl` (chặn `02`; **không** chặn `01`, mà rơi ra từ lát cắt `01`) → `text`. **Không còn module `core/` nào chặn stage nào khác.** Bản đồ đầy đủ: [`PIPELINE.md`](PIPELINE.md) §2.1 |
| `report/quality.py` | ✅ stage đầu tiên được dời (từ `step00`), chạy được |
| `kpi/canonicalize.py` | ✅ dời từ `step03c`; arm so **5 214 KPIObservation thật** giữa hai cây |
| `resolve/indicators.py` | ✅ dời từ `step05c`; diff 15+/115− **0 dòng logic mới**; arm dựng lại 67 chỉ số + 1 346 cạnh trên đồ thị thật đã strip |
| `graph/anchor_kpi.py` | ✅ dời từ `step03b` (2026-07-27); diff 17+/20− **0 dòng logic**; arm dựng lại 95 anchor trên corpus đã strip + nhánh hub-guard + idempotency. Test riêng: `test/test_esg_kg_anchor_kpi.py` |
| `resolve/provenance.py` | ✅ dời từ `step05b` (2026-07-27); diff 18+/8− **0 dòng logic** — stage đầu tiên dời mà **không phải trích thêm `core/`** nào; arm so 6 258 dấu trên đồ thị thật + arm strip chứng minh stage không đọc output của chính nó + fixture nhánh `extraction`. Test riêng: `test/test_esg_kg_provenance.py` |
| `graph/fix_triples.py` | ✅ dời từ `step03` (2026-07-28); stage **thứ hai** dời mà không phải trích thêm `core/`. Nó *trông* như hub (7 stage import) nhưng mọi symbol chúng lấy đã ở `core/dates`+`core/schema` ⇒ thực chất là leaf — **"hub" phải kiểm bằng CHIỀU import**. Arm corpus thật (14 492 validated + 1 036 unfixable) không cần `strip_*` vì stage không bao giờ gặp output của chính nó; pha 2 (trả tiền) có arm bằng LLM giả. Test riêng: `test/test_esg_kg_fix_triples.py` |
| `graph/build_validated.py` | ✅ **KHỐI** `03 → 03b → 03c` (2026-07-28) — không phải stage, **không có bản `src/`** nên không tính vào mẫu số. Nối chuỗi in-memory, ghi `all_validated_triples.json` **1 lần**; `src/` giữ nguyên 3 stage và làm **oracle**. Pha 2 cache theo *nội dung* triple ⇒ chạy lại **0 lời gọi LLM**. Test riêng: `test/test_esg_kg_validated_block.py` (DESIGN.md §5.7) |
| `resolve/align_claims.py` | ✅ dời từ `step05d` (2026-07-28); stage thứ **ba** dời mà không phải trích thêm `core/` — lát cắt `05c` đã đẩy `GraphPatch`/`temporal_md` lên kernel *chính vì* file này import chúng từ một stage. Stage **bắt buộc có LLM** — `--dry-run` return trước khi provider được dựng, nên nhánh đắt được phủ bằng **provider giả tiêm vào cả hai cây** (tất định theo CRC của prompt). Test riêng: `test/test_esg_kg_align_claims.py` (14 nhóm) |
| `crosscheck/claims_vs_conduct.py` | ✅ dời từ `step07` (2026-07-28), stage thứ **tám** — đòn bẩy lớn nhất trước khi dời: stage DUY NHẤT còn chặn ai đó (`08` chờ `node_text`, `10` chờ `Adjudicator`). `_Provider`/`_OpenAIProvider` nay import NGƯỢC từ `core.llm` — đúng hai lớp mà slice đó đã trích TỪ CHÍNH file này ngày 2026-07-27; `Adjudicator` cố ý ở lại stage (prompt + parse verdict + cascade — logic, không phải kernel). Khác `05d`, `--dry-run` ở đây KHÔNG return trước khi dựng provider (chỉ bỏ ghi file cuối) nên arm dry-run cũng là kiểm tương đương thật. Không đọc lại output của chính nó (ghi khác thư mục) nên PIPELINE.md §3 không áp dụng. Test riêng: `test/test_esg_kg_crosscheck.py` (21 nhóm) |
| `registry/standards.py` | ⛔ **không dời** — `step04b` đọc output của `step05` (vòng lặp) và lần quét đồ thị đóng góp 0; registry thành config tĩnh, `step00` audit độ phủ (DESIGN.md §4.2) |
| Stage kế tiếp | 🟢 `03`, `05d`, `07` đã dời (2026-07-28), còn **năm** stage đủ điều kiện: `01`, `04`, `05`, `06`, `09` — cộng **`08`**/**`10`**, hai stage `07` vừa mở khoá (chờ `node_text`/`Adjudicator` từ chính stage đó, không còn chờ kernel). `step04` là leaf (3 symbol đã ở `core/naming`, nhưng ghi một file **tracked + sửa tay**, arm phải dùng workspace tạm). `step05` **chưa được dời** cho tới khi xử §3.1 — nay mặc định là gộp khối theo §3.2. PIPELINE.md §2.1 |
| `step07b` (softmax) | ⛔ **không dời** — UI `frontend/`+`api/` không đọc; giữ chạy ở `src/` (DESIGN.md §4.1) |

`src/` **vẫn là pipeline chạy thật**; mới **tám** stage chạy được từ đây (`00`, `03`, `03b`,
`03c`, `05b`, `05c`, `05d`, `07`) **cộng một khối** `build_validated` — `run.py --list` là nguồn sự thật —
và bản `src/step00_graph_quality_report.py` vẫn còn (nợ đã ghi: DESIGN.md §6.1).
