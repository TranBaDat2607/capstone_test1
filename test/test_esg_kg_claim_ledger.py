#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice:
`src/step09_report_claim_ledger.py` -> `esg_kg.report.claim_ledger`.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
step09 imports NOTHING from a sibling stage — it defines its own `REPO_ROOT` the same
"count parents" way every `src/` script used to (PIPELINE.md §2.1: "(không import stage
nào)"). The only change here is swapping that self-defined constant for
`esg_kg.core.paths.REPO_ROOT`, the same single-source-of-truth swap every migrated leaf has
made since step01 — purely a consistency change, not something anyone was blocked on.

THE FIRST NEO4J-READ STAGE TO MIGRATE
Every prior Neo4j-touching migration (step08, step06) only WRITES — the fake driver could
get away with recording (query, params) and returning an empty/zeroed result, because
neither stage does anything with what Neo4j hands back. step09 is different: `load_from_
neo4j()` actually consumes the rows (`.single()`, `list(...)`, a `for row in ...` loop) and
builds dossier dicts out of them, and the render functions consume THOSE. So the fake driver
here must return real canned data, not just swallow calls — otherwise there is nothing for
either tree's processing logic to diverge on, and the arm would be vacuous. Both trees are
fed the IDENTICAL canned rows (via a shared queue consumed in call order, since the stage
issues its 4 reads in a fixed order: org name -> claim rows -> edge rows -> conduct-pool
rows), so the arm proves two things at once: the Cypher text/params sent are byte-identical,
AND the dossier dicts built from the same input rows are byte-identical.

WHY THERE IS NO REAL-CORPUS ARM (unlike every prior migration)
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
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script --------------------------------------------------
import step09_report_claim_ledger as old_step09  # noqa: E402

# --- new: the esg_kg package -----------------------------------------------------
from esg_kg.report import claim_ledger as new_step09  # noqa: E402

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def _norm(text: str) -> str:
    """Mask the ONE deliberate cosmetic difference between the two trees: the "how to
    refresh" command reference in render_header_text's source line (old:
    `python src/step08_sync_crosscheck_to_neo4j.py`, new: `python src_module/run.py
    neo4j_sync`) — the same one-line message swap step04/step06/step08 each made when they
    migrated (pointing users at the new entry point). Everywhere else the trees must match
    byte-for-byte; this is the only masked field, unlike step07's non-deterministic
    `recorded_at` there is nothing random here, just an intentional wording difference."""
    return (text
            .replace("src/step08_sync_crosscheck_to_neo4j.py", "<SYNC_CMD>")
            .replace("src_module/run.py neo4j_sync", "<SYNC_CMD>"))


