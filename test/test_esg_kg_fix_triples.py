#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice: `src/step03_fix_invalid_triplets.py`
-> `esg_kg.graph.fix_triples`.

WHY THIS IS A SEPARATE FILE
Same contract and same reason as `test_esg_kg_anchor_kpi.py` and
`test_esg_kg_provenance.py`: import BOTH trees, run them on the same real input,
assert equal. `test_esg_kg_equivalence.py` covers the kernel and is past 1,100 lines;
a whole stage gets its own file.

WHY THIS SLICE NEEDS NO NEW core/ MODULE
step03 looks like a hub — seven src/ stages import from it — but every symbol they
take (`ISO_DATE_RE`, `normalize_date_string`, `date_start_key` -> `core/dates.py`;
`load_schema_sets`, `validate_triple` -> `core/schema.py`) was already lifted by the
earlier slices. Nobody imports its stage-local functions. What step03 itself imports
is `REPO_ROOT` (-> `core/paths`) and `RateLimiter` (-> `core/llm`), both present since
2026-07-27. So the hub-ness is already dissolved and this is a clean stage move, the
second after step05b to touch no kernel module.

HOW THE ALREADY-PATCHED-ARTIFACT LAW (PIPELINE.md §3) APPLIES HERE
Ask the one question that law turns on: when the stage meets its own past output, does
it `continue` or recompute? step03's MAIN PATH never meets its own output at all — it
reads `graph_output/graphs/` (step02's output) and writes a fresh
`all_validated_triples.json`. So the real-corpus arm is non-vacuous BY CONSTRUCTION;
no `strip_*` helper is needed, unlike step05c/step03b.

The exception is `--renormalize`, which DOES read the aggregated file this stage wrote
and re-applies phase 1.5 to it. That path gets its own arm, including idempotency
(phase 1.5 on already-ISO dates must be a no-op).

WHAT COSTS MONEY AND HOW IT IS STILL COVERED
Only phase 2 calls an LLM. It is exercised in BOTH trees with a stubbed
`fix_batch_with_llm`, so the paid branch — including the `preserve_property_values`
guard added in 046e572 — is compared without spending anything. `BATCH_FIX_PROMPT` is
pinned byte-for-byte for the same reason `test_esg_kg_llm.py` pins the request shape:
a silently reworded paid prompt still "works" while changing every repair.

Offline: no LLM, no Neo4j, no network. `config/schema.json` is tracked in git so the
pure arms always run; arms needing `graph_output/` (git-ignored, shipped via the HF
snapshot) SKIP with a message on a bare clone.

Run from the repo root:

    python test/test_esg_kg_fix_triples.py
"""

import copy
import json
import logging
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script -------------------------------------------------
import step03_fix_invalid_triplets as old_step03  # noqa: E402

# --- new: the esg_kg package ---------------------------------------------------
from esg_kg.graph import fix_triples as new_fix  # noqa: E402

# --- the kernel the new tree must be REUSING, not re-copying -------------------
from esg_kg.core import dates as core_dates  # noqa: E402
from esg_kg.core import schema as core_schema  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
GRAPHS_DIR = REPO / "graph_output" / "graphs"
VALIDATED_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"

_skips: list = []
_cache: dict = {}

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"
VN_FACILITY = "Nhà máy sản xuất số 1"


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def load_schema() -> dict:
    if "schema" not in _cache:
        _cache["schema"] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _cache["schema"]


def schema_sets():
    if "sets" not in _cache:
        _cache["sets"] = old_step03.load_schema_sets(load_schema())
    return _cache["sets"]


def real_page_files(limit: int = 0):
    """Real step02 page files, or [] when the HF snapshot is not pulled."""
    if not GRAPHS_DIR.is_dir():
        return []
    files = sorted(GRAPHS_DIR.rglob("page*.json"))
    return files[:limit] if limit else files


def _quiet():
    """Silence the stage's per-file INFO chatter; the arms compare artifacts, not logs."""
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.ERROR)
    return prev


def _unquiet(prev) -> None:
    logging.getLogger().setLevel(prev)


def _triple(subj_props=None, obj_props=None, predicate="ownsFacility"):
    """A schema-legal Organization --ownsFacility--> Facility triple."""
    return {
        "subject": {
            "class": "Organization",
            "properties": {
                "name": VN_NAME, "valid_from": "2024", "valid_to": None,
                "is_current": True, **(subj_props or {}),
            },
        },
        "predicate": predicate,
        "object": {
            "class": "Facility",
            "properties": {
                "name": VN_FACILITY, "valid_from": "2024", "valid_to": None,
                "is_current": True, **(obj_props or {}),
            },
        },
        "temporal_metadata": {
            "valid_from": "2024", "valid_to": None, "recorded_at": "2024"},
    }


