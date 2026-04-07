# extraction/ — Notes

## Files

### `pdf_parser.py`
Extracts text, tables, and images from ESG PDFs.

**Methods:**
- `parse(pdf_path)` → list of page dicts (backward-compatible)
- `extract_and_save(pdf_path, output_dir)` → saves `extraction_result.json` + `images/IMG_*.png`

**Output — `extraction_result.json`:**
```json
{
  "document": {
    "document_id": "2023-fpt-esg-report",
    "source_file": "2023-fpt-esg-report.pdf",
    "extracted_at": "2026-04-07",
    "total_pages": 120
  },
  "blocks": [
    {
      "id": "2023-fpt-esg-report_blk_0001",
      "type": "text",
      "page": 1,
      "content": { "text": "..." },
      "layout": { "bbox": [0.0, 0.0, 595.28, 841.89], "reading_order": 1 },
      "context": { "before": "...", "after": "...", "window_size": 200 },
      "metadata": { "has_numeric_data": true, "extraction_method": "pdfplumber" }
    },
    {
      "id": "2023-fpt-esg-report_blk_0010",
      "type": "table",
      "page": 12,
      "content": {
        "rows": [["Chỉ tiêu", "2022", "2023"], ["CO2 (tấn)", "1280", "980"]],
        "header": ["Chỉ tiêu", "2022", "2023"],
        "raw": "Chỉ tiêu | 2022 | 2023\nCO2 (tấn) | 1280 | 980"
      },
      "layout": { "bbox": [57.0, 312.4, 538.0, 480.6], "reading_order": 10 },
      "context": { "before": "...", "after": "..." },
      "metadata": { "has_numeric_data": true, "extraction_method": "pdfplumber" }
    },
    {
      "id": "2023-fpt-esg-report_blk_0020",
      "type": "image",
      "page": 5,
      "content": { "path": "2023-fpt-esg-report/images/IMG_001.png", "format": "png" },
      "layout": { "bbox": [72.0, 180.0, 520.0, 420.0], "reading_order": 20 },
      "context": { "before": "...", "after": "..." },
      "metadata": { "content_type_hint": "chart", "extraction_method": "PyMuPDF" }
    }
  ]
}
```

**Key metadata fields:**

| Field | KG usage |
|-------|---------|
| `layout.bbox` | Spatial provenance |
| `layout.reading_order` | Block sequence across document |
| `context.before/after` | LLM context window for NLP extraction |
| `content.header` (table) | Column labels → DataPoint unit/year inference |
| `content.raw` (table) | Original text for LLM re-parsing |
| `metadata.has_numeric_data` | Flags DataPoint candidates |
| `metadata.content_type_hint` | `chart`/`diagram`/`photo` → controls NLP pipeline routing |
| `metadata.extraction_method` | Stored in KG relation properties |

---

### `nlp_pipeline.py`
Sends PDF pages to Claude API and extracts ESG entities/relations.

**Output:**
```json
{
  "entities": [
    {"id": "CLM_001", "type": "Claim", "properties": {"text": "...", "pillar": "E", "sentiment": "Positive", "page_ref": 12, "year": 2023}},
    {"id": "DP_001",  "type": "DataPoint", "properties": {"value": 980, "unit": "tonne CO2e", "year": 2023, "page_ref": 12, "data_type": "Actual"}}
  ],
  "relations": [
    {"id": "REL_001", "type": "claims_reduction", "source_id": "COMP_FPT", "target_id": "CLM_001", "confidence_score": 0.95, "extraction_method": "LLM_Constraint"},
    {"id": "REL_EXT_CLM_001", "type": "extracted_from", "source_id": "CLM_001", "target_id": "RPT_FPT_ESG_2023", "properties": {"page_number": 12}}
  ]
}
```

---

### `news_processor.py`
Ingests crawled news JSONs from `data/raw/crawl_data_news/YYYY/` as `NewsEvent` KG nodes.

**Normalized article format:**
```json
{
  "headline": "...", "content": "...", "url": "...",
  "source": "VnExpress", "published_at": "2023-06-15",
  "pillar": "E", "sentiment": "Negative", "year": 2023
}
```

---

## Data Flow

```
PDF ──► PDFParser.extract_and_save() ──► extraction_result.json + images/
                                               │
                                               ▼
                                   NLPExtractionPipeline ──► {entities, relations} ──► KG

News JSON ──► NewsProcessor.ingest_into_kg() ──► NewsEvent nodes ──► KG
```
