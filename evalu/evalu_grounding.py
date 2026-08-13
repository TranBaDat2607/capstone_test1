#!/usr/bin/env python3
"""
evalu_grounding.py — A: round-trip grounding of extracted KPI values.

The question: **does the number the pipeline extracted actually appear on the
page it cites?**

This is the only metric in the suite that is genuine accuracy rather than a
proxy, and it is worth being precise about why, because
``docs/EVALUATION_WITHOUT_LABELS.md`` §11 states that no metric there is
accuracy. That statement is about the ADJUDICATION layer, where no ground truth
for "is this claim greenwashing?" exists and never will. It does not bind the
EXTRACTION layer: for the question "was this number in the document?", the
document itself is the ground truth. No annotator is required, and the answer is
not a matter of judgement.

It also fills a hole the pipeline's own quality report admits to. ``q1_accuracy``
in ``esg_kg/report/quality.py`` carries the note *"manual 30–50 node sample audit
is out of scope for this script"* — so extraction accuracy has never been
measured here. This measures it on every KPIObservation that can be checked,
automatically and offline.

**Where this lives or dies: Vietnamese number forms.** One quantity is written
many ways in these reports — `4.500.000`, `4,5 triệu`, `1.300 tỷ`, and negatives
in accounting parentheses `(843.923.914)`. A naive string search reports all of
these as hallucinations, and a metric that cries hallucination on correct
extractions is worse than no metric. ``number_variants`` enumerates the forms;
``test/test_evalu_metrics.py`` pins each one against a real example from this
corpus.

**What a match does and does not prove.** It proves the number is present on the
cited page. It does NOT prove it was attached to the right indicator, the right
period, or the right unit. This is therefore an upper bound on extraction
correctness, and the report says so.

Offline: reads labeled JSONL + the resolved graph. No LLM, no Neo4j, no network.
Run:  python evalu/evalu_grounding.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]

RESOLVED_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
LABELED_DIR = REPO_ROOT / "data" / "labeled"

# Digits only: with separators stripped, "4.500.000" and "4500000" become the
# same needle, and so do "(843.923.914)" and "843923914".
_STRIP_RE = re.compile(r"[.,\s]")

# A 1-digit needle appears on almost every page by chance, so a match would carry
# no information. Two digits is the shortest needle worth trusting.
MIN_DIGITS = 2

# Scale words are how these reports write large numbers; the digit string on the
# page is then the scaled-down value ("1.300 tỷ" for 1_300_000_000_000).
SCALES = (1, 1e3, 1e6, 1e9)


def normalize_page(text: str) -> str:
    """Page text reduced to a separator-free string for substring search."""
    return _STRIP_RE.sub("", text or "")


def number_variants(value: Any) -> Set[str]:
    """Every digit string this value might legitimately appear as.

    Sign is dropped before matching: Vietnamese financial statements write
    negatives in parentheses — `(843.923.914)` — so the digits on the page carry
    no minus for the search to find.
    """
    try:
        magnitude = abs(float(value))
    except (TypeError, ValueError):
        return set()

    out: Set[str] = set()
    for scale in SCALES:
        scaled = magnitude / scale
        # Scaling BELOW 1 is never a real reporting form and generates degenerate
        # needles: 3 / 1e3 formats as "0.00" -> "000", which is both meaningless
        # and long enough to slip past the MIN_DIGITS filter. It would then match
        # any page containing a run of zeros, and — worse — would drag values that
        # are unverifiable in principle into the denominator as if they had been
        # checked. Nobody writes "3" as "0,003 nghìn".
        if scaled < 1:
            continue
        if scaled != int(scaled):
            # Vietnamese uses the comma as decimal mark; stripping separators
            # turns "4,5" into "45", so the needle must be built the same way.
            out.add(f"{scaled:.1f}".replace(".", ""))
            out.add(f"{scaled:.2f}".replace(".", ""))
        out.add(str(int(scaled)))
    return {d for d in out if len(d) >= MIN_DIGITS}


def value_on_page(value: Any, page_text: str) -> bool:
    """True when `value` appears on the page in any of its legitimate forms."""
    variants = number_variants(value)
    if not variants:
        return False
    haystack = normalize_page(page_text)
    return any(v in haystack for v in variants)


class GroundingEvaluator:
    """Round-trip check: extracted KPI value vs the page it cites."""

    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root
        graph = self._load(RESOLVED_GRAPH) or {}
        self.nodes: List[Dict[str, Any]] = graph.get("nodes", [])

    @staticmethod
    def _load(path: Path) -> Any:
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _cited_docs(self) -> Set[str]:
        """Only the documents actually cited need indexing.

        Matters more than it looks: `data/labeled/` holds an 873k-sentence sector
        sweep alongside the AAA pilot, and indexing all of it to check ~4,900
        nodes would read hundreds of megabytes to no purpose.
        """
        return {str((n.get("properties") or {}).get("source_doc"))
                for n in self.nodes
                if n.get("class") == "KPIObservation"
                and (n.get("properties") or {}).get("source_doc")}

    def _page_index(self, wanted: Set[str]) -> Dict[tuple, str]:
        """(doc_stem, page) -> normalized page text, for cited docs only."""
        pages: Dict[tuple, List[str]] = defaultdict(list)
        for path in sorted(LABELED_DIR.glob("*/*.jsonl")):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    # Graph nodes carry the stem; the JSONL carries the filename.
                    stem = str(rec.get("source_pdf", "")).replace(".pdf", "")
                    if stem in wanted:
                        pages[(stem, rec.get("page"))].append(rec.get("text") or "")
        return {k: normalize_page(" ".join(v)) for k, v in pages.items()}

    def run(self) -> Dict[str, Any]:
        if not self.nodes:
            return {"key": "a_roundtrip_grounding",
                    "metric": "A — round-trip grounding của giá trị KPI",
                    "measured": False,
                    "reason": "khong co resolved_graph.json tren dia"}

        index = self._page_index(self._cited_docs())
        if not index:
            return {"key": "a_roundtrip_grounding",
                    "metric": "A — round-trip grounding của giá trị KPI",
                    "measured": False,
                    "reason": ("khong doc duoc trang nguon tu data/labeled/ "
                               "(chay datasync pull)")}

        kpis = [n for n in self.nodes if n.get("class") == "KPIObservation"]
        matched = mismatched = 0
        skipped: Counter = Counter()
        examples: List[Dict[str, Any]] = []
        per_doc: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ok": 0, "miss": 0})

        for node in kpis:
            p = node.get("properties") or {}
            value = p.get("value")
            if value is None:
                skipped["no_value"] += 1
                continue
            if not number_variants(value):
                # e.g. a 1-digit count: checkable in principle, but a match would
                # be luck, so it is excluded from the denominator rather than
                # silently counted as grounded.
                skipped["value_too_short_to_verify"] += 1
                continue
            doc, page = p.get("source_doc"), p.get("source_page")
            text = index.get((doc, page))
            if text is None:
                skipped["source_page_not_found"] += 1
                continue

            if any(v in text for v in number_variants(value)):
                matched += 1
                per_doc[str(doc)]["ok"] += 1
            else:
                mismatched += 1
                per_doc[str(doc)]["miss"] += 1
                if len(examples) < 10:
                    examples.append({
                        "title": p.get("title"), "value": value, "unit": p.get("unit"),
                        "kpi_id": p.get("kpi_id"),
                        "cited": f"{doc} p.{page}",
                    })

        denominator = matched + mismatched
        worst = sorted(({"doc": d, **v} for d, v in per_doc.items() if v["miss"]),
                       key=lambda x: -x["miss"])[:5]

        return {
            "key": "a_roundtrip_grounding",
            "metric": "A — round-trip grounding của giá trị KPI",
            "measured": True,
            "score": round(matched / denominator, 4) if denominator else None,
            "numerator": matched,
            "denominator": denominator,
            "mismatches": mismatched,
            "skipped": dict(skipped),
            "mismatch_examples": examples,
            "worst_documents": worst,
            "kpi_nodes_total": len(kpis),
            "note": ("Tỷ lệ giá trị KPI thực sự xuất hiện trên đúng trang mà node đó trích dẫn. "
                     "Văn bản gốc chính là ground truth, nên đây là ĐỘ ĐÚNG thật, không phải "
                     "proxy — và không cần ai gán nhãn."),
            "caveat": ("Khớp chỉ chứng minh con số CÓ MẶT trên trang. Nó không chứng minh con số "
                       "được gán đúng chỉ tiêu, đúng kỳ hay đúng đơn vị. Vì vậy đây là CẬN TRÊN "
                       "của độ đúng trích xuất."),
            "source": "resolved_graph.json + data/labeled/*/*.jsonl",
        }


if __name__ == "__main__":
    print(json.dumps(GroundingEvaluator().run(), indent=2, ensure_ascii=False))
