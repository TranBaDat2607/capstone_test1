"""Extract candidate ESG keywords from regulatory PDFs using YAKE.

Reads Circular 96/2020/TT-BTC and the IFC-SSC sustainability reporting
handbook, runs unsupervised YAKE keyword extraction on each, and writes
the top-300 candidates per source (plus a merged deduplicated pool) to
`data_processing/yake_candidates.json`.

This is the candidate-generation step of the keyword-dictionary protocol:
output is a *pool* to be manually reviewed/pruned, not the final dictionary.

Run:
    python -m data_processing.extract_keywords
"""

from __future__ import annotations

import json
from pathlib import Path

import yake

from pdf_extractor import extract_full_text


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES: dict[str, Path] = {
    "tt_96_2020_btc": REPO_ROOT / "data" / "tt-96-btc" / "96-btc.pdf",
    "tt_08_2026_btc": REPO_ROOT / "data" / "tt-08-2026-btc" / "08-2026-btc.pdf",
    "ifc_ssc_handbook": REPO_ROOT
    / "data"
    / "IFC_SSC_handbook"
    / "SSC IFC Huong dan lap Bao cao Phat trien ben vung.pdf",
    "csi_2020": REPO_ROOT
    / "data"
    / "CSI_criteria"
    / "2020.6.22-9.9.59_Huong dan Bo Chi so CSI 2020.pdf",
}
OUTPUT_PATH = Path(__file__).resolve().parent / "yake_candidates.json"

TOP_K = 300
NGRAM_MAX = 3
DEDUP_LIM = 0.9
LANGUAGE = "vi"


def _read_pdf_text(pdf_path: Path) -> str:
    pages = extract_full_text(pdf_path)
    return "\n\n".join(p.text for p in pages)


def _run_yake(text: str) -> list[dict[str, float | str]]:
    extractor = yake.KeywordExtractor(
        lan=LANGUAGE,
        n=NGRAM_MAX,
        dedupLim=DEDUP_LIM,
        top=TOP_K,
    )
    raw = extractor.extract_keywords(text)
    # YAKE returns (keyword, score) where LOWER score = more relevant.
    return [{"keyword": kw, "score": float(score)} for kw, score in raw]


def main() -> None:
    per_source: dict[str, list[dict[str, float | str]]] = {}
    for name, pdf_path in SOURCES.items():
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing PDF: {pdf_path}")
        print(f"[{name}] reading {pdf_path.name} ...")
        text = _read_pdf_text(pdf_path)
        print(f"[{name}] extracted {len(text):,} chars; running YAKE (top={TOP_K}) ...")
        per_source[name] = _run_yake(text)
        print(f"[{name}] kept {len(per_source[name])} candidates")

    # Merge: keep best (lowest) YAKE score per unique keyword across sources.
    merged: dict[str, dict[str, object]] = {}
    for name, items in per_source.items():
        for it in items:
            kw = str(it["keyword"]).strip()
            key = kw.lower()
            score = float(it["score"])
            if key not in merged or score < float(merged[key]["score"]):
                merged[key] = {"keyword": kw, "score": score, "source": name}
            elif merged[key]["source"] != name:
                merged[key]["source"] = "both"
    merged_sorted = sorted(merged.values(), key=lambda x: float(x["score"]))

    payload = {
        "config": {
            "language": LANGUAGE,
            "ngram_max": NGRAM_MAX,
            "dedup_limit": DEDUP_LIM,
            "top_k_per_source": TOP_K,
        },
        "sources": {name: str(path) for name, path in SOURCES.items()},
        "per_source": per_source,
        "merged_pool": merged_sorted,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"\nWrote {len(merged_sorted)} unique candidates "
        f"({sum(len(v) for v in per_source.values())} raw) to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
