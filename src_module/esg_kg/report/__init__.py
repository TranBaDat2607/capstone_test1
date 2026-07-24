"""report — offline, read-only outputs (no writes to the graph).

    quality.py       <- step00_graph_quality_report.py   (Q1-Q8 diagnostics; run before/after changes)
    claim_ledger.py  <- step09_report_claim_ledger.py     (Neo4j-only claim ledger)
    evaluate.py      <- step10_evaluate.py                (P6 evaluation report, Vietnamese)

NOTE: step00 runs FIRST in the pipeline (baseline snapshot) even though it lives
here — grouped by role (offline analysis), not by run position. See pipeline.py.
"""
