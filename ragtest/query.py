#!/usr/bin/env python3
"""
Query the ragtest index with a news sentence and get back the annual-report ESG claims of
that same company.

Pipeline per query:
    detect company  -> alias match on the sentence (or --ticker to force it)
    retrieve        -> BM25 + dense cosine, both filtered to that company, fused by RRF
    rerank          -> GLM reorders the shortlist (listwise, one call)
    verdict         -> GLM says which claim matches and whether it supports/contradicts
    save            -> one JSONL row per query, for the evaluation to score later

    python ragtest/query.py --interactive
    python ragtest/query.py -q "Nhựa An Phát Xanh ra mắt bao bì phân huỷ sinh học"
    python ragtest/query.py -q "..." --ticker AAA --no-llm      # free: retrieval only
    python ragtest/query.py --from-news --ticker AAA --limit 20  # batch from the news corpus

`--no-llm` runs retrieval alone, with no API call at all — use it to sanity-check the
index for free before spending anything on reranking.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

from ragtest.answer import VerdictAnswerer  # noqa: E402
from ragtest.build_index import load_index  # noqa: E402
from ragtest.company import detect_ticker, load_aliases  # noqa: E402
from ragtest.config import (  # noqa: E402
    CHAT_MODEL,
    DEFAULT_FINAL_K,
    DEFAULT_POOL,
    DEFAULT_TOP_K,
    EMBED_MODEL,
    INDEX_DIR,
    ISSUER_REGISTRY,
    NEWS_PREPROCESSED,
    RESULTS_PATH,
)
from ragtest.corpus import TICKERS  # noqa: E402
from ragtest.llm import build_clients  # noqa: E402
from ragtest.rerank import LLMReranker  # noqa: E402
from ragtest.retriever import HybridRetriever  # noqa: E402
from ragtest.store import save_result  # noqa: E402


def news_queries(path: Path, ticker=None, limit=20, esg_only=True):
    """Sample real news sentences from the preprocessed news corpus already on disk."""
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("ticker") not in (TICKERS if ticker is None else (ticker,)):
                continue
            if esg_only and not row.get("labels"):
                continue
            if len((row.get("text") or "").split()) < 8:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def show(candidates, final_k):
    if not candidates:
        print("    (không tìm thấy ứng viên nào)")
        return
    # Number by display position: without --rerank neither rerank_rank nor fusion_rank
    # is set, and reading them would print "1." against every row.
    for position, candidate in enumerate(candidates[:final_k]):
        channels = []
        if candidate.get("bm25_rank") is not None:
            channels.append(f"bm25#{candidate['bm25_rank'] + 1}")
        if candidate.get("dense_rank") is not None:
            channels.append(f"dense#{candidate['dense_rank'] + 1}")
        print(f"    {position + 1}. [{candidate['ticker']} {candidate.get('year')}] "
              f"{candidate['source_pdf']} tr.{candidate['page']}  "
              f"({', '.join(channels) or 'fusion'})")
        print(f"       {candidate['text'][:300]}")


def run_one(query, retriever, aliases, reranker, answerer, args):
    ticker = args.ticker or detect_ticker(query, aliases)
    scope = ticker or "TẤT CẢ 5 công ty (không nhận ra tên công ty trong câu)"
    print(f"\n>>> {query}")
    print(f"    công ty: {scope}")

    candidates = retriever.retrieve(query, ticker=ticker, top_k=args.top_k, pool=args.pool)

    stage = "fusion"
    if reranker is not None and candidates:
        candidates, _ = reranker.rerank(query, candidates)
        stage = "rerank"

    show(candidates, args.final_k)

    verdict = {}
    if answerer is not None and getattr(args, "with_verdict", False):
        verdict = answerer.answer(query, candidates[:args.final_k])
        matched = verdict.get("matched_doc_ids") or []
        print(f"\n    → kết luận: {verdict.get('relation')} "
              f"(confidence {verdict.get('confidence'):.2f})")
        if matched:
            print(f"      claim khớp: {', '.join(matched)}")
        if verdict.get("reason"):
            print(f"      lý do: {verdict['reason']}")
        if not verdict.get("parse_ok"):
            print("      (không đọc được JSON từ mô hình — đã ghi nhận là irrelevant)")

    return save_result(args.results, {
        "query": query,
        "ticker": ticker,
        "ticker_source": "forced" if args.ticker else ("detected" if ticker else "none"),
        "ranking_stage": stage,
        "top_k": args.top_k,
        "pool": args.pool,
        "chat_model": args.chat_model if reranker or answerer else None,
        "embed_model": args.embed_model,
        "candidates": candidates,
        "verdict": verdict,
    })


def main() -> int:
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-q", "--query", help="one news sentence")
    source.add_argument("--interactive", action="store_true", help="paste sentences one by one")
    source.add_argument("--from-news", action="store_true",
                        help="take real sentences from the preprocessed news corpus")

    parser.add_argument("--ticker", choices=list(TICKERS),
                        help="force the company instead of detecting it from the sentence")
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--news", type=Path, default=NEWS_PREPROCESSED)
    parser.add_argument("--limit", type=int, default=20, help="--from-news: how many sentences")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help="candidates handed to the reranker")
    parser.add_argument("--final-k", type=int, default=DEFAULT_FINAL_K,
                        help="candidates shown and sent to the verdict prompt")
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL,
                        help="candidates pulled from each channel before fusion")
    parser.add_argument("--chat-model", default=CHAT_MODEL)
    parser.add_argument("--embed-model", default=EMBED_MODEL)
    parser.add_argument("--no-llm", action="store_true",
                        help="retrieval only — no rerank, no verdict, no API cost")
    parser.add_argument("--no-rerank", action="store_true", help="keep the fusion order")
    parser.add_argument("--no-verdict", action="store_true", help="skip the answer prompt")
    parser.add_argument("--with-verdict", action="store_true", help="enable the LLM verdict step")
    args = parser.parse_args()

    corpus, embeddings, meta = load_index(args.index_dir)
    print(f"index    {len(corpus):,} claim sentences · {meta.get('embed_model')} "
          f"· dim {meta.get('dim')}")

    aliases = load_aliases(ISSUER_REGISTRY, args.news)

    # The query still needs embedding even with --no-llm; that call is cached and costs
    # ~nothing, but if it cannot be made we fall back to BM25 alone rather than failing.
    embedder = reranker = answerer = None
    try:
        clients = build_clients(args.chat_model, args.embed_model,
                                cache_path=args.index_dir / "embed_cache.json")
        embedder = clients["embed"]
        if not args.no_llm:
            if not args.no_rerank:
                reranker = LLMReranker(clients["chat"], args.chat_model)
            if not args.no_verdict:
                answerer = VerdictAnswerer(clients["chat"], args.chat_model)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: no API client ({exc}) — falling back to BM25-only retrieval")

    retriever = HybridRetriever(corpus, embeddings, embedder=embedder)
    mode = "bm25+dense" if embedder else "bm25 only"
    extras = [name for name, on in (("rerank", reranker), ("verdict", answerer)) if on]
    print(f"mode     {mode}{' + ' + ' + '.join(extras) if extras else ''}")
    print(f"results  {args.results}")

    if args.query:
        run_one(args.query, retriever, aliases, reranker, answerer, args)
        return 0

    if args.from_news:
        rows = news_queries(args.news, ticker=args.ticker, limit=args.limit)
        print(f"\n{len(rows)} câu tin tức lấy từ {args.news.name}")
        for row in rows:
            forced = args.ticker
            args.ticker = forced or row.get("ticker")  # the news corpus knows its ticker
            run_one(row["text"], retriever, aliases, reranker, answerer, args)
            args.ticker = forced
        return 0

    print("\nDán một câu tin tức rồi Enter. Gõ 'quit' để thoát.")
    while True:
        try:
            line = input("\nnews> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in {"quit", "exit", "q"}:
            break
        run_one(line, retriever, aliases, reranker, answerer, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
