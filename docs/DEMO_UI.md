# Demo UI — the company-code claim-ledger explorer

Script: [`app.py`](../app.py) (repo root) · theme: [`.streamlit/config.toml`](../.streamlit/config.toml).
System context: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §9, [`CLAIM_LEDGER.md`](./CLAIM_LEDGER.md).

A **Streamlit** web front-end for Step 7. You enter a **company code (ticker)** and the app
renders that issuer's **claim ledger**: every `SustainabilityClaim` beside the conduct evidence
that supports or contradicts it, plus an explicitly **advisory** assessment.

It is a lookup/dashboard, **not a chatbot** — a deliberate design choice. The output is
deterministic (same input → same evidence), fully traceable to sources, and preserves the
project's non-negotiable framing: **no ground truth ⇒ evidence + an advisory opinion, never a
greenwashing score or verdict** ([`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §1.1).

---

## 1. What it shows

- **Company picker** — a ticker dropdown, auto-populated from the tickers that have an advisory
  layer (`crosscheck_ticker` in Neo4j). Currently only **AAA** has data; it scales as you run
  the pipeline for more of the 115 companies in `config/company_annual_report.xlsx`.
- **Issuer header** — count chips (total / appears_contradicted / appears_supported /
  unverified), the standing **advisory-only banner**, and the **coverage caveat** (thin
  independent conduct is *not* exoneration — §8.3).
- **Signal-first claim cards** — ordered contradicted → supported → unverified, color-coded,
  each listing contradicting (`✗`), supporting (`✓`) and flagged company-domain (`⚑`) evidence
  with class, confidence, year, source domain, provider, and the LLM rationale — plus per-claim
  `signals` and `caveats`.
- **Source references** (`docs/PROVENANCE_PATCH.md`) — the claim header cites the annual
  report + page (`📄 AAA_Baocaothuongnien_2021 · tr. 36`; falls back to the free-text
  `c.source` for unstamped nodes) and each evidence line cites its origin: report-side
  `📄 <doc> · tr. <N>`, news-side `📰 <article title> · <domain>` (plain text, not a link).
  Requires `step05b_stamp_provenance.py` to have run before the Neo4j load; press
  "↻ Làm mới từ Neo4j" after a reload to drop the Streamlit cache.
- **Filters** (sidebar) — view bucket, **Review queue** (contradiction **and** no independent
  verification — the schema payoff, §4.1), free-text search, max-claims cap, text-length cap.

It is **read-only and LLM-free**: it queries the Neo4j advisory layer only and reuses
`src/step09_report_claim_ledger.py`'s own helpers (`build_header`, `is_review_queue`,
`_sort_key`, `ROLE_BUCKET`, …) so the web view can never drift from the CLI ledger.

---

## 2. Prerequisites (same as Step 7)

1. **Dependencies** (adds `streamlit` to the existing set):
   ```bash
   pip install -r requirements.txt        # or: pip install streamlit
   ```
2. **Neo4j up** with the step-5 graph loaded:
   ```bash
   docker compose up -d                   # Neo4j on bolt://localhost:8687
   ```
   Connection is read from `.env` (`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` /
   `NEO4J_DATABASE`), with the same defaults as `src/step09_report_claim_ledger.py`.
3. **Advisory layer synced** once (free, no tokens — it re-reads the paid Step-6 dossier):
   ```bash
   python src/step08_sync_crosscheck_to_neo4j.py
   ```

If a prerequisite is missing the app fails gracefully with the exact fix:
- Neo4j down → an error card with the `docker compose up -d` command.
- No assessed claims for the ticker → a prompt to run `step08_sync_crosscheck_to_neo4j.py`.

---

## 3. Run it

From the repo root:

```bash
streamlit run app.py
```

Streamlit opens `http://localhost:8501` in your browser. Pick a ticker (AAA), then use the
sidebar to switch views. **↻ Refresh from Neo4j** clears the cache and re-reads the graph — use
it after re-running the sync.

To run on a different port, or headless (no auto-open) for a remote/demo machine:

```bash
streamlit run app.py --server.port 8599                 # custom port
streamlit run app.py --server.headless true             # don't open a browser
```

---

## 4. Suggested 60-second demo flow

1. Open with the default **Signal-bearing** view → the contradicted + supported claims, sorted
   by confidence.
2. Point at a real contradiction, e.g. `AAA_SC_001` — *"Ensures growth in revenue and profit"*
   with a `KPIObservation` showing **−42.3 %** (conf 1.00).
3. Switch to **Review queue** → the claims an analyst should look at first (contradiction, no
   independent verification).
4. Call out the **advisory banner** + **coverage caveat**: the system surfaces and organizes
   evidence and offers an opinion; the judgment stays with the human.

---

## 5. Relationship to the CLI

`app.py` is a thin presentation layer over the same Neo4j advisory layer that
`src/step09_report_claim_ledger.py` renders to the console/Markdown. Everything the CLI does
(header, buckets, review queue, signal-first ordering) is available in the UI; the CLI remains
the scriptable/Markdown path, the UI the interactive one. The analyst Cypher in
[`neo4j/crosscheck_queries.cypher`](../neo4j/crosscheck_queries.cypher) queries the identical layer.

## 6. Related docs

[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) (§9 — output & querying) ·
[`CLAIM_LEDGER.md`](./CLAIM_LEDGER.md) (Step 6b sync + Step 7 ledger this UI mirrors) ·
[`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) (Step 6 — the dossiers behind it)
