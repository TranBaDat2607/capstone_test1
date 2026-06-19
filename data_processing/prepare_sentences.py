"""Extract every sentence from PDFs into a flat file for model classification.

This is the *local, CPU* half of the ViDeBERTa ESG pipeline. It reuses the same
PDF + sentence stages as `pipeline.py` but applies **no** keyword/GRI ESG filter
— the ViDeBERTa-v3-ESG model (run on Kaggle GPU) is the ESG detector now, so we
hand it every sentence.

Workflow (hybrid local + Kaggle):
    1. python -m data_processing.prepare_sentences \
           --input "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
           --output "data/interim/sentences/aaa_sentences.jsonl"   # <- this script
    2. Upload the resulting .jsonl (+ esg_classifier.py) as a Kaggle Dataset.
    3. Run notebooks/kaggle_esg_classify.ipynb on Kaggle (GPU + Internet on).
    4. Download classified.jsonl/.csv — that is the final ESG-tagged artifact.

Output row schema (one JSON object per line; also mirrored as CSV):
    {source_pdf, page, sentence_index, text}
These four fields are what the ViDeBERTa classifier (esg_classifier.py /
notebooks/kaggle_esg_classify.ipynb) reads back in.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .pdf_extractor import extract_pages
from .sentence_splitter import split_sentences


@dataclass
class Sentence:
    source_pdf: str
    page: int          # 1-based
    sentence_index: int  # 1-based, within the page
    text: str


def _iter_pdfs(root: Path) -> Iterable[Path]:
    """Yield a single PDF or every *.pdf under a folder (recursive, sorted)."""
    if root.is_file() and root.suffix.lower() == ".pdf":
        yield root
        return
    yield from sorted(p for p in root.rglob("*.pdf") if p.is_file())


def extract_sentences(pdf_path: Path) -> list[Sentence]:
    rows: list[Sentence] = []
    for page in extract_pages(pdf_path):
        for i, sent in enumerate(split_sentences(page.text), start=1):
            rows.append(
                Sentence(
                    source_pdf=pdf_path.name,
                    page=page.page_number,
                    sentence_index=i,
                    text=sent,
                )
            )
    return rows


def write_jsonl(rows: list[Sentence], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def write_csv(rows: list[Sentence], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so the Vietnamese text opens cleanly in Excel.
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_pdf", "page", "sentence_index", "text"])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True,
                    help="PDF file or folder of PDFs (recursively scanned).")
    ap.add_argument("--output", required=True,
                    help="Output .jsonl path. A sibling .csv is written too unless --no-csv.")
    ap.add_argument("--no-csv", dest="csv", action="store_false",
                    help="Skip writing the sibling .csv file.")
    args = ap.parse_args(argv)

    in_root = Path(args.input)
    out_path = Path(args.output)

    pdfs = list(_iter_pdfs(in_root))
    if not pdfs:
        print(f"No PDFs found under {in_root}", file=sys.stderr)
        return 1

    all_rows: list[Sentence] = []
    for pdf in pdfs:
        try:
            rows = extract_sentences(pdf)
        except Exception as e:  # noqa: BLE001 - report and continue over a folder
            print(f"[FAIL] {pdf.name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        all_rows.extend(rows)
        print(f"[OK]   {pdf.name}: {len(rows)} sentences")

    if not all_rows:
        print("No sentences extracted.", file=sys.stderr)
        return 1

    write_jsonl(all_rows, out_path)
    print(f"\nWrote {len(all_rows)} sentences from {len(pdfs)} PDF(s) -> {out_path}")
    if args.csv:
        csv_path = out_path.with_suffix(".csv")
        write_csv(all_rows, csv_path)
        print(f"Wrote CSV mirror -> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
