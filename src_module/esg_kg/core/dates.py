"""Date canonicalization shared across pipeline stages.

Extracted verbatim from ``src/step03_fix_invalid_triplets.py`` (Phase 1.5, P4 in
docs/TEMPORAL_KG_DESIGN.md):

    ISO_DATE_RE, normalize_date_string   <- step03:75, 85
    date_start_key                       <- step03:130

These decide WHEN a fact was true, which is the axis the whole product turns on
(a 2023 claim cross-checked against 2024 conduct). step00 measures temporal
quality with them and step05 builds version chains with them, so both must read
a date identically or the graph corrupts silently.

Two behaviours worth not "improving" later:

* ``normalize_date_string`` returns ``(value, parseable)``. An unrecognized
  spelling ("Q2 2023") comes back UNCHANGED with ``parseable=False`` — it never
  invents a date. Downstream code handling the resulting ``None`` from
  ``date_start_key`` is honouring that contract, not papering over a bug
  (DESIGN.md §5.1, exemption E3).
* ``date_start_key`` projects a partial date onto its start instant, so "2011"
  and "2011-01-01" collapse to one key. That is the P4 fix: comparing raw
  strings split one fact into two ``temporal_versions`` both claiming
  ``is_current=true``.

Deliberately NOT moved: ``enforce_temporal_invariants`` (step03:378) — it is
step03's own Phase-1.5 pass, imported only by the test, and travels with step03
to ``graph/fix_triples.py``.

Behaviour is asserted equal to the src/ originals in
``test/test_esg_kg_equivalence.py``.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

# Dates are canonicalized to ISO YYYY[-MM[-DD]] so that downstream version
# comparison (step05) and quality gates (step00) compare instants, not string
# spellings ("2011" vs "2011-01-01" was observed splitting one fact into two
# temporal_versions both flagged is_current=true).
ISO_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_DATE_PATTERNS = [
    # (regex, (year_group, month_group, day_group)) — day-first is the Vietnamese order
    (re.compile(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$"), (1, 2, 3)),   # 2023/05/31, 2023.05.31
    (re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$"), (3, 2, 1)),  # 31/05/2023, 31-05-2023
    (re.compile(r"^(\d{1,2})[/.\-](\d{4})$"), (2, 1, None)),           # 05/2023, 05-2023
    (re.compile(r"^(\d{4})[/.](\d{1,2})$"), (1, 2, None)),             # 2023/05
]


def normalize_date_string(value: Any) -> Tuple[Optional[str], bool]:
    """Canonicalize one date value to ISO YYYY[-MM[-DD]].

    Returns (normalized, parseable). JSON null / "" / "null" / "none" -> (None, True).
    An unrecognized spelling is returned unchanged with parseable=False (never
    silently invent a date). Datetime strings keep only the date part.
    """
    if value is None:
        return None, True
    s = str(value).strip()
    if s == "" or s.lower() in ("null", "none"):
        return None, True

    # datetime -> date part
    if "T" in s:
        s = s.split("T", 1)[0].strip()

    m = ISO_DATE_RE.match(s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
    else:
        y = mo = d = None
        for pat, (gy, gm, gd) in _DATE_PATTERNS:
            pm = pat.match(s)
            if pm:
                y = pm.group(gy)
                mo = pm.group(gm) if gm else None
                d = pm.group(gd) if gd else None
                break
        if y is None:
            return str(value), False

    if mo is not None and not (1 <= int(mo) <= 12):
        return str(value), False
    if d is not None and not (1 <= int(d) <= 31):
        return str(value), False

    out = y
    if mo is not None:
        out += f"-{int(mo):02d}"
        if d is not None:
            out += f"-{int(d):02d}"
    return out, True


def date_start_key(value: Any) -> Optional[str]:
    """The start instant of a (possibly partial) date, as a comparable YYYY-MM-DD.

    "2011" and "2011-01-01" share the start instant "2011-01-01" — the exact
    ambiguity that produced duplicate is_current=true versions (P4). Returns
    None for null/unparseable values.
    """
    norm, ok = normalize_date_string(value)
    if not ok or norm is None:
        return None
    parts = norm.split("-")
    y = parts[0]
    mo = parts[1] if len(parts) > 1 else "01"
    d = parts[2] if len(parts) > 2 else "01"
    return f"{y}-{mo}-{d}"


__all__ = ["ISO_DATE_RE", "normalize_date_string", "date_start_key"]
