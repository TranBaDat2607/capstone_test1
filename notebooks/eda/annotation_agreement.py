"""Inter-annotator agreement + adjudicator precision on the 220-row annotated sample.

SUPERSEDED — READ THIS FIRST
    `evalu/` on branch `wip/gri-parser-and-eval` is the authority: `evalu/annotation.py`
    (`score()`), `evalu/iaa.py`, `evalu/ANNOTATION_PROTOCOL.md`. Once that branch merges,
    use it and delete this file. It is kept only because `evalu/` is not on `main` yet.

    Two things this script CANNOT see, because they live in the sheet's `_key`, which the
    spreadsheets do not carry:

      * **20 of the 220 rows are decoys** — attention checks that are not system
        predictions and must be excluded from precision. Everything below therefore
        computes over 220 where the protocol computes over 200, and its agreement figures
        run high (kappa 0.714 here vs 0.698 on the real pairs) because decoys are easy.
      * **The per-pair system verdict is recorded in `_key`.** This script re-derives it by
        re-hashing the adjudication cache, which is a reconstruction, not a reading.

    The protocol also mandates Gwet AC1 / Krippendorff alpha as the headline agreement
    metric, not the Cohen's kappa printed below.

Offline: reads only spreadsheets and JSON already on disk, no LLM call, no network call.

WHAT IT DOES
    1. Cohen's kappa between annotator A (`sheetA.xlsx`) and B (`sheetB.xlsx`)
       over the 220 (claim, evidence) pairs they both labelled.
    2. Recovers, for each pair, the verdict the ADJUDICATOR gave it, by
       re-deriving the content-addressed cache key the way step07 built it
       (`ContentCache.key(claim_text, evidence_text, meta)`), then reports the
       adjudicator's precision against the rows where A and B agree.

WHY THE JOIN IS DONE THIS WAY
    The spreadsheets carry text, not node indices, and the caches store only a
    sha256 -> verdict mapping (the texts are not in the cache). So the join goes
    text -> node index -> cache key:

        node_text(node)  ==  sheet's claim_text / evidence_text
        meta             ==  f"{cls} from {domain or 'news'}, year {year}"
        key              ==  sha256(json.dumps([claim, evidence, meta], sort_keys=True))

    A claim's text can match more than one node (39 of 220 rows), so the cache
    lookup is scoped to the issuer's OWN cache file, keyed off the sheet's
    `claim_company` column. That scoping is what makes the join unambiguous:
    with it, zero rows resolve to conflicting verdicts; without it, 15 do,
    because an unscoped search also hits other issuers' caches.

WHAT THE NUMBERS MEAN — AND DO NOT MEAN
    The 220 pairs are the system's POSITIVE predictions (the recovered verdicts
    are 117 contradicts / 86 supports / 0 irrelevant), so this yields PRECISION
    only. There is no recall here and no prevalence estimate.

    The caches predate commit 7c108f9 (2026-08-07), so these numbers describe the
    adjudicator BEFORE conduct retrieval was issuer-scoped, before the VN-aware
    min-topic-overlap gate, and before ADJUDICATE_SYSTEM was tightened against
    halo reasoning. Report them as "before the contamination fix".

Run from the repo root:  python notebooks/eda/annotation_agreement.py
"""

from __future__ import annotations

import collections
import hashlib
import html
import json
import math
import pathlib
import re
import sys
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.crosscheck.claims_vs_conduct import (  # noqa: E402
    node_domain,
    node_text,
    node_year,
)

RESOLVED_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
CROSSCHECK_DIR = REPO_ROOT / "graph_output" / "crosscheck"

# One cache file per issuer. AAA's run predates the per-ticker naming, so it is
# the unsuffixed `adjudication_cache_openai.json`; the other four are suffixed.
CACHE_OF_TICKER = {
    "AAA": "adjudication_cache_openai.json",
    "ACC": "adjudication_cache_openai_ACC.json",
    "ACG": "adjudication_cache_openai_ACG.json",
    "ADP": "adjudication_cache_openai_ADP.json",
    "AGG": "adjudication_cache_openai_AGG.json",
}

