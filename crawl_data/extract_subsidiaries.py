"""Step 4c — trich danh sach cong ty con/lien ket tu bao cao thuong nien (Gemini-vision redesign).

Design note: see `docs/SUBSIDIARY_EXTRACTION_LLM_VISION_PLAN.md` for the full history — this
stage previously reconstructed table columns from PyMuPDF line geometry (x0 clustering) plus a
Tesseract-OCR fallback for font-broken/scanned PDFs (~940 lines). That approach was accurate but
heavy to review/merge and needed an external OCR binary. Testing showed sending the page as an
IMAGE to Gemini (instead of scrambled reading-order text) matches or beats it in accuracy on the
same calibration set (AAA/KBC/VIC-2025), and rescues font-broken pages without any OCR install
(Gemini reads pixels, same as OCR, without the external dependency).

ALGORITHM (per document)
0. Font sanity gate (unchanged from the old design): sample pages, measure the fraction of
   letters carrying a Vietnamese diacritic. Below a floor, the PDF is font-broken or scanned —
   auto page-location for that case is not yet built (see plan doc §6), so such files are marked
   extraction_method="unusable" for now, same as the pre-OCR baseline.
1. Locate: scan every text line for a *heading* ("Danh sách Công ty con", "THÔNG TIN VỀ CÁC CÔNG
   TY CON", "Phụ lục 1 – Danh sách công ty con", ...). Each heading opens a *segment*
   (relationship=subsidiary|associate) that runs until the next heading or a content-based stop
   rule. Ported unchanged from the geometric version — this part was never the complex bit.
2. Render: every page touched by a segment -> PNG (PyMuPDF pixmap, 200 dpi).
3. Extract: send the segment's page image(s) + a Vietnamese prompt to Gemini with a JSON
   response_schema (same genai.Client structured-output pattern as step01/step02). The model
   reads the table directly off the rendered page — no manual column reconstruction.
4. Validate: every extracted name is split into ascii-folded tokens; a row is confidence="high"
   only if >=80% of its name tokens are found in the page's own native PyMuPDF text (order-
   agnostic — the native text is reading-order, not column-order, so a wrapped name's tokens can
   be non-contiguous there even when correct; see plan doc §3/§4). Rows from a font-broken
   segment never reach this (whole file is "unusable"), so there is no case where an unverifiable
   row is silently marked "high".

OUTPUT: config/subsidiaries/<TICKER>.json — SAME schema as the geometric version, so
esg_news_crawler/resolver.py (_AnnualReportSource) needs no changes.

  python crawl_data/extract_subsidiaries.py --doc AAA_Baocaothuongnien_2025    # single file
  python crawl_data/extract_subsidiaries.py --doc AAA --dry-run                # print JSON only
  python crawl_data/extract_subsidiaries.py --latest-per-ticker --limit-docs 5 # stress a handful
  python crawl_data/extract_subsidiaries.py --latest-per-ticker                # full corpus run
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from dotenv import load_dotenv
from PIL import Image
from google import genai
from google.genai import types

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_DIR = REPO_ROOT / "Bao_cao_thuong_nien"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "config" / "subsidiaries"
DEFAULT_MODEL = "gemini-flash-latest"  # gemini-2.5-flash is no longer issued to new API keys/
                                        # projects as of 2026-07 (404 "no longer available to
                                        # new users") -- verify with client.models.list() if
                                        # this stops working, don't assume the old docs' model.
DEFAULT_RATE_LIMIT = 12  # conservative calls/minute for a single free-tier key

FILENAME_RE = re.compile(r"(\d{4}|Unknown)_([A-Za-z0-9]{2,6})_Baocaothuongnien_(\d{4})", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 0. Font sanity check (unchanged from the geometric version)
# ---------------------------------------------------------------------------

_VN_DIACRITIC_RE = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
FONT_SANITY_SAMPLE_PAGES = 30
# Calibrated against known-good (VIC 2023, ratio~0.24) and known-broken (VIC 2025, ratio~0.10)
# samples; 0.15 sits comfortably between them.
FONT_SANITY_MIN_DIACRITIC_RATIO = 0.15


def font_sanity_ratio(doc: fitz.Document) -> float:
    n = min(FONT_SANITY_SAMPLE_PAGES, doc.page_count)
    text = "\n".join(doc[i].get_text("text") for i in range(n))
    n_letters = len(_LETTER_RE.findall(text))
    if n_letters == 0:
        return 0.0
    return len(_VN_DIACRITIC_RE.findall(text)) / n_letters


# ---------------------------------------------------------------------------
# 1. Locate: line collection + heading / segment detection (unchanged)
# ---------------------------------------------------------------------------

LANDSCAPE_2UP_MIN_WIDTH = 900.0  # VIC's 2-up pages measure ~1190pt; plain A4 portrait ~595pt
PAGE_MARGIN_BAND = 65.0  # a bare page number sitting this close to the top/bottom edge is furniture
STT_INT_RE = re.compile(r"^\d{1,4}$")


@dataclass
class Line:
    page: int       # 0-indexed
    col: int        # 0 or 1 (2-up page column group)
    x0: float
    y0: float
    text: str

    @property
    def ordinal(self) -> float:
        return self.page * 1_000_000 + self.col * 500_000 + self.y0


def collect_lines(doc: fitz.Document) -> List[Line]:
    lines: List[Line] = []
    for p in range(doc.page_count):
        page = doc[p]
        half = page.rect.width / 2 if page.rect.width >= LANDSCAPE_2UP_MIN_WIDTH else None
        height = page.rect.height
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for ln in block.get("lines", []):
                text = "".join(s["text"] for s in ln.get("spans", [])).strip()
                if not text:
                    continue
                x0, y0 = ln["bbox"][0], ln["bbox"][1]
                if STT_INT_RE.match(text) and (y0 < PAGE_MARGIN_BAND or y0 > height - PAGE_MARGIN_BAND):
                    continue  # running page-number footer/header, not table content
                col = 1 if (half is not None and x0 >= half) else 0
                x0_local = x0 - half if col == 1 else x0
                lines.append(Line(page=p, col=col, x0=x0_local, y0=y0, text=text))
    return lines


def heading_relationship(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped or len(stripped) > 100:
        return None
    low = stripped.lower()
    has_sub = "công ty con" in low
    has_assoc = "công ty liên kết" in low
    if not (has_sub or has_assoc):
        return None
    # Deliberately NOT "line is ALL CAPS" -- that also fires on subtype sub-headings ("CÔNG TY
    # CON TRỰC TIẾP") and unrelated ALL-CAPS section titles that happen to mention "công ty con"
    # in passing. Every true table heading found across calibration samples contains one of
    # these three words, so requiring one is strictly more precise with no coverage loss.
    strong = "danh sách" in low or "thông tin" in low or "phụ lục" in low
    if not strong:
        return None
    return "associate" if has_assoc else "subsidiary"


@dataclass
class Segment:
    relationship: str
    start_ordinal: float
    end_ordinal: float


MAX_SEGMENT_PAGES = 8  # generous vs. the largest observed table run (VIC's 6-page appendix)


def find_segments(doc: fitz.Document, lines: List[Line]) -> List[Segment]:
    headings = []
    for ln in lines:
        rel = heading_relationship(ln.text)
        if rel:
            headings.append((ln.ordinal, ln.page, rel))
    headings.sort()

    page_texts_low: List[str] = ["" for _ in range(doc.page_count)]
    for ln in lines:
        page_texts_low[ln.page] += " " + ln.text.lower()
    header_repeat_pages = {ln.page for ln in lines if ln.text.strip().lower() in ("tt", "stt")}

    def page_has_signal(p: int) -> bool:
        # Deliberately NOT "any page with a bare number" -- a financial-statements-heavy annual
        # report has numbers on nearly every page. Two signals instead: the section keyword
        # itself, or a repeated "TT"/"STT" column header (a multi-page table reprints its header
        # on every continuation page but doesn't repeat "công ty con" on them).
        return ("công ty con" in page_texts_low[p] or "công ty liên kết" in page_texts_low[p]
                or p in header_repeat_pages)

    segments: List[Segment] = []
    for i, (ordinal, page, rel) in enumerate(headings):
        if i + 1 < len(headings):
            end_ordinal = headings[i + 1][0]
        else:
            end_page = page
            for p in range(page, min(page + MAX_SEGMENT_PAGES, doc.page_count)):
                if p == page or page_has_signal(p):
                    end_page = p
                else:
                    break
            end_ordinal = (end_page + 1) * 1_000_000  # through the end of end_page
        segments.append(Segment(relationship=rel, start_ordinal=ordinal, end_ordinal=end_ordinal))
    return segments


# ---------------------------------------------------------------------------
# 1b. Locate fallback: content-scored page scan (when the heading regex finds nothing)
# ---------------------------------------------------------------------------
#
# find_segments() above assumes the FIRST line matching the heading regex is the real table --
# true for the AAA/KBC/VIC calibration set, but false whenever the same phrase also appears in
# the table of contents (a Vietnamese annual report's "Mục lục" reprints every chapter title,
# including "Công ty con, Công ty liên kết", pointing at a page dozens/hundreds of pages later).
# Confirmed on real corpus samples (AGG, CDC, CTR): the ToC line matches the heading regex, the
# real table sits far downstream and never gets located, and the ticker was wrongly marked
# "unusable" -- not because it has no subsidiaries, but because locate stopped at the ToC.
#
# This fallback scores EVERY page that so much as mentions "công ty con"/"công ty liên kết" by
# how much it structurally looks like a company table -- lines starting with "Công ty Cổ phần/
# TNHH/CTCP" (candidate row names) and lines carrying a "%" value (ownership/voting columns). A
# ToC page has neither (it lists chapter titles + page numbers, not company names), so it scores
# ~0 and is skipped; a real table page scores high regardless of which exact heading wording the
# document used. Runs ONLY when find_segments() returns nothing, so the fast/simple path stays
# unchanged for the majority of documents already validated against it.

_COMPANY_LINE_RE = re.compile(r"^(cong ty|cty|ctcp)\b")
_PERCENT_LINE_RE = re.compile(r"\d[\d.,]*\s*%")
MIN_COMPANY_LINES_FOR_TABLE = 3
MIN_COMPANY_LINES_WITH_PERCENT = 2
MIN_PERCENT_LINES_FOR_TABLE = 2


def _page_table_score(page_lines: List["Line"]) -> Tuple[int, int]:
    n_company = sum(1 for ln in page_lines if _COMPANY_LINE_RE.match(ascii_fold(ln.text)))
    n_percent = sum(1 for ln in page_lines if _PERCENT_LINE_RE.search(ln.text))
    return n_company, n_percent


def _page_looks_like_table(page_lines: List["Line"]) -> bool:
    n_company, n_percent = _page_table_score(page_lines)
    # A small company's single associate/subsidiary is sometimes disclosed as one key-value block
    # ("Tên công ty: X / Tỷ lệ vốn góp: Y%") rather than a grid table -- that only scores 1
    # company-line + 1 percent-line, below the thresholds calibrated for multi-row grids (see
    # DTT: real 1-associate disclosure, missed until this condition was added). Accepting any
    # n_company>=1 page is safe even though it also re-admits some narrative false positives
    # (e.g. C32 p.63 scored 1+2) -- extract_segment's prompt already returns companies=[] for a
    # page with no real table, so a re-admitted false positive costs one extra API call, not bad
    # data (see PROMPT_TMPL_MIXED's explicit "no table -> empty" instruction).
    return (n_company >= MIN_COMPANY_LINES_FOR_TABLE
            or (n_company >= MIN_COMPANY_LINES_WITH_PERCENT and n_percent >= MIN_PERCENT_LINES_FOR_TABLE)
            or (n_company >= 1 and n_percent >= 1))


# ---------------------------------------------------------------------------
# 1c. Locate fallback for font-broken/scanned PDFs: vision page classification
# ---------------------------------------------------------------------------
#
# Neither find_segments() (text heading regex) nor find_segments_by_content() (text company-
# name/percent density) can run on a font-broken or scanned PDF -- both need PyMuPDF's extracted
# text, and that text is either garbage (font substitution corrupts diacritics silently) or
# nonexistent (a scanned page has no text layer at all). The page RENDERS correctly either way
# (see module docstring), so the only way in is to ask Gemini to look at the pages directly, the
# same way a human would flip through the PDF. Runs ONLY when font_sanity_ratio() fails the gate.
#
# Cost control: analysis of the 87 tickers already located successfully showed the real table's
# position ranges from 1.5% to 100% of the way through the document (median ~25%) with no usable
# clustering -- restricting the scan to e.g. "the last third" would silently miss real tables, so
# every page must be considered. To keep this affordable, pages are thumbnailed at low DPI and
# classified in batches (one Gemini call judges a whole chunk at once, not one call per page);
# only the pages a batch call flags get re-rendered at full DPI for the real extraction call.

PAGE_LOCATE_THUMB_DPI = 100
PAGE_LOCATE_CHUNK_SIZE = 15

PAGE_LOCATE_SCHEMA = {
    "type": "object",
    "properties": {"pages": {"type": "array", "items": {"type": "integer"}}},
    "required": ["pages"],
}

PAGE_LOCATE_PROMPT_TMPL = """Đây là ảnh các trang {pages_desc} của một báo cáo thường niên công ty
niêm yết Việt Nam, ĐÚNG THEO THỨ TỰ đó (ảnh đầu tiên = trang {pages_desc_first}, ảnh cuối = trang
{pages_desc_last}, các ảnh ở giữa theo đúng thứ tự trang tăng dần).

