#!/usr/bin/env python3
"""
Helper - inspect the downloaded sources so we can see the real structure of the
environmental & social disclosure section before writing the parser.

This does NOT produce the dataset; it only prints located text for review.

Run:
    python _inspect_sources.py
"""

import pathlib
import re

import fitz  # PyMuPDF
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "sources"


def html_to_text(path: pathlib.Path) -> str:
    raw = path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text("\n")
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{2,}", "\n", text))


def pdf_to_text(path: pathlib.Path) -> str:
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc)


def show_section(text: str, anchor: str, before: int, after: int, label: str) -> None:
    low = text.lower()
    idx = low.find(anchor.lower())
    print("\n" + "=" * 90)
    print(f"{label}: anchor={anchor!r} found_at={idx} total_len={len(text)}")
    print("=" * 90)
    if idx >= 0:
        print(text[max(0, idx - before): idx + after])
    else:
        # Fall back: show where key ESG terms appear at all
        for term in ["môi trường và xã hội", "nguyên vật liệu", "năng lượng",
                     "khí nhà kính", "người lao động"]:
            print(f"  '{term}' at {low.find(term.lower())}")


def main() -> None:
    # 1) Circular 96 - official gazette HTML
    tt96 = html_to_text(SRC / "TT96_2020_congbao.html")
    show_section(tt96, "tác động liên quan đến môi trường", 150, 2800,
                 "TT96 congbao")

    # 2) Circular 96 - Annex IV template (lookup site)
    tpl = html_to_text(SRC / "TT96_2020_phuluc4.html")
    show_section(tpl, "Quản lý nguồn nguyên vật liệu", 400, 2600,
                 "TT96 Phu luc IV")

    # 3) SSC-IFC guide PDF
    guide = pdf_to_text(SRC / "SSC_IFC_sustainability_guide.pdf")
    show_section(guide, "khí nhà kính", 300, 1200, "SSC-IFC guide")
    print("\nSSC-IFC guide total chars:", len(guide))


if __name__ == "__main__":
    main()
