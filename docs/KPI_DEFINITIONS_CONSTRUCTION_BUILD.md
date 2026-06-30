# Building `kpi_definitions_construction.json`

This document explains, in detail, how the sector‑tailored KPI definition file
`kpi_definitions_construction.json` (35 KPIs for **Construction / Building
Materials / Real Estate**) is constructed from official Vietnamese regulatory
sources by the reproducible pipeline under [`kpi_build/`](../kpi_build/).

## 1. What this file is and why it is built

`kpi_definitions_construction.json` is the **controlled vocabulary (taxonomy) of
ESG indicators** consumed by the extraction pipeline. It is **not** the knowledge‑graph
schema — node classes and edge labels live in `EmeraldMind/schemas/schema.json`.
Instead, each record here defines one allowed value (and its meaning) for the
`kpi_type` property of a `KPIObservation` node.

- **Design rule:** *no KPI text is hand‑invented.* Every record is derived verbatim
  from a source document and carries a `source` block recording where it came from.

## 2. Source documents (provenance)

| Document | Role | KPIs | ID prefix |
|----------|------|------|-----------|
| **Thông tư 96/2020/TT‑BTC, Phụ lục IV, Mục 6** | Mandatory ESG disclosure backbone for listed firms (cross‑sector) | 19 | `TT96-6.x.y` |
| **Quyết định 2171/QĐ‑TTg (2021)** | Non‑fired building‑materials usage target (35–45%) | 1 | `QD2171-1` |
| **QCVN 09:2017/BXD** | Energy‑efficient building compliance (≥ 2500 m²) | 1 | `QCVN09-1` |
| **SSC–IFC Sustainability Reporting Guide** | 14 recommended E&S aspects (biodiversity, recycling, OHS, diversity…) | 14 | `SSCIFC-E*` / `SSCIFC-S*` |

Sector specialisation comes from QĐ 2171, QCVN 09 and the SSC‑IFC aspects; Circular 96
§6 is cross‑sector but forms the regulatory backbone. Exact URLs + sha256 hashes are
recorded in `sources/manifest.json` and `sources/manifest_sector.json`.

## 3. Pipeline overview

The build is six ordered scripts in `kpi_build/`. Stages 1–4 **download and extract
verbatim** (no LLM, fully auditable); stages 5–6 **merge and shape** into the final schema.

```
01_download_sources.py ─┐
02_extract_section6.py  ─┼─► sources/extracted_section6.json ─┐
03_download_sector_sources.py ─┐                              │
04_extract_sector_kpis.py ─────┴─► sources/extracted_sector.json ─┤
                                                                  ▼
                          05_build_kpi_definitions.py ──► kpi_definitions_construction.json
                                                                  │
                          06_enrich_kpis.py ──────────► (rewritten in place)
```

| Stage | Script | What it does | Produces |
|-------|--------|--------------|----------|
| 1 | `01_download_sources.py` | Download Circular 96/2020 (2 mirrors) + SSC‑IFC guide | `sources/*.html/.pdf`, `manifest.json` |
| 2 | `02_extract_section6.py` | Parse Circular 96 Annex IV §6 into mandated indicators | `sources/extracted_section6.json` |
| 3 | `03_download_sector_sources.py` | Download QĐ 2171 + QCVN 09 (mirror fallback + content check) | `sources/*.html`, `manifest_sector.json` |
| 4 | `04_extract_sector_kpis.py` | Extract non‑fired materials target, energy‑efficiency scope, SSC‑IFC 14 aspects | `sources/extracted_sector.json` |
| 5 | `05_build_kpi_definitions.py` | Merge §6 + sector indicators (verbatim) into final schema | `kpi_definitions_construction.json` |
| 6 | `06_enrich_kpis.py` | Split short `name` vs measurable `definition` (with units); keep verbatim text in `source.excerpt` | `kpi_definitions_construction.json` (rewritten) |

Helpers `_inspect_sources.py` / `_inspect_sector.py` only print located text for manual
verification; they are **not** part of the build.

## 4. Stage‑by‑stage detail

### Stage 1 — `01_download_sources.py` (download core sources)

- Downloads three documents declared in the `SOURCES` list: the Circular 96 original
  (Công báo), the Circular 96 Annex IV **template** (LuatMinhKhue lookup copy), and the
  SSC‑IFC sustainability‑reporting PDF.
- Uses **browser‑like headers** — government/legal portals reject the default
  `python-requests` user agent with HTTP 403.
- Each file is saved verbatim into `sources/`, and a manifest record captures the URL,
  HTTP status, byte count and **sha256 hash** for reproducibility/auditability.

