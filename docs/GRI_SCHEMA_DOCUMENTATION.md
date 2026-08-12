# The GRI catalog — `config/gri_catalog.json`

**Builder:** `gri/build_gri_catalog.py` (run-once) · **Output:** `config/gri_catalog.json`
· **136 indicator codes**

The international half of the indicator vocabulary. `indicators` (05c) reads it for GRI
node names and pillars, and `config/standard_crosswalk.json` maps Vietnamese TT96
indicators onto it — which is what makes the graph both locally auditable and
internationally comparable.

**Not a pipeline stage.** It reads no pipeline output, so unlike the removed
standards-registry reseed there is no cycle. Rebuild by hand, then commit the regenerated
JSON.

---

## 1. The two-step build

```
gri/crawl_full_gri.py       → gri/full_gri/Full set of GRI Standards - English/   (42 PDFs, ~45 MB)
                            → gri/full_gri/json/                                  (extracted per standard)
gri/build_gri_catalog.py    → config/gri_catalog.json                              (136 codes, flat)
```

The 42 source PDFs are committed to Git. `gri/` is one of two named exceptions to the "no
data files inside code packages" rule, for the same reason as `kpi_build/`: a run-once
provenance builder keeps its sources beside the code so an indicator can be traced back to a
page.

---

## 2. Entry shape

Flat lookup keyed by the full indicator code, standard prefix included:

```jsonc
"GRI 2-1": {
  "gri_standard": "GRI 2",
  "standard_title_en": "General Disclosures 2021",
  "title_en": "Organizational details",
  "title_vi": "Organizational details",
  "pillar": "Quản trị",
  "definition_vi": "Chỉ số công bố GRI 2-1: Organizational details",
  "requirement_type": "Qualitative",
  "units": [],
  "tt96_equivalent": null,
  "versions": [
    { "version_id": "GRI_2_2021", "version_year": 2021,
      "effective_date": "2022-01-01", "status": "Active" }
  ],
  "superseded_by": null,
  "source_pdf": "GRI 2_ General Disclosures 2021.pdf",
  "sha256": "e75728efe274f606031abf775021c6e3c8076ad264b13342d58c0e4a8ef897ea",
  "page": 58
}
```

| Field | Notes |
|---|---|
| `pillar` | Vietnamese labels — `Môi trường` / `Xã hội` / `Quản trị` — so it is directly comparable with the TT96 vocabulary and directly usable by the UI |
| `versions[]` | An array, because GRI standards are revised. `GRI 306` legitimately carries both its 2016 and 2020 versions |
| `superseded_by` | Set when a standard was replaced |
| `source_pdf` / `sha256` / `page` | Per-PDF provenance: which document, which exact file, which page |
| `title_vi` | Falls back to the English title where no Vietnamese rendering exists — visible in the example above |

---

## 3. The ownership rule — the thing that is easy to get wrong

**A GRI standard's JSON does not only describe its own disclosures.** The sector standards
(GRI 11–14) and the 2024/25 rewrites (GRI 101–103) *re-list* disclosures belonging to other
standards.

So a disclosure is attributed to **the standard whose `standard_id` is its prefix** —
`standard_of()` — never to whichever file happens to be read first.

Before that rule existed, `sorted(glob(...))` decided ownership, and `"gri_101"` sorts
before `"gri_2"`. The result: `GRI 2-27` was published carrying **GRI 101 Biodiversity's**
title, PDF, sha256 and version. **80 of 136 entries were mis-attributed** that way and 31
titles were mangled.

The pillar follows from the same decision, which is why the two are one concern: pillar is a
property of the **standard**, read from the source via `PILLAR_MAP`, and never guessed from
the shape of the indicator code. Guessing from the code is exactly the failure mode that hit
the TT96 side — see [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) §5.3.

`test/test_gri_catalog_build.py` pins all of it: prefix-based attribution, pillar from
`PILLAR_MAP`, provenance fields agreeing with the attributed standard, and GRI 306's real
two-version merge still working.

---

## 4. The crosswalk

`tt96_equivalent` in this file is informational. The **authoritative** mapping is
`config/standard_crosswalk.json`, which is hand-edited and carries a review status:

```jsonc
{ "tt96": "TT96-6.1.1",
  "gri": ["GRI 305-1", "GRI 305-2"],
  "gri_name": "Direct (Scope 1) and energy indirect (Scope 2) GHG emissions",
  "confidence": "high",
  "status": "confirmed",
  "note": "Scope 1+2 GHG is the canonical GRI 305-1/305-2 pair." }
```

Currently 23 `confirmed` rows and 4 in `needs_review`. **Only `confirmed` rows become
`equivalentTo` edges.** An unreviewed equivalence would silently let a Vietnamese indicator
answer for a GRI one.

Splitting the crosswalk out of the catalog is the same reasoning as splitting it out of the
KPI definitions file: a catalog is an extraction artifact, a crosswalk is an editorial
judgement with its own review lifecycle.

---

## 5. Rebuilding

```bash
python gri/crawl_full_gri.py         # only if the PDF set changed
python gri/build_gri_catalog.py      # → config/gri_catalog.json
python test/test_gri_catalog_build.py
git add config/gri_catalog.json && git commit
```

Then re-run `indicators` (05c) and compare `quality --label` before and after — GRI node
names and pillars come from this file, so a change is visible in the graph.

`build_gri_catalog.py`'s docstring references `feedback-gri-catalog.md`, a review note that
is no longer in the repository. The rules it demanded are all implemented and pinned by the
test above; the reference is dead, not a pending requirement.

---

## 6. `gri/` layout

```
gri/
├── crawl_full_gri.py                        # downloads and extracts the 42 PDFs
├── build_gri_catalog.py                     # → config/gri_catalog.json
├── full_gri/
│   ├── Full set of GRI Standards - English/ #   42 source PDFs (committed)
│   └── json/                                 #   extracted per standard
├── E/  S/  G/                                # older per-pillar extraction from the 2021 XLSX
├── gri_standards_summary.json                # index for the above
├── gri-content-index-template-2021.xlsx      # the original GRI content-index template
└── README.md
```

The `E/` `S/` `G/` tree and `gri_standards_summary.json` come from an earlier extraction
based on the 2021 content-index spreadsheet (24 standards, 104 disclosures). The
**`full_gri/` PDF route is the current source** for `config/gri_catalog.json`; the older
tree is kept for reference only.
