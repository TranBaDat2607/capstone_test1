# extraction/ — Notes

## Purpose
Data ingestion layer. Converts raw external sources (PDFs, crawled news) into structured entities/relations for the Knowledge Graph.

---

## Files

### `pdf_parser.py`
Reads ESG/Annual Report PDFs page by page.

**Backends (in priority order):**
1. `pdfplumber` — primary, supports text + table extraction
2. `fitz` (PyMuPDF) — fallback, text only (no tables)

**Key methods:**
- `parse(pdf_path)` → list of page dicts (filtered by `min_text_length`, default 50 chars)
- `parse_to_chunks(pdf_path, chunk_size=1000, overlap=100)` → overlapping text chunks for RAG indexing

**Output format per page:**
```python
{
    "page_number": int,
    "text": str,           # cleaned plain text
    "tables": [
        {
            "rows": [["col1", "col2"], ["val1", "val2"]],
            "page": int
        }
    ],
    "metadata": {"width": float, "height": float}
}
```

> Note: `tables` is always `[]` when using the fitz fallback.

---

### `nlp_pipeline.py`
Sends parsed PDF pages to Claude (Anthropic API) and extracts structured ESG entities and relations conforming to ontology schema v2.0.

**Entity types extracted:**
| Type | Example |
|------|---------|
| `Claim` | "FPT cam kết giảm 30% carbon vào 2030" |
| `DataPoint` | value=1250, unit="tonne CO2e", year=2023 |
| `Metric` | Standardized GRI/ISSB metric with `gri_code` |
| `Target` | Long-term ESG goal with `target_year` |
| `Project` | Named ESG initiative/program |

**Relation types extracted:**
- `claims_reduction` — Company → Claim
- `supported_by` — Claim → DataPoint
- `has_emission` — Company → Metric
- `targets_reduction` — Company → Target
- `invests_in` — Company → Project

**Key methods:**
- `extract_from_page(page)` → `{entities: [...], relations: [...]}`
- `extract_from_pages(pages)` → merged result across all pages (IDs globally deduplicated)

**Confidence scores:**
- `0.95` — direct quote from text
- `0.80` — inferred from context

**Output format:**
```python
{
    "entities": [
        {"id": "CLM_001", "type": "Claim", "properties": {"text": "...", "pillar": "E", "sentiment": "Positive", "page_ref": 12, "year": 2023}}
    ],
    "relations": [
        {"id": "REL_001", "type": "claims_reduction", "source_id": "COMP_FPT", "target_id": "CLM_001", "confidence_score": 0.95, "extraction_method": "LLM_Constraint"}
    ]
}
```

---

### `news_processor.py`
Walks `data/raw/crawl_data_news/YYYY/` directories and ingests crawled news articles as `NewsEvent` nodes in the KG.

**Processing steps per article:**
1. Normalize field names (handles `title`/`headline`/`name`, `content`/`summary`/`body`, etc.)
2. Classify ESG pillar (E/S/G/Mixed) via Vietnamese + English keyword matching
3. Infer sentiment (Positive/Negative/Neutral) via keyword counts
4. Parse date to ISO `YYYY-MM-DD` format (best-effort, multiple formats supported)
5. Ingest via `GraphBuilder.add_news_event()`

**Key methods:**
- `load_all_articles(years=None)` → list of normalized article dicts
- `ingest_into_kg(graph_builder, years=None)` → int (number of NewsEvent nodes created)

---

## Data Flow

```
PDF file  ──► PDFParser.parse()
                    │
                    ▼
          NLPExtractionPipeline.extract_from_pages()
                    │
                    ▼
          {entities, relations} ──► GraphBuilder (KG)

News JSON ──► NewsProcessor.ingest_into_kg()
                    │
                    ▼
          NewsEvent nodes ──────────► GraphBuilder (KG)
```

---

## Dependencies

| Library | Used by | Purpose |
|---------|---------|---------|
| `pdfplumber` | pdf_parser | Primary PDF extraction |
| `PyMuPDF` (fitz) | pdf_parser | Fallback PDF extraction |
| `anthropic` | nlp_pipeline | Claude API calls |
| stdlib only | news_processor | No extra deps needed |
