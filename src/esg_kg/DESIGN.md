# esg_kg — thiết kế module (thay cho cây phẳng `src/step*.py`)

Bản thiết kế bố cục package để refactor 19 file `src/step*.py` (+ `data_sync.py`)
sang kiến trúc module, làm **tăng dần từng stage một**. Mọi ánh xạ dưới đây dựa
trên đồ thị import thật của cây phẳng cũ (không đoán).

> **Lưu ý khi đọc (2026-07-30):** package này nằm ở `src/esg_kg/` — thư mục `src/` từng
> tên `src_module/`, đổi tên sau khi refactor khép lại. Trong tài liệu này `src/` trơ trọi
> luôn nghĩa là **cây phẳng cũ** (`stepNN_*.py`, đã xoá 2026-07-29), không phải `src/` hôm nay.

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

Phát hiện thêm: `node_text` tồn tại ở **hai** nơi — `step05d:63` và `step07:133` —
nhưng **KHÔNG phải bản trùng** (xem §2, `text.py`). Cả hai cùng về `core/text.py`,
giữ tên riêng.

✅ **Nút `step05c` đã gỡ (2026-07-27).** `GraphPatch`/`temporal_md` — dòng cuối bảng trên,
symbol mà `step05d:34` import ngược lên một stage — nay ở `core/graph_patch.py`. Đây đúng
là ca §1 mô tả: một file stage kiêm vai thư viện. Khi `step05d` được dời, nó import từ
kernel chứ không từ `esg_kg.resolve.indicators`.

## 2. Bố cục đề xuất

