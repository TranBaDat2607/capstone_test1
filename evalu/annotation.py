"""
Blind human annotation of claim↔evidence pairs.

No greenwashing ground truth exists for Vietnamese listed companies, so the
project cannot report precision against a gold standard. It CAN report precision
against a documented, blind, reproducible human annotation of its own output —
which is standard practice in domains with no gold labels, provided four things
hold (see ANNOTATION_PROTOCOL.md):

    1. the protocol is fixed before results are looked at
    2. the annotator cannot see the system's verdict
    3. it is reported as author annotation, never as an expert panel
    4. a second annotator scores the same items, so agreement is measurable

Condition 2 is enforced here rather than by discipline: `build_sheet` constructs
items from an explicit whitelist of display fields, so a verdict cannot leak in
by someone later adding a key upstream. `test_sheet_is_blind` guards it.

What this measures, and what it does not
----------------------------------------
Only pairs the system actually cited are annotatable, because pairs adjudicated
`irrelevant` are never written to a dossier. So this yields PRECISION of the
positive verdicts, not recall. Saying otherwise would overclaim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evalu.negative_control import (EVIDENCE_KINDS, attribute_ticker,
                                    load_issuer_variants, mentions_claimant)

LABELS = ("supports", "contradicts", "irrelevant")

# The verdict each system_kind asserts. An annotation matches when the human
# picked the same relation the system implicitly claimed by citing the pair.
KIND_TO_RELATION = {
    "supporting_evidence": "supports",
    "contradicting_evidence": "contradicts",
    "flagged_non_independent_support": "supports",
}

# Fields an annotator is allowed to see. Anything not here cannot reach the sheet.
DISPLAY_FIELDS = ("pair_id", "claim_company", "claim_text", "evidence_text",
                  "evidence_kind_label", "evidence_date",
                  "relation", "about_claim_company", "note")


def _pair_id(claim_id: str, node_index: int, salt: str = "") -> str:
    raw = f"{claim_id}|{node_index}|{salt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def collect_pairs(dossiers: Sequence[Dict[str, Any]],
                  nodes: Sequence[Dict[str, Any]],
                  variants: Optional[Dict[str, set]] = None) -> List[Dict[str, Any]]:
    """Every (claim, evidence) pair the system cited, with its hidden metadata."""
    variants = variants or {}
    out: List[Dict[str, Any]] = []
    for d in dossiers:
        ticker = str(d.get("_ticker") or "").upper()
        claim_id = d.get("claim_id") or ""
        for kind in EVIDENCE_KINDS:
            for ev in (d.get(kind) or []):
                xi = ev.get("node_index")
                if not isinstance(xi, int) or not (0 <= xi < len(nodes)):
                    continue
                node = nodes[xi]
                ev_ticker = attribute_ticker(node)
                same_auto = (ev_ticker == ticker) or mentions_claimant(
                    node, variants.get(ticker, {ticker.lower()}))
                out.append({
                    "pair_id": _pair_id(claim_id, xi),
                    "claim_id": claim_id,
                    "claim_company": ticker,
                    "claim_text": d.get("claim_text") or "",
                    "node_index": xi,
                    "evidence_text": (ev.get("text") or "")[:600],
                    "evidence_kind_label": node.get("class"),
                    "evidence_date": ev.get("date") or ev.get("year"),
                    # hidden from the sheet, kept for scoring
                    "system_kind": kind,
                    "assessment": d.get("assessment"),
                    "evidence_ticker": ev_ticker,
                    "same_company_auto": bool(same_auto),
                    "is_decoy": False,
                })
    return out


def sample_pairs(pairs: Sequence[Dict[str, Any]], n: int,
                 seed: int = 42) -> List[Dict[str, Any]]:
    """
    Reproducible stratified sample.

    Strata are (claim_company, system_kind) so no company and neither verdict
    kind can vanish from the sample by chance — with one dominant ticker in this
    corpus, simple random sampling could easily return almost no ADP or ACC.
    Quotas are proportional, with any rounding remainder filled from the largest
    strata. n >= population returns the whole population (a census).
    """
    pairs = list(pairs)
    if n >= len(pairs):
        return sorted(pairs, key=lambda p: p["pair_id"])

    rng = random.Random(seed)
    strata: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for p in pairs:
        strata[(p["claim_company"], p["system_kind"])].append(p)

    total = len(pairs)
    picked: List[Dict[str, Any]] = []
    leftovers: List[Dict[str, Any]] = []
    for key in sorted(strata):
        bucket = sorted(strata[key], key=lambda p: p["pair_id"])
        rng.shuffle(bucket)
        # at least one from every stratum, so small companies stay represented
        quota = max(1, round(n * len(bucket) / total))
        quota = min(quota, len(bucket))
        picked.extend(bucket[:quota])
        leftovers.extend(bucket[quota:])

    rng.shuffle(leftovers)
    if len(picked) > n:
        picked = picked[:n]
    else:
        picked.extend(leftovers[: n - len(picked)])
    return sorted(picked, key=lambda p: p["pair_id"])


def _make_decoys(pairs: Sequence[Dict[str, Any]], k: int,
                 seed: int) -> List[Dict[str, Any]]:
    """
    Attention checks: a real claim paired with an unrelated piece of evidence.

    These are near-certainly `irrelevant`. Marking them as supports/contradicts
    means the annotation session was not being done carefully, and the whole
    batch should be re-run rather than quietly reported.
    """
    if k <= 0 or len(pairs) < 2:
        return []
    rng = random.Random(seed + 977)
    out = []
    for i in range(k):
        a, b = rng.sample(list(pairs), 2)
        out.append({
            "pair_id": _pair_id(a["claim_id"], b["node_index"], salt=f"decoy{i}"),
            "claim_id": a["claim_id"],
            "claim_company": a["claim_company"],
            "claim_text": a["claim_text"],
            "node_index": b["node_index"],
            "evidence_text": b["evidence_text"],
            "evidence_kind_label": b["evidence_kind_label"],
            "evidence_date": b["evidence_date"],
            "system_kind": None,
            "assessment": None,
            "evidence_ticker": b["evidence_ticker"],
            "same_company_auto": None,
            "is_decoy": True,
        })
    return out


def build_sheet(pairs: Sequence[Dict[str, Any]], decoys: int = 0,
                seed: int = 42, annotator: str = "") -> Dict[str, Any]:
    """
    A blind annotation sheet.

    Items are built from DISPLAY_FIELDS only, so no field carrying the system's
    verdict can reach the annotator even if `pairs` grows new keys later.
    """
    items_src = list(pairs) + _make_decoys(pairs, decoys, seed)
    rng = random.Random(seed + 31)
    rng.shuffle(items_src)

    items = []
    for p in items_src:
        item = {k: p.get(k) for k in DISPLAY_FIELDS}
        item["relation"] = None            # supports | contradicts | irrelevant
        item["about_claim_company"] = None  # True | False
        item["note"] = ""
        items.append(item)

    return {
        "schema": "evalu.annotation/v1",
        "annotator": annotator,
        "seed": seed,
        "labels": list(LABELS),
        "instructions": (
            "Với mỗi dòng, đọc TUYÊN BỐ và BẰNG CHỨNG rồi trả lời 2 câu:\n"
            "  relation             : supports | contradicts | irrelevant\n"
            "  about_claim_company  : true nếu bằng chứng nói về ĐÚNG doanh nghiệp "
            "ở cột claim_company, false nếu nói về doanh nghiệp khác\n"
            "Chấm độc lập, KHÔNG tra kết luận của hệ thống. Nếu phân vân giữa "
            "supports và irrelevant, chọn irrelevant (quy tắc thận trọng, "
            "xem ANNOTATION_PROTOCOL.md §4)."
        ),
        "items": items,
        # the answer key: kept beside the sheet, never on an item
        "_key": {p["pair_id"]: {k: p.get(k) for k in
                                ("system_kind", "assessment", "evidence_ticker",
                                 "same_company_auto", "is_decoy", "claim_company")}
                 for p in items_src},
        "_decoy_ids": [p["pair_id"] for p in items_src if p["is_decoy"]],
    }


def write_sheet(sheet: Dict[str, Any], out_dir: Path,
                name: str = "sheet") -> Dict[str, Path]:
    """Write the sheet as JSON (source of truth) plus a CSV for Excel."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    csv_path = out_dir / f"{name}.csv"
    json_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(DISPLAY_FIELDS))
        w.writeheader()
        for item in sheet["items"]:
            w.writerow({k: item.get(k) for k in DISPLAY_FIELDS})
    return {"json": json_path, "csv": csv_path}


