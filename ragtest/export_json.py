#!/usr/bin/env python3
"""
Export the whole claim index as ONE self-contained JSON file.

    python ragtest/export_json.py

Writes `ragtest/claims_with_embeddings.json`: every claim sentence from the 5 companies'
annual reports, with its provenance AND its embedding vector inline. Portable — open it,
send it, load it without numpy.

This is a SEPARATE artifact from the working index, not a replacement. `build_index.py`
keeps vectors in a float32 `.npy` because that is what retrieval reads: 55 MB vs 277 MB,
0.02 s to load vs 1.17 s, and the build re-saves every 512 sentences. The JSON here is
the human/portable form of the same numbers.

Vectors are rounded to 6 decimals — that halves the file and moves a unit-norm cosine by
under 1e-5, far below anything that could reorder a result. The rounding is written into
the file's own `float_decimals` field rather than left for someone to discover.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

FLOAT_DECIMALS = 6
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "claims_with_embeddings.json"

# Fields copied from the corpus row onto each exported claim, in this order.
CLAIM_FIELDS = ("doc_id", "text", "ticker", "year", "source_pdf", "page",
                "sentence_index", "labels")


def export_claims_json(path: Path, corpus: Sequence[Dict[str, Any]],
                       embeddings: np.ndarray, meta: Dict[str, Any] | None = None,
                       decimals: int = FLOAT_DECIMALS) -> Dict[str, Any]:
    """Write one JSON file holding every claim and its vector. Returns the payload."""
    if len(corpus) != len(embeddings):
        raise ValueError(f"stale index: {len(corpus)} claim rows vs {len(embeddings)} "
                         f"embedding rows — rebuild the index before exporting")

    meta = meta or {}
    matrix = np.asarray(embeddings, dtype="float32")

    claims = []
    for row, vector in zip(corpus, matrix):
        claim = {field: row.get(field) for field in CLAIM_FIELDS}
        claim["embedding"] = [round(float(value), decimals) for value in vector]
        claims.append(claim)

    payload = {
        "embed_model": meta.get("embed_model"),
        "dim": int(matrix.shape[1]) if matrix.size else meta.get("dim"),
        "n_claims": len(claims),
        "per_ticker": dict(sorted(Counter(c["ticker"] for c in claims).items())),
        "float_decimals": decimals,
        "built_at": meta.get("built_at"),
        "source_records": meta.get("source_records"),
        "note": ("Câu tuyên bố ESG trích từ báo cáo thường niên của 5 công ty, kèm vector "
                 "embedding. Vector đã làm tròn 6 chữ số thập phân."),
        "claims": claims,
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> int:
    from esg_kg.core.console import ensure_utf8_stdout

    from ragtest.build_index import load_index
    from ragtest.config import INDEX_DIR

    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--decimals", type=int, default=FLOAT_DECIMALS)
    args = parser.parse_args()

    corpus, embeddings, meta = load_index(args.index_dir)
    payload = export_claims_json(args.output, corpus, embeddings, meta,
                                 decimals=args.decimals)

    size_mb = args.output.stat().st_size / 1e6
    print(f"wrote {args.output}")
    print(f"  {payload['n_claims']:,} câu claim · vector {payload['dim']} chiều "
          f"· {payload['embed_model']}")
    for ticker, count in payload["per_ticker"].items():
        print(f"    {ticker}  {count:,}")
    print(f"  {size_mb:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