# --------------------------------------------------------------------------- #
# 1. Module surface — these run on a bare clone.
# --------------------------------------------------------------------------- #
def test_fix_triples_module_constants_match_src():
    assert new_fix.DEFAULT_INPUT_DIR == old_step03.DEFAULT_INPUT_DIR
    assert new_fix.DEFAULT_SCHEMA == old_step03.DEFAULT_SCHEMA
    assert new_fix.DEFAULT_OUT_DIR == old_step03.DEFAULT_OUT_DIR
    assert new_fix.DEFAULT_MODEL == old_step03.DEFAULT_MODEL
    assert new_fix.DEFAULT_BATCH_SIZE == old_step03.DEFAULT_BATCH_SIZE
    assert new_fix.DEFAULT_RATE_LIMIT == old_step03.DEFAULT_RATE_LIMIT
    assert new_fix.NEWS_DATE_UNCERTAIN_CLASSES == old_step03.NEWS_DATE_UNCERTAIN_CLASSES
    assert new_fix._NODE_DATE_PROPS == old_step03._NODE_DATE_PROPS
    assert new_fix._EDGE_DATE_PROPS == old_step03._EDGE_DATE_PROPS
    assert new_fix.MUTABLE_NODE_PROPS == old_step03.MUTABLE_NODE_PROPS
    # the paths must be the REAL ones, not something the new tree invented
    assert new_fix.DEFAULT_INPUT_DIR == GRAPHS_DIR
    assert new_fix.DEFAULT_SCHEMA == SCHEMA_FILE


def test_fix_triples_keeps_its_own_rate_limit_constant():
    """`DEFAULT_RATE_LIMIT` must be this module's own value, not imported from
    core/llm. Both are 10 today, so importing would look correct — and would then
    silently retune step03 the day someone changes step02's limit."""
    from esg_kg.core import llm as core_llm
    src_txt = Path(new_fix.__file__).read_text(encoding="utf-8")

    assert any(ln.startswith("DEFAULT_RATE_LIMIT") for ln in src_txt.splitlines()), (
        "the module must define its own DEFAULT_RATE_LIMIT, not inherit one")
    llm_imports = [ln for ln in src_txt.splitlines()
                   if ln.startswith("from esg_kg.core.llm import")]
    assert llm_imports, "the new module must take RateLimiter from core/llm"
    for ln in llm_imports:
        assert "DEFAULT_RATE_LIMIT" not in ln, (
            f"DEFAULT_RATE_LIMIT must not be imported from core/llm: {ln!r} — "
            "that couples step03's rate limit to step02's")
    # They agree today; the point is that they are free to diverge.
    assert new_fix.DEFAULT_RATE_LIMIT == core_llm.DEFAULT_RATE_LIMIT == 10


def test_batch_fix_prompt_is_byte_identical():
    """The PAID prompt. A reworded prompt still 'works' while changing every repair,
    and phase 2 cannot be verified by re-running it (CLAUDE.md)."""
    assert new_fix.BATCH_FIX_PROMPT == old_step03.BATCH_FIX_PROMPT, (
        "BATCH_FIX_PROMPT diverged between the trees")
    # the issue-#6 guard clause must still be in it (belt and braces on the code guard)
    assert "NEVER touch property values" in new_fix.BATCH_FIX_PROMPT
    assert "Do NOT translate" in new_fix.BATCH_FIX_PROMPT


def test_new_tree_reuses_the_kernel_instead_of_copying_it():
    """The whole point of the slice: the date/schema helpers are DELETED here and
    imported from core/, not duplicated. Identity check, not equality."""
    assert new_fix.validate_triple is core_schema.validate_triple
    assert new_fix.load_schema_sets is core_schema.load_schema_sets
    assert new_fix.normalize_date_string is core_dates.normalize_date_string
    assert new_fix.date_start_key is core_dates.date_start_key
    src_txt = Path(new_fix.__file__).read_text(encoding="utf-8")
    for dup in ("def validate_triple", "def load_schema_sets",
                "def normalize_date_string", "def date_start_key"):
        assert dup not in src_txt, f"{dup} was copied into the new tree instead of imported"


