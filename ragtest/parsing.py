"""
Tolerant JSON extraction for LLM replies.

Every model here is asked for JSON and most of the time obliges, but "most of the time"
is exactly the problem: a reply wrapped in ```json fences, prefixed with "Đây là kết
quả:", or refused outright ("xin lỗi, tôi không thể") must be handled, not crashed on.

CLAUDE.md records the same defect class in step07: `_parse_verdict` called `.get()` on
whatever `json.loads` returned, so a reply of "[]" raised AttributeError instead of being
refused. The fix belongs here, once, rather than in each caller: this function returns
whatever the reply parsed to — dict, list, scalar or None — and the callers are the ones
that check the type before using it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: Optional[str]) -> Optional[Any]:
    """Best-effort parse. Returns None when nothing JSON-shaped is present."""
    if not text or not text.strip():
        return None

    candidate = text.strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        pass

    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, candidate, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                continue
    return None