# --------------------------------------------------------------------------- #
# Synthetic dossier dicts — the shape load_from_neo4j() assembles and every
# render_* function consumes.
# --------------------------------------------------------------------------- #
def _mini_dossiers():
    return [
        {
            "claim_id": "AAA_SC_001", "claim_text": "Chung toi cam ket giam 20% phat thai CO2 vao 2025.",
            "year": 2023, "claim_source_type": "report", "assessment": "appears_contradicted",
            "supporting_evidence": [],
            "contradicting_evidence": [
                {"class": "MediaReport", "text": "Bai bao doc lap noi ve vu viec X.",
                 "source_domain": "baodientu.vn", "year": 2023, "date": "2023-06-01",
                 "confidence": 0.82, "rationale": "Mau thuan voi cam ket.", "provider": "openai",
                 "date_uncertain": False, "source_doc": None, "source_page": None,
                 "article_title": "Tieu de bai bao doc lap"},
            ],
            "flagged_non_independent_support": [],
            "signals": {"structural_contradiction": True, "kpi_gap": False},
            "caveats": ["Thin independent conduct."],
            "assessment_scores": {"contradicted": 0.7, "supported": 0.2, "abstain": 0.1},
            "score_disagrees_with_assessment": False,
            "source_doc": "AAA_2023.pdf", "source_page": 12,
        },
        {
            "claim_id": "AAA_SC_002", "claim_text": "100% chat thai duoc xu ly dat chuan.",
            "year": 2022, "claim_source_type": "report", "assessment": "appears_supported",
            "supporting_evidence": [
                {"class": "ThirdPartyVerification", "text": "Chung nhan ISO 14001.",
                 "source_domain": "", "year": 2022, "date": None, "confidence": 0.6,
                 "rationale": "", "provider": "openai", "date_uncertain": True,
                 "source_doc": "AAA_2022.pdf", "source_page": 5, "article_title": None},
            ],
            "contradicting_evidence": [], "flagged_non_independent_support": [
                {"class": "MediaReport", "text": "Bai PR tu website cong ty.",
                 "source_domain": "aaacorp.com.vn", "year": 2022, "date": None,
                 "confidence": 0.4, "rationale": "", "provider": "openai",
                 "date_uncertain": True, "source_doc": None, "source_page": None,
                 "article_title": "Thong cao bao chi AAA"},
            ],
            "signals": {"structural_contradiction": False, "kpi_gap": True},
            "caveats": [], "assessment_scores": None, "score_disagrees_with_assessment": False,
            "source_doc": None, "source_page": None,
        },
        {
            "claim_id": "AAA_SC_003", "claim_text": "Claim khong co bang chung nao.",
            "year": None, "claim_source_type": "report", "assessment": "unverified_insufficient_evidence",
            "supporting_evidence": [], "contradicting_evidence": [], "flagged_non_independent_support": [],
            "signals": {}, "caveats": [], "assessment_scores": None,
            "score_disagrees_with_assessment": False, "source_doc": None, "source_page": None,
        },
    ]


def _mini_conduct_pool():
    return {"MediaReport": 5, "Controversy": 1}


# --------------------------------------------------------------------------- #
# Pure rendering / sorting arm — no Neo4j needed, carries the bulk of the logic.
# --------------------------------------------------------------------------- #
def test_is_review_queue_and_sort_key_match_both_trees():
    for d in _mini_dossiers():
        assert old_step09.is_review_queue(d) == new_step09.is_review_queue(d)
        assert old_step09._sort_key(d) == new_step09._sort_key(d)


def test_build_header_and_render_header_text_match_both_trees():
    dossiers = _mini_dossiers()
    pool = _mini_conduct_pool()
    old_h = old_step09.build_header("AAA", "Cong ty A", dossiers, pool)
    new_h = new_step09.build_header("AAA", "Cong ty A", dossiers, pool)
    assert old_h == new_h
    assert _norm(old_step09.render_header_text(old_h)) == _norm(new_step09.render_header_text(new_h))


def test_source_ref_matches_both_trees():
    for d in _mini_dossiers():
        assert old_step09._source_ref(d) == new_step09._source_ref(d)
        for ev in d.get("supporting_evidence", []) + d.get("contradicting_evidence", []):
            assert old_step09._source_ref(ev) == new_step09._source_ref(ev)


def test_render_entry_text_matches_both_trees():
    for d in _mini_dossiers():
        assert old_step09.render_entry_text(d, 300) == new_step09.render_entry_text(d, 300)


def test_render_markdown_matches_both_trees():
    dossiers = _mini_dossiers()
    pool = _mini_conduct_pool()
    old_h = old_step09.build_header("AAA", "Cong ty A", dossiers, pool)
    new_h = new_step09.build_header("AAA", "Cong ty A", dossiers, pool)
    from collections import defaultdict
    old_groups, new_groups = defaultdict(list), defaultdict(list)
    for d in sorted(dossiers, key=old_step09._sort_key):
        old_groups[d.get("assessment", "unverified_insufficient_evidence")].append(d)
    for d in sorted(dossiers, key=new_step09._sort_key):
        new_groups[d.get("assessment", "unverified_insufficient_evidence")].append(d)
    old_md = old_step09.render_markdown(old_h, old_groups, 300)
    new_md = new_step09.render_markdown(new_h, new_groups, 300)
    assert old_md == new_md


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