```
src/esg_kg/
  core/                # KERNEL dùng chung — tách ra TRƯỚC TIÊN
    paths.py           #  REPO_ROOT, DEFAULT_* dirs            <- step01:36-44
    io_jsonl.py        #  load_pages_from_jsonl, build_page_text, page_has_esg  <- step01:97-124  ✅ ĐÃ LÀM
    schema.py          #  load_schema_sets, validate_triple    <- step03:150,260
                       #  get_identity_keys                    <- step02:100
    naming.py          #  normalize_name, name_tokens, merge_preserving_edits  <- step04:138,158,399
    dates.py           #  date_start_key (+ canonicalize ISO)  <- step03:130
    identity.py        #  parse_source_id                      <- step03b:98
                       #  PROVENANCE_CLASSES, stable_id        <- step02
    text.py            #  ❌ KHÔNG LÀM (xem PIPELINE.md §2.1 "bẫy node_text"): hai
                       #  `node_text` (step05d:63 props dict, step07:133 node+class)
                       #  hoá ra KHÔNG phải bản trùng — gộp sẽ viết lại prompt LLM đã
                       #  trả tiền của một trong hai stage. Mỗi bản ở lại đúng stage
                       #  sinh ra nó (`esg_kg.resolve.align_claims.node_text` /
                       #  `esg_kg.crosscheck.claims_vs_conduct.node_text`), không lên kernel.
    llm.py             #  RateLimiter                          <- step02:70            ✅ ĐÃ LÀM
                       #  _Provider/_OpenAIProvider cascade    <- step07:284
                       #  (KHÔNG có provider Gemini — step01 tự nói chuyện với
                       #  google.genai.Client trực tiếp, xem §3 lát cắt step01)
    console.py         #  ensure_utf8_stdout  ✅ ĐÃ LÀM        <- step00 __main__ (03a1592)
    graph_patch.py     #  GraphPatch, temporal_md  ✅ ĐÃ LÀM   <- step05c:76,102,109,114
                       #  (norm + TODAY đi kèm; 05d import từ đây, không từ stage)
    datasync.py        #  HF snapshot pull/push                <- src/data_sync.py

  kpi/                 extract.py(step01)  canonicalize.py(step03c)
  graph/               extract_triples.py(step02)  fix_triples.py(step03)  anchor_kpi.py(step03b)
  registry/            issuer.py(step04)          # standards.py: KHONG dời, xem §4.2
  resolve/             entities.py(step05)  provenance.py(step05b)  indicators.py(step05c)  align_claims.py(step05d)
  load/                neo4j_load.py(step06)  neo4j_sync.py(step08)
  crosscheck/          claims_vs_conduct.py(step07)   # enrich_dossiers: KHONG dời, xem §4.1
  report/              quality.py(step00)  claim_ledger.py(step09)  # evaluate.py(step10): KHÔNG CÒN — xem §4.3

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
`python -m esg_kg.kpi.extract` — **không** chạy trực tiếp file nữa.

**✅ ĐÃ CHỐT (khi dời step00, 2026-07-25).** Hai cách, cùng một code path:

```bash
python src/run.py quality --label baseline   # từ REPO ROOT (cách chính thức)
cd src && python -m esg_kg.report.quality --label baseline   # tương đương
```

`src/run.py` là **file duy nhất** chạm `sys.path`. Ba phương án đã cân:

| Phương án | Loại vì |
|---|---|
| `pip install -e .` + `pyproject.toml` | thêm một bước build; bare clone quên cài là `ModuleNotFoundError` |
| export `PYTHONPATH=src` | theo từng shell, dễ quên, không ghi được vào tài liệu lệnh |
| **`run.py` dispatcher** ✅ | giữ quy ước "chạy từ repo root" của CLAUDE.md, không cần cài gì |

Lợi ích kèm theo: `run.py` **đọc bảng stage từ `pipeline.py`** thay vì chép lại,
nên `pipeline.py` từ tài liệu chết thành entrypoint sống, và
`python src/run.py --list` báo tiến độ migrate **trung thực** (hỏi
`importlib.util.find_spec`, không phải một danh sách tay). Stage chưa dời thì
`run.py` in ra đúng lệnh `src/` cần chạy thay vì báo lỗi cụt.

- `REPO_ROOT`: bản `src/` cũ dùng `parents[1]`. Trong bố cục mới file nằm sâu hơn
  (`esg_kg/kpi/extract.py`) nên đếm `parents[N]` sẽ sai. **Đã chốt & làm xong**
  trong `core/paths.py`: neo `REPO_ROOT` bằng marker — tổ tiên đầu tiên có **cả**
  `config/` lẫn `.git` (yêu cầu cả hai để không dính nhầm `EmeraldMind/`), kèm
  escape hatch `ESG_KG_REPO_ROOT`. Đây từng là bẫy dễ sai nhất khi di chuyển.
  **Đã kiểm thực tế**: chạy cả hai cách trên với hai cwd khác nhau đều đọc đúng
  `graph_output/resolved/resolved_graph.json` của repo và ghi đúng `--out-dir`.

## 4. Chiến lược migrate: Model A (KHÔNG đụng `src/` đang chạy)

**Quan trọng — cái bẫy đã né:** code `src/` cũ chạy nhờ Python tự đặt thư mục
`src/` lên `sys.path` rồi `from step0X import ...`. Package `esg_kg` nằm dưới
`src/`, **không** trên path đó — nên KHÔNG thể sửa file trong `src/` để
`from esg_kg... import` (sẽ `ImportError`) trừ khi cài editable (`pip install -e`).
Vì vậy ta **không rewire `src/`**. Thay vào đó:

- **Xây `core/` như code mới**, trích nguyên văn (verbatim) từ `src/`.
- **Kiểm mỗi module `core` bằng test TƯƠNG ĐƯƠNG** với bản `src/` gốc: import cả
  hai, chạy trên cùng input thật, assert kết quả bằng nhau. (Đây là "walking
  skeleton test", KHÔNG phải rewire `src/`.)
- Helper tồn tại **song song** ở cả hai cây trong lúc migrate — trùng lặp tạm
  thời, chấp nhận được, đổi lấy pipeline cũ **không gãy**.
- Một stage chỉ đổi `import` sang `esg_kg.core` **khi chính nó được dời** sang
  `esg_kg/` (§ thứ tự bên dưới).

### Thứ tự thực hiện (giảm rủi ro cho kiểu "từng bước một")

1. ✅ **`core/paths.py`** — `REPO_ROOT` marker-based + hằng gốc + `load_env()`.
   *Đã xong, verify: `REPO_ROOT` neo đúng repo thật dù ở sâu 3 cấp.*
2. ⏳ **Phần còn lại của `core/`** (theo số importer):
   - ✅ `core/schema.py` — `load_schema_sets`, `validate_triple`, `get_identity_keys`.
   - ✅ `core/naming.py` — `normalize_name`, `name_tokens`, `merge_preserving_edits` (6 file).
     `issuer_core_tokens`/`GENERIC_TOKENS` **ở lại** step04 (không ai khác import).
   - Cả hai verify bằng `test/test_esg_kg_equivalence.py` (§6), chạy trên schema
     thật + 5000 triple thật + 242 tên Organization thật.
   - ✅ `core/dates.py` — `ISO_DATE_RE`, `normalize_date_string`, `date_start_key`
     (+ bảng riêng `_DATE_PATTERNS`). `enforce_temporal_invariants` (step03:378)
     **ở lại** step03 (chỉ test import). Xếp trước `io_jsonl` **không** vì số
     importer mà vì nó **mở khoá `step00`** (xem bước 3); `io_jsonl` chỉ step02
     dùng, mà step02 là hub cuối ở bước 4 — làm sớm không mở khoá được gì.
   - ✅ `core/graph_patch.py` — `GraphPatch`, `temporal_md` (+ `norm`, `TODAY` đi kèm),
     trích khi dời `step05c` (2026-07-27). Không xếp theo số importer mà theo stage cần:
     nó là điều kiện của `step05c`, và là thứ `step05d` sẽ import thay cho việc gọi ngược
     lên một stage.
   - ✅ `core/identity.py` — `parse_source_id` (<- step03b:98), `get_stable_entity_id` +
     `PROVENANCE_CLASSES` (<- step02:104, :501), trích khi dời `step03b` (2026-07-27).
     Cả ba đi cùng nhau vì `step05b:49-51` import cả ba một lượt. Cũng như `graph_patch`:
     xếp theo stage cần, không theo số importer. **Điều này mở khoá `step05b`.**
   - ✅ `core/llm.py` — `RateLimiter` (<- step02:70), `_Provider`/`_OpenAIProvider`
     (<- step07:284), trích 2026-07-27. **Đòn bẩy lớn nhất**: nó chặn `step03`, `step05`,
     `step07`, `step05d` cùng lúc (rồi kéo theo `step08`, và từng kéo theo `step10` cho tới
     khi stage đó bị xoá hẳn khỏi dự án — §4.3) — bản đồ đầy đủ ở
     `PIPELINE.md` §2.1. KHÔNG có provider Gemini: dự án đứng sau `GEMINI_API_KEY` bị 403
     vĩnh viễn, nên `step07` chỉ còn cascade OpenAI, và `step01` (dùng Gemini trực tiếp)
     không hề đụng module này.
   - ✅ `core/io_jsonl.py` — `load_pages_from_jsonl`, `build_page_text`, `page_has_esg`,
     `select_documents`, `parse_company_year_from_filename` (<- step01), trích khi dời
     `step01` (2026-07-28). Đúng 5 symbol mà `step02:43-50` import — module này là điều
     kiện của `step02`, không phải của `step01` (nó rơi ra từ chính lát cắt đó).
   - ❌ `core/text.py` — KHÔNG LÀM. Kế hoạch ban đầu định gộp hai `node_text`
     (`step05d:63` nhận *props dict*, `step07:133` nhận *node* rồi rẽ nhánh theo class)
     vào một module chung, giữ tên riêng. Khi hai stage đó thực sự dời (2026-07-28), lộ ra
     đây **không phải bản trùng** theo nghĩa "cùng logic, khác chỗ ở" — gộp chung sẽ âm
     thầm viết lại prompt LLM đã trả tiền của một trong hai. Mỗi hàm ở lại đúng stage sinh
     ra nó; xem PIPELINE.md §2.1 "bẫy `node_text`".
3. **Các stage dời được** — tiêu chí là **"mọi symbol NÓ import đã nằm trong `core/`"**,
   KHÔNG phải "không ai import nó". Cả hai điều kiện đều cần, nhưng điều kiện thứ hai
   mới là thứ quyết định thời điểm dời được.
   - ✅ **`step00` → `report/quality.py`** (2026-07-25), stage đầu tiên được dời.
     Dời **nguyên văn**: `diff` với bản `src/` chỉ khác đúng hai chỗ — docstring và
     khối import (4 symbol giờ lấy từ `esg_kg.core`, `DEFAULT_*` dựng từ
     `core.paths`). Toàn bộ ~500 dòng logic Q1–Q8 không đổi một ký tự.
     Đây cũng là lúc chốt cách CHẠY (§3).
   - **Quét lại đồ thị import (2026-07-25): 6 stage nữa ĐÃ đủ điều kiện ngay**, không
     phải "chờ `core/` xong" như bản trước của tài liệu này viết:

     | Stage | Import từ stage khác | Trạng thái |
     |---|---|---|
     | `step07b`, `step09`, `data_sync` | *(không có)* | ✅ dời được ngay |
     | `step03c` | `REPO_ROOT` | ✅ đã có trong `core/paths` |
     | `step06` | `REPO_ROOT`, `load_schema_sets` | ✅ đã có |
     | `step04b` | `merge_preserving_edits`, `normalize_name` | ⛔ đủ điều kiện nhưng KHÔNG dời — §4.2 |
     | `step05b` | + `parse_source_id` (step03b), `PROVENANCE_CLASSES`/`get_stable_entity_id` (step02) | ✅ **ĐÃ DỜI** 2026-07-27 (`core/identity.py` mở khoá, rồi dời ngay trong ngày) |

     ⚠️ **Hai chỗ bảng trên từng ghi sai, sửa 2026-07-27:**
     (a) symbol `step05b` cần từ step02 là **`get_stable_entity_id`**, không phải
     `stamp_provenance` — xem `step05b:49-50`;
     (b) bảng này là bản quét **2026-07-25** nên **thiếu `step03b` và `step04`**: cả hai
     trở nên đủ điều kiện *về sau*, khi `core/naming` + `core/schema` hoàn tất. Đừng đọc
     nó như danh sách đầy đủ — nguồn cập nhật là `PIPELINE.md` §2.1.

     ✅ **`step03c` → `kpi/canonicalize.py` (2026-07-25), stage thứ hai.** `diff` với bản
     `src/` đúng **hai hunk**: docstring và một dòng import (`REPO_ROOT` lấy từ
     `core.paths`). Dời bằng cách *copy nguyên file rồi vá khối import* — không gõ lại,
     nên "verbatim" là sự thật kiểm chứng được chứ không phải lời hứa.
     Arm tương đương gồm 6 nhóm; mạnh nhất là chạy `canonicalize_kpis` ở **cả hai cây**
     trên corpus thật rồi so **từng property dict của 5 214 KPIObservation** (4 913 node
     phân biệt) + dict stats + `backfill_goal_target_date`. Mỗi cây nhận một deep copy
     riêng vì hàm này mutate tại chỗ. Kèm `test_canonicalize_corpus_arm_is_not_vacuous`
     canh 4 tier (`kpi_type`/`alias_exact`/`rejected_unit`/`no_match`) đều phải kích hoạt
     — nếu không, arm chỉ đang so hai đống rỗng mà vẫn "PASS".

     ❌ **`step04b` đã được dời sang `registry/standards.py` (2026-07-26) rồi **bị gỡ ra**
     ngay trong ngày. Lần dời verbatim làm đúng quy trình và xanh hết, nhưng chính lúc đọc
     kỹ file để viết arm tương đương thì lộ ra nợ thiết kế bên dưới — và theo §5.4, cái
     đúng là sửa chứ không phải bê nguyên sang kiến trúc mới. Xem **§4.2**.

     ✅ **`step05c` → `resolve/indicators.py` (2026-07-27), stage thứ ba.** `diff` với bản
     `src/`: **15 dòng thêm / 115 dòng xoá, 0 dòng logic mới** — docstring, khối import,
     bỏ `from datetime import date` (chỉ `TODAY` dùng), và xoá phần đã trích sang
     `core/graph_patch.py`. Sinh bằng script cắt file, không gõ lại.
     Arm tương đương gồm 7 nhóm, **hai arm chạy `run()` thật bổ sung cho nhau chứ không
     thừa** — đo bằng mutation check: hoán đổi `pen_ind = "TT96-6.5.2" if amount else …`
     thì arm đồ thị thật **không thấy** (cả 4 node `Penalty` sống đều `amount == 0`, đi
     nhánh `self_reported_zero` rồi `continue` trước khi tới dòng đó), chỉ fixture tổng hợp
     bắt được. Ngược lại arm đồ thị thật chạy trên bản đã **strip trục chỉ số** — bỏ node
     `StandardIndicator` + 4 nhãn cạnh rồi remap chỉ số mảng — nếu không thì đồ thị đã vá
     sẵn khiến mọi counter về 0 và arm chỉ so hai bản báo cáo rỗng. Đã dựng lại đủ
     67 chỉ số / 1 346 cạnh trên 10 358 node thật, khớp từng node và từng cạnh giữa hai cây.

     ℹ️ **Cập nhật 2026-07-26 — một rào cản của `step05c` đã tự mất.** Bản merge nhánh `tuan`
     thêm `get_gri_catalog()`: một global `GRI_CATALOG_PATH` hardcode + cache suốt vòng đời
     tiến trình, tức là symbol thứ ba chưa có chỗ ở trong `core/`, và tệ hơn là không test
     được (không inject được đường dẫn, cache rò rỉ giữa các test). Commit sửa bug pillar đã
     thay nó bằng `load_gri_catalog(path)` thuần + cờ `--gri-catalog`, catalog nạp **một lần
     trong `run()`** rồi truyền tay xuống `make_gri_node`/`build_keyword_index`. Nên khi dời
     `step05c` **không cần** nghĩ chỗ ở cho nó nữa — chỉ còn `GraphPatch`/`temporal_md`.
     Lưu ý khi viết arm tương đương: `match_keyword` nay là **"phrase dài nhất thắng"**, không
     còn là "chỉ khớp khi không nhập nhằng" như tài liệu cũ mô tả — pin đúng hành vi hiện tại;
     muốn đổi lại thì đó là commit hành vi riêng theo §5.3.
     ✅ **`step03b` → `graph/anchor_kpi.py` (2026-07-27), stage thứ tư.** `diff` với bản
     `src/`: **17 dòng thêm / 20 dòng xoá, 0 dòng logic** — docstring, khối import, bỏ
     `Optional` khỏi `typing`, và **xoá** `parse_source_id` (nay lấy từ `core.identity`).
     Sinh bằng script cắt file, có assert vị trí cắt trước khi cắt.
     Arm nằm ở **file riêng** `test/test_esg_kg_anchor_kpi.py` — file equivalence đã quá
     1 100 dòng; hợp đồng không đổi, chỉ là chuyện tổ chức.
     **Bản nháp đầu của arm bị RỖNG, và đó là bài học đáng ghi**: corpus trên đĩa đã bị
     chính stage này vá (95/306 cạnh `observedAtFacility` mang
     `anchor_method=offline_gazetteer`), nên chạy lại là no-op và arm so hai kết quả rỗng
     rồi in PASS. Đúng cái bẫy `strip_axis()` của `step05c` — nay đã **hai ca**, nên coi
     là luật cho mọi stage vá tại chỗ: `strip_anchors()` dựng lại input trước-khi-vá, và
     **strip theo nguồn gốc chứ không theo nhãn cạnh** (211 cạnh `observedAtFacility` còn
     lại do extraction sinh, xoá nhầm là đo sai). Kết quả rỗng được giữ lại thành arm
     **idempotency** riêng, vì đó mới là tính chất vận hành thật đang dựa vào.
     Kiểm bằng mutation: `MIN_NAME_CHARS` 10 → 9 ở cây mới làm arm đỏ.
     ✅ **`step05b` → `resolve/provenance.py` (2026-07-27), stage thứ năm.** `diff` với bản
     `src/`: **18 dòng thêm / 8 dòng xoá, 0 dòng logic** — chỉ docstring + khối import.
     Là stage đầu tiên dời được mà **không phải trích thêm module `core/` nào**: lát cắt
     `step03b` hôm trước đã lifted sẵn cả 4 symbol nó cần (`PROVENANCE_CLASSES`,
     `get_stable_entity_id`, `parse_source_id` → `core.identity`; `get_identity_keys` →
     `core.schema`). Đó chính là ý nghĩa vận hành của chữ "mở khoá" ở mục trên.
     Arm ở file riêng `test/test_esg_kg_provenance.py` (12 nhóm, không nhóm nào skip).

     **Luật vá-tại-chỗ ở §PIPELINE.md §3 được tinh chỉnh tại đây, và đây là phần đáng
     ghi nhất của lát cắt này.** Dự đoán ban đầu là arm sẽ rỗng như `05c`/`03b`. **Sai**:
     `step05b` chỉ `continue` đúng một trường hợp (`provenance_method == "extraction"`,
     hiện **0 node**), còn lại nó **khớp lại và đóng dấu lại từ đầu** — nên arm trên đồ thị
     sống so **6 258 dấu** thật ở cả hai cây, không cần strip để cứu. Luật đúng không phải
     "stage vá tại chỗ ⇒ arm rỗng" mà là: **hỏi cái `continue` — nó bỏ qua hay tính lại?**
     `strip_provenance()` vẫn được viết, nhưng để chứng minh tính chất *mạnh hơn*: không key
     nào `05b` ghi nằm trong `identity_keys` của bất kỳ lớp `PROVENANCE_CLASSES` nào (đã đối
     chiếu `config/schema.json`), nên `get_stable_entity_id` ở tier 3 không thể thấy chúng và
     **stage không bao giờ đọc output của chính nó**. Nếu điều đó vỡ, đồ thị sẽ trôi dần sau
     mỗi lần chạy lại mà không có tín hiệu nào khác. Thêm arm bất biến thứ tự node (step06
     khoá Neo4j theo *chỉ số mảng*, dossier step07 trỏ theo `node_index`) và fixture tổng hợp
     cho nhánh `extraction` mà dữ liệu thật chưa chạm tới.

     (`step07b` từng đứng đầu danh sách này — đã loại, xem §4.1.) `step09`/`step06` cần
     Neo4j nên arm của chúng chỉ kiểm được tới mức import + hàm thuần; để sau.

     ✅ **Bốn lượt dời sau đó (2026-07-28), tường thuật đầy đủ ở `PIPELINE.md` §2.1 —
     ở đây chỉ tóm để mục này khỏi lệch với hiện trạng thật:**
     - **`step03` → `graph/fix_triples.py`, stage thứ sáu.** Trông như hub (7 stage
       import nó) nhưng mọi symbol chúng lấy đã lên `core/` từ trước, phần stage-local
       không ai import ⇒ luật "kiểm bằng CHIỀU import, không bằng số người import" áp
       dụng — nó là leaf, không phải hub. Đi kèm khối `build_validated` đầu tiên (§5.7).
     - **`step05d` → `resolve/align_claims.py`, stage thứ bảy.** `GraphPatch`/`temporal_md`
       đã có sẵn từ lát cắt `05c`, nên dời không trích thêm `core/` nào. Bài học lớn nhất:
       "có `--dry-run`" ≠ "dễ test" — ở đây `--dry-run` return trước khi provider được
       dựng, nên thứ chứng minh tương đương là một **provider giả** tiêm vào cả hai cây.
     - **`step07` → `crosscheck/claims_vs_conduct.py`, stage thứ tám** — đòn bẩy lớn nhất
       cả đợt, vì nó là stage DUY NHẤT còn chặn ai đó (`08` chờ `node_text`, `10` chờ
       `Adjudicator`); dời nó mở khoá cả hai cùng lúc. (`10` đã bị xoá hẳn khỏi dự án
       sau đó — §4.3 — nên phát biểu này giờ chỉ còn đúng cho `08`.) Cũng là lượt import
       NGƯỢC đầu tiên: `_Provider`/`_OpenAIProvider` nay lấy từ `core.llm` — đúng hai lớp
       mà kernel đó đã trích TỪ CHÍNH file này một ngày trước.
     - **`step04` → `registry/issuer.py`, stage thứ chín, cùng ngày với `07`.** Trông như
       hub (6 stage import nó) nhưng cả ba symbol chúng lấy (`normalize_name`,
       `name_tokens`, `merge_preserving_edits`) đã ở `core/naming.py` — hub đã tan, dời
       được ngay như một leaf. Ghi file **tracked + sửa tay** (`config/issuer_registry.json`),
       nên mọi arm chạy trên workspace tạm, không đụng bản thật. Một commit theo sau xoá
       nhánh chết `isinstance(data, dict) and "nodes"/"edges"` **trong CẢ HAI cây** (§5.2
       bảng cuối, §5.3).

     Với bốn lượt đó, `01` là hub **duy nhất** còn lại (§4 dưới không còn đúng như viết
     ban đầu — xem sửa ngay sau).
   - **CHƯA đủ điều kiện dù không ai import chúng, TÍNH TỚI THỜI ĐIỂM VIẾT ĐOẠN NÀY
     (2026-07-27)** — bốn dòng dưới đã lỗi thời sau các lượt dời ở trên, giữ lại để thấy
     dự đoán ban đầu sai ở đâu: ~~`step05d` (còn chặn ở `core/llm.py`)~~ → đã dời.
     ~~`step08` (chờ `core/text.py`)~~ / ~~`step10` (chờ `Adjudicator`)~~ → cả hai chờ
     đúng `step07` dời, không chờ `core/` nào — và `step07` đã dời, nên lúc đó cả hai chỉ
     còn chờ tới lượt chính chúng. (`step10` sau đó bị xoá hẳn khỏi dự án, §4.3 — dòng này
     giữ nguyên vì là tường thuật đúng thời điểm 2026-07-28 lúc `step07` vừa dời.)

     ✅ **`step01` → `kpi/extract.py`, stage thứ mười (2026-07-28), một ngày sau `04`/`07`.**
     Nó không dùng `_Provider`/`_OpenAIProvider` — `core/llm.py` đã ghi rõ không có provider
     Gemini để trích (dự án đứng sau `GEMINI_API_KEY` bị 403 vĩnh viễn) — nên `KPIExtractor`,
     prompt, JSON schema (`KPI_SCHEMA`/`_OBSERVATION_SCHEMA`/`_KPI_ITEM_SCHEMA`) và
     `normalize_kpi_response` ở lại stage nguyên vẹn; không ai khác trong pipeline import
     chúng. Chỉ 5 helper JSONL thuần dời sang **`core/io_jsonl.py` (module `core/` mới)** —
     đúng 5 symbol mà `step02:43-50` import từ nó, nên module này là điều kiện của `02`,
     không phải của `01`, đúng kiểu `core/identity.py` rơi ra từ lát cắt `03b`. Diff với bản
     `src/`: docstring + khối import + xoá 5 hàm giờ import từ `core.io_jsonl`, **0 dòng
     logic khác**. Nhánh trả tiền dùng đúng kỹ thuật của `03`/`05d`/`07`: vì không có
     `_Provider` đứng trước Gemini, stub tiêm thẳng lên `google.genai.Client`, trả lời tất
     định theo CRC của prompt — áp dụng lần thứ tư, xác nhận đây là khuôn chung chứ không
     phải mẹo riêng cho stage OpenAI. Arm mạnh nhất: `load_pages_from_jsonl` +
     `build_page_text`/`page_has_esg` trên corpus thật (13 tài liệu / 1 356 trang, 0 dòng
     lệch), cộng `process_document` qua fixture tổng hợp ở cả hai cây — bao gồm arm
     idempotency (`out_file.exists()` ⇒ không gọi lại client, cùng câu hỏi "gặp lại tàn dư
     của chính nó thì bỏ qua hay tính lại" mà PIPELINE.md §3 đặt ra cho mọi stage vá tại
     chỗ, chỉ khác là ở đây tàn dư là *file*, không phải *node đồ thị*). Test:
     `test/test_esg_kg_extract.py` (10 nhóm).
4. **Stage HUB cuối cùng: không còn.** ~~step04 → step03 → step02 → step01~~ — dự đoán ban
   đầu sai theo thứ tự: `step04` và `step03` hoá ra là **leaf** (hub của chúng đã tan nhờ
   `core/naming` và `core/schema`/`core/dates`), và `step01` — dự đoán đúng là hub thật sự
   **duy nhất** còn lại — nay cũng đã dời (2026-07-28), cho ra `core/io_jsonl`. `step02`
   không phải hub, và nay cũng đã dời (2026-07-29, sau khi §5.6 land trong `src/` trước)
   — nó là stage cuối cùng, xem `PIPELINE.md` §2.1.

### 4.1 `step07b` KHÔNG được dời sang `esg_kg` (quyết định 2026-07-25)

⚠️ **Cập nhật 2026-07-29 (§7):** phần dưới đây, kể cả các dòng "❌ KHÔNG xoá
`src/step07b_enrich_dossiers.py`", mô tả quyết định TẠI THỜI ĐIỂM 2026-07-25, khi `src/`
còn phải chạy được song song với `esg_kg`. Quyết định đó đã bị **thay bằng một quyết định
mới** khi `src/` bị xoá hẳn 2026-07-29: file này (và `step04b`/`step10`) **đã bị xoá cùng
`src/`**, không giữ lại làm công cụ standalone nữa — xem §7. Đọc phần dưới cho *lý do*
step07b ngoài phạm vi migrate, không phải như một hướng dẫn "đừng xoá file" còn hiệu lực.

Refactor là lúc rẻ nhất để **không** mang một thứ sang kiến trúc mới. `step07b`
(softmax cân bằng bằng chứng, `docs/SOFTMAX_SCORING.md`) từng là stage kế tiếp trong
danh sách trên — nay bị loại khỏi phạm vi migrate.

**Căn cứ (quét 2026-07-25).** Bề mặt được giao là UI `frontend/` + `api/`, và nó
không đọc output của step07b — grep `score|softmax|abstain|assessment` trên
`frontend/js/app.js` (318 dòng) và `api/evidence_service.py` (263 dòng) ra **0 kết
quả**. Ba trường `assessment_scores` / `score_components` /
`score_disagrees_with_assessment` chỉ được đọc ở đúng hai nơi, và **cả hai đã chịu
được khi thiếu**: `step08:159,169-172` (`None` → `SET` null, tự xoá property cũ — ý
đồ ghi rõ ở `step08:167`) và `step09:268-274,358-361` (`if scores:` bỏ qua khối in).

**Phạm vi quyết định — đọc kỹ chỗ này:**

- ✅ `esg_kg` **không bao giờ** có `crosscheck/enrich_dossiers.py`. Không viết arm
  tương đương cho nó. `pipeline.py` để `new_module=None` (không xoá dòng: vị trí
  của nó trong thứ tự chạy vẫn là tri thức thật), `run.py --list` in `(not ported)`
  và loại nó khỏi mẫu số — nếu tính vào, tiến độ migrate sẽ vĩnh viễn không bao giờ đạt 100%.
- ❌ **KHÔNG xoá `src/step07b_enrich_dossiers.py`.** Model A: cây cũ vẫn chạy được
  nguyên vẹn. Xoá nó là *thay đổi hành vi*, phải theo §5.3, và không có lợi ích gì
  bù lại rủi ro sửa đường đọc trong step08/step09 sát hạn bảo vệ.
- ❌ **Không dọn dữ liệu.** 1093/1093 claim trong
  `graph_output/crosscheck/aaa_claim_assessments.json` đã có sẵn `assessment_scores`.
  Bỏ stage **không** làm mất field trên dossier hiện có; step08 vẫn đẩy lên Neo4j,
  step09 vẫn in. Muốn con số biến mất khỏi output thì sửa ở tầng trình bày, không
  phải ở đây.

  ⚠️ **Sửa 2026-07-26 (§5.4).** Bản trước còn viện thêm *"và file đó nằm trong snapshot
  HF đã pin ở `data_version.json`"* như thể điểm số đã đóng băng vĩnh viễn. **Căn cứ đó
  hết hiệu lực**: sau lần trích lại theo kế hoạch, step07 sinh dossier MỚI và
  `assessment_scores` biến mất khỏi đó. Quyết định không port **vẫn đứng vững** vì căn
  cứ chính không hề dựa vào snapshot — UI không đọc (grep 0 kết quả) và **cả hai
  consumer đều chịu được khi thiếu** (`step08:159,169-172` set null; `step09:268-274`
  `if scores:` bỏ qua). Hệ quả thật sau lần trích lại chỉ là: con số vắng mặt trong
  Neo4j/ledger cho tới khi ai đó chạy tay `python src/step07b_enrich_dossiers.py` —
  rẻ, offline, idempotent, và đó chính là lý do KHÔNG xoá file đó khỏi `src/`.

**Điều kiện đảo ngược.** Nếu `signals` generator trong `docs/proposals/CROSSCHECK_EXPANSION.md`
được xây (lúc đó `lam_struct`/`lam_kpi`/`lam_bp` mới khác 0 — hiện chúng đóng góp
đúng 0), hoặc nếu cần lại cờ `score_disagrees_with_assessment` như hàng đợi review
(66/1093 claim mà argmax mâu thuẫn với nhãn LLM), thì dời `None` → module path và
làm theo quy trình bước 3 bình thường.

Lưu ý: **muốn có lại điểm số sau lần trích lại KHÔNG phải là điều kiện đảo ngược** —
chạy tay `src/step07b_enrich_dossiers.py` trên dossier mới là đủ. Chỉ port khi stage
này trở thành thứ có người tiêu thụ thường xuyên.

Bảng stage được canh bởi `test/test_pipeline_table.py`: một stage `None` **bắt buộc**
phải có note nói rõ "not ported", và `--list` không được phép hiển thị nó như "chưa dời".

### 4.2 `step04b` KHÔNG được dời sang `esg_kg` — registry thành config tĩnh (quyết định 2026-07-26)

⚠️ **Cập nhật 2026-07-29 (§7):** cùng caveat như §4.1 — dòng "❌ KHÔNG xoá
`src/step04b_build_standards_registry.py`" mô tả quyết định 2026-07-26, khi `src/` còn
chạy song song. File đó **đã bị xoá cùng `src/` ngày 2026-07-29**; rebuild registry từ đầu
nay có nghĩa là sửa tay `config/standards_registry.json`, không còn script nào để chạy.

Khác `step07b` (§4.1, loại vì không ai tiêu thụ output), `step04b` bị loại vì **bản thân
nó không phải một stage**. Hai bằng chứng, đều đo được:

**(a) Vòng lặp phụ thuộc.** `step04b` đọc `graph_output/resolved/resolved_graph.json` —
**output của `step05`** — trong khi `step05` đọc `config/standards_registry.json` là output
của `step04b`. Thứ tự chạy ghi là 04b trước 05, nên **trên bare clone stage này không chạy
được**: file input chưa tồn tại. Nó chỉ chạy được vì máy đã có sẵn một vòng pipeline cũ.
Đối chiếu: `step04` (anh em sinh đôi) đọc `all_validated_triples.json` — stage **đứng
trước** nó — không vòng.

**(b) Lần quét đồ thị thu về con số không.** Cả **10/10 alias** trong registry đang commit
trùng khít `seed_aliases` viết tay trong chính file `.py`; 0 exclusion đến từ đồ thị. Quét
436 node, thêm được 0 thông tin — vì 5 tài liệu này là **từ vựng đóng**, đã biết trước hết.
Tệ hơn, chạy lại sinh đúng 1 mục `needs_review`: **`canonical_name` do chính `step04b` đặt
ra**, đã được step05 gắn lên node hợp nhất, nay quay ngược lại bị nhận nhầm là "tên lạ cần
duyệt". Vòng lặp đang tự sinh nhiễu cho chính nó.

**Quyết định — tách đôi đúng bản chất:**

- `config/standards_registry.json` **là config tĩnh**. Không stage nào sinh ra nó nữa ⇒ vòng
  lặp biến mất, bare clone chạy được. `match_patterns` và `exclude_hints` (trước đây là
  `SEEDS[*]["match_re"]` và `EXCLUDE_HINTS` trong code) **chuyển nguyên văn vào file config**,
  để nó tự mô tả đầy đủ. `step05` không đổi một dòng: nó chỉ đọc `canonical_name`/`kind`/
  `aliases`/`exclusions` và bỏ qua khóa lạ.
- Phần quét đồ thị thành **audit trong `step00`** (`standards_registry_audit`): "đồ thị có
  mention nào *trông giống* 1 trong 5 tài liệu mà registry chưa phủ không?". Cùng họ với P1
  identity lint, và step00 đã ở `esg_kg` rồi nên **số stage giảm 1 thay vì tăng**. Vòng
  lặp không tái sinh vì step00 **báo cáo về** một đồ thị chứ không **nuôi** đồ thị nào.
- ❌ **KHÔNG xoá `src/step04b_build_standards_registry.py`** (cùng lý do §4.1): nó vẫn là
  công cụ **gây lại registry từ đầu** cho một bộ corpus hoàn toàn mới. Chỉ là nó không
  nằm trên đường chạy nữa. `pipeline.py` để `new_module=None`, giữ nguyên dòng.

**Điều audit phải KHÔNG được làm mất.** Đồ thị có ~432 node `Standard`/`Regulation` nhưng
chỉ ~10 thuộc 5 tài liệu trong phạm vi; phần còn lại là chuẩn kế toán, ISO, thông tư thuế —
**cố ý ngoài phạm vi**. Một danh sách "không có trong registry" ngây thơ sẽ dài ~420 dòng
nhiễu và dạy người ta bỏ qua mục này. Đó là lý do `match_patterns` phải sống sót qua lần
chuyển này, và là một test riêng trong `test/test_standards_audit.py`.

**Kết quả trên đồ thị thật:** 418 cách viết phân biệt, 5 đã curate, **0 uncovered** — và
cái `needs_review` giả của step04b biến mất vì `canonical_name` nay được tính là covered
theo định nghĩa. Hai cây cho kết quả giống hệt nhau trên đồ thị thật.

**Điều kiện đảo ngược.** Nếu số tài liệu tham chiếu thôi đóng (ví dụ mở sang nhiều ngành,
mỗi ngành một bộ quy định riêng) thì việc soạn registry bằng tay hết rẻ, và lúc đó một
stage sinh registry mới có lý. Khi ấy **vẫn phải đổi input sang `all_validated_triples.json`
(step03)** — nếu không, vòng lặp quay lại y nguyên.

### 4.3 `step10` (P6 evaluation) BỊ XOÁ hẳn khỏi dự án — không phải hoãn migrate (quyết định 2026-07-28)

Khác hẳn §4.1/§4.2: `step07b`/`step04b` là quyết định **phạm vi refactor** — cả hai vẫn
sống nguyên trong `src/`, người dùng vẫn chạy tay được. `step10` là quyết định **phạm vi
dự án**: người dùng chốt bỏ hẳn kiểu đo "coverage + case study + ablation không có nhãn
gốc" (P6) khỏi danh sách sản phẩm giao, không phải vì có cơ chế nào khác thay thế nó —
đơn giản là không cần đo kiểu này nữa.

**Hệ quả cụ thể, khác `step07b`/`step04b` ở đúng điểm then chốt:**

- ❌ **`src/step10_evaluate.py` bị XOÁ**, không giữ lại như công cụ chạy tay. Đây là điểm
  khác biệt với §4.1/§4.2 (cả hai đều "không xoá file `src/`" vì nó còn ích lợi làm công
  cụ độc lập) — `step10` không có lý do tương tự để giữ lại, vì quyết định là bỏ hẳn phép
  đo, không phải bỏ mỗi việc port.
- ❌ **`docs/EVALUATION.md` bị xoá.**
- ❌ **`esg_kg/pipeline.py::STAGES` không còn dòng `"10"`** — khác `07b`/`04b` (giữ dòng với
  `new_module=None` vì file `src/` gốc vẫn tồn tại), `step10` không có dòng nào cả: một dòng
  `STAGES` phải trỏ tới một file `src/` có thật (`test_pipeline_table.py::
  test_every_stage_points_at_a_real_src_file`), và file đó không còn tồn tại.
- Test liên quan: không có `test_esg_kg_evaluate.py` (chưa từng viết, vì `step10` chưa
  từng được dời) nên không có gì phải xoá ở phía test tương đương.
- Các chỗ mô tả lịch sử "dời `step07` mở khoá `08` và `10`" (CLAUDE.md, PIPELINE.md,
  bình luận trong `core/llm.py`/`crosscheck/claims_vs_conduct.py`) được sửa lại chỉ còn
  `08` — sự kiện mở khoá `10` vẫn có thật lúc đó, nhưng nhắc lại hôm nay dễ khiến người đọc
  tưởng nhầm còn một stage `10` đang chờ dời.

**Điều kiện đảo ngược.** Nếu dự án sau này cần lại một phép đo kiểu P6 (coverage/case-study/
ablation không có ground truth), đó là viết **mới** — tra `git log -- src/step10_evaluate.py
docs/EVALUATION.md` trước ngày xoá để lấy lại thiết kế cũ làm tham khảo, không phải khôi phục
nguyên trạng, vì các doc thiết kế phụ thuộc nó (`docs/proposals/CROSSCHECK_EXPANSION.md`,
`docs/SOFTMAX_SCORING.md`) cũng đã được đánh dấu là đề xuất treo, không còn chỗ để cắm.

## 5. Sửa lỗi trong lúc refactor — nguyên tắc "vá ở stage sớm nhất"

Refactor **không** tự sửa lỗi: helper được trích nguyên văn, nên mọi khiếm khuyết
của `src/` đi thẳng sang `esg_kg`. Test tương đương (§6) tồn tại chính là để *bảo
toàn hành vi*, kể cả hành vi sai. Vì vậy việc sửa lỗi cần luật riêng.

### 5.1 Luật: lỗi được sửa ở stage SỚM NHẤT có đủ thông tin để sửa

Không được để một module phía sau đi dọn hậu quả của module phía trước. Stage sau
chỉ được xử lý bù khi rơi vào **một trong ba ngoại lệ có tên**, và phải ghi rõ
ngoại lệ nào ngay trong docstring của stage:

- **E1 — Backfill dữ liệu đã đóng băng.** Bản sửa thật ĐÃ nằm ở stage sớm; stage
  sau chỉ vá phần dữ liệu cũ không thể trích lại (tốn tiền LLM, và step02 chạy
  lại còn kéo theo rủi ro `claim_id` không tất định). **Bắt buộc** đánh dấu
  phương pháp trên chính dữ liệu (vd `anchor_method`, `provenance_method`) và ghi
  điều kiện khai tử: *"gỡ được khi corpus được trích lại"*.
- **E2 — Stage sớm về mặt cấu trúc không thể biết.** Thông tin chỉ tồn tại về
  sau (vd cần đồ thị đã resolve mới có node canonical để nối).
- **E3 — Stage sớm cố ý giữ lại bất định thay vì đoán bừa.** Khi ấy stage sau xử
  lý `None`/cờ nghi ngờ là **tôn trọng hợp đồng**, không phải vá bù.

Không thuộc E1/E2/E3 ⇒ sửa ngược lên stage sớm, không thêm code phòng thủ — **trừ khi
stage sau không hề đang vá bù mà đang làm một việc khác về bản chất** (§5.2.1). Hỏi trước:
*đây có thật là dọn hậu quả của stage trước không?* Nếu không, đừng ép nó vào E1/E2/E3.

### 5.2 Phân loại hiện trạng `src/` (quét ngày 2026-07-25)

| Chỗ | Loại | Căn cứ |
|---|---|---|
| step03b anchor KPI→Facility | **E1** | step02 prompt đã sinh `observedAtFacility` cho extraction mới (step02:181,191,224,281); step03b chỉ vá dữ liệu đã trả tiền, gắn `anchor_method="offline_gazetteer"` |
| step05b stamp provenance | **E1** | step02:555–572 tự stamp `provenance_method="extraction"`; step05b:29 bỏ qua node đã có |
| step03c gán `kpi_id` | **KHÔNG phải vá bù** — mối quan tâm riêng, xem §5.2.1 | ~~E2~~ *(phân loại cũ sai, sửa 2026-07-25)* |
| step05c trục chỉ số | **E2** | cần đồ thị đã resolve |
| step05:392 `date_start_key(...) or str(...)` | **E3, hợp lệ** | step03 cố ý trả `("Q2 2023", False)` giữ nguyên thay vì bịa ngày; step05 buộc phải xử lý `None`, nếu không mọi ngày không parse được sẽ gộp thành một version |
| ~~step04:428 sniff `{nodes,edges}`~~ | **VI PHẠM — ĐÃ SỬA (2026-07-28)** | step03 luôn ghi `List[Dict]` (step03:545,622); file thật là list 14 677 phần tử; step05 đọc đúng file đó mà không sniff. Nhánh chết đã bị xoá **trong CẢ HAI cây** cùng lúc step04 dời (§5.3), red-first: `test_build_no_longer_silently_converts_a_nodes_edges_dict_in_either_tree` trong `test/test_esg_kg_issuer.py` |

Kết luận: nguyên tắc này thực ra đã được tuân thủ gần như toàn bộ, nhưng chưa từng
được viết ra — nên nó đang được giữ bằng trí nhớ. Bảng trên là chỗ ghi chính thức.

### 5.2.1 Loại thứ tư: "mối quan tâm riêng" (không cần ngoại lệ nào)

§5.1 viết như thể mọi stage-sau-xử-lý đều là *vá bù*, và không thuộc E1/E2/E3 thì phải
đẩy ngược lên stage sớm. Thiếu một khả năng: stage sau có thể đang làm **một việc khác
về bản chất**, không phải dọn hậu quả của ai cả. Khi đó không cần ngoại lệ, và đẩy ngược
lên stage sớm là làm hỏng thiết kế.

`step03c` là ca đó. Phân loại **E2 cũ là sai**, với hai lỗi:

1. Căn cứ cũ ("`kpi_type` nằm trong `identity_keys`") giải thích vì sao step03c **ghi
   property mới thay vì đè `kpi_type`** — nó không nói gì về việc *gán ở stage nào*. Nếu
   step01 sinh thẳng `kpi_id` lúc trích thì node sinh ra đã có mã, **không hề có vấn đề
   thứ tự node**. Căn cứ đúng cho một câu hỏi khác.
2. E2 đòi "stage sớm về cấu trúc không thể biết" — sai thực tế: `step01:221` đã nhét
   nguyên `KPI_DEFINITIONS` vào prompt và `step01:214` bảo LLM tự gán. Step01 **biết**,
   chỉ là gán kém (488/5214 ≈ 9,4% ra được mã).

Căn cứ thật để tách stage: **map từ vựng là hàm tất định, không được nhốt trong một lời
gọi bất định.**

| | step01 | step03c |
|---|---|---|
| Bản chất | đọc hiểu văn bản | tra từ điển |
| Tính chất | LLM, bất định, trả phí | thuần, tất định, miễn phí |
| Chạy lại | trả tiền lại, kết quả có thể khác | vài giây, `--dry-run`, luôn ra đúng thế |
| Truy vết | "vì sao LLM chọn TT96-6.6.1?" → không trả lời được | `kpi_id_method` ghi rõ tier đã kích hoạt |

Thêm nữa `config/kpi_type_aliases.json` là **vật sống**, được nuôi từ chính danh sách
`no_match` trong file stats. Nhốt việc map vào step01 nghĩa là mỗi lần thêm một bí danh
phải trích lại toàn bộ corpus bằng LLM.

**Đường tiến hoá đúng** (chưa làm, ghi lại để không quên): dạy `step01` sinh thẳng
`kpi_id` khi chắc chắn — lúc đó step03c tụt xuống thành **E1 thuần** ("bản sửa thật đã ở
stage sớm, stage sau chỉ vá dữ liệu đã đóng băng"), kèm điều kiện khai tử *"gỡ được khi
corpus được trích lại"*. Đúng khuôn mẫu step02→step03b (`anchor_method`) và
step02→step05b (`provenance_method`) đã dùng.

✅ **Đã làm 2026-07-25:** `kpi_id_method` được stamp lên từng node
(`step03c:242`), đáp ứng yêu cầu "bắt buộc đánh dấu phương pháp trên chính dữ liệu" của
§5.1 mà stage này đang thiếu. Quan trọng nhất là nó tách `rejected_unit` (2913 — cố ý từ
chối KPI tài chính) khỏi `no_match` (1368 — lỗ hổng từ điển, tức việc cần làm); trước đó
cả hai đều là `kpi_id: null` và không phân biệt được, nên 1368 ca đáng sửa bị chôn trong
đống nhiễu gấp đôi. Canh bởi `test_step03c_stamps_the_rule_that_decided_each_kpi_id`.
*(Ghi nhận: `load_triples()` trong `test/test_esg_kg_equivalence.py` cũng đang sniff
kiểu tương tự — chấp nhận được cho test harness, nhưng siết lại khi step04 được dời.)*

### 5.3 Quy trình sửa một lỗi (giữ nguyên lưới an toàn)

Mấu chốt: test tương đương **chặn** thay đổi hành vi, nên không được nhét bản sửa
vào commit refactor. Tách làm hai loại commit:

- **Commit refactor** — dời nguyên văn, `src/` không đổi, test tương đương XANH.
- **Commit sửa lỗi** — sửa **ĐỒNG THỜI CẢ HAI CÂY** trong cùng một commit, cộng
  một test hành vi đã đỏ trước đó. Test tương đương **vẫn xanh**, và giờ nó chứng
  minh thêm một điều: bản sửa đã đáp xuống hai cây giống hệt nhau.

Sửa cả hai cây **không** phá Model A: Model A cấm *rewire import* của `src/`
(sẽ `ImportError`), chứ không cấm sửa lỗi tại chỗ. Nhờ vậy không bao giờ có giai
đoạn hai cây lệch nhau âm thầm, và bản sửa có hiệu lực ngay trên pipeline đang
chạy thật (`src/`) chứ không nằm chờ trong `esg_kg`.

Arm tương đương của một symbol chỉ được **khai tử khi bản sinh đôi trong `src/`
bị xoá**, không sớm hơn.

### 5.4 Corpus AAA SẼ được trích lại — chuẩn hoá ngay trong lúc refactor (chốt 2026-07-26)

**Mục tiêu của refactor không chỉ là dời code, mà là để chạy lại pipeline từ đầu — kể cả
với AAA.** Cây `esg_kg` phải là thứ dựng lại được toàn bộ đồ thị từ JSONL đã gán nhãn, chứ
không phải một bản chép đẹp hơn của các bản vá tích tụ quanh một snapshot đóng băng.

Hệ quả trực tiếp: **"làm vậy sẽ đổi `identity_keys` / đổi thứ tự node / hỏng dossier đã trả
tiền" KHÔNG còn là quyền phủ quyết.** Nó tụt xuống thành **chi phí phải lên lịch**. Trước
2026-07-26 nó là lý do để chọn phương án vá bù; từ nay nó không còn là lý do đó nữa.

**Luật quyết định (thay cho mặc định cũ):**

> Khi refactor chạm tới một cơ chế mà bản sửa đúng nằm ở stage sớm hơn, **hãy đưa nó về
> stage sớm đó**. Chỉ giữ lại bản vá ở stage sau khi nó thuộc **E2 hoặc E3** (§5.1) — hai
> ngoại lệ này nói về *thông tin*, nên trích lại corpus không xoá được chúng.
> **E1 thì khác hẳn**: E1 tồn tại *chỉ vì* dữ liệu cũ không trích lại được. Điều kiện khai
> tử của E1 — *"gỡ được khi corpus được trích lại"* — nay là **một sự kiện đã lên lịch**,
> không còn là giả định xa vời.

**Những gì luật này lật lại trong chính tài liệu này:**

| Chỗ | Trước | Từ 2026-07-26 |
|---|---|---|
| §5.2.1 "đường tiến hoá đúng": dạy `step01` sinh thẳng `kpi_id` | ghi lại để khỏi quên, chưa làm | **nằm trong phạm vi** — làm được thì làm; step03c tụt xuống E1 thuần rồi khai tử cùng lần trích lại |
| step03b `anchor_method`, step05b `provenance_method` (E1) | vá vĩnh viễn | vá **có hạn sử dụng** — sau lần trích lại, phần dữ liệu cũ hết lý do tồn tại |
| Tên `Standard`/`Regulation` (ca step04b, phát hiện 2026-07-26) | không đụng vì `identity_keys=['name']` → đổi thứ tự node → hỏng dossier | **chuẩn hoá ở step03** bằng alias map tĩnh; neo Stage A.3 của step05 còn lại chỉ là lưới an toàn |
| Bất kỳ đề xuất nào bị bác vì "phải re-run step02/step05" | bác | cân nhắc lại theo chi phí, không bác thẳng |

**Điều kiện tiên quyết phải xong TRƯỚC lần trích lại** (không phải rào cản để bàn thiết kế,
nhưng là rào cản để bấm nút):

1. **`claim_id` phải tất định** — dựng từ `(source_doc, source_page, sentence_index)` thay vì
   để LLM tự đặt (GitHub issue #2). Không có cái này thì step08 miss tier-1 **âm thầm**,
   không exception, và 209 evidence item đã trả tiền mất chỗ bám. Đây là món đầu tiên trong
   danh sách, không phải món cuối.
2. **Kế toán chi phí lần trích lại**: step01 + step02 (LLM, toàn corpus) + step07 (LLM, bắt
   buộc). step05 hiện chạy `--no-llm` nên không tính.
3. **Chụp `step00 --label` trước và sau**, rồi `data_sync.py push` + commit lại
   `data_version.json` trong cùng một lần ngồi (CLAUDE.md) — nếu không, snapshot mới vô hình
   với cả nhóm.

**Vẫn giữ nguyên, không được nới:**

- **§5.3 vẫn có hiệu lực.** Chuẩn hoá là *thay đổi hành vi* ⇒ commit riêng, sửa **cả hai
  cây**, kèm test hành vi đã đỏ trước. Không bao giờ nhét vào commit "dời nguyên văn".
- **Trích lại là một quyết định có chủ ý, không phải tác dụng phụ.** Không stage nào được tự
  ý làm mất hiệu lực dossier hiện có giữa chừng; việc đó xảy ra đúng một lần, có kế hoạch.
- Cho tới lúc đó, `src/` vẫn là pipeline chạy thật và dossier hiện có vẫn là bản giao.

### 5.5 `step05` khi được dời KHÔNG được ghi đè đồ thị đã vá (chốt 2026-07-27, ĐÃ LÀM 2026-07-29)

✅ **Cập nhật 2026-07-29: đã dời `step05` (`esg_kg/resolve/entities.py`, stage thứ mười
bốn) kèm khối `build_resolved` (§5.7 "Áp cho cụm 05", §3.2b của PIPELINE.md).** Toàn bộ
mục này vẫn đúng làm bối cảnh (mô tả khiếm khuyết trong `src/`, vẫn còn nguyên vì `src/`
không đổi — Model A), nhưng phần "quyết định" bên dưới nay đã thành code, không còn là
kế hoạch. Đọc §5.7 để biết cơ chế thật đã chọn.

Hôm nay đọc lại đường dữ liệu của cụm 05 thì lộ ra một khiếm khuyết thiết kế trong `src/`:
**chuỗi vá là bắt buộc nhưng không có gì bảo vệ nó.** Bản `esg_kg` không được mang khiếm
khuyết này sang.

**Hiện trạng đo được (2026-07-27, trên snapshot HF `09cfe062`):**

Chỉ tồn tại **một** file `graph_output/resolved/resolved_graph.json`. `05b`/`05c`/`05d` đều
`write_text()` ngược lại đúng đường dẫn đó, còn `step05:655` ghi đè **toàn bộ** file — không
merge, không cảnh báo. Nên chạy lại `step05` **xoá sạch cả ba bản vá**, và không có dấu hiệu
nào cho biết điều đó đã xảy ra.

| Chỗ | Bảo vệ hiện có | Hậu quả khi thiếu bản vá |
|---|---|---|
| `step05:655` | **không có** | ghi đè, mất `provenance_method` + trục chỉ số + align |
| `step06:365-368` | chỉ `logger.warning` | vẫn nạp Neo4j, đồ thị thiếu `StandardIndicator` |
| `step07:703-705` | **không có** — chỉ kiểm file tồn tại, thông báo lỗi còn chỉ nhắc `step05` | `step07:417-429` dựng index trục chỉ số ra rỗng ⇒ tầng retrieval tier-1 (`INDICATOR_BOOST`) đóng góp **0**, tụt về token overlap. Không lỗi, không cảnh báo; dấu vết duy nhất là `indicator_tier_pairs: 0` trong file stats |

Thứ đang giữ cho chuỗi này chạy đúng chỉ là ba dòng log cuối stage (`05b:369`, `05c:477`,
`05d:152` — đều nói *"Next: step06 --clear"*). Đó là **hợp đồng bằng trí nhớ**, đúng loại
nợ mà §5.2 đã phải lập bảng để ghi lại.

Dữ liệu xác nhận chuỗi hiện đang ở trạng thái đã vá: `provenance_method` trên 6 258 node
(05b), 67 `StandardIndicator` + 4 `self_reported_zero` (05c), và `alignment_method` chỉ có
`keyword` 639 — **`llm` bằng 0, tức `step05d` chưa từng chạy thật.** Nó là stage TÙY CHỌN
(docstring `step05d:3-5`), nên "đồ thị hoàn chỉnh" = `05 → 05b → 05c`; `05d` là tuỳ thêm.

**Quyết định.** Khi `step05` được dời sang `esg_kg/resolve/entities.py`, nó **không được ghi
đè artifact mà `step06`/`step07` đọc**. Chuỗi `05b → 05c` là bắt buộc và phải được cưỡng chế
bằng cấu trúc, không bằng tài liệu.

**Cơ chế: xem §5.7 — mặc định bây giờ là PHƯƠNG ÁN KHỐI, không phải ba dòng dưới đây.**
(Bản gốc để mở phần này. Ngày 2026-07-28 luật khối được chốt tổng quát ở §5.7 và nó là
phương án **thứ tư**, tốt hơn cả ba: không tốn thêm 40 MB, không cần `--force`, và **xoá
hẳn** khái niệm "vá tại chỗ" thay vì canh gác nó.) Ba phương án cũ giữ lại để đối chiếu:

| Phương án | Được | Mất |
|---|---|---|
| `step05` ghi artifact gốc riêng (`resolved_graph.base.json`), chuỗi vá sinh ra `resolved_graph.json` | `step06`/`step07` không phải sửa; chạy lại `step05` an toàn | thêm một bản 40 MB |
| Mỗi stage một artifact bất biến (`.base` → `.prov` → `.axis` → `.aligned`) | diff được từng stage; khái niệm "vá tại chỗ" biến mất | 4 × 40 MB; phải đổi `DEFAULT_INPUT` của 06/07 |
| Giữ một file, `step05` từ chối ghi khi phát hiện dấu vết vá (cần `--force`) | sửa ít nhất | vẫn một file; `--force` vẫn phá được |

**Ràng buộc mà phương án nào cũng phải thoả:**

1. **§5.4 vẫn ưu tiên.** Mục tiêu là dựng lại đồ thị **từ đầu**, nên "không ghi đè" bắt buộc
   phải có đường thoát cho lần trích lại có chủ đích. Không được biến thành cái khoá làm
   pipeline không rebuild được — đó sẽ là đánh đổi ngược hẳn với §5.4.
2. ⚠️ **SỬA 2026-07-28 — ràng buộc này đã đổi, đọc §5.7.** Bản gốc viết: *"§5.3 áp dụng ⇒
   commit riêng, sửa **cả hai cây**"*. Phần "cả hai cây" **không còn đúng**: §5.7 chốt rằng
   gộp khối là **redesign có chủ ý của riêng `esg_kg`**, `src/` giữ nguyên. Phần còn lại vẫn
   đúng nguyên: commit riêng, **test hành vi đỏ trước**, và test đó phải khẳng định điều hôm
   nay không gì khẳng định — *chạy `step05` trên đồ thị đã vá thì các bản vá phải còn nguyên
   (hoặc stage phải dừng)*. Với phương án khối thì câu đó thành: **không tồn tại trạng thái
   "đồ thị đã vá" ở giữa** để mà mất.
3. **Cưỡng chế thứ tự là phần việc riêng.** Nâng `step06:365` từ warning lên lỗi cứng, và
   thêm phép kiểm tương đương cho `step07`, là **commit khác** — nó đụng vào stage đã trả
   tiền (`step07`), nên không gộp chung.
4. `05d` phụ thuộc **cả** `05c` (`GraphPatch`/`temporal_md`) **lẫn** `step07` (`step05d:35`
   import `_OpenAIProvider`, `RateLimiter`) — chạy ngược chiều dòng dữ liệu. Nó là stage bị
   chặn nặng nhất của nhóm 05; đừng xếp lịch dời nó trước khi `core/llm.py` có.

### 5.6 `step02` sẽ xuất tiếng Việt cho `name`/`title` — phạm vi và ranh giới (chốt 2026-07-27)

Việc thực thi nằm ở GitHub issue **#6**; mục này ghi **quyết định và ranh giới**, vì đây là
thứ phải cố định *trước* khi bấm nút trích lại (§5.4) chứ không phải thứ ứng biến lúc sửa prompt.

**Hiện trạng đo được** (`graph_output/validated/all_validated_triples.json`, 14 677 triple,
27 220 lượt node có `name`/`title`): `step02` **không có một dòng nào** hướng dẫn về ngôn ngữ,
nên LLM tự quyết và đã dịch **52,7%** số tên sang tiếng Anh; chỉ 47,3% còn dấu tiếng Việt.
Cùng một pháp nhân tồn tại song song hai bản.

**Đây là sửa lỗi, không phải thêm rủi ro** — và lý lẽ nằm ở `normalize_name`, vốn đã hiểu
tiếng Việt (bỏ dấu + bỏ từ chỉ loại hình pháp lý):

```
'CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT' -> 'nhua va moi truong xanh an phat'
'Công ty Cổ phần Nhựa và Môi trường Xanh An Phát' -> 'nhua va moi truong xanh an phat'   ✅ gộp
'An Phat Green Environment and Plastic Joint Stock Company'
                                                 -> 'an phat xanh environment and plastic' ❌
