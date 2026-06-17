"""
Extract ESG-labeled text from the labeled JSONL files.

Input  : data/labeled/  (a folder of subfolders, each holding labeled *.jsonl,
                          one labeled sentence per line)
Output : data/outputs/esg_extracted/
           - <subfolder>/<name>_extracted.jsonl   one clean record per ESG-labeled
                                                   sentence, mirroring the input layout
           - esg_all_records.jsonl                all sources merged
           - esg_by_document.json                 records grouped by source document
           - esg_stats.json                       summary counts

A record is kept when its `labels` array is non-empty (i.e. an E/S/G
category was assigned). Output records are trimmed to the fields useful
for building a GraphRAG schema later; add/remove fields in `make_record`.

Run:  python -m data_processing.extract_esg
      python -m data_processing.extract_esg --input data/labeled/news_labeled
      python -m data_processing.extract_esg --input data/labeled/news_labeled --out data/outputs/news_extracted
"""

import argparse
import json
import glob
import os
from collections import defaultdict

# ---- config ---------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "data", "labeled")            # folder of *.jsonl (searched recursively)
OUT_DIR = os.path.join(REPO_ROOT, "data", "outputs", "esg_extracted")
ESG_CATEGORIES = ("Environmental", "Social", "Governance")


def make_record(obj, source_file):
    """Trim a raw labeled object down to the fields useful for GraphRAG."""
    return {
        "source_file": source_file,           # which labeled file it came from
        "source_pdf": obj.get("source_pdf"),  # source document / article id
        "page": obj.get("page"),
        "sentence_index": obj.get("sentence_index"),
        "text": obj.get("text"),
        "labels": obj.get("labels"),          # assigned ESG categories
        "scores": obj.get("scores"),          # classifier probabilities (optional)
    }


def is_esg_labeled(obj):
    """Keep sentences that have at least one assigned ESG category."""
    return bool(obj.get("labels"))


def main(input_dir=INPUT_DIR, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)

    all_records = []
    by_document = defaultdict(list)
    per_file_counts = {}
    label_counts = defaultdict(int)

    # every *.jsonl under input_dir, including nested subfolders
    input_files = sorted(glob.glob(os.path.join(input_dir, "**", "*.jsonl"), recursive=True))
    if not input_files:
        print(f"No .jsonl found under {input_dir}")
        return

    for path in input_files:
        # mirror the input subfolder layout under out_dir, and append _extracted to the name
        rel = os.path.relpath(path, input_dir)                       # e.g. news_labeled/aaa_news_classified.jsonl
        stem, ext = os.path.splitext(rel)                           # ("news_labeled/aaa_news_classified", ".jsonl")
        per_file_out = os.path.join(out_dir, stem + "_extracted" + ext)
        os.makedirs(os.path.dirname(per_file_out), exist_ok=True)
        kept = 0

        with open(path, encoding="utf-8") as src, \
                open(per_file_out, "w", encoding="utf-8") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not is_esg_labeled(obj):
                    continue
                rec = make_record(obj, rel)
                dst.write(json.dumps(rec, ensure_ascii=False) + "\n")
                all_records.append(rec)
                by_document[rec["source_pdf"]].append(rec)
                for lab in rec["labels"]:
                    label_counts[lab] += 1
                kept += 1

        per_file_counts[rel] = kept
        print(f"wrote {per_file_out}  ({kept} records)")

    # merged JSONL — easiest single input for a downstream schema/graph step
    merged_path = os.path.join(out_dir, "esg_all_records.jsonl")
    with open(merged_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {merged_path}  ({len(all_records)} records)")

    # grouped by source document — convenient for per-doc graph building
    grouped_path = os.path.join(out_dir, "esg_by_document.json")
    with open(grouped_path, "w", encoding="utf-8") as f:
        json.dump(by_document, f, ensure_ascii=False, indent=2)
    print(f"wrote {grouped_path}  ({len(by_document)} documents)")

    # stats
    stats = {
        "total_esg_records": len(all_records),
        "documents": len(by_document),
        "per_file": per_file_counts,
        "label_counts": dict(label_counts),
    }
    stats_path = os.path.join(out_dir, "esg_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"wrote {stats_path}")
    print("\nSUMMARY:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract ESG-labeled sentences from labeled JSONL files.")
    parser.add_argument("--input", default=INPUT_DIR,
                        help="input folder of *.jsonl (searched recursively). Default: data/labeled")
    parser.add_argument("--out", default=OUT_DIR,
                        help="output folder. Default: data/outputs/esg_extracted")
    cli = parser.parse_args()
    main(input_dir=cli.input, out_dir=cli.out)
