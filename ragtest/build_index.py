#!/usr/bin/env python3
"""
Build the ragtest index over the ESG sentences already extracted by this project.

No pipeline stage is re-run: this reads `data/outputs/esg_extracted/esg_all_records.jsonl`
(the existing output of `data_processing.extract_esg`), keeps the 5 companies in use,
cleans and dedups, then embeds each sentence once.

Embeddings are cached on disk by sha1(model + text), so re-running after adding a company
only pays for the new sentences, and re-running unchanged is free.

    python ragtest/build_index.py --dry-run          # counts only, no API call, no cost
    python ragtest/build_index.py                     # build + embed + save
    python ragtest/build_index.py --tickers AAA       # one company

Writes to data/outputs/ragtest/ (git-ignored, per CLAUDE.md's layout rule):
    corpus.jsonl      one row per claim sentence, with its provenance
    embeddings.npy    (n_docs, dim) float32, row i <-> corpus line i
    meta.json         model, dims, counts, build time
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

from ragtest.config import CHAT_MODEL, EMBED_MODEL, ESG_RECORDS, INDEX_DIR  # noqa: E402
from ragtest.corpus import TICKERS, build_from_file  # noqa: E402
from ragtest.llm import build_clients  # noqa: E402


def save_index(index_dir: Path, corpus, embeddings: np.ndarray, meta: dict) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    with open(index_dir / "corpus.jsonl", "w", encoding="utf-8") as handle:
        for row in corpus:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    np.save(index_dir / "embeddings.npy", embeddings)
    (index_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def load_index(index_dir: Path):
    """Read back what save_index wrote. Raises a readable error if the pair is stale."""
    corpus_path = index_dir / "corpus.jsonl"
    embeddings_path = index_dir / "embeddings.npy"
    if not corpus_path.exists() or not embeddings_path.exists():
        raise FileNotFoundError(
            f"no index at {index_dir} — build it first:\n"
            f"    python ragtest/build_index.py")

    corpus = [json.loads(line) for line in
              corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    embeddings = np.load(embeddings_path)
    if len(corpus) != len(embeddings):
        raise ValueError(f"index is stale: {len(corpus)} corpus rows vs "
                         f"{len(embeddings)} embedding rows — rebuild it")
    meta = {}
    meta_path = index_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return corpus, embeddings, meta


def main() -> int:
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=Path, default=ESG_RECORDS,
                        help="the extracted ESG sentences (default: the project's own)")
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    parser.add_argument("--tickers", nargs="*", default=list(TICKERS),
                        help=f"companies to index (default: {' '.join(TICKERS)})")
    parser.add_argument("--embed-model", default=EMBED_MODEL)
    parser.add_argument("--limit", type=int, default=None,
                        help="index only the first N sentences (smoke test)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be indexed; no API call, no cost")
    parser.add_argument("--export-json", action="store_true",
                        help="also write ragtest/claims_with_embeddings.json — one "
                             "portable file holding every claim WITH its vector inline")
    parser.add_argument("--no-export-json", dest="export_json", action="store_false",
                        help="skip that export")
    parser.set_defaults(export_json=True)
    args = parser.parse_args()

    if not args.records.exists():
        print(f"ERROR: {args.records} not found.")
        print("       This file is git-ignored and ships via the HF snapshot — run:")
        print("           python src/esg_kg/core/datasync.py pull")
        return 1

    print(f"reading  {args.records}")
    started = time.time()
    corpus = build_from_file(args.records, tickers=tuple(args.tickers))
    if args.limit:
        corpus = corpus[:args.limit]

    per_ticker = Counter(row["ticker"] for row in corpus)
    docs = len({row["source_pdf"] for row in corpus})
    print(f"corpus   {len(corpus):,} claim sentences from {docs} annual reports "
          f"({time.time() - started:.1f}s)")
    for ticker in sorted(per_ticker):
        print(f"           {ticker}  {per_ticker[ticker]:,}")

    if not corpus:
        print("nothing to index — check --tickers")
        return 1

    if args.dry_run:
        print("\n--dry-run: stopping before the embedding call (nothing was written)")
        return 0

    cache_path = args.index_dir / "embed_cache.json"
    clients = build_clients(CHAT_MODEL, args.embed_model, cache_path=cache_path)
    embedder = clients["embed"]
    print(f"\nembedding via {clients['base_url']} ({args.embed_model})")
    if embedder.cache:
        print(f"  {len(embedder.cache):,} vectors already cached on disk")

    texts = [row["text"] for row in corpus]
    embed_started = time.time()
    chunk = 512
    parts = []
    for start in range(0, len(texts), chunk):
        parts.append(embedder.embed(texts[start:start + chunk]))
        done = min(start + chunk, len(texts))
        print(f"  {done:,}/{len(texts):,}  "
              f"(api calls {embedder.api_calls}, cache hits {embedder.cache_hits})",
              flush=True)
        embedder.save_cache()
    embeddings = np.vstack(parts)

    meta = {
        "embed_model": args.embed_model,
        "base_url": clients["base_url"],
        "dim": int(embeddings.shape[1]),
        "n_docs": int(embeddings.shape[0]),
        "tickers": sorted(per_ticker),
        "per_ticker": dict(per_ticker),
        "source_records": str(args.records),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "embed_seconds": round(time.time() - embed_started, 1),
        "api_calls": embedder.api_calls,
        "cache_hits": embedder.cache_hits,
    }
    save_index(args.index_dir, corpus, embeddings, meta)
    embedder.save_cache()

    print(f"\nwrote    {args.index_dir}")
    print(f"           corpus.jsonl     {len(corpus):,} rows")
    print(f"           embeddings.npy   {embeddings.shape} float32 "
          f"({embeddings.nbytes / 1e6:.0f} MB)")

    if args.export_json:
        from ragtest.export_json import DEFAULT_OUTPUT, export_claims_json
        export_claims_json(DEFAULT_OUTPUT, corpus, embeddings, meta)
        print(f"           {DEFAULT_OUTPUT.name}  "
              f"{DEFAULT_OUTPUT.stat().st_size / 1e6:.0f} MB "
              f"(one file: câu claim + vector, in {DEFAULT_OUTPUT.parent})")

    print(f"\nnext:    python ragtest/query.py --interactive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
