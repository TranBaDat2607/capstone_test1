"""
EDA: which companies have the most ESG-classified news sentences?

Source: data/labeled/news_labeled/all_news_sentences_classified.jsonl
  (ViDeBERTa-v3-ESG classifier output on the news corpus; `esg` is the
  overall E/S/G-vs-Neutral flag, `labels` is the multi-label subset of
  {Environmental, Social, Governance} for that sentence.)

Run from repo root:
    python notebooks/eda/esg_news_volume_by_company.py
Outputs a ranked table to stdout, a CSV, and charts under notebooks/eda/output/.
"""

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELED_NEWS = REPO_ROOT / "data" / "labeled" / "news_labeled" / "all_news_sentences_classified.jsonl"
OUT_DIR = Path(__file__).resolve().parent / "output"


def load_counts() -> pd.DataFrame:
    total = Counter()
    esg_true = Counter()
    env = Counter()
    soc = Counter()
    gov = Counter()
    company_name = {}

    with LABELED_NEWS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ticker = rec.get("ticker")
            total[ticker] += 1
            company_name.setdefault(ticker, rec.get("company"))
            if rec.get("esg"):
                esg_true[ticker] += 1
                labels = rec.get("labels", [])
                if "Environmental" in labels:
                    env[ticker] += 1
                if "Social" in labels:
                    soc[ticker] += 1
                if "Governance" in labels:
                    gov[ticker] += 1

    rows = []
    for ticker, n_total in total.items():
        n_esg = esg_true.get(ticker, 0)
        rows.append({
            "ticker": ticker,
            "company": company_name.get(ticker),
            "total_sentences": n_total,
            "esg_sentences": n_esg,
            "esg_ratio": round(n_esg / n_total, 4) if n_total else 0.0,
            "environmental_sentences": env.get(ticker, 0),
            "social_sentences": soc.get(ticker, 0),
            "governance_sentences": gov.get(ticker, 0),
        })
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_counts().sort_values("esg_sentences", ascending=False).reset_index(drop=True)

    print(f"Companies with news: {len(df)}")
    print(f"Total ESG-classified news sentences (esg=true) across sector: {df['esg_sentences'].sum()}\n")

    print("=== Top 20 companies by ESG-classified news sentence count ===")
    print(df.head(20)[[
        "ticker", "company", "total_sentences", "esg_sentences", "esg_ratio",
        "environmental_sentences", "social_sentences", "governance_sentences",
    ]].to_string(index=False))

    print("\n=== Top 10 by ESG ratio (esg_sentences / total_sentences), min 500 total sentences ===")
    ratio_ranked = df[df["total_sentences"] >= 500].sort_values("esg_ratio", ascending=False).head(10)
    print(ratio_ranked[["ticker", "company", "total_sentences", "esg_sentences", "esg_ratio"]].to_string(index=False))

    print("\n=== Summary stats ===")
    print(df[["total_sentences", "esg_sentences", "esg_ratio",
              "environmental_sentences", "social_sentences", "governance_sentences"]].describe().to_string())

    out_csv = OUT_DIR / "esg_news_volume_by_company.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nFull table written to {out_csv}")

    # Chart 1: top 20 by total ESG sentence count, stacked by pillar
    top20 = df.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 9))
    ax.barh(top20["ticker"], top20["environmental_sentences"], color="#55A868", label="Environmental")
    ax.barh(top20["ticker"], top20["social_sentences"], left=top20["environmental_sentences"],
            color="#4C72B0", label="Social")
    ax.barh(top20["ticker"],
            top20["governance_sentences"],
            left=top20["environmental_sentences"] + top20["social_sentences"],
            color="#C44E52", label="Governance")
    ax.set_xlabel("Number of ESG-classified news sentences")
    ax.set_title("Top 20 companies by ESG-classified news sentences (by pillar)")
    ax.legend()
    fig.tight_layout()
    out_png1 = OUT_DIR / "top20_companies_by_esg_news_sentences.png"
    fig.savefig(out_png1, dpi=150)
    print(f"Chart written to {out_png1}")

    # Chart 2: distribution of esg_ratio across all companies
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    ax2.hist(df["esg_ratio"], bins=20, color="#4C72B0", edgecolor="white")
    ax2.set_xlabel("ESG sentence ratio (esg_sentences / total_sentences)")
    ax2.set_ylabel("Number of companies")
    ax2.set_title("Distribution of ESG-relevance ratio across companies")
    fig2.tight_layout()
    out_png2 = OUT_DIR / "esg_ratio_distribution.png"
    fig2.savefig(out_png2, dpi=150)
    print(f"Chart written to {out_png2}")


if __name__ == "__main__":
    main()