```

Hai khoá khác nhau ⇒ **Stage A của `step05` không thể gộp deterministic**. Bản dịch không gây
lỗi, nó **tách một thực thể thành hai** — đúng loại hỏng mà §5.1 bảo phải sửa ở stage sớm nhất
có đủ thông tin, và stage đó là `step02`.

**Phạm vi — ranh giới phải ghi thẳng vào prompt:**

| Trường | Ngôn ngữ | Vì sao |
|---|---|---|
| `name`, `title`, `description`, văn bản tự do | **tiếng Việt, giữ dấu** | là bằng chứng truy vết được, và là khoá của `normalize_name` |
| `valid_from`, `valid_to`, `date`, `recorded_at` | ISO `YYYY[-MM[-DD]]` | xem cảnh báo ngay dưới |
| `class`, `predicate` | định danh schema | `validate_triple` khớp **chính xác** với `config/schema.json` |
| id, `kpi_id`, `claim_id` | định danh máy | `claim_id` còn phải tất định (issue #2) |
| `is_current`, `date_uncertain` | boolean | kiểu dữ liệu, không phải văn bản |
| `unit`, `unit_normalized` | từ vựng có kiểm soát | `step03c` khớp theo alias, không theo văn xuôi |

**Ngày là ranh giới nguy hiểm nhất.** Hôm nay chỉ **6 / 72 473** giá trị ngày không parse
được, vì prompt `step02` đã ép ISO (`step02:152-153`). Cách viết bằng chữ tiếng Việt hỏng hết:

```
OK    '31/12/2024' -> '2024-12-31'      FAIL  'ngày 31 tháng 12 năm 2024'
OK    '12/2024'    -> '2024-12'         FAIL  'Quý 4/2024' · 'năm 2024' · 'tháng 12/2024'
```

`normalize_date_string` **cố ý không bịa ngày**: nó trả lại nguyên chuỗi và chỉ cộng vào
`dates_unparseable`. Không exception, không cảnh báo — và P4 (`valid_from > valid_to`, chuỗi
version `is_current`) mất hiệu lực đúng trên những node đó. Đây là lý do phạm vi phải liệt kê
**loại trừ tường minh**, không chỉ nói "xuất tiếng Việt".

**Điều kiện tiên quyết:**

1. **Issue #2 — `claim_id` tất định.** Thay đổi chỉ có hiệu lực qua một lần trích lại toàn
   corpus, tức đúng sự kiện đã lên lịch ở §5.4, và §5.4 đã xếp #2 là *"món đầu tiên trong
   danh sách, không phải món cuối"*.
2. **Guard pha 2 của `step03` — ĐÃ XONG** (commit `046e572`, 2026-07-27).
   `preserve_property_values` chặn LLM sửa giá trị thuộc tính: `BATCH_FIX_PROMPT` là tiếng
   Anh và ra lệnh *"Fix typos/synonyms"* mà không giới hạn trường, nên đưa cho nó `name`
   tiếng Việt là nó dịch hoặc khử dấu — mà `validate_triple` không hề kiểm giá trị. Làm
   trước khi `step03` dời để chỉ phải sửa **một** cây (§5.3). Test:
   `test/test_step03_llm_value_guard.py`.

**Cái KHÔNG phải đổi.** `step03` bản thân nó miễn nhiễm với ngôn ngữ: pha 1
(`fix_direction` + `validate_triple`, `step03:260-324`) chỉ đọc `class`, `predicate` và *sự
có mặt* của các trường thời gian — không bao giờ đọc `name`/`title`; pha 1.5 chỉ đụng trường
ngày; pha 3 đã ghi `ensure_ascii=False`. Chỉ prompt pha 2 cần guard, và guard đã có.
`config/kpi_type_aliases.json` sẵn 26% chuỗi tiếng Việt nên `step03c` chịu được — nhưng rà
lại độ phủ sau khi có dữ liệu mới.

**Vấn đề riêng, đừng gộp vào đây:** 1 540 lượt tên chứa `Ƣ` (U+01A2 `LATIN CAPITAL LETTER
OI`) thay vì `Ư` — di sản font VNI/TCVN3 trong PDF (`MÔI TRƢỜNG` 594 lượt vs `MÔI TRƯỜNG`
571 lượt). Đã kiểm: `normalize_name` **gộp được** cả hai nên **không** phải lỗi định danh.
Nhưng `name` hiển thị thẳng ra ledger `step09` và Evidence View, nên khi title thành tiếng
Việt thì người đọc sẽ thấy nó. Chỗ sửa đúng là `data_processing/pdf_extractor.py`.

**Nghiệm thu** (neo vào số đo, không neo vào cảm nhận): tỉ lệ tên có dấu tăng rõ so với mốc
**47,3%**; `dates_unparseable` **không tăng** so với mốc **6 / 72 473**; số node
`Organization` của chính doanh nghiệp phát hành **giảm** sau `step05`; chụp
`step00 --label before/after` để đối chiếu Q1–Q8.

**Thực thi — phần mã nguồn ĐÃ LÀM (2026-07-29), phần nghiệm thu CHƯA LÀM.** Hai commit
riêng, đúng thứ tự đã chốt ở trên: (1) prompt fix land trong `src/` trước — thêm mục
`## OUTPUT LANGUAGE` vào cả hai template đúng bảng phạm vi ở trên, sửa lại các ví dụ mẫu
của cả hai template (chính chúng cũng đang mô hình hoá lỗi dịch/khử dấu), test
`test/test_step02_language_guard.py` (`Refs #6`); (2) dời sang
`esg_kg.graph.extract_triples` — stage thứ mười lăm và cuối cùng của đợt refactor, test
`test/test_esg_kg_extract_triples.py`. Điều kiện tiên quyết #2 ở trên (guard pha 2 step03)
đã xong từ trước; điều kiện tiên quyết #1 (issue #2, `claim_id` tất định) **vẫn OPEN**.
Vì vậy mục **Nghiệm thu** ngay trên đây **vẫn chưa được đo** — cả 4 số đo cần một lần
trích lại thật trên toàn corpus bằng `step02` mới, và CLAUDE.md cấm verify bằng cách chạy
lại một stage trả tiền. Bốn số đo đó để dành cho sự kiện trích lại toàn corpus đã lên
lịch ở §5.4, sau khi issue #2 xong — **không được coi mục 5.6 này là "đã nghiệm thu"**
chỉ vì phần code đã land.