LABELS = ("supports", "contradicts", "irrelevant")


# --------------------------------------------------------------------------- xlsx
def read_xlsx(path: pathlib.Path) -> list[dict]:
    """Minimal .xlsx reader — handles both shared strings and inline strings, so
    it works on the human-filled sheets and on the tool-generated comparison
    sheet alike. Avoids adding openpyxl to a repo that deliberately keeps its
    dependency list short."""
    zf = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        raw = zf.read("xl/sharedStrings.xml").decode("utf-8")
        shared = [html.unescape(re.sub(r"<[^>]+>", "", m))
                  for m in re.findall(r"<si>(.*?)</si>", raw, re.S)]

    sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    rows: list[dict[str, str]] = []
    for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells: dict[str, str] = {}
        for cell in re.findall(r"<c[^>]*?>.*?</c>|<c[^>]*?/>", row_xml, re.S):
            ref = re.search(r'r="([A-Z]+)\d+"', cell)
            if not ref:
                continue
            typ = re.search(r't="(\w+)"', cell)
            val_m = re.search(r"<v>(.*?)</v>", cell, re.S)
            inline = re.search(r"<is>(.*?)</is>", cell, re.S)
            if inline is not None:
                value = html.unescape(re.sub(r"<[^>]+>", "", inline.group(1)))
            elif val_m is not None:
                value = html.unescape(val_m.group(1))
                if typ and typ.group(1) == "s":
                    value = shared[int(val_m.group(1))]
            else:
                value = ""
            cells[ref.group(1)] = value
        rows.append(cells)

    header = {name: col for col, name in rows[0].items()}
    return [{name: r.get(col, "") for name, col in header.items()} for r in rows[1:]]


# ------------------------------------------------------------------------ stats
def cohen_kappa(a: list[str], b: list[str]) -> tuple[float, float]:
    n = len(a)
    p_o = sum(1 for x, y in zip(a, b) if x == y) / n
    p_e = sum((a.count(l) / n) * (b.count(l) / n) for l in set(a) | set(b))
    return p_o, (p_o - p_e) / (1 - p_e)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — correct near 0 and 1, where the normal
    approximation produces intervals that run outside [0, 1]. The
    `contradicts` precision below sits close enough to 0 for that to matter."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def cache_key(*parts) -> str:
    """Byte-identical to `esg_kg.core.llm_cache.ContentCache.key`. Reimplemented
    rather than imported so that a future change to the kernel helper shows up
    here as a drop in the match rate instead of silently re-keying history."""
    value = parts[0] if len(parts) == 1 else parts
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def norm(s: object) -> str:
    return " ".join(str(s).split())


