"""ESG sentence extraction pipeline orchestrator.

End-to-end: walk a folder of PDFs → extract pages → split sentences →
keyword pre-filter → semantic GRI mapping → write JSONL per PDF.

Usage:
    python -m data_processing.pipeline \
        --input "data/annual_report/Xây dựng - VLXD - BĐS/AAA - CTCP Nhựa An Phát Xanh" \
        --output "data/processed/esg_sentences"

    # Skip semantic stage (keyword-only pre-filter):
    python -m data_processing.pipeline --input ... --no-semantic

    # Pre-filter all sentences (no ESG filter at all, slowest):
    python -m data_processing.pipeline --input ... --no-prefilter
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .esg_keywords import find_matches
from .pdf_extractor import extract_pages
from .sentence_splitter import split_sentences


@dataclass
class ExtractedSentence:
    source_pdf: str
    page: int
    sentence_index: int  # 1-based, within the page
    text: str
    keyword_hits: list[dict]   # [{pillar, keyword}]
    gri_matches: list[dict]    # [{code, pillar, title_en, title_vi, score}]


def _iter_pdfs(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix.lower() == ".pdf":
        yield root
        return
    yield from sorted(p for p in root.rglob("*.pdf") if p.is_file())


def process_pdf(
    pdf_path: Path,
    use_prefilter: bool,
    use_semantic: bool,
    top_k: int,
    min_score: float,
) -> list[ExtractedSentence]:
    # Stage 1+2: pages + sentence segmentation
    candidates: list[ExtractedSentence] = []
    for page in extract_pages(pdf_path):
        for i, sent in enumerate(split_sentences(page.text), start=1):
            hits = find_matches(sent) if use_prefilter else []
            if use_prefilter and not hits:
                continue
            candidates.append(
                ExtractedSentence(
                    source_pdf=pdf_path.name,
                    page=page.page_number,
                    sentence_index=i,
                    text=sent,
                    keyword_hits=[{"pillar": p, "keyword": k} for p, k in hits],
                    gri_matches=[],
                )
            )

    # Stage 3: semantic GRI mapping (deferred import — heavy deps)
    if use_semantic and candidates:
        from .gri_mapper import map_sentences

        texts = [c.text for c in candidates]
        all_matches = map_sentences(texts, top_k=top_k, min_score=min_score)
        for c, matches in zip(candidates, all_matches):
            c.gri_matches = [
                {
                    "code": m.code,
                    "standard_code": m.standard_code,
                    "pillar": m.pillar,
                    "title_en": m.title_en,
                    "title_vi": m.title_vi,
                    "score": round(m.score, 4),
                }
                for m in matches
            ]
        # If we ran the semantic stage and didn't pre-filter, drop sentences
        # with no GRI match — they're not ESG-relevant.
        if not use_prefilter:
            candidates = [c for c in candidates if c.gri_matches]

    return candidates


def write_jsonl(rows: list[ExtractedSentence], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="PDF file or folder of PDFs (recursively scanned).")
    ap.add_argument("--output", required=True, help="Output folder for JSONL files (one per PDF).")
    ap.add_argument("--no-prefilter", dest="prefilter", action="store_false",
                    help="Skip the keyword pre-filter (run semantic stage on every sentence).")
    ap.add_argument("--no-semantic", dest="semantic", action="store_false",
                    help="Skip the semantic GRI mapper (keyword stage only).")
    ap.add_argument("--top-k", type=int, default=3, help="Top-K GRI matches per sentence.")
    ap.add_argument("--min-score", type=float, default=0.45,
                    help="Minimum cosine similarity to keep a GRI match.")
    args = ap.parse_args(argv)

    if not args.prefilter and not args.semantic:
        print("error: --no-prefilter and --no-semantic both set — nothing to filter on.",
              file=sys.stderr)
        return 2

    in_root = Path(args.input)
    out_root = Path(args.output)

    pdfs = list(_iter_pdfs(in_root))
    if not pdfs:
        print(f"No PDFs found under {in_root}", file=sys.stderr)
        return 1

    total_sents = 0
    for pdf in pdfs:
        try:
            rows = process_pdf(
                pdf,
                use_prefilter=args.prefilter,
                use_semantic=args.semantic,
                top_k=args.top_k,
                min_score=args.min_score,
            )
        except Exception as e:
            print(f"[FAIL] {pdf.name}: {e}", file=sys.stderr)
            continue
        rel = pdf.relative_to(in_root) if in_root.is_dir() else Path(pdf.name)
        out_path = out_root / rel.with_suffix(".jsonl")
        write_jsonl(rows, out_path)
        total_sents += len(rows)
        print(f"[OK]   {pdf.name}: {len(rows)} ESG sentences -> {out_path}")

    print(f"\nDone. {len(pdfs)} PDFs, {total_sents} ESG sentences total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
