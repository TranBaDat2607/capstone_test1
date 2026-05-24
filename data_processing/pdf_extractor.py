"""Extract raw text from PDF annual reports, preserving page numbers.

Uses PyMuPDF (fitz) which handles Vietnamese diacritics correctly and
preserves reading order well for typical annual-report layouts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF


@dataclass
class PageText:
    page_number: int  # 1-indexed
    text: str


_WS_RE = re.compile(r"[ \t ]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SOFT_HYPHEN = "­"


def _clean_page_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw)
    text = text.replace(_SOFT_HYPHEN, "")
    # Join words broken by a hyphen at end-of-line: "phát-\ntriển" -> "pháttriển"
    text = re.sub(r"-\n(?=\w)", "", text)
    # Collapse horizontal whitespace
    text = _WS_RE.sub(" ", text)
    # Collapse 3+ blank lines to 2
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path) -> Iterator[PageText]:
    """Yield (page_number, cleaned_text) for each page of the PDF."""
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            cleaned = _clean_page_text(raw)
            if cleaned:
                yield PageText(page_number=i, text=cleaned)


def extract_full_text(pdf_path: Path) -> list[PageText]:
    return list(extract_pages(pdf_path))
