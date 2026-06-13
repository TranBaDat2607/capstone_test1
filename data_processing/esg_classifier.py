"""ESG sentence classifier wrapping `nguyen599/ViDeBERTa-v3-ESG-base`.

This is the *GPU* half of the hybrid pipeline (see prepare_sentences.py for the
local half). It is intentionally self-contained — it depends only on `torch` and
`transformers`, so the same file imports cleanly on Kaggle.

IMPORTANT — the model is **multi-label**:
    config.problem_type == "multi_label_classification"
so we apply a per-label **sigmoid** (NOT softmax). An E/S/G pillar tag is assigned
when its sigmoid score >= `threshold` (default 0.45).

Labels (config.id2label):  0 -> Neutral  ("Neural" in the card)
                           1 -> Environmental
                           2 -> Social
                           3 -> Governance

ESG-relevance is decided from the **Neutral** score, not from a single pillar:
    esg = (Neutral < neutral_threshold)   # default 0.5
In practice this model spreads probability like a softmax (pillars + Neutral ~= 1)
and almost never tags two pillars at once, so a clearly-ESG sentence can have its
signal *split* across two pillars (e.g. labour-law compliance -> S=0.44, G=0.44)
with neither clearing the bar. Keying `esg` off Neutral recovers those cases while
still excluding true boilerplate (which scores Neutral ~= 0.95+).

CLI (read a sentences file, append predictions):
    python -m data_processing.esg_classifier \
        --input  data/processed/aaa_sentences.jsonl \
        --output data/processed/aaa_classified.jsonl \
        --batch-size 32 --threshold 0.5

On a machine with no GPU this runs on CPU (slow but correct); on Kaggle with an
accelerator attached it auto-selects CUDA.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

MODEL_ID = "nguyen599/ViDeBERTa-v3-ESG-base"
ESG_PILLARS = ("Environmental", "Social", "Governance")


def _normalize_label(label: str) -> str:
    # The published config spells the neutral class "Neural"; normalize it.
    return "Neutral" if label.strip().lower() in {"neural", "neutral", "none"} else label


def load_classifier(model_id: str = MODEL_ID, device: str | None = None):
    """Load (tokenizer, model, device, id2label). Auto-selects CUDA when available."""
    import torch  # local import so prepare_sentences.py never needs torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.to(device)
    model.eval()

    id2label = {int(i): _normalize_label(lbl) for i, lbl in model.config.id2label.items()}
    return tokenizer, model, device, id2label


def classify(
    texts: list[str],
    tokenizer=None,
    model=None,
    device: str | None = None,
    id2label: dict[int, str] | None = None,
    batch_size: int = 32,
    max_length: int = 256,
    threshold: float = 0.45,
    neutral_threshold: float = 0.5,
) -> list[dict]:
    """Classify `texts`. Loads the model on first call if not supplied.

    Returns one dict per text:
        {scores: {label: float, ...}, labels: [E/S/G pillars >= threshold], esg: bool}
    where `esg` is True iff Neutral < `neutral_threshold` (robust to split signals).
    """
    import torch

    if model is None or tokenizer is None:
        tokenizer, model, device, id2label = load_classifier(device=device)
    assert id2label is not None and device is not None

    results: list[dict] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        enc = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            logits = model(**enc).logits
            probs = torch.sigmoid(logits).cpu().tolist()  # multi-label -> sigmoid

        for row in probs:
            scores = {id2label[i]: round(float(p), 4) for i, p in enumerate(row)}
            # Pillar tags: any E/S/G clearing the per-label threshold.
            labels = [p for p in ESG_PILLARS if scores.get(p, 0.0) >= threshold]
            # ESG-relevance: keyed off Neutral so split signals aren't dropped.
            esg = scores.get("Neutral", 0.0) < neutral_threshold
            results.append({"scores": scores, "labels": labels, "esg": esg})
    return results


def _read_sentences(path: Path) -> list[dict]:
    rows: list[dict] = []
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    else:  # jsonl
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    return rows


def _write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_csv(rows: list[dict], path: Path) -> None:
    """Flatten predictions into spreadsheet-friendly columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_pdf", "page", "sentence_index", "text",
              "labels", "esg", *ESG_PILLARS, "Neutral"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            scores = r.get("scores", {})
            w.writerow({
                "source_pdf": r.get("source_pdf", ""),
                "page": r.get("page", ""),
                "sentence_index": r.get("sentence_index", ""),
                "text": r.get("text", ""),
                "labels": ", ".join(r.get("labels", [])),
                "esg": r.get("esg", ""),
                **{p: scores.get(p, "") for p in (*ESG_PILLARS, "Neutral")},
            })


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="sentences .jsonl or .csv (from prepare_sentences).")
    ap.add_argument("--output", required=True, help="output .jsonl path (a sibling .csv is also written).")
    ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--threshold", type=float, default=0.45,
                    help="Sigmoid cutoff to assign an E/S/G pillar tag (multi-label model).")
    ap.add_argument("--neutral-threshold", type=float, default=0.5,
                    help="A sentence is ESG-relevant when its Neutral score is below this.")
    ap.add_argument("--esg-only", action="store_true",
                    help="Keep only ESG-relevant sentences (Neutral < neutral-threshold).")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    rows = _read_sentences(in_path)
    if not rows:
        print("No input sentences.", file=sys.stderr)
        return 1
    texts = [str(r.get("text", "")) for r in rows]

    tokenizer, model, device, id2label = load_classifier(model_id=args.model_id)
    print(f"Loaded {args.model_id} on {device}. Classifying {len(texts)} sentences...")

    preds = classify(
        texts,
        tokenizer=tokenizer, model=model, device=device, id2label=id2label,
        batch_size=args.batch_size, max_length=args.max_length,
        threshold=args.threshold, neutral_threshold=args.neutral_threshold,
    )
    merged = [{**row, **pred} for row, pred in zip(rows, preds)]
    if args.esg_only:
        merged = [r for r in merged if r.get("esg")]

    _write_jsonl(merged, out_path)
    _write_csv(merged, out_path.with_suffix(".csv"))

    # Summary
    counts = {lbl: 0 for lbl in ESG_PILLARS}
    esg_total = 0
    for r in merged:
        for lbl in r.get("labels", []):
            counts[lbl] = counts.get(lbl, 0) + 1
        esg_total += int(bool(r.get("esg")))
    print(f"\nWrote {len(merged)} rows -> {out_path} (+ .csv)")
    print(f"ESG-relevant (Neutral<{args.neutral_threshold}): {esg_total}/{len(merged)}  "
          f"|  pillar tag counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
