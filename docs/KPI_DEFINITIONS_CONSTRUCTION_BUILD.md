# The KPI vocabulary — `kpi_definitions_construction.json`

**Builder:** `kpi_build/` (run-once) · **Output:** `kpi_definitions_construction.json` at
the **repo root** (not in `config/`, not in `kpi_build/`) · **35 indicators**

The controlled ESG indicator vocabulary for the Construction / Building Materials / Real
Estate sector, extracted **verbatim** from official Vietnamese sources. Every record
carries a `source` block, so any claim in the graph can be traced back to the regulation
that defines the indicator it is measured under.

Treat this as generated data. It rarely needs rebuilding.

---

## 1. Who consumes it

| Consumer | Use |
|---|---|
| `extract` (01) | The vocabulary in the extraction prompt; a matched KPI arrives already carrying a `TT96-*` / `SSCIFC-*` id |
| `canonicalize` (03c) | Maps free-text `kpi_type` onto these ids as `kpi_id` |
| `indicators` (05c) | Mints the `StandardIndicator` nodes, and reads `pillar` from here |
| `align_claims` (05d) | The candidate indicator list for LLM topic classification |

`core/paths.py` exposes it as `KPI_DEFS_PATH`; four stage files reference it.

---

## 2. Sources and provenance

| Document | Role | Indicators |
|---|---|---|
| **Thông tư 96/2020/TT-BTC**, Phụ lục IV, Mục 6 | The mandatory ESG disclosure backbone for listed firms | 19 (`TT96-6.x.y`) |
| **Quyết định 2171/QĐ-TTg (2021)** | Non-fired building-materials usage target (35–45%) | 1 (`QD2171-1`) |
| **QCVN 09:2017/BXD** | Energy-efficient building compliance (≥ 2,500 m²) | 1 (`QCVN09-1`) |
| **SSC–IFC Sustainability Reporting Guide** | 14 recommended E&S aspects (biodiversity, recycling, OHS, diversity, …) | 14 (`SSCIFC-E*` / `SSCIFC-S*`) |

Exact URLs and SHA-256 hashes are recorded in `kpi_build/sources/manifest.json` and
`manifest_sector.json`.

Circular 96 §6 is **cross-sector** — it applies to every listed firm. The sector
specialization comes from QĐ 2171, QCVN 09 and the SSC-IFC aspects, plus a single combined
`sector` label on every record.

---

## 3. Record shape

```jsonc
{
  "id": "TT96-6.2.2",
  "name": "Tỷ lệ nguyên vật liệu tái chế",
  "definition": "Tỷ lệ phần trăm (%) nguyên vật liệu tái chế trên tổng nguyên vật liệu đầu vào ...",
  "sector": ["Xây dựng - Vật liệu xây dựng - Bất động sản"],
  "pillar": "Môi trường",
  "source": {
    "document": "Thong tu 96/2020/TT-BTC - Phu luc IV ... Muc 6",
    "section": "Mục 6.2 - ...",
    "url": "https://...",
    "excerpt": "Báo cáo tỷ lệ phần trăm nguyên vật liệu được tái chế ..."   // VERBATIM
  }
}
```

The split between `name` and `definition` is deliberate: `name` is a short label for
display and matching, `definition` is a measurable specification with unit hints. **The
exact regulatory wording is retained in `source.excerpt`**, so the curation in
`definition` never destroys the original text.

`pillar` is one of `Môi trường` / `Xã hội` / `Quản trị`. `indicators` (05c) reads it
directly onto the `StandardIndicator` node, and the Evidence View shows it as the claim's
E/S/G column — which is why it comes from here rather than being inferred.

---

## 4. The build

Six sequential scripts, run from `kpi_build/`:

| Stage | Script | Does |
|---|---|---|
| 1 | `01_download_sources.py` | Download Circular 96/2020 + the SSC-IFC guide |
| 2 | `02_extract_section6.py` | Parse Circular 96 Annex IV §6 |
| 3 | `03_download_sector_sources.py` | Download QĐ 2171 + QCVN 09 (mirror fallback + content check) |
| 4 | `04_extract_sector_kpis.py` | Extract the non-fired materials target, the energy-efficiency scope, and the 14 SSC-IFC aspects |
| 5 | `05_build_kpi_definitions.py` | Merge §6 + sector indicators verbatim into the final schema |
| 6 | `06_enrich_kpis.py` | Split short `name` from measurable `definition`; keep verbatim text in `source.excerpt` |

`_inspect_sources.py` and `_inspect_sector.py` only print located text for manual
verification; they are not part of the build.

`kpi_build/` is one of two named exceptions to the repo's "no data files inside code
packages" rule (the other is `gri/`). Both are run-once provenance builders that keep their
sources beside the code, so a claim can be traced back to a page.

---

## 5. Extraction caveats worth knowing

- **Unicode is normalized to NFC.** Some legal portals serve NFD combining diacritics,
  which breaks naive string search.
- **The bilingual Circular 96 template interleaves Vietnamese and English**; §6 parsing
  uses a Vietnamese-diacritic heuristic to split each indicator from its translation.
- **One source OCR artefact is patched** in stage 5 (`lao độngnhằm` → `lao động nhằm`).
- **Some SSC-IFC aspects overlap conceptually with §6 items** (energy, GHG, water). They
  are kept as separate ids rather than merged, because they come from different documents
  with different binding force — and `standard_crosswalk.json` is where equivalences are
  asserted deliberately.

---

## 6. Rebuilding

Only necessary when a source document changes or a new instrument is added. Run the six
scripts in order, then:

1. `python test/test_temporal_invariants.py` — the `kpi_id` canonicalization arm reads this
   file;
2. `python test/test_indicator_axis.py` — the axis stage reads `pillar` and `id` from it;
3. re-run `canonicalize` (03c) and `indicators` (05c), then `quality --label` before/after.

Adding an indicator id without re-running 03c leaves it with no measurements attached.

---

## 7. Related

- [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) — how the vocabulary becomes
  graph structure
- [GRI_SCHEMA_DOCUMENTATION.md](GRI_SCHEMA_DOCUMENTATION.md) — the GRI side and the
  crosswalk
- `kpi_build/README.md` — package-level usage
- [ROADMAP.md](ROADMAP.md) §2.6 — the regulatory properties the schema still cannot express
