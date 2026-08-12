# Data Construction Pipeline

End-to-end flow from raw annual reports / news through to the temporal ESG knowledge
graph and the Evidence View UI. Stage names in parentheses (e.g. `step05c`) are the
`old_step` labels used by `python src/run.py <stage>` — see `CLAUDE.md` for the full
command reference.

```mermaid
flowchart TD

    subgraph D["D. KPI definition builder (kpi_build/, run-once)"]
        D1["01_...→06_... crawl TT96/QĐ2171/QCVN09/SSC-IFC"] --> D2out["kpi_definitions_construction.json"]
    end

    subgraph D2["D2. GRI catalog builder (gri/, run-once)"]
        G1["crawl_full_gri.py → 42 GRI PDFs"] --> G2["build_gri_catalog.py"] --> G3["config/gri_catalog.json"]
    end

    subgraph A["A. Ingestion → ESG sentences (reports)"]
        A1["crawl_data/download_reports.py"] --> A2["data/raw/annual_report/"]
        A2 --> A3["data_processing.prepare_sentences\n(pdf_extractor + sentence_splitter)"]
        A3 --> A4["data/interim/sentences/*.jsonl"]
        A4 --> A5["ViDeBERTa-v3-ESG classifier"]
        A5 --> A6["data/labeled/classified/\nall_sentences_classified.jsonl"]
        A6 --> A7["data_processing.extract_esg"]
        A7 --> A8["data/outputs/esg_extracted/classified/"]
    end

    subgraph B["B. News ingestion (conduct side)"]
        B1["esg_news_crawler.run"] --> B2["data/outputs/news/<TICKER>.jsonl"]
        B2 --> B3["ViDeBERTa-v3-ESG classifier"]
        B3 --> B4["data/labeled/news_labeled/\nall_news_sentences_classified.jsonl"]
        B4 --> B5["data_processing.preprocess_news"]
        B5 --> B6["data/interim/news_preprocessed/"]
    end

    subgraph C["C. Labeled JSONL → temporal KG (src/esg_kg)"]
        C0["quality (step00)\nQ1-Q8 report"]

        C1["extract (step01)"] --> C1out["kpi_output/<doc>_kpis/"]
        D2out -.-> C1

        C2["extract_triples (step02)\n--source report / --source news"] --> C2out["graph_output/graphs/<doc>/page{N}.json"]

        subgraph BLOCK1["build_validated BLOCK"]
            C3["fix_triples (step03)"] --> C3b["anchor_kpi (step03b)"] --> C3c["canonicalize (step03c)"]
        end
        C3c --> C3out["all_validated_triples.json"]

        C4["issuer (step04)"] --> C4out["config/issuer_registry.json"]
        C4reg["config/standards_registry.json\n(static, hand-edited)"]

        subgraph BLOCK2["build_resolved BLOCK"]
            C5["entities (step05)"] --> C5b["provenance (step05b)"] --> C5c["indicators (step05c)"]
        end
        C5c --> C5out["resolved_graph.json"]

        C5d["align_claims (step05d)\noptional, LLM"]
        C11["export_kgc (step11, partial)"] --> C11out["graph_output/export_kgc/"]

        C6["neo4j_load (step06)"] --> NEO[("Neo4j\nbolt://localhost:8687")]

        C7["claims_vs_conduct (step07)\nLLM adjudication"] --> C7out["graph_output/crosscheck/\n<ticker>_claim_assessments.json"]

        C8["neo4j_sync (step08)"] --> NEO
        C9["claim_ledger (step09)"] --> C9out["claim ledger (stdout + .md)"]
    end

    A8 --> C2
    B6 --> C2
    A8 --> C1
    C2out --> C3
    C3out --> C4
    C4out --> C5
    C4reg --> C5
    C5out --> C5d
    C5out --> C11
    C5out --> C6
    G3 -.-> C5c
    C5out --> C7
    NEO --> C7
    C7out --> C8
    NEO --> C9

    subgraph E["E. Evidence View UI"]
        E1["api/main.py + evidence_service.py"] --> E2["frontend/ (index.html/app.js)"]
    end
    NEO --> E1

    style D fill:#f5f5f5
    style D2 fill:#f5f5f5
    style A fill:#eef7ff
    style B fill:#fff7ee
    style C fill:#f0fff0
    style E fill:#fef0f6
```
