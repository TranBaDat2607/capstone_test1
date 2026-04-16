"""
generators/report_blocks.py

Prepare report blocks (text + tables) for LLM extraction.
Converts the extraction_result.json format into clean text blocks.
"""
from __future__ import annotations


def _table_to_text(content: dict) -> str:
    """Convert table content dict to a readable text representation."""
    raw = content.get("raw", "")
    if raw:
        return raw.strip()
    header = content.get("header", [])
    rows   = content.get("rows", [])
    lines: list[str] = []
    if header:
        lines.append(" | ".join(str(h) for h in header))
    for row in rows:
        if isinstance(row, list):
            lines.append(" | ".join(str(c) for c in row))
        elif isinstance(row, dict):
            lines.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(lines).strip()


def prepare_blocks(report: dict) -> list[dict]:
    """Extract text and table blocks from the report; skip images."""
    result: list[dict] = []
    for blk in report.get("blocks", []):
        btype = blk.get("type", "")
        bid   = blk.get("id", "")
        page  = blk.get("page", 0)

        if btype == "image":
            continue

        if btype == "text":
            text = blk.get("content", {}).get("text", "").strip()
        elif btype == "table":
            text = _table_to_text(blk.get("content", {}))
        else:
            continue

        if text:
            result.append({"id": bid, "page": page, "type": btype, "text": text})

    return result
