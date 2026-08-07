"""
Append query results as JSONL, so the evaluation can be run later without re-calling the
API.

Everything needed to re-score a run offline is written: the query, the detected company,
the full candidate list WITH its provenance and per-channel ranks (bm25/dense/fusion/
rerank), and the verdict. That is what lets a later evaluation ask "would top-3 have been
enough?" or "did reranking change anything?" without paying for the run twice — the same
reason evalu/ pools candidates across methods before annotating.

UTF-8, ensure_ascii=False: the corpus is Vietnamese and a \\uXXXX-escaped file is unusable
for hand-checking a claim against a report page.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def save_result(path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    """Append one result row. Returns the row actually written (with its timestamp)."""
    row = dict(record)
    row.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_results(path: Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows
