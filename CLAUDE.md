# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **Graph-RAG pipeline for detecting greenwashing in Vietnamese listed companies**
(Construction / Building Materials / Real Estate sector). It ingests ESG statements
from annual reports and news, classifies them, extracts numeric KPIs, and builds a
**temporal ESG knowledge graph** so a company's *reported* ESG claims can be
cross-checked against its *real-world* conduct.

## `EmeraldMind/` is a read-only reference — NOT part of this project

`EmeraldMind/` is an external reference implementation. **Never edit it and never
treat its files as part of this codebase** (don't list, refactor, or count them as
project files). You may read it to understand intent: `src/` here ports
`EmeraldMind/src/EmeraldKG/` steps 1→2→3 closely, then 4 (entity resolution) as a
**deliberate redesign** — all adapted to take **labeled JSONL** input (not PDFs) and a
**single `GEMINI_API_KEY`** (not a multi-key pool). When porting more EmeraldKG stages,
keep prompts/validation/output conventions identical so stages stay drop-in compatible;
when a stage is redesigned instead of ported (like step 4), document why in `docs/`.
It is **excluded from git** (`.gitignore` → `EmeraldMind/`) — it has its own `.git`
repo and secrets, so it is never committed or pushed with this project.

## Environment & conventions

- **Windows / PowerShell** host. `.rar`/`.7z` extraction in `crawl_data/extract_archives.py`
  shells out to external **UnRAR.exe / 7z.exe** (install WinRAR + 7-Zip separately).
- **Generated data is distributed via Hugging Face, not Git** (`src/data_sync.py`, not a
  pipeline step): `data/`, `graph_output/`, `kpi_output/` are git-ignored (~342 MB) and ship
  as an HF dataset repo. The pushed revision is **pinned in `data_version.json`, which IS
  tracked in Git** — so a checkout recovers the data that went with that code, which is what
  makes the baseline vs after-Phase-0 comparison reproducible. Never re-run an expensive stage
  to get data a teammate already pushed; `pull` it. Needs `huggingface_hub` (imported lazily,
  deliberately not in `requirements.txt` so the tool works on a bare clone) and `HF_TOKEN` in
  `.env` (or `hf auth login`). The repo lives in the `nammovuivui-capstone` **org**, not a personal
  namespace — HF has no collaborator feature for user-owned repos, so an org is the only way to
  share a private one; you must be invited to it (`read` to pull, `write` to push) or it 404s.
  **Anyone pushing must commit `data_version.json` in the same sitting** — a pushed snapshot whose
  pin is not committed is invisible: the team keeps pulling the old revision with no error. `git pull`
  before pushing, so a pin conflict surfaces in Git rather than silently overwriting someone's
  snapshot. `neo4j_data/` is never synced — rebuild it with step06. Both `push` and `pull` are
  scoped with `ALLOW_PATTERNS` to exactly those three folders: `local_dir` is the CODE repo, so
  an unscoped pull writes the dataset's own root files over tracked ones — that is how the Hub's
  `.gitattributes` came to be committed here (and why this repo now routes `*.png/jpg/zip/parquet`
  through Git LFS). Guarded by `test/test_data_sync_scope.py`.
