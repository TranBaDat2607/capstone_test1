"""Split Vietnamese text into sentences.

Prefers `underthesea.sent_tokenize` (Vietnamese-aware: handles abbreviations
like "TP.HCM", "Q.1", "Cty.", numeric points like "1.500", etc.). Falls back to
a conservative regex splitter if underthesea isn't installed.
"""

from __future__ import annotations

import re
from typing import Callable

try:
    from underthesea import sent_tokenize as _ut_sent_tokenize  # type: ignore

    def _split(text: str) -> list[str]:
        return _ut_sent_tokenize(text)

except ImportError:  # pragma: no cover - fallback only
    # Regex fallback: split on .!? followed by space + uppercase or newline.
    # Won't handle Vietnamese abbreviations correctly, but better than nothing.
    _SENT_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ỹ])|\n{2,}")

    def _split(text: str) -> list[str]:
        return [s.strip() for s in _SENT_END_RE.split(text) if s.strip()]


_BULLET_RE = re.compile(r"^[\s•·\-–—*●▪►]+")
_PAGE_NUM_RE = re.compile(r"^\s*\d+\s*$")
# TOC line: contains a long run of dots (dot leaders to page numbers).
_TOC_RE = re.compile(r"\.{6,}")
# Looks like a mostly-numeric / table-row fragment.
_NUMERIC_NOISE_RE = re.compile(r"^[\d\s.,()%/\-+]+$")
_MIN_LEN = 25  # chars; drop short fragments
_MIN_WORDS = 4


def _merge_wrapped_lines(block: str) -> str:
    """Collapse single newlines (layout wraps) inside a paragraph block.
    Lines that don't end with sentence-final punctuation are joined with a
    space to the next line. Blank-line breaks are preserved by the caller.
    """
    out: list[str] = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        if out and not re.search(r"[.!?:;…]$", out[-1]) and not line[0:1].isdigit():
            out[-1] = out[-1] + " " + line
        else:
            out.append(line)
    return "\n".join(out)


def split_sentences(text: str) -> list[str]:
    """Return a list of cleaned sentence strings from `text`.

    Strategy:
      1. Split the page on blank lines into paragraph blocks.
      2. Within each block, merge soft-wrapped lines into running text.
      3. Run the VN-aware sentence tokenizer on the joined text.
      4. Drop TOC lines, page numbers, numeric-only fragments, and shorts.
    """
    sentences: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        joined = _merge_wrapped_lines(block)
        for s in _split(joined):
            s = _BULLET_RE.sub("", s).strip()
            if not s:
                continue
            if _PAGE_NUM_RE.match(s):
                continue
            if _TOC_RE.search(s):
                continue
            if _NUMERIC_NOISE_RE.match(s):
                continue
            if len(s) < _MIN_LEN:
                continue
            if len(s.split()) < _MIN_WORDS:
                continue
            sentences.append(s)
    return sentences