> Output: `sources/TT96_2020_congbao.html`, `sources/TT96_2020_phuluc4.html`,
> `sources/SSC_IFC_sustainability_guide.pdf`, `sources/manifest.json`.

### Stage 2 — `02_extract_section6.py` (parse Circular 96 §6)

The Annex IV annual‑report template lists, sub‑section by sub‑section, exactly which
E&S indicators a listed company must disclose. This stage slices §6 out and parses every
mandated indicator.

1. **`html_to_text`** — flatten the template HTML to text (BeautifulSoup).
2. **`slice_section6`** — cut from the §6 heading *"Báo cáo tác động liên quan đến môi
   trường và xã hội"* up to the closing *"Lưu ý/Note"* paragraph after item 6.8.
3. **Bilingual split** — the template interleaves `<Vietnamese>/<English>` on one line.
   Because Vietnamese carries tone marks/special letters (`VI_CHARS`) the English
   translation lacks, `is_vietnamese()` + `vi_indicators()` cut the Vietnamese indicator
   out of each `/`‑separated unit.
4. **`parse_section6`** — locate each `6.x.` header, map it to a known subsection title
   (`SUBSECTION_TITLES`, 6.1–6.8), and emit one structured item per indicator with
   `subsection`, `subsection_title`, `index_in_subsection`, and the Vietnamese text `vi`.

> Output: `sources/extracted_section6.json` (≈19 indicators) + a `.txt` dump of the raw §6 block.

### Stage 3 — `03_download_sector_sources.py` (download sector sources)

- Downloads the two sector documents in `SECTOR_SOURCES`: **QĐ 2171/QĐ‑TTg** and
  **QCVN 09:2017/BXD**.
- Each source lists **mirror URLs in priority order**. Some legal portals return HTTP 403
  to scripts; others return only navigation boilerplate. `fetch_first_ok()` saves the
  first mirror that returns HTTP 200 **and** whose page text actually contains a required
  `must_contain` needle (e.g. `"tổng số vật liệu xây"`), guaranteeing the real document
  body was fetched rather than a stub.
- Vietnamese text is normalised to **NFC** before the content check (some portals serve
  NFD combining diacritics, which breaks naive string search).
- The SSC‑IFC guide is already present from Stage 1, so it is not re‑downloaded here.

> Output: `sources/QD_2171_2021.html`, `sources/QCVN_09_2017.html`, `sources/manifest_sector.json`.

### Stage 4 — `04_extract_sector_kpis.py` (extract sector indicators)

Extracts sector‑specific KPI content verbatim (all text NFC‑normalised):

- **`extract_qd2171`** — regex‑locates the specific‑target sentence under *"b) Mục tiêu
  cụ thể"* (the 35–40% / 40–45% non‑fired‑materials target) → one item `QD2171-1`.
- **`extract_qcvn09`** — regex‑locates the scope sentence under *"Mục 1.1 — Phạm vi điều
  chỉnh"* (buildings ≥ 2500 m²) → one item `QCVN09-1`.
- **`extract_ssc_ifc_aspects`** — the SSC‑IFC guide renders the recommended aspects as a
  two‑column table (Môi trường | Xã hội). The code slices between *"Tiết kiệm năng lượng"*
  and *"Thông tin được công bố"*, drops the column headers, and de‑interleaves alternating
  lines into environmental (`SSCIFC-E1..E7`) and social (`SSCIFC-S1..S7`) items.

Each item carries `source_id`, `pillar`, `name`, the verbatim `vi`, and a `source` block.

> Output: `sources/extracted_sector.json` (16 indicators: 1 + 1 + 14).

### Stage 5 — `05_build_kpi_definitions.py` (merge into final schema)

Merges Stage 2 + Stage 4 outputs into the final record schema:

- **`build_circular96`** — for each §6 item, builds id `TT96-{subsection}.{index}`, a
  short `name` (via `short_name`, which strips *"Báo cáo liên quan đến…"* prefixes),
  a `definition` (= verbatim `vi`), the single `sector` label, a `pillar`
  (`PILLAR_BY_SUBSECTION`: 6.1–6.5 → Môi trường, 6.6–6.7 → Xã hội, 6.8 → Quản trị), and
  a `source` block.
- **`build_sector`** — passes through the Stage‑4 items (QĐ 2171, QCVN 09, SSC‑IFC) into
  the same record shape, keeping their own `source_id` as `id`.
- **`fix`** — patches a known OCR artefact (`"Chính sách lao độngnhằm"` →
  `"Chính sách lao động nhằm"`).
- **Sanity assertion** — `id`s must be unique (the pipeline uses `id` as the `kpi_type`
  token), so a duplicate aborts the build.