### 5.7 Gộp stage thành KHỐI: một artifact, ghi một lần (chốt 2026-07-28)

Đây là **luật chung cho mọi cụm về sau**, không phải xử lý riêng cụm 03. §5.5 đã mô tả đúng
triệu chứng ở cụm 05 nhưng để mở phần cơ chế; mục này chốt cơ chế đó, và chốt ở dạng tổng
quát vì cùng một hình dạng lỗi xuất hiện ở **cả hai** cụm.

**Luật.** Khi N stage cùng đọc *và* ghi **một** artifact, chúng không phải N stage — chúng là
**một khối**. Trong `esg_kg`, khối được viết thành một hàm chạy chuỗi **in-memory** và ghi
file **đúng một lần ở cuối**. Không có "output ở giữa pipeline".

**Vì sao artifact trung gian là lỗi chứ không phải tính năng.** Nó không phải sản phẩm giao
ra — nó là chi tiết cài đặt bị rò ra thành hợp đồng. Cái giá đo được ở cụm 03:

| | Số đo (2026-07-28) |
|---|---|
| `all_validated_triples.json` trên đĩa | **14 677** triple |
| ├─ `03` pha 1, offline | 14 492 — dựng lại **miễn phí** |
| ├─ `03` pha 2, LLM | **90** — **đã trả tiền, không tất định** |
| └─ `03b` anchor | 95 — dựng lại miễn phí |
| `03c` `kpi_id` | 683 lượt node — dựng lại miễn phí |

