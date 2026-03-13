"""
extraction/pdf_parser.py

PDF text and table extraction for ESG/Annual Report PDFs.

Uses pdfplumber as the primary backend (handles both digital-born PDFs and
scanned PDFs with embedded OCR text). Falls back to PyMuPDF (fitz) when
pdfplumber fails on a page.

Output per page:
    {
        "page_number": int,
        "text": str,
        "tables": [{"rows": [[cell, ...], ...], "page": int}],
        "metadata": {"width": float, "height": float}
    }
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports — graceful degradation if libraries not installed
# ---------------------------------------------------------------------------
try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False
    logger.warning("pdfplumber not installed. PDF parsing will be limited.")

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

class PDFParser:
    """
    Extracts structured text and tables from ESG / Annual Report PDFs.

    Parameters
    ----------
    min_text_length : int
        Pages with fewer characters of extracted text are skipped.
    extract_tables : bool
        Whether to attempt table extraction (slower but richer).
    """

    def __init__(self, min_text_length: int = 50, extract_tables: bool = True) -> None:
        self.min_text_length = min_text_length
        self.extract_tables = extract_tables

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, pdf_path: str | Path) -> list[dict[str, Any]]:
        """
        Parse a PDF and return a list of page dicts.

        Parameters
        ----------
        pdf_path : str | Path
            Path to the PDF file.

        Returns
        -------
        list[dict]
            One dict per page: {page_number, text, tables, metadata}.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info("Parsing PDF: %s", pdf_path.name)

        if _HAS_PDFPLUMBER:
            pages = self._parse_with_pdfplumber(pdf_path)
        elif _HAS_FITZ:
            pages = self._parse_with_fitz(pdf_path)
        else:
            raise RuntimeError(
                "No PDF library available. Install pdfplumber: pip install pdfplumber"
            )

        # Filter out near-empty pages
        pages = [p for p in pages if len(p["text"]) >= self.min_text_length]
        logger.info("  Extracted %d pages with content from %s", len(pages), pdf_path.name)
        return pages

    def parse_to_chunks(
        self,
        pdf_path: str | Path,
        chunk_size: int = 1000,
        overlap: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Parse PDF and split text into overlapping chunks for RAG indexing.

        Returns
        -------
        list[dict]
            {chunk_id, text, source_page, source_file, char_start, char_end}
        """
        pages = self.parse(pdf_path)
        chunks: list[dict] = []
        chunk_id = 0

        for page in pages:
            text = page["text"]
            for start in range(0, len(text), chunk_size - overlap):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end].strip()
                if len(chunk_text) < 30:
                    continue
                chunks.append({
                    "chunk_id": f"{Path(pdf_path).stem}_p{page['page_number']}_c{chunk_id}",
                    "text": chunk_text,
                    "source_page": page["page_number"],
                    "source_file": Path(pdf_path).name,
                    "char_start": start,
                    "char_end": end,
                })
                chunk_id += 1

        return chunks

    def extract_tables_from_page(self, page_data: dict) -> list[dict]:
        """Return the tables list from a parsed page dict."""
        return page_data.get("tables", [])

    # ------------------------------------------------------------------
    # Backend implementations
    # ------------------------------------------------------------------

    def _parse_with_pdfplumber(self, pdf_path: Path) -> list[dict]:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = self._clean_text(text)

                tables = []
                if self.extract_tables:
                    try:
                        raw_tables = page.extract_tables()
                        for tbl in (raw_tables or []):
                            clean_rows = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in tbl
                            ]
                            tables.append({"rows": clean_rows, "page": i})
                    except Exception as e:
                        logger.debug("Table extraction failed on page %d: %s", i, e)

                pages.append({
                    "page_number": i,
                    "text": text,
                    "tables": tables,
                    "metadata": {
                        "width": float(page.width),
                        "height": float(page.height),
                    },
                })
        return pages

    def _parse_with_fitz(self, pdf_path: Path) -> list[dict]:
        pages = []
        doc = fitz.open(str(pdf_path))
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            text = self._clean_text(text)
            rect = page.rect
            pages.append({
                "page_number": i,
                "text": text,
                "tables": [],  # fitz table extraction requires extra work
                "metadata": {"width": rect.width, "height": rect.height},
            })
        doc.close()
        return pages

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalize whitespace and remove control characters."""
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def table_to_text(table: dict) -> str:
        """Convert a table dict to a readable pipe-delimited text representation."""
        lines = []
        for row in table.get("rows", []):
            lines.append(" | ".join(cell for cell in row))
        return "\n".join(lines)