Cho biết những trang nào trong số này chứa BẢNG liệt kê "Danh sách Công ty con" và/hoặc "Danh sách
Công ty liên kết" (bảng có cột tên công ty + tỷ lệ sở hữu/biểu quyết, thường nằm trong phần
Thuyết minh báo cáo tài chính hợp nhất).

KHÔNG tính các trường hợp sau (không phải bảng thật, đừng trả về):
- Trang Mục lục (chỉ có tên chương + số trang, không có tên công ty cụ thể).
- Đoạn văn chỉ NHẮC ĐẾN cụm từ "công ty con"/"công ty liên kết" mà không có bảng tên công ty đi kèm.

Trả về JSON {{"pages": [số trang tuyệt đối, ...]}} (dùng đúng số trang đã cho ở trên, không phải
thứ tự ảnh), mảng rỗng nếu không trang nào trong nhóm này là bảng thật."""


def _pages_to_mixed_segments(pages: List[int]) -> List[Segment]:
    """Group adjacent/near-adjacent qualifying pages into segments (a table can span a few
    pages). relationship="mixed" -- both fallback locators (content-scoring and vision
    page-classification) find table PAGES, not a specific heading, so neither can assert
    whether the table(s) found are subsidiary, associate, or both; the LLM decides per row
    instead (see extract_segment's PROMPT_TMPL_MIXED branch)."""
    if not pages:
        return []
    pages = sorted(pages)
    groups: List[List[int]] = [[pages[0]]]
    for p in pages[1:]:
        if p - groups[-1][-1] <= 2:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [Segment(relationship="mixed",
                     start_ordinal=grp[0] * 1_000_000,
                     end_ordinal=(grp[-1] + 1) * 1_000_000)
            for grp in groups]


def find_segments_by_content(doc: fitz.Document, lines: List[Line]) -> List[Segment]:
    lines_by_page: Dict[int, List[Line]] = {}
    for ln in lines:
        lines_by_page.setdefault(ln.page, []).append(ln)

    mentions_page = {
        p for p, pls in lines_by_page.items()
        if any("công ty con" in ln.text.lower() or "công ty liên kết" in ln.text.lower() for ln in pls)
    }
    table_pages = [p for p in mentions_page if _page_looks_like_table(lines_by_page[p])]
    return _pages_to_mixed_segments(table_pages)


def locate_pages_via_vision(doc: fitz.Document, extractor: "SubsidiaryExtractor",
                             chunk_size: int = PAGE_LOCATE_CHUNK_SIZE) -> List[Segment]:
    """Font-broken/scanned fallback: thumbnail every page, classify in chunks via Gemini vision,
    return segments built from whichever pages got flagged as a real table. See module-level
    comment above PAGE_LOCATE_SCHEMA for cost rationale (why the whole doc must be scanned, and
    why in low-DPI batches rather than one full-res call per page)."""
    all_pages = list(range(doc.page_count))
    found_pages: List[int] = []
    for i in range(0, len(all_pages), chunk_size):
        chunk = all_pages[i:i + chunk_size]
        thumbs = render_pages(doc, chunk, dpi=PAGE_LOCATE_THUMB_DPI)
        found_pages.extend(extractor.classify_pages(chunk, thumbs))
    return _pages_to_mixed_segments(found_pages)


_ASCII_FOLD_RE = re.compile(r"[^a-z0-9]+")


def ascii_fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d")
    return _ASCII_FOLD_RE.sub(" ", s).strip()


def ticker_and_year_from_filename(path: Path) -> Tuple[Optional[str], Optional[int]]:
    m = FILENAME_RE.search(path.stem)
    if not m:
        return None, None
    return m.group(2).upper(), int(m.group(3))


# ---------------------------------------------------------------------------
# 2. Render segment pages to images
# ---------------------------------------------------------------------------

RENDER_DPI = 200


def render_pages(doc: fitz.Document, page_nums: List[int], dpi: int = RENDER_DPI) -> List[bytes]:
    imgs = []
    for p in page_nums:
        pix = doc[p].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        imgs.append(buf.getvalue())
    return imgs


# ---------------------------------------------------------------------------
# 3. Extract via Gemini vision (structured output, same pattern as step01/step02)
# ---------------------------------------------------------------------------

ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stt": {"type": "integer", "nullable": True},
                    "name": {"type": "string"},
                    "alias": {"type": "string", "nullable": True},
                    "relationship": {"type": "string", "enum": ["subsidiary", "associate"]},
                    "subtype": {"type": "string", "enum": ["direct", "indirect"], "nullable": True},
                    "capital": {"type": "string", "nullable": True},
                    "ownership_pct": {"type": "number", "nullable": True},
                    "voting_pct": {"type": "number", "nullable": True},
                    "address": {"type": "string", "nullable": True},
                    "sector": {"type": "string", "nullable": True},
                },
                "required": ["name", "relationship"],
            },
        }
    },
    "required": ["companies"],
}

