"""
Preprocess the news-channel labeled JSONL (Step P1 of docs/SYSTEM_DESIGN.md).

Two jobs, and only two (SYSTEM_DESIGN §7.1 + §8.2):
  1. Date normalization  — news `publish_date` is unreliable (trafilatura placeholder
     "2002-01-01", values equal to the crawl date, empty strings). Compute a trustworthy
     effective date + an uncertainty flag so the downstream temporal cross-check (§7.2)
     has something to align on.
  2. Boilerplate filtering — drop junk rows using signals the crawler already emits
     (`company_mentioned`, near-empty `text`). We do NOT drop `esg=false` rows here; the
     upstream ESG gate is trusted downstream (§8.2).

Explicitly out of scope (§8.1): no `source_domain` routing, no `news_domain_policy.json`.

Non-destructive: every original field is preserved (sentence-level traceability, per
CLAUDE.md); we only ADD `publish_date_normalized`, `publish_year`, `date_uncertain`.

Input  : data/labeled/news_labeled/  (folder of labeled *.jsonl, searched recursively)
Output : data/interim/news_preprocessed/
           - <subfolder>/<name>_preprocessed.jsonl   mirroring the input layout
           - preprocess_news_stats.json               summary counts

Run:  python -m data_processing.preprocess_news
      python -m data_processing.preprocess_news --input data/labeled/news_labeled
      python -m data_processing.preprocess_news --min-chars 20
"""

import argparse
import json
import glob
import os
import re
from collections import defaultdict
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "data", "labeled", "news_labeled")
OUT_DIR = os.path.join(REPO_ROOT, "data", "interim", "news_preprocessed")

PLACEHOLDER_DATES = {"2002-01-01"}
MIN_YEAR = 1990
DEFAULT_MIN_CHARS = 15


def normalize_date(raw: str) -> str:
    """Coerce assorted date strings to YYYY-MM-DD; return "" if unrecognizable."""
    if not raw:
        return ""
    s = raw.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r"^(\d{4}-\d{2})$", s)
    if m:
        return s + "-01"
    return ""


def extract_year_from_url(url: str) -> "str | None":
    """Recover a 4-digit year from common Vietnamese news URL patterns."""
    if not url:
        return None
    m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6,}\.htm", url)
    if m:
        y = int(m.group(1))
        if 2005 <= y <= 2030:
            return str(y)
    m = re.search(r"185(\d{2})(\d{2})(\d{2})\d+\.htm", url)
    if m:
        return "20" + m.group(1)
    m = re.search(r"/(20[0-2]\d)/", url)
    if m:
        return m.group(1)
    return None


def _year_from_text(*texts: str) -> "str | None":
    """Last-resort: a plausible 20xx year mentioned in the title/body text."""
    for t in texts:
        if not t:
            continue
        for m in re.finditer(r"\b(20[0-2]\d)\b", t):
            return m.group(1)
    return None


def normalize_effective_date(row: dict, current_year: int) -> dict:
    """
    Resolve a trustworthy effective date for a news record (SYSTEM_DESIGN §7.1).

    Returns {"publish_date_normalized", "publish_year", "date_uncertain"} following the
    fallback chain:
      (a) trust `publish_date` if plausible (not placeholder, not == crawl date, in range)
      (b) else recover a YEAR from the url / title / text  -> YYYY-01-01, uncertain
      (c) else give up: "" / None / uncertain (date_crawled stays only as a loose bound)
    """
    crawl_date = (row.get("date_crawled") or "")[:10]

    norm = normalize_date(row.get("publish_date") or "")
    if norm and norm not in PLACEHOLDER_DATES and norm != crawl_date:
        year = int(norm[:4])
        if MIN_YEAR <= year <= current_year:
            return {
                "publish_date_normalized": norm,
                "publish_year": year,
                "date_uncertain": False,
            }

    year_str = extract_year_from_url(row.get("url") or "") or _year_from_text(
        row.get("title") or "", row.get("text") or ""
    )
    if year_str:
        year = int(year_str)
        if MIN_YEAR <= year <= current_year:
            return {
                "publish_date_normalized": f"{year}-01-01",
                "publish_year": year,
                "date_uncertain": True,
            }

    return {"publish_date_normalized": "", "publish_year": None, "date_uncertain": True}


def is_boilerplate(row: dict, min_chars: int) -> bool:
    """True if the record should be dropped as noise (SYSTEM_DESIGN §8.2)."""
    if not row.get("company_mentioned"):
        return True
    if len((row.get("text") or "").strip()) < min_chars:
        return True
    return False


def main(input_dir=INPUT_DIR, out_dir=OUT_DIR, min_chars=DEFAULT_MIN_CHARS):
    os.makedirs(out_dir, exist_ok=True)
    current_year = datetime.now().year

    input_files = sorted(glob.glob(os.path.join(input_dir, "**", "*.jsonl"), recursive=True))
    if not input_files:
        print(f"No .jsonl found under {input_dir}")
        return

    per_file = {}
    totals = defaultdict(int)

    for path in input_files:
        rel = os.path.relpath(path, input_dir)
        stem, ext = os.path.splitext(rel)
        out_path = os.path.join(out_dir, stem + "_preprocessed" + ext)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        read = kept = dropped = uncertain = 0
        with open(path, encoding="utf-8") as src, \
                open(out_path, "w", encoding="utf-8") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                read += 1
                row = json.loads(line)

                if is_boilerplate(row, min_chars):
                    dropped += 1
                    continue

                row.update(normalize_effective_date(row, current_year))
                if row["date_uncertain"]:
                    uncertain += 1
                dst.write(json.dumps(row, ensure_ascii=False) + "\n")
                kept += 1

        per_file[rel] = {"read": read, "kept": kept, "dropped": dropped, "date_uncertain": uncertain}
        for k, v in per_file[rel].items():
            totals[k] += v
        print(f"wrote {out_path}  (read {read}, kept {kept}, dropped {dropped}, uncertain {uncertain})")

    stats = {
        "input_dir": input_dir,
        "out_dir": out_dir,
        "min_chars": min_chars,
        "totals": dict(totals),
        "per_file": per_file,
    }
    stats_path = os.path.join(out_dir, "preprocess_news_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"wrote {stats_path}")
    print("\nSUMMARY:", json.dumps(stats["totals"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess news labeled JSONL: normalize publish dates + drop boilerplate.")
    parser.add_argument("--input", default=INPUT_DIR,
                        help="input folder of news *.jsonl (searched recursively). "
                             "Default: data/labeled/news_labeled")
    parser.add_argument("--out", default=OUT_DIR,
                        help="output folder. Default: data/interim/news_preprocessed")
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS,
                        help=f"drop records whose text is shorter than this after strip "
                             f"(default: {DEFAULT_MIN_CHARS})")
    cli = parser.parse_args()
    main(input_dir=cli.input, out_dir=cli.out, min_chars=cli.min_chars)