# --------------------------------------------------------------------------- #
# 2. Pure functions, both trees — bare-clone safe.
# --------------------------------------------------------------------------- #
DIRECTION_CASES = [
    # (subject class, predicate, object class) — reversed, correct, unknown predicate
    ("Facility", "ownsFacility", "Organization"),
    ("Organization", "ownsFacility", "Facility"),
    ("Organization", "notARealPredicate", "Facility"),
    ("Organization", "ownsFacility", "NotARealClass"),
]


def test_fix_direction_matches_src():
    _, _, edge_directions = schema_sets()
    for s_cls, pred, o_cls in DIRECTION_CASES:
        t = _triple(predicate=pred)
        t["subject"]["class"] = s_cls
        t["object"]["class"] = o_cls
        got_new, sw_new = new_fix.fix_direction(copy.deepcopy(t), edge_directions)
        got_old, sw_old = old_step03.fix_direction(copy.deepcopy(t), edge_directions)
        assert sw_new == sw_old, f"swap flag diverged for {(s_cls, pred, o_cls)}"
        assert got_new == got_old, f"triple diverged for {(s_cls, pred, o_cls)}"
    # and the fixture is not vacuous: at least one case really swaps
    t = _triple()
    t["subject"]["class"], t["object"]["class"] = "Facility", "Organization"
    _, swapped = new_fix.fix_direction(t, edge_directions)
    assert swapped, "DIRECTION_CASES no longer contains a reversed triple"


JSON_RESPONSE_CASES = [
    '[{"a": 1}]',
    '```json\n[{"a": 1}]\n```',
    '[{"a": 1},]',                       # trailing comma
    '// a comment\n[{"a": 1}]',
    '/* block */ [{"a": 1}]',
    'prose before [{"a": 1}] prose after',
    'not json at all',
    '',
    '[',
]


def test_extract_json_from_response_matches_src():
    for raw in JSON_RESPONSE_CASES:
        assert new_fix.extract_json_from_response(raw) == \
            old_step03.extract_json_from_response(raw), f"diverged on {raw!r}"


def test_preserve_property_values_matches_src():
    """The 046e572 guard must survive the port unchanged."""
    cases = []
    # translated name
    o = _triple(); r = copy.deepcopy(o); r["subject"]["properties"]["name"] = EN_NAME
    cases.append((o, r))
    # invented key
    o = _triple(); r = copy.deepcopy(o); r["subject"]["properties"]["revenue"] = 1
    cases.append((o, r))
    # dropped key
    o = _triple(subj_props={"source_id": "aaa_2024_p12_s3"})
    r = copy.deepcopy(o); del r["subject"]["properties"]["source_id"]
    cases.append((o, r))
    # rounded value + tidied unit
    o = _triple(obj_props={"value": 1234.5, "unit": "tấn CO2e"})
    r = copy.deepcopy(o)
    r["object"]["properties"]["value"] = 1235
    r["object"]["properties"]["unit"] = "tCO2e"
    cases.append((o, r))
    # honest repair
    o = _triple(predicate="ownsFacilty"); r = copy.deepcopy(o); r["predicate"] = "ownsFacility"
    cases.append((o, r))
    # malformed originals
    for bad in (None, "not a dict", {"subject": None}):
        cases.append((bad, _triple()))

    total_blocked = 0
    for original, repaired in cases:
        g_new, b_new = new_fix.preserve_property_values(original, copy.deepcopy(repaired))
        g_old, b_old = old_step03.preserve_property_values(original, copy.deepcopy(repaired))
        assert b_new == b_old, f"blocked count diverged: {b_new} vs {b_old}"
        assert g_new == g_old, "guarded triple diverged"
        total_blocked += b_new
    assert total_blocked >= 5, (
        f"fixture stopped exercising the guard (only {total_blocked} blocked)")


def test_enforce_temporal_invariants_matches_src():
    """Phase 1.5 on hand-built triples that hit every counter."""
    triples = [
        # a date spelling that must be canonicalized
        _triple(subj_props={"valid_from": "31/12/2024"}),
        # valid_from > valid_to
        _triple(subj_props={"valid_from": "2024", "valid_to": "2020"}),
        # unparseable date, left alone
        _triple(subj_props={"valid_from": "ngày 31 tháng 12 năm 2024"}),
    ]
    # a news T2 node missing date_uncertain
    news = _triple()
    news["object"]["class"] = "Controversy"
    news["object"]["properties"]["source_type"] = "news"
    news["predicate"] = "hasControversy"
    triples.append(news)

    t_new, t_old = copy.deepcopy(triples), copy.deepcopy(triples)
    s_new = new_fix.enforce_temporal_invariants(t_new)
    s_old = old_step03.enforce_temporal_invariants(t_old)

    assert s_new == s_old, f"stats diverged:\n  new={s_new}\n  old={s_old}"
    assert t_new == t_old, "triples diverged"
    # the fixture really fires every counter — otherwise this compares four zeros
    for k, v in s_new.items():
        assert v > 0, f"counter {k} never fired; fixture is vacuous: {s_new}"


