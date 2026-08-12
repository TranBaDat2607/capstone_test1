# Figma AI Prompts — Pipeline Architecture & Block Diagram

Generated from a direct read of `src/esg_kg` (pipeline.py, run.py, stage docstrings),
`crawl_data/` (download_reports.py, extract_archives.py, crawler.py, crawler_news.py),
and `data_processing/` (pdf_extractor.py, sentence_splitter.py, prepare_sentences.py,
esg_classifier.py, extract_esg.py, preprocess_news.py) — **not** from `docs/`, which may
describe a legacy pipeline shape.

Paste each prompt below into Figma Make / Figma AI separately. Style target: flat
academic figure look (CVPR/ICCV/ECCV/NeurIPS/ICML), lettered dashed-border panels, thin
black strokes, muted pastel fills, no drop shadows/gradients, sans-serif labels — matching
the reference figure you supplied.

## Caveats (read before generating)

- The "conduct/news" ingestion internals in Figure 1 panel (b) are shown as an opaque
  external box because `esg_news_crawler/` was not in the read scope — only
  `preprocess_news.py`'s consumption of its output was verified. `crawl_data/crawler.py`
  and `crawl_data/crawler_news.py` are FPT-specific one-off tools (confirmed from their
  own code/docstrings), not part of this pipeline, and are excluded from both figures.
- Node/edge class names, counts, and `config/schema.json` details are deliberately
  omitted/generic since that file was not read.
- Everything else (stage order, script names, function behavior, file paths, block
  grouping) is taken directly from `src/run.py`, `src/esg_kg/pipeline.py`, and the stage
  docstrings/code — not from `docs/`.

---

## Figure 1 — End-to-End Pipeline Architecture

```
Create a clean academic figure in the style of a CVPR/NeurIPS paper diagram (flat design, white background, thin 1.5pt black strokes, rounded rectangles ~8px radius, no drop shadows, no gradients, sans-serif font like Inter/Helvetica for body text, bold for headers). Layout: 3 horizontal dashed-border panels stacked top to bottom, each with a bold panel label in the top-left corner like "(a)", "(b)", "(c)" in a serif font, matching the composition style of a multi-panel method figure.

CANVAS: 1800x1100px, white background.

--- PANEL (a): "Report Ingestion & ESG Labeling" — dashed border box, light yellow tint (#FFF9E0), positioned top.

Left to right flow with solid black arrows:
1. Box "config/company_annual_report.xlsx" (small file icon, gray fill #EEEEEE) 
   arrow -> 
2. Box "download_reports.py" (rounded rect, light blue #E3F0FF) with small caption below: "5 parallel threads · retry+backoff · auto-extract .zip/.rar/.7z · resumable"
   arrow ->
3. Box "data/raw/annual_report/ (PDFs)" (folder icon, gray #EEEEEE)
   arrow ->
4. Box "pdf_extractor.py" (light blue) caption: "PyMuPDF · keeps page numbers · Vietnamese diacritics"
   arrow ->
5. Box "sentence_splitter.py" (light blue) caption: "underthesea VN sentence tokenizer · drops TOC/page-numbers/short fragments"
   these two boxes (4,5) sit inside a smaller sub-frame labeled "prepare_sentences.py" with a thin solid border
   arrow ->
6. Box "data/interim/sentences/*.jsonl" caption: "{source_pdf, page, sentence_index, text} — every sentence, no ESG filter"
   arrow ->
7. Box "ViDeBERTa-v3-ESG classifier" (light green #E6F5E9) caption: "esg_classifier.py — multi-label sigmoid over Environmental/Social/Governance/Neutral; esg=true iff Neutral<0.5; GPU (Kaggle) or CPU"
   arrow ->
8. Box "data/labeled/*.jsonl" caption: "+ labels[], scores{}, esg bool"

Below this row, a smaller side-branch box labeled "notebooks/kaggle_esg_classify.ipynb (GPU)" connected with a dashed arrow up into box 7, captioned "same classifier logic, runs on Kaggle GPU".

--- PANEL (b): "ESG Record Extraction" — dashed border box, light pink tint (#FDEDF3), positioned middle, narrower/shorter than (a).

Flow:
1. Box "data/labeled/*.jsonl" (carried over from panel a, dotted connector from panel a's box 8 down into this panel)
   arrow ->
2. Box "extract_esg.py" (light blue) caption: "keeps records where labels[] is non-empty; trims to GraphRAG-ready fields"
   arrow -> fans out to 3 output boxes side by side:
   - "esg_all_records.jsonl" (merged, all sources)
   - "esg_by_document.json" (grouped by source doc)
   - "esg_stats.json" (label counts / summary)
   all three in gray file-icon boxes, connected from extract_esg.py by three arrows.

Add a small parallel lane below, labeled "Conduct-side / news channel", showing:
Box "data/labeled/news_labeled/*.jsonl" (external — same ViDeBERTa classifier, upstream news-crawling pipeline not expanded here)
   arrow ->
Box "preprocess_news.py" caption: "date normalization (trust real publish_date -> else recover year from URL/title/text -> else uncertain) + boilerplate filter (company_mentioned, min length); non-destructive, only adds publish_date_normalized/publish_year/date_uncertain"
   arrow ->
Box "data/interim/news_preprocessed/*.jsonl"

Label this whole lower lane with a small dashed sub-box captioned "News = the 'conduct' evidence side, symmetric to the report 'claim' side above".

--- PANEL (c): "Knowledge-Graph Construction (src/esg_kg, downstream)" — dashed border box, light blue-gray tint (#EAF1F7), positioned bottom, wide.

Just a compact summary strip here (full detail lives in Figure 2): a single row of 4 rounded boxes connected left-to-right by a bold chevron arrow labeled "src/run.py <stage>", reading:
"Validated Graph (extract, extract_triples, fix_triples block)" -> "Resolved Graph (entities, provenance, indicators block)" -> "Neo4j (graph load + advisory sync)" -> "Claims vs Conduct cross-check + Claim Ledger"
Caption underneath the whole row, small italic gray text: "See Figure 2 for the full stage-by-stage block diagram."

STYLE NOTES:
- All arrows: solid black, 1.5pt, small filled arrowhead.
- Dotted/dashed arrows only for cross-panel data handoffs (a->b) and the external/upstream note in panel b.
- File/folder artifacts: light gray fill (#EEEEEE), small document or folder glyph, monospace font for paths.
- Processing scripts: light blue fill (#E3F0FF), sans-serif bold filename.
- ML models: light green fill (#E6F5E9).
- Keep captions small (9-10pt), gray (#555555), under each box.
- Panel border: 2pt dashed, colored to match panel tint (darker shade), rounded corners 12px.
- Panel label "(a)"/"(b)"/"(c)": bold, 16pt, black, top-left inside each panel border.
```

