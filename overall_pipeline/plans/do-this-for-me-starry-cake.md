# Render the ESG pipeline figures as hand-built SVG

## Context

`src/imports/pasted_text/pipeline-architecture.md` contains two long prose prompts written
for Figma AI, each describing an academic paper figure (CVPR/NeurIPS flat style) for an ESG
knowledge-graph pipeline:

- **Figure 1** — end-to-end pipeline, 3 stacked dashed panels (a) report ingestion & ESG
  labeling, (b) ESG record extraction + news/conduct lane, (c) compact KG-construction strip.
- **Figure 2** — the 15-stage `src/esg_kg` block diagram, with two dashed "BLOCK" clusters
  (`build_validated`, `build_resolved`), a left-margin run-order gutter, LLM badges, and
  optional/read-only side paths.

Rather than round-tripping through an image generator, we render both figures deterministically
as hand-built SVG in this React/Vite app. That gives crisp text, exact spec colors, and a real
export path for dropping into a paper. Confirmed with the user: **both figures on one scrollable
page, each with SVG and PNG download buttons.**

The project is a bare scaffold — `src/App.tsx` is placeholder dot-grid demo code with no
reusable UI, and `src/index.css` contains only `@import 'tailwindcss';`. Everything here is new.

## Approach

Pure `<svg>` with explicit coordinates. No layout engine, no diagram library — the figures are
fixed-canvas and every position is spec'd, so hardcoded coordinate constants are simpler and
produce cleaner output than auto-layout.

### Files

- **`src/figures/primitives.tsx`** — shared SVG building blocks and the style token object.
  Tokens come straight from the STYLE NOTES: strokes `1.5` black, radius 8 (12 for panels),
  fills `#EEEEEE` artifact / `#E3F0FF` script / `#E6F5E9` model+resolved-cluster /
  `#F0E6FA` LLM stage / `#DCEAFB` Neo4j / `#FFD580` badge, caption `#555555` at 9–10pt,
  panel tints `#FFF9E0` / `#FDEDF3` / `#EAF1F7` / `#FFF1E0`.
  Components: `Panel` (dashed 2pt border + tint + `(a)` serif corner label), `Cluster`
  (dashed BLOCK box with bold header + "writes its artifact exactly once" subcaption),
  `NodeBox` (rounded rect, title, optional wrapped caption below, optional `LLM` pill),
  `Artifact` (gray box with a doc / folder / flat-top-cylinder glyph, monospace label),
  `Arrow` (solid or dashed, orthogonal elbow support, shared `<marker>` arrowhead),
  `Caption` / `WrapText` (manual line-splitting helper — SVG has no text wrapping, so captions
  are passed as pre-split string arrays or wrapped by a small char-budget helper).
- **`src/figures/Figure1.tsx`** — `viewBox="0 0 1800 1100"`. Panel (a) is the 8-step ingestion
  row with `pdf_extractor.py` + `sentence_splitter.py` nested in a solid-bordered
  `prepare_sentences.py` sub-frame, plus the dashed Kaggle-notebook side branch. Panel (b) is
  `extract_esg.py` fanning to three output files, with the dashed "Conduct-side / news channel"
  sub-lane beneath. Panel (c) is the 4-box chevron strip + italic gray "See Figure 2" caption.
  Dotted cross-panel connector from (a) box 8 into (b) box 1.
- **`src/figures/Figure2.tsx`** — `viewBox="0 0 1800 1300"`, extended taller if the 11 stage
  rows plus two clusters don't fit legibly (correctness of the diagram beats the nominal canvas
  number; the aspect ratio stays paper-friendly). Vertical spine 01 → 02 → build_validated
  cluster → build_resolved cluster → 06 → 07 → 08 → 09, with `04 issuer` as a side box feeding
  the resolved cluster, `05d align_claims` as a dashed-outline optional box, and `export_kgc`
  disconnected except for a light dashed arrow off `resolved_graph.json`. Left-margin run-order
  gutter with the numbered labels. `LLM` badges on extract, extract_triples, fix_triples,
  entities, align_claims, claims_vs_conduct.
- **`src/lib/download.ts`** — `downloadSvg(el, filename)` serializes via `XMLSerializer` into a
  `image/svg+xml` Blob; `downloadPng(el, filename, scale = 2)` serializes to a data URL, draws
  it into an offscreen `<canvas>` at 2× with a white fill underneath, and exports via
  `toBlob`. Both revoke their object URLs.
- **`src/App.tsx`** — replaces the placeholder entirely. A quiet paper-review shell: title,
  short note that these are generated from the pipeline read, then two figure cards. Each card
  holds a `ref` to its `<svg>`, a caption line, and **SVG** / **PNG** buttons wired to
  `src/lib/download.ts`. Figures are rendered responsively (`width: 100%`, `height: auto` off
  the viewBox) so they scale down on narrow screens without affecting export fidelity.
- **`src/index.css`** — page background and body font wiring only; figure styling stays in the
  SVG so exports are self-contained.

### Constraints worth flagging

- **Fonts must be system stacks inside the SVG** (`Helvetica/Arial/sans-serif`,
  `ui-monospace/Menlo/monospace`, `Georgia/serif` for the panel letters). A webfont would
  rasterize as a fallback in the PNG canvas path unless base64-embedded, and the spec only asks
  for "sans-serif like Inter/Helvetica". Page chrome outside the SVG can use a webfont freely.
- Text wrapping is manual — captions are long, so each gets an explicit character budget and
  `<tspan>` lines; I'll tune line breaks per box rather than relying on a generic wrapper alone.
- Per the doc's own caveats, the news-crawling upstream stays an opaque external box and no
  schema/class names or counts are invented.

I'll invoke the `aesthetic-stance` skill before writing code for the page chrome around the
figures; the figures themselves follow the spec's flat-academic style, which overrides it.

## Verification

- The dev server is already running on `$PORT` — load the preview and confirm both figures
  render with no overlapping boxes, no clipped text, and arrows that land on box edges.
- Click **SVG** and **PNG** on each figure; confirm four files download, the SVG opens standalone
  in a browser with correct fills and fonts, and the PNG is 2× resolution on a white (not
  transparent) background.
- Narrow the preview to confirm the figures scale down rather than overflow.
- Typecheck once at the end (`pnpm exec tsc --noEmit`) since this adds several new modules.