PROMPT_TMPL = """Đây là (các) trang thuyết minh báo cáo tài chính hợp nhất của một công ty niêm yết
Việt Nam, chứa bảng "{heading}". Đọc đúng bảng trong ảnh và trả về danh sách công ty {rel} dưới
dạng JSON theo schema đã cho.

QUY TẮC BẮT BUỘC:
- Chỉ lấy tên công ty và số liệu ĐỌC ĐƯỢC TRONG ẢNH. Không bịa, không suy diễn.
- ownership_pct = cột "Tỷ lệ lợi ích" (nếu bảng chỉ có 1 cột tỷ lệ gộp "Tỷ lệ sở hữu" thì dùng
  cho ownership_pct, để voting_pct = null).
- voting_pct = cột "Tỷ lệ biểu quyết" / "Tỷ lệ quyền biểu quyết" nếu có cột riêng.
- alias = cột "Tên viết tắt" nếu bảng có cột này.
- relationship = "{rel}" cho toàn bộ dòng trong bảng này.
- Nếu bảng phân biệt "trực tiếp"/"gián tiếp" thì set subtype tương ứng, else null.

Trả về JSON theo schema, KHÔNG kèm giải thích."""

# Used when locate fell back to find_segments_by_content() (Segment.relationship == "mixed") --
# the content-scoring fallback finds table PAGES, not a specific heading, so it can't assert
# whether the table(s) on those pages are subsidiary, associate, or both; the model decides
# per row instead of trusting a hardcoded value (see find_segments_by_content's docstring).
PROMPT_TMPL_MIXED = """Đây là (các) trang thuyết minh báo cáo tài chính hợp nhất của một công ty
niêm yết Việt Nam, có thể chứa bảng "Danh sách Công ty con" và/hoặc "Danh sách Công ty liên kết"
(một hoặc cả hai loại bảng có thể xuất hiện). Đọc đúng (các) bảng trong ảnh và trả về danh sách
công ty dưới dạng JSON theo schema đã cho.

QUY TẮC BẮT BUỘC:
- Chỉ lấy tên công ty và số liệu ĐỌC ĐƯỢC TRONG ẢNH. Không bịa, không suy diễn.
- Nếu trang KHÔNG chứa bảng danh sách công ty con/liên kết nào (VD: đây là trang mục lục, trang
  thuyết minh chính sách kế toán chung...), trả về companies=[] -- KHÔNG cố lấy đại tên công ty
  nào xuất hiện trong đoạn văn.
- relationship: xác định RIÊNG cho từng dòng dựa vào nó thuộc bảng "công ty con" hay "công ty
  liên kết" trong ảnh (dựa vào tiêu đề bảng/cột chứa dòng đó), không gán cùng một giá trị cho
  toàn bộ.
- ownership_pct = cột "Tỷ lệ lợi ích" (nếu bảng chỉ có 1 cột tỷ lệ gộp "Tỷ lệ sở hữu" thì dùng
  cho ownership_pct, để voting_pct = null).
- voting_pct = cột "Tỷ lệ biểu quyết" / "Tỷ lệ quyền biểu quyết" nếu có cột riêng.
- alias = cột "Tên viết tắt" nếu bảng có cột này.
- Nếu bảng phân biệt "trực tiếp"/"gián tiếp" thì set subtype tương ứng, else null.

Trả về JSON theo schema, KHÔNG kèm giải thích."""


