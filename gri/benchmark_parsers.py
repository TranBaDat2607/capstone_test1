"""
PDF-parser ablation for the GRI standards corpus.

WHAT THIS MEASURES
------------------
The indicator-metadata module (docs/CAPSTONE_REPORT_DRAFT.md §3.2) linearises 42 GRI
standard PDFs before segmenting them into disclosure units. This script answers, with
numbers instead of assertion, the question a reviewer will ask: *does the layout-aware
parser actually buy anything over positional text extraction?*

Three arms, all fed through the SAME disclosure detector — the one copied verbatim from
the production parser (gri/full_gri/parse_gri_markdown.py). The arms differ only in how
the PDF became text:

  pymupdf_raw     page.get_text()               — naive full-text extraction
  pymupdf_blocks  page.get_text("blocks")       — positionally ordered text blocks; this
                                                  is the method the AIP491 reference
                                                  report uses for its GRI corpus
  marker          cached Marker/Surya Markdown  — layout-aware linearisation (what this
                                                  project actually runs)

GROUND TRUTH
------------
GRI's own published content-index template (gri-content-index-template-2021.xlsx),
which enumerates every disclosure code and its official title. It is authored by GRI,
not derived from any parser here, so no arm can score well by construction.

METRICS
-------
  recall          fraction of official disclosures the arm's text yields as a unit
  precision       fraction of detected units that are real disclosures of that standard
  title_fidelity  of the correctly detected units, fraction whose title matches the
                  official title — this is where a parser that finds the CODE but
                  mangles the TITLE gets caught
  mention_recall  permissive control: fraction of official codes appearing anywhere in
                  the raw characters. Both arms should score high. Its purpose is to
                  show that any gap in `recall` is STRUCTURAL, not a character-level
                  extraction failure — without it, a reader can reasonably suspect the
                  weaker arm simply lost text.

Offline: no network, no LLM. Marker output is read from the on-disk cache produced by
gri/full_gri/convert_pdf_to_markdown.py, so re-running costs nothing.

Usage (from the repo root):
    python gri/benchmark_parsers.py
    python gri/benchmark_parsers.py --limit 5          # smoke run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, Iterable, Set, Tuple

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "full_gri", "Full set of GRI Standards - English")
CACHE_DIR = os.path.join(BASE_DIR, "full_gri", "markdown_cache")
XLSX_PATH = os.path.join(BASE_DIR, "gri-content-index-template-2021.xlsx")
OUT_DIR = os.path.join(BASE_DIR, "benchmark_results")


# ---------------------------------------------------------------------------
# The production detector.
#
# These two patterns are COPIED VERBATIM from parse_gri_markdown.py
# (parse_disclosures_from_markdown). They are duplicated rather than imported
# because that function also does requirement parsing, unit inference and
# translation — none of which this benchmark should pay for or perturb.
#
# test/test_gri_parser_benchmark.py asserts both patterns still appear literally
# in the production source, so an edit there cannot silently desynchronise this
# benchmark from the pipeline it claims to measure.
# ---------------------------------------------------------------------------
DISCLOSURE_HEADING_RE = re.compile(
    r"(?:^|\n)#{1,4}\s*(?:Disclosure\s+)?((\d+[\-\.]\d+)\s+([^\n\r]+))",
    re.IGNORECASE,
)
DISCLOSURE_FALLBACK_RE = re.compile(
    r"(Disclosure\s+(\d+[\-\.]\d+)\s+([^\n\r]+))",
    re.IGNORECASE,
)

# Emphasis-tolerant variants of the same two patterns. Identical in every respect
# except that markdown emphasis markers are permitted around the 'Disclosure' label
# and the code. The corpus contains headings like:
#
#     ## **Disclosure 416-1** Assessment of the health and safety impacts ...
#
# which the production regex cannot see, because '**' sits between the heading
# marker and the word 'Disclosure'. That is a DETECTOR limitation, not a parser
# one — and scoring it as a parser result would understate any parser that emits
# emphasis. Kept as a separate, clearly-labelled variant so the primary table
# remains an honest measurement of the pipeline as it actually runs.
_EMPH = r"[\*\_]{0,3}"
DISCLOSURE_HEADING_RE_TOLERANT = re.compile(
    rf"(?:^|\n)#{{1,4}}\s*{_EMPH}\s*(?:Disclosure\s+)?{_EMPH}((\d+[\-\.]\d+){_EMPH}\s+([^\n\r]+))",
    re.IGNORECASE,
)
DISCLOSURE_FALLBACK_RE_TOLERANT = re.compile(
    rf"({_EMPH}Disclosure\s+{_EMPH}(\d+[\-\.]\d+){_EMPH}\s+([^\n\r]+))",
    re.IGNORECASE,
)

# Permissive control: a bare disclosure code anywhere in the character stream.
MENTION_RE = re.compile(r"\b(\d{1,3}-\d{1,2})\b")


def detect_disclosures(text: str, emphasis_tolerant: bool = False) -> Dict[str, str]:
    """Run the production disclosure segmenter over `text`.

    Mirrors parse_disclosures_from_markdown: try the heading pattern first, fall
    back to a bare 'Disclosure NNN-N <title>' line only when the heading pattern
    matched nothing at all, and keep the FIRST title seen for each code.

    `emphasis_tolerant` swaps in the relaxed patterns described above. It is a
    strict relaxation — every code the production detector finds is still found,
    with the same title — so the two runs stay directly comparable.
    """
    heading_re = DISCLOSURE_HEADING_RE_TOLERANT if emphasis_tolerant else DISCLOSURE_HEADING_RE
    fallback_re = DISCLOSURE_FALLBACK_RE_TOLERANT if emphasis_tolerant else DISCLOSURE_FALLBACK_RE

    matches = list(heading_re.finditer(text))
    if not matches:
        matches = list(fallback_re.finditer(text))

    out: Dict[str, str] = {}
    for m in matches:
        code = m.group(2).strip().replace(".", "-")
        if code in out:
            continue
        title = re.sub(r"[\*\_\#]+", "", m.group(3)).strip()
        title = re.sub(r"\s*\(Continued\)$", "", title, flags=re.IGNORECASE).strip()
        out[code] = title
    return out


def mere_mention_codes(text: str) -> Set[str]:
    """Permissive control — every disclosure-shaped code present in the characters."""
    return {m.group(1) for m in MENTION_RE.finditer(text)}


# ---------------------------------------------------------------------------
# Title comparison
# ---------------------------------------------------------------------------
_STRIP_MARKUP = re.compile(r"<[^>]+>|[\*\_\#`]+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_title(s: str) -> str:
    """Fold away everything that is presentation, keep everything that is content.

    Markdown emphasis, HTML subscript tags (Marker renders NO<sub>x</sub>),
    punctuation and whitespace runs are cosmetic and must not count as a
    difference — otherwise the metric measures markup syntax rather than whether
    the parser recovered the title. Missing WORDS must still count.
    """
    s = _STRIP_MARKUP.sub("", s or "").lower()
    return _NON_ALNUM.sub(" ", s).strip()


def title_matches(candidate: str, official: str) -> bool:
    return normalize_title(candidate) == normalize_title(official)


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
_STD_HEADER_RE = re.compile(r"GRI\s+(\d{1,3})\s*:\s*(.+?)\s*(\d{4})?\s*$")
_ROW_RE = re.compile(r"^(\d{1,3}-\d{1,2})\s+(.+)$", re.S)


def load_ground_truth(xlsx_path: str = XLSX_PATH) -> Dict[str, Dict[str, str]]:
    """Load the official disclosure list from GRI's published content index template.

    Independent provenance: this workbook is authored and distributed by GRI. It is
    not produced by, and does not read, any parser in this repository.

    Returns {standard_key: {code: official_title}}, deduplicated — GRI 3 lists
    disclosure 3-3 once per material topic, and counting rows instead of distinct
    codes would inflate that one standard's weight roughly tenfold.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["1. Content index in accordance"]

    truth: Dict[str, Dict[str, str]] = {}
    current: str | None = None

    for row in ws.iter_rows(min_row=6, values_only=True):
        cell_a = row[0] if len(row) > 0 else None
        cell_b = row[1] if len(row) > 1 else None

        if isinstance(cell_a, str) and "GRI" in cell_a:
            head = re.sub(r"\s+", " ", cell_a).strip()
            m = _STD_HEADER_RE.match(head)
            if m:
                num, name, year = m.group(1), m.group(2).strip(), m.group(3) or ""
                current = f"{num}:{year}" if year else num
                truth.setdefault(current, {})
                _STANDARD_TITLES[current] = f"GRI {num}: {name} {year}".strip()

        if isinstance(cell_b, str) and current:
            m = _ROW_RE.match(re.sub(r"\s+", " ", cell_b).strip())
            if m:
                code, title = m.group(1), m.group(2).strip()
                # First title wins; repeated rows (GRI 3-3 per topic) collapse.
                truth[current].setdefault(code, title)

    wb.close()
    return {k: v for k, v in truth.items() if v}


