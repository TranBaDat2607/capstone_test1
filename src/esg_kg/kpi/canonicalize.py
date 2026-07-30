"""Step 3c — canonicalize KPI vocabulary + backfill Goal target dates (offline, NO LLM).

Design docs: docs/CROSSCHECK_EXPANSION.md §4.1/§4.2 and docs/STANDARD_INDICATOR_AXIS.md §5.2.

WHY THIS STAGE EXISTS
step01 already matches many KPIs against the 35 controlled definitions in
kpi_definitions_construction.json (484/4906 on AAA carry a `TT96-*` / `SSCIFC-*` code), but the
rest arrive as free text ("Tiêu hao điện năng cho sản xuất", "Male employees"). Those are the
same facts under a different name, and without a canonical code they cannot be joined to the
indicator axis that step05c builds. This stage assigns that code.

WHY IT ADDS `kpi_id` INSTEAD OF REWRITING `kpi_type`
It writes a NEW property `kpi_id` and NEVER rewrites `kpi_type`. The reason is provenance, not
convenience: `kpi_type` is the RAW wording the extractor read off the page, `kpi_id` is the
canonical code it maps to. Overwrite the raw value and a wrong mapping can never be traced back
to what the report actually said. That reason holds however often the corpus is re-extracted.

Secondary, and NO LONGER a constraint: `kpi_type` sits in KPIObservation.identity_keys
(config/schema.json), so rewriting it would re-cluster step05 and renumber the resolved node
array, which the step07 dossiers index positionally. That used to be the headline reason here.
It is not any more — a full re-extraction including AAA is a planned goal of the refactor, so
node-order churn is a scheduled cost rather than a veto (src/esg_kg/DESIGN.md §5.4).

PRECISION OVER RECALL
~85% of the unmapped tail is purely financial ("Lợi nhuận sau thuế", unit VND). Those are not
missing ESG mappings, they are correctly-excluded noise: `reject_units` in
config/kpi_type_aliases.json blocks them outright. Unmatched nodes keep `kpi_id = null` and are
listed in the stats file so the alias dictionary can be grown deliberately.

WHICH RULE DECIDED — `kpi_id_method`, stamped on every node
A null `kpi_id` is ambiguous on its own: `rejected_unit` means we deliberately refused a
financial KPI, `no_match` means the alias file has a hole. Only the second is a backlog
item, and on the AAA corpus they are 2913 vs 1368 — so without the stamp the real work is
buried in noise three times its size. The same property makes a wrong `measuredUnder` edge
traceable back to the tier that minted it (`alias_exact` is curated, `fuzzy_NN` is a guess).
Values: kpi_type | alias_exact | official_name | alias_contains | fuzzy_NN | rejected_unit |
unit_mismatch | no_title | no_match. Marking the method on the data is required by
src/esg_kg/DESIGN.md §5.1 — cf. step03b's `anchor_method`, step05b's `provenance_method`.

Also does (same pass, same file, both offline):
  * `unit_normalized` / `value_normalized` — canonical unit spelling, and value rescaled to a
    base unit when a conversion factor is known (nghìn m3 → m³, MWh → kWh).
  * `period` — an ISO-ish reporting period derived from year / target_year / valid_from.
  * Goal.target_date — Vietnamese/English regex over name+description, filled ONLY when empty
    and only when the extracted year is later than the goal's valid_from (a goal cannot target
    its own past). Goals still without a target_date are left alone: a slogan is not a promise.

Run from the repo root, after step03b (anchor_kpi) and before the registries/step05:
  python src/run.py canonicalize --dry-run
  python src/run.py canonicalize
Equivalently, from inside src/:  python -m esg_kg.kpi.canonicalize --dry-run

Moved verbatim from src/step03c_canonicalize_kpis.py (Model A: that file still exists
and still runs). Only the docstring and the import block differ — the logic below is
unchanged, and test/test_esg_kg_equivalence.py compares the two trees on the real
corpus to keep it that way.
"""

import argparse
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.paths import REPO_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TRIPLES = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_ALIASES = REPO_ROOT / "config" / "kpi_type_aliases.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "validated" / "kpi_canonical_stats.json"

# A code step01 already emitted — trusted as-is, never re-derived.
STANDARD_CODE_RE = re.compile(r"^(TT96-|QD2171|QCVN09|SSCIFC-)", re.IGNORECASE)

# rapidfuzz only ever runs against the 35 official indicator NAMES (never against the alias
# lists, which are meant to be exact), and only above a deliberately high cutoff.
DEFAULT_FUZZY_THRESHOLD = 92