class RateLimiter:
    """Single-key calls/minute limiter (this project uses one GEMINI_API_KEY, not a pool --
    see CLAUDE.md -- so this is deliberately simpler than step02_extract_triplet_from_jsonl.py's
    multi-key-indexed RateLimiter)."""

    def __init__(self, max_calls_per_minute: int = DEFAULT_RATE_LIMIT):
        self.max_calls = max_calls_per_minute
        self.call_times: deque = deque()
        self.lock = Lock()

    def wait_if_needed(self) -> None:
        with self.lock:
            now = time.time()
            while self.call_times and now - self.call_times[0] >= 60:
                self.call_times.popleft()
            if len(self.call_times) >= self.max_calls:
                wait_time = 60 - (now - self.call_times[0]) + 0.1
                if wait_time > 0:
                    logger.info(f"Rate limit: waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
            self.call_times.append(time.time())


class SubsidiaryExtractor:
    def __init__(self, model: str = DEFAULT_MODEL, rate_limit: int = DEFAULT_RATE_LIMIT):
        load_dotenv(REPO_ROOT / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"GEMINI_API_KEY not set. Copy {REPO_ROOT / '.env.example'} to "
                f"{REPO_ROOT / '.env'} and paste your key."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.limiter = RateLimiter(rate_limit)
        self.quota_exhausted = False  # sticky circuit breaker; see extract_segment()

    def _call_gemini(self, parts: List[Any], schema: Dict[str, Any], max_retries: int = 3
                     ) -> Dict[str, Any]:
        for attempt in range(1, max_retries + 1):
            self.limiter.wait_if_needed()
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0,
                    ),
                )
                text = (resp.text or "").strip()
                return json.loads(text) if text else {}
            except Exception as e:
                # A quota-exhaustion 429 will not be fixed by waiting a few seconds and retrying
                # within the same run (the daily cap is dead until it resets) -- fail fast instead
                # of burning the backoff budget on a call that is guaranteed to fail again. Any
                # OTHER error (transient network blip, 5xx) still gets the normal retry+backoff.
                msg = str(e)
                if "RESOURCE_EXHAUSTED" in msg or " 429 " in f" {msg} ":
                    self.quota_exhausted = True
                    raise RuntimeError(f"Gemini quota exhausted: {msg}") from e
                if attempt == max_retries:
                    # Never silently swallow a persistent failure as "0 companies" -- that would
                    # get written to config/subsidiaries/<TICKER>.json indistinguishable from a
                    # genuinely empty table (see docs/SUBSIDIARY_EXTRACTION_LLM_VISION_PLAN.md
                    # incident notes: this exact bug corrupted the first full-corpus run).
                    raise RuntimeError(f"Gemini call failed after {max_retries} attempts: {e}") from e
                wait = 2 ** attempt
                logger.warning(f"  Gemini call failed (attempt {attempt}/{max_retries}): {e}; retrying in {wait}s")
                time.sleep(wait)
        return {}

    def extract_segment(self, seg: Segment, page_imgs: List[bytes]) -> List[Dict[str, Any]]:
        if seg.relationship == "mixed":
            prompt = PROMPT_TMPL_MIXED
        else:
            heading = "Danh sách Công ty con" if seg.relationship == "subsidiary" else "Danh sách Công ty liên kết"
            prompt = PROMPT_TMPL.format(heading=heading, rel=seg.relationship)
        parts = [types.Part.from_bytes(data=b, mime_type="image/png") for b in page_imgs]
        parts.append(types.Part.from_text(text=prompt))
        return self._call_gemini(parts, ROW_SCHEMA).get("companies", [])

    def classify_pages(self, page_nums: List[int], thumbnails: List[bytes]) -> List[int]:
        """For font-broken/scanned PDFs (see locate_pages_via_vision): given a chunk of page
        thumbnails in order, ask which ABSOLUTE page numbers show a subsidiary/associate company
        list table -- not a table of contents, not prose merely mentioning the topic."""
        prompt = PAGE_LOCATE_PROMPT_TMPL.format(
            pages_desc=", ".join(str(p + 1) for p in page_nums),
            pages_desc_first=page_nums[0] + 1,
            pages_desc_last=page_nums[-1] + 1)
        parts = [types.Part.from_bytes(data=b, mime_type="image/png") for b in thumbnails]
        parts.append(types.Part.from_text(text=prompt))
        found = self._call_gemini(parts, PAGE_LOCATE_SCHEMA).get("pages", [])
        # Model returns 1-indexed page numbers (matches what the prompt told it); convert back to
        # 0-indexed and drop anything outside this chunk (hallucinated numbers, defensively).
        valid = set(page_nums)
        return sorted({p - 1 for p in found if (p - 1) in valid})