Chạy lại `03` đầy đủ ⇒ `write_text()` đè cả file ⇒ mất **toàn bộ** phần dưới, không cảnh báo.
Y hệt `step05:655` trong §5.5, chỉ sớm hơn một file. Thứ giữ cho nó không hỏng là dòng log
cuối stage — lại là **hợp đồng bằng trí nhớ**.

**Ranh giới bắt buộc: "artifact trung gian" ≠ "cache của kết quả đã trả tiền".**
Đây là chỗ dễ làm hỏng nhất khi áp luật này. Bỏ artifact trung gian thì đúng; nhưng nếu bỏ
luôn chỗ lưu kết quả LLM thì mỗi lần chạy khối là **một lần trả tiền nữa**, và vì LLM không
tất định, kết quả còn **khác nhau giữa các lần**. Hôm nay `03b`/`03c` chạy lại được miễn phí
*chính vì* chúng đọc file đã đóng băng — gộp khối mà không tách cache ra là **đánh mất tính
chất đó**, tức là làm pipeline tệ đi chứ không tốt lên.

⇒ Phần trả tiền được ghi ra **cache riêng** (`graph_output/validated/phase2_repairs.json`),
khoá theo nội dung triple đầu vào. Khối đọc cache trước, chỉ gọi LLM cho phần chưa có. Kết
quả: **một** đầu ra duy nhất, mà khối vẫn chạy lại được **offline, miễn phí, tất định**.