# --------------------------------------------------------------------------- #
# 3. Real corpus — the strong arms. SKIP on a bare clone.
# --------------------------------------------------------------------------- #
def test_load_triples_from_file_matches_src_on_real_pages():
    files = real_page_files(limit=200)
    if not files:
        return _skip("load_triples_from_file", "graph_output/graphs/ not present")
    formats = set()
    total = 0
    for fp in files:
        t_new, f_new = new_fix.load_triples_from_file(fp)
        t_old, f_old = old_step03.load_triples_from_file(fp)
        assert f_new == f_old, f"format diverged on {fp.name}"
        assert t_new == t_old, f"triples diverged on {fp.name}"
        formats.add(f_new)
        total += len(t_new)
    assert total > 0, "read 200 real page files and got no triples — arm is vacuous"
    print(f"     ({total} triples over {len(files)} files, formats={sorted(formats)})")


def test_process_file_offline_matches_src_on_real_pages():
    files = real_page_files(limit=200)
    if not files:
        return _skip("process_file_offline", "graph_output/graphs/ not present")
    entity_classes, edge_labels, edge_directions = schema_sets()
    agg = {"valid": 0, "invalid": 0, "direction_fixed": 0}
    for fp in files:
        v_new, i_new, s_new, fmt_new = new_fix.process_file_offline(
            fp, entity_classes, edge_labels, edge_directions)
        v_old, i_old, s_old, fmt_old = old_step03.process_file_offline(
            fp, entity_classes, edge_labels, edge_directions)
        assert s_new == s_old, f"stats diverged on {fp.name}: {s_new} vs {s_old}"
        assert v_new == v_old, f"valid triples diverged on {fp.name}"
        assert i_new == i_old, f"invalid triples diverged on {fp.name}"
        assert fmt_new == fmt_old, f"format diverged on {fp.name}"
        for k in agg:
            agg[k] += s_new[k]
    assert agg["valid"] > 0 and agg["invalid"] > 0, (
        f"arm needs both outcomes to be meaningful, got {agg}")
    print(f"     ({agg})")


def _run_stage(mod, input_dir: Path, out_dir: Path) -> dict:
    """Full phases 1 + 1.5 + 3 with NO LLM (client=None), writing to out_dir.

    dry_run stays False on purpose: dry_run writes nothing, and an artifact is the
    only thing worth comparing. client=None makes phase 2 log-and-skip, so this is
    offline and free.
    """
    schema = load_schema()
    entity_classes, edge_labels, edge_directions = schema_sets()
    mod.process_all_files(
        input_dir=input_dir, out_dir=out_dir, schema=schema,
        entity_classes=entity_classes, edge_labels=edge_labels,
        edge_directions=edge_directions, client=None, rate_limiter=None,
        model="stub", batch_size=25, dry_run=False,
    )
    out = {}
    for name in ("all_validated_triples.json", "unfixable_triples.json"):
        fp = out_dir / name
        out[name] = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
    return out


