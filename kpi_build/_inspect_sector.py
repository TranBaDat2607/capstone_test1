#!/usr/bin/env python3
"""Helper - dump the KPI-relevant passages from the sector sources for review."""

import pathlib
import re
import unicodedata

import fitz
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "sources"


def html_text(name: str) -> str:
    t = BeautifulSoup((SRC / name).read_bytes(), "html.parser").get_text("\n")
    t = unicodedata.normalize("NFC", t)  # lawnet serves NFD combining diacritics
    return re.sub(r"\n{2,}", "\n", t)


def pdf_text(name: str) -> str:
    return "\n".join(p.get_text() for p in fitz.open(SRC / name))


def dump(text: str, anchor: str, before: int, after: int, label: str):
    i = text.lower().find(anchor.lower())
    print("\n" + "=" * 88)
    print(f"{label}: anchor={anchor!r} at {i} (len={len(text)})")
    print("=" * 88)
    print(text[max(0, i - before): i + after] if i >= 0 else "  [not found]")


def main():
    qd = html_text("QD_2171_2021.html")
    dump(qd, "tổng số vật liệu xây", 400, 500, "QD 2171 - objectives")

    guide = unicodedata.normalize("NFC", pdf_text("SSC_IFC_sustainability_guide.pdf"))
    # The actual aspect list is the *second* occurrence (first is the table of contents)
    first = guide.find("Khía cạnh hoạt động kinh doanh")
    second = guide.find("Khía cạnh hoạt động kinh doanh", first + 1)
    print("\n" + "=" * 88, "\nSSC-IFC guide - aspect section at", second)
    print("=" * 88)
    print(guide[second: second + 1800] if second > 0 else "[not found]")


if __name__ == "__main__":
    main()