- **Secrets:** copy `.env.example` → `.env` and set `GEMINI_API_KEY` (and optionally
  `OPENAI_API_KEY`, the fallback LLM provider for step 6's cross-check). All `src/` LLM
  scripts load `.env` from the repo root regardless of cwd. `.env` is git-ignored — never
  commit it.
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`, `src_module/`,
  `kpi_build/`, `gri/`, plus the UI pair `api/` + `frontend/`). Everything else is `config/`
  (schema + dictionaries), `neo4j/` (`init.cypher` constraints + `crosscheck_queries.cypher`
  analyst queries), or `data/` (`raw/` → `interim/` → `labeled/` → `outputs/`).
  **No data files inside code packages** — with two named exceptions, both run-once
  provenance builders that keep their sources beside them so a claim can be traced to a
  page: `kpi_build/` and `gri/` (the latter carries 42 GRI Standards PDFs, ~45 MB, in Git).
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/` scripts are **standalone files** run directly (`python src/step02_extract_triplet_from_jsonl.py`);
    they import each other by module name relying on Python putting `src/` on `sys.path`.
    Run them from the repo root.
  - `src_module/esg_kg/` is the in-progress third style (see the refactor section below):
    a real package, run from the repo root via its dispatcher —
    `python src_module/run.py quality --label baseline` (equivalently
    `python -m esg_kg.report.quality` from inside `src_module/`). 14 of 15 stages have been
    migrated so far (everything except step02); `python src_module/run.py --list` shows which, and it asks the
    import system rather than trusting a hand-kept list. `src/` is still the pipeline
    you execute.
- **Sentence-level traceability** (`source_pdf`, `page`, `sentence_index`) is preserved
  through every stage so each graph node traces back to its source — keep it intact.
- **Torch is intentionally absent from `requirements.txt`.** The ViDeBERTa ESG classifier
  runs on GPU via `notebooks/kaggle_esg_classify.ipynb`; install torch locally only to
  test `data_processing/esg_classifier.py` on CPU.
- **Other deps are deliberately unlisted and imported lazily** — each degrades gracefully
  so a bare clone still runs: `huggingface_hub` (`data_sync.py`), `rapidfuzz` (step03c's
  fuzzy tier; disabled with a warning if absent), `openai` (step07). Install them
  on demand rather than adding them to `requirements.txt`.
- **Gemini is currently billing-blocked**, so the code has drifted to OpenAI where a
  choice exists: step07's `DEFAULT_PROVIDER_ORDER` is `"openai"` and step05 is run with
  `--no-llm` (Stages A + B.1 only — no embedding blocking, no adjudication). Don't
  "fix" these back to Gemini without checking whether the key works.

## Working rule: Test-Driven Development (applies to ALL code from now on)

**Write the test first. Run it. See it fail. Then write the code.** No production code
lands without a failing test that demanded it. This is not optional and not limited to the
refactor — it is how code gets written in this repo from now on.

The cycle, per unit of work:
1. **Red** — write the smallest test that expresses the next behaviour, run it, confirm it
   fails *for the expected reason* (a test that passes before the code exists is testing nothing).
2. **Green** — the minimum code to pass. No extra features "while I'm here".
3. **Refactor** — clean up with the test green, re-run.

Conventions (match `test/test_temporal_invariants.py`, the existing precedent):
- **Plain `assert` scripts, no pytest** — the repo has no pytest/linter harness. A test is
  a runnable file under `test/` printing pass/fail and exiting non-zero on failure.
- **Tests must be offline** — no LLM, no Neo4j, no network. They run on real artifacts
  already on disk (`config/schema.json`, `graph_output/…`). This keeps them free and
  repeatable; **never verify by re-running a paid stage** (see also `--dry-run`/`--no-llm`).
- Run from the repo root: `python test/<name>.py`.
- Touching step03/03b/03c/05/05b/05c/08 still means re-running `test_temporal_invariants.py`.

## Active refactor: `src/` → `src_module/esg_kg/`

Migrating the 19 flat `src/step*.py` scripts to a module architecture, **one stage at a
time**. Design + old→new file mapping: `src_module/esg_kg/DESIGN.md`; canonical run order
(replacing the `stepNN_` prefixes): `src_module/esg_kg/pipeline.py`.

Non-negotiable rules while this is in flight:
- **Model A — never rewire `src/`.** The old pipeline must keep running untouched.
  `esg_kg` is not on `src/`'s `sys.path`, so editing `src/` to import from it would just
  `ImportError`. Helpers therefore **exist in both trees temporarily** — accepted cost.
- **The TDD test for this refactor is an old-vs-new equivalence test**: import the `src/`
  original *and* the `esg_kg` version, run both on real input, assert equal results. Write
  it before extracting the module. This is the only thing preventing the two copies drifting.
- **A stage may move only when every symbol IT imports already lives in `esg_kg.core`** —
  *not* merely when nobody imports it. Order: finish `core/` → leaf stages → hubs
  (step04 → step03 → step02 → step01).
- Extract helpers **verbatim**. Behaviour changes and refactoring are separate commits.

**Goal of the refactor: `esg_kg` must be able to rebuild the graph from scratch — including
for AAA** (DESIGN.md §5.4, decided 2026-07-26). So **"it would change `identity_keys` /
node order / invalidate the paid dossiers" is NOT a veto any more** — it is a scheduled
cost. When a refactor touches a mechanism whose correct fix belongs at an earlier stage,
**canonicalize it there** instead of preserving the later patch; keep a late patch only
under E2/E3 (those are about *information*, which a re-extraction cannot recover). E1
patches (`anchor_method`, `provenance_method`, step03c's `kpi_id`) now have an expiry date.
Two things do not relax: §5.3 still applies (a canonicalization is a behaviour change → its
own commit, **both trees**, red-first test), and the re-extraction is a deliberate one-time
decision — **deterministic `claim_id` (GitHub issue #2) must land first**, or step08's tier-1
resolution misses silently. Until that run happens, `src/` is still the live pipeline.

State: `core/` has `paths` (marker-based `REPO_ROOT`), `schema`, `naming`, `dates`, all
covered by `test/test_esg_kg_equivalence.py`. **`step00` is the first migrated STAGE**
(`esg_kg/report/quality.py`) — with it the run convention is settled: `src_module/run.py`
is the only file that touches `sys.path`, and it reads the stage table from `pipeline.py`
so `--list` reports migration status honestly. No `pip install` step.

`step03c` is the second migrated stage (`esg_kg/kpi/canonicalize.py`), its equivalence arm
comparing all 5,214 real KPIObservation occurrences across both trees.
**`step04b` is deliberately NOT ported either** (DESIGN.md §4.2, decided 2026-07-26): it read
`resolved_graph.json` — step05's *output* — while step05 reads the registry it writes, a
dependency cycle that made it unrunnable on a bare clone; and its scan earned nothing (all 10
aliases in the committed registry are its own hardcoded `SEEDS`, and a re-run only surfaced
step04b's own `canonical_name` as a to-review item). So **`config/standards_registry.json` is
static config now** — nothing regenerates it, it carries `match_patterns`/`exclude_hints`
inline, and **step00 audits its coverage** instead (`standards_registry_audit`, same family as
the P1 identity lint). `src/step04b_build_standards_registry.py` is NOT deleted — it remains
the from-scratch reseed tool.
`step05c` is the third migrated stage (`esg_kg/resolve/indicators.py`, 2026-07-27). Moving it
gave `GraphPatch`/`temporal_md` a home in **`core/graph_patch.py`** — they had been imported
UP into `src/step05d:34` from a stage, the "a step file doubles as a utility library" knot
`core/` exists to untie. The diff against `src/` is 15 added / 115 deleted lines with **no new
logic line**, generated by slicing the file rather than retyping it. Its two run-level
equivalence arms are complementary, not redundant: the real-graph arm runs on a copy with the
indicator axis **stripped** (remove `StandardIndicator` nodes + the 4 axis edge labels, remap
the array indices) because the live graph is already patched and every stats counter sits
behind `if gp.add_edge(...)` — without stripping it compares two empty reports; and the
synthetic arm is the only one that reaches the `Penalty` fine branch, since all four live
`Penalty` nodes carry `amount == 0` and take the self-reported-zero `continue`.
`step03b` is the fourth migrated stage (`esg_kg/graph/anchor_kpi.py`, 2026-07-27), diff
17 added / 20 deleted with **no logic line changed**. It came with **`core/identity.py`**
(`parse_source_id` <- step03b, `get_stable_entity_id`/`PROVENANCE_CLASSES` <- step02):
`parse_source_id` was DEFINED in step03b and imported by `step05b:51`, so moving the stage
without lifting it would have left the migrated 05b importing from a sibling stage — the
same knot `core/graph_patch.py` untied a day earlier. Its arms live in a separate
`test/test_esg_kg_anchor_kpi.py` (the equivalence file is past 1,100 lines) and the
**first draft of them was vacuous**: the live `all_validated_triples.json` is already
patched (95 of its 306 `observedAtFacility` edges carry `anchor_method=offline_gazetteer`),
so a re-run emits nothing and the arm compared two empty results while printing PASS. This
is now a known law for every in-place-patch stage, with two confirmed cases — strip the
stage's OWN past output to rebuild the pre-patch input (`strip_axis` for 05c,
`strip_anchors` for 03b), stripping by provenance and never by edge label (the other 211
`observedAtFacility` edges came from extraction and must stay). See `src_module/PIPELINE.md` §3.
`step05b` is the fifth migrated stage (`esg_kg/resolve/provenance.py`, 2026-07-27), diff
18 added / 8 deleted — docstring and imports only, **no logic line changed**. It is the
first stage to move **without extracting any new `core/` module**: the step03b slice had
already lifted all four symbols it needs. Its arms are in `test/test_esg_kg_provenance.py`.
**It also corrected the in-place-patch law above, so read that law with this caveat**: the
right question is not "does the stage patch in place" but **"when it meets its own past
output, does it `continue` or recompute?"** 05c/03b skip, so their naive arms went vacuous;
step05b's only skip is `provenance_method == "extraction"` (zero nodes today — it is for
post-re-extraction step02 output), so it re-matches and re-stamps everything and the live-graph
arm really does compare 6,258 stamps. `strip_provenance` is still written, but to prove a
stronger property: none of the keys 05b writes appears in any `PROVENANCE_CLASSES`
`identity_keys`, so `get_stable_entity_id` cannot see them and **the stage never reads its own
output** — if that broke, the graph would drift on every re-run with no other signal.
**`core/llm.py` landed 2026-07-27 — the kernel now has no blocking module left.** It lifts
`DEFAULT_RATE_LIMIT` + `RateLimiter` (from step02) and `_Provider` + `_OpenAIProvider` (from
step07), verbatim, no logic line changed. Those four **cannot be split**: `_OpenAIProvider.
__init__` constructs a `RateLimiter`, i.e. step07 was reaching UP into step02 for a utility.
It migrates no stage (still 5/16) but unblocks four at once, taking the symbol-eligible set
from 4 to **8**: `01`, `03`, `04`, `05`, `05d`, `06`, `07`, `09`. `Adjudicator` deliberately
stayed in step07 (stage logic: prompt, verdict parsing, provider cascade), so **`step08`
(and, at the time, `step10`) are NOT unblocked** — they wait on step07 itself, not on the
kernel. (`step10` was removed from the project outright on 2026-07-28 — see the note near
the end of this section — so read "`step08` and `step10`" below as history, not a stage
still pending.) `step02` waits
on `core/io_jsonl`, which falls out of the step01 slice rather than preceding it. Its arms
are in `test/test_esg_kg_llm.py`, and the one that earns its keep pins the **paid request
shape** with a stub client (`temperature=0`, `response_format={"type":"json_object"}`, the
system/user split, and `wait_if_needed` firing before `create`) — drop any of those and
step07 still "works" while every verdict silently changes. Choosing what moves next is now
about **arm strength, not symbol availability**.
`step03` is the sixth migrated stage (`esg_kg/graph/fix_triples.py`, 2026-07-28) and the
second — after step05b — to move **without extracting any new `core/` module**. Two lessons
worth reusing, both of which contradicted the plan:
**(a) "hub" must be tested by import DIRECTION, not by how many files import you.** Seven
`src/` stages import from step03, which is why DESIGN.md §4 had it queued in the late "hub"
batch — but every symbol they take (`ISO_DATE_RE`/`normalize_date_string`/`date_start_key`
→ `core/dates`, `load_schema_sets`/`validate_triple` → `core/schema`) had already been
lifted by earlier slices, and nothing imports its stage-local functions. The hub had already
dissolved; the rule that governs is the one about what a stage *itself* imports. Check the
same way before scheduling `step04`.
**(b) A same-named constant is not a shared constant.** `DEFAULT_RATE_LIMIT` exists in both
step03 and `core/llm` and both are `10`, so importing the kernel's would have looked correct
forever — and would silently retune step03 the day step02's limit changes. Only `RateLimiter`
is shared; the constant stays module-local, pinned by an arm.
Its arms are in `test/test_esg_kg_fix_triples.py`. The stage is also the first where the
in-place-patch question (PIPELINE.md §3) answers *"never meets its own output"* — the main
path reads step02's `graphs/` and writes a different file, so the real-corpus arm (14,492
validated + 1,036 unfixable, both trees) is non-vacuous with no `strip_*` fixture. Only
`--renormalize` re-reads the aggregated file, and that is where the idempotency arm sits.
Phase 2 (the paid branch) is driven by a stubbed LLM in both trees, so
`preserve_property_values` is proven wired in the migrated copy too — mutation-checked: unwiring
the guard reddens the phase-2 arm, dropping `_bugged` files reddens the corpus arm.
`step05d` is the seventh migrated stage (`esg_kg/resolve/align_claims.py`, 2026-07-28) and
the third — after step05b and step03 — to move **without extracting any new `core/` module**:
the step05c slice had already lifted `GraphPatch`/`temporal_md` into `core/graph_patch.py`
*precisely because* this file imported them from a stage. No logic line changed; two dead
symbols are dropped (`TODAY`, defined and never read, and an unused `RateLimiter` import).
**Its real lesson is about test strategy, and it inverts a criterion this file used to state:
"has `--dry-run`" is NOT what makes a stage easy to test.** `--dry-run` here returns *before*
the provider is even constructed, so a dry-run-only arm proves almost nothing about a
mandatory-LLM stage. What earns the arm is a **stub provider injected over `_OpenAIProvider`
in both trees**, answering deterministically from a CRC of the prompt so both trees see
identical replies — the same technique that covered step03's phase 2. Having now worked
twice, it is a general pattern, so **"the stage costs money" is no longer a reason to defer
one**: that removes the standing objection to `step07`, which is the only stage still
blocking others (`08` waits on `node_text`, `10` on `Adjudicator`). Its arms are in
`test/test_esg_kg_align_claims.py`, including the documented `node_text` trap (05d's takes a
properties dict, step07's takes a node), `SYSTEM` pinned byte-for-byte, and an append-only /
node-order arm that matters more here than elsewhere: unlike step05c this stage never calls
`assert_append_only()` itself. It also adds a **fourth** case to the in-place-patch law
(PIPELINE.md §3): 05d *does* skip its own output like 05c/03b, but the live artifact contains
none of it (all 639 `alignsWithIndicator` edges are step05c's `keyword` tier, zero are `llm`),
so the arm is non-vacuous **because of the data, not the design** — `strip_llm_alignments()`
is written and applied anyway, removing 0 edges today. A separate commit then fixed a defect
the migration surfaced and deliberately did not touch: `parse_reply` called `.get()` on
whatever `json.loads` returned, so a reply of `[]` or `"text"` raised `AttributeError` instead
of returning `None` — and since `run()` writes the graph only after the loop, one odd reply
discarded every adjudication already paid for. Fixed in **both** trees per §5.3.
`step07` is the eighth migrated stage (`esg_kg/crosscheck/claims_vs_conduct.py`, 2026-07-28)
and the highest-leverage move in the refactor so far: it was the only stage still blocking
others (`08` on `node_text`, `10` on `Adjudicator`, both via a lazy import), so migrating it
unblocks both at once. It is also the first migration to import BACK from a kernel module
built out of itself — `_Provider`/`_OpenAIProvider` came from `core/llm.py` (2026-07-27,
extracted from this very file), and this slice is what finally has the stage import them
rather than redefine them; the previously-dead `RateLimiter` import (from step02) is dropped,
the same shape step05d's dead import had. `Adjudicator` stays in the stage, exactly as
`core/llm.py`'s docstring always said it would — prompt text, verdict parsing, and the
provider cascade are stage logic, not kernel. Unlike step05d, `--dry-run` here does NOT
return before the provider is built (it only skips the final writes), so the dry-run arm is
itself a real equivalence check, not a vacuous one. This stage reads `resolved_graph.json`
and writes to a different directory (`graph_output/crosscheck/`), so it never meets its own
past output — PIPELINE.md §3's in-place-patch question does not apply, the same shape step03
had. Its arms are in `test/test_esg_kg_crosscheck.py` (22 groups), including a reciprocal
`node_text` trap check (this stage's takes a NODE and dispatches on class; step05d's takes a
properties dict — each test file pins the divergence from its own side), the self-verification
guard (a company-owned domain must never get a `verifiedBy` edge), and the assessment-mapping
priority (a contradiction always wins over supporting evidence in the same dossier). The
migration surfaced the same class of defect step05d's `a308608` fixed: `_parse_verdict` also
called `.get()` on whatever `json.loads` returned, so a reply like `[]` crashed instead of
being treated as unusable. Here the blast radius was smaller — the call sits inside
`Adjudicator.adjudicate`'s own try/except, so it degraded to "no verdict for this pair"
rather than losing a whole run — but it was still misfiled as a *provider failure* rather
than an unusable-reply no-op. Following the same order as step05d, this landed as verbatim
first, then a follow-up commit added an `isinstance(out, dict)` guard in **both** trees per
§5.3, with a red-first test (`test_parse_verdict_rejects_non_object_json_in_BOTH_trees`).
06/09 read Neo4j, 01 costs money, 04 is *nominally* a hub — re-checked 2026-07-28 per lesson
(a) and **its hub has dissolved too**: all three symbols other stages take from it
(`normalize_name`, `name_tokens`, `merge_preserving_edits`) are already in `core/naming.py`,
and step04 itself imports only `REPO_ROOT`. `step01` is now the ONLY genuine hub left.
`step04` is the ninth migrated stage (`esg_kg/registry/issuer.py`, 2026-07-28, same day as
`step07`): confirmed leaf per the check above, AST-diff shows **11 shared functions, 0
bytes different**, `main()` changes exactly one error message (points at `build_validated`
instead of `step03_fix_invalid_triplets.py`, since §3.2 renamed the stage that produces its
input), and the 3 deleted functions are exactly the 3 now imported from `core/naming`. What
is new here versus every prior leaf move: `step04` writes `config/issuer_registry.json`, a
file **tracked in git with human edits** (that is why `merge_preserving_edits` exists), so
every equivalence arm must run `build()` against a temp workspace and never touch the real
file — covered by a dedicated arm plus one that simulates a person moving a `needs_review`
entry into `exclusions` and re-running. Test: `test/test_esg_kg_issuer.py` (12 groups). A
follow-up commit then removed a dead branch DESIGN.md §5.2 had already flagged: `build()`
used to sniff `isinstance(data, dict) and "nodes" in data and "edges" in data` as an
alternate input shape, but the only writer of its input (`step03`/`build_validated`) always
emits `List[Dict]`, and `step05` reads that same file with no sniffing at all. Removed in
**both** trees at once, red-first (`test_build_no_longer_silently_converts_a_nodes_edges_dict_in_either_tree`).
`step01` is the tenth migrated stage (`esg_kg/kpi/extract.py`, 2026-07-28, the day after
`04`/`07`) and the genuine hub the lesson-(a) recheck predicted: it does not use
`_Provider`/`_OpenAIProvider` at all — `core/llm.py`'s own docstring records that no Gemini
provider was ever lifted (the project behind `GEMINI_API_KEY` is permanently 403), so this
stage talks to `google.genai.Client` directly, and `KPIExtractor`, its prompt, its JSON
schema, and `normalize_kpi_response` all stay stage-local — nothing else in the pipeline
imports them. Only the 5 pure JSONL-reconstruction helpers move, into a new kernel module
**`core/io_jsonl.py`**: `load_pages_from_jsonl`, `build_page_text`, `page_has_esg`,
`select_documents`, `parse_company_year_from_filename` — exactly the 5 symbols
`step02_extract_triplet_from_jsonl.py:43-50` imports from step01, so this module is what
`step02` needs, not a precondition for `step01` itself (the same shape `core/identity.py`
fell out of the step03b slice). Diff against `src/`: docstring, import block, and the 5
deleted function bodies — no logic line changed. The paid path has no `_Provider` to stand
in front of, so the stub is injected directly over `google.genai.Client`, answering
deterministically from a CRC of the prompt — the fourth use of the technique first proven on
step03's phase 2, confirming it is a general pattern rather than an OpenAI-specific trick.
Arms: the real corpus (13 documents / 1,356 pages, `load_pages_from_jsonl` output byte-equal
between trees) plus a synthetic `process_document` run through both trees, including an
idempotency check — `out_file.exists()` must skip without re-calling the client, the same
"does it skip or recompute" question PIPELINE.md §3 asks of every stage that meets its own
past output, just applied to files instead of graph nodes. Test:
`test/test_esg_kg_extract.py` (10 groups). With this move, no stage is a "hub" in the
import-direction sense any more (lesson (a)) — `02`/`05`/`06`/`09` wait only on their own
turn or a scheduling decision (§3.1, §5.6), never on a symbol still stuck in a sibling stage.
`step08` is the eleventh migrated stage (`esg_kg/load/neo4j_sync.py`, 2026-07-29) and the
first Neo4j-touching stage to move: a confirmed leaf (it imports only its own `REPO_ROOT`
and `node_text` from step07, which moved the day before and is what unblocked this one).
Every earlier paid/networked stage covered its expensive branch for free by injecting a
stub UNDER an existing abstraction layer (`_OpenAIProvider`, `google.genai.Client`) — step08
has no such layer in front of the real call (`from neo4j import GraphDatabase`, a lazy
import inside `run()`, executed only past `--dry-run`), so the stub instead replaces the
installed `neo4j` package's `GraphDatabase` attribute directly, the same shape the step01
migration used when there was no provider abstraction standing in front of the Gemini
client either. The fake driver records every Cypher string + parameter dict it receives and
executes nothing, so `test/test_esg_kg_neo4j_sync.py` compares 5 real Neo4j calls
byte-for-byte between both trees on the real corpus (1,093 dossiers against the 10,425-node
resolved graph) without touching a live database. Diff against `src/`: docstring, the
`REPO_ROOT`/`node_text` import swap, and two comment/log strings pointing at `run.py`
instead of the old `src/stepNN_*.py` filenames — no logic line changed. The `node_text`
trap (§2 above) held for a third time: `esg_kg.load.neo4j_sync.node_text is
esg_kg.crosscheck.claims_vs_conduct.node_text`, pinned by a dedicated test. Test:
`test/test_esg_kg_neo4j_sync.py` (8 groups, incl. `--clear-advisory`, a missing-resolved-graph
positional-only fallback, and the `sys.exit(1)` guard for a missing dossier file).
`step06` (`esg_kg/load/neo4j_load.py`) and `step09` (`esg_kg/report/claim_ledger.py`) moved
the same day as `step08` (the twelfth and thirteenth migrated stages): `step06` is the
second Neo4j-*writing* stage, with a wider client surface than `step08`
(`session.execute_write` + a read-back via `.single()`), so its fake session/tx has to
answer both shapes, not just record calls (`test/test_esg_kg_neo4j_load.py`, 5 groups).
`step09` is the first Neo4j-*reading* stage migrated — `load_from_neo4j()` actually
processes what the driver returns, so its fake driver must serve real fake data (a queue of
4 result sets, one per `session.run()` call) rather than just record what it was asked, and
it is the first migrated stage with no real-corpus arm at all (it reads only Neo4j, no JSON
file on disk) — the strongest arm instead covers its pure presentation/sorting helpers
(`test/test_esg_kg_claim_ledger.py`, 10 groups).
**BLOCKS — the shape `esg_kg` is allowed to change (DESIGN.md §5.7, decided 2026-07-28).**
When N stages each read AND write the same artifact they are not N stages, they are one:
in `esg_kg` they become a block that chains in memory and writes the artifact ONCE.
`src/` is NOT touched and keeps the stages separate — this is a deliberate redesign, not
drift, so §5.3's "land it in both trees" does not apply to block changes (§5.5's constraint
2 is corrected accordingly). The first block is **`03 → 03b → 03c`**
(`esg_kg/graph/build_validated.py`, `run.py build_validated`), registered in a `BLOCKS`
table in `pipeline.py` separate from `STAGES` because a block has no `src/` counterpart by
design. Three things make it safe, and they generalize:
**(a) `src/` is still the oracle.** The change is to WHEN the file is written, never to
WHAT is in it — so the test runs the `src/` chain 03→03b→03c and asserts the block's
artifact is identical (14,584 triples / 92 anchors / 679 `kpi_id`, real corpus, free). The
day a refactor breaks that property, stop: there is no oracle left.
**(b) "intermediate artifact" ≠ "cache of a paid result".** Dropping the first is the goal;
dropping the second would make every block run re-pay for phase 2 AND return something
different each time (the LLM is not deterministic). Today 03b/03c re-run for free precisely
BECAUSE they read a frozen file. So phase-2 repairs go to `phase2_repairs.json`, keyed by
triple CONTENT (never by position — batch boundaries move), storing the model's raw reply
with `preserve_property_values` applied on the way out.
**(c) a block ADDS an entry point, never removes the per-stage ones** — losing the ability
to run one stage alone loses the ability to diagnose it. Per-stage stats files stay too:
they are diagnostics, not intermediate artifacts.
Its arms are in `test/test_esg_kg_validated_block.py`; `test_pipeline_table.py` covers the
`BLOCKS` table. `fix_triples` gained `run_phases()` (phases 1–1.5, writes nothing) with
`process_all_files()` = `run_phases` + the writes, so the stage's behaviour is unchanged.
**`step05` moved on 2026-07-29 (the fourteenth migrated stage, `esg_kg/resolve/entities.py`)
together with a SECOND block, `05 → 05b → 05c`** (`esg_kg/resolve/build_resolved.py`,
`run.py build_resolved`) — the answer §3.1 (below) used to defer. Confirmed leaf per the
symbol rule: every import (`REPO_ROOT`, `RateLimiter`, `date_start_key`, `normalize_name`)
already lived in `core/`; one dead import (`load_schema_sets`, never called) is dropped,
the same "garbage import" shape already seen in `05d`/`07`. Unlike most leaf moves,
`resolve(args)` was split at migration time (not as a block follow-up the way
`fix_triples` gained `run_phases()`): `resolve_graph(triples, idkeys, ...) ->
(resolved, stats)` is pure — no file I/O, no client construction — so the block calls it
directly and chains straight into 05b/05c in memory; `main()` keeps the exact `src/`
CLI/file-write behaviour for standalone `run.py entities`. `indicators.py` (05c) got the
same `run_phases`-style split for the block: `link_indicator_axis(graph, defs, crosswalk,
catalog, ...)` pulled out of `run()`, pure extraction, 0 logic lines changed
(`test/test_indicator_axis.py` stays green untouched). `provenance.py` (05b) needed no
change at all — `stamp_graph()` was already pure since it moved. **`05d` (align_claims) is
deliberately NOT part of the block**: it is optional (budgeted LLM) and already patches
`resolved_graph.json` in place AFTER 05c, unchanged — the block must produce a correct
graph with 05d entirely absent. The paid-path cache is scoped narrower than §5.7 first
sketched: cluster 05 has TWO paid branches (Stage B embeddings, Stage C adjudication), and
only Stage C — the non-deterministic LLM verdict, the exact analogue of `03`'s phase-2
repairs — gets `AdjudicationCache` (keyed by pair content, same shape as `RepairCache`).
Stage B is deliberately left uncached: it is billed but deterministic per model version,
and per "Gemini is currently billing-blocked" above, Stages B/C do not run in the live
pipeline at all today (`--no-llm` is the default), so an embedding cache would be
speculative work for a currently-dormant path — a candidate follow-up, not a gap. The
oracle arm runs `src/`'s real chain `step05(--no-llm) -> step05b -> step05c` (today's
actual operating mode, not a weakened proxy) and compares to the block: 10,425 nodes /
14,387 edges identical on the real corpus. Tests: `test/test_esg_kg_entities.py` (7
groups, stage-alone, incl. a `google.genai.Client` stub for Stage B/C — same technique as
`step01`, no `_Provider` abstraction to stand in front of Gemini) and
`test/test_esg_kg_resolve_block.py` (5 groups, incl. the "writes exactly once" pair and a
smoke-check that `05d` still runs cleanly against the block's output).
**`step07b` is deliberately NOT being ported** (DESIGN.md §4.1): the delivered surface is
the `frontend/`+`api/` UI, which never reads its softmax scores, so `pipeline.py` carries
it as `new_module=None` and `run.py --list` shows `(not ported)` and drops it from the
denominator. It is NOT deleted — `src/step07b_enrich_dossiers.py` still runs, and both
consumers tolerate the scores being absent (step08 sets null, step09 skips the block). After
the planned re-extraction the new dossiers start without scores; run that script by hand if
you want them back — that is not a reason to port it.
Known debt: `src/step00_graph_quality_report.py` still exists, so the T1/T2/T3 tier map that
`test/test_schema_contract.py` imports lives in two trees — cleanup commit spelled out in
`src_module/esg_kg/DESIGN.md` §6.1.

**`step10` (P6 evaluation) was removed from the project outright on 2026-07-28** — a
project-scope decision, not a refactor-scope one like `step07b`/`step04b` above: this style
of measurement (coverage/case-study/ablation with no ground truth) is no longer a
deliverable, not superseded by anything. Unlike `step07b`/`step04b`, `src/step10_evaluate.py`
and `docs/EVALUATION.md` were both deleted rather than kept as standalone tools, and
`esg_kg/pipeline.py::STAGES` no longer carries a `"10"` row. See
`src_module/esg_kg/DESIGN.md` §4.3 and `src_module/PIPELINE.md` §4 for the record.

Corrections to DESIGN.md found by review, since resolved by the migrations themselves:
- The two `node_text` are **NOT duplicates** — `step05d`'s takes a *properties dict*,
  `step07`'s takes a *node* and class-dispatches. Both have now moved
  (`esg_kg.resolve.align_claims.node_text` / `esg_kg.crosscheck.claims_vs_conduct.node_text`),
  keeping separate names; each stage's equivalence test pins the divergence from its own side.
- ~~`GraphPatch` / `temporal_md` (step05c) are shared but have no home in the `core/`
  layout — this blocks step05d.~~ Resolved 2026-07-27: they live in `core/graph_patch.py`.
- ~~`step05d`, `step08`, `step10` are listed as safe "leaf" moves but are not: they import
  from step05c/step07.~~ `step05d` has since moved (2026-07-28). `step08`/`step10` were
  blocked on `step07` itself (not a `core/` module) — `step10_evaluate.py:367`'s lazy
  `from step07… import Adjudicator` inside a `try` still fails *silently* if broken, but
  `step07` has now moved too (2026-07-28), so `step08` is unblocked and just awaits its own
  turn. (`step10` itself was removed from the project on 2026-07-28, after this was
  written — see the "Known debt" note above and `src_module/esg_kg/DESIGN.md` §4.3; the
  file path quoted above no longer exists.)

## Pipeline architecture (the big picture)

Data flows left→right; each stage's output is the next stage's input.

**A. Ingestion → ESG sentences**
```
crawl_data/download_reports.py   → data/raw/annual_report/        (threaded, resumable, from config/company_annual_report.xlsx)
data_processing.prepare_sentences → data/interim/sentences/*.jsonl (every sentence, NO ESG filter)
   ├─ pdf_extractor.py     (PyMuPDF, keeps page numbers + Vietnamese diacritics)
   └─ sentence_splitter.py (underthesea, VN-aware segmentation)
ViDeBERTa-v3-ESG classifier      → data/labeled/                  (multi-label E/S/G/Neutral per sentence)
   (notebooks/kaggle_esg_classify.ipynb on GPU; data_processing/esg_classifier.py = same logic, CPU)
data_processing.extract_esg      → data/outputs/esg_extracted/    (trimmed Graph-RAG-ready records)
```

**B. News ingestion (parallel evidence channel = the "conduct" side)**
```
esg_news_crawler.run → data/outputs/news/<TICKER>.jsonl + coverage.csv
   companies → queries → Google News RSS / Bing / DuckDuckGo → fetch (disk-cached, rate-limited)
            → extract (trafilatura) → normalize (sentence-split into the annual-report schema)
ViDeBERTa-v3-ESG classifier      → data/labeled/news_labeled/       (same classifier as reports)
data_processing.preprocess_news  → data/interim/news_preprocessed/  (P1: normalize publish dates,
   add publish_date_normalized / publish_year / date_uncertain, drop boilerplate; NO domain routing)
```
Reports are the **claim** side ("what they say"); news is the **conduct** side ("what they do").
Both feed the same `src/` graph-construction path and land in one temporal KG (see `docs/SYSTEM_DESIGN.md`).

`crawl_data/crawler_news.py` is a separate, FPT-specific standalone news crawler (not a
`-m` package, not wired into pipeline B above) — treat it as a legacy/experimental tool, not
the documented news-ingestion path. See `docs/NEWS_CRAWLER_OPTIMIZATION.md` for its design.

**C. Labeled JSONL → temporal knowledge graph (`src/`, the EmeraldKG port)**
```
src/step00_graph_quality_report.py      → graph_output/quality/quality_report_<label>.{json,md}
   (offline diagnostics, NO LLM/DB: measures the Q1–Q8 quality attributes of the resolved
    graph — consistency incl. P4 temporal invariants + P1 identity lint, conciseness,
    conduct completeness, Q7 traversability (median degree / leaves / masked-answerable /
    hub-free structural claim→conduct / T2 anchoring). Run BEFORE and AFTER any
    schema/pipeline change with --label; see docs/TEMPORAL_KG_DESIGN.md §4)
src/step01_extract_kpi_from_jsonl.py    → kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json
   (per page: Gemini 2.5 Flash w/ structured output → typed KPIObservation records,
    only pages with ≥1 esg=true sentence are sent; uses kpi_definitions_construction.json)
src/step02_extract_triplet_from_jsonl.py → graph_output/graphs/<pdf_stem>/page{N}.json  (+ _bugged.json, _malformed.txt)
   (per page: page text + page KPIs + config/schema.json → temporal triples → node/edge graph.
    --source report (default) = claim-side prompt; --source news = conduct-side prompt (Controversy/
    MediaReport/Penalty/observed KPIObservation); every node/edge stamped source_type=report|news)
src/step03_fix_invalid_triplets.py      → graph_output/validated/all_validated_triples.json (+ unfixable_triples.json)
   (Phase 1 offline: swap reversed edge directions + schema-validate;
    Phase 1.5 offline (P4): canonicalize dates to ISO YYYY[-MM[-DD]], warn valid_from>valid_to,
    default missing date_uncertain on news T2 nodes; --renormalize applies only this phase to
    the existing aggregated file (no LLM, keeps prior repairs);
    Phase 2 LLM: batch-repair invalid triples; Phase 3: aggregate)
src/step03b_anchor_kpi_facilities.py    → appends to all_validated_triples.json (+ anchor_patch_stats.json)
   (P3 offline patch, NO LLM: gazetteer of Facility names already in the graph matched against
    each KPI's source sentence (source_id → labeled JSONL) → emits KPIObservation
    --observedAtFacility--> Facility edges, tagged anchor_method=offline_gazetteer.
    Run after step03, before step05. New extractions get anchors from the step02 prompt instead)
src/step03c_canonicalize_kpis.py        → appends/patches all_validated_triples.json (+ kpi_canonical_stats.json)
   (offline, NO LLM: assigns each KPIObservation a canonical `kpi_id` from the 35-indicator
    vocabulary via config/kpi_type_aliases.json + rapidfuzz on official names, writing a NEW
    property (NEVER rewrites `kpi_type`, which is in identity_keys — so node order is preserved
    and paid step07 dossiers survive). Also unit_normalized/value_normalized/period and a
    Goal.target_date regex backfill (future years only). Feeds the indicator axis, docs/
    STANDARD_INDICATOR_AXIS.md §5.2. Run after step03b, before step04. Precision over recall:
    financial KPIs in VND are rejected, not force-mapped)
src/step04_build_issuer_registry.py     → config/issuer_registry.json                       (run-once bootstrap)
   (drafts the reporting company's name variants → aliases / exclusions / needs_review;
    re-running preserves human edits, --force rebuilds; a human confirms needs_review)
config/standards_registry.json          — STATIC CONFIG, no longer a pipeline stage (2026-07-26)
   (the 5 reference documents behind the indicator vocabulary (TT96, QĐ2171, QCVN09, SSC-IFC,
    GRI) with their aliases/exclusions + `match_patterns`/`exclude_hints`. step05's standards
    anchor freezes GRI's ≥4 spellings and TT96 VN/EN onto one canonical node each (diagnosis C3).
    Hand-edited: add an alias, then re-run step05. NOTHING generates it — step00's
    `standards_registry_audit` reports uncovered mentions instead, which is all the old
    generator ever produced. `src/step04b_build_standards_registry.py` still exists as the
    from-scratch reseed tool, but it is OFF the run order: it read step05's output while
    step05 read its output. See DESIGN.md §4.2)
src/step05_resolve_entities.py          → graph_output/resolved/resolved_graph.json (+ _stats.json)
   (step 4: collapse duplicate entity nodes into canonical entities, keeping temporal history.
    Stage A deterministic identity_keys merge + FROZEN issuer anchor (issuer_registry.json) +
    FROZEN standards anchor (Stage A.3, standards_registry.json — Standard/Regulation mentions);
    Stage B VN-aware blocking (normalized signature + gemini-embedding-001 cosine);
    Stage C gemini-2.5-flash adjudication on ambiguous pairs (budgeted); Stage D consolidate)
src/step05b_stamp_provenance.py         → patches resolved_graph.json in place (+ provenance_patch_stats.json)
   (offline provenance patch, NO LLM: matches claim/evidence nodes (PROVENANCE_CLASSES, never
    T1 entities) back to the per-page graph_output/graphs/<doc>/page{N}.json files via a 4-tier
    precedence (parseable source_id → exact source_id index → recomputed stable_id → _pageNN_
    token) and stamps source_doc/source_page (+ article_title/url/domain for news docs from the
    news JSONL). NEVER reorders nodes (step06 _node_key + dossier node_index are positional).
    Run after step05, before step06; re-run after any step05 re-run. New step02 extractions
    self-stamp (provenance_method=extraction) and are skipped. See docs/PROVENANCE_PATCH.md)
src/step05c_link_standard_indicators.py → patches resolved_graph.json in place (+ indicator_axis_stats.json)
   (offline, NO LLM: materializes the TT96/GRI indicator axis. APPENDS ~35 StandardIndicator
    nodes + edges: partOf (indicator→document), measuredUnder (KPIObservation/Emission→indicator,
    read from step03c's kpi_id — never guessed here), equivalentTo (TT96→GRI, from
    config/standard_crosswalk.json, confirmed rows only), and a keyword tier of alignsWithIndicator
    (Claim/Goal/Initiative→indicator; longest matching phrase wins). Penalty amount==0 = self-reported
    "fined 0 times" → flagged self_reported_zero, NO conduct edge. APPEND-ONLY (asserts the
    existing node/edge prefix is untouched — dossiers stay valid). Also RESTAMPS
    StandardIndicator.pillar from the file entitled to say — kpi_definitions_construction.json
    for the VN vocabulary, config/gri_catalog.json (--gri-catalog) for GRI — and never invents
    one: an id neither covers keeps the pillar it had. The Evidence View reads that property
    directly for a claim's E/S/G column, so a guess there is visible to the reader. Run after
    step05b, before step06. See docs/STANDARD_INDICATOR_AXIS.md)
src/step05d_align_claims_to_indicators.py → patches resolved_graph.json in place (+ indicator_align_llm_stats.json)
   (OPTIONAL, LLM, budgeted: alignsWithIndicator for the Claim/Goal/Initiative the keyword tier
    left unresolved. Topic classification only (alignment_method=llm), NOT a supports/contradicts
    judgement. Pipeline is complete without it. Run after step05c; --max-llm-pairs, --dry-run)
src/step06_load_graph_to_neo4j.py       → Neo4j (bolt://localhost:8687, db `neo4j`)            (step 5)
   (load the resolved {nodes,edges} graph as a property graph — NO LLM. Nodes keyed by
    array index (entities already resolved; not re-deduped); edges keep temporal_metadata and
    MERGE on a temporal _edge_key so multi-year edges stay distinct; temporal_versions become
    supersedes version-node chains for supersedes-legal classes, else a JSON property)
src/step07_crosscheck_claims_vs_conduct.py → graph_output/crosscheck/<ticker>_claim_assessments.json   (step 6)
   (the analytical core: for each SustainabilityClaim, retrieve conduct-side candidates →
    LLM-adjudicate supports/contradicts/irrelevant → write verifiedBy / contradictedBy* edges.
    LLM adjudication is MANDATORY (no deterministic fallback) — provider cascade
    (--provider-order, default `openai` = gpt-4o-mini); aborts up front if no provider is
    available. **OpenAI is the ONLY provider left**: Gemini support was removed outright
    (step07:34) because the project behind GEMINI_API_KEY is permanently 403, so the
    registry at step07:321 holds just `openai` and passing `gemini` logs "Unknown
    adjudication provider — ignored". Do not plan a Gemini fallback here.
    Self-verification guard drops company-own-domain "verify" edges.
    Emits advisory dossiers — NO greenwashing score/label. --dry-run / --to-neo4j)
src/step07b_enrich_dossiers.py          → patches the step07 dossiers in place (idempotent)     (step 6c)
   (offline, NO LLM/DB: softmax over three evidence-balance components → assessment_scores
    {contradicted, supported, abstain} + score_components + score_disagrees_with_assessment,
    written back into <ticker>_claim_assessments.json. This is NOT a greenwashing
    probability (SYSTEM_DESIGN §1.1 — no ground truth); the categorical `assessment` stays
    the primary output. Deterministic over the frozen dossier, so it never needs the paid
    step07 re-run. The `signals` terms (lam_struct/lam_kpi/lam_bp) contribute 0 until the
    generator in docs/CROSSCHECK_EXPANSION.md lands — safe to run today. Consumed by
    step08 + step09. Read docs/SOFTMAX_SCORING.md before touching the formula; beta0 is a
    design decision, not a fitted parameter. --dry-run, --calibrate, --bin-confidence, --params)
src/step08_sync_crosscheck_to_neo4j.py  → Neo4j advisory layer                                        (step 6b)
   (NO LLM — reuses the paid step-6 dossier. MERGEs assessment/caveats/signals onto claim nodes +
    llm_supports / llm_contradicts / llm_flagged_support evidence edges (incl. KPI contradictions
    the base schema can't express). Idempotent; --clear-advisory, --dry-run)
src/step09_report_claim_ledger.py       → stdout + graph_output/crosscheck/<ticker>_claim_ledger.md   (step 7)
   (presentation only — NO LLM, reads ONLY Neo4j (run step 6b first). Per-company claim ledger,
    signal-first (contradicted → supported → unverified), with the coverage caveat.
    --review-queue (contradiction + no verification), --assessment, --claim-id, --markdown)
```

`src/step10_evaluate.py` (step 8 / P6 evaluation report, no-ground-truth coverage/case-study/
ablation) was **removed from the project on 2026-07-28** — see the "Known debt" note above.
The claim ledger (`step09`) is the last stage in the pipeline now.

The `src/` scripts share helpers by importing across files: later stages import
`REPO_ROOT`, `build_page_text`, `load_pages_from_jsonl`, `RateLimiter`, `load_schema_sets`,
`normalize_name`, etc. from the earlier ones (`step01_extract_kpi_from_jsonl`,
`step02_extract_triplet_from_jsonl`, `step03_fix_invalid_triplets`, `step04_build_issuer_registry`). Changing a
shared helper's signature affects every downstream stage.

**D. KPI definition builder (`kpi_build/`, run-once provenance pipeline)**
Stages `01_…`→`06_…` download official Vietnamese ESG regulations (Circular 96/2020,
QĐ 2171, QCVN 09, SSC-IFC guide) and extract them **verbatim** into
`kpi_definitions_construction.json` (35 KPIs, each carrying a `source` block). This file
is the controlled KPI vocabulary consumed by stage C's KPI extractor. It rarely needs
rebuilding; treat it as generated data.

**D2. GRI catalog builder (`gri/`, run-once, same shape as `kpi_build/`)**
`gri/crawl_full_gri.py` downloads the 42 GRI Standards PDFs into
`gri/full_gri/Full set of GRI Standards - English/` and extracts them to
`gri/full_gri/json/`; `gri/build_gri_catalog.py` folds those into
**`config/gri_catalog.json`** — 136 GRI indicator codes with `title_vi`/`title_en`,
`pillar`, `units`, `tt96_equivalent`, `versions[]` and per-PDF `sha256`. step05c reads it
for GRI node names and pillars. **NOT a pipeline stage** (it reads no pipeline output, so
unlike the old step04b there is no cycle) — rebuild by hand after editing the crawl or the
crosswalk, then commit the regenerated JSON.
*Ownership rule worth knowing before touching it:* a GRI standard's JSON also re-lists
disclosures belonging to OTHER standards (the sector standards GRI 11–14 and the 2024/25
rewrites GRI 101–103 do this), so a disclosure is attributed to the standard whose
`standard_id` is its prefix — `standard_of()` — never to whichever file is read first.
Getting that wrong mis-attributed 80/136 entries and mangled 31 titles. Covered by
`test/test_gri_catalog_build.py`.

**E. ESG Evidence View UI (`api/` + `frontend/`) — the demo surface**
`api/main.py` is a **pure–standard-library `http.server`** (deliberately no FastAPI/Flask,
to dodge framework version mismatches) that serves the REST endpoints and the static
`frontend/` on `http://localhost:8000`. All data access lives in `api/evidence_service.py`,
which reads **live Neo4j** (the step06 base graph + the step08 advisory layer) — the mock
data is gone and **Neo4j is REQUIRED**; the query helpers raise `RuntimeError` if it is
unreachable. Only claims carrying an `alignsWithIndicator` edge are shown, so each card's
E/S/G pillar comes from the linked `StandardIndicator.pillar` rather than being guessed.
The frontend (`index.html` + `css/style.css` + `js/app.js`) is intentionally frozen:
per `docs/REAL_DATA_INTEGRATION_GUIDE.md`, data-source changes belong in
`evidence_service.py` only. See `docs/ESG_EVIDENCE_VIEW.md`.

## The graph schema (`config/schema.json`)

The single source of truth for the knowledge graph: ~28 node classes (Organization,
KPIObservation, Emission, SustainabilityClaim, Controversy, …) and ~50 directed edge
labels. Key invariants the `src/` validation relies on (see docs/TEMPORAL_KG_DESIGN.md
for the T1/T2/T3 tier model behind them):
- **At extraction (step02/step03) every node carries** `valid_from`, `valid_to`,
  `is_current`; every edge carries `temporal_metadata` (`valid_from`, `valid_to`,
  `recorded_at`). In the **resolved** graph (step05+) time lives on **edges and T2/T3
  event nodes** (P2); T1 entity nodes are timeless, their history is `temporal_versions`.
- Dates are canonical ISO `YYYY[-MM[-DD]]` (step03 phase 1.5); a version chain with an
  open version has exactly one `is_current=true` (P4, enforced in step05).
- Each node has `identity_keys` used to compute a stable entity id (for dedup/versioning).
  **T1 identity is timeless (P1):** never put time fields (`valid_from`, `date`, `year`,
  `validity_period`, …) in a T1 class's `identity_keys` — step00 lints this. Observation
  classes (`KPIObservation`, `Emission`, `Waste`) legitimately carry time in their keys and
  are versioned per-observation; entities are versioned only when properties change
  (linked via `supersedes` edges).
- An edge label may appear with **multiple legal (source_class, target_class) pairs**;
  the validator treats any matching pair as valid and auto-swaps reversed directions.
- News-derived observation classes (`KPIObservation`, `Controversy`, `Penalty`,
  `MediaReport`) carry a required `date_uncertain` bool: `false` when the article states
  an explicit date/period for that fact, `true` when step02's news prompt had to fall
  back to the article's publish date as a proxy (never silently assume the publish year).
  step07 surfaces this as a caveat on any dossier whose evidence includes an uncertain date.
See `docs/SCHEMA_EXPLAINED.md` for the rationale.

## Common commands

```bash
pip install -r requirements.txt

# 0. Land the data snapshot this commit was built against (instead of re-running the pipeline)
python src/data_sync.py status                              # what is pinned vs what is local
python src/data_sync.py pull                                # teammate: fetch the revision in data_version.json
python src/data_sync.py push                                # after a rebuild: upload + re-pin (needs org `write`)
                                                            #   then: git add data_version.json && git commit

# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg            # labeled JSONL → esg_extracted records

# B. News evidence for one company (conduct side)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news                             # P1: → data/interim/news_preprocessed/ (date-normalize + drop boilerplate)

# C. Labeled JSONL → temporal KG (run from repo root, in order)
python src/step00_graph_quality_report.py --label baseline                   # Q1–Q8 snapshot (before/after any change; offline)
python src/step01_extract_kpi_from_jsonl.py     -i <labeled.jsonl>            # → kpi_output/
python src/step02_extract_triplet_from_jsonl.py -i <report_labeled.jsonl>    # → graph_output/graphs/ (claim side; --source report default)
python src/step02_extract_triplet_from_jsonl.py -i <news_preprocessed.jsonl> --source news   # conduct side (stamps source_type=news)
python src/step03_fix_invalid_triplets.py                                    # → graph_output/validated/
python src/step03_fix_invalid_triplets.py --renormalize                      #   P4-only pass on the existing validated file (no LLM)
python src/step03b_anchor_kpi_facilities.py --dry-run                        # P3 offline anchor patch preview (then run without --dry-run)
python src/step03c_canonicalize_kpis.py --dry-run                            # assign canonical kpi_id (then run without --dry-run; offline, no LLM)
python src/step04_build_issuer_registry.py                                   # → config/issuer_registry.json (run-once; then hand-confirm needs_review)
#   (no step04b: config/standards_registry.json is static config, hand-edited; step00 audits its coverage)
python src/step05_resolve_entities.py                                        # → graph_output/resolved/ (step 4: entity resolution + standards anchor)
python src/step05b_stamp_provenance.py --dry-run                             # provenance patch preview (then run without --dry-run; offline, no LLM)
python gri/build_gri_catalog.py                                              # → config/gri_catalog.json (run-once builder, not a stage; commit the result)
python src/step05c_link_standard_indicators.py --dry-run                     # TT96/GRI indicator axis preview (reports the pillar restamp too; then run without --dry-run)
python src/step05d_align_claims_to_indicators.py --dry-run                   # OPTIONAL LLM: align remaining claims (then --max-llm-pairs N to run)
python src/step06_load_graph_to_neo4j.py --dry-run                           # step 5: preview planned counts, no DB
docker compose up -d                                                 # start Neo4j on :8687 (then run neo4j/init.cypher once — see docs)
python src/step06_load_graph_to_neo4j.py --clear                            # → Neo4j (wipe + load; needs the instance running)
python src/step07_crosscheck_claims_vs_conduct.py --dry-run                 # step 6: preview claim↔conduct pairs (runs LLM, writes nothing)
python src/step07_crosscheck_claims_vs_conduct.py                           # → graph_output/crosscheck/ (advisory dossiers + linking edges)
python src/step07b_enrich_dossiers.py --dry-run                            # step 6c: softmax evidence-balance scores (then run without --dry-run; offline, no LLM)
python src/step08_sync_crosscheck_to_neo4j.py                              # step 6b: push dossiers into Neo4j advisory layer (no LLM)
python src/step09_report_claim_ledger.py                                   # step 7: render the AAA claim ledger FROM Neo4j (no LLM)
python src/step09_report_claim_ledger.py --review-queue --markdown         #   contradiction-no-verification queue + Markdown file
# (step10_evaluate.py / P6 evaluation report was removed from the project 2026-07-28 — see CLAUDE.md "Known debt")

# Refactor target (src_module/esg_kg) — 14/15 stages have moved so far (everything except step02); see src_module/PIPELINE.md
python src_module/run.py --list                                            # stages + which are migrated
python src_module/run.py quality --label baseline                          # == src/step00_graph_quality_report.py
python src_module/run.py extract --doc AAA_2023                            # == src/step01_extract_kpi_from_jsonl.py
python src_module/run.py fix_triples --dry-run                             # == src/step03_fix_invalid_triplets.py
python src_module/run.py canonicalize --dry-run                            # == src/step03c_canonicalize_kpis.py
python src_module/run.py build_validated --dry-run                         # BLOCK: 03 -> 03b -> 03c in one pass,
                                                                           #   writes all_validated_triples.json ONCE (DESIGN.md §5.7)
python src_module/run.py anchor_kpi --dry-run                              # == src/step03b_anchor_kpi_facilities.py
python src_module/run.py issuer                                            # == src/step04_build_issuer_registry.py
python src_module/run.py entities --dry-run                                # == src/step05_resolve_entities.py (--no-llm for --dry-run)
python src_module/run.py provenance --dry-run                              # == src/step05b_stamp_provenance.py
python src_module/run.py indicators --dry-run                              # == src/step05c_link_standard_indicators.py
python src_module/run.py build_resolved --dry-run                          # BLOCK: 05 -> 05b -> 05c in one pass,
                                                                           #   writes resolved_graph.json ONCE (DESIGN.md §5.7); 05d stays separate, after
python src_module/run.py align_claims --dry-run                            # == src/step05d_align_claims_to_indicators.py (optional, runs after the block)
python src_module/run.py neo4j_load --dry-run                              # == src/step06_load_graph_to_neo4j.py
python src_module/run.py claims_vs_conduct --dry-run                       # == src/step07_crosscheck_claims_vs_conduct.py
python src_module/run.py neo4j_sync --dry-run                              # == src/step08_sync_crosscheck_to_neo4j.py
python src_module/run.py claim_ledger                                      # == src/step09_report_claim_ledger.py (Neo4j-only)

# ESG Evidence View UI (web front-end; reads the Neo4j advisory layer, no LLM — see docs/ESG_EVIDENCE_VIEW.md)
python api/main.py                                                         # 3-column TT96/GRI evidence view at http://localhost:8000

# Useful src/ flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load steps: offline only, no LLM/DB/writes);
#   quality (step00): --label <name>, --skip-slow (skip the BFS-heavy Q7(c)/(d)), --max-hops, --standards-registry;
#   fix (step03): --renormalize (P4 pass only); anchor patch (step03b): --max-per-facility, --dry-run;
#   kpi canonical (step03c): --aliases, --fuzzy-threshold, --no-goals, --dry-run;
#   provenance patch (step05b): --graphs-dir, --news-globs, --stats-out, --dry-run;
#   indicator axis (step05c): --crosswalk, --no-gri, --no-align, --trust-draft-crosswalk, --dry-run;
#   claim→indicator LLM (step05d): --max-llm-pairs, --openai-model, --dry-run;
#   resolve: --no-llm (Stages A+B.1 only), --standards-registry, --similarity-threshold, --max-llm-pairs;
#   load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD);
#   crosscheck: LLM adjudication is mandatory (no --no-llm); --max-llm-pairs, --provider-order (default openai), --to-neo4j;
#   softmax scores (step07b): --dry-run, --calibrate (grid over tau/beta1/w_max), --bin-confidence, --params '{"tau":0.75}';
#   sync (step08_sync_crosscheck_to_neo4j.py): --clear-advisory, --dry-run;
#   ledger (step09_report_claim_ledger.py, Neo4j-only): --review-queue, --assessment, --claim-id, --limit, --markdown;
```

No pytest harness or linter is configured — tests are plain assert scripts under `test/`
(see the TDD working rule above; new code adds new files here, test-first). The existing
check covers the P3/P4 Phase-0 temporal logic, the step05b provenance matching, and the
indicator-axis stages (step03c/step05c/step08) — run it from the repo root after touching
step03/step03b/step03c/step05/step05b/step05c/step08:

```bash
python test/test_temporal_invariants.py    # offline, no LLM/DB; asserts date canonicalization,
                                           # temporal invariants, source_id parsing, DSU consolidate,
                                           # provenance tier matching + node-order invariant,
                                           # kpi_id canonicalization, indicator-axis edge minting,
                                           # and step08 stable-id (claim_id) resolution
python test/test_schema_contract.py        # config/schema.json itself: P1 both ways (T1 identity
                                           # timeless / T2 observations KEEP their time key), every
                                           # class in exactly one tier, indicator-axis edge pairs.
                                           # Tier map is IMPORTED from step00, never re-declared.
                                           # Run after ANY hand-edit to schema.json.
python test/test_indicator_axis.py         # drives step05c's real run() on a temp workspace:
                                           # self-reported-zero Penalty gets NO conduct edge,
                                           # kpi_id-not-kpi_type boundary, confirmed-crosswalk
                                           # gate, stage-level append-only + idempotency.
python test/test_standards_audit.py        # step00's standards-registry audit, in BOTH trees:
                                           # an uncurated GRI spelling surfaces, an out-of-scope
                                           # accounting standard does NOT (the noise filter that
                                           # makes the section readable), a curated exclusion
                                           # stays closed, and canonical_name is never reported
                                           # as unknown (step04b's old feedback artifact).
                                           # Run after touching step00 or the registry config.
python test/test_pipeline_table.py         # refactor stage table (src_module/esg_kg/pipeline.py
                                           # + run.py): every row points at a real src/ file,
                                           # short names don't collide, and a stage that is
                                           # NEVER being ported is rendered as such instead of
                                           # as "not yet" (which would keep dead work queued).
python test/test_gri_catalog_build.py      # gri/build_gri_catalog.py: a disclosure is attributed
                                           # to the standard whose id is its prefix (not to whichever
                                           # file sorts first), pillar comes from the source via
                                           # PILLAR_MAP (never a substring guess), provenance fields
                                           # agree with the attributed standard, and GRI 306's real
                                           # 2016+2020 versions still merge. Run after touching gri/.
python test/test_console_utf8.py           # ensure_utf8_stdout in BOTH trees + the WIRING (main()
                                           # actually calls it, nothing calls it at import). Closes
                                           # the hole the equivalence test cannot see: it never
                                           # executes main() or a __main__ block.
python test/test_data_sync_scope.py        # data_sync pull is scoped to the three synced folders,
                                           # so it can never overwrite a tracked repo-root file
                                           # (that is how the Hub's .gitattributes got committed).
                                           # Offline: snapshot_download is replaced by a recorder.
python test/test_esg_kg_equivalence.py     # refactor safety net: imports BOTH src/ and
                                           # src_module/esg_kg, runs them on the real
                                           # schema/corpus, asserts equal. Run after ANY
                                           # edit to a src/ helper that has a core/ twin,
                                           # or to step00 (whose whole Q1-Q8 surface is
                                           # compared against esg_kg/report/quality.py —
                                           # real graph with --skip-slow, plus a synthetic
                                           # 20-node graph for the 44s Q7 BFS arms).
python test/test_esg_kg_anchor_kpi.py      # same contract as the file above, for the step03b
                                           # migration slice: core/identity (parse_source_id,
                                           # get_stable_entity_id, PROVENANCE_CLASSES) and
                                           # graph/anchor_kpi. Split off because that file is
                                           # past 1,100 lines. Runs the stage in BOTH trees on
                                           # the real corpus with strip_anchors() applied (the
                                           # file on disk is already patched — without the
                                           # strip the arm compares two empty results), plus a
                                           # cap=1 arm for the P5 hub guard the live data never
                                           # trips, plus an idempotency arm. Run after touching
                                           # step03b, step02's identity helpers, or step05b.
python test/test_esg_kg_provenance.py      # same contract, for the step05b migration slice
                                           # (resolve/provenance). Note the CONTRAST with the
                                           # file above: step05b does NOT skip its own past
                                           # output, it re-stamps, so the live-graph arm is
                                           # already non-vacuous (6,258 stamps compared in both
                                           # trees). strip_provenance() is there to prove the
                                           # stage never READS its own output — no key it writes
                                           # is in any identity_keys, so a stripped rebuild must
                                           # be identical. Plus a node-order arm (step06 keys
                                           # Neo4j by array index) and a synthetic arm for the
                                           # provenance_method="extraction" skip that no live
                                           # node exercises. Run after touching step05b, step02's
                                           # identity helpers, or the per-page graph writer.
python test/test_esg_kg_llm.py             # same contract, for the core/llm slice (RateLimiter
                                           # <- step02, _Provider/_OpenAIProvider <- step07).
                                           # Needs NO artifacts, so every arm runs on a bare
                                           # clone. Drives the throttle through a FAKE CLOCK
                                           # (never really sleeps) and pins the PAID request
                                           # shape with a stub client: temperature=0,
                                           # response_format=json_object, the system/user
                                           # split, and wait_if_needed BEFORE create. Those
                                           # are behaviour, not style — dropping one still
                                           # "works" while silently changing every verdict.
                                           # Run after touching step02's RateLimiter, step07's
                                           # providers, or any stage's DEFAULT_RATE_LIMIT.
python test/test_esg_kg_fix_triples.py     # same contract, for the step03 migration slice
                                           # (graph/fix_triples). The headline arm runs the
                                           # REAL corpus (43 doc dirs / 1,370 page files)
                                           # through both trees with client=None — phase 2
                                           # logs-and-skips, so it is offline and free — and
                                           # compares the written artifacts (14,492 validated
                                           # + 1,036 unfixable). No strip_* fixture needed:
                                           # unlike 05c/03b/05b this stage never reads its own
                                           # output. Phase 2 IS covered, by a stubbed tampering
                                           # LLM in both trees, which is what proves
                                           # preserve_property_values is wired into the
                                           # migrated copy and not just src/. Also pins
                                           # BATCH_FIX_PROMPT byte-for-byte (a reworded paid
                                           # prompt still "works" while changing every repair)
                                           # and asserts the new tree IMPORTS the four kernel
                                           # helpers rather than re-copying them. Run after
                                           # touching step03, core/dates, or core/schema.
python test/test_esg_kg_validated_block.py # the 03 BLOCK (DESIGN.md §5.7): 03 -> 03b -> 03c
                                           # as one unit writing the artifact ONCE. The main
                                           # arm runs the src/ chain as an ORACLE and asserts
                                           # the block's artifact is identical — that works
                                           # because the redesign changes WHEN the file is
                                           # written, not WHAT is in it. Paired with a
                                           # non-vacuity arm (src/ chain must write it 3×,
                                           # block exactly 1×) so "exactly 1" cannot be
                                           # trivially true. Also pins the paid-repair cache:
                                           # a second run calls the LLM ZERO times, and a
                                           # rebuild with client=None still reproduces the
                                           # cached repair. Run after touching the block,
                                           # fix_triples.run_phases, anchor_kpi or canonicalize.
python test/test_esg_kg_align_claims.py    # same contract, for the step05d migration slice
                                           # (resolve/align_claims). This stage REQUIRES an
                                           # LLM and --dry-run returns before the provider is
                                           # built, so both trees are driven by a STUB provider
                                           # injected over _OpenAIProvider, answering
                                           # deterministically from a CRC of the prompt — the
                                           # whole paid path compared for free, on the real
                                           # resolved graph (1,810 candidates, 60 adjudications).
                                           # Pins the node_text trap (05d takes a properties
                                           # dict, step07 takes a node — merging them rewrites
                                           # step07's paid prompt), SYSTEM byte-for-byte, and
                                           # append-only/node order, which nothing else guards
                                           # because 05d never calls assert_append_only itself.
                                           # Synthetic fixtures cover the 3-failure abort, an
                                           # indicator id with no node, and the re-run skip.
                                           # Run after touching step05d or core/graph_patch.
python test/test_esg_kg_crosscheck.py      # same contract, for the step07 migration slice
                                           # (crosscheck/claims_vs_conduct) — the highest-
                                           # leverage move so far: the only stage that was
                                           # still blocking others (08 on node_text, 10 on
                                           # Adjudicator). _Provider/_OpenAIProvider now
                                           # import FROM core.llm instead of being redefined
                                           # (that kernel module was extracted FROM this file
                                           # on 2026-07-27); Adjudicator stays in the stage.
                                           # Unlike step05d, --dry-run here does NOT return
                                           # before the provider is built, so the dry-run arm
                                           # is a real equivalence check, not a vacuous one.
                                           # Headline arm runs the full retrieval + stub
                                           # adjudication + dossier path on the real resolved
                                           # graph (1,093 claims, 3,461 candidate pairs) in
                                           # both trees and compares dossiers/stats/edges
                                           # (masking the one non-deterministic field,
                                           # `recorded_at`). Pins the node_text trap from this
                                           # side (this stage's takes a NODE and dispatches on
                                           # class; step05d's takes a properties dict),
                                           # ADJUDICATE_SYSTEM byte-for-byte, the self-
                                           # verification guard (a company-owned domain must
                                           # never get a verifiedBy edge), and the assessment-
                                           # mapping priority (contradiction beats support in
                                           # the same dossier) via synthetic fixtures. Also
                                           # covers a follow-up fix, same shape as step05d's
                                           # a308608: _parse_verdict called .get() on whatever
                                           # json.loads returned, so a reply like "[]" crashed
                                           # instead of being refused — smaller blast radius
                                           # here (caught by Adjudicator.adjudicate's own
                                           # try/except) but still wrong. Fixed in BOTH trees.
                                           # Run after touching step07 or core/llm.
python test/test_esg_kg_issuer.py          # same contract, for the step04 migration slice
                                           # (registry/issuer) — confirmed leaf, not hub:
                                           # AST-diff shows 11 shared functions, 0 bytes
                                           # different; the 3 deleted functions are exactly
                                           # the 3 now imported from core/naming. The stage
                                           # writes config/issuer_registry.json, a file
                                           # TRACKED in git with human edits, so every arm
                                           # runs build() against a temp workspace — one arm
                                           # asserts the real tracked file is never touched,
                                           # another simulates a person moving a needs_review
                                           # entry into exclusions and re-running, proving the
                                           # edit survives identically in both trees. Also
                                           # covers a follow-up fix: build() used to silently
                                           # accept an alternate {nodes,edges} input shape
                                           # that no writer has produced since step03 started
                                           # emitting List[Dict] — removed in BOTH trees,
                                           # red-first. Run after touching step04 or
                                           # core/naming.
python test/test_esg_kg_extract.py         # same contract, for the step01 migration slice
                                           # (kpi/extract) — the last genuine hub (nothing
                                           # else was still importing another stage's
                                           # stage-local symbols). This stage does NOT use
                                           # _Provider/_OpenAIProvider: core/llm.py's own
                                           # docstring records that no Gemini provider was
                                           # ever lifted, so KPIExtractor talks to
                                           # google.genai.Client directly and stays entirely
                                           # stage-local — only the 5 pure JSONL helpers
                                           # (load_pages_from_jsonl, build_page_text,
                                           # page_has_esg, select_documents,
                                           # parse_company_year_from_filename) move, into a
                                           # NEW kernel module core/io_jsonl.py — exactly the
                                           # 5 symbols step02 imports from step01, so this
                                           # module is what step02 needs, not a precondition
                                           # for step01 itself. The paid path has no
                                           # _Provider to stand in front of, so the stub is
                                           # injected directly over google.genai.Client,
                                           # answering deterministically from a CRC of the
                                           # prompt — the fourth use of that technique,
                                           # confirming it is a general pattern and not an
                                           # OpenAI-specific trick. Headline arm compares
                                           # load_pages_from_jsonl/build_page_text/
                                           # page_has_esg on the real corpus (13 documents /
                                           # 1,356 pages) plus a synthetic process_document
                                           # run through both trees, including an idempotency
                                           # check (out_file.exists() must skip without
                                           # re-calling the client). Run after touching
                                           # step01 or core/llm.
python test/test_esg_kg_neo4j_sync.py      # same contract, for the step08 migration slice
                                           # (load/neo4j_sync) — the first NEO4J-touching
                                           # stage to migrate. A confirmed leaf: it imports
                                           # only its own REPO_ROOT and node_text from step07
                                           # (moved the day before — that move is what
                                           # unblocked this one). Every earlier paid/networked
                                           # stage covered its expensive branch by stubbing
                                           # UNDER an existing abstraction (_OpenAIProvider,
                                           # google.genai.Client); step08 has no such layer in
                                           # front of the real call (a lazy `from neo4j import
                                           # GraphDatabase` inside run(), executed only past
                                           # --dry-run), so the stub replaces the installed
                                           # neo4j package's GraphDatabase attribute directly —
                                           # the same shape step01 used when there was no
                                           # provider abstraction in front of the Gemini
                                           # client either. The fake driver records every
                                           # Cypher string + parameter dict and executes
                                           # nothing, so the headline arm compares 5 real
                                           # Neo4j calls byte-for-byte between both trees on
                                           # the real corpus (1,093 dossiers against the
                                           # 10,425-node resolved graph) without touching a
                                           # live database. Also covers --clear-advisory, a
                                           # missing-resolved-graph positional-only fallback,
                                           # the sys.exit(1) guard for a missing dossier file,
                                           # and pins the node_text trap from a third angle
                                           # (esg_kg.load.neo4j_sync.node_text IS
                                           # esg_kg.crosscheck.claims_vs_conduct.node_text).
                                           # Run after touching step08 or crosscheck's
                                           # node_text.
python test/test_esg_kg_neo4j_load.py      # same contract, for the step06 migration slice
                                           # (load/neo4j_load) — the second Neo4j-WRITING
                                           # stage. Wider client surface than step08:
                                           # ingest_nodes/ingest_data_edges/ingest_supersedes
                                           # go through session.execute_write(lambda tx:
                                           # tx.run(...).consume()) rather than a bare
                                           # session.run(), and print_graph_stats reads
                                           # back (.single(), iteration) — so the fake
                                           # session/tx must answer both call shapes and
                                           # read shapes, still recording (cypher, params)
                                           # and executing nothing. Headline arm:
                                           # build_payload() as a pure function on the real
                                           # corpus (10,425 nodes) plus an ingestion arm
                                           # comparing 76 Neo4j calls byte-for-byte between
                                           # both trees. Run after touching step06.
python test/test_esg_kg_claim_ledger.py    # same contract, for the step09 migration slice
                                           # (report/claim_ledger) — the first Neo4j-READING
                                           # stage migrated, unlike step06/step08 which only
                                           # write. load_from_neo4j() actually processes what
                                           # the driver returns, so a "just record the call"
                                           # fake driver (step06/step08's shape) would give a
                                           # vacuous arm — the fake here must return REAL FAKE
                                           # DATA, a queue of 4 result sets in the exact order
                                           # of the 4 session.run() calls, so both the Cypher
                                           # and the assembled dossier can be compared. Also
                                           # the first migrated stage with NO real-corpus arm
                                           # at all (it reads only Neo4j, no JSON file on
                                           # disk) — the strongest arm instead covers the pure
                                           # presentation/sorting helpers (build_header,
                                           # render_markdown, _sort_key, ...), which is most of
                                           # the stage's real logic. Run after touching step09.
python test/test_esg_kg_entities.py        # same contract, for the step05 migration slice
                                           # (resolve/entities) — confirmed leaf (every import
                                           # already in core/; one dead import,
                                           # load_schema_sets, dropped — same "garbage import"
                                           # shape as 05d/07). Unlike most leaf moves,
                                           # resolve() was split into resolve_graph() (pure,
                                           # no file I/O, no client construction) + main() AT
                                           # MIGRATION TIME, not as a later block follow-up
                                           # (contrast fix_triples/run_phases), because the
                                           # resolve BLOCK (build_resolved.py) needs to call it
                                           # directly. Headline arm: resolve_graph() vs the old
                                           # resolve() on the real corpus with no_llm=True —
                                           # today's actual operating mode per "Gemini is
                                           # currently billing-blocked" above, not a weakened
                                           # proxy — comparing the full resolved graph
                                           # (10,356 nodes / 13,041 edges, identical). The paid
                                           # path (Stage B embeddings + Stage C adjudication)
                                           # is covered by a stub over google.genai.Client —
                                           # same technique as step01 (no _Provider
                                           # abstraction stands in front of Gemini) — on a
                                           # synthetic near-duplicate-org fixture (a VN name
                                           # and its English translation, engineered to reach
                                           # Stage B/C since Stage A/B.1 cannot merge them).
                                           # Also proves the new-tree-only AdjudicationCache
                                           # property: a second resolve_graph() call with the
                                           # same cache object calls the LLM zero times and
                                           # reproduces the identical result. Run after
                                           # touching step05 or core/llm.
python test/test_esg_kg_resolve_block.py   # the 05 BLOCK (DESIGN.md §5.7, §3.2b): 05 -> 05b
                                           # -> 05c as one unit writing resolved_graph.json
                                           # ONCE. Same shape as test_esg_kg_validated_block.py
                                           # for the 03 block. Headline arm runs the REAL
                                           # src/ chain step05(--no-llm) -> step05b -> step05c
                                           # as an ORACLE on the real corpus (14,677 validated
                                           # triples) and asserts the block's artifact is
                                           # identical (10,425 nodes / 14,387 edges). Paired
                                           # with the "writes exactly once" arm and its
                                           # counter-arm (the src/ chain must write it 3x, the
                                           # block exactly 1x) — same technique as the 03
                                           # block. The paid-path cache arm runs the block
                                           # twice through a stubbed google.genai.Client on the
                                           # same near-duplicate-org fixture as
                                           # test_esg_kg_entities.py: the second run calls
                                           # generate_content ZERO times and reproduces the
                                           # identical artifact — proving AdjudicationCache
                                           # (Stage C only; Stage B/embeddings is deliberately
                                           # NOT cached, see build_resolved.py's docstring).
                                           # Also a smoke-check that the ALREADY-migrated,
                                           # UNCHANGED 05d (align_claims) still runs cleanly
                                           # --dry-run against the block's output, since 05d
                                           # is deliberately NOT part of the block. Run after
                                           # touching step05, step05b, step05c, or the block.
```

The rest of `test/` and `notebooks/` are Jupyter notebooks for manual validation
(e.g. `test/test_pdf_extraction.ipynb`).

## Documentation map

`docs/SYSTEM_DESIGN.md` is the **final end-to-end system design** — read it first for the big
picture: the symmetric greenwashing setup (reports = claims, independent news = conduct, both
in one temporal KG), the new news→graph branch and claim↔conduct cross-check stage, and the
deliberate "evidence + advisory LLM assessment, no greenwashing score/verdict" framing (no
ground-truth labels exist). The rest of `docs/` holds per-stage design notes worth reading
before modifying a stage:
`SCHEMA_EXPLAINED.md`, `TEMPORAL_KG_DESIGN.md` (the 8 temporal-KG design principles
P1–P8 + the Q1–Q8 quality attributes measured by step00 — read before touching the
schema, step02 prompts, step03, or step05), `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_VALIDATION.md`, `PROVENANCE_PATCH.md` (step 5b — offline source_doc/source_page
stamping of the resolved graph so the UI/ledger can cite report page + article title),
`ENTITY_RESOLUTION.md` (step 4 — why it's a redesign, not a port),
`GRAPH_LOAD_NEO4J.md` (step 5 — Neo4j load; also a redesign),
`CLAIM_CONDUCT_CROSSCHECK.md` (step 6 — claim↔conduct cross-check, the analytical core),
`CLAIM_LEDGER.md` (step 6b sync + step 7 — dossier → Neo4j advisory layer, then the Neo4j-only claim ledger + analyst Cypher),
`SOFTMAX_SCORING.md` (step 6c — the evidence-balance formula, its parameters, and why it
is explicitly not a greenwashing probability; read before changing step07b),
`ESG_EVIDENCE_VIEW.md` (the 3-column TT96/GRI evidence-view UI, `api/` + `frontend/` — how to run the demo),
`REAL_DATA_INTEGRATION_GUIDE.md` (Vietnamese — the mock→live-Neo4j swap for that UI; the
rule that only `api/evidence_service.py` changes, never the frontend),
`ENTITY_RESOLUTION_IMPROVEMENT.md` (Vietnamese — proposal to use graph structural
signatures to auto-resolve step-4's lexically ambiguous `needs_review` cases),
`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`, `VIETNAM_IMPROVEMENT_PLAN.md`,
`NEWS_CRAWLER_OPTIMIZATION.md` (Vietnamese — architecture of the standalone, FPT-specific
`crawl_data/crawler_news.py`, not the documented `esg_news_crawler/` pipeline). The root
`ENTITY_RESOLUTION_PLAN.md` is the step-4 engineering checklist. `README.md` (root),
`esg_news_crawler/README.md`, `kpi_build/README.md`, and `gri/README.md` cover their
respective subsystems.

Added with the GRI catalog (2026-07-26), describing the `src/` pipeline as it runs today —
none of them mention `src_module/`/`esg_kg`, so for the refactor's view of stage C read
`src_module/PIPELINE.md` instead: `docs/PIPELINE_DIAGRAMS.md` (10 figures: architecture,
collection, extraction, KPI, KG construction, entity resolution, cross-check, schema, data
layout, end-to-end sequence), `docs/PIPELINE_UNIFIED.md`, `docs/PROJECT_OVERVIEW.md`,
`docs/GRI_SCHEMA_DOCUMENTATION.md` (the shape of `gri/full_gri/json/*.json` and of
`config/gri_catalog.json`), plus the rendered diagrams in `diagram/`.

**Proposals, not implementations** (pre-defence-1 improvement plan — don't read them as
descriptions of existing code): `CROSSCHECK_EXPANSION.md` (Vietnamese — the `signals`
generator, graph-routed evidence retrieval, and the D1 finding that `kpi_gap` /
`structural_contradiction` are currently *ghost* signals step07 never writes) and
`BERT_NER_GRAPH_QUALITY.md` (Vietnamese — decision analysis: local CPU sentence-embeddings
to replace the billing-blocked `gemini-embedding-001` in step05, underthesea NER for news
anchoring; explicitly rejects fine-tuning a greenwashing classifier, since no labels exist).
`docs/SSRL_REASONING_LAYER.md` is referenced by `TEMPORAL_KG_DESIGN.md` but **is not in the
repo** — the path-reasoning layer (steps 11–13) is unbuilt and its design doc is missing.
