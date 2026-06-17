# KPI definition builder — Construction / Building Materials / Real Estate

Reproducible pipeline that **downloads official Vietnamese ESG sources and
extracts** a sector-tailored KPI definition dataset, replacing the generic
`kpi_definitions.json`. No KPI text is hand-written — every record is taken
verbatim from a source document and carries a `source` block.

Output: `../kpi_definitions_construction.json` (35 KPIs).

## Pipeline

| Stage | Script | What it does | Produces |
|------|--------|--------------|----------|
| 1 | `01_download_sources.py` | Download Circular 96/2020 + SSC-IFC guide | `sources/*.html/.pdf`, `manifest.json` |
| 2 | `02_extract_section6.py` | Parse Circular 96 Annex IV §6 (ESG report) | `sources/extracted_section6.json` |
| 3 | `03_download_sector_sources.py` | Download QĐ 2171 + QCVN 09 (mirror fallback + content check) | `sources/*.html`, `manifest_sector.json` |
| 4 | `04_extract_sector_kpis.py` | Extract non-fired materials target, energy-efficiency scope, SSC-IFC 14 aspects | `sources/extracted_sector.json` |
| 5 | `05_build_kpi_definitions.py` | Merge §6 + sector indicators (verbatim) into the final schema | `../kpi_definitions_construction.json` |
| 6 | `06_enrich_kpis.py` | Split short `name` vs measurable `definition` (with units); keep verbatim text in `source.excerpt` | `../kpi_definitions_construction.json` (rewritten) |

Helpers `_inspect_sources.py` / `_inspect_sector.py` only print located text for
manual verification; they are not part of the build.

### Run everything
```bash
python 01_download_sources.py
python 02_extract_section6.py
python 03_download_sector_sources.py
python 04_extract_sector_kpis.py
python 05_build_kpi_definitions.py
python 06_enrich_kpis.py
```

## Sources (provenance)

| Document | Role | KPIs |
|----------|------|------|
| **Thông tư 96/2020/TT-BTC, Phụ lục IV, Mục 6** (Cong bao / Phu luc IV) | Mandatory ESG disclosure backbone for listed firms | 19 (`TT96-6.x.y`) |
| **Quyết định 2171/QĐ-TTg (2021)** | Non-fired building-materials usage target (35–45%) | 1 (`QD2171-1`) |
| **QCVN 09:2017/BXD** | Energy-efficient building compliance (≥2500 m²) | 1 (`QCVN09-1`) |
| **SSC–IFC Sustainability Reporting Guide** | 14 recommended E&S aspects (biodiversity, recycling, OHS, diversity…) | 14 (`SSCIFC-E*/S*`) |

Exact URLs + sha256 hashes are recorded in `sources/manifest.json` and
`sources/manifest_sector.json`.

## Output schema

Each record (compatible with `1-kpi-extraction.py`, which reads `id`, `name`,
`definition`, `sector`; `pillar` and `source` are extra/ignored). After Stage 6,
`name` is a short label and `definition` is a measurable spec with unit hints; the
**verbatim source text is kept in `source.excerpt`** for audit:

```json
{
  "id": "TT96-6.2.2",
  "name": "Tỷ lệ nguyên vật liệu tái chế",
  "definition": "Tỷ lệ phần trăm (%) nguyên vật liệu tái chế trên tổng nguyên vật liệu đầu vào ...",
  "sector": ["Xây dựng - Vật liệu xây dựng - Bất động sản"],
  "pillar": "Môi trường",
  "source": {
    "document": "...", "section": "Mục 6.2 - ...", "url": "...",
    "excerpt": "Báo cáo tỷ lệ phần trăm nguyên vật liệu được tái chế ..."  // verbatim
  }
}
```

## Notes & caveats

- Vietnamese is normalised to **NFC** (some legal portals serve NFD combining
  diacritics, which breaks naive string search).
- The bilingual Circular 96 template interleaves VN/EN; §6 parsing uses a
  Vietnamese-diacritic heuristic to split each indicator from its translation.
- One source OCR artefact is patched in Stage 5 (`lao độngnhằm` → `lao động nhằm`).
- Circular 96 §6 is **cross-sector** (applies to all listed firms); sector
  specialisation comes from QĐ 2171, QCVN 09 and the SSC-IFC aspects, plus the
  single combined `sector` label.
- Stage 6 definitions are **curated, source-anchored** metric specs (units added
  per common ESG reporting practice). The exact regulatory wording is retained in
  `source.excerpt`, so nothing extracted is lost.
- Some SSC-IFC aspects overlap conceptually with §6 items (energy, GHG, water,
  community). They are kept with distinct ids/sources as multi-source
  corroboration; prune in Stage 6's `ENRICH` map if you prefer a minimal set.

## Wiring into the extraction pipeline

`EmeraldMind/` is a **read-only reference project — do not edit it.** Use this
dataset from your own working copy of the pipeline:

```bash
python <your-copy>/1-kpi-extraction.py -r <reports_dir> -k ../kpi_definitions_construction.json
```
For sector filtering to engage (instead of falling back to "use all KPIs"), add
the label to the `SECTORS` list in `detect_company_and_sector` **in your own copy**:
```python
SECTORS = [
    "Xây dựng - Vật liệu xây dựng - Bất động sản",   # <-- add this
    ...
]
```
Or hardcode `sector = "Xây dựng - Vật liệu xây dựng - Bất động sản"` for a
single-sector corpus.
