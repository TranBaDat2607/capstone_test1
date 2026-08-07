"""
Work out which of the 5 companies a pasted news sentence is about.

This is what makes the answer "claim của công ty đó": the retriever filters the index to
one ticker before searching, so a claim from another company can never be returned. Get
the detection wrong and the accuracy of everything downstream goes with it — so the rule
here is that an unrecognised sentence returns None (the caller then searches all 5 and
says so), never a guess.

Matching is done on a diacritic-folded, lowercased copy of the text so "Nhựa An Phát
Xanh", "NHUA AN PHAT XANH" and "nhua an phat xanh" all hit the same alias. Aliases are
matched on token boundaries — a bare 3-letter ticker must not fire inside another word —
and the LONGEST matching alias wins, so "An Phát Xanh" beats a stray "AAA".

Alias sources, both already in the repo:
  config/issuer_registry.json                     — the curated variants (AAA today)
  data/interim/news_preprocessed/...jsonl          — each row's ticker + company name
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .corpus import TICKERS


def fold(text: Optional[str]) -> str:
    """Lowercase + strip Vietnamese diacritics, so spelling variants collapse to one form."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    stripped = stripped.replace("đ", "d")
    return re.sub(r"\s+", " ", stripped).strip()


def detect_ticker(text: str, aliases: Dict[str, Sequence[str]]) -> Optional[str]:
    """Return the ticker whose longest alias appears in `text`, else None."""
    haystack = fold(text)
    if not haystack:
        return None

    best_ticker: Optional[str] = None
    best_length = 0
    for ticker, names in aliases.items():
        for name in names:
            needle = fold(name)
            if not needle or len(needle) <= best_length:
                continue
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
                best_ticker, best_length = ticker, len(needle)
    return best_ticker


def _clean_alias(name: Optional[str]) -> Optional[str]:
    """Drop aliases too generic or too structural to identify a company in a news sentence."""
    if not name or not isinstance(name, str):
        return None
    name = name.strip()
    if len(name) < 3:
        return None
    # "Suppliers of AAA", "Shareholders and Investors of ..." describe a relationship,
    # not the issuer; they would fire on sentences that are about someone else.
    lowered = name.lower()
    for prefix in ("suppliers of", "customers of", "creditors of", "shareholders",
                   "subsidiary companies of", "general director"):
        if lowered.startswith(prefix):
            return None
    return name


def load_aliases(issuer_registry: Optional[Path] = None,
                 news_jsonl: Optional[Path] = None,
                 tickers: Sequence[str] = TICKERS) -> Dict[str, List[str]]:
    """Build {ticker: [alias, ...]} from the registry and the news metadata already on disk."""
    aliases: Dict[str, List[str]] = {t: [t] for t in tickers}

    if issuer_registry and Path(issuer_registry).exists():
        registry = json.loads(Path(issuer_registry).read_text(encoding="utf-8"))
        for ticker, entry in registry.items():
            if ticker not in aliases or not isinstance(entry, dict):
                continue
            for name in [entry.get("canonical_name"), *(entry.get("aliases") or [])]:
                cleaned = _clean_alias(name)
                if cleaned:
                    aliases[ticker].append(cleaned)

    if news_jsonl and Path(news_jsonl).exists():
        with open(news_jsonl, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ticker = row.get("ticker")
                cleaned = _clean_alias(row.get("company"))
                if ticker in aliases and cleaned:
                    aliases[ticker].append(cleaned)

    for ticker, names in aliases.items():
        seen, unique = set(), []
        for name in names:
            key = fold(name)
            if key and key not in seen:
                seen.add(key)
                unique.append(name)
        aliases[ticker] = unique
    return aliases