Nói gọn hai câu để lần sau khỏi cân lại:

> *Artifact trung gian* trả lời câu "pipeline đang chạy tới đâu" — bỏ được, vì đó là trạng
> thái nội bộ. *Cache* trả lời câu "cái này đã tốn tiền/thời gian rồi" — không bỏ được, vì
> thông tin đó không tái tạo miễn phí.

**Quan hệ với §5.3 — đây là NGOẠI LỆ, và phải đọc kỹ.** §5.3 bắt mọi thay đổi hành vi phải
land ở **cả hai cây**. Luật đó tồn tại để chống **drift ngoài ý muốn**. Còn đây là
**redesign có chủ ý của riêng `esg_kg`** (chốt với người dùng 2026-07-28), đúng tiền lệ
`step04` entity resolution: `src/` **không đụng một dòng nào**, giữ nguyên 3 stage rời và
artifact trung gian. Đồng bộ ngược sẽ là việc vô nghĩa — nó phá đúng cái Model A đang bảo vệ.
**Hệ quả: ràng buộc 2 của §5.5 ("sửa cả hai cây") KHÔNG còn áp cho các thay đổi kiểu khối
này.** Ai đọc §5.5 sau ngày này phải đọc kèm mục này.

**Vì sao ngoại lệ đó KHÔNG làm mất lưới an toàn** — điểm quan trọng nhất của cả mục:
thay đổi này chỉ đụng **thời điểm ghi file**, không đụng **nội dung kết quả**. Nên `src/`
vẫn làm **oracle** được, dù vĩnh viễn không được sửa:

