#!/usr/bin/env python3
"""Phase 2's LLM may repair the SHAPE of a triple, never the VALUES in it.

Why this file exists. ``BATCH_FIX_PROMPT`` (step03) is written in English and
tells the model to "Fix typos/synonyms" without saying which fields it is
allowed to touch. Today that is survivable because roughly half the extracted
names are already English. It stops being survivable the moment step02 is
changed to emit Vietnamese ``name``/``title`` (GitHub issue #6): an
English-instructed model handed ``CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN
PHÁT`` is very likely to "correct" it — translate it, strip the diacritics, or
tidy the casing — and phase 2 accepts whatever comes back as long as
``validate_triple`` passes. Nothing compares the repair against its original.

Why that is silent and expensive. ``normalize_name`` collapses every Vietnamese
spelling of a name onto one key but sends the English translation to a different
one, so a translated name does not raise an error — it splits one entity into
two in step05 Stage A, which surfaces much later as duplicate nodes nobody can
trace back to a repair that happened here.

The rule under test: phase 2 may change ``class``, ``predicate`` and the
temporal fields the prompt actually asks for (``valid_from``/``valid_to``/
``is_current``, and ``temporal_metadata`` on the edge). Every other property
value is copied verbatim from the original — not translated, not reformatted,
not invented, not dropped.

A prompt edit alone cannot be tested offline, and CLAUDE.md forbids verifying by
re-running a paid stage. So the rule is enforced in code by
``preserve_property_values`` and pinned here; the prompt wording is belt and
braces on top of it.

Two things are asserted, because either alone would be a false green:

  1. **behaviour** — the guard restores, drops and permits exactly the right
     fields;
  2. **wiring** — a guard nothing calls is as broken as no guard. The last arm
     drives the real ``process_all_files`` with a stubbed LLM that tampers with
     a value, and reads the written artifact back.

Offline, no LLM/Neo4j/network. Run from the repo root:

    python test/test_step03_llm_value_guard.py
"""
import copy
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.graph import fix_triples as step03  # noqa: E402
from esg_kg.graph.fix_triples import (  # noqa: E402
    preserve_property_values,
    process_all_files,
)
from esg_kg.core.schema import load_schema_sets  # noqa: E402

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"
VN_FACILITY = "Nhà máy sản xuất số 1"


def _triple(subj_props=None, obj_props=None, predicate="ownsFacility"):
    """A schema-legal Organization --ownsFacility--> Facility triple."""
    return {
        "subject": {
            "class": "Organization",
            "properties": {
                "name": VN_NAME,
                "valid_from": "2024",
                "valid_to": None,
                "is_current": True,
                **(subj_props or {}),
            },
        },
        "predicate": predicate,
        "object": {
            "class": "Facility",
            "properties": {
                "name": VN_FACILITY,
                "valid_from": "2024",
                "valid_to": None,
                "is_current": True,
                **(obj_props or {}),
            },
        },
        "temporal_metadata": {
            "valid_from": "2024",
            "valid_to": None,
            "recorded_at": "2024",
        },
    }


# --------------------------------------------------------------------------- #
# 1. Behaviour
# --------------------------------------------------------------------------- #
def test_translated_vietnamese_name_is_restored():
    """The issue-#6 case: the model returns an English translation."""
    original = _triple()
    repaired = copy.deepcopy(original)
    repaired["subject"]["properties"]["name"] = EN_NAME

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["subject"]["properties"]["name"] == VN_NAME, (
        "phase 2 translated a Vietnamese name and the guard let it through: "
        f"{guarded['subject']['properties']['name']!r}")
    assert blocked == 1, f"expected 1 blocked override, got {blocked}"


def test_diacritics_stripped_is_also_restored():
    """Subtler than translation and far easier to miss on review."""
    original = _triple()
    repaired = copy.deepcopy(original)
    repaired["subject"]["properties"]["name"] = "CONG TY CO PHAN NHUA VA MOI TRUONG XANH AN PHAT"

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["subject"]["properties"]["name"] == VN_NAME
    assert blocked == 1


def test_class_and_predicate_may_be_repaired():
    """Fixing schema terms is the entire point of phase 2 — it must survive."""
    original = _triple(predicate="ownsFacilty")
    original["subject"]["class"] = "Organisation"
    repaired = copy.deepcopy(original)
    repaired["predicate"] = "ownsFacility"
    repaired["subject"]["class"] = "Organization"

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["predicate"] == "ownsFacility", "the guard must not undo a predicate repair"
    assert guarded["subject"]["class"] == "Organization", "the guard must not undo a class repair"
    assert blocked == 0, "repairing class/predicate is not a blocked override"


def test_missing_temporal_props_may_be_added():
    """Rule 2 of the prompt: add valid_from/valid_to/is_current."""
    original = _triple()
    del original["subject"]["properties"]["valid_from"]
    del original["subject"]["properties"]["is_current"]
    repaired = copy.deepcopy(original)
    repaired["subject"]["properties"]["valid_from"] = "2023"
    repaired["subject"]["properties"]["is_current"] = True

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["subject"]["properties"]["valid_from"] == "2023"
    assert guarded["subject"]["properties"]["is_current"] is True
    assert blocked == 0, "adding the temporal props the prompt asks for is allowed"


def test_temporal_metadata_may_be_created():
    original = _triple()
    del original["temporal_metadata"]
    repaired = copy.deepcopy(original)
    repaired["temporal_metadata"] = {
        "valid_from": "2024", "valid_to": None, "recorded_at": "2024"}

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["temporal_metadata"]["recorded_at"] == "2024"
    assert blocked == 0


