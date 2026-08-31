# Contributing

This is a capstone research project, so the conventions below are not arbitrary style —
several exist because breaking them silently corrupts results rather than failing loudly.
Read this section before your first change.

## The rules that matter

### 1. Test-first, always

No production code lands without a failing test that demanded it.

1. **Red** — write the smallest test expressing the next behaviour. Run it. Confirm it fails
   *for the reason you expect*. A test that passes before the code exists is testing nothing.
2. **Green** — the minimum code to pass. No extra features "while I'm here".
3. **Refactor** — clean up with the test green, then re-run.

### 2. Tests are plain `assert` scripts — there is no pytest

Every test under `test/` is a runnable file that prints pass/fail per group and exits
non-zero on failure. Match the existing shape (see `test/test_temporal_invariants.py`):

```bash
python test/<name>.py      # one file
python test/run_all.py     # everything, one exit code
```

Do not introduce pytest, a linter, or a formatter without discussion. Their absence is a
deliberate choice, recorded here so the next contributor does not "fix" it.

### 3. Tests must be offline, and must never re-run a paid stage

No LLM calls, no Neo4j, no network. Cover a paid or networked stage by stubbing **under**
its abstraction layer — `_GeminiProvider`, `google.genai.Client`, `neo4j.GraphDatabase`, or
a provider passed in as a parameter — with a deterministic fake, so real stage logic runs
against fake I/O.

**Never verify a change by re-running a paid stage.** It costs money and is not repeatable.
The two real-LLM tests exist but no-op unless `RUN_LLM_INTEGRATION_TESTS=1` /
`RUN_LLM_SYSTEM_TEST=1` is set; CI never sets them.

### 4. Paid prompt templates are pinned byte-for-byte

`test_step02_language_guard.py`, `test_step01_step07_language_guard.py` and
`test_step03_llm_value_guard.py` compare prompt text exactly. This looks pedantic and is
not: a reworded prompt still "works", produces plausible output, and silently changes every
downstream verdict — with no error anywhere. If you intend to change a prompt, change the
guard in the same commit and say why.

### 5. Do not quote a fresher number over the frozen evaluation snapshot

`docs/EVALUATION_BASELINE.md` is the authority for every reported figure, and it wins over
whatever is currently on disk. Re-pin deliberately, in its own commit, or not at all.
`docs/PROJECT_HISTORY.md` records decisions that are closed — read it before reopening one.

### 6. Sentence-level provenance is load-bearing

`source_id`, `source_doc`, `source_page` and `sentence_index` flow through every stage so a
graph node can be traced back to the sentence it came from. That traceability is the point
of the system, not a debugging aid. Do not drop these fields.

### 7. Node order in the resolved graph is significant

`neo4j_load`'s node key and the cross-check dossiers' `node_index` are **positional**.
Reordering `resolved_graph.json`'s nodes invalidates paid dossiers. Stages that patch the
graph are append-only and assert it.

## Getting set up

```bash
pip install -r requirements.txt -r requirements-test.txt
cp .env.example .env      # your own keys; never commit this file
python test/run_all.py    # should be green on a bare clone
```

You do **not** need the private dataset to contribute. Data-backed test arms fall back to
the synthetic fixtures in `test/fixtures/`; see "What you can run without data access" in
the README for what a clone can and cannot do.

If you change `test/fixtures/build_fixtures.py`, re-run it and commit the regenerated JSON —
CI checks the committed files still match the generator, and the generator validates
everything it emits against `config/schema.json`.

## Re-run triggers

| after touching | re-run |
| --- | --- |
| step03 / 03b / 03c / 05 / 05b / 05c / 08 | `test_temporal_invariants.py` |
| any `core/` helper, or `report/quality.py` | `test_esg_kg_equivalence.py` |
| `config/schema.json` (any hand edit) | `test_schema_contract.py` |
| `metric/hub.py` or Q7 | `test_quality_hub_set.py` |
| a paid LLM prompt template | that stage's language/value guard |

`test/README.md` has the full per-file catalogue.

## Pull requests

- Branch off `main`; keep one logical change per commit.
- Say **why**, not just what. The commit log is the project's memory.
- Run `python test/run_all.py` and include the result.
- Update the docs you invalidated in the same PR. Documentation drifting out of sync with
  the code has been a recurring problem here.

## Reporting a security issue

See [`SECURITY.md`](SECURITY.md) — please do not open a public issue for a credential leak.
