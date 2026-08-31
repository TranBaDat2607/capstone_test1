# Notice on third-party materials

The MIT licence in [`LICENSE`](LICENSE) covers **the source code of this project only** —
the Python packages, configuration, tests and documentation authored by the project team.

It does **not** license the third-party material this project reads, cites or derives from.
Those retain their own terms, and you are responsible for obtaining them under those terms.

## GRI Standards

`config/gri_catalog.json` and `gri/full_gri/json/` are **derived metadata** — standard
identifiers, disclosure titles, pillar classifications, page counts and SHA-256 checksums.
They contain no verbatim body text of any GRI Standard.

The GRI Standards PDFs themselves are **copyright Global Reporting Initiative** and are
**not distributed with this repository**. To rebuild the catalog, download the "Full set of
GRI Standards" yourself from <https://www.globalreporting.org/> under GRI's terms and place
the PDFs as described in [`gri/README.md`](gri/README.md). The per-PDF `sha256` recorded in
`gri/full_gri/json/` lets you verify your copies match the ones used to build the committed
catalog.

## Vietnamese regulatory documents

`kpi_definitions_construction.json` quotes definitions from Vietnamese regulatory and
guidance documents — Circular 96/2020/TT-BTC, Decision 2171/QĐ-BTC, QCVN 09 and the
SSC–IFC ESG reporting guide. Each KPI entry carries a `source` block identifying the
document and location it was taken from. These are official Vietnamese government
publications; consult their own terms before redistributing.

## Corpus data

Annual reports, crawled news articles and every generated artifact under `data/`,
`graph_output/` and `kpi_output/` are **not** part of this repository and are **not**
covered by the MIT licence. Annual reports are the property of the issuing companies; news
articles are the property of their publishers. See the "What you can run without data
access" section of the [README](README.md).

## Reference implementation

`EmeraldMind/` (git-ignored, never committed) is an external reference implementation with
its own licence and is not part of this project.
