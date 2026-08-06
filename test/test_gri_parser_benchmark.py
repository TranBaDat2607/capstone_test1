"""
Tests for gri/benchmark_parsers.py — the PDF-parser comparison used in the capstone
report (§5, parser ablation).

WHY THESE ASSERTIONS AND NOT OTHERS
-----------------------------------
A benchmark that compares two parsers is trivially riggable, and a rigged benchmark
still "runs" and still prints a table. Everything pinned here is a property that, if
it broke, would leave the numbers looking perfectly plausible while meaning nothing:

  1. ONE detector for every arm. If the markdown arm were scored with a
     markdown-aware detector and the PyMuPDF arm with something weaker, the result
     would measure the detectors, not the parsers. Pinned behaviourally: identical
     input text scored under two different arm labels must produce identical scores.

  2. Ground truth is INDEPENDENT of every arm. It comes from GRI's own published
     content-index template. If it were ever derived from a parser's output, that
     parser would score 100% by construction.

  3. Ground truth deduplicates. GRI 3: Material Topics lists disclosure 3-3 once per
     material topic (33 rows). Counting rows instead of distinct codes would inflate
     that standard's denominator ~10x and silently dominate the corpus average.

  4. The permissive "mere-mention" control is genuinely more permissive than the
     structural detector. That control exists to prove the parser gap is STRUCTURAL,
     not character-level. If the two ever collapsed to the same thing, the control
     would prove nothing while still printing a reassuring number.

  5. Title fidelity actually catches a line-truncated title. This is the specific
     PyMuPDF failure mode observed in the corpus (a disclosure title split across a
     line break, so the tail is lost). A fidelity metric that scored that as a match
     would erase the single most decisive finding.

Offline: reads only files already on disk, no network, no LLM. Run from the repo root:
    python test/test_gri_parser_benchmark.py
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "gri"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import benchmark_parsers as bp  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILURES.append(label)


# --------------------------------------------------------------------------
# 1. One detector for every arm
# --------------------------------------------------------------------------
def test_single_shared_detector():
    print("\n[1] The same detector scores every arm")

    text = (
        "### Disclosure 305-1 Direct (Scope 1) GHG emissions\n"
        "some body text\n"
        "### Disclosure 305-2 Energy indirect (Scope 2) GHG emissions\n"
    )
    truth = {
        "305-1": "Direct (Scope 1) GHG emissions",
        "305-2": "Energy indirect (Scope 2) GHG emissions",
    }

    a = bp.evaluate_text(text, truth)
    b = bp.evaluate_text(text, truth)
    check("identical text scores identically regardless of caller", a == b, f"{a} vs {b}")

    # The arm registry must map an arm name to a TEXT PRODUCER only. If an arm could
    # also supply its own detector, arms would no longer be comparable.
    for name, spec in bp.ARMS.items():
        check(
            f"arm '{name}' declares a text producer only (no private detector)",
            callable(spec) or (isinstance(spec, dict) and set(spec) <= {"loader", "label", "note"}),
            f"got {type(spec)}",
        )


# --------------------------------------------------------------------------
# 2 + 3. Ground truth: independent, and deduplicated
# --------------------------------------------------------------------------
def test_ground_truth():
    print("\n[2] Ground truth is independent and deduplicated")

    xlsx = os.path.join(REPO_ROOT, "gri", "gri-content-index-template-2021.xlsx")
    if not os.path.exists(xlsx):
        check("content-index template present", False, xlsx)
        return

    gt = bp.load_ground_truth(xlsx)
    check("ground truth is non-empty", len(gt) >= 30, f"got {len(gt)} standards")

    # GRI 3 lists 3-3 once per material topic; distinct codes must be far fewer.
    gri3 = None
    for key in gt:
        if key.startswith("3:") or key == "3":
            gri3 = gt[key]
            break
    check("GRI 3 present in ground truth", gri3 is not None)
    if gri3 is not None:
        check(
            "GRI 3 deduplicated to distinct codes (not one row per material topic)",
            len(gri3) <= 5,
            f"got {len(gri3)} codes: {sorted(gri3)}",
        )

    # Every code must carry a title; a title-less ground truth silently makes the
    # title-fidelity metric vacuous (everything matches nothing).
    missing = [
        (std, code)
        for std, codes in gt.items()
        for code, title in codes.items()
        if not title or not title.strip()
    ]
    check("every ground-truth code carries a non-empty title", not missing, str(missing[:5]))

    # Independence: the loader must not read any parser artifact.
    src = bp.load_ground_truth.__doc__ or ""
    check(
        "ground-truth loader documents its independent provenance",
        "content index" in src.lower() or "gri" in src.lower(),
    )


# --------------------------------------------------------------------------
# 4. The permissive control is actually more permissive
# --------------------------------------------------------------------------
def test_mention_control_is_more_permissive():
    print("\n[3] Mere-mention control is strictly more permissive than the detector")

    # A prose mention with NO heading and NO 'Disclosure NNN-N <title>' anchor.
    prose = (
        "The organization can combine its reporting on 305-1 with the figures it\n"
        "already publishes, and may cross-reference 302-4 where relevant.\n"
    )

    detected = set(bp.detect_disclosures(prose))
    mentioned = bp.mere_mention_codes(prose)

    check("mention control finds codes in bare prose", {"305-1", "302-4"} <= mentioned, str(mentioned))
    check("structural detector finds none in bare prose", not detected, str(detected))
    check("mention set is a strict superset here", detected < mentioned)


# --------------------------------------------------------------------------
# 5. Title fidelity catches the line-truncation failure mode
# --------------------------------------------------------------------------
def test_title_fidelity_catches_truncation():
    print("\n[4] Title fidelity catches a line-truncated title")

    official = "Nitrogen oxides (NOx), sulfur oxides (SOx), and other significant air emissions"

    # This is verbatim the shape PyMuPDF produces: the title is cut at the line break,
    # losing 'air emissions'.
    truncated = "Nitrogen oxides (NOx), sulfur oxides (SOx), and other significant"

    check(
        "identical title counts as fidelity match",
        bp.title_matches(official, official),
    )
    check(
        "truncated title does NOT count as a match",
        not bp.title_matches(truncated, official),
        f"'{truncated}' wrongly matched '{official}'",
    )
    # Cosmetic differences must NOT be counted as failures, or the metric measures
    # markdown syntax instead of parser quality.
    check(
        "markdown emphasis / whitespace differences still match",
        bp.title_matches("**Nitrogen oxides (NO<sub>x</sub>), sulfur oxides (SO<sub>x</sub>), "
                         "and other significant   air emissions**", official),
    )


# --------------------------------------------------------------------------
# 6. Scoring arithmetic
# --------------------------------------------------------------------------
def test_scoring_math():
    print("\n[5] Recall / precision / fidelity arithmetic")

    truth = {"1-1": "Alpha", "1-2": "Beta", "1-3": "Gamma", "1-4": "Delta"}
    detected = {"1-1": "Alpha", "1-2": "WRONG TITLE", "1-9": "Spurious"}

    s = bp.score(detected, truth)
    check("recall = 2/4", abs(s["recall"] - 0.5) < 1e-9, str(s))
    check("precision = 2/3", abs(s["precision"] - 2 / 3) < 1e-9, str(s))
    check("title fidelity = 1/2 of correctly detected", abs(s["title_fidelity"] - 0.5) < 1e-9, str(s))
    check("false positives counted", s["false_positives"] == 1, str(s))

    empty = bp.score({}, truth)
    check("empty detection => recall 0, no crash", empty["recall"] == 0.0)
    check("empty detection => precision defined (0.0)", empty["precision"] == 0.0)


# --------------------------------------------------------------------------
# 7. Real detector against the real production regex behaviour
# --------------------------------------------------------------------------
def test_detector_matches_production_shapes():
    print("\n[6] Detector handles both real corpus shapes")

    # Shape A: Marker markdown heading.
    md = "### Disclosure 305-1 Direct (Scope 1) GHG emissions\nbody\n"
    d = bp.detect_disclosures(md)
    check("markdown heading detected", d.get("305-1") == "Direct (Scope 1) GHG emissions", str(d))

    # Shape B: bare 'Disclosure NNN-N Title' line, as PyMuPDF emits.
    raw = "Disclosure 305-1 Direct (Scope 1) GHG emissions\nbody\n"
    d2 = bp.detect_disclosures(raw)
    check("bare disclosure line detected via fallback", d2.get("305-1") == "Direct (Scope 1) GHG emissions", str(d2))

    # Guidance headings must not overwrite the real disclosure title.
    both = (
        "### Disclosure 305-1 Direct (Scope 1) GHG emissions\nbody\n"
        "#### Guidance for Disclosure 305-1\nmore\n"
    )
    d3 = bp.detect_disclosures(both)
    check(
        "'Guidance for Disclosure NNN-N' does not become the title",
        d3.get("305-1") == "Direct (Scope 1) GHG emissions",
        str(d3),
    )


# --------------------------------------------------------------------------
# 7c. False positives are split by the SAME prefix rule the pipeline uses
# --------------------------------------------------------------------------
def test_false_positive_classification():
    print("\n[7b] False positives split into own-standard vs cross-standard")

    # Not every false positive is the same kind of wrong, and reporting one number
    # would hide that:
    #   - own-standard  (306-1 while parsing GRI 306) is very likely a GROUND-TRUTH
    #     gap: the 2021 content index retired disclosures the 2016 PDF still contains.
    #     Counting these against a parser punishes it for being correct.
    #   - cross-standard (2-23 while parsing GRI 101) is a REAL extraction error, and
    #     is exactly the mis-attribution that standard_of() exists to prevent.
    detected = {"306-1": "Water discharge", "2-23": "in GRI 2: General Disclosures", "306-3": "Significant spills"}
    truth = {"306-3": "Significant spills"}

    split = bp.classify_false_positives(detected, truth, standard_number="306")
    check("own-standard FP counted separately", split["own_standard"] == ["306-1"], str(split))
    check("cross-standard FP counted separately", split["cross_standard"] == ["2-23"], str(split))
    check("true positives are not counted as FP at all",
          "306-3" not in split["own_standard"] + split["cross_standard"], str(split))

    # The split must use the disclosure-code PREFIX, matching standard_of() in the
    # catalogue builder — not a substring test, which would call 30-1 a match for 3.
    split2 = bp.classify_false_positives({"30-1": "x"}, {}, standard_number="3")
    check("prefix rule is exact, not substring ('30-1' is not GRI 3)",
          split2["cross_standard"] == ["30-1"], str(split2))


# --------------------------------------------------------------------------
# 7b. Detector variants isolate "parser quality" from "detector bug"
# --------------------------------------------------------------------------
def test_emphasis_tolerant_variant():
    print("\n[7a] Emphasis-tolerant detector variant")

    # Real shape from the corpus: Marker marks the disclosure label bold, so the
    # production regex cannot see the code. That is a limitation of the DETECTOR,
    # not of the parser — and conflating the two would understate Marker while
    # looking like a parser result.
    bolded = "## **Disclosure 416-1** Assessment of the health and safety impacts\nbody\n"

    strict = bp.detect_disclosures(bolded)
    tolerant = bp.detect_disclosures(bolded, emphasis_tolerant=True)

    check("strict (production) detector misses a bold-wrapped code", "416-1" not in strict, str(strict))
    check("tolerant variant recovers it", "416-1" in tolerant, str(tolerant))
    check(
        "tolerant variant recovers the correct title too",
        tolerant.get("416-1") == "Assessment of the health and safety impacts",
        str(tolerant),
    )

    # The variant must be a strict relaxation: anything the production detector
    # finds, the tolerant one must also find. Otherwise the two tables in the
    # report would not be comparable.
    plain = (
        "### Disclosure 305-1 Direct (Scope 1) GHG emissions\n"
        "### Disclosure 305-2 Energy indirect (Scope 2) GHG emissions\n"
    )
    s2 = bp.detect_disclosures(plain)
    t2 = bp.detect_disclosures(plain, emphasis_tolerant=True)
    check("tolerant variant is a superset of the strict one", set(s2) <= set(t2), f"{s2} vs {t2}")
    check("tolerant variant does not alter titles it shares", all(t2[c] == s2[c] for c in s2), f"{s2} vs {t2}")


# --------------------------------------------------------------------------
# 7. The benchmark measures the PRODUCTION detector, not a lookalike
# --------------------------------------------------------------------------
def test_detector_stays_in_sync_with_production():
    print("\n[7] Benchmark regexes are still the production regexes")

    prod = os.path.join(REPO_ROOT, "gri", "full_gri", "parse_gri_markdown.py")
    if not os.path.exists(prod):
        check("production parser present", False, prod)
        return

    with open(prod, "r", encoding="utf-8") as fh:
        source = fh.read()

    # If someone edits parse_gri_markdown.py's disclosure regexes, this benchmark
    # silently stops measuring the real pipeline while still printing a table.
    for name, pattern in (
        ("primary", bp.DISCLOSURE_HEADING_RE.pattern),
        ("fallback", bp.DISCLOSURE_FALLBACK_RE.pattern),
    ):
        check(
            f"{name} regex is verbatim from parse_gri_markdown.py",
            pattern in source,
            f"not found in production source: {pattern!r}",
        )


def main():
    print("=" * 72)
    print("GRI parser benchmark — contract tests")
    print("=" * 72)

    test_single_shared_detector()
    test_ground_truth()
    test_mention_control_is_more_permissive()
    test_title_fidelity_catches_truncation()
    test_scoring_math()
    test_detector_matches_production_shapes()
    test_false_positive_classification()
    test_emphasis_tolerant_variant()
    test_detector_stays_in_sync_with_production()

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