# ------------------------------------------------------------------------- main
def main() -> int:
    for path in (REPO_ROOT / "sheetA.xlsx", REPO_ROOT / "sheetB.xlsx", RESOLVED_GRAPH):
        if not path.exists():
            print(f"MISSING: {path}\nFetch it with: python src/esg_kg/core/datasync.py pull")
            return 1

    sheet_a = read_xlsx(REPO_ROOT / "sheetA.xlsx")
    sheet_b = read_xlsx(REPO_ROOT / "sheetB.xlsx")
    assert [r["pair_id"] for r in sheet_a] == [r["pair_id"] for r in sheet_b], \
        "sheetA and sheetB must list the same pairs in the same order"

    a = [r["relation"].strip().lower() for r in sheet_a]
    b = [r["relation"].strip().lower() for r in sheet_b]

    print("=" * 66)
    print("1. INTER-ANNOTATOR AGREEMENT")
    print("=" * 66)
    p_o, kappa = cohen_kappa(a, b)
    gold_idx = [i for i in range(len(a)) if a[i] == b[i]]
    print(f"  pairs labelled by both      : {len(a)}")
    print(f"  raw agreement               : {p_o:.4f}")
    print(f"  Cohen's kappa               : {kappa:.4f}")
    print(f"  gold subset (A == B)        : {len(gold_idx)} "
          f"({100 * len(gold_idx) / len(a):.1f}%)")
    print(f"  gold label distribution     : "
          f"{dict(collections.Counter(a[i] for i in gold_idx))}")
    print("  reference: CLIMATE-FEVER reports human-human kappa 0.684 on the "
          "analogous task\n  (docs/ANNOTATION_GUIDELINE.md section 7)")

    print()
    print("  disagreement matrix  A (row) x B (col):", LABELS)
    for la in LABELS:
        print(f"    {la:<12}",
              [sum(1 for x, y in zip(a, b) if x == la and y == lb) for lb in LABELS])

    # ---- recover the adjudicator's verdict for each annotated pair ----
    nodes = json.loads(RESOLVED_GRAPH.read_text(encoding="utf-8"))["nodes"]
    by_text: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        by_text.setdefault(norm(node_text(node)), []).append(i)

    caches = {}
    for ticker, fname in CACHE_OF_TICKER.items():
        path = CROSSCHECK_DIR / fname
        if path.exists():
            caches[ticker] = json.loads(path.read_text(encoding="utf-8"))["entries"]

    verdicts: list[str | None] = []
    ambiguous = 0
    for row in sheet_a:
        store = caches.get(row["claim_company"], {})
        hits = set()
        for ci in by_text.get(norm(row["claim_text"]), []):
            for xi in by_text.get(norm(row["evidence_text"]), []):
                meta = (f"{nodes[xi].get('class')} from "
                        f"{node_domain(nodes[xi]) or 'news'}, "
                        f"year {node_year(nodes[xi])}")
                key = cache_key(node_text(nodes[ci]), node_text(nodes[xi]), meta)
                if key in store:
                    hits.add(store[key]["verdict"])
        if len(hits) > 1:
            ambiguous += 1
        verdicts.append(next(iter(hits)) if len(hits) == 1 else None)

    print()
    print("=" * 66)
    print("2. ADJUDICATOR PRECISION  (pre-fix run; see module docstring)")
    print("=" * 66)
    print(f"  verdicts recovered          : {sum(1 for v in verdicts if v)}/{len(verdicts)}")
    print(f"  rows resolving ambiguously  : {ambiguous}  (must be 0)")
    print(f"  verdict distribution        : "
          f"{dict(collections.Counter(v for v in verdicts if v))}")
    print("  -> no 'irrelevant' verdicts: this sample IS the system's positive\n"
          "     predictions, so it measures PRECISION only, never recall.")

    print()
    for label in ("supports", "contradicts"):
        sub = [i for i, v in enumerate(verdicts) if v == label]
        sub_gold = [i for i in sub if a[i] == b[i]]
        correct = sum(1 for i in sub_gold if a[i] == label)
        lo, hi = wilson(correct, len(sub_gold))
        print(f"  system said {label!r}: n={len(sub)}, on gold subset n={len(sub_gold)}")
        print(f"     annotators concur : {correct}/{len(sub_gold)} = "
              f"{100 * correct / len(sub_gold):.1f}%  "
              f"(Wilson 95% CI {100 * lo:.1f}-{100 * hi:.1f}%)")
        print(f"     gold labels here  : "
              f"{dict(collections.Counter(a[i] for i in sub_gold))}")

    pos_gold = [i for i, v in enumerate(verdicts) if v and a[i] == b[i]]
    ok = sum(1 for i in pos_gold if a[i] != "irrelevant")
    lo, hi = wilson(ok, len(pos_gold))
    print()
    print(f"  any relation at all: {ok}/{len(pos_gold)} = "
          f"{100 * ok / len(pos_gold):.1f}%  (Wilson 95% CI {100 * lo:.1f}-{100 * hi:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