def test_load_from_neo4j_identical_calls_and_output_both_trees():
    old_queue = [list(rows) for rows in _canned_rows()]
    new_queue = [list(rows) for rows in _canned_rows()]
    old_fake = _FakeGraphDatabase(old_queue)
    new_fake = _FakeGraphDatabase(new_queue)

    old_name, old_dossiers, old_pool = old_step09.load_from_neo4j(
        old_fake.driver("bolt://x"), None, "AAA")
    new_name, new_dossiers, new_pool = new_step09.load_from_neo4j(
        new_fake.driver("bolt://x"), None, "AAA")

    assert old_name == new_name == "Cong ty A"
    assert old_dossiers == new_dossiers
    assert old_pool == new_pool
    assert len(old_fake.calls) == len(new_fake.calls) == 4
    for (oq, op), (nq, np_) in zip(old_fake.calls, new_fake.calls):
        assert oq == nq
        assert op == np_


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


def test_run_stdout_identical_both_trees():
    old_queue = [list(rows) for rows in _canned_rows()]
    new_queue = [list(rows) for rows in _canned_rows()]
    old_out = _run_captured(old_step09, _ns(), old_queue)
    new_out = _run_captured(new_step09, _ns(), new_queue)
    assert _norm(old_out) == _norm(new_out)
    assert "AAA" in old_out and "Cong ty A" in old_out


def test_run_markdown_file_identical_both_trees():
    import tempfile
    old_queue = [list(rows) for rows in _canned_rows()]
    new_queue = [list(rows) for rows in _canned_rows()]
    with tempfile.TemporaryDirectory() as td:
        old_md = Path(td) / "old.md"
        new_md = Path(td) / "new.md"
        _run_captured(old_step09, _ns(markdown=str(old_md)), old_queue)
        _run_captured(new_step09, _ns(markdown=str(new_md)), new_queue)
        assert old_md.read_text(encoding="utf-8") == new_md.read_text(encoding="utf-8")


def test_run_review_queue_and_claim_id_filters_identical_both_trees():
    old_queue = [list(rows) for rows in _canned_rows()]
    new_queue = [list(rows) for rows in _canned_rows()]
    old_out = _run_captured(old_step09, _ns(review_queue=True), old_queue)
    new_out = _run_captured(new_step09, _ns(review_queue=True), new_queue)
    assert _norm(old_out) == _norm(new_out)

    old_queue = [list(rows) for rows in _canned_rows()]
    new_queue = [list(rows) for rows in _canned_rows()]
    old_out = _run_captured(old_step09, _ns(claim_id="AAA_SC_002", maxlen=100000), old_queue)
    new_out = _run_captured(new_step09, _ns(claim_id="AAA_SC_002", maxlen=100000), new_queue)
    assert _norm(old_out) == _norm(new_out)


def test_run_no_claims_for_ticker_exits_both_trees():
    """load_from_neo4j() calls sys.exit(1) when the org has no claims — both trees must
    refuse the same way rather than one crashing with a raw exception."""
    empty_name_row = [{"name": None}]
    for module in (old_step09, new_step09):
        queue = [empty_name_row, [], [], []]
        fake = _FakeGraphDatabase(queue)

        def _fake_connect(_args_ns, _fake=fake):
            return _fake.driver("bolt://x"), None

        original_connect = module.connect
        module.connect = _fake_connect
        try:
            try:
                module.run(_ns(ticker="ZZZ"))
                assert False, f"{module} did not exit when no claims exist for the ticker"
            except SystemExit as e:
                assert e.code == 1
        finally:
            module.connect = original_connect


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed"
          + (f", {len(_skips)} skipped." if _skips else "."))