GOAL_YEAR_PATTERNS = [
    re.compile(r"(?:đến|vào|trước|tới)\s*năm\s*(20\d{2})", re.IGNORECASE),
    re.compile(r"giai\s*đoạn\s*20\d{2}\s*[-–—]\s*(20\d{2})", re.IGNORECASE),
    re.compile(r"\bby\s*(20\d{2})", re.IGNORECASE),
]


# --------------------------------------------------------------------------- #
# Normalization.
# --------------------------------------------------------------------------- #
def normalize_title(s: Any) -> str:
    """Lowercase + collapse whitespace + drop edge punctuation. Diacritics are KEPT:
    'nước' and 'nuoc' are different words to a Vietnamese reader, and the alias file is
    written in real Vietnamese."""
    if not s:
        return ""
    t = unicodedata.normalize("NFC", str(s)).strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .:;,-–—()[]")


def normalize_unit(u: Any, unit_canonical: Dict[str, str]) -> str:
    if u in (None, ""):
        return ""
    raw = normalize_title(u)
    return unit_canonical.get(raw, str(u).strip())


def derive_period(props: Dict[str, Any]) -> Optional[str]:
    for key in ("year", "target_year"):
        v = props.get(key)
        if isinstance(v, int) and 1900 < v < 2200:
            return str(v)
        if isinstance(v, str) and re.fullmatch(r"(19|20)\d{2}", v.strip()):
            return v.strip()
    vf = props.get("valid_from")
    if isinstance(vf, str):
        m = re.match(r"((?:19|20)\d{2})", vf.strip())
        if m:
            return m.group(1)
    return None


def rescale_value(value: Any, raw_unit: str,
                  scales: Dict[str, Dict[str, Any]]) -> Tuple[Optional[float], Optional[str]]:
    """Return (value_in_base_unit, base_unit) when a conversion factor is known."""
    rule = scales.get(normalize_title(raw_unit))
    if not rule or not isinstance(value, (int, float)):
        return None, None
    try:
        return float(value) * float(rule["factor"]), str(rule["base"])
    except (TypeError, ValueError, KeyError):
        return None, None


# --------------------------------------------------------------------------- #
# Matching.
# --------------------------------------------------------------------------- #
class Matcher:
    """Tiered title→indicator matcher. Every hit reports WHICH tier fired, so a wrong
    mapping can always be traced back to the rule that produced it."""

    def __init__(self, defs: List[Dict[str, Any]], aliases: Dict[str, Any],
                 fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD):
        self.valid_ids = {d["id"] for d in defs}
        self.unit_canonical = {normalize_title(k): v
                               for k, v in (aliases.get("unit_canonical") or {}).items()}
        self.unit_scales = {normalize_title(k): v
                            for k, v in (aliases.get("unit_scale_to_base") or {}).items()}
        self.reject_units = {normalize_title(u) for u in (aliases.get("reject_units") or [])}
        self.fuzzy_threshold = fuzzy_threshold

        # Official indicator names — free recall, no curation needed.
        self.by_official_name = {normalize_title(d["name"]): d["id"] for d in defs}

        self.exact: Dict[str, str] = {}
        self.contains: List[Tuple[str, str]] = []
        self.units_of: Dict[str, set] = {}
        for rule in aliases.get("rules") or []:
            ind = rule.get("indicator_id")
            if ind not in self.valid_ids:
                logger.warning(f"Alias rule points at unknown indicator {ind!r} — skipped.")
                continue
            units = rule.get("units") or []
            self.units_of[ind] = {normalize_title(u) for u in units}
            for t in rule.get("exact") or []:
                self.exact[normalize_title(t)] = ind
            for t in rule.get("contains") or []:
                self.contains.append((normalize_title(t), ind))
        # Longest phrase first so the most specific `contains` rule wins.
        self.contains.sort(key=lambda kv: -len(kv[0]))

        self._fuzz = None
        try:
            from rapidfuzz import fuzz
            self._fuzz = fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed — fuzzy tier disabled "
                           "(exact + contains tiers still run).")

    def _unit_allows(self, indicator: str, unit_norm: str) -> bool:
        allowed = self.units_of.get(indicator)
        if not allowed:
            return True
        return normalize_title(unit_norm) in allowed

    def match(self, title: Any, unit_norm: str) -> Tuple[Optional[str], str]:
        """Return (indicator_id, method). method is a reason string when nothing matched."""
        t = normalize_title(title)
        if not t:
            return None, "no_title"
        if normalize_title(unit_norm) in self.reject_units:
            return None, "rejected_unit"

        if t in self.exact:
            ind = self.exact[t]
            return (ind, "alias_exact") if self._unit_allows(ind, unit_norm) else (None, "unit_mismatch")

        if t in self.by_official_name:
            return self.by_official_name[t], "official_name"

        for phrase, ind in self.contains:
            if phrase in t:
                return (ind, "alias_contains") if self._unit_allows(ind, unit_norm) else (None, "unit_mismatch")

        if self._fuzz is not None:
            best_id, best_score = None, 0
            for name, ind in self.by_official_name.items():
                score = self._fuzz.ratio(t, name)
                if score > best_score:
                    best_id, best_score = ind, score
            if best_id and best_score >= self.fuzzy_threshold:
                return best_id, f"fuzzy_{int(best_score)}"

        return None, "no_match"