> chạy chuỗi `src/` `03 → 03b → 03c` trên bản copy, chạy khối `esg_kg`, **kết quả cuối phải
> bằng nhau**. Corpus thật, offline, miễn phí.

Đó là tiêu chí nghiệm thu, và phải **đỏ trước**. Ngày nào một refactor làm mất tính chất
"cùng nội dung, khác thời điểm ghi" thì **dừng lại bàn** — lúc đó không còn oracle nào nữa,
và đó là loại thay đổi khác hẳn về mức rủi ro.

**Áp cho cụm 05 (trả lời phần bỏ ngỏ của §5.5) — ĐÃ LÀM 2026-07-29.** Cùng luật ⇒
`05 → 05b → 05c` là **một khối** (`esg_kg/resolve/build_resolved.py`), ghi
`resolved_graph.json` một lần ở cuối. Đây là **phương án thứ tư** cho bảng ở §5.5, và nó
tốt hơn cả ba dòng trong đó: không tốn thêm 40 MB như hai phương án artifact bất biến,
không cần `--force` mong manh như phương án thứ ba, và **xoá hẳn** khái niệm "vá tại chỗ"
thay vì canh gác nó. Ràng buộc riêng của cụm 05 được giữ đúng như dự tính:

- **`05d` KHÔNG nằm trong khối** — nó **tuỳ chọn** (budgeted LLM) và tự vá
  `resolved_graph.json` SAU khối, y hệt trước giờ; khối phải ra một `resolved_graph.json`
  đúng và đầy đủ dù `05d` vắng mặt, và arm oracle chứng minh đúng điều đó (05d không tham
  gia bước nào của nó).
