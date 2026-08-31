"""Name normalization shared across pipeline stages.

Extracted verbatim from ``src/step04_build_issuer_registry.py`` so every stage
imports them from one stable place instead of from a sibling step file:

    normalize_name, name_tokens      <- step04:138, 158   (6 importers)
    merge_preserving_edits           <- step04:399

``normalize_name`` is the most load-bearing helper in the repo: step04 writes
``config/issuer_registry.json`` with it and step05 re-derives the same keys when
resolving entities, so BOTH sides must normalize identically or the frozen issuer
anchor silently stops matching. Same for ``config/standards_registry.json``
(step04b/step05 Stage A.3). That is why the lookup tables live here next to the
function rather than being re-declared per stage.

``merge_preserving_edits`` is the registry-merge contract: human-confirmed
aliases/exclusions survive a rebuild, and only genuinely unseen names reappear in
``needs_review``. Shared by step04 and step04b, which have the same registry shape.

Pure functions over strings/dicts — no filesystem, no network, no dependency on
other stages. Behaviour is asserted equal to the src/ originals in
``test/test_esg_kg_equivalence.py``.

Deliberately NOT moved: ``issuer_core_tokens`` / ``GENERIC_TOKENS`` — they are
step04-internal (nothing else imports them) and belong with the issuer registry
builder, not in the shared kernel.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Set

OCR_FIXES = {"Ƣ": "U", "ƣ": "u", "ư": "u", "Ư": "U", "đ": "d", "Đ": "d"}

LEGAL_FORMS = [
    "cong ty trach nhiem huu han", "tong cong ty", "cong ty co phan", "cong ty cp",
    "cong ty tnhh", "cong ty", "ctcp", "tnhh", "tap doan", "joint stock company",
    "joint stock", "corporation", "company", "co ltd", "ltd", "jsc", "j s c", "plc", "inc",
]

SYNONYMS = {"green": "xanh", "plastics": "plastic"}


def normalize_name(s: Any) -> str:
    """Lowercase, de-OCR, strip diacritics + legal forms, canonicalize synonyms."""
    if not s:
        return ""
    s = str(s)
    for a, b in OCR_FIXES.items():
        s = s.replace(a, b)
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = f" {s.strip()} "
    for phrase in sorted(LEGAL_FORMS, key=len, reverse=True):
        s = s.replace(f" {phrase} ", " ")
    for a, b in SYNONYMS.items():
        s = s.replace(f" {a} ", f" {b} ")
    return re.sub(r"\s+", " ", s).strip()


def name_tokens(s: Any) -> Set[str]:
    n = normalize_name(s)
    return set(n.split()) if n else set()


def merge_preserving_edits(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Keep human-confirmed aliases/exclusions; only (re)surface unseen names in needs_review."""
    confirmed_alias = set(old.get("aliases", []))
    confirmed_excl_names = {e["name"] for e in old.get("exclusions", [])}
    resolved = confirmed_alias | confirmed_excl_names

    merged_aliases = sorted(confirmed_alias | set(new["aliases"]))
    excl_by_name = {e["name"]: e for e in new["exclusions"]}
    excl_by_name.update({e["name"]: e for e in old.get("exclusions", [])})

    review = [r for r in new["needs_review"]
              if r["name"] not in resolved and r["name"] not in merged_aliases]
    return {
        "ticker": new["ticker"],
        "canonical_name": old.get("canonical_name") or new["canonical_name"],
        "core_tokens": new["core_tokens"],
        "aliases": [a for a in merged_aliases if a not in excl_by_name],
        "exclusions": sorted(excl_by_name.values(), key=lambda e: e["name"]),
        "needs_review": review,
    }


__all__ = [
    "OCR_FIXES",
    "LEGAL_FORMS",
    "SYNONYMS",
    "normalize_name",
    "name_tokens",
    "merge_preserving_edits",
]
