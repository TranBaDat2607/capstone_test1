# Provenance patch — step 5b (`src/step05b_stamp_provenance.py`)

**Goal:** every claim card and evidence entry in the demo UI (and the CLI ledger) can cite
its source by name — *"Báo cáo thường niên 2021, trang 36"* on the report side,
*"article title · domain"* on the news side.

## 1. Why a patch is needed at all

Sentence-level traceability (`source_pdf`, `page`, `sentence_index`) is a stated pipeline
principle (CLAUDE.md), and step02 runs **per page** — at extraction time the doc + page are
known exactly. But nothing stamped them onto the nodes: `stamp_source_type` only stamped
`source_type`, and the step03 aggregation flattens all page files into one triple list.
After step05, the resolved nodes retain only:

- `KPIObservation.source_id` — sometimes the canonical `<src>_<page>_<idx>` form,
  often an LLM-invented string;
- `SustainabilityClaim.source` — free text (usually just the report stem, page only rarely);
- nothing at all on `Controversy` / `Penalty`; `MediaReport` keeps `title`/`publisher` but
  no page and no URL.

The information is **not lost**, though: the per-page extraction files
`graph_output/graphs/<doc>/page{N}.json` still exist, their **path** encodes doc + page, and
each raw node carries the `stable_id` step02 computed. The news JSONL corpora
(`data/labeled/news_labeled/*.jsonl`, `data/interim/news_preprocessed/*.jsonl`) map every
news doc id (`TICKER__domain__hash`) to the article's `title`/`url`/`source_domain`.
step05b joins all of this back — offline, **no LLM, no DB, no re-extraction cost**.

## 2. The 4-tier matching precedence

For each resolved node of a stamped class, the first tier that yields candidates wins
(recorded in `provenance_method`):

| tier | method | how | coverage (AAA snapshot, 2026-07-19) |
|---|---|---|---|
| 1 | `source_id` | node's own `source_id` parses as `<src>_<page>_<idx>` (`parse_source_id` from step03b) | 1,614 |
| 2 | `source_id_index` | exact raw `source_id` lookup in an index over all page-file nodes (LLM-invented ids are retained verbatim in the page files) | 3,233 |
| 3 | `stable_id_index` | recompute `get_stable_entity_id` (step02) for the canonical props **and** each `temporal_versions[i].properties`; look up the page-file `stable_id` index | 1,398 |
| 4 | `page_token` | `_pageNN_` token embedded in a KPI-style id + a unique year-matching doc dir | 13 |

Resulting per-class coverage: SustainabilityClaim **1217/1217**, KPIObservation 4894/4906,
MediaReport 91/91, Controversy 2/2, Penalty 4/4, ThirdPartyVerification 24/24, Waste 15/15,
Emission 11/24, Certification 0/92 (identity props were canonicalized in resolution — these
stay unstamped and the UI falls back to the free-text `source`).

**Stamped classes** = `PROVENANCE_CLASSES` (step02): SustainabilityClaim, KPIObservation,
MediaReport, Controversy, Penalty, ThirdPartyVerification, Emission, Waste, Certification.
T1 entities (Organization, Person, …) are deliberately excluded — they recur on dozens of
pages and get merged in step05, so one stamped page would be misleading.

## 3. Ambiguity policy

If a node matches several `(doc, page)` locations (`choose_primary`):

1. prefer docs whose stem ends with `_<year>` of the node's year context
   (`year`/`target_year`/`date`/`valid_from`);
2. then the lexicographically smallest doc;
3. then the smallest page.

The full candidate list is preserved in `source_pages` (`["doc:page", …]`) so nothing is
hidden — only 28 such nodes today, mostly claims repeated verbatim across report pages.

## 4. Property glossary (all additive; loaded into Neo4j automatically by step06)

| property | on | meaning |
|---|---|---|
| `source_doc` | stamped nodes | doc dir name: report stem (`AAA_Baocaothuongnien_2011`) or news doc id (`AAA__vietstock.vn__hash`) |
| `source_page` | stamped nodes | 1-based page in that doc (always 1 for news) |
| `source_pages` | ambiguous nodes only | full `"doc:page"` candidate list |
| `provenance_method` | stamped nodes | which tier matched; `"extraction"` = stamped by step02 itself (ground truth — the patch never overwrites it) |
| `article_title` / `article_url` / `source_domain` | news-doc nodes | from the news JSONL corpora |

Existing properties (`source`, `source_id`, `source_type`, `title`, `publisher`,
`temporal_versions`) are never touched.

## 5. Hard invariant: node order is load-bearing

step06 keys Neo4j nodes by array index (`_node_key = f"n{i}"`) and the step07 dossiers
reference nodes by `node_index` / `claim_node_index`. step05b therefore **never inserts,
removes, or reorders nodes** — it only mutates `properties` dicts — and asserts the
node/edge counts are unchanged before writing. This is also covered by
`test/test_temporal_invariants.py::test_stamp_graph`.

## 6. Run order (all free — no tokens)

```bash
python src/step05b_stamp_provenance.py --dry-run   # coverage preview + stats
python src/step05b_stamp_provenance.py             # patch resolved_graph.json in place
python src/step06_load_graph_to_neo4j.py --clear   # reload (wipes the advisory layer too!)
python src/step08_sync_crosscheck_to_neo4j.py      # restore the advisory layer (reuses the paid dossier)
```

Re-run step05b after any step05 re-run (the resolver rewrites `resolved_graph.json`).
New step02 extractions self-stamp (`stamp_provenance`, `provenance_method="extraction"`),
so on freshly extracted docs the patch becomes a no-op for those nodes.

Display side: the ESG Evidence View UI (`api/` + `frontend/`, claim source `<doc>, trang <N>`)
and `src/step09_report_claim_ledger.py` (`[<doc> p.<N>]` / article title) — see
`docs/ESG_EVIDENCE_VIEW.md`, `docs/CLAIM_LEDGER.md`.

Stats land in `graph_output/resolved/provenance_patch_stats.json`.
