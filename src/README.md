# src/ — the pipeline (refactor hoàn tất; cây phẳng `stepNN_*.py` cũ đã xoá 2026-07-29)

> **Lưu ý khi đọc (thêm 2026-07-30):** thư mục này **từng tên là `src_module/`**, đổi
> thành `src/` sau khi đợt refactor khép lại và cái tên cũ được giải phóng. Trong phần
> lịch sử bên dưới (và trong `PIPELINE.md`/`DESIGN.md`/`docs/`), `src/` trơ trọi nghĩa là
> **cây phẳng cũ** — mỗi stage một file `stepNN_*.py` — đã bị xoá, KHÔNG phải thư mục này.
> Không còn file `src/stepNN_*.py` nào tồn tại; lệnh chạy thật đều là `python src/run.py <stage>`.

Đích đến của đợt refactor: **15/15 stage đã dời**, và cây phẳng cũ — pipeline từng là
bản đang chạy thật trong suốt đợt refactor — **đã bị xoá**. `esg_kg` là cây duy nhất
còn lại. Phần lịch sử bên dưới (và trong PIPELINE.md/DESIGN.md) mô tả quá trình dời
từng stage một, không big-bang — giữ nguyên vì đó là ghi chép có thật về cách tính
tương đương được chứng minh, dù cây cũ không còn tồn tại để đối chiếu nữa.

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
python src/run.py --list                      # mọi stage + đã dời hay chưa
python src/run.py quality --label baseline    # chạy stage (từ REPO ROOT)
cd src && python -m esg_kg.report.quality --label baseline   # tương đương
```

`run.py` là file duy nhất chạm `sys.path`, và đọc bảng stage từ `pipeline.py` nên
`--list` luôn nói thật. **Không cần `pip install`.** Đường dẫn output neo theo
`REPO_ROOT` (marker-based) nên không phụ thuộc cwd. Lý do chọn cách này: DESIGN.md §3.

Bảng phân biệt **hai** trạng thái (từng là ba, khi `src/` còn tồn tại và có trạng thái
"chưa dời"): `ready` (15/15 stage) và `(removed)` — ba stage **cố ý không dời rồi bị xoá
hẳn** (`step10`, `step04b`, `step07b`), bị loại khỏi mẫu số vì nếu tính vào thì tiến độ
migrate vĩnh viễn không thể đạt 100%.

## Cách làm việc

Test-first, luôn luôn (xem CLAUDE.md → "Working rule: Test-Driven Development").
Mỗi module `core/` mới **phải có arm trong `test/test_esg_kg_equivalence.py` trước
khi được trích** — thêm arm, chạy, thấy đỏ, rồi mới viết code. Với một **stage**,
arm so ba thứ: hằng số module, từng hàm, và output đã render.

```bash
python test/test_esg_kg_equivalence.py    # regression: core/paths+schema+naming+dates+graph_patch, report/quality, resolve/indicators
python test/test_esg_kg_anchor_kpi.py     # lát cắt step03b: core/identity + graph/anchor_kpi
python test/test_esg_kg_provenance.py     # lát cắt step05b: resolve/provenance
python test/test_esg_kg_llm.py            # lát cắt core/llm: throttle + hình dạng request đã trả tiền
python test/test_esg_kg_fix_triples.py    # lát cắt step03: corpus thật + pha 2 bằng LLM giả
python test/test_esg_kg_validated_block.py # KHỐI 03→03b→03c: "ghi đúng 1 lần", cache pha 2
python test/test_esg_kg_align_claims.py    # lát cắt step05d: nhánh LLM bắt buộc, chạy bằng provider giả
python test/test_esg_kg_crosscheck.py      # lát cắt step07: đòn bẩy lớn nhất, mở khoá 08
python test/test_esg_kg_issuer.py          # lát cắt step04: ghi file TRACKED + sửa tay, arm dùng workspace tạm
python test/test_esg_kg_extract.py         # lát cắt step01: hub cuối cùng, cho ra core/io_jsonl
python test/test_esg_kg_neo4j_load.py      # lát cắt step06: stage GHI Neo4j thứ hai, stub execute_write
python test/test_esg_kg_neo4j_sync.py      # lát cắt step08: stage NEO4J đầu tiên dời, stub GraphDatabase
python test/test_esg_kg_claim_ledger.py    # lát cắt step09: stage ĐỌC Neo4j đầu tiên, driver giả trả dữ liệu
python test/test_esg_kg_entities.py        # lát cắt step05: hàm resolve_graph() thuần + stub trên google.genai.Client
python test/test_esg_kg_resolve_block.py   # KHỐI 05→05b→05c: "ghi đúng 1 lần", cache Stage C
python test/test_esg_kg_datasync.py        # esg_kg.core.datasync: pull scope, push --dry-run
python test/test_step02_language_guard.py  # issue #6: prompt tiếng Việt, đỏ trên prompt chưa sửa
python test/test_esg_kg_extract_triples.py # lát cắt step02: stage cuối cùng, client giả truyền trực tiếp
python test/test_pipeline_table.py        # bảng STAGES/BLOCKS + run.py --list nói thật
python test/test_temporal_invariants.py   # P3/P4 temporal logic, esg_kg-only
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
| `core/io_jsonl.py` | ✅ 5 helper JSONL thuần (`load_pages_from_jsonl`, `build_page_text`, `page_has_esg`, `select_documents`, `parse_company_year_from_filename`), rơi ra từ lát cắt `01` — đúng 5 symbol mà `step02` cần. **Không còn module `core/` nào chặn stage nào khác** (PIPELINE.md §2.1) |
| `report/quality.py` | ✅ stage đầu tiên được dời (từ `step00`), chạy được |
| `kpi/extract.py` | ✅ dời từ `step01` (2026-07-28), hub thật sự cuối cùng của cả đợt; không dùng `_Provider`/`_OpenAIProvider` (không có Gemini provider để trích), nên `KPIExtractor`/prompt/JSON schema ở lại stage, chỉ 5 helper JSONL dời (→ `core/io_jsonl.py`). Nhánh trả tiền: stub tiêm thẳng lên `google.genai.Client`. Test: `test/test_esg_kg_extract.py` (10 nhóm) |
| `kpi/canonicalize.py` | ✅ dời từ `step03c`; arm so **5 214 KPIObservation thật** giữa hai cây |
| `resolve/entities.py` | ✅ dời từ `step05` (2026-07-29), stage **thứ mười bốn**; leaf xác nhận (mọi symbol đã ở `core/`), một dead import `load_schema_sets` bị bỏ. `resolve()` tách thành `resolve_graph()` (hàm thuần, không I/O) + `main()`, ngay lúc dời (không phải làm thêm sau như `fix_triples`), để khối `build_resolved` gọi thẳng. Nhánh trả tiền (Stage B embed + Stage C adjudicate) stub trên `google.genai.Client`. Test riêng: `test/test_esg_kg_entities.py` (7 nhóm) |
| `resolve/indicators.py` | ✅ dời từ `step05c`; diff 15+/115− **0 dòng logic mới**; arm dựng lại 67 chỉ số + 1 346 cạnh trên đồ thị thật đã strip. **Sửa thêm 2026-07-29**: tách `link_indicator_axis()` khỏi `run()` (hàm thuần, không I/O) để khối `build_resolved` gọi thẳng — trích nguyên văn, 0 dòng logic đổi, `test/test_indicator_axis.py` xanh không cần sửa |
| `graph/anchor_kpi.py` | ✅ dời từ `step03b` (2026-07-27); diff 17+/20− **0 dòng logic**; arm dựng lại 95 anchor trên corpus đã strip + nhánh hub-guard + idempotency. Test riêng: `test/test_esg_kg_anchor_kpi.py` |
| `resolve/provenance.py` | ✅ dời từ `step05b` (2026-07-27); diff 18+/8− **0 dòng logic** — stage đầu tiên dời mà **không phải trích thêm `core/`** nào; arm so 6 258 dấu trên đồ thị thật + arm strip chứng minh stage không đọc output của chính nó + fixture nhánh `extraction`. Test riêng: `test/test_esg_kg_provenance.py` |
| `graph/fix_triples.py` | ✅ dời từ `step03` (2026-07-28); stage **thứ hai** dời mà không phải trích thêm `core/`. Nó *trông* như hub (7 stage import) nhưng mọi symbol chúng lấy đã ở `core/dates`+`core/schema` ⇒ thực chất là leaf — **"hub" phải kiểm bằng CHIỀU import**. Arm corpus thật (14 492 validated + 1 036 unfixable) không cần `strip_*` vì stage không bao giờ gặp output của chính nó; pha 2 (trả tiền) có arm bằng LLM giả. Test riêng: `test/test_esg_kg_fix_triples.py` |
| `graph/build_validated.py` | ✅ **KHỐI** `03 → 03b → 03c` (2026-07-28) — không phải stage, **không có bản `src/`** nên không tính vào mẫu số. Nối chuỗi in-memory, ghi `all_validated_triples.json` **1 lần**; `src/` giữ nguyên 3 stage và làm **oracle**. Pha 2 cache theo *nội dung* triple ⇒ chạy lại **0 lời gọi LLM**. Test riêng: `test/test_esg_kg_validated_block.py` (DESIGN.md §5.7) |
| `resolve/align_claims.py` | ✅ dời từ `step05d` (2026-07-28); stage thứ **ba** dời mà không phải trích thêm `core/` — lát cắt `05c` đã đẩy `GraphPatch`/`temporal_md` lên kernel *chính vì* file này import chúng từ một stage. Stage **bắt buộc có LLM** — `--dry-run` return trước khi provider được dựng, nên nhánh đắt được phủ bằng **provider giả tiêm vào cả hai cây** (tất định theo CRC của prompt). Ở NGOÀI khối `build_resolved` (§3.2b) — chạy sau, không đổi. Test riêng: `test/test_esg_kg_align_claims.py` (14 nhóm) |
| `crosscheck/claims_vs_conduct.py` | ✅ dời từ `step07` (2026-07-28), stage thứ **tám** — đòn bẩy lớn nhất trước khi dời: stage DUY NHẤT còn chặn ai đó (`08` chờ `node_text`, `10` chờ `Adjudicator`). `_Provider`/`_OpenAIProvider` nay import NGƯỢC từ `core.llm` — đúng hai lớp mà slice đó đã trích TỪ CHÍNH file này ngày 2026-07-27; `Adjudicator` cố ý ở lại stage (prompt + parse verdict + cascade — logic, không phải kernel). Khác `05d`, `--dry-run` ở đây KHÔNG return trước khi dựng provider (chỉ bỏ ghi file cuối) nên arm dry-run cũng là kiểm tương đương thật. Không đọc lại output của chính nó (ghi khác thư mục) nên PIPELINE.md §3 không áp dụng. Test riêng: `test/test_esg_kg_crosscheck.py` (21 nhóm) |
| `registry/issuer.py` | ✅ dời từ `step04` (2026-07-28), stage **thứ chín**; hub *trông* như còn nhưng đã tan từ trước (6 stage `src/` chỉ lấy `normalize_name`/`name_tokens`/`merge_preserving_edits`, cả ba đã ở `core/naming` — bản thân stage chỉ import `REPO_ROOT`). AST-diff: **11 hàm chung, 0 hàm khác một byte** (`main()` chỉ đổi 1 dòng thông báo, trỏ sang `build_validated` thay vì `step03…`), 3 hàm bị xoá đúng là 3 hàm đã có trong `core/naming`. Hoàn toàn offline — không LLM, không Neo4j — nhưng ghi `config/issuer_registry.json`, một file **tracked trong Git và có sửa tay của người**, nên MỌI arm gọi `build()` phải ghi ra workspace tạm, không bao giờ chạm bản thật; có arm riêng khẳng định điều đó (`test_build_never_touches_the_real_tracked_registry`) và một arm mô phỏng người di chuyển một `needs_review` sang `exclusions` rồi chạy lại để chứng minh `merge_preserving_edits` giữ đúng bản sửa ở cả hai cây. Một commit riêng theo sau xoá nhánh sniff `{nodes,edges}` chết mà DESIGN.md §5.2 đã ghi từ 2026-07-25 — **cả hai cây cùng lúc**, red-first (bug tồn tại ở cả hai, không phải một cây lệch cây kia). Test riêng: `test/test_esg_kg_issuer.py` (12 nhóm) |
| `registry/standards.py` | 🗑️ **không tồn tại** — `step04b` đọc output của `step05` (vòng lặp) và lần quét đồ thị đóng góp 0; registry thành config tĩnh (hand-edited), `step00` audit độ phủ (DESIGN.md §4.2). Xoá hẳn cùng `src/` (2026-07-29), không phải "chưa dời" |
| `load/neo4j_load.py` | ✅ dời từ `step06` (2026-07-29) — leaf từ trước, nhưng stage GHI Neo4j **thứ hai**: client surface rộng hơn `08` (`session.execute_write` + đọc lại `.single()`), nên fake session/tx phải đỡ cả hình dạng gọi lẫn hình dạng đọc. Arm mạnh nhất: `build_payload()` thuần hàm trên corpus thật + 76 lệnh Neo4j giống hệt byte-for-byte giữa hai cây. Test riêng: `test/test_esg_kg_neo4j_load.py` (5 nhóm) |
| `load/neo4j_sync.py` | ✅ dời từ `step08` (2026-07-29) — leaf, nhưng stage NEO4J **đầu tiên** dời: không có lớp `_Provider` trước driver Neo4j thật, nên stub thế chỗ thẳng `neo4j.GraphDatabase` (đúng kỹ thuật `google.genai.Client` ở `01`). Driver giả chỉ ghi lại Cypher + tham số; arm so 5 lệnh giống hệt byte-for-byte trên corpus thật (1 093 dossier). `node_text` trap giữ đúng lần thứ ba. Test riêng: `test/test_esg_kg_neo4j_sync.py` (8 nhóm) |
| `report/claim_ledger.py` | ✅ dời từ `step09` (2026-07-29) — stage ĐỌC Neo4j **đầu tiên**, khác `06`/`08` vốn chỉ ghi: fake driver phải TRẢ DỮ LIỆU GIẢ (hàng đợi 4 bộ, đúng thứ tự 4 lần `s.run()`), không chỉ ghi lại lời gọi. Stage đầu tiên KHÔNG có arm corpus thật trên đĩa (chỉ đọc Neo4j, không file JSON nào). Test riêng: `test/test_esg_kg_claim_ledger.py` (10 nhóm) |
| `resolve/build_resolved.py` | ✅ **KHỐI** `05 → 05b → 05c` (2026-07-29) — không phải stage, **không có bản `src/`** nên không tính vào mẫu số. Nối chuỗi in-memory, ghi `resolved_graph.json` **1 lần**; `src/` giữ nguyên 3 script và làm **oracle** (`step05(--no-llm) → step05b → step05c`, so ra 10 425 node / 14 387 cạnh giống hệt). `05d` KHÔNG nằm trong khối — vẫn là stage tuỳ chọn chạy sau, không đổi. Cache chỉ bọc Stage C (adjudication LLM); Stage B (embedding) cố ý không cache — xem docstring của file. Test riêng: `test/test_esg_kg_resolve_block.py` (5 nhóm, DESIGN.md §5.7, PIPELINE.md §3.2b) |
| `graph/extract_triples.py` | ✅ dời từ `step02` (2026-07-29), stage **thứ mười lăm và cuối cùng** — khép lại đợt refactor. Hai commit riêng: (1) prompt fix issue #6 land trong `src/` trước (thêm mục `## OUTPUT LANGUAGE` vào cả hai template, sửa lại ví dụ mẫu đang mô hình hoá lỗi dịch/khử dấu; test `test/test_step02_language_guard.py`), (2) dời thuần túy sau. Leaf xác nhận — mọi symbol đã ở `core/` (`io_jsonl`, `llm`, `schema`, `identity`); hàm trùng `schema_sets()` bị **xoá**, thay bằng `core.schema.load_schema_sets` (bỏ `edge_directions`, không dùng ở stage này). Khác `01`, step02 không tự dựng client — `call_llm`/`process_page`/`process_document` nhận `client` như tham số thuần, nên stub trả tiền trong test là một client giả truyền thẳng vào, không phải monkeypatch. Test riêng: `test/test_esg_kg_extract_triples.py` (12 nhóm) |
| `step07b` (softmax) | 🗑️ **không tồn tại** — UI `frontend/`+`api/` không đọc `assessment_scores`/`score_components`; xoá hẳn cùng `src/` (2026-07-29), không phải "chưa dời" |

`src/` **đã bị xoá** (2026-07-29) — **15/15** stage chạy được từ `esg_kg` **cộng hai
khối** `build_validated` + `build_resolved`; không còn stage nào đang chờ dời, và không
còn cây thứ hai để đối chiếu. `run.py --list` là nguồn sự thật. `step10`/`step04b`/
`step07b` không có hàng trong bảng — cả ba bị xoá hẳn, không phải "cố ý không dời"
(xem ghi chú trong `pipeline.py`).