# --------------------------------------------------------------------------- #
# Passes.
# --------------------------------------------------------------------------- #
def _entities(triples: List[Dict[str, Any]], cls: str):
    """Yield every (property-dict) occurrence of `cls`. The triple list is denormalized —
    one logical node appears in many triples — so every occurrence must be patched."""
    for t in triples:
        for side in ("subject", "object"):
            ent = t.get(side)
            if isinstance(ent, dict) and ent.get("class") == cls:
                props = ent.get("properties")
                if isinstance(props, dict):
                    yield props


def _node_key(props: Dict[str, Any]) -> str:
    """Identity of a KPI occurrence for counting DISTINCT nodes (mirrors step03b's approach
    of hashing the whole property dict)."""
    return json.dumps({k: props.get(k) for k in sorted(props)}, ensure_ascii=False, sort_keys=True)


def canonicalize_kpis(triples: List[Dict[str, Any]], matcher: Matcher) -> Dict[str, Any]:
    methods: Counter = Counter()
    unmapped: Counter = Counter()
    per_indicator: Counter = Counter()
    seen_nodes: Dict[str, Tuple[Optional[str], str]] = {}
    occurrences = 0

    for props in _entities(triples, "KPIObservation"):
        occurrences += 1
        key = _node_key(props)

        raw_unit = props.get("unit")
        unit_norm = normalize_unit(raw_unit, matcher.unit_canonical)

        kpi_type = props.get("kpi_type")
        if kpi_type and STANDARD_CODE_RE.match(str(kpi_type)):
            ind, method = str(kpi_type), "kpi_type"
        else:
            ind, method = matcher.match(props.get("title"), unit_norm)

        props["kpi_id"] = ind
        # WHICH rule decided, stamped on the node itself (DESIGN.md §5.1, as step03b does
        # with anchor_method and step05b with provenance_method). Two things need it:
        # a wrong measuredUnder edge must be traceable back to the tier that minted it,
        # and — more importantly — a null kpi_id is ambiguous without it. `rejected_unit`
        # (a financial KPI we deliberately refused) and `no_match` (a hole in the alias
        # file, i.e. real work) are indistinguishable on the node otherwise, and only the
        # second is a backlog item.
        props["kpi_id_method"] = method
        if unit_norm:
            props["unit_normalized"] = unit_norm
        base_val, base_unit = rescale_value(props.get("value"), raw_unit, matcher.unit_scales)
        if base_val is not None:
            props["value_normalized"] = base_val
            props["unit_normalized"] = base_unit
        period = derive_period(props)
        if period:
            props["period"] = period

        if key not in seen_nodes:                       # count each distinct node once
            seen_nodes[key] = (ind, method)
            methods[method] += 1
            if ind:
                per_indicator[ind] += 1
            else:
                title = normalize_title(props.get("title")) or "(no title)"
                unmapped[f"{title} | {unit_norm or '-'}"] += 1

    mapped = sum(1 for ind, _ in seen_nodes.values() if ind)
    return {
        "kpi_occurrences_patched": occurrences,
        "distinct_kpi_nodes": len(seen_nodes),
        "mapped": mapped,
        "unmapped": len(seen_nodes) - mapped,
        "mapped_pct": round(100.0 * mapped / len(seen_nodes), 1) if seen_nodes else 0.0,
        "by_method": dict(methods.most_common()),
        "by_indicator": dict(per_indicator.most_common()),
        "unmapped_titles": [{"title_unit": k, "count": v} for k, v in unmapped.most_common(60)],
    }


