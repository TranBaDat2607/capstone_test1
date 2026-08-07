"""
The grounded-ESG-term vocabulary behind metric M1.1 (ESG Signal-to-Noise Ratio).

The classifier (ViDeBERTa-v3-ESG) marks a sentence `esg=true` from learned
sentence semantics. That is exactly what makes SNR worth measuring: marketing
prose ("hướng tới phát triển bền vững", "tầm nhìn trở thành doanh nghiệp hàng
đầu") reads as ESG to a classifier while carrying no measurable ESG content.

"Grounded" here means the sentence contains a term drawn from a controlled
vocabulary the project already maintains for other reasons — never a list
invented for this metric:

    kpi_definitions_construction.json   the 35 TT96/QĐ2171/QCVN09 KPI names
    config/kpi_type_aliases.json        their Vietnamese spelling variants
    config/gri_catalog.json             136 GRI indicator titles (vi + en)

So SNR answers a narrow, honest question: what share of sentences the classifier
accepted can be tied to a term the KPI/indicator layer can actually act on. It is
NOT a precision score against human labels — no such labels exist.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]

# Vietnamese "đ" is a distinct letter, not a base+combining pair, so NFD alone
# will not fold it. Everything else falls out of NFD + mark stripping.
_DSTROKE = str.maketrans({"đ": "d", "Đ": "d", "ð": "d"})

_MIN_TERM_LEN = 4          # drop 1-3 char fragments: they match almost any text


def fold(text: Optional[str]) -> str:
    """Lowercase, strip diacritics, collapse whitespace. Matching is done here."""
    if not text:
        return ""
    s = str(text).lower().translate(_DSTROKE)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s%/]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Function words and measurement scaffolding. A phrase made only of these, or
# hanging off one at either end, matches almost any Vietnamese annual report and
# would inflate M1.1 without carrying ESG signal.
GENERIC_TOKENS = {
    "tong", "so", "ty", "le", "va", "cua", "cac", "trong", "cho", "theo", "ky",
    "bao", "cao", "nam", "thu", "muc", "do", "co", "duoc", "tu", "voi", "ve",
    "hoac", "den", "tren", "duoi", "binh", "quan", "gia", "tri", "cong", "chung",
    "khac", "mot", "hai", "phan", "tram", "luong", "scope", "and", "the", "of",
    "to", "in", "for", "total", "number", "rate", "ratio",
}

_MAX_NGRAM = 5


def derive_phrases(name: Optional[str]) -> Set[str]:
    """
    Contiguous sub-phrases of an official indicator name, folded.

    "Tổng phát thải khí nhà kính (Scope 1 + Scope 2)"
        -> {"phat thai khi nha kinh", "khi nha kinh", "phat thai khi", ...}

    Rules, all mechanical so the vocabulary stays reproducible from config:
      * length 2..5 tokens (single tokens match far too much text)
      * NO generic token anywhere in the phrase, not merely at the ends.
        Allowing them in the middle produced fragments straddling a conjunction
        — "trực tiếp và gián tiếp" -> "tiep va gian" — which are not terms.
      * digits-only tokens are dropped before n-gramming
    """
    folded = fold(name)
    if not folded:
        return set()
    tokens = [t for t in folded.split() if not t.isdigit()]
    out: Set[str] = set()
    for n in range(2, _MAX_NGRAM + 1):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if any(t in GENERIC_TOKENS for t in gram):
                continue
            phrase = " ".join(gram)
            if len(phrase) >= _MIN_TERM_LEN:
                out.add(phrase)
    return out


def _harvest(obj, out: Set[str]) -> None:
    """Pull every plausible term string out of a nested config blob."""
    keys = {"name", "name_vi", "name_en", "title", "title_vi", "title_en",
            "kpi_name", "label", "aliases", "alias", "synonyms", "keywords",
            "match_patterns", "official_name"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                if isinstance(v, str):
                    out.add(v)
                elif isinstance(v, list):
                    out.update(x for x in v if isinstance(x, str))
            _harvest(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _harvest(item, out)


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return None


def build_lexicon(kpi_defs: Optional[Path] = None,
                  aliases: Optional[Path] = None,
                  gri: Optional[Path] = None) -> Set[str]:
    """
    The controlled ESG vocabulary, folded.

    Three sources, each already maintained by the project for other reasons —
    nothing here is a list invented for the metric:

      kpi_definitions_construction.json   35 official TT96/QĐ2171/QCVN09 KPI
                                          names, plus sub-phrases of each
                                          (derive_phrases), because an official
                                          title never appears verbatim in prose
      config/kpi_type_aliases.json        `rules[].exact` / `rules[].contains` —
                                          curated free-text spellings — and the
                                          `unit_canonical` keys, since a unit
                                          like tCO2e or kWh is itself grounding
      config/gri_catalog.json             136 GRI indicator titles. Many
                                          `title_vi` are untranslated English
                                          passthrough, so these contribute far
                                          less on a Vietnamese corpus than their
                                          count suggests — a known limitation,
                                          not a bug to hide.

    A missing file is skipped rather than fatal, so a bare clone still runs.
    """
    kpi_defs = kpi_defs or REPO_ROOT / "kpi_definitions_construction.json"
    aliases = aliases or REPO_ROOT / "config" / "kpi_type_aliases.json"
    gri = gri or REPO_ROOT / "config" / "gri_catalog.json"

    exact: Set[str] = set()          # curated spellings, taken as-is
    names: Set[str] = set()          # official titles, expanded into sub-phrases

    blob = _load(kpi_defs)
    if isinstance(blob, list):
        for item in blob:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"])

    blob = _load(aliases)
    if isinstance(blob, dict):
        for rule in blob.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            for field in ("exact", "contains"):
                exact.update(x for x in (rule.get(field) or []) if isinstance(x, str))
        for item in blob.get("needs_review") or []:
            if isinstance(item, dict):
                exact.update(x for x in (item.get("titles") or []) if isinstance(x, str))
        exact.update(k for k in (blob.get("unit_canonical") or {}) if isinstance(k, str))

    # GRI titles enter as WHOLE titles only, never n-grammed. Most `title_vi`
    # are untranslated English, and slicing English titles yields fragments like
    # "that were screened using" or "on local" — grammar, not terminology. On a
    # Vietnamese corpus those would fire as false positives far more often than
    # they would find a real GRI mention.
    blob = _load(gri)
    if isinstance(blob, dict):
        for entry in blob.values():
            if isinstance(entry, dict):
                for field in ("title_vi", "title_en"):
                    if isinstance(entry.get(field), str):
                        exact.add(entry[field])

    lex = {f for f in (fold(t) for t in exact) if len(f) >= _MIN_TERM_LEN}
    for name in names:
        lex.update(derive_phrases(name))

    # a bare single token matches too much unless it is genuinely specific
    return {t for t in lex if " " in t or len(t) >= 6}


def contains_term(text: str, lexicon: Set[str]) -> bool:
    """True when any lexicon term appears in `text` (both sides folded)."""
    folded = fold(text)
    if not folded:
        return False
    return any(term in folded for term in lexicon)


class LexiconMatcher:
    """
    Compiled form of the lexicon, for scanning the full corpus.

    The naive `any(term in text for term in lexicon)` is O(terms x sentences):
    with ~10^3 terms and ~9x10^5 sentences that is ~10^9 substring scans. One
    compiled alternation hands the same work to the regex engine in a single
    pass per sentence. Terms are sorted longest-first so the reported match is
    the most specific phrase rather than a prefix of it.
    """

    __slots__ = ("_re", "size")

    def __init__(self, lexicon: Iterable[str]):
        terms = sorted({t for t in (fold(x) for x in lexicon) if t},
                       key=len, reverse=True)
        self.size = len(terms)
        self._re = (re.compile("|".join(re.escape(t) for t in terms))
                    if terms else None)

    def matches(self, text: str) -> bool:
        if self._re is None:
            return False
        folded = fold(text)
        return bool(folded) and self._re.search(folded) is not None

    def first_match(self, text: str) -> Optional[str]:
        if self._re is None:
            return None
        m = self._re.search(fold(text))
        return m.group(0) if m else None