> Output: `kpi_definitions_construction.json` (35 records). At this point `definition`
> is the verbatim regulatory wording.

### Stage 6 — `06_enrich_kpis.py` (make extraction‑ready)

Regulations state *topics to disclose*, but the extractor needs *metrics to measure*.
Several verbatim rows are too thin to drive numeric extraction (e.g. `"Tái chế"`). This
stage attaches a curated, source‑anchored **measurable definition** to every KPI:

- A hardcoded `ENRICH` map (`id → (short name, measurable definition with unit hints)`)
  rewrites `name` and `definition`. Units reflect common ESG reporting practice
  (tCO2e, m³, kWh, %, VND, giờ/người, số vụ…).
- **The original verbatim text is preserved** in `source.excerpt` on first run and never
  overwritten — so nothing extracted is lost and provenance is auditable.
- **Idempotent:** re‑running re‑applies the map without corrupting `source.excerpt`.
- **Coverage assertions:** every KPI `id` must have exactly one `ENRICH` entry and vice
  versa, so the map cannot silently drift out of sync with Stage 5.

> Output: `kpi_definitions_construction.json` rewritten in place — final form.

## 5. Final record schema

After Stage 6, each record has a short `name` label, a measurable `definition` with unit
hints, and the verbatim regulatory text retained in `source.excerpt`:

```json
{
  "id": "TT96-6.2.2",
  "name": "Tỷ lệ nguyên vật liệu tái chế",
  "definition": "Tỷ lệ phần trăm (%) nguyên vật liệu tái chế trên tổng nguyên vật liệu đầu vào dùng để sản xuất sản phẩm, dịch vụ chính.",
  "sector": ["Xây dựng - Vật liệu xây dựng - Bất động sản"],
  "pillar": "Môi trường",
  "source": {
    "document": "Thong tu 96/2020/TT-BTC - Phu luc IV ...",
    "section": "Mục 6.2 - Quản lý nguồn nguyên vật liệu",
    "url": "https://luatminhkhue.vn/...",
    "excerpt": "Báo cáo tỷ lệ phần trăm nguyên vật liệu được tái chế ..."   // verbatim
  }
}
```

| Field | Used by `1-kpi-extraction.py`? | Meaning |
|-------|:--:|---------|
| `id` | ✅ | Stable token; becomes `KPIObservation.kpi_type` in the graph. Must be unique. |
| `name` | ✅ | Short human label (injected into prompt). |
| `definition` | ✅ | Measurable spec with unit hints (injected into prompt). |
| `sector` | ✅ | Sector filter key (`get_sector_view`). |
| `pillar` | ⬜ | E/S/G classification metadata (Môi trường / Xã hội / Quản trị). |
| `source` | ⬜ | Provenance + verbatim `excerpt` for audit. |

## 6. Reproducing the build

```bash
cd kpi_build
python 01_download_sources.py
python 02_extract_section6.py
python 03_download_sector_sources.py
python 04_extract_sector_kpis.py
python 05_build_kpi_definitions.py
python 06_enrich_kpis.py
```

Dependencies: `requests`, `beautifulsoup4`, `PyMuPDF` (`fitz`).

## 7. Notes & caveats

- **NFC normalisation** is applied throughout; some legal portals serve NFD combining
  diacritics that break naive search.
- The bilingual Circular 96 template requires a **Vietnamese‑diacritic heuristic** to
  split each indicator from its English translation; layout changes upstream could break
  Stage 2 parsing.
- Stage 6 definitions are **curated, source‑anchored** metric specs (units added per ESG
  practice). The exact regulatory wording is retained in `source.excerpt`.
- Some SSC‑IFC aspects overlap conceptually with §6 items (energy, GHG, water, community).
  They are kept with distinct ids/sources as multi‑source corroboration; prune in Stage 6's
  `ENRICH` map for a minimal set.
- **Wiring into extraction:** for sector filtering to engage (instead of falling back to
  "use all KPIs"), the label `"Xây dựng - Vật liệu xây dựng - Bất động sản"` must be added
  to the `SECTORS` list in `detect_company_and_sector` in `1-kpi-extraction.py` (the
  hardcoded list there is otherwise English‑only and never emits this sector). Per the
  `kpi_build/README.md`, treat `EmeraldMind/` as a read‑only reference and apply that edit
  in your own working copy:
  ```bash
  python <your-copy>/1-kpi-extraction.py -r <reports_dir> -k kpi_definitions_construction.json
  ```

## 8. Related docs

- [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) — the KG node/edge schema that consumes `kpi_type`.
- [`kpi_build/README.md`](../kpi_build/README.md) — the build pipeline's own README.