def _year_of(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = re.match(r"((?:19|20)\d{2})", value.strip())
        if m:
            return int(m.group(1))
    return None


def backfill_goal_target_date(triples: List[Dict[str, Any]]) -> Dict[str, Any]:
    filled: Counter = Counter()
    seen: Dict[str, bool] = {}
    already = no_match = rejected_past = 0

    for props in _entities(triples, "Goal"):
        key = _node_key(props)
        first_time = key not in seen
        if props.get("target_date") not in (None, ""):
            if first_time:
                seen[key] = True
                already += 1
            continue

        text = f"{props.get('name') or ''} {props.get('description') or ''}"
        year = None
        for pat in GOAL_YEAR_PATTERNS:
            m = pat.search(text)
            if m:
                year = int(m.group(1))
                break

        if year is None:
            if first_time:
                seen[key] = True
                no_match += 1
            continue

        vf = _year_of(props.get("valid_from"))
        if vf is not None and year <= vf:
            # A goal cannot target a year it already lives in — that is a date mention,
            # not a deadline (docs/CROSSCHECK_EXPANSION.md §5 risk control).
            if first_time:
                seen[key] = True
                rejected_past += 1
            continue

        props["target_date"] = str(year)
        props["target_date_method"] = "regex_backfill"
        if first_time:
            seen[key] = True
            filled[str(year)] += 1

    return {
        "distinct_goals": len(seen),
        "filled": sum(filled.values()),
        "already_had_target_date": already,
        "no_year_found": no_match,
        "rejected_not_in_future": rejected_past,
        "filled_by_year": dict(sorted(filled.items())),
    }


# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 3c — assign canonical kpi_id + normalize units/periods + backfill "
                    "Goal target_date (offline, no LLM).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_TRIPLES,
                   help="Validated triples JSON (patched in place).")
    p.add_argument("--defs", type=Path, default=DEFAULT_DEFS,
                   help="kpi_definitions_construction.json (the 35 controlled indicators).")
    p.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES,
                   help="config/kpi_type_aliases.json (curated free-text → indicator map).")
    p.add_argument("--fuzzy-threshold", type=int, default=DEFAULT_FUZZY_THRESHOLD,
                   help=f"rapidfuzz cutoff against official names (default {DEFAULT_FUZZY_THRESHOLD}).")
    p.add_argument("--no-goals", action="store_true", help="Skip the Goal.target_date backfill.")
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    args = p.parse_args()

    for path, hint in ((args.input, "run step03_fix_invalid_triplets.py first"),
                       (args.defs, "kpi_definitions_construction.json is missing"),
                       (args.aliases, "config/kpi_type_aliases.json is missing")):
        if not path.exists():
            logger.error(f"Input not found: {path} ({hint}).")
            return

    triples = json.loads(args.input.read_text(encoding="utf-8"))
    defs = json.loads(args.defs.read_text(encoding="utf-8"))
    aliases = json.loads(args.aliases.read_text(encoding="utf-8"))
    n_triples = len(triples)

    matcher = Matcher(defs, aliases, args.fuzzy_threshold)
    logger.info(f"Loaded {len(defs)} indicator definitions, {len(matcher.exact)} exact alias(es), "
                f"{len(matcher.contains)} contains-rule(s), "
                f"{len(aliases.get('needs_review') or [])} held back in needs_review.")

    kpi_stats = canonicalize_kpis(triples, matcher)
    goal_stats = {"skipped": True} if args.no_goals else backfill_goal_target_date(triples)

    assert len(triples) == n_triples, "step03c must never add or remove triples"

    logger.info(f"KPI: {kpi_stats['mapped']}/{kpi_stats['distinct_kpi_nodes']} distinct nodes "
                f"mapped ({kpi_stats['mapped_pct']}%) — by method: {kpi_stats['by_method']}")
    for row in kpi_stats["unmapped_titles"][:5]:
        logger.info(f"  unmapped ×{row['count']}: {row['title_unit']}")
    if not args.no_goals:
        logger.info(f"Goal target_date: filled {goal_stats['filled']} of "
                    f"{goal_stats['distinct_goals']} distinct goal(s) "
                    f"(already set {goal_stats['already_had_target_date']}, "
                    f"no year {goal_stats['no_year_found']}, "
                    f"rejected as not-future {goal_stats['rejected_not_in_future']})")

    stats = {"kpi": kpi_stats, "goal": goal_stats,
             "params": {"fuzzy_threshold": args.fuzzy_threshold,
                        "aliases_version": aliases.get("version"),
                        "dry_run": args.dry_run}}

    if args.dry_run:
        logger.info("--dry-run: nothing written.")
        return

    args.input.write_text(json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {args.input} and {args.stats_out}. "
                f"Next: python src/step04_build_issuer_registry.py (or straight to step05).")


if __name__ == "__main__":
    main()