# ---------------------------------------------------------------------------
# 4. Validate -- token-overlap against the page's own native text
# ---------------------------------------------------------------------------

MIN_TOKEN_HIT_RATIO = 0.8


def validate_rows(rows: List[Dict[str, Any]], native_text: str, font_ok: bool) -> None:
    blob_tokens = set(ascii_fold(native_text).split())
    for r in rows:
        if not font_ok or not r.get("name"):
            r["confidence"] = "needs_review"
            continue
        name_tokens = [t for t in ascii_fold(r["name"]).split() if len(t) > 1]
        if not name_tokens:
            r["confidence"] = "needs_review"
            continue
        hit_ratio = sum(1 for t in name_tokens if t in blob_tokens) / len(name_tokens)
        r["confidence"] = "high" if hit_ratio >= MIN_TOKEN_HIT_RATIO else "needs_review"


def _dedupe_companies(rows: List[dict]) -> Tuple[List[dict], int]:
    """Drop exact duplicate rows caused by adjacent segments sharing a
    boundary page. Segment ranges are computed at LINE granularity (one
    ordinal cutoff), but extraction renders and sends whole PAGE images --
    so when heading N+1 sits partway down the same page that heading N's
    trailing lines are on, that page gets rendered and sent to Gemini twice
    (once per neighboring segment), and Gemini reads the same visible table
    rows both times. Keeps the first (earlier-segment) occurrence of each
    (name, relationship) pair; genuinely different rows on a shared page are
    untouched since their names differ. Returns (deduped_rows, n_dropped)."""
    seen: set = set()
    out: List[dict] = []
    n_dropped = 0
    for r in rows:
        key = (ascii_fold(r.get("name", "")), r.get("relationship", ""))
        if key in seen:
            n_dropped += 1
            continue
        seen.add(key)
        out.append(r)
    return out, n_dropped


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def extract_subsidiaries_from_pdf(pdf_path: Path, extractor: SubsidiaryExtractor) -> Dict[str, Any]:
    ticker, report_year = ticker_and_year_from_filename(pdf_path)
    doc = fitz.open(pdf_path)
    out: Dict[str, Any] = {
        "ticker": ticker,
        "source_doc": pdf_path.name,
        "source_pages": [],
        "as_of": report_year,
        "extraction_method": "gemini_vision",
        "reviewed": False,
        "segment_stats": [],
        "companies": [],
    }

    ratio = font_sanity_ratio(doc)
    out["font_diacritic_ratio"] = round(ratio, 4)
    font_ok = ratio >= FONT_SANITY_MIN_DIACRITIC_RATIO
    lines: List[Line] = []

    if font_ok:
        lines = collect_lines(doc)
        segments = find_segments(doc, lines)
        if not segments:
            # Heading regex found nothing -- could be a genuinely subsidiary-free filing (nothing
            # to find), or the only matching line was in the table of contents pointing at a real
            # table elsewhere (see find_segments_by_content's docstring). Try the content-scored
            # fallback before giving up.
            segments = find_segments_by_content(doc, lines)
            if segments:
                out["segment_stats"].append({
                    "note": "heading regex found nothing; located via content-scoring fallback "
                            "(no explicit heading matched -- table page(s) identified by "
                            "company-name/percent density instead)"
                })
    else:
        # Text layer is unusable (font substitution or scan -- see font_sanity_ratio); neither
        # text-based locator above can run. Fall back to asking Gemini to look at the rendered
        # pages directly (see locate_pages_via_vision's docstring).
        segments = locate_pages_via_vision(doc, extractor)
        if segments:
            out["extraction_method"] = "gemini_vision_font_broken"
            out["segment_stats"].append({
                "note": f"font_diacritic_ratio={ratio:.3f} < {FONT_SANITY_MIN_DIACRITIC_RATIO} "
                        f"(font substitution/scan suspected); text-based locate skipped, table "
                        f"page(s) found via vision page-classification instead. Rows from this "
                        f"path are ALWAYS needs_review -- no independent native text exists to "
                        f"validate names against."
            })

    if not segments:
        out["extraction_method"] = "unusable"
        note = ("no 'công ty con'/'công ty liên kết' heading or table-like page located" if font_ok
                else f"font_diacritic_ratio={ratio:.3f} < {FONT_SANITY_MIN_DIACRITIC_RATIO} "
                     f"(font substitution/scan suspected); vision page-classification found no "
                     f"table page either")
        out["segment_stats"].append({"note": note})
        doc.close()
        return out

    pages_touched: set = set()
    for seg in segments:
        if font_ok:
            seg_lines = [ln for ln in lines if seg.start_ordinal <= ln.ordinal < seg.end_ordinal]
            pages = sorted({ln.page for ln in seg_lines})
            native_text = " ".join(ln.text for ln in seg_lines)
        else:
            # Vision-located segment: boundaries are always clean page*1_000_000 multiples (see
            # _pages_to_mixed_segments), so the page range decodes directly with no line lookup.
            pages = list(range(int(seg.start_ordinal // 1_000_000),
                                int(seg.end_ordinal // 1_000_000)))
            native_text = ""  # unused: validate_rows forces needs_review whenever font_ok=False

        page_imgs = render_pages(doc, pages)
        rows = extractor.extract_segment(seg, page_imgs)
        validate_rows(rows, native_text, font_ok)

        n_ok = sum(1 for r in rows if r.get("confidence") == "high")
        out["segment_stats"].append({
            "relationship": seg.relationship, "pages": [p + 1 for p in pages],
            "n_rows": len(rows), "n_high_confidence": n_ok,
        })
        out["companies"].extend(rows)
        pages_touched.update(p + 1 for p in pages)  # 1-indexed for humans

    out["companies"], n_dropped = _dedupe_companies(out["companies"])
    if n_dropped:
        out["duplicate_rows_removed"] = n_dropped

    out["source_pages"] = sorted(pages_touched)
    doc.close()
    return out


def discover_pdfs(corpus_dir: Path, doc_filter: Optional[str], limit: Optional[int]) -> List[Path]:
    pdfs = sorted(corpus_dir.rglob("*.pdf"))
    if doc_filter:
        pdfs = [p for p in pdfs if doc_filter.lower() in p.name.lower()]
    if limit:
        pdfs = pdfs[:limit]
    return pdfs


def group_pdfs_by_ticker(pdfs: List[Path]) -> Dict[str, List[Tuple[int, Path]]]:
    """Group PDFs by ticker, each ticker's list sorted newest-report-year first."""
    groups: Dict[str, List[Tuple[int, Path]]] = {}
    for p in pdfs:
        ticker, year = ticker_and_year_from_filename(p)
        if not ticker:
            continue
        groups.setdefault(ticker, []).append((year or 0, p))
    for ticker in groups:
        groups[ticker].sort(key=lambda t: t[0], reverse=True)
    return groups


def _is_reviewed(output_path: Path) -> bool:
    """True if `output_path` already exists and a human has confirmed it (`reviewed: true`) --
    re-running the extractor must never silently clobber that with fresh, unreviewed output."""
    if not output_path.exists():
        return False
    try:
        return bool(json.loads(output_path.read_text(encoding="utf-8")).get("reviewed", False))
    except Exception:
        return False


def run_latest_per_ticker(corpus_dir: Path, output_dir: Path, doc_filter: Optional[str],
                           limit_tickers: Optional[int], dry_run: bool, force: bool,
                           extractor: SubsidiaryExtractor, resume: bool = False) -> None:
    """One PDF per ticker: newest report year first, falling back to an older year only if the
    newest comes back 'unusable'."""
    all_pdfs = discover_pdfs(corpus_dir, doc_filter, None)
    groups = group_pdfs_by_ticker(all_pdfs)
    tickers = sorted(groups)
    if limit_tickers:
        tickers = tickers[:limit_tickers]
    logger.info(f"{len(tickers)} ticker(s) with at least one .pdf report "
                f"(out of {len(groups)} discovered, {len(all_pdfs)} total PDFs)")

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    ok: List[str] = []
    all_unusable: List[str] = []
    errors: List[str] = []
    skipped_reviewed: List[str] = []
    skipped_resume: List[str] = []
    aborted_quota: List[str] = []
    n_companies_total = 0
    n_high_total = 0

    for idx, ticker in enumerate(tickers, 1):
        out_path = output_dir / f"{ticker}.json"
        if not force and not dry_run and _is_reviewed(out_path):
            logger.info(f"  [{idx}/{len(tickers)}] {ticker}: skipping -- already reviewed:true "
                        f"(pass --force to re-extract)")
            skipped_reviewed.append(ticker)
            continue
        if resume and not force and not dry_run and out_path.exists():
            # Resuming an interrupted run (e.g. after a quota wall) -- don't re-burn API calls
            # redoing tickers that already produced output, reviewed or not.
            logger.info(f"  [{idx}/{len(tickers)}] {ticker}: skipping -- output already exists "
                        f"(--resume; pass --force to redo)")
            skipped_resume.append(ticker)
            continue

        candidates = groups[ticker]
        attempts: List[str] = []
        result = None
        used_pdf = None
        for year, pdf_path in candidates:
            if extractor.quota_exhausted:
                break
            try:
                r = extract_subsidiaries_from_pdf(pdf_path, extractor)
            except Exception as e:
                logger.error(f"  [{idx}/{len(tickers)}] {ticker}: FAILED on {pdf_path.name}: {e}")
                attempts.append(f"{pdf_path.name}=error")
                continue
            attempts.append(f"{pdf_path.name}={r['extraction_method']}")
            if r["extraction_method"] != "unusable":
                result, used_pdf = r, pdf_path
                break

        if extractor.quota_exhausted:
            logger.error(f"  [{idx}/{len(tickers)}] {ticker}: ABORTING RUN -- Gemini quota "
                         f"exhausted. Remaining tickers not attempted; re-run with --resume once "
                         f"quota resets.")
            aborted_quota.extend(tickers[idx - 1:])
            break

        if result is None:
            logger.warning(f"  [{idx}/{len(tickers)}] {ticker}: no usable report among "
                            f"{len(candidates)} tried ({', '.join(attempts)})")
            if attempts and all(a.endswith("=error") for a in attempts):
                errors.append(ticker)
            else:
                all_unusable.append(ticker)
            continue

        n = len(result["companies"])
        n_high = sum(1 for c in result["companies"] if c.get("confidence") == "high")
        n_companies_total += n
        n_high_total += n_high
        logger.info(f"  [{idx}/{len(tickers)}] {ticker}: used {used_pdf.name} -> "
                    f"companies={n} (high={n_high}) [tried: {', '.join(attempts)}]")
        ok.append(ticker)

        if not dry_run:
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("=" * 70)
    logger.info(f"SUMMARY: {len(ok)} ticker(s) OK, {len(skipped_reviewed)} skipped (already "
                f"reviewed), {len(skipped_resume)} skipped (--resume), {len(all_unusable)} "
                f"all-unusable, {len(errors)} error(s), {len(aborted_quota)} not attempted "
                f"(quota exhausted)")
    logger.info(f"  Total companies extracted: {n_companies_total} (high-confidence: {n_high_total})")
    if skipped_reviewed:
        logger.info(f"  Skipped (reviewed:true, use --force to override): {', '.join(skipped_reviewed)}")
    if all_unusable:
        logger.info(f"  All-unusable tickers: {', '.join(all_unusable)}")
    if errors:
        logger.info(f"  Error tickers: {', '.join(errors)}")
    if aborted_quota:
        logger.info(f"  Not attempted (quota exhausted, re-run with --resume): {', '.join(aborted_quota)}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Extract subsidiary/associate company tables from annual reports via Gemini "
                    "vision (see docs/SUBSIDIARY_EXTRACTION_LLM_VISION_PLAN.md).")
    p.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    p.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--doc", type=str, default=None, help="Only process PDFs whose filename contains this substring.")
    p.add_argument("--limit-docs", type=int, default=None,
                   help="Cap the number of PDFs/tickers processed.")
    p.add_argument("--dry-run", action="store_true", help="Print JSON to stdout, don't write files.")
    p.add_argument("--latest-per-ticker", action="store_true",
                   help="Corpus-wide mode: one PDF per ticker (newest report year first).")
    p.add_argument("--force", action="store_true",
                   help="Re-extract and overwrite even a ticker whose output file is already reviewed:true.")
    p.add_argument("--resume", action="store_true",
                   help="Corpus-wide mode only: skip any ticker whose output file already exists "
                        "(reviewed or not) -- use to continue a run interrupted by a quota wall "
                        "without re-spending API calls on tickers already done.")
    p.add_argument("--model", type=str, default=DEFAULT_MODEL)
    p.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT,
                   help="Max Gemini calls per minute (default %(default)s).")
    args = p.parse_args()

    if not args.corpus_dir.exists():
        logger.error(f"Corpus dir not found: {args.corpus_dir}")
        return

    extractor = SubsidiaryExtractor(model=args.model, rate_limit=args.rate_limit)

    if args.latest_per_ticker:
        run_latest_per_ticker(args.corpus_dir, args.output_dir, args.doc, args.limit_docs,
                               args.dry_run, args.force, extractor, resume=args.resume)
        return

    pdfs = discover_pdfs(args.corpus_dir, args.doc, args.limit_docs)
    if not pdfs:
        logger.error("No matching PDFs found.")
        return
    logger.info(f"Processing {len(pdfs)} PDF(s)")

    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdfs:
        logger.info(f"--- {pdf_path.relative_to(REPO_ROOT) if pdf_path.is_relative_to(REPO_ROOT) else pdf_path} ---")
        ticker_guess, _ = ticker_and_year_from_filename(pdf_path)
        out_path = args.output_dir / f"{(ticker_guess or pdf_path.stem)}.json"
        if not args.force and not args.dry_run and _is_reviewed(out_path):
            logger.info(f"  skipping -- {out_path.name} already reviewed:true (pass --force to override)")
            continue
        try:
            result = extract_subsidiaries_from_pdf(pdf_path, extractor)
        except Exception as e:
            logger.error(f"FAILED on {pdf_path.name}: {e}")
            continue

        n = len(result["companies"])
        n_high = sum(1 for c in result["companies"] if c.get("confidence") == "high")
        logger.info(f"  ticker={result['ticker']} method={result['extraction_method']} "
                    f"companies={n} (high={n_high}) pages={result['source_pages']}")

        if args.dry_run:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            out_name = result["ticker"] or pdf_path.stem
            out_path = args.output_dir / f"{out_name}.json"
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