_STANDARD_TITLES: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Parser arms
# ---------------------------------------------------------------------------
def load_pymupdf_raw(pdf_path: str) -> str:
    import fitz

    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def load_pymupdf_blocks(pdf_path: str) -> str:
    """Positionally ordered text blocks — the reference report's stated method."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        parts = []
        for page in doc:
            blocks = page.get_text("blocks")
            # (x0, y0, x1, y1, text, block_no, block_type); order by reading position.
            blocks = [b for b in blocks if len(b) > 4 and isinstance(b[4], str)]
            blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
            parts.extend(b[4] for b in blocks)
        return "\n".join(parts)
    finally:
        doc.close()


def load_marker(pdf_path: str) -> str:
    """Cached Marker/Surya Markdown, keyed by PDF filename."""
    cache = os.path.join(CACHE_DIR, os.path.basename(pdf_path) + ".md")
    if not os.path.exists(cache):
        raise FileNotFoundError(cache)
    with open(cache, "r", encoding="utf-8") as fh:
        return fh.read()


ARMS = {
    "pymupdf_raw": load_pymupdf_raw,
    "pymupdf_blocks": load_pymupdf_blocks,
    "marker": load_marker,
}

ARM_LABELS = {
    "pymupdf_raw": "PyMuPDF (raw text)",
    "pymupdf_blocks": "PyMuPDF (ordered blocks)",
    "marker": "Marker / Surya (layout-aware)",
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(detected: Dict[str, str], truth: Dict[str, str]) -> Dict[str, float]:
    truth_codes = set(truth)
    det_codes = set(detected)
    hits = truth_codes & det_codes

    recall = len(hits) / len(truth_codes) if truth_codes else 0.0
    precision = len(hits) / len(det_codes) if det_codes else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    good_titles = sum(1 for c in hits if title_matches(detected[c], truth[c]))
    fidelity = good_titles / len(hits) if hits else 0.0

    return {
        "expected": len(truth_codes),
        "detected": len(det_codes),
        "hits": len(hits),
        "false_positives": len(det_codes - truth_codes),
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "title_fidelity": fidelity,
        "titles_correct": good_titles,
        "missed": sorted(truth_codes - det_codes),
        # Concrete evidence for the report's error analysis, not just counts.
        "bad_titles": [
            {"code": c, "detected": detected[c], "official": truth[c]}
            for c in sorted(hits)
            if not title_matches(detected[c], truth[c])
        ][:5],
        "fp_examples": [
            {"code": c, "detected_as": detected[c]}
            for c in sorted(det_codes - truth_codes)
        ][:5],
    }


def classify_false_positives(
    detected: Dict[str, str], truth: Dict[str, str], standard_number: str
) -> Dict[str, list]:
    """Split false positives by whether the code belongs to the standard being parsed.

    Uses the disclosure-code prefix — the same rule as standard_of() in the
    catalogue builder — because the two failure modes are not equally serious:

      own_standard    e.g. 306-1 found while parsing GRI 306: Effluents and Waste
                      2016. The 2021 content index retired those disclosures when
                      GRI 306: Waste 2020 superseded them, but the 2016 PDF still
                      contains them. This is a GROUND-TRUTH gap, and counting it
                      against a parser penalises it for extracting real content.

      cross_standard  e.g. 2-23 found while parsing GRI 101, harvested out of a
                      cross-reference like "...as required by 2-23 in GRI 2".
                      This is a genuine extraction error and precisely the
                      mis-attribution standard_of() exists to prevent.
    """
    own, cross = [], []
    for code in sorted(set(detected) - set(truth)):
        if code.split("-")[0] == standard_number:
            own.append(code)
        else:
            cross.append(code)
    return {"own_standard": own, "cross_standard": cross}


def evaluate_text(text: str, truth: Dict[str, str], standard_number: str | None = None) -> Dict[str, float]:
    """Score one arm's text. The ONLY scoring entry point — every arm goes through
    this function with the same detector, so arms remain comparable."""
    detected = detect_disclosures(text)
    s = score(detected, truth)

    # Same relaxed detector applied to EVERY arm, reported separately.
    tol = score(detect_disclosures(text, emphasis_tolerant=True), truth)
    s["tolerant"] = {
        "hits": tol["hits"],
        "detected": tol["detected"],
        "recall": tol["recall"],
        "precision": tol["precision"],
        "titles_correct": tol["titles_correct"],
        "title_fidelity": tol["title_fidelity"],
        "missed": tol["missed"],
    }

    if standard_number:
        s["fp_split"] = classify_false_positives(detected, truth, standard_number)

    mentions = mere_mention_codes(text)
    truth_codes = set(truth)
    s["mention_recall"] = (
        len(truth_codes & mentions) / len(truth_codes) if truth_codes else 0.0
    )
    s["chars"] = len(text)
    s["md_headings"] = len(re.findall(r"(?m)^#{1,6}\s", text))
    s["md_tables"] = len(re.findall(r"(?m)^\s*\|.+\|\s*$", text))
    return s


# ---------------------------------------------------------------------------
# PDF <-> ground-truth pairing
# ---------------------------------------------------------------------------
_PDF_KEY_RE = re.compile(r"^GRI\s+(\d{1,3})_.*?(\d{4})?\s*(?:V[\d.]+)?\.pdf$", re.IGNORECASE)


def pdf_standard_key(filename: str) -> str | None:
    """Map 'GRI 306_ Waste 2020.pdf' -> '306:2020'."""
    m = re.match(r"^GRI\s+(\d{1,3})_", filename, re.IGNORECASE)
    if not m:
        return None
    num = m.group(1)
    years = re.findall(r"\b(19|20)\d{2}\b", filename)
    ym = re.findall(r"\b((?:19|20)\d{2})\b", filename)
    return f"{num}:{ym[-1]}" if ym else num


def pair_pdfs_with_truth(truth: Dict[str, Dict[str, str]]) -> list[Tuple[str, str]]:
    """Return [(pdf_path, standard_key)] for PDFs the content index covers.

    Standards the index does not enumerate (the sector standards GRI 11-14, GRI 1
    Foundation, the Glossary) are EXCLUDED rather than scored against an empty
    denominator — scoring them would silently drag every arm toward zero and say
    nothing about the parsers.
    """
    import glob

    pairs = []
    for path in sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))):
        key = pdf_standard_key(os.path.basename(path))
        if key and key in truth:
            pairs.append((path, key))
    return pairs


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run(limit: int | None = None) -> dict:
    truth = load_ground_truth()
    pairs = pair_pdfs_with_truth(truth)
    if limit:
        pairs = pairs[:limit]

    print(f"[+] Ground truth: {len(truth)} standards from GRI content index")
    print(f"[+] Scored corpus: {len(pairs)} PDFs matched to the index")
    print(f"[+] Arms: {', '.join(ARMS)}\n")

    per_doc = []
    timings = {a: 0.0 for a in ARMS}

    for i, (pdf_path, key) in enumerate(pairs, 1):
        name = os.path.basename(pdf_path)
        std_truth = truth[key]
        row = {"pdf": name, "standard_key": key, "expected": len(std_truth), "arms": {}}

        for arm, loader in ARMS.items():
            t0 = time.perf_counter()
            try:
                text = loader(pdf_path)
            except Exception as exc:  # noqa: BLE001
                row["arms"][arm] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            elapsed = time.perf_counter() - t0
            timings[arm] += elapsed
            s = evaluate_text(text, std_truth, standard_number=key.split(":")[0])
            s["seconds"] = round(elapsed, 3)
            row["arms"][arm] = s

        per_doc.append(row)
        marks = " ".join(
            f"{a}={row['arms'][a].get('recall', 0):.2f}" for a in ARMS
        )
        print(f"  [{i:>2}/{len(pairs)}] {name[:52]:<52} {marks}")

    summary = aggregate(per_doc)
    summary["timings_seconds"] = {a: round(t, 2) for a, t in timings.items()}
    result = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ground_truth_source": os.path.basename(XLSX_PATH),
        "standards_scored": len(pairs),
        "summary": summary,
        "examples": collect_examples(per_doc),
        "per_document": per_doc,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "parser_benchmark.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    md = render_markdown(result)
    with open(os.path.join(OUT_DIR, "parser_benchmark.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    print("\n" + md)
    print(f"[✔] Wrote {OUT_DIR}/parser_benchmark.{{json,md}}")
    return result


def aggregate(per_doc: list) -> dict:
    out = {}
    for arm in ARMS:
        rows = [d["arms"][arm] for d in per_doc if "error" not in d["arms"].get(arm, {})]
        if not rows:
            out[arm] = {"error": "no successful runs"}
            continue
        tot_expected = sum(r["expected"] for r in rows)
        tot_hits = sum(r["hits"] for r in rows)
        tot_detected = sum(r["detected"] for r in rows)
        tot_titles = sum(r["titles_correct"] for r in rows)
        tot_mention = sum(
            round(r["mention_recall"] * r["expected"]) for r in rows
        )
        micro_r = tot_hits / tot_expected if tot_expected else 0.0
        micro_p = tot_hits / tot_detected if tot_detected else 0.0

        t_hits = sum(r["tolerant"]["hits"] for r in rows)
        t_det = sum(r["tolerant"]["detected"] for r in rows)
        t_titles = sum(r["tolerant"]["titles_correct"] for r in rows)
        t_r = t_hits / tot_expected if tot_expected else 0.0
        t_p = t_hits / t_det if t_det else 0.0

        out[arm] = {
            "tolerant": {
                "micro_recall": t_r,
                "micro_precision": t_p,
                "micro_f1": (2 * t_p * t_r / (t_p + t_r)) if (t_p + t_r) else 0.0,
                "title_fidelity": t_titles / t_hits if t_hits else 0.0,
                "false_positives": t_det - t_hits,
            },
            "documents": len(rows),
            "expected_disclosures": tot_expected,
            "detected_units": tot_detected,
            "hits": tot_hits,
            "false_positives": tot_detected - tot_hits,
            "micro_recall": micro_r,
            "micro_precision": micro_p,
            "micro_f1": (2 * micro_p * micro_r / (micro_p + micro_r)) if (micro_p + micro_r) else 0.0,
            "title_fidelity": tot_titles / tot_hits if tot_hits else 0.0,
            "titles_correct": tot_titles,
            "mention_recall": tot_mention / tot_expected if tot_expected else 0.0,
            "fp_own_standard": sum(len(r.get("fp_split", {}).get("own_standard", [])) for r in rows),
            "fp_cross_standard": sum(len(r.get("fp_split", {}).get("cross_standard", [])) for r in rows),
            "macro_recall": sum(r["recall"] for r in rows) / len(rows),
            "md_headings_total": sum(r["md_headings"] for r in rows),
            "md_tables_total": sum(r["md_tables"] for r in rows),
            "perfect_documents": sum(1 for r in rows if r["recall"] == 1.0),
        }
    return out


def render_markdown(result: dict) -> str:
    s = result["summary"]
    n = result["standards_scored"]
    L = []
    L.append("# GRI PDF parser ablation\n")
    L.append(f"- generated: {result['generated']}")
    L.append(f"- ground truth: `{result['ground_truth_source']}` (published by GRI)")
    L.append(f"- corpus: {n} GRI standard PDFs covered by the content index")
    L.append("- detector: identical for every arm, copied verbatim from "
             "`gri/full_gri/parse_gri_markdown.py`\n")

    L.append("## Main result\n")
    L.append("| Parser | Recall | Precision | F1 | Title fidelity | False positives | Perfect docs |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for arm in ARMS:
        a = s.get(arm, {})
        if "error" in a:
            L.append(f"| {ARM_LABELS[arm]} | — | — | — | — | — | {a['error']} |")
            continue
        L.append(
            f"| {ARM_LABELS[arm]} | {a['micro_recall']*100:.1f}% | {a['micro_precision']*100:.1f}% "
            f"| {a['micro_f1']*100:.1f}% | {a['title_fidelity']*100:.1f}% "
            f"| {a['false_positives']} | {a['perfect_documents']}/{a['documents']} |"
        )

    L.append("\n## False positives, split by kind\n")
    L.append("Not every false positive is equally wrong, and one number would hide that. "
             "A code whose prefix matches the standard being parsed (e.g. `306-1` inside "
             "GRI 306) is almost certainly a **ground-truth gap** — the 2021 content index "
             "retired disclosures the 2016 PDF still contains, so the parser is being "
             "penalised for extracting real content. A code with a different prefix "
             "(e.g. `2-23` inside GRI 101) is a **real error**, harvested out of a "
             "cross-reference, and is exactly the mis-attribution `standard_of()` exists "
             "to prevent.\n")
    L.append("| Parser | Total FP | Ground-truth gap (own standard) | Real contamination (cross standard) |")
    L.append("|---|---:|---:|---:|")
    for arm in ARMS:
        a = s.get(arm, {})
        if "error" in a:
            continue
        L.append(
            f"| {ARM_LABELS[arm]} | {a['false_positives']} | {a.get('fp_own_standard', 0)} "
            f"| {a.get('fp_cross_standard', 0)} |"
        )

    L.append("\n## Detector ablation: emphasis-tolerant segmenter\n")
    L.append("The production segmenter cannot match a disclosure code wrapped in markdown "
             "emphasis (`## **Disclosure 416-1** ...`). That is a limitation of the "
             "**detector**, not of any parser, and it only ever penalises a parser rich "
             "enough to emit emphasis. Re-running with a relaxed pattern — applied "
             "identically to every arm — separates the two concerns.\n")
    L.append("| Parser | Recall (production) | Recall (tolerant) | Precision (tolerant) | Title fidelity (tolerant) |")
    L.append("|---|---:|---:|---:|---:|")
    for arm in ARMS:
        a = s.get(arm, {})
        if "error" in a:
            continue
        t = a["tolerant"]
        L.append(
            f"| {ARM_LABELS[arm]} | {a['micro_recall']*100:.1f}% | {t['micro_recall']*100:.1f}% "
            f"| {t['micro_precision']*100:.1f}% | {t['title_fidelity']*100:.1f}% |"
        )

    L.append("\n## Control: is the gap structural or character-level?\n")
    L.append("`mention_recall` counts a disclosure code appearing **anywhere** in the "
             "extracted characters, with no structural requirement. If every arm scores "
             "high here while differing on `recall`, the difference is caused by lost "
             "**structure**, not by lost **text**.\n")
    L.append("| Parser | Mention recall (chars) | Unit recall (structure) | Gap |")
    L.append("|---|---:|---:|---:|")
    for arm in ARMS:
        a = s.get(arm, {})
        if "error" in a:
            continue
        gap = a["mention_recall"] - a["micro_recall"]
        L.append(
            f"| {ARM_LABELS[arm]} | {a['mention_recall']*100:.1f}% "
            f"| {a['micro_recall']*100:.1f}% | {gap*100:+.1f}pp |"
        )

    L.append("\n## Structural signal recovered\n")
    L.append("| Parser | Markdown headings | Table rows | Extraction time (s) |")
    L.append("|---|---:|---:|---:|")
    for arm in ARMS:
        a = s.get(arm, {})
        if "error" in a:
            continue
        L.append(
            f"| {ARM_LABELS[arm]} | {a['md_headings_total']} | {a['md_tables_total']} "
            f"| {s['timings_seconds'].get(arm, 0)} |"
        )

    L.append("\n> Note on extraction time: the Marker column measures **cache reads**, "
             "not model inference. Conversion is a one-off cost already paid; the "
             "cache is what every rebuild actually touches.\n")

    L.append("\n## Error analysis — what the losing arm actually produces\n")
    ex = result.get("examples", {})
    for arm in ARMS:
        items = ex.get(arm, {})
        bad = items.get("bad_titles", [])
        fps = items.get("false_positives", [])
        if not bad and not fps:
            continue
        L.append(f"\n### {ARM_LABELS[arm]}\n")
        if bad:
            L.append("**Titles recovered incorrectly** (code found, content wrong):\n")
            L.append("| Standard | Code | Extracted title | Official title |")
            L.append("|---|---|---|---|")
            for b in bad[:8]:
                L.append(
                    f"| {b['pdf']} | {b['code']} | `{b['detected'][:70]}` | `{b['official'][:70]}` |"
                )
            L.append("")
        if fps:
            L.append("**Spurious disclosure units** (text mistaken for a disclosure heading):\n")
            L.append("| Standard | Fabricated code | Captured as |")
            L.append("|---|---|---|")
            for f in fps[:8]:
                L.append(f"| {f['pdf']} | {f['code']} | `{f['detected_as'][:70]}` |")
            L.append("")
    return "\n".join(L)


def collect_examples(per_doc: list) -> dict:
    """Pull concrete failure instances out of the per-document results."""
    out = {}
    for arm in ARMS:
        bad, fps = [], []
        for d in per_doc:
            a = d["arms"].get(arm, {})
            if "error" in a:
                continue
            for b in a.get("bad_titles", []):
                bad.append({"pdf": d["pdf"].replace(".pdf", ""), **b})
            for f in a.get("fp_examples", []):
                fps.append({"pdf": d["pdf"].replace(".pdf", ""), **f})
        out[arm] = {"bad_titles": bad, "false_positives": fps}
    return out


def dump_extractions(limit: int | None = None) -> None:
    """Write every arm's extracted disclosure set to disk, for manual inspection.

    Deliberately thin: it reuses ARMS and detect_disclosures directly rather than
    re-deriving anything, so what lands on disk is exactly what the benchmark
    scored. There is no second implementation here to drift out of sync.
    """
    truth = load_ground_truth()
    pairs = pair_pdfs_with_truth(truth)
    if limit:
        pairs = pairs[:limit]

    root = os.path.join(OUT_DIR, "extractions")
    for arm in ARMS:
        os.makedirs(os.path.join(root, arm), exist_ok=True)
    os.makedirs(os.path.join(root, "side_by_side"), exist_ok=True)

    print(f"[+] Dumping extractions for {len(pairs)} standards x {len(ARMS)} arms")

    for pdf_path, key in pairs:
        name = os.path.basename(pdf_path).replace(".pdf", "")
        safe = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")
        std_truth = truth[key]

        arm_out = {}
        for arm, loader in ARMS.items():
            try:
                detected = detect_disclosures(loader(pdf_path))
            except Exception as exc:  # noqa: BLE001
                detected = {"__error__": f"{type(exc).__name__}: {exc}"}
            arm_out[arm] = detected
            with open(os.path.join(root, arm, f"{safe}.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "pdf": os.path.basename(pdf_path),
                        "standard_key": key,
                        "parser": ARM_LABELS[arm],
                        "disclosures_detected": len(detected),
                        "disclosures": dict(sorted(detected.items())),
                    },
                    fh,
                    indent=2,
                    ensure_ascii=False,
                )

        # Side-by-side view: official vs each arm, one row per disclosure code.
        codes = sorted(
            set(std_truth) | {c for d in arm_out.values() for c in d if c != "__error__"},
            key=lambda c: [int(x) for x in c.split("-")] if c.replace("-", "").isdigit() else [999],
        )
        lines = [f"# {name}\n", f"Ground-truth disclosures: **{len(std_truth)}**\n"]
        lines.append("| Code | Official title (GRI index) | " +
                     " | ".join(ARM_LABELS[a] for a in ARMS) + " |")
        lines.append("|---|---|" + "---|" * len(ARMS))
        for c in codes:
            official = std_truth.get(c, "— *(not a real disclosure of this standard)*")
            cells = []
            for arm in ARMS:
                got = arm_out[arm].get(c)
                if got is None:
                    cells.append("**MISSING**")
                elif c not in std_truth:
                    cells.append(f"⚠ FALSE POSITIVE: `{got[:60]}`")
                elif title_matches(got, official):
                    cells.append("✔")
                else:
                    cells.append(f"⚠ WRONG TITLE: `{got[:60]}`")
            lines.append(f"| {c} | {official[:80]} | " + " | ".join(cells) + " |")
        with open(os.path.join(root, "side_by_side", f"{safe}.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    print(f"[✔] Wrote {root}/{{{','.join(ARMS)},side_by_side}}/")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="score only the first N PDFs")
    ap.add_argument("--dump", action="store_true",
                    help="also write every arm's extracted disclosures for manual review")
    args = ap.parse_args()
    run(limit=args.limit)
    if args.dump:
        print()
        dump_extractions(limit=args.limit)


if __name__ == "__main__":
    main()
