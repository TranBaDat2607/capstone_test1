#!/usr/bin/env python3
"""step01 (kpi.extract) and step07 (crosscheck.claims_vs_conduct) prompts must require
Vietnamese output for the free-text values they generate — same defect shape as issue #6
(test_step02_language_guard.py), found while auditing every LLM stage that writes content
that ends up in the graph.

Why these two specifically. `test_step02_language_guard.py` already covers
`extract_triples.py`'s TEMPORAL_GRAPH_PROMPT_TEMPLATE / NEWS_GRAPH_PROMPT_TEMPLATE. Auditing
every other stage's prompt for the same gap (2026-08-05) found two more free-text fields with
no explicit output-language instruction, only a note that the SOURCE text is Vietnamese:

  - kpi.extract's `title`/`snippet` (KPIObservation free text; `title` especially, since the
    kpi_type="other" fallback asks for "a descriptive title" with no language constraint at
    all). This feeds extract_triples's per-page prompt as page KPI context.
  - claims_vs_conduct's `rationale` (written onto llm_supports/llm_contradicts edges via
    `_mk_edge`, synced into Neo4j by neo4j_sync, and rendered in the claim ledger / Evidence
    View — advisory content that is genuinely "in the graph", not just internal reasoning).

Other stages audited and found NOT to need a guard:
  - entities.py's Stage-C ADJUDICATE_PROMPT returns only {"same_entity": bool} — no free text.
  - align_claims.py's SYSTEM performs topic classification (picks an indicator id) — no free
    text either.
  - fix_triples.py's BATCH_FIX_PROMPT repairs triple SHAPE, never VALUES
    (preserve_property_values, test_step03_llm_value_guard.py) — it must never invent new
    prose in any language, so a language directive there would have nothing to apply to.

Same reasoning as test_step02_language_guard.py for why there is no runtime guard here: these
two stages are points of origin for these values (extract.py: nothing to compare a repair
against; claims_vs_conduct.py: rationale is advisory prose, not a structural property
step03's guard could police). The only thing to pin offline is the prompt text itself.

Offline, no LLM/Neo4j/network. Run from the repo root:

    python test/test_step01_step07_language_guard.py
"""
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.kpi.extract import KPIExtractor, SECTOR  # noqa: E402
from esg_kg.crosscheck.claims_vs_conduct import ADJUDICATE_SYSTEM  # noqa: E402

# Directive text the OUTPUT LANGUAGE section must contain, same vocabulary as issue #6's
# extract_triples fix, for one consistent phrasing across the repo.
REQUIRED_DIRECTIVE_SNIPPETS = (
    "OUTPUT LANGUAGE",
    "VIETNAMESE",
    "full diacritics",
    "Do NOT translate",
    "Do NOT strip diacritics",
)


def _build_extract_system_prompt() -> str:
    ex = KPIExtractor.__new__(KPIExtractor)
    ex.kpi_defs = [{"id": "TT96-1", "definition": "d1"}]
    system, _user = ex._build_prompt(
        "Cong ty da giam phat thai 20% trong nam 2023.", "AAA", SECTOR, 5, "AAA_2023.pdf")
    return system


# --------------------------------------------------------------------------- #
# 1. kpi.extract's system prompt states the rule and exempts structural fields.
# --------------------------------------------------------------------------- #
def test_kpi_extract_system_prompt_states_the_vietnamese_output_rule():
    system = _build_extract_system_prompt()
    for snippet in REQUIRED_DIRECTIVE_SNIPPETS:
        assert snippet in system, f"kpi.extract system prompt is missing the language directive {snippet!r}"


def test_kpi_extract_system_prompt_exempts_structural_fields():
    system = _build_extract_system_prompt()
    assert "does NOT apply to" in system
    for field in ("kpi_type", "unit", "source_id"):
        assert field in system, f"exclusion clause should name {field!r}"


def test_kpi_extract_system_prompt_covers_the_other_fallback_title():
    """The kpi_type="other" branch is the one place a language-neutral "descriptive title"
    instruction previously had no language attached to it at all."""
    system = _build_extract_system_prompt()
    assert 'kpi_type to "other"' in system
    other_idx = system.index('kpi_type to "other"')
    language_idx = system.index("OUTPUT LANGUAGE")
    assert language_idx > other_idx, (
        "the language rule must be present and apply to the descriptive title the "
        "'other' fallback asks for"
    )


# --------------------------------------------------------------------------- #
# 2. claims_vs_conduct's ADJUDICATE_SYSTEM states the rule for `rationale` and
#    exempts the structural verdict/confidence fields.
# --------------------------------------------------------------------------- #
def test_adjudicate_system_states_the_vietnamese_output_rule():
    for snippet in REQUIRED_DIRECTIVE_SNIPPETS:
        assert snippet in ADJUDICATE_SYSTEM, (
            f"claims_vs_conduct ADJUDICATE_SYSTEM is missing the language directive {snippet!r}"
        )
    assert "rationale" in ADJUDICATE_SYSTEM


def test_adjudicate_system_exempts_verdict_and_confidence():
    assert "does NOT apply to" in ADJUDICATE_SYSTEM
    assert "verdict" in ADJUDICATE_SYSTEM
    assert "confidence" in ADJUDICATE_SYSTEM


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}\n     {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test is a failure too
            failed += 1
            print(f"ERROR {t.__name__}\n     {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} test(s) passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
