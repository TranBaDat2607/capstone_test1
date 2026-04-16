"""
generators/build_instances.py

Generates ontology/sample_instances.json by:
  1. Building the KG skeleton (Regulation, Indicator, Company, Report nodes)
     from ontology/framework_indicators.json
  2. Using Claude to extract Claim nodes from an extracted ESG report
     (output/extracted/.../extraction_result.json)

All entity data (regulations, companies, reports, indicators) is loaded from
framework_indicators.json — nothing is hardcoded in Python.

Usage
-----
    python generators/build_instances.py
    python generators/build_instances.py \\
        --indicators ontology/framework_indicators.json \\
        --report     output/extracted/2023-fpt-esg-report/extraction_result.json \\
        --out        ontology/sample_instances.json \\
        --model      claude-sonnet-4-20250514
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Fix Windows console encoding for Vietnamese characters
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from dotenv import load_dotenv

from kg_primitives import make_entity, make_relation, _now_iso
from report_blocks import prepare_blocks
from claude_extractor import build_prompt, call_claude

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INDICATORS = ROOT / "ontology" / "framework_indicators.json"
DEFAULT_REPORT     = (
    ROOT / "output" / "extracted" / "2023-fpt-esg-report" / "extraction_result.json"
)
DEFAULT_OUT   = ROOT / "ontology" / "sample_instances.json"
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Phase 1 — Build KG skeleton from catalog
# ---------------------------------------------------------------------------

def build_static_skeleton(catalog: dict) -> tuple[list[dict], list[dict]]:
    """Return (entities, relations) for Regulation, Indicator, Company, Report nodes.

    All data is read from the catalog (framework_indicators.json).
    """
    entities: list[dict] = []
    relations: list[dict] = []

    # --- Regulations ---
    for reg in catalog.get("regulations", []):
        reg_id = reg["regulation_id"]
        props = {k: v for k, v in reg.items() if k != "regulation_id"}
        entities.append(make_entity(reg_id, "Regulation", props))

    # Regulation amendment edges
    for amendment in catalog.get("regulation_amendments", []):
        relations.append(make_relation("amended_by", amendment["from"], amendment["to"]))

    # --- Companies ---
    for comp in catalog.get("companies", []):
        comp_id = comp["company_id"]
        complies_with = comp.get("complies_with", [])
        props = {k: v for k, v in comp.items() if k not in ("company_id", "complies_with")}
        entities.append(make_entity(comp_id, "Company", props))

        for reg_id in complies_with:
            relations.append(make_relation("complies_with", comp_id, reg_id))

    # --- Reports ---
    for rpt in catalog.get("reports", []):
        rpt_id = rpt["report_id"]
        comp_id = rpt.get("company_id", "")
        props = {k: v for k, v in rpt.items() if k != "report_id"}
        entities.append(make_entity(rpt_id, "Report", props))

        if comp_id:
            relations.append(make_relation("extracted_from", rpt_id, comp_id))

    # --- Indicators + requires edges ---
    for ind in catalog.get("indicators", []):
        node_id = ind["indicator_id"]
        props = {k: v for k, v in ind.items() if k != "indicator_id"}
        entities.append(make_entity(node_id, "Indicator", props))

        for reg_id in ind.get("mandatory_for", []):
            relations.append(make_relation(
                "requires", reg_id, node_id,
                extra={
                    "framework": ind.get("framework"),
                    "category": ind.get("category"),
                },
            ))

    # --- Cross-framework maps_to edges ---
    for mapping in catalog.get("cross_framework_maps", []):
        relations.append(make_relation(
            "maps_to", mapping["from"], mapping["to"],
            confidence=0.95,
            extra={"note": "cross-framework equivalence"},
        ))

    return entities, relations


# ---------------------------------------------------------------------------
# Phase 4 — Convert claims -> KG Claim nodes + relations
# ---------------------------------------------------------------------------

def claims_to_kg(
    claims: list[dict],
    indicator_map: dict[str, dict],
    report_id: str,
    company_id: str,
    model_name: str,
) -> tuple[list[dict], list[dict]]:
    """Convert raw claim dicts from Claude into KG entity + relation dicts."""
    entities:  list[dict] = []
    relations: list[dict] = []
    seq_counter: dict[str, int] = {}
    today = _now_iso()

    for claim in claims:
        ind_id = claim.get("indicator_id", "")
        if not ind_id:
            print("  WARNING: claim missing indicator_id — skipping")
            continue
        if ind_id not in indicator_map:
            print(f"  WARNING: unknown indicator_id '{ind_id}' — skipping")
            continue

        seq_counter[ind_id] = seq_counter.get(ind_id, 0) + 1
        node_id = f"CLM_{ind_id}_{seq_counter[ind_id]:03d}"
        ind     = indicator_map[ind_id]
        conf    = float(claim.get("confidence", 0.5))

        properties: dict = {
            "indicator_id":   ind_id,
            "claim_type":     claim.get("claim_type", "unknown"),
            "claim_text":     claim.get("claim_text", ""),
            "value":          claim.get("value"),
            "unit":           claim.get("unit") or ind.get("unit"),
            "confidence_score": conf,
            "source_block_id": claim.get("source_block_id", ""),
            "source_page":    claim.get("source_page"),
            "report_id":      report_id,
            "company_id":     company_id,
            "pillar":         ind.get("pillar", ""),
            "category":       ind.get("category", ""),
            "extracted_at":   today,
            "extraction_method": model_name,
        }

        entities.append(make_entity(node_id, "Claim", properties))

        # supports: Claim -> Indicator
        relations.append(make_relation(
            "supports", node_id, ind_id,
            confidence=conf,
            method=f"LLM:{model_name}",
        ))

        # extracted_from: Claim -> Report
        relations.append(make_relation(
            "extracted_from", node_id, report_id,
            confidence=1.0,
            method=f"LLM:{model_name}",
        ))

    return entities, relations


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(claim_entities: list[dict], indicator_map: dict[str, dict]) -> None:
    pillar_counts: dict[str, int] = {}
    type_counts:   dict[str, int] = {}

    for ent in claim_entities:
        props  = ent["properties"]
        pillar = props.get("pillar", "?")
        ctype  = props.get("claim_type", "?")
        pillar_counts[pillar] = pillar_counts.get(pillar, 0) + 1
        type_counts[ctype]    = type_counts.get(ctype, 0) + 1

    print(f"  Claims by pillar : {dict(sorted(pillar_counts.items()))}")
    print(f"  Claims by type   : {dict(sorted(type_counts.items()))}")

    # Mandatory indicators with no matching claim
    claimed = {e["properties"]["indicator_id"] for e in claim_entities}
    missing = [
        iid for iid, ind in indicator_map.items()
        if ind.get("mandatory_for") and iid not in claimed
    ]
    if missing:
        print(f"\n  Mandatory indicators with NO claim extracted ({len(missing)}):")
        for iid in missing[:10]:
            ind = indicator_map[iid]
            print(f"    - {iid}  [{ind.get('code')}]  {ind.get('title', '')[:55]}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build sample_instances.json using Claude for Claim extraction."
    )
    p.add_argument(
        "--indicators", type=Path, default=DEFAULT_INDICATORS,
        help="Path to framework_indicators.json",
    )
    p.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT,
        help="Path to extraction_result.json",
    )
    p.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help="Output path for sample_instances.json",
    )
    p.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help="Anthropic model name (default: claude-sonnet-4-20250514)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set. Add it to your .env file.")
    if not args.indicators.exists():
        sys.exit(f"ERROR: indicators file not found: {args.indicators}")
    if not args.report.exists():
        sys.exit(f"ERROR: report file not found: {args.report}")

    # ------------------------------------------------------------------
    # Load inputs
    # ------------------------------------------------------------------
    print(f"Loading indicators  : {args.indicators}")
    with args.indicators.open(encoding="utf-8") as f:
        catalog = json.load(f)
    indicators    = catalog["indicators"]
    indicator_map = {ind["indicator_id"]: ind for ind in indicators}
    print(f"  {len(indicators)} indicators")
    print(f"  {len(catalog.get('regulations', []))} regulations")
    print(f"  {len(catalog.get('companies', []))} companies")
    print(f"  {len(catalog.get('reports', []))} reports")

    # Resolve report_id and company_id from catalog
    reports = catalog.get("reports", [])
    if not reports:
        sys.exit("ERROR: no reports defined in indicators file")
    report_id  = reports[0]["report_id"]
    company_id = reports[0].get("company_id", "")

    print(f"\nLoading report      : {args.report}")
    with args.report.open(encoding="utf-8") as f:
        report = json.load(f)
    print(f"  {len(report.get('blocks', []))} blocks total")

    # ------------------------------------------------------------------
    # Phase 1 — KG skeleton
    # ------------------------------------------------------------------
    print("\n=== Phase 1: KG skeleton ===")
    entities, relations = build_static_skeleton(catalog)
    print(f"  Entities  : {len(entities)}")
    print(f"  Relations : {len(relations)}")

    # ------------------------------------------------------------------
    # Phase 2 — Prepare blocks
    # ------------------------------------------------------------------
    print("\n=== Phase 2: Preparing report blocks ===")
    blocks = prepare_blocks(report)
    print(f"  Blocks for LLM : {len(blocks)}  (text + table; images skipped)")

    # ------------------------------------------------------------------
    # Phase 3 — Claude extraction
    # ------------------------------------------------------------------
    print(f"\n=== Phase 3: Claude extraction ({args.model}) ===")
    prompt = build_prompt(indicators, blocks)
    claims = call_claude(prompt, args.model, api_key)
    print(f"  Claims returned : {len(claims)}")

    # ------------------------------------------------------------------
    # Phase 4 — Convert to KG nodes
    # ------------------------------------------------------------------
    print("\n=== Phase 4: Converting claims to KG nodes ===")
    claim_entities, claim_relations = claims_to_kg(
        claims, indicator_map, report_id, company_id, args.model,
    )
    print(f"  Claim nodes     : {len(claim_entities)}")
    print(f"  Claim relations : {len(claim_relations)}")
    print_summary(claim_entities, indicator_map)

    # ------------------------------------------------------------------
    # Phase 5 — Write output
    # ------------------------------------------------------------------
    all_entities  = entities  + claim_entities
    all_relations = relations + claim_relations

    output = {
        "_meta": {
            "generated":       _now_iso(),
            "description": (
                "KG instances for the ESG Greenwashing Detection pipeline. "
                f"Static nodes (Regulation, Indicator, Company, Report) built from "
                f"{args.indicators.name}. "
                f"Claim nodes extracted by {args.model} from {args.report.name}."
            ),
            "source":          "generators/build_instances.py",
            "llm_model":       args.model,
            "report_file":     str(args.report),
            "total_entities":  len(all_entities),
            "total_relations": len(all_relations),
            "claim_count":     len(claim_entities),
        },
        "entities":  all_entities,
        "relations": all_relations,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== Done ===")
    print(f"  Total entities  : {len(all_entities)}")
    print(f"  Total relations : {len(all_relations)}")
    print(f"  Wrote → {args.out}")


if __name__ == "__main__":
    main()