def test_process_all_files_matches_src_on_the_real_corpus():
    """The headline arm: 43 real doc dirs through both trees, artifacts compared."""
    if not real_page_files(limit=1):
        return _skip("process_all_files", "graph_output/graphs/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            got_new = _run_stage(new_fix, GRAPHS_DIR, tmp / "new")
            got_old = _run_stage(old_step03, GRAPHS_DIR, tmp / "old")
    finally:
        _unquiet(prev)

    valid_new = got_new["all_validated_triples.json"]
    valid_old = got_old["all_validated_triples.json"]
    assert valid_new is not None, "the new tree wrote no all_validated_triples.json"
    assert len(valid_new) == len(valid_old), (
        f"validated count diverged: new={len(valid_new)} old={len(valid_old)}")
    assert valid_new == valid_old, "validated triples diverged"

    uf_new = got_new["unfixable_triples.json"] or []
    uf_old = got_old["unfixable_triples.json"] or []
    assert uf_new == uf_old, f"unfixable diverged: {len(uf_new)} vs {len(uf_old)}"

    assert len(valid_new) > 1000, (
        f"only {len(valid_new)} triples — the real corpus was not actually read")
    print(f"     ({len(valid_new)} validated, {len(uf_new)} unfixable — both trees equal)")


def test_renormalize_existing_matches_src_and_is_idempotent():
    """The ONE path that reads this stage's own output (PIPELINE.md §3)."""
    if not VALIDATED_FILE.exists():
        return _skip("renormalize_existing", "all_validated_triples.json not present")
    entity_classes, edge_labels, edge_directions = schema_sets()
    original = VALIDATED_FILE.read_text(encoding="utf-8")

    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            d_new, d_old = tmp / "new", tmp / "old"
            for d in (d_new, d_old):
                d.mkdir()
                (d / "all_validated_triples.json").write_text(original, encoding="utf-8")

            new_fix.renormalize_existing(d_new, entity_classes, edge_labels, edge_directions)
            old_step03.renormalize_existing(d_old, entity_classes, edge_labels, edge_directions)

            out_new = (d_new / "all_validated_triples.json").read_text(encoding="utf-8")
            out_old = (d_old / "all_validated_triples.json").read_text(encoding="utf-8")
            assert out_new == out_old, "renormalize diverged between the trees"

            # idempotency: the file on disk is already normalized, so a second pass
            # must be a no-op. If it is not, every re-run silently rewrites the graph.
            new_fix.renormalize_existing(d_new, entity_classes, edge_labels, edge_directions)
            out_twice = (d_new / "all_validated_triples.json").read_text(encoding="utf-8")
            assert out_twice == out_new, "renormalize_existing is not idempotent"
    finally:
        _unquiet(prev)
    print("     (both trees equal, and a second pass changes nothing)")


# --------------------------------------------------------------------------- #
# 4. Phase 2 — the paid branch, driven with a stub in BOTH trees.
# --------------------------------------------------------------------------- #
def _tampering_llm(batch, schema, client, rate_limiter, model):
    """An 'honest repair' plus the silent tampering issue #6 warns about."""
    out = []
    for t in batch:
        r = copy.deepcopy(t)
        r["predicate"] = "ownsFacility"
        r["subject"]["properties"]["name"] = EN_NAME
        out.append(r)
    return out


def _phase2_page():
    return {
        "nodes": [
            {"class": "Organization", "properties": {
                "name": VN_NAME, "valid_from": "2024", "valid_to": None, "is_current": True}},
            {"class": "Facility", "properties": {
                "name": VN_FACILITY, "valid_from": "2024", "valid_to": None, "is_current": True}},
        ],
        # a typo phase 1 cannot fix -> the triple reaches phase 2
        "edges": [{"subject": 0, "object": 1, "predicate": "ownsFacilty",
                   "temporal_metadata": {"valid_from": "2024", "valid_to": None,
                                         "recorded_at": "2024"}}],
    }


def _run_phase2(mod, tmp: Path) -> list:
    schema = load_schema()
    entity_classes, edge_labels, edge_directions = schema_sets()
    doc = tmp / "graphs" / "aaa_2024"
    doc.mkdir(parents=True)
    (doc / "page1.json").write_text(json.dumps(_phase2_page(), ensure_ascii=False),
                                    encoding="utf-8")
    out_dir = tmp / "validated"
    real = mod.fix_batch_with_llm
    mod.fix_batch_with_llm = _tampering_llm
    try:
        mod.process_all_files(
            input_dir=tmp / "graphs", out_dir=out_dir, schema=schema,
            entity_classes=entity_classes, edge_labels=edge_labels,
            edge_directions=edge_directions, client=object(), rate_limiter=None,
            model="stub", batch_size=25, dry_run=False,
        )
    finally:
        mod.fix_batch_with_llm = real
    return json.loads((out_dir / "all_validated_triples.json").read_text(encoding="utf-8"))


def test_phase2_repair_path_matches_src_with_a_stubbed_llm():
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            got_new = _run_phase2(new_fix, Path(t1))
            got_old = _run_phase2(old_step03, Path(t2))
    finally:
        _unquiet(prev)

    assert got_new == got_old, f"phase 2 diverged:\n  new={got_new}\n  old={got_old}"
    assert len(got_new) == 1, f"expected the repaired triple to be kept, got {len(got_new)}"
    # the honest repair survived...
    assert got_new[0]["predicate"] == "ownsFacility", "the repair was lost"
    # ...and the guard is wired into the MIGRATED tree too, not just src/
    assert got_new[0]["subject"]["properties"]["name"] == VN_NAME, (
        "the migrated stage wrote the LLM's translated name — "
        "preserve_property_values is not wired into process_all_files")
    print("     (repair kept, tampering blocked, both trees equal)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}\n     {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")
    raise SystemExit(1 if failed else 0)