def read_annotations(path: Path) -> List[Dict[str, Any]]:
    """Read a filled sheet back — JSON or the CSV round-trip."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        blob = json.loads(path.read_text(encoding="utf-8"))
        return blob.get("items", blob)
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    if s in ("true", "1", "yes", "y", "co", "có"):
        return True
    if s in ("false", "0", "no", "n", "khong", "không"):
        return False
    return None


def score(sheet: Dict[str, Any],
          annotations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Turn a filled sheet into the numbers the thesis needs.

    precision.overall           the system cited this pair as supports/contradicts;
                                did the annotator agree?
    precision.same_company_only the same figure restricted to pairs the annotator
                                judged to be about the right company — i.e. an
                                estimate of precision AFTER the cross-company fix,
                                computable from this one session because the fix
                                only removes pairs
    attribution_validation      annotator's company judgement vs negative_control's
                                automated source_doc attribution
    attention_check             decoys marked as evidence
    """
    key = sheet.get("_key", {})
    decoys = set(sheet.get("_decoy_ids", []))

    filled = {}
    for a in annotations:
        pid = (a.get("pair_id") or "").strip()
        rel = (a.get("relation") or "").strip().lower() or None
        if not pid or rel not in LABELS:
            continue
        filled[pid] = {"relation": rel,
                       "about": _norm_bool(a.get("about_claim_company"))}

    overall = {"n": 0, "correct": 0}
    post_fix = {"n": 0, "correct": 0}
    by_kind: Dict[str, Counter] = defaultdict(Counter)
    attribution = {"compared": 0, "agreed": 0}
    decoy_seen = decoy_failed = 0
    confusion: Counter = Counter()

    for pid, ann in filled.items():
        meta = key.get(pid)
        if meta is None:
            continue
        if meta.get("is_decoy") or pid in decoys:
            decoy_seen += 1
            if ann["relation"] != "irrelevant":
                decoy_failed += 1
            continue

        claimed = KIND_TO_RELATION.get(meta.get("system_kind"))
        if claimed is None:
            continue
        agree = (ann["relation"] == claimed)
        overall["n"] += 1
        overall["correct"] += int(agree)
        by_kind[meta["system_kind"]]["n"] += 1
        by_kind[meta["system_kind"]]["correct"] += int(agree)
        confusion[(claimed, ann["relation"])] += 1

        if ann["about"] is True:
            post_fix["n"] += 1
            post_fix["correct"] += int(agree)

        if ann["about"] is not None and meta.get("same_company_auto") is not None:
            attribution["compared"] += 1
            attribution["agreed"] += int(ann["about"] == meta["same_company_auto"])

    def _ratio(c, n):
        return (c / n) if n else None

    return {
        "annotated": len(filled),
        "sheet_items": len(sheet.get("items", [])),
        "precision": {
            "overall": {**overall, "value": _ratio(overall["correct"], overall["n"])},
            "same_company_only": {**post_fix,
                                  "value": _ratio(post_fix["correct"], post_fix["n"]),
                                  "note": "ước lượng precision SAU khi lọc theo "
                                          "doanh nghiệp; tính được từ chính phiên "
                                          "chấm này vì bản sửa chỉ loại bớt cặp"},
            "by_kind": {k: {**dict(v), "value": _ratio(v["correct"], v["n"])}
                        for k, v in by_kind.items()},
        },
        "attribution_validation": {
            **attribution,
            "value": _ratio(attribution["agreed"], attribution["compared"]),
            "note": "mức khớp giữa phán đoán của người chấm và heuristic source_doc "
                    "của negative_control (NC.1)",
        },
        "attention_check": {
            "decoys_in_sheet": len(decoys),
            "decoys_annotated": decoy_seen,
            "decoys_failed": decoy_failed,
            "pass_rate": _ratio(decoy_seen - decoy_failed, decoy_seen),
        },
        "confusion": {f"{a}->{b}": n for (a, b), n in sorted(confusion.items())},
    }