---

## Figure 2 — Temporal Knowledge-Graph Construction Block Diagram (`src/esg_kg`)

```
Create a clean academic block diagram (same flat style as Figure 1: white background, thin 1.5pt black strokes, rounded rects, no shadows/gradients, sans-serif). This figure details the 15-stage pipeline inside src/esg_kg, run via "python src/run.py <stage>". Group stages into dashed-border clusters representing the two "block" units the code collapses multiple stages into (each block writes its shared artifact exactly once).

CANVAS: 1800x1300px, white background.

Top input, centered: box "data/outputs/esg_extracted/ (labeled ESG records, report + news)" gray file icon, feeding down into the diagram with one arrow.

--- STAGE 01: box "extract  (kpi/extract.py)" light purple (#F0E6FA), caption: "per-page: Gemini structured output -> typed KPIObservation records; only ESG pages sent" 
   output artifact below it: small db-cylinder icon "kpi_output/<doc>_kpis/page_NNN_kpis.json"
   arrow down ->

--- STAGE 02: box "extract_triples  (graph/extract_triples.py)" light purple, caption: "page text + page KPIs + schema -> temporal triples -> node/edge graph; --source report|news; stamps source_type"
   output: "graph_output/graphs/<doc>/page{N}.json"
   arrow down into a dashed-border cluster labeled "BLOCK: build_validated (03 -> 03b -> 03c, one write)" light orange tint (#FFF1E0):

   Inside the cluster, 3 boxes left to right connected by thin arrows:
   - "03 fix_triples" caption: "reverse-edge repair + schema validate (offline) -> LLM batch-repair invalid triples -> aggregate"
   - "03b anchor_kpi" caption: "offline gazetteer match: KPIObservation -> Facility edges"
   - "03c canonicalize" caption: "offline: map KPI to 35-indicator vocabulary via aliases+fuzzy match; adds kpi_id, unit_normalized, value_normalized"
   Below the cluster: db-cylinder icon labeled "graph_output/validated/all_validated_triples.json"
   arrow down ->

--- STAGE 04 (parallel side box, not in the block): "issuer  (registry/issuer.py)" light purple, caption: "run-once bootstrap: drafts reporting-company name variants -> config/issuer_registry.json (hand-confirmed)"
   connect with a side arrow feeding into the next cluster (issuer registry is an input to entity resolution).

   Second dashed-border cluster labeled "BLOCK: build_resolved (05 -> 05b -> 05c, one write)" light green tint (#E6F5E9):
   Inside, 3 boxes left to right:
   - "05 entities" caption: "Stage A deterministic identity_keys + frozen issuer/standards anchors; Stage B VN-aware blocking + embeddings; Stage C LLM adjudication (budgeted); Stage D consolidate"
   - "05b provenance" caption: "offline: stamps source_doc/source_page (+ article title/url for news) back onto claim/evidence nodes"
   - "05c indicators" caption: "offline: appends ~35 StandardIndicator nodes + partOf/measuredUnder/equivalentTo/alignsWithIndicator edges"
   Below cluster: db-cylinder icon "graph_output/resolved/resolved_graph.json"

--- Optional side box below the resolved cluster: "05d align_claims (optional, LLM)" light purple, dashed outline (indicating optional), caption: "topic-classifies remaining Claim/Goal/Initiative -> alignsWithIndicator; not a verdict"
   connected with a dashed arrow (optional path) back into the resolved_graph.json artifact.

   arrow down from resolved_graph.json ->

--- STAGE 06: box "neo4j_load  (load/neo4j_load.py)" dark blue tint (#DCEAFB), caption: "loads {nodes,edges} as a property graph; nodes keyed by array index; MERGE temporal edges"
   feeds into a database cylinder icon labeled "Neo4j (bolt://localhost:8687)"
   arrow right ->

--- STAGE 07: box "claims_vs_conduct  (crosscheck/claims_vs_conduct.py)" light purple, caption: "for each SustainabilityClaim: retrieve conduct candidates (same issuer + topic + temporal window) -> LLM adjudicate supports/contradicts/irrelevant -> advisory dossier; no score, no label"
   output: "graph_output/crosscheck/<ticker>_claim_assessments.json"
   arrow down ->

--- STAGE 08: box "neo4j_sync  (load/neo4j_sync.py)" dark blue tint, caption: "MERGEs dossier assessment + evidence edges onto Neo4j advisory layer; idempotent, no LLM"
   arrow into the same Neo4j cylinder icon (dashed connector back up to it)
   arrow down ->

--- STAGE 09: box "claim_ledger  (report/claim_ledger.py)" light gray-blue, caption: "Neo4j-only, no LLM: renders per-company claim ledger, signal-first (contradicted -> supported -> unverified)"
   output: small doc icon "stdout / <ticker>_claim_ledger.md"

--- Separate side box, disconnected from the main vertical spine except a light dashed arrow from resolved_graph.json cylinder: "export_kgc  (export/export_kgc.py)" caption: "offline: reads resolved_graph.json READ-ONLY; decomposes high-degree Organization hubs into synthetic HubBucket nodes for an SSRL export view; never patches resolved_graph.json or Neo4j"
   output: "graph_output/export_kgc/"

STYLE NOTES:
- Two main dashed clusters (build_validated, build_resolved) each get a bold header label at the top of their dashed box, e.g. "BLOCK: build_validated" in 13pt bold, plus a small caption underneath: "writes its artifact exactly once".
- Stage boxes: rounded rect, light purple fill (#F0E6FA) for LLM-involving stages, plain white/light-gray fill for pure offline stages, dark blue tint (#DCEAFB) for Neo4j-touching stages.
- Add a small "$" or "LLM" pill badge (top-right corner of the box, orange #FFD580) on every stage that calls Gemini: extract, extract_triples, fix_triples (phase 2 only), entities (Stage C only), align_claims, claims_vs_conduct.
- Artifacts (JSON files / Neo4j) drawn as flat-top cylinder or folder icons, gray (#EEEEEE), monospace font, connected by thin arrows from/into the stage that writes them.
- Arrows: solid black 1.5pt with filled arrowhead for the main pipeline spine; dashed gray arrows for optional/read-only/side paths (05d, export_kgc, 08's write-back to Neo4j).
- Keep a vertical "run order" guide on the left margin: small numbered labels 01, 02, 03/03b/03c, 04, 05/05b/05c, 05d, 06, 07, 08, 09, 11 aligned to each stage's vertical position.
- Title above the whole figure, bold 18pt: "Figure 2. src/esg_kg stage pipeline — python src/run.py <stage>".
```
