"""crosscheck — the analytical core: claim vs conduct adjudication.

    claims_vs_conduct.py  <- step07_crosscheck_claims_vs_conduct.py  (LLM adjudication; dossiers)

The step07b offline softmax-scoring companion (evidence-balance distribution over an
already-adjudicated dossier) was removed outright with `src/` (2026-07-29) rather than
ported — nothing on the delivered UI surface read its scores. Dossiers written by
claims_vs_conduct.py never carry `assessment_scores`/`score_components` now; the
categorical `assessment` field was always the primary output (see docs/SYSTEM_DESIGN.md
§1.1 — no ground truth exists for a greenwashing probability).
"""
