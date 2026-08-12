"""
EDA: which company has the most news coverage?

Reads three independent sources so results cross-check each other:
  1. data/outputs/news/coverage.csv        - crawler's own per-ticker summary
  2. data/outputs/news/<TICKER>.jsonl      - recomputed article/sentence counts
     (counted straight from the crawled sentence files, in case coverage.csv is stale)
  3. data/labeled/news_labeled/all_news_sentences_classified.jsonl
     - how many of those sentences are actually ESG-relevant (esg=true)

Run from repo root:
    python notebooks/eda/news_volume_by_company.py
Outputs a ranked table to stdout, a CSV, and a PNG chart under notebooks/eda/output/.
"""

import json
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[2]
NEWS_DIR = REPO_ROOT / "data" / "outputs" / "news"
COVERAGE_CSV = NEWS_DIR / "coverage.csv"
LABELED_NEWS = REPO_ROOT / "data" / "labeled" / "news_labeled" / "all_news_sentences_classified.jsonl"
OUT_DIR = Path(__file__).resolve().parent / "output"


def load_coverage() -> pd.DataFrame:
    df = pd.read_csv(COVERAGE_CSV)
    return df[["ticker", "company", "candidates", "articles", "sentences"]]


def recount_from_jsonl() -> pd.DataFrame:
    rows = []
    for path in sorted(NEWS_DIR.glob("*.jsonl")):
        ticker = path.stem
        n_sentences = 0
        articles = set()
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                n_sentences += 1
                articles.add(rec.get("source_pdf") or rec.get("url"))
        rows.append({"ticker": ticker, "articles_recount": len(articles), "sentences_recount": n_sentences})
    return pd.DataFrame(rows)


def count_esg_sentences() -> pd.DataFrame:
    counts = {}
    esg_counts = {}
    with LABELED_NEWS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            t = rec.get("ticker")
            counts[t] = counts.get(t, 0) + 1
            if rec.get("esg"):
                esg_counts[t] = esg_counts.get(t, 0) + 1
    rows = [
        {"ticker": t, "labeled_sentences": counts[t], "esg_sentences": esg_counts.get(t, 0)}
        for t in counts
    ]
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    coverage = load_coverage()
    recount = recount_from_jsonl()
    esg = count_esg_sentences()

    df = coverage.merge(recount, on="ticker", how="outer").merge(esg, on="ticker", how="outer")
    df = df.sort_values("sentences_recount", ascending=False).reset_index(drop=True)

    # sanity check: coverage.csv vs recomputed counts should agree if the crawl is up to date
    mismatch = df[df["sentences"] != df["sentences_recount"]]

    print(f"Companies with a news file: {len(df)}")
    print(f"Rows where coverage.csv disagrees with a fresh recount: {len(mismatch)}\n")

    print("=== Top 15 companies by article count (most news) ===")
    top_articles = df.sort_values("articles_recount", ascending=False).head(15)
    print(top_articles[["ticker", "company", "articles_recount", "sentences_recount", "esg_sentences"]].to_string(index=False))

    print("\n=== Top 15 companies by ESG-relevant news sentences ===")
    top_esg = df.sort_values("esg_sentences", ascending=False).head(15)
    print(top_esg[["ticker", "company", "articles_recount", "sentences_recount", "esg_sentences"]].to_string(index=False))

    print("\n=== Summary stats ===")
    print(df[["candidates", "articles_recount", "sentences_recount", "esg_sentences"]].describe().to_string())

    out_csv = OUT_DIR / "news_volume_by_company.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nFull table written to {out_csv}")

    # chart: top 20 by article count
    top20 = df.sort_values("articles_recount", ascending=False).head(20)
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(top20["ticker"][::-1], top20["articles_recount"][::-1], color="#4C72B0")
    ax.set_xlabel("Number of articles")
    ax.set_title("Top 20 companies by news article count")
    fig.tight_layout()
    out_png = OUT_DIR / "top20_companies_by_article_count.png"
    fig.savefig(out_png, dpi=150)
    print(f"Chart written to {out_png}")


if __name__ == "__main__":
    main()
