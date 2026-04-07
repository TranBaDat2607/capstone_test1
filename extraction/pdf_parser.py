"""
extraction/pdf_parser.py

PDF text, table, and image extraction for ESG/Annual Report PDFs.

Uses pdfplumber as the primary backend (handles both digital-born PDFs and
scanned PDFs with embedded OCR text). Falls back to PyMuPDF (fitz) when
pdfplumber fails on a page. Images are always extracted via PyMuPDF (fitz)
as pdfplumber does not expose raw image bytes.

Public API
----------
parse(pdf_path)
    → list[page_dict]  (backward-compatible, one dict per page)

extract_and_save(pdf_path, output_dir)
    → dict  (full extraction result, also written to JSON)

Output JSON: <output_dir>/<pdf_stem>/extraction_result.json
Image files: <output_dir>/<pdf_stem>/images/IMG_<NNN>.png
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
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
# Regex for numeric data detection (ESG-relevant units)
# ---------------------------------------------------------------------------
_NUMERIC_RE = re.compile(
    r"\d[\d.,]*\s*(?:tonne|kwh|mwh|gwh|%|m3|m²|ha|usd|vnd|triệu|tỷ|million|billion|kg|lít|liter)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------

class PDFParser:
    """
    Extracts structured text, tables, and images from ESG / Annual Report PDFs.

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
    # Public API — backward-compatible parse()
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
            Tables include a 'bbox' key when extracted via pdfplumber.
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
    # Public API — full extraction with JSON output
    # ------------------------------------------------------------------

    def extract_and_save(
        self,
        pdf_path: str | Path,
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """
        Extract text, tables, and images from a PDF, enrich with KG metadata,
        and save the result to a structured JSON file.

        Parameters
        ----------
        pdf_path : str | Path
            Path to the PDF file.
        output_dir : str | Path
            Root output directory. Results are saved under
            <output_dir>/<pdf_stem>/extraction_result.json
            Images are saved to <output_dir>/<pdf_stem>/images/

        Returns
        -------
        dict
            The full extraction result dict (same structure as the JSON file).
        """
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        doc_id = pdf_path.stem
        img_dir = output_dir / doc_id / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        result_path = output_dir / doc_id / "extraction_result.json"

        # ---- Phase 1: parse text + tables ----
        pages = self.parse(pdf_path)

        # ---- Phase 2: build blocks ----
        blocks: list[dict] = []
        reading_order = 0
        img_counter = 0

        # Open fitz doc once for all image extraction
        fitz_doc = None
        if _HAS_FITZ:
            try:
                fitz_doc = fitz.open(str(pdf_path))
            except Exception as e:
                logger.warning("Could not open PDF with fitz for image extraction: %s", e)

        for page_data in pages:
            page_num = page_data["page_number"]
            page_text = page_data["text"]
            page_width = page_data["metadata"]["width"]
            page_height = page_data["metadata"]["height"]

            # -- Text block (one per page) --
            reading_order += 1
            blocks.append({
                "id": f"{doc_id}_blk_{reading_order:04d}",
                "type": "text",
                "page": page_num,
                "content": {
                    "text": page_text,
                },
                "layout": {
                    "bbox": [0.0, 0.0, round(page_width, 2), round(page_height, 2)],
                    "reading_order": reading_order,
                },
                "context": {
                    "before": "",   # filled in post-processing pass
                    "after": "",
                    "window_size": 200,
                },
                "metadata": {
                    "has_numeric_data": self._has_numeric_data(page_text),
                    "extraction_method": "pdfplumber",
                },
            })

            # -- Table blocks --
            for table in page_data.get("tables", []):
                reading_order += 1
                rows = table["rows"]
                bbox = table.get("bbox", [0.0, 0.0, round(page_width, 2), round(page_height, 2)])
                header = rows[0] if rows else []
                raw_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)

                # Context: text surrounding the table header in the page text
                ctx = self._get_context(page_text, " | ".join(str(c) for c in header) if header else "")

                blocks.append({
                    "id": f"{doc_id}_blk_{reading_order:04d}",
                    "type": "table",
                    "page": page_num,
                    "content": {
                        "rows": rows,
                        "header": header,
                        "raw": raw_text,
                    },
                    "layout": {
                        "bbox": [round(v, 2) for v in bbox],
                        "reading_order": reading_order,
                    },
                    "context": {
                        "before": ctx["before"],
                        "after": ctx["after"],
                    },
                    "metadata": {
                        "has_numeric_data": self._has_numeric_data(raw_text),
                        "extraction_method": "pdfplumber",
                    },
                })

            # -- Image blocks (via fitz) --
            if fitz_doc is not None:
                fitz_page = fitz_doc[page_num - 1]  # fitz is 0-indexed
                for img_info in fitz_page.get_images(full=True):
                    xref = img_info[0]
                    try:
                        pix = fitz.Pixmap(fitz_doc, xref)
                        if pix.n > 4:  # CMYK or CMYKA → convert to RGB
                            pix = fitz.Pixmap(fitz.csRGB, pix)

                        img_counter += 1
                        reading_order += 1
                        img_filename = f"IMG_{img_counter:03d}.png"
                        img_abs_path = img_dir / img_filename
                        pix.save(str(img_abs_path))

                        # Relative path from output_dir for portability
                        try:
                            img_rel_path = img_abs_path.relative_to(output_dir)
                        except ValueError:
                            img_rel_path = img_abs_path

                        # Bounding box on the page
                        try:
                            bbox_rect = fitz_page.get_image_bbox(img_info)
                            bbox = [
                                round(bbox_rect.x0, 2), round(bbox_rect.y0, 2),
                                round(bbox_rect.x1, 2), round(bbox_rect.y1, 2),
                            ]
                            w = bbox_rect.x1 - bbox_rect.x0
                            h = bbox_rect.y1 - bbox_rect.y0
                        except Exception:
                            bbox = [0.0, 0.0, round(page_width, 2), round(page_height, 2)]
                            w, h = page_width, page_height

                        blocks.append({
                            "id": f"{doc_id}_blk_{reading_order:04d}",
                            "type": "image",
                            "page": page_num,
                            "content": {
                                "path": str(img_rel_path).replace("\\", "/"),
                                "format": "png",
                            },
                            "layout": {
                                "bbox": bbox,
                                "reading_order": reading_order,
                            },
                            "context": {
                                "before": page_text[:200].strip(),
                                "after": page_text[-200:].strip() if len(page_text) > 200 else "",
                            },
                            "metadata": {
                                "content_type_hint": self._infer_content_type(w, h),
                                "extraction_method": "PyMuPDF",
                            },
                        })
                    except Exception as e:
                        logger.debug("Image extraction failed (xref %d, page %d): %s", xref, page_num, e)

        if fitz_doc is not None:
            fitz_doc.close()

        # ---- Phase 3: fill context.before / context.after for text blocks ----
        self._fill_text_context(blocks)

        # ---- Phase 4: assemble and save result ----
        result: dict[str, Any] = {
            "document": {
                "document_id": doc_id,
                "source_file": pdf_path.name,
                "extracted_at": datetime.now().strftime("%Y-%m-%d"),
                "total_pages": len(pages),
            },
            "blocks": blocks,
        }

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(
            "Saved extraction result → %s  (%d blocks: %d text, %d table, %d image)",
            result_path,
            len(blocks),
            sum(1 for b in blocks if b["type"] == "text"),
            sum(1 for b in blocks if b["type"] == "table"),
            sum(1 for b in blocks if b["type"] == "image"),
        )
        return result

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
                        # find_tables() returns Table objects with .bbox
                        raw_tables = page.find_tables()
                        for tbl in (raw_tables or []):
                            rows = tbl.extract() or []
                            clean_rows = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in rows
                            ]
                            # bbox: (x0, top, x1, bottom)
                            bbox = list(tbl.bbox) if hasattr(tbl, "bbox") else []
                            tables.append({"rows": clean_rows, "page": i, "bbox": bbox})
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
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_numeric_data(text: str) -> bool:
        """Return True if the text contains numeric ESG data (values with units)."""
        return bool(_NUMERIC_RE.search(text))

    @staticmethod
    def _infer_content_type(width: float, height: float) -> str:
        """
        Infer image content type from aspect ratio.

        wide  (w/h > 2.0) → chart / graph
        tall  (w/h < 0.6) → diagram / infographic
        else              → photo
        """
        if height == 0:
            return "photo"
        ratio = width / height
        if ratio > 2.0:
            return "chart"
        if ratio < 0.6:
            return "diagram"
        return "photo"

    @staticmethod
    def _get_context(page_text: str, anchor: str, window: int = 200) -> dict[str, str]:
        """
        Return text before and after `anchor` within `page_text`.

        Falls back to page start/end if anchor is not found.
        """
        if anchor and anchor in page_text:
            pos = page_text.index(anchor)
            before = page_text[max(0, pos - window):pos].strip()
            after_start = pos + len(anchor)
            after = page_text[after_start:after_start + window].strip()
        else:
            before = page_text[:window].strip()
            after = page_text[-window:].strip() if len(page_text) > window else ""
        return {"before": before, "after": after}

    @staticmethod
    def _fill_text_context(blocks: list[dict], window: int = 200) -> None:
        """
        Fill context.before / context.after for text blocks using adjacent blocks.
        Mutates blocks in-place. Other block types already have context set.
        """
        text_indices = [i for i, b in enumerate(blocks) if b["type"] == "text"]
        for rank, idx in enumerate(text_indices):
            blk = blocks[idx]
            # before: tail of the previous text block
            if rank > 0:
                prev_text = blocks[text_indices[rank - 1]]["content"]["text"]
                blk["context"]["before"] = prev_text[-window:].strip()
            # after: head of the next text block
            if rank < len(text_indices) - 1:
                next_text = blocks[text_indices[rank + 1]]["content"]["text"]
                blk["context"]["after"] = next_text[:window].strip()

    # ------------------------------------------------------------------
    # Text helpers
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
