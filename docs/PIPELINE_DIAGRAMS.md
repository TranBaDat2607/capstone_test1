# Pipeline diagrams

Visual companion to [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Every diagram here is drawn
from the code as it exists; if a diagram and a stage disagree, the stage is right and this
file is stale — fix it.

Diagrams are Mermaid, rendered by GitHub and by most Markdown viewers. Editable
draw.io / PlantUML sources for the presentation versions live in `diagram/`.

**Contents**

1. [System context](#1-system-context)
2. [Report ingestion (channel A)](#2-report-ingestion-channel-a)
3. [News ingestion (channel B)](#3-news-ingestion-channel-b)
4. [Graph construction — the 16 stages](#4-graph-construction--the-16-stages)
5. [Why blocks exist](#5-why-blocks-exist)
6. [Entity resolution stages A–D](#6-entity-resolution-stages-ad)
7. [The indicator axis](#7-the-indicator-axis)
8. [Claim ↔ conduct cross-check](#8-claim--conduct-cross-check)
9. [Schema tiers T1 / T2 / T3](#9-schema-tiers-t1--t2--t3)
10. [Artifact and data layout](#10-artifact-and-data-layout)
11. [End-to-end sequence](#11-end-to-end-sequence)

---

## 1. System context

```mermaid
flowchart LR
    subgraph sources[Sources]
        R[Annual & sustainability<br/>report PDFs]
        N[Third-party news]
        V[Reference vocabularies<br/>TT96 · QĐ2171 · QCVN09<br/>SSC-IFC · GRI]
    end

    subgraph build[Graph construction · esg_kg]
        KG[(Temporal ESG<br/>knowledge graph)]
    end

    subgraph serve[Presentation]
        DB[(Neo4j<br/>base + advisory layer)]
        L[Claim ledger<br/>Markdown / stdout]
        UI[ESG Evidence View<br/>localhost:8000]
    end

    R -->|claims: what they say| KG
    N -->|conduct: what they do| KG
    V -->|indicator axis| KG
    KG --> DB --> L
    DB --> UI

    classDef claim fill:#e8f0fe,stroke:#4285f4
    classDef conduct fill:#fce8e6,stroke:#ea4335
    class R claim
    class N conduct
```

The two channels stay distinguishable inside the graph via `source_type`, which is what
makes the cross-check meaningful rather than circular.

---

## 2. Report ingestion (channel A)

```mermaid
flowchart TD
    X[config/company_annual_report.xlsx] --> D[crawl_data/download_reports.py<br/>threaded · resumable]
    D --> RAW[data/raw/annual_report/]
    RAW --> A[extract_archives.py<br/>UnRAR.exe · 7z.exe]
    A --> RAW
    RAW --> P[data_processing.prepare_sentences]

    subgraph P2[inside prepare_sentences]
        PE[pdf_extractor.py<br/>PyMuPDF · keeps page numbers<br/>and Vietnamese diacritics]
        SS[sentence_splitter.py<br/>underthesea · VN-aware]
        PE --> SS
    end

    P --> S[data/interim/sentences/*.jsonl<br/>EVERY sentence · no ESG filter]
    S --> C[ViDeBERTa-v3-ESG classifier<br/>GPU: notebooks/kaggle_esg_classify.ipynb<br/>CPU: data_processing/esg_classifier.py]
    C --> LAB[data/labeled/classified/<br/>all_sentences_classified.jsonl<br/>197 companies · 873,756 sentences<br/>303,723 esg=true]
    LAB --> E[data_processing.extract_esg]
    E --> OUT[data/outputs/esg_extracted/classified/]
```

`prepare_sentences` deliberately keeps **every** sentence, not just ESG ones: page text is
reconstructed later from all sentences on a page, while only pages containing at least one
`esg=true` sentence are sent to the LLM.

---

## 3. News ingestion (channel B)

```mermaid
flowchart TD
    CO[companies.py<br/>identity sets from xlsx] --> Q[queries.py<br/>identity × ESG/controversy terms]
    Q --> SRC{sources/}
    SRC --> G[Google News RSS]
    SRC --> B[Bing]
    SRC --> DD[DuckDuckGo]
    G & B & DD --> F[fetch.py<br/>disk-cached · rate-limited]
    F --> EX[extract.py · trafilatura<br/>title / text / date]
    EX --> NM[normalize.py<br/>sentence-split into the<br/>annual-report schema]
    NM --> NJ[data/outputs/news/TICKER.jsonl<br/>+ coverage.csv]
    NJ --> CL[ViDeBERTa-v3-ESG<br/>same classifier as reports]
    CL --> NL[data/labeled/news_labeled/<br/>115 tickers · 174,256 sentences<br/>77,229 esg=true]
    NL --> PP[data_processing.preprocess_news]
    PP --> PPO[data/interim/news_preprocessed/<br/>publish_date_normalized · publish_year<br/>date_uncertain · boilerplate dropped]
```

`coverage.csv` is not a by-product — it is the evidence for the coverage caveat in
[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §8.3.

---

## 4. Graph construction — the 16 stages

```mermaid
flowchart TD
    LAB[labeled JSONL<br/>reports + news] --> S01

    S01[01 extract<br/>Gemini · per page]:::llm --> KPIO[kpi_output/]
    LAB --> S02
    KPIO --> S02[02 extract_triples<br/>Gemini or DeepSeek<br/>--source report / news]:::llm
    S02 --> GRAPHS[graph_output/graphs/&lt;doc&gt;/pageN.json]

    GRAPHS --> BV
    subgraph BV[build_validated · BLOCK]
        S03[03 fix_triples<br/>phase 1 validate · 1.5 dates · 2 LLM repair]:::llm
        S03B[03b anchor_kpi<br/>offline gazetteer]:::free
        S03C[03c canonicalize<br/>kpi_id · Goal.target_date]:::free
        S03 --> S03B --> S03C
    end
    BV --> VAL[(all_validated_triples.json<br/>written ONCE)]

    VAL --> S04[04 issuer<br/>run-once bootstrap]:::free
    S04 --> REG[config/issuer_registry.json<br/>tracked · hand-confirmed]

    VAL --> BR
    REG --> BR
    subgraph BR[build_resolved · BLOCK]
        S05[05 entities<br/>Stage A-D]:::llm
        S05B[05b provenance<br/>source_doc / source_page]:::free
        S05C[05c indicators<br/>StandardIndicator axis]:::free
        S05 --> S05B --> S05C
    end
    BR --> RES[(resolved_graph.json<br/>written ONCE)]

    RES --> S05D[05d align_claims<br/>OPTIONAL · budgeted LLM]:::llm
    RES --> S11[11 export_kgc<br/>separate export view]:::free
    RES --> S06[06 neo4j_load]:::free
    S06 --> DB[(Neo4j)]
    RES --> S07[07 claims_vs_conduct<br/>LLM adjudication MANDATORY]:::llm
    S07 --> DOS[crosscheck/&lt;ticker&gt;_claim_assessments.json]
    DOS --> S08[08 neo4j_sync<br/>advisory layer · no LLM]:::free
    S08 --> DB
    DB --> S09[09 claim_ledger]:::free
    DB --> UI[api/main.py · Evidence View]:::free

    RES -.read-only.-> S00[00 quality<br/>Q1-Q8 · R1/R5/R7]:::free

    classDef llm fill:#fff4e5,stroke:#f59e0b
    classDef free fill:#e8f5e9,stroke:#34a853
```

Orange = costs money. Green = free, offline, re-runnable. The colour split is the reason
blocks exist (§5) and the reason caches are scoped to paid results only.

---

## 5. Why blocks exist

The failure mode a block prevents:

```mermaid
flowchart LR
    subgraph bad[Three separate stages · the shape that bites]
        direction TB
        A1[03 writes the file] --> A2[03b patches it]
        A2 --> A3[03c patches it]
        A3 -.->|re-run 03 alone| A4[/whole file overwritten<br/>anchors gone · kpi_id gone<br/>PAID repairs gone · no warning/]
    end

    subgraph good[One block · the shape that ships]
        direction TB
        B1[03 in memory] --> B2[03b in memory] --> B3[03c in memory] --> B4[(write ONCE)]
        B5[(paid-repair cache<br/>content-addressed)] -.-> B1
    end

    bad ~~~ good

    style A4 fill:#fce8e6,stroke:#ea4335
    style B4 fill:#e8f5e9,stroke:#34a853
```

The distinction that makes it safe: the **intermediate artifact** answers "how far did the
pipeline get?" — internal state, droppable. The **cache** answers "what already cost
money?" — not reproducible for free, so it is kept, keyed by content rather than by
position in a batch.

---

## 6. Entity resolution stages A–D

```mermaid
flowchart TD
    IN[all_validated_triples.json<br/>many duplicate entity mentions] --> A

    subgraph A[Stage A · deterministic · free]
        A1[A.1 exact identity_keys signature]
        A2[A.2 issuer anchor · FROZEN<br/>config/issuer_registry.json]
        A3[A.3 standards anchor · FROZEN<br/>config/standards_registry.json]
    end

    A --> B
    subgraph B[Stage B · blocking]
        B1[B.1 normalized VN signature<br/>diacritics · legal form · case]
        B2[B.2 gemini-embedding-001 cosine<br/>batched · L2-normalized]
        B1 --> B2
    end

    B --> C[Stage C · gemini-2.5-flash<br/>adjudicate ambiguous pairs<br/>budgeted · cached]:::llm
    C --> D[Stage D · consolidate<br/>DSU clusters → temporal_versions<br/>year-aware edge rewiring]
    D --> OUT[(resolved_graph.json)]

    NOLLM[--no-llm<br/>the usual mode today] -.skips.-> B2
    NOLLM -.skips.-> C

    classDef llm fill:#fff4e5,stroke:#f59e0b
```

The issuer cluster is frozen on purpose: it is the backbone of the whole cross-check, so
its identity must never depend on an embedding or a model verdict.

---

## 7. The indicator axis

```mermaid
flowchart LR
    REG[Regulation TT96] -.partOf.- IND
    IND[StandardIndicator<br/>TT96-6.1.1] -->|equivalentTo| GRI[StandardIndicator<br/>GRI 305-1]
    KPI[KPIObservation<br/>kpi_id = TT96-6.1.1] -->|measuredUnder| IND
    EMI[Emission] -->|measuredUnder| IND
    CLM[SustainabilityClaim] -->|alignsWithIndicator| IND
    GOL[Goal] -->|alignsWithIndicator| IND
    INI[Initiative] -->|alignsWithIndicator| IND

    style IND fill:#e8f0fe,stroke:#4285f4,stroke-width:3px
```

`StandardIndicator` is the **join point**: a company's *claim* about an indicator and the
conduct *KPIs* measured under it hang off one node, so the cross-check can walk two hops
instead of guessing from token overlap. `pillar` on that node is also what gives the UI a
claim's E/S/G column — read, never guessed.

Two rules the stage will not break: it reads `kpi_id` assigned by `canonicalize` rather
than guessing an indicator itself, and a `Penalty` with `amount == 0` is a self-reported
"fined 0 times" boast, flagged and given **no** conduct edge.

---

## 8. Claim ↔ conduct cross-check

```mermaid
flowchart TD
    RES[(resolved_graph.json)] --> POOL[Conduct pool for the issuer<br/>Controversy · Penalty · MediaReport<br/>KPIObservation · ThirdPartyVerification]
    RES --> CLAIMS[SustainabilityClaim nodes<br/>on the issuer]

    CLAIMS --> RET
    POOL --> RET
    subgraph RET[6a retrieval · deterministic]
        R1[same issuer]
        R2[VN topic overlap ≥ min-topic-overlap]
        R3[temporal window<br/>-window-before / +window-after]
        R4[rank · cap at --top-k]
    end

    RET --> ADJ[6b adjudicate<br/>Gemini or DeepSeek<br/>MANDATORY · no fallback<br/>--max-llm-pairs budget]:::llm
    ADJ -->|cached by content| CACHE[(adjudication_cache.json)]

    ADJ --> V{verdict}
    V -->|supports| G{6c-guard<br/>company-owned domain?}
    V -->|contradicts| EDGE2[contradictedBy / contradictedByMedia]
    V -->|irrelevant| DROP[dropped]

    G -->|yes| FLAG[flagged_non_independent_support<br/>never counted as support]
    G -->|no| EDGE1[verifiedBy]

    EDGE1 & EDGE2 & FLAG --> DOS[6d dossier<br/>assessment · caveats<br/>assessment_is_advisory = true]
    DOS --> OUT[graph_output/crosscheck/]

    classDef llm fill:#fff4e5,stroke:#f59e0b
    style FLAG fill:#fce8e6,stroke:#ea4335
```

Assessment mapping: any contradiction ⇒ `appears_contradicted`; else any independent
support ⇒ `appears_supported`; else `unverified_insufficient_evidence`. Contradiction
outranks support in a mixed dossier, and the mixed case adds its own caveat.

---

## 9. Schema tiers T1 / T2 / T3

```mermaid
flowchart TD
    subgraph T1[T1 · entities · timeless identity]
        O[Organization]
        F[Facility]
        PR[Product]
        ST[Standard / Regulation]
    end
    subgraph T2[T2 · events & observations · time in identity]
        K[KPIObservation]
        EM[Emission]
        W[Waste]
        CT[Controversy]
        PN[Penalty]
        MR[MediaReport]
    end
    subgraph T3[T3 · statements & reference]
        SC[SustainabilityClaim]
        GO[Goal]
        SI[StandardIndicator]
    end

    O -->|reportsKPI| K
    O -->|ownsFacility| F
    K -->|observedAtFacility| F
    O -->|claims| SC
    SC -->|alignsWithIndicator| SI
    K -->|measuredUnder| SI

    style T1 fill:#e8f0fe,stroke:#4285f4
    style T2 fill:#fce8e6,stroke:#ea4335
    style T3 fill:#f3e8fd,stroke:#a142f4
```

The rule that follows from the tiers (P1): **never put a time field in a T1 class's
`identity_keys`**. Observation classes legitimately carry time in their keys and are
versioned per observation; entities are versioned only when their properties change,
linked by `supersedes`. `quality` lints this, and `test/test_schema_contract.py` asserts
it both ways.

---

## 10. Artifact and data layout

```mermaid
flowchart LR
    subgraph git[Tracked in Git]
        CFG[config/<br/>schema.json · registries<br/>gri_catalog · crosswalk]
        CODE[code packages]
        DV[data_version.json<br/>pins the HF revision]
        NEO[neo4j/*.cypher]
    end
    subgraph hf[Hugging Face dataset repo · git-ignored]
        DATA[data/<br/>raw → interim → labeled → outputs]
        GO[graph_output/<br/>graphs · validated · resolved<br/>crosscheck · quality · export_kgc]
        KO[kpi_output/]
    end
    subgraph local[Rebuilt locally · never synced]
        ND[neo4j_data/]
    end

    DV -.pins.-> hf
    GO -->|neo4j_load| ND
```

`data_version.json` is the hinge: it is tracked in Git, so checking out an old commit and
pulling recovers the data that commit was built against. See [DATA_SYNC.md](DATA_SYNC.md).

---

## 11. End-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    participant U as Analyst
    participant P as esg_kg stages
    participant L as LLM provider
    participant N as Neo4j
    participant W as Evidence View

    U->>P: quality --label baseline
    P-->>U: Q1-Q8 snapshot (offline)

    U->>P: extract -i labeled.jsonl
    P->>L: per-page KPI extraction (structured output)
    L-->>P: KPIObservation records

    U->>P: extract_triples --source report / news
    P->>L: page text + KPIs + schema
    L-->>P: temporal triples → per-page graphs

    U->>P: build_validated
    P->>L: batch-repair invalid triples (cached)
    P-->>P: anchor KPIs, assign kpi_id
    P-->>U: all_validated_triples.json (written once)

    U->>P: build_resolved
    P-->>P: Stage A-D, provenance, indicator axis
    P-->>U: resolved_graph.json (written once)

    U->>N: neo4j_load --clear
    U->>P: claims_vs_conduct
    P->>L: adjudicate (claim, evidence) pairs — mandatory
    L-->>P: supports / contradicts / irrelevant
    P-->>U: advisory dossiers

    U->>N: neo4j_sync (free, reuses the paid dossier)
    U->>P: claim_ledger
    P->>N: read advisory layer
    P-->>U: per-company ledger

    U->>W: open localhost:8000
    W->>N: live queries
    W-->>U: 3-column TT96/GRI evidence view

    U->>P: quality --label after-change
    P-->>U: measured before/after
```

The first and last steps are the same command on purpose: every schema or pipeline change
is expected to carry a measured before/after, and `quality` is free to run.
