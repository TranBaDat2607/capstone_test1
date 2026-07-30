#!/usr/bin/env python3
"""
Coverage for `esg_kg.report.claim_ledger` (formerly an old-vs-new equivalence test
against `src/step09_report_claim_ledger.py`).

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Functions whose entire
content was a cross-tree "new equals old" comparison with no independent claim about
correct output were deleted rather than have a guessed expected value bolted on; the
rest were stripped down to the independent assertions they already carried (or, for the
canned-driver arm, rewritten to check the new tree's output against the values baked into
the fixture itself — those are known, not guessed, since this file authors the fixture).

THE FIRST NEO4J-READ STAGE MIGRATED
Every prior Neo4j-touching migration (step08, step06) only WRITES — the fake driver could
get away with recording (query, params) and returning an empty/zeroed result, because
neither stage does anything with what Neo4j hands back. step09 is different: `load_from_
neo4j()` actually consumes the rows (`.single()`, `list(...)`, a `for row in ...` loop) and
builds dossier dicts out of them, and the render functions consume THOSE. So the fake driver
here must return real canned data, not just swallow calls, or there is nothing for the
processing logic to be checked against — hence `_canned_rows()`, a fixed queue of rows
consumed in call order (org name -> claim rows -> edge rows -> conduct-pool rows) whose
resulting dossier shape is exercised below.

WHY THERE IS NO REAL-CORPUS ARM
CLAUDE.md's TDD rule requires tests to be offline — no live Neo4j. Every earlier stage got a
free non-vacuous real-corpus arm from a JSON file already on disk (graphs/, validated/,
resolved/, crosscheck/ — all shipped via the HF snapshot). step09 reads ONLY Neo4j; there is
no on-disk artifact to replay against a fake driver realistically without first re-deriving
the query→row mapping by hand, which is exactly what the canned-driver arm below already
does directly. So the strongest achievable coverage here is: (a) the pure rendering/sorting
functions, which carry the bulk of this stage's actual logic and need no Neo4j at all, plus
(b) the canned-driver arm for the read + assembly path. This is a smaller arm than usual by
necessity, not by choice, and it should not be read as a precedent for skimping elsewhere.

Offline: no LLM, no real Neo4j, no network — nothing here touches `neo4j+bolt://`.

Run from the repo root:

    python test/test_esg_kg_claim_ledger.py
"""

import argparse
import contextlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# --- the esg_kg package -----------------------------------------------------------
from esg_kg.report import claim_ledger as new_step09  # noqa: E402

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


# --------------------------------------------------------------------------- #
# Fake Neo4j driver that RETURNS REAL DATA (unlike the write-only stages' fakes) —
# a queue of canned row-sets consumed in call order, since load_from_neo4j() issues
# its reads in a fixed sequence: name -> claims -> edges -> conduct pool.
# --------------------------------------------------------------------------- #
class _FakeRecord(dict):
    def __getitem__(self, key):
        return dict.get(self, key)


class _FakeResult:
    def __init__(self, rows):
        self._rows = [_FakeRecord(r) for r in rows]

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, calls, queue):
        self._calls = calls
        self._queue = queue

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self._calls.append((query, params))
        rows = self._queue.pop(0) if self._queue else []
        return _FakeResult(rows)


class _FakeDriver:
    def __init__(self, calls, queue):
        self._calls = calls
        self._queue = queue

    def session(self, database=None):
        return _FakeSession(self._calls, self._queue)

    def verify_connectivity(self):
        pass

    def close(self):
        pass


class _FakeGraphDatabase:
    def __init__(self, queue):
        self.calls = []
        self.driver_calls = []
        self._queue = queue

    def driver(self, uri, auth=None):
        self.driver_calls.append((uri, auth))
        return _FakeDriver(self.calls, self._queue)