- **Cache pha trả tiền được khoanh vùng hẹp hơn dự tính ban đầu — chỉ Stage C, không
  phải "05/05d" nói chung.** Đọc lại lúc thực thi thì cụm 05 có HAI nhánh tốn tiền khác
  nhau: Stage B (`gemini-embedding-001`, tính similarity) và Stage C
  (`gemini-2.5-flash`, phán quyết `same_entity`). Chỉ Stage C là bản sao đúng nghĩa của
  pha 2 khối 03 (LLM, không tất định) nên chỉ nó được cache
  (`AdjudicationCache`, khoá theo nội dung cặp node). Stage B bị bỏ ngoài **có chủ ý**:
  nó tất định theo phiên bản model, và theo CLAUDE.md pipeline hôm nay chạy `--no-llm`
  nên Stage B/C không hề chạy trong pipeline sống — viết cache cho một nhánh đang ngủ
  đông là việc đầu cơ, để lại làm follow-up nếu Stage B quay lại dùng thường xuyên.

Kết quả kiểm: arm oracle (chạy `src/` `step05(--no-llm) → step05b → step05c` làm oracle
trên corpus thật, so với khối) khớp **10 425 node / 14 387 cạnh giống hệt tuyệt đối**;
arm cache (chạy khối 2 lần qua client giả) cho thấy lần hai gọi `generate_content` **0
lần**. Test: `test/test_esg_kg_entities.py` + `test/test_esg_kg_resolve_block.py`. Chi
tiết đầy đủ: PIPELINE.md §3.2b.

**Cái KHÔNG được mất khi gộp khối:**

1. **Vẫn phải vá được đồ thị đang có.** §5.4 đòi dựng lại từ đầu, nhưng không được biến
   thành cái khoá chặn việc vá artifact hiện tại — giữ một lối vào đọc file đã có
   (`--renormalize`, hoặc `--from-validated`).
2. **Từng stage vẫn chạy riêng được.** Gộp khối là thêm một entrypoint, **không phải xoá**
   `run.py anchor_kpi`. Mất khả năng chạy lẻ là mất luôn khả năng chẩn đoán.
3. **Stats của từng stage vẫn phải ghi ra.** `anchor_patch_stats.json` /
   `kpi_canonical_stats.json` là dữ liệu chẩn đoán, không phải artifact trung gian — chúng
   không bị luật này đụng tới.

## 6. Lưới an toàn & mắt xích yếu

- **`test/test_esg_kg_equivalence.py`** là lưới chính khi xây `core/` (§4): pipeline cũ
  không đổi nên chỉ cần chứng minh bản mới bằng hệt bản cũ. Import cả hai cây, chạy
  trên input thật, assert bằng nhau. Offline (không LLM/Neo4j/mạng); arm nào cần
  `graph_output/` (git-ignored, ship qua HF) sẽ SKIP có thông báo trên bare clone.
  **Mỗi module `core/` mới phải thêm arm vào đây TRƯỚC khi trích** (xem quy tắc TDD
  trong CLAUDE.md). Đã mutation-check: sửa lệch `SYNONYMS`/`LEGAL_FORMS` ở một cây
  bị bắt bởi 3 arm.
  Arm của một **stage** không có "một giá trị trả về" để so, nên so ba thứ định
  nghĩa nó: hằng số module, từng hàm chỉ số, và Markdown đã render. Với `step00`
  còn có thêm phép kiểm cuối: chạy thật cả hai cây trên đồ thị thật rồi so
  artifact — JSON giống hệt, `.md` chỉ khác `label` + `generated_at`.
  ⚠️ **Chi phí phải né**: `q7_traversability` full BFS tốn ~44s/lần trên đồ thị
  10 393 node (đo thật) → 88s nếu chạy cả hai cây. Vì vậy arm đồ thị thật chạy
  `skip_slow=True`, còn nhánh Q7(c)/(d) phủ bằng một mini-graph tổng hợp 20 node
  (tức thời, và **chạy được trên bare clone**). Mini-graph đó được canh gác bởi
  `test_quality_mini_graph_is_not_vacuous`: mọi counter phải khác 0 và hai chỉ số
  BFS phải nằm **strictly giữa 0% và 100%** — nếu không, arm chỉ đang so hai đống
  số 0 mà vẫn "PASS".
- `test/test_temporal_invariants.py` import theo **bare-module** (`from step03_...`).
  Nó vẫn xanh trong suốt giai đoạn `core/` (vì `src/` không đổi). Chỉ khi tới bước
  3–4 (dời stage) mới cần cập nhật import của nó **đồng bộ** với mỗi lần chuyển.
- ✅ **Mắt xích yếu "cách CHẠY" đã gỡ** ở bước dời `step00` — xem §3.

### 6.1 Nợ kỹ thuật đã biết: bản sinh đôi của `step00`

`src/step00_graph_quality_report.py` **vẫn còn nguyên** sau khi dời (Model A), nên
tier map T1/T2/T3 hiện tồn tại ở **hai** nơi. Đó chính là thứ mà comment ở
`test/test_schema_contract.py:15` ("IMPORTED from step00, never re-declared") sinh
ra để chặn — chấp nhận tạm vì arm tương đương đang khoá hai bản bằng nhau, nhưng
**không được để lâu**. Commit dọn (tách riêng, đúng §5.3):

1. xoá `src/step00_graph_quality_report.py`;
2. `test/test_schema_contract.py` đổi sang `from esg_kg.report.quality import ...`;
3. khai tử các arm `test_quality_*` trong test tương đương (theo luật §5.3: arm
   chỉ chết khi bản sinh đôi trong `src/` bị xoá);
4. cập nhật CLAUDE.md phần "Common commands".

Không stage `src/` nào import `step00`, nên bước 1 không làm gãy pipeline đang chạy.

### 6.2 Lỗ của lưới an toàn: test tương đương KHÔNG thấy entrypoint (phát hiện 2026-07-26)

Merge nhánh `tuan` (`03a1592`) thêm một khối `sys.stdout.reconfigure(encoding="utf-8")`
cho win32 vào **`__main__` của `src/step00`** — và chỉ ở đó. Bản twin
`esg_kg/report/quality.py` không có, `run.py` cũng không xử lý encoding. Kết quả:
`python src/step00_...` in được báo cáo, còn `python src/run.py quality` vẫn
`UnicodeEncodeError` ở `print(render_markdown(report))`. **Cây đã refactor kém hơn cây nó
thay thế**, đúng tại stage sinh ra để chạy trước/sau mọi thay đổi.

`test_esg_kg_equivalence.py` **về mặt cấu trúc không thể bắt** ca này: nó so hằng số, từng
hàm chỉ số và Markdown đã render — nó *import* module, không bao giờ chạy `main()` hay
`__main__`. Mọi thứ nằm trong khối `__main__` là điểm mù.

**Đã sửa** (§5.3: một commit, cả hai cây, test đỏ trước): helper thành
`core/console.py::ensure_utf8_stdout()`, bản song sinh nằm ngay trong `src/step00`, và
**điểm gọi là đầu `main()`, KHÔNG phải `__main__`** — vì đó là chỗ duy nhất cả ba cách chạy
đều đi qua (`python src/stepNN_*.py`, `run.py <stage>` gọi `mod.main()`, và
`python -m esg_kg...`). Nhờ vậy `run.py` vẫn là bộ sửa `sys.path` thuần, đúng như docstring
của nó hứa.

**Luật rút ra, áp cho mọi lần dời stage sau này:** khối `__main__` **không được chứa logic**.
Nó chỉ được gọi `main()`. Bất cứ thứ gì cần chạy trước khi stage làm việc thì nằm ở đầu
`main()` — nếu không, `run.py` sẽ bỏ qua nó một cách âm thầm.

Lưới mới là `test/test_console_utf8.py`: nó vừa là **arm tương đương** cho
`core/console.py` (chạy cả hai cây qua cùng ma trận `sys.platform`/`sys.stdout` giả rồi so),
vừa canh **wiring** bằng `ast` (`main()` có thật sự gọi helper không, và helper có bị gọi lúc
import không). Đã mutation-check: bỏ cổng `win32` ở một cây bị **2 arm** bắt.
Kiểm end-to-end: `PYTHONIOENCODING=cp1252` chạy cả hai cây trên đồ thị thật đều
**exit 0** và JSON **giống hệt nhau** (chỉ khác `generated_at`).

## 7. `src/` đã bị xoá (2026-07-29) — refactor hoàn tất

Toàn bộ nội dung §1-§6 ở trên là nhật ký lịch sử của quá trình dời — giữ nguyên vì nó ghi
lại đúng cách "Model A" (§4) từng vận hành trong lúc `src/` còn là oracle sống. Sau khi cả
15 stage dời xong (tổng kết ở CLAUDE.md, mục "Active refactor"), Model A đã hết nhiệm vụ:

- `src/data_sync.py` dời sang `esg_kg/core/datasync.py` — file cuối cùng chặn việc xoá.
- Toàn bộ 19 file test "hai cây" (`test_esg_kg_*`, `test_console_utf8.py`,
  `test_standards_audit.py`) được viết lại thành test một cây: bỏ nhánh import `src/` và
  phép so sánh cross-tree, giữ lại (hoặc thay bằng giá trị vàng lấy trực tiếp từ hàm) mọi
  assertion có tuyên bố độc lập thật sự.
- `step10`, `step04b`, `step07b` — ba stage §4 từng liệt là "cố ý không dời, vẫn chạy được
  từ `src/`" — bị **xoá hẳn** cùng lúc với `src/`, không giữ lại làm công cụ độc lập.
  `pipeline.py::STAGES` không còn hàng nào cho chúng.
- `src/` đã bị xoá khỏi repo. Không còn "cây thứ hai" nào để `esg_kg` phải giữ tương đương
  — `esg_kg` bây giờ tự nó là oracle.

Đọc `esg_kg/pipeline.py` (bảng STAGES/BLOCKS thật) và `src/README.md` để biết trạng
thái hiện tại; tài liệu §1-§6 ở trên mô tả LÀM SAO đi tới đây, không phải trạng thái bây giờ.