def test_dropped_property_is_restored():
    """Losing a value is as bad as changing it — traceability lives in these keys."""
    original = _triple(subj_props={"source_id": "aaa_2024_p12_s3", "ticker": "AAA"})
    repaired = copy.deepcopy(original)
    del repaired["subject"]["properties"]["source_id"]

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["subject"]["properties"]["source_id"] == "aaa_2024_p12_s3", (
        "the guard must restore a property the model dropped")
    assert blocked == 1


def test_invented_property_is_dropped():
    """The prompt never authorises new facts; an invented key is hallucination."""
    original = _triple()
    repaired = copy.deepcopy(original)
    repaired["subject"]["properties"]["revenue"] = 1234567

    guarded, blocked = preserve_property_values(original, repaired)

    assert "revenue" not in guarded["subject"]["properties"], (
        "the guard must drop a property the model invented")
    assert blocked == 1


def test_numeric_value_and_unit_are_restored():
    """KPI values are the whole point of the graph; a 'tidied' unit is a wrong fact."""
    original = _triple(obj_props={"value": 1234.5, "unit": "tấn CO2e"})
    repaired = copy.deepcopy(original)
    repaired["object"]["properties"]["value"] = 1235
    repaired["object"]["properties"]["unit"] = "tCO2e"

    guarded, blocked = preserve_property_values(original, repaired)

    assert guarded["object"]["properties"]["value"] == 1234.5
    assert guarded["object"]["properties"]["unit"] == "tấn CO2e"
    assert blocked == 2


def test_faithful_repair_reports_nothing_blocked():
    """No false positives: an honest repair must not be counted as tampering."""
    original = _triple(predicate="ownsFacilty")
    repaired = copy.deepcopy(original)
    repaired["predicate"] = "ownsFacility"

    guarded, blocked = preserve_property_values(original, repaired)

    assert blocked == 0
    assert guarded["subject"]["properties"] == original["subject"]["properties"]
    assert guarded["object"]["properties"] == original["object"]["properties"]


def test_original_is_not_mutated():
    """The caller keeps using `original` afterwards (it tags it `_fixed`)."""
    original = _triple()
    snapshot = copy.deepcopy(original)
    repaired = copy.deepcopy(original)
    repaired["subject"]["properties"]["name"] = EN_NAME

    preserve_property_values(original, repaired)

    assert original == snapshot, "preserve_property_values must not mutate its input"


def test_malformed_original_does_not_crash():
    """Phase 2 exists to handle junk; the guard must not be the thing that dies."""
    for bad in (None, "not a dict", {"subject": None}, {"subject": {"class": "Organization"}}):
        repaired = _triple()
        guarded, blocked = preserve_property_values(bad, repaired)
        assert isinstance(guarded, dict), f"guard returned {type(guarded)} for {bad!r}"


# --------------------------------------------------------------------------- #
# 2. Wiring — a guard nothing calls is as broken as no guard.
# --------------------------------------------------------------------------- #
def test_process_all_files_applies_the_guard():
    """Drive the real phase-2 path with a stubbed LLM that tampers with a name."""
    schema = json.loads((REPO_ROOT / "config" / "schema.json").read_text(encoding="utf-8"))
    entity_classes, edge_labels, edge_directions = load_schema_sets(schema)

    page = {
        "nodes": [
            {"class": "Organization", "properties": {
                "name": VN_NAME, "valid_from": "2024", "valid_to": None, "is_current": True}},
            {"class": "Facility", "properties": {
                "name": VN_FACILITY, "valid_from": "2024", "valid_to": None, "is_current": True}},
        ],
        # `ownsFacilty` is a typo -> phase 1 cannot fix it -> it reaches phase 2.
        "edges": [{"subject": 0, "object": 1, "predicate": "ownsFacilty",
                   "temporal_metadata": {"valid_from": "2024", "valid_to": None,
                                         "recorded_at": "2024"}}],
    }

    def tampering_llm(batch, schema, client, rate_limiter, model, cached_content=None):
        out = []
        for t in batch:
            r = copy.deepcopy(t)
            r["predicate"] = "ownsFacility"                    # the honest repair
            r["subject"]["properties"]["name"] = EN_NAME       # the silent tampering
            out.append(r)
        return out

    real_llm = step03.fix_batch_with_llm
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        doc = tmp / "graphs" / "aaa_2024"
        doc.mkdir(parents=True)
        (doc / "page1.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        out_dir = tmp / "validated"
        step03.fix_batch_with_llm = tampering_llm
        try:
            process_all_files(
                input_dir=tmp / "graphs", out_dir=out_dir, schema=schema,
                entity_classes=entity_classes, edge_labels=edge_labels,
                edge_directions=edge_directions, client=object(),
                rate_limiter=None, model="stub", batch_size=25, dry_run=False,
            )
        finally:
            step03.fix_batch_with_llm = real_llm

        written = json.loads((out_dir / "all_validated_triples.json").read_text(encoding="utf-8"))

    assert len(written) == 1, f"expected the repaired triple to be kept, got {len(written)}"
    got = written[0]
    assert got["predicate"] == "ownsFacility", "the honest part of the repair was lost"
    assert got["subject"]["properties"]["name"] == VN_NAME, (
        "process_all_files wrote the LLM's translated name — the guard is not wired in: "
        f"{got['subject']['properties']['name']!r}")


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}\n     {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test is a failure too
            failed += 1
            print(f"ERROR {t.__name__}\n     {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} test(s) passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
