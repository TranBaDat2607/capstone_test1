#!/usr/bin/env python3
"""Behavioural tests for `esg_kg.crosscheck.readjudicate` — the targeted, budgeted
re-adjudication of legacy-prompt pairs under the CURRENT prompt.

WHAT IT IS FOR
`replay_adjudications` (stage 12) showed the adjudication caches hold two prompt
generations: unsalted keys written by the pre-2026-08-13 prompt, and salted keys written
by the prompt in the tree today. They disagree 43.8% of the time once either verdict is
non-`irrelevant` — i.e. exactly on the pairs a supports/contradicts classifier would
train on. This stage closes that gap by asking the CURRENT prompt about the legacy pairs
that have no current verdict yet, so the training set is single-generation.

WHY IT DELEGATES TO `Adjudicator` INSTEAD OF PROMPTING ITSELF
The whole point is that the new verdicts are indistinguishable from ones step07 would
have produced. Reimplementing the prompt/parse/cache-key path would defeat that on the
first divergence. So this stage constructs the real `Adjudicator` and calls
`.adjudicate()` — the prompt, the verdict parsing, and the salted cache key are step07's,
not this file's. `test_writes_under_the_current_salt` is the guard.

WHY WRITING INTO THE LIVE CACHE IS SAFE
The new entries are keyed with the current salt; the legacy entries are keyed without it.
Different keys, so the write is append-only in effect and no paid verdict is ever
destroyed. `test_existing_entries_survive` pins that, because the cost of getting it
wrong is 4,259 paid verdicts. The write also means a future step07 run gets these free.

Offline: no LLM, no Neo4j, no network — `_GeminiProvider` is stubbed before it can look
for a key, the same technique test_esg_kg_crosscheck.py uses.

Run from the repo root:

    python test/test_readjudicate_legacy.py
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core.llm_cache import ContentCache  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct as step07  # noqa: E402
from esg_kg.crosscheck import readjudicate  # noqa: E402

MODEL = "gemini-2.5-flash"


def make_stub(verdict: str = "irrelevant"):
    calls_seen: list = []

    class _Stub:
        name = "gemini"

        def __init__(self, model, rate_limit, api_key=None):
            self.model = model
            self.rate_limit = rate_limit
            self.enabled = True
            self.calls = 0
            self.failures = 0

        def call(self, system, user):
            calls_seen.append((system, user))
            return json.dumps({"verdict": verdict, "confidence": 0.9,
                               "rationale": "stub re-adjudication"})

    _Stub.calls_seen = calls_seen
    return _Stub


def row(ctext, etext, meta, gen, verdict, provider="openai"):
    """A replay_adjudications output row, trimmed to the fields this stage reads."""
    return {"claim_text": ctext, "evidence_text": etext, "evidence_meta": meta,
            "prompt_generation": gen, "verdict": verdict, "provider": provider,
            "claim_node_index": 1, "evidence_node_index": 2, "claim_id": "c-1",
            "evidence_class": "MediaReport", "evidence_domain": "vnexpress.net",
            "evidence_year": 2024, "cache_file": "adjudication_cache_openai.json"}


REPLAY_ROWS = [
    # targeted: legacy, non-irrelevant, no current verdict
    row("claim A", "evidence A", "MediaReport from a.vn, year 2024", "legacy", "supports"),
    row("claim B", "evidence B", "Controversy from b.vn, year 2023", "legacy", "contradicts"),
    # NOT targeted: legacy but irrelevant
    row("claim C", "evidence C", "MediaReport from c.vn, year 2024", "legacy", "irrelevant"),
    # NOT targeted: already has a current-prompt verdict
    row("claim D", "evidence D", "MediaReport from d.vn, year 2024", "legacy", "supports"),
    row("claim D", "evidence D", "MediaReport from d.vn, year 2024", "current", "irrelevant", "gemini"),
]


class Workspace:
    def __init__(self, rows=REPLAY_ROWS):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_readj_"))
        self.replay = self.dir / "adjudicated_pairs.jsonl"
        self.replay.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                               encoding="utf-8")
        self.cache_path = self.dir / "adjudication_cache.json"
        self.out = self.dir / "out" / "readjudicated.jsonl"
        self.stats_out = self.dir / "out" / "readjudicate_stats.json"

    def args(self, **overrides):
        args = argparse.Namespace(
            replay=self.replay, cache=self.cache_path, out=self.out,
            stats_out=self.stats_out, model=MODEL, rate_limit=60,
            provider_order=["gemini"], max_workers=2, limit=None, dry_run=False,
            checkpoint_every=25,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def cache_entries(self):
        if not self.cache_path.exists():
            return {}
        return json.loads(self.cache_path.read_text(encoding="utf-8")).get("entries", {})

    def rows(self):
        if not self.out.exists():
            return None
        return [json.loads(l) for l in self.out.read_text(encoding="utf-8").splitlines() if l.strip()]

    def stats(self):
        return json.loads(self.stats_out.read_text(encoding="utf-8")) if self.stats_out.exists() else None

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run_stubbed(ws, stub_verdict="irrelevant", **overrides):
    stub = make_stub(stub_verdict)
    original = step07._GeminiProvider
    try:
        step07._GeminiProvider = stub
        readjudicate.run(ws.args(**overrides))
    finally:
        step07._GeminiProvider = original
    return stub


# --------------------------------------------------------------------------- #
# 1. Target selection
# --------------------------------------------------------------------------- #
def test_targets_are_legacy_non_irrelevant_without_a_current_verdict():
    targets = readjudicate.select_targets(REPLAY_ROWS)
    texts = {t["claim_text"] for t in targets}
    assert texts == {"claim A", "claim B"}, (
        f"expected only the legacy non-irrelevant pairs lacking a current verdict: {texts}")
    for t in targets:
        assert t["evidence_meta"] and t["evidence_text"], t
        # legacy_verdicts is {provider: verdict} — the verdicts are the VALUES
        assert set(t["legacy_verdicts"].values()) <= {"supports", "contradicts", "irrelevant"}, t


def test_a_pair_whose_legacy_providers_disagree_is_still_targeted():
    """gemini and openai splitting on the same legacy pair is exactly the noise this
    stage is meant to resolve — it must not be skipped for being ambiguous."""
    rows = [row("claim X", "ev X", "MediaReport from x.vn, year 2024", "legacy", "supports", "gemini"),
            row("claim X", "ev X", "MediaReport from x.vn, year 2024", "legacy", "contradicts", "openai")]
    targets = readjudicate.select_targets(rows)
    assert len(targets) == 1, targets
    assert sorted(set(targets[0]["legacy_verdicts"].values())) == ["contradicts", "supports"], targets[0]


# --------------------------------------------------------------------------- #
# 2. The cache-key contract
# --------------------------------------------------------------------------- #
def test_writes_under_the_current_salt():
    """A new verdict must land on the key step07 would compute TODAY, so `replay` reads
    it back as prompt_generation=current and a future step07 run gets it free."""
    ws = Workspace()
    try:
        run_stubbed(ws, "irrelevant")
        entries = ws.cache_entries()
        salt = f"{readjudicate.prompt_hash()}|gemini:{MODEL}"
        for ctext, etext, meta in (("claim A", "evidence A", "MediaReport from a.vn, year 2024"),
                                   ("claim B", "evidence B", "Controversy from b.vn, year 2023")):
            key = ContentCache.key(salt, ctext, etext, meta)
            assert key in entries, f"no salted entry for {ctext!r}"
            assert entries[key]["verdict"] == "irrelevant", entries[key]
        legacy_key = ContentCache.key("claim A", "evidence A", "MediaReport from a.vn, year 2024")
        assert legacy_key not in entries, "must not write an unsalted key — that is the old shape"
    finally:
        ws.close()


def test_existing_entries_survive():
    """The live cache holds thousands of paid verdicts. Appending must never drop one."""
    ws = Workspace()
    legacy_key = ContentCache.key("claim A", "evidence A", "MediaReport from a.vn, year 2024")
    preexisting = {legacy_key: {"verdict": "supports", "confidence": 0.8,
                                "rationale": "paid legacy verdict", "provider": "openai"},
                   "some-unrelated-key": {"verdict": "contradicts", "confidence": 0.5,
                                          "rationale": "other", "provider": "gemini"}}
    ws.cache_path.write_text(json.dumps({"version": 1, "entries": preexisting}, ensure_ascii=False),
                             encoding="utf-8")
    try:
        run_stubbed(ws)
        entries = ws.cache_entries()
        for k, v in preexisting.items():
            assert entries.get(k) == v, f"paid entry {k} was destroyed: {entries.get(k)}"
        assert len(entries) == len(preexisting) + 2, f"expected 2 appended entries: {len(entries)}"
    finally:
        ws.close()


def test_a_backup_is_written_before_the_cache_is_touched():
    ws = Workspace()
    ws.cache_path.write_text(json.dumps({"version": 1, "entries": {"k": {"verdict": "supports"}}}),
                             encoding="utf-8")
    try:
        run_stubbed(ws)
        bak = ws.cache_path.with_suffix(".json.pre_readjudicate.bak")
        assert bak.exists(), "no backup of the paid cache was written"
        assert json.loads(bak.read_text(encoding="utf-8"))["entries"] == {"k": {"verdict": "supports"}}
    finally:
        ws.close()


# --------------------------------------------------------------------------- #
# 3. Cost control
# --------------------------------------------------------------------------- #
def test_dry_run_makes_no_calls_and_writes_nothing():
    ws = Workspace()
    try:
        stub = run_stubbed(ws, dry_run=True)
        assert stub.calls_seen == [], f"--dry-run must not call the provider: {stub.calls_seen}"
        assert not ws.cache_path.exists(), "--dry-run must not write the cache"
        assert not ws.out.exists(), "--dry-run must not write the output"
    finally:
        ws.close()


def test_rerun_is_free():
    """Second run: every target is a cache hit under the current salt, so zero calls.
    This is what makes an interrupted run safe to resume."""
    ws = Workspace()
    try:
        first = run_stubbed(ws)
        assert len(first.calls_seen) == 2, first.calls_seen
        second = run_stubbed(ws)
        assert second.calls_seen == [], (
            f"a re-run must cost nothing, got {len(second.calls_seen)} call(s)")
        st = ws.stats()
        assert st["llm_calls"] == 0 and st["cache_hits"] == 2, st
    finally:
        ws.close()


def test_limit_caps_the_paid_calls():
    ws = Workspace()
    try:
        stub = run_stubbed(ws, limit=1)
        assert len(stub.calls_seen) == 1, f"--limit 1 must make exactly 1 call: {stub.calls_seen}"
        st = ws.stats()
        assert st["targets"] == 2 and st["attempted"] == 1, st
    finally:
        ws.close()


def test_provider_dying_midrun_aborts_instead_of_reporting_unusable_replies():
    """`Adjudicator` disables a provider after 3 failures with 0 successes, after which
    `.adjudicate()` returns None WITHOUT calling anything. Counting those as "the model
    gave an unusable reply" is a lie that hides a dead run — the first real 182-pair run
    reported 177 unusable replies when it had actually asked about 5. The stage must
    label them not_asked, still persist whatever was paid for, and exit non-zero."""
    # needs >3 targets: the disable rule fires on the 3rd failure, and everything after
    # it is what "never asked" means.
    ws = Workspace([row(f"claim {i}", f"evidence {i}", f"MediaReport from {i}.vn, year 2024",
                        "legacy", "contradicts") for i in range(6)])
    stub = make_stub()
    original = step07._GeminiProvider

    class _Dead(stub):
        def call(self, system, user):
            raise RuntimeError("stub: 429 rate limited")

    raised = False
    try:
        step07._GeminiProvider = _Dead
        try:
            readjudicate.run(ws.args(max_workers=1))
        except SystemExit as exc:
            raised = True
            assert "not_asked" in str(exc) or "disabled" in str(exc).lower(), exc
    finally:
        step07._GeminiProvider = original

    try:
        assert raised, "a run whose provider died must exit non-zero, not report success"
        st = ws.stats()
        assert st["verdicts"] == 0, st
        # 3 asked (the provider raised on each), then the disable rule fired and the
        # remaining 3 were never asked at all. Conflating the two is the bug.
        assert st["asked_no_verdict"] == 3, st
        assert st["not_asked"] == 3, st
        assert st["provider_disabled"] is True, st
        assert ws.rows() is not None, "partial output must still be written"
    finally:
        ws.close()


def test_stats_record_the_resolved_model_not_the_raw_flag():
    """--model defaults to None and Adjudicator resolves it to GEMINI_MODEL. Recording
    the raw flag writes `"model": null` into the provenance of a paid artifact."""
    ws = Workspace()
    try:
        run_stubbed(ws, model=None)
        st = ws.stats()
        assert st["model"], f"resolved model must be recorded, got {st['model']!r}"
        assert st["model"] in st["cache_salt"], (
            f"the recorded model must be the one in the salt: {st['model']} / {st['cache_salt']}")
    finally:
        ws.close()


def test_output_rows_carry_both_verdicts_for_comparison():
    """The point of the exercise is measuring how the prompt change moved verdicts, so
    each row must keep the legacy verdict beside the new one."""
    ws = Workspace()
    try:
        run_stubbed(ws, "irrelevant")
        rows = ws.rows()
        assert len(rows) == 2, rows
        for r in rows:
            assert r["verdict"] == "irrelevant", r
            assert r["prompt_generation"] == "current", r
            assert r["legacy_verdicts"], r
            assert r["changed"] is True, "legacy supports/contradicts -> current irrelevant is a change"
        st = ws.stats()
        assert st["changed"] == 2 and st["unchanged"] == 0, st
    finally:
        ws.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
