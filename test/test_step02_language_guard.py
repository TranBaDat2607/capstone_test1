#!/usr/bin/env python3
"""step02's extraction prompt must require Vietnamese output for free text (issue #6).

Why this file exists. ``TEMPORAL_GRAPH_PROMPT_TEMPLATE`` and
``NEWS_GRAPH_PROMPT_TEMPLATE`` (the report/claim-side and news/conduct-side
extraction prompts) contain zero instruction about output language for
``name``/``title``/``description``/other free text. Measured on the real
corpus, the LLM translates ~52.7% of entity names into English. That is not
merely cosmetic: ``normalize_name`` (step05 Stage A, now ``esg_kg.core.naming``)
collapses every Vietnamese spelling of a name onto one key but sends the
English translation to a different one, so a translated name does not raise
an error anywhere downstream — it silently splits one real-world entity into
two nodes in the resolved graph.

Why there is no runtime guard here (unlike step03's ``preserve_property_values``,
commit 046e572). step02 is the point of *origin* for these values — nothing in
this file reads a value back and compares it to something earlier, the way
phase 2 of step03 compares a repair against the original triple. The
*consequence* of an LLM ignoring instructions is already guarded downstream,
at step03, where an English "repair" of a Vietnamese name is now blocked.
Adding a second, redundant runtime guard here would have nothing to check
against. So the only thing to pin here is the prompt text itself, and the
only correctness property available offline is: the current (pre-fix) prompt
text fails these assertions, and the fixed text passes them — CLAUDE.md
forbids verifying by re-running a paid stage, so no live-corpus measurement
is attempted here.

Offline, no LLM/Neo4j/network. Run from the repo root:

    python test/test_step02_language_guard.py
"""
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.graph.extract_triples import (  # noqa: E402
    NEWS_GRAPH_PROMPT_TEMPLATE,
    TEMPORAL_GRAPH_PROMPT_TEMPLATE,
    build_page_prompt,
)

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"

REQUIRED_DIRECTIVE_SNIPPETS = (
    "## OUTPUT LANGUAGE",
    "VIETNAMESE",
    "full diacritics",
    "Do NOT translate",
    "Do NOT strip diacritics",
)

REQUIRED_EXCLUSION_SNIPPETS = (
    "does NOT apply to",
    "ISO",
    "class`/`predicate",
    "source_id/kpi_id/claim_id",
    "is_current/date_uncertain",
    "unit",
)

OLD_REPORT_NAMES = ("Acme Corp", "Acme Hanoi Plant")
NEW_REPORT_NAMES = (
    "Công ty Cổ phần Vật liệu Xây dựng Sông Hồng",
    "Nhà máy Sông Hồng Hà Nội",
)

OLD_NEWS_STRINGS = (
    "CTCP Nhua An Phat Xanh",
    "Khai sai thue, Nhua An Phat Xanh bi xu ly hon 1,7 ty dong",
    "Tax mis-declaration penalty",
    "Loi nhuan quy 2 tang truong 24.6 phan tram",
)
NEW_NEWS_STRINGS = (
    "CTCP Nhựa An Phát Xanh",
    "Khai sai thuế, Nhựa An Phát Xanh bị xử lý hơn 1,7 tỷ đồng",
    "Xử phạt do khai sai thuế",
    "Lợi nhuận quý 2 tăng trưởng 24,6 phần trăm",
)


def _load_schema():
    return json.loads((REPO_ROOT / "config" / "schema.json").read_text(encoding="utf-8"))


def test_report_template_states_the_vietnamese_output_rule():
    for snippet in REQUIRED_DIRECTIVE_SNIPPETS:
        assert snippet in TEMPORAL_GRAPH_PROMPT_TEMPLATE, (
            f"report prompt is missing the language directive {snippet!r}")
    for snippet in REQUIRED_EXCLUSION_SNIPPETS:
        assert snippet in TEMPORAL_GRAPH_PROMPT_TEMPLATE, (
            f"report prompt is missing the exclusion clause {snippet!r}")


def test_news_template_states_the_vietnamese_output_rule():
    for snippet in REQUIRED_DIRECTIVE_SNIPPETS:
        assert snippet in NEWS_GRAPH_PROMPT_TEMPLATE, (
            f"news prompt is missing the language directive {snippet!r}")
    for snippet in REQUIRED_EXCLUSION_SNIPPETS:
        assert snippet in NEWS_GRAPH_PROMPT_TEMPLATE, (
            f"news prompt is missing the exclusion clause {snippet!r}")


def test_report_template_worked_example_uses_vietnamese_names():
    for old in OLD_REPORT_NAMES:
        assert old not in TEMPORAL_GRAPH_PROMPT_TEMPLATE, (
            f"report prompt's worked example still models drift: {old!r}")
    for new in NEW_REPORT_NAMES:
        assert new in TEMPORAL_GRAPH_PROMPT_TEMPLATE, (
            f"report prompt's worked example should use {new!r}")


def test_news_template_worked_examples_are_fully_diacritic():
    for old in OLD_NEWS_STRINGS:
        assert old not in NEWS_GRAPH_PROMPT_TEMPLATE, (
            f"news prompt's worked example still models drift: {old!r}")
    for new in NEW_NEWS_STRINGS:
        assert new in NEWS_GRAPH_PROMPT_TEMPLATE, (
            f"news prompt's worked example should use {new!r}")


def test_build_page_prompt_report_carries_the_language_rule():
    schema = _load_schema()
    prompt = build_page_prompt(
        schema=schema, page_text="Doanh thu nam 2023 dat 1.200 ty dong.",
        page_no=1, page_kpis=[], company="AAA", year=2023, source="report",
    )
    assert "## OUTPUT LANGUAGE" in prompt
    assert "Do NOT translate" in prompt


def test_build_page_prompt_news_carries_the_language_rule():
    schema = _load_schema()
    prompt = build_page_prompt(
        schema=schema, page_text="Cong ty bi xu phat vi vi pham moi truong.",
        page_no=1, page_kpis=[], company="AAA", year=2024, source="news",
        article_meta={
            "source_domain": "vietnamnet.vn",
            "title": "AAA bi xu phat",
            "publish_date": "2024-08-14",
            "url": "https://vietnamnet.vn/example",
        },
    )
    assert "## OUTPUT LANGUAGE" in prompt
    assert "Do NOT translate" in prompt


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