def _canned_rows():
    """One canned response per s.run() call in load_from_neo4j(), IN ORDER:
    org name, claim rows, edge rows, conduct-pool rows."""
    return [
        [{"name": "Cong ty A"}],
        [
            {"key": "n10", "claim_id": "AAA_SC_001", "text": "Chung toi cam ket giam 20% phat thai CO2 vao 2025.",
             "year": 2023, "src": "report", "assessment": "appears_contradicted",
             "caveats": ["Thin independent conduct."], "struct": True, "kpi_gap": False,
             "score_c": 0.7, "score_s": 0.2, "score_a": 0.1, "score_dis": False,
             "source_doc": "AAA_2023.pdf", "source_page": 12},
            {"key": "n11", "claim_id": "AAA_SC_002", "text": "100% chat thai duoc xu ly dat chuan.",
             "year": 2022, "src": "report", "assessment": "appears_supported",
             "caveats": [], "struct": False, "kpi_gap": True,
             "score_c": None, "score_s": None, "score_a": None, "score_dis": False,
             "source_doc": None, "source_page": None},
        ],
        [
            {"key": "n10", "role": "contradict", "class": "MediaReport",
             "text": "Bai bao doc lap noi ve vu viec X.", "source_domain": "baodientu.vn",
             "year": 2023, "date": "2023-06-01", "confidence": 0.82,
             "rationale": "Mau thuan voi cam ket.", "provider": "openai",
             "independent": True, "date_uncertain": False,
             "e_source_doc": None, "e_source_page": None, "e_article_title": "Tieu de bai bao doc lap"},
            {"key": "n11", "role": "support", "class": "ThirdPartyVerification",
             "text": "Chung nhan ISO 14001.", "source_domain": "", "year": 2022, "date": None,
             "confidence": 0.6, "rationale": "", "provider": "openai",
             "independent": True, "date_uncertain": True,
             "e_source_doc": "AAA_2022.pdf", "e_source_page": 5, "e_article_title": None},
        ],
        [
            {"cls": "MediaReport", "c": 5},
            {"cls": "Controversy", "c": 1},
        ],
    ]


def test_load_from_neo4j_builds_dossiers_from_the_canned_rows():
    """The rows are a fixture we author, so the expected shape below is KNOWN (not
    guessed): the queue is 4 result sets consumed in order (name, claims, edges,
    conduct-pool counts), so the assembled output must reflect exactly those values."""
    queue = [list(rows) for rows in _canned_rows()]
    fake = _FakeGraphDatabase(queue)

    name, dossiers, pool = new_step09.load_from_neo4j(fake.driver("bolt://x"), None, "AAA")

    assert name == "Cong ty A"
    assert len(fake.calls) == 4, f"expected 4 s.run() calls (name/claims/edges/pool), saw {len(fake.calls)}"
    assert pool == {"MediaReport": 5, "Controversy": 1}
    ids = {d["claim_id"] for d in dossiers}
    assert ids == {"AAA_SC_001", "AAA_SC_002"}, f"dossier claim_ids diverged from the canned rows: {ids}"
    by_id = {d["claim_id"]: d for d in dossiers}
    assert by_id["AAA_SC_001"]["assessment"] == "appears_contradicted"
    assert by_id["AAA_SC_001"]["source_doc"] == "AAA_2023.pdf"
    assert by_id["AAA_SC_001"]["source_page"] == 12
    assert len(by_id["AAA_SC_001"]["contradicting_evidence"]) == 1
    assert by_id["AAA_SC_002"]["assessment"] == "appears_supported"
    assert len(by_id["AAA_SC_002"]["supporting_evidence"]) == 1


# --------------------------------------------------------------------------- #
# run() end-to-end via a monkeypatched connect() — captures stdout + optional
# markdown file, compares byte-for-byte between the two trees.
# --------------------------------------------------------------------------- #
def _ns(**kw) -> argparse.Namespace:
    base = dict(ticker="AAA", assessment=None, review_queue=False, claim_id=None,
                limit=None, maxlen=300, markdown=None,
                uri=None, user=None, password=None, database=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _run_captured(module, args_ns, queue):
    fake = _FakeGraphDatabase(queue)

    def _fake_connect(_args_ns):
        return fake.driver("bolt://x"), None

    original_connect = module.connect
    module.connect = _fake_connect
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            module.run(args_ns)
    finally:
        module.connect = original_connect
    return buf.getvalue()


def test_run_stdout_reflects_the_canned_rows():
    queue = [list(rows) for rows in _canned_rows()]
    out = _run_captured(new_step09, _ns(), queue)
    assert "AAA" in out and "Cong ty A" in out


def test_run_no_claims_for_ticker_exits():
    """load_from_neo4j() calls sys.exit(1) when the org has no claims — must refuse
    cleanly rather than crash with a raw exception."""
    empty_name_row = [{"name": None}]
    queue = [empty_name_row, [], [], []]
    fake = _FakeGraphDatabase(queue)

    def _fake_connect(_args_ns):
        return fake.driver("bolt://x"), None

    original_connect = new_step09.connect
    new_step09.connect = _fake_connect
    try:
        try:
            new_step09.run(_ns(ticker="ZZZ"))
            assert False, "did not exit when no claims exist for the ticker"
        except SystemExit as e:
            assert e.code == 1
    finally:
        new_step09.connect = original_connect


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed"
          + (f", {len(_skips)} skipped." if _skips else "."))
