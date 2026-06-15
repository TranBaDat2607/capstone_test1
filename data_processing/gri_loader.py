"""Parse the official GRI Standards PDFs into structured JSON.

Source folder: data/raw/gri_standards/
Outputs (data/interim/gri_taxonomy/):
    disclosures.json  – list of disclosures (code, standard, title, requirements,
                        recommendations, guidance, year, pillar, superseded_by)
    sectors.json      – list of sector standards (code, name, topics)
    glossary.json     – defined terms from the official Glossary

Filename convention is the source of truth for classification:
    "GRI 1_ Foundation 2021.pdf"             -> universal (no disclosures)
    "GRI 2_ General Disclosures 2021.pdf"    -> universal (Disclosure 2-N)
    "GRI 3_ Material Topics 2021.pdf"        -> universal (Disclosure 3-N)
    "GRI 11_ Oil and Gas Sector 2021 V1.1.pdf" -> sector  (Topic 11.N)
    "GRI 101_ ... .pdf"                      -> topic   (Disclosure 101-N)  (newer)
    "GRI 201_ ... .pdf"                      -> topic   (Disclosure 201-N)  (classic)
    "GRI Standards Glossary 2025.pdf"        -> glossary
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "raw" / "gri_standards"
OUTPUT_DIR = ROOT / "data" / "interim" / "gri_taxonomy"


# ───────────────────────── filename classification ──────────────────────────

_FILENAME_RE = re.compile(r"^GRI\s+(?P<num>\d+)[_\s]", re.IGNORECASE)
_SECTOR_NUMS = {11, 12, 13, 14}
_UNIVERSAL_NUMS = {1, 2, 3}


@dataclass
class StandardMeta:
    standard_code: str           # "305", "2", "11", etc.
    standard_name: str           # "Emissions", "General Disclosures", etc.
    standard_year: str           # "2016", "2021", "2024"
    standard_type: str           # "universal" | "topic" | "sector" | "glossary"
    source_pdf: str


def _classify(pdf_path: Path) -> StandardMeta | None:
    name = pdf_path.name
    if "Glossary" in name:
        year = _extract_year(name) or ""
        return StandardMeta("glossary", "GRI Standards Glossary", year, "glossary", name)
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    num = int(m.group("num"))
    title, year = _parse_title_year(name, num)
    if num in _UNIVERSAL_NUMS:
        stype = "universal"
    elif num in _SECTOR_NUMS:
        stype = "sector"
    else:
        stype = "topic"
    return StandardMeta(str(num), title, year, stype, name)


_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _extract_year(name: str) -> str | None:
    m = _YEAR_RE.search(name)
    return m.group(1) if m else None


def _parse_title_year(name: str, num: int) -> tuple[str, str]:
    """Extract human title and year from a filename like
    'GRI 305_ Emissions 2016.pdf' -> ('Emissions', '2016')."""
    stem = Path(name).stem
    # Strip leading "GRI <num>_ " or "GRI <num> "
    body = re.sub(rf"^GRI\s+{num}[_\s]+", "", stem, flags=re.IGNORECASE).strip()
    # Trailing version "V1.1"
    body = re.sub(r"\s+V\d+(\.\d+)*\s*$", "", body)
    # Trailing language tag like "- English"
    body = re.sub(r"\s*-\s*English\s*$", "", body, flags=re.IGNORECASE)
    year = ""
    m = _YEAR_RE.search(body)
    if m:
        year = m.group(1)
        body = (body[: m.start()] + body[m.end():]).strip(" -_")
    # Collapse any whitespace artifacts
    body = re.sub(r"\s+", " ", body).strip(" -_")
    return body, year


# ─────────────────────── pillar classification ───────────────────────

# Hand-curated pillar mapping by standard number. This is the only place
# we inject opinion; everything else is verbatim from the PDFs.
_PILLAR_BY_STANDARD: dict[str, str] = {
    # Economic / Governance
    "201": "G", "202": "S", "203": "S", "204": "S",
    "205": "G", "206": "G", "207": "G",
    # Environmental
    "101": "E", "102": "E", "103": "E",
    "301": "E", "302": "E", "303": "E", "304": "E",
    "305": "E", "306": "E", "308": "E",
    # Social
    "401": "S", "402": "S", "403": "S", "404": "S", "405": "S",
    "406": "S", "407": "S", "408": "S", "409": "S", "410": "S",
    "411": "S", "413": "S", "414": "S", "415": "G",
    "416": "S", "417": "S", "418": "S",
    # GRI 2 General Disclosures – mostly Governance
    "2": "G",
    # GRI 3 Material Topics – Governance (meta-process)
    "3": "G",
}


def _pillar_for(standard_code: str) -> str:
    return _PILLAR_BY_STANDARD.get(standard_code, "X")


# ───────────────────────── text cleaning ──────────────────────────

_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("­", "")   # soft hyphen
    s = re.sub(r"-\n(?=\w)", "", s)
    s = _WS_RE.sub(" ", s)
    s = _MULTI_NL_RE.sub("\n\n", s)
    return s.strip()


def _strip_footer(text: str, standard_label: str) -> str:
    """Remove the per-page running footer + page number.
    Footer always ends with the standard label (e.g. "GRI 305: Emissions 2016")
    followed by a page number on its own line."""
    # Remove the page number on its own line at the very end
    text = re.sub(r"\n\s*\d+\s*$", "", text)
    # Remove the running footer if present
    if standard_label:
        esc = re.escape(standard_label)
        text = re.sub(rf"\n\s*{esc}\s*$", "", text)
    return text.rstrip()


# ───────────────────────── TOC parsing ─────────────────────────

# TOC entry: a line "Disclosure <code> <title>" followed by a numeric line (page).
# Codes:
#   Universal: "2-9", "3-1"
#   Topic:     "305-1", "101-1"
_DISCLOSURE_LINE_RE = re.compile(r"^Disclosure\s+(\d+-\d+|\d-\d+)\s+(.+?)\s*$")
# Sector standard topic line: "Topic 11.1 Climate change"
_TOPIC_LINE_RE = re.compile(r"^Topic\s+(\d+\.\d+)\s+(.+?)\s*$")
_PAGE_LINE_RE = re.compile(r"^\d+$")


@dataclass
class TocEntry:
    code: str                  # "305-1" or "11.1"
    kind: str                  # "disclosure" or "topic"
    title: str
    page: int                  # 1-indexed pdf page


_MAX_TITLE_CONTINUATION_LINES = 2


def _parse_toc(doc: fitz.Document, max_pages: int = 4) -> list[TocEntry]:
    """Parse the printed Content/Contents section near the front of the PDF.

    Each TOC entry is the line `Disclosure <code> <title>` (or `Topic <code> <title>`)
    followed by a numeric line giving the page. Titles can wrap onto the next
    1–2 lines, but we don't accumulate further or we risk swallowing unrelated
    paragraphs that follow some sector-standard TOC entries.
    """
    raw_lines: list[str] = []
    for pno in range(min(max_pages, len(doc))):
        raw_lines.extend(doc[pno].get_text("text").splitlines())

    entries: list[TocEntry] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        m_d = _DISCLOSURE_LINE_RE.match(line)
        m_t = _TOPIC_LINE_RE.match(line)
        match, kind = (m_d, "disclosure") if m_d else (m_t, "topic") if m_t else (None, "")
        if match:
            code = match.group(1)
            title = match.group(2).strip()
            extra = 0
            j = i + 1
            while j < len(raw_lines):
                nxt = raw_lines[j].strip()
                if _PAGE_LINE_RE.match(nxt):
                    entries.append(TocEntry(code=code, kind=kind, title=title, page=int(nxt)))
                    i = j
                    break
                if (
                    _DISCLOSURE_LINE_RE.match(nxt)
                    or _TOPIC_LINE_RE.match(nxt)
                    or extra >= _MAX_TITLE_CONTINUATION_LINES
                    or not nxt
                ):
                    # No page number found within the allowed window — skip.
                    break
                title += " " + nxt
                extra += 1
                j += 1
        i += 1
    return entries


# ───────────────────────── section splitting ─────────────────────────

# Section headers always appear as ALL-CAPS standalone words inside a disclosure.
_SECTION_HEADERS = ("REQUIREMENTS", "RECOMMENDATIONS", "GUIDANCE")
_SECTION_RE = re.compile(
    r"^(?:" + "|".join(_SECTION_HEADERS) + r")\s*$",
    re.MULTILINE,
)


def _split_sections(block: str) -> dict[str, str]:
    """Split a per-disclosure text block into {section: text}.

    The Disclosure header line is treated as 'overview' (everything before the
    first REQUIREMENTS heading is the introductory sentence).
    """
    out: dict[str, str] = {"overview": "", "requirements": "", "recommendations": "", "guidance": ""}

    parts: list[tuple[str, int, int]] = []  # (name, start, end)
    matches = list(_SECTION_RE.finditer(block))
    if not matches:
        out["overview"] = block.strip()
        return out

    # Overview = text before first section header
    first = matches[0]
    out["overview"] = block[: first.start()].strip()

    for idx, m in enumerate(matches):
        name = m.group(0).strip().lower()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        out[name] = (out.get(name, "") + "\n" + block[start:end].strip()).strip()
    return out


# ───────────────────────── disclosure header (in body) ─────────────────────────

# Used to find where exactly a disclosure starts on its page.
_BODY_DISCLOSURE_RE = re.compile(r"^Disclosure\s+(\d+-\d+|\d-\d+)\s+(.+)$", re.MULTILINE)


def _extract_disclosure_body(
    doc: fitz.Document,
    entries: list[TocEntry],
    entry_idx: int,
    standard_label: str,
) -> str:
    """Pull the text of disclosure[entry_idx] from its start page up to the
    start of the next disclosure (or end of document)."""
    ent = entries[entry_idx]
    start_page = ent.page - 1  # 0-indexed
    if entry_idx + 1 < len(entries):
        end_page = entries[entry_idx + 1].page - 1
        # The next disclosure might start on the same page or the next.
        # Inclusive read up through end_page; we'll trim on the marker below.
    else:
        end_page = len(doc) - 1

    pages_text: list[str] = []
    for pno in range(start_page, min(end_page + 1, len(doc))):
        raw = doc[pno].get_text("text")
        clean = _strip_footer(_normalize_text(raw), standard_label)
        pages_text.append(clean)

    block = "\n\n".join(pages_text)

    # Trim everything before our own Disclosure header
    start_marker = re.search(rf"Disclosure\s+{re.escape(ent.code)}\s+", block)
    if start_marker:
        block = block[start_marker.start():]

    # Trim everything from the next Disclosure header onwards
    if entry_idx + 1 < len(entries):
        next_code = entries[entry_idx + 1].code
        nxt = re.search(rf"\nDisclosure\s+{re.escape(next_code)}\s+", block)
        if nxt:
            block = block[: nxt.start()]
        else:
            # Sometimes the next item is a Topic / Glossary / Bibliography
            for marker in ("\nGlossary\n", "\nBibliography\n"):
                pos = block.find(marker)
                if pos > 0:
                    block = block[:pos]
                    break

    return block.strip()


# ───────────────────────── supersession ─────────────────────────

# Page footers in superseded standards say:
#   "Note: Requirement 1.2 and Disclosures 305-1 to 305-5 have been superseded by GRI 102: Climate Change 2025"
# Capture the full "GRI <num>: <Title> <Year>" form including the year.
_SUPERSEDED_RE = re.compile(
    r"have been superseded by\s+(?P<by>GRI\s+\d+:\s*[^\n]+?\s+\d{4})",
    re.IGNORECASE,
)


def _find_supersession(doc: fitz.Document) -> str | None:
    """Return the superseding standard name if mentioned anywhere in the PDF."""
    for page in doc:
        txt = page.get_text("text")
        # Collapse intra-line whitespace so wrapped notes still match.
        flat = re.sub(r"\s+", " ", txt)
        m = _SUPERSEDED_RE.search(flat)
        if m:
            return re.sub(r"\s+", " ", m.group("by")).strip()
    return None


# ───────────────────────── output dataclasses ─────────────────────────

@dataclass
class Disclosure:
    code: str                # "305-1" or "2-9"
    standard_code: str       # "305"
    standard_name: str       # "Emissions"
    standard_year: str       # "2016"
    standard_type: str       # "universal" | "topic"
    pillar: str              # "E" / "S" / "G" / "X"
    title: str               # "Direct (Scope 1) GHG emissions"
    overview: str = ""
    requirements: str = ""
    recommendations: str = ""
    guidance: str = ""
    superseded_by: str | None = None
    source_pdf: str = ""
    page: int = 0            # start page in the source PDF


@dataclass
class SectorTopic:
    code: str                # "11.1"
    title: str
    page: int
    body: str = ""           # raw text block for the topic


@dataclass
class SectorStandard:
    standard_code: str       # "11"
    standard_name: str       # "Oil and Gas Sector"
    standard_year: str       # "2021"
    source_pdf: str
    topics: list[SectorTopic] = field(default_factory=list)


# ───────────────────────── main loaders ─────────────────────────

def _standard_label(meta: StandardMeta) -> str:
    """The running footer text, e.g. 'GRI 305: Emissions 2016'."""
    if meta.standard_type == "glossary":
        return "GRI Standards Glossary 2025"
    base = f"GRI {meta.standard_code}: {meta.standard_name}"
    return f"{base} {meta.standard_year}".strip()


def load_topic_or_universal(pdf_path: Path, meta: StandardMeta) -> list[Disclosure]:
    out: list[Disclosure] = []
    with fitz.open(pdf_path) as doc:
        entries = [e for e in _parse_toc(doc) if e.kind == "disclosure"]
        superseded_by = _find_supersession(doc)
        label = _standard_label(meta)
        for idx, ent in enumerate(entries):
            body = _extract_disclosure_body(doc, entries, idx, label)
            sections = _split_sections(body)
            out.append(Disclosure(
                code=ent.code,
                standard_code=meta.standard_code,
                standard_name=meta.standard_name,
                standard_year=meta.standard_year,
                standard_type=meta.standard_type,
                pillar=_pillar_for(meta.standard_code),
                title=ent.title.strip(),
                overview=sections.get("overview", ""),
                requirements=sections.get("requirements", ""),
                recommendations=sections.get("recommendations", ""),
                guidance=sections.get("guidance", ""),
                superseded_by=superseded_by,
                source_pdf=meta.source_pdf,
                page=ent.page,
            ))
    return out


def load_sector(pdf_path: Path, meta: StandardMeta) -> SectorStandard:
    sector = SectorStandard(
        standard_code=meta.standard_code,
        standard_name=meta.standard_name,
        standard_year=meta.standard_year,
        source_pdf=meta.source_pdf,
    )
    with fitz.open(pdf_path) as doc:
        entries = [e for e in _parse_toc(doc) if e.kind == "topic"]
        label = _standard_label(meta)
        for idx, ent in enumerate(entries):
            # Pull text from this topic's page through the next topic's page.
            start = ent.page - 1
            end = (entries[idx + 1].page - 1) if idx + 1 < len(entries) else len(doc) - 1
            pages_text: list[str] = []
            for pno in range(start, min(end + 1, len(doc))):
                pages_text.append(_strip_footer(_normalize_text(doc[pno].get_text("text")), label))
            body = "\n\n".join(pages_text).strip()
            sector.topics.append(SectorTopic(code=ent.code, title=ent.title.strip(),
                                              page=ent.page, body=body))
    return sector


# Glossary: each entry is "Term" then its definition.
def load_glossary(pdf_path: Path, meta: StandardMeta) -> list[dict]:
    """Extract defined terms. The glossary structure has each term as a bold
    heading followed by its definition paragraph. Without font info we use a
    heuristic: short title-case line followed by longer definition text."""
    terms: list[dict] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            blocks = page.get_text("dict").get("blocks", [])
            for blk in blocks:
                if blk.get("type") != 0:
                    continue
                # Collect spans with their flags
                for line in blk.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    if not text:
                        continue
                    # Heuristic: bold-flagged spans usually mark term headings.
                    if any(int(s.get("flags", 0)) & 16 for s in spans) and len(text) < 80:
                        terms.append({"term": text, "definition": ""})
                    elif terms and not terms[-1]["definition"]:
                        terms[-1]["definition"] = text
                    elif terms:
                        terms[-1]["definition"] += " " + text
    # Filter: keep only entries that look like real definitions
    return [t for t in terms if 2 <= len(t["term"]) <= 80 and len(t["definition"]) > 20]


# ───────────────────────── orchestrator ─────────────────────────

def build_all(source_dir: Path = SOURCE_DIR, output_dir: Path = OUTPUT_DIR) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    disclosures: list[Disclosure] = []
    sectors: list[SectorStandard] = []
    glossary: list[dict] = []

    pdfs = sorted(source_dir.glob("*.pdf"))
    for pdf in pdfs:
        meta = _classify(pdf)
        if not meta:
            print(f"[skip] {pdf.name}: unrecognized filename")
            continue
        try:
            if meta.standard_type in ("universal", "topic"):
                ds = load_topic_or_universal(pdf, meta)
                disclosures.extend(ds)
                print(f"[ok]   {pdf.name}: {len(ds)} disclosures")
            elif meta.standard_type == "sector":
                s = load_sector(pdf, meta)
                sectors.append(s)
                print(f"[ok]   {pdf.name}: {len(s.topics)} topics")
            elif meta.standard_type == "glossary":
                glossary = load_glossary(pdf, meta)
                print(f"[ok]   {pdf.name}: {len(glossary)} terms")
        except Exception as e:
            print(f"[fail] {pdf.name}: {e!r}")

    with open(output_dir / "disclosures.json", "w", encoding="utf-8") as f:
        json.dump([asdict(d) for d in disclosures], f, ensure_ascii=False, indent=2)
    with open(output_dir / "sectors.json", "w", encoding="utf-8") as f:
        json.dump([
            {**asdict(s), "topics": [asdict(t) for t in s.topics]}
            for s in sectors
        ], f, ensure_ascii=False, indent=2)
    with open(output_dir / "glossary.json", "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)

    return {
        "disclosures": len(disclosures),
        "sectors": len(sectors),
        "sector_topics": sum(len(s.topics) for s in sectors),
        "glossary_terms": len(glossary),
    }


if __name__ == "__main__":
    summary = build_all()
    print("\nSummary:", json.dumps(summary, indent=2))
