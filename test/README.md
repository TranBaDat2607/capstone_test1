# Test suite

Plain `assert` scripts — **no pytest, no linter is configured**. Each file is runnable on its
own, prints pass/fail per group, and exits non-zero on failure. Run from the repo root:

```bash
python test/<name>.py          # one file
python test/run_all.py         # everything, one exit code, one summary table
python test/run_all.py -k issuer   # only files matching a substring
```

`run_all.py` adds no judgement of its own — each file is still the authority on itself and
runs in its own process. It exists because CI (and anyone evaluating the project) needs a
single command and a single exit code, and because it reports **where the data came from**
(see "Fixtures" below).

New code adds new files here, **test-first** — see the TDD working rule in `CLAUDE.md`, which
is not optional and not limited to the refactor that started it.

Every file is **offline** (no LLM, no Neo4j, no network) except two, which cost real money and
no-op unless their env var is set: `test_esg_kg_integration_llm.py`
(`RUN_LLM_INTEGRATION_TESTS=1`) and `test_esg_kg_system_llm.py` (`RUN_LLM_SYSTEM_TEST=1`).
A paid or networked stage is covered for free by stubbing **under** its abstraction layer —
`_GeminiProvider`, `google.genai.Client`, `neo4j.GraphDatabase`, or a provider object passed
in as a parameter — with a deterministic fake (usually keyed by a CRC of the prompt), so the
real stage logic still runs against fake I/O. **Never verify by re-running a paid stage.**

## Fixtures — why a green run has two meanings

`graph_output/` and `data/` are git-ignored and ship through a **private** Hugging Face
dataset repo, so a clone of this repository cannot obtain them. Arms that read
`all_validated_triples.json` or `resolved_graph.json` therefore used to skip silently: the
suite printed "all pass" while roughly a dozen real checks had never executed.

`test/_fixture_paths.py` closes that. `resolve_artifact("validated"|"resolved")` returns the
**real** artifact when the snapshot is pulled and falls back to the small synthetic graph in
`test/fixtures/` otherwise. Three rules keep this honest:

1. **Real data always wins.** The fixture is a fallback, never an override. There is no env
   var to opt in — one that outsiders would never set would defeat the purpose.
2. **Every affected arm prints `[fixture]` or `[real]`.** `run_all.py` rolls those up, so
   `grep '\[fixture\]'` tells you exactly how much of the suite saw real data. A silent
   substitution would make a green run mean less than it appears to.
3. **Scale assertions refuse the fixture.** Arms asserting real corpus *size*
   (`len(nodes) > 1000`, `claims > 100`, `candidates > 100`, `distinct_kpi_nodes > 100`,
   `max_degree_before > 5000`) call `skip_if_fixture()` and keep skipping. Lowering a
   threshold to make it pass on a 24-node graph would convert a real check into a
   decorative one — do not do it.

`test/fixtures/*.json` are generated, not hand-written. Edit `test/fixtures/build_fixtures.py`
and re-run it; the script validates everything it emits against `config/schema.json` and CI
asserts the committed files still match the generator. Arms needing artifacts *beyond* those
two (`graph_output/graphs/`, labeled JSONL, crosscheck dossiers) still skip — closing those
would need more fixtures than this covers.

Re-run triggers worth memorising:

| after touching | re-run |
| --- | --- |
| step03 / 03b / 03c / 05 / 05b / 05c / 08 | `test_temporal_invariants.py` |
| any `core/` helper, or `report/quality.py` | `test_esg_kg_equivalence.py` |
| `config/schema.json` (any hand edit) | `test_schema_contract.py` |
| `metric/hub.py` or Q7 | `test_quality_hub_set.py` |
| a paid LLM prompt template | that stage's guard: `test_step02_language_guard.py`, `test_step01_step07_language_guard.py`, `test_step03_llm_value_guard.py` |

**Reading note on the per-file comments below**: many were written while `src/` and
`esg_kg` existed side by side, so phrases like "both trees" / "BOTH trees" describe how
that test *proved the migration correct at the time* — importing `src/` as the oracle and
comparing. After `src/` was deleted (2026-07-29), every one of those files (`test_esg_kg_*`,
`test_console_utf8.py`, `test_standards_audit.py`) was converted to a single-tree test
against `esg_kg` alone — same assertions, same non-vacuity guarantees, no `src/` import
left anywhere. Read "both trees" in what follows as history, not as what the test imports
today:

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
python test/test_standards_audit.py        # esg_kg's standards-registry audit (quality.py):
                                           # an uncurated GRI spelling surfaces, an out-of-scope
                                           # accounting standard does NOT (the noise filter that
                                           # makes the section readable), a curated exclusion
                                           # stays closed, and canonical_name is never reported
                                           # as unknown (step04b's old feedback artifact).
                                           # Run after touching step00 or the registry config.
python test/test_pipeline_table.py         # esg_kg stage table (esg_kg/pipeline.py + run.py):
                                           # every old_step label is well-formed and unique
                                           # (src/ is gone, so this no longer checks a real
                                           # file exists — see pipeline.py's own docstring),
                                           # short names don't collide, block members are all
                                           # migrated stages, and a stage that will NEVER be
                                           # ported is rendered as such instead of "not yet"
                                           # (which would keep dead work permanently queued).
python test/test_gri_catalog_build.py      # gri/build_gri_catalog.py: a disclosure is attributed
                                           # to the standard whose id is its prefix (not to whichever
                                           # file sorts first), pillar comes from the source via
                                           # PILLAR_MAP (never a substring guess), provenance fields
                                           # agree with the attributed standard, and GRI 306's real
                                           # 2016+2020 versions still merge. Run after touching gri/.
python test/test_evalu_annotation.py       # evalu/annotation.py score(): the annotation scoring
                                           # used by docs/ANNOTATION_RESULTS.md and the 43-pair
                                           # census behind main.tex S4.4. Run after touching
                                           # evalu/annotation.py or evalu/iaa.py.
python test/test_extract_archives_portable.py  # crawl_data/extract_archives.py stays runnable by
                                           # someone who is not its author: repo-relative defaults,
                                           # argparse overrides, a four-tier archiver lookup
                                           # (flag -> env -> PATH -> per-OS install paths), and
                                           # os.sep rather than a literal backslash.
python test/test_console_utf8.py           # ensure_utf8_stdout in BOTH trees + the WIRING (main()
                                           # actually calls it, nothing calls it at import). Closes
                                           # the hole the equivalence test cannot see: it never
                                           # executes main() or a __main__ block.
python test/test_data_sync_scope.py        # esg_kg.core.datasync pull is scoped to the three
                                           # synced folders, so it can never overwrite a tracked
                                           # repo-root file (that is how the Hub's .gitattributes
                                           # got committed). Offline: snapshot_download is a recorder.
python test/test_esg_kg_datasync.py        # esg_kg.core.datasync (the src/data_sync.py port,
                                           # 2026-07-29 — the last file that blocked deleting
                                           # src/): constants match the documented shape, push/pull
                                           # scoping, status reporting. Offline: huggingface_hub
                                           # calls replaced by recorders, nothing touches the network.
python test/test_esg_kg_equivalence.py     # regression net for esg_kg's core/ helpers and
                                           # quality.py (step00's whole Q1-Q8 surface), run on
                                           # the real schema/corpus against golden values
                                           # captured from esg_kg itself (converted from a
                                           # src/-vs-esg_kg comparison once src/ was proven
                                           # equivalent and then deleted, 2026-07-29). Run
                                           # after ANY edit to a core/ helper, or to
                                           # esg_kg/report/quality.py — real graph with
                                           # --skip-slow, plus a synthetic 20-node graph for
                                           # the 44s Q7 BFS arms.
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
python test/test_step03_llm_value_guard.py # step03 phase 2 may repair a triple's SHAPE
                                           # (class/predicate/temporal fields) but never
                                           # translate/reformat/invent/drop a property VALUE
                                           # (preserve_property_values) — belt-and-braces on
                                           # top of BATCH_FIX_PROMPT now that step02 emits
                                           # Vietnamese name/title (issue #6): an
                                           # English-instructed repair model "fixing" a VN
                                           # name would silently split one entity into two at
                                           # step05. Asserts both behaviour (guard restores/
                                           # drops/permits the right fields) and wiring (a
                                           # stubbed tampering LLM run through the real
                                           # process_all_files, artifact read back). Offline.
                                           # Run after touching step03's BATCH_FIX_PROMPT or
                                           # preserve_property_values.
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
python test/test_step02_language_guard.py  # issue #6: pins that TEMPORAL_GRAPH_PROMPT_TEMPLATE
                                           # and NEWS_GRAPH_PROMPT_TEMPLATE require Vietnamese
                                           # output (name/title/description/free text) and no
                                           # longer model the drift in their own worked examples.
                                           # Prompt-text-only (no runtime guard at step02 itself —
                                           # the consequence-guard already lives at step03,
                                           # preserve_property_values, 046e572); red against the
                                           # unfixed prompt. Run after touching either template.
python test/test_esg_kg_extract_triples.py # same contract as the files above, for the step02
                                           # migration slice (graph/extract_triples) — the 15th
                                           # and FINAL stage. Confirmed leaf: every symbol it
                                           # imports was already lifted (core/io_jsonl, core/llm,
                                           # core/schema, core/identity); the one stage-local
                                           # duplicate, schema_sets(), is deleted in favour of
                                           # core.schema.load_schema_sets(). Unlike step01,
                                           # step02 never constructs its own client — call_llm/
                                           # process_page/process_document all take `client` as a
                                           # plain parameter, so the paid-path stub is a fake
                                           # client object passed in directly, not a genai.Client
                                           # monkeypatch. 12 groups: kernel-reuse identity checks,
                                           # a real-corpus arm (13 documents), both prompt
                                           # templates pinned byte-for-byte (carrying the issue-#6
                                           # language fix), build_page_prompt compared for both
                                           # --source report and --source news, and the paid path
                                           # driven by 4 deterministic response shapes. Run after
                                           # touching step02 or core/io_jsonl.
python test/test_export_kgc.py             # esg_kg.export.export_kgc (GRAPH_IMPROVEMENT_PLAN.md
                                           # B4): reuses metric/hub.py's multi-issuer cluster
                                           # machinery rather than reimplementing hub detection.
                                           # Synthetic 2-issuer fixture proves the property that
                                           # matters for scaling — a bucketed ticker's nodes/edges
                                           # never leak into an untouched ticker's — plus input-
                                           # purity (never mutates nodes/edges in place),
                                           # determinism (two runs, byte-identical output),
                                           # is_synthetic flagging on every new node/edge (P7 —
                                           # a bucket hop carries no source sentence, so it must
                                           # be flagged, not presented as a citable reasoning
                                           # step), and that "HubBucket" never appears in
                                           # config/schema.json (it is a dataset-construction
                                           # artifact, not a T1/T2/T3 entity). Real-corpus arm
                                           # (skips gracefully without the HF snapshot) asserts
                                           # an order-of-magnitude degree reduction AND that
                                           # resolved_graph.json's bytes on disk are unchanged
                                           # after the stage runs — the whole point of the
                                           # export-only design. Run after touching export_kgc
                                           # or metric/hub.py.
python test/test_claim_id_deterministic.py # GitHub issue #2 / plan item C1 — deterministic
                                           # `claim_id`. SustainabilityClaim's identity_keys is
                                           # exactly ["claim_id"] and get_stable_entity_id hashes
                                           # it straight off that property, so while claim_id was
                                           # free text the LLM invented, re-running step02 over the
                                           # same sentence could re-partition every already-paid
                                           # dossier (neo4j_sync resolves claims 100% by stable_id,
                                           # with no fallback tier). Drives
                                           # assign_deterministic_claim_ids /
                                           # make_deterministic_claim_id (graph/extract_triples) on
                                           # synthetic triples AND on the real resolved graph for a
                                           # non-vacuous uniqueness arm: same source sentence ->
                                           # same id despite LLM wording drift, different page ->
                                           # different id, two wordings of one sentence collapse,
                                           # and ONLY SustainabilityClaim is touched. This is the
                                           # test that unblocked the planned full re-extraction.
                                           # Run after touching step02's claim_id assignment or
                                           # core/identity.
python test/test_entities_partial_key_merge.py # plan item B1 — subsumption merge for partially
                                           # filled identity keys. identity_signature() builds its
                                           # tuple from ALL of a class's identity_keys and Stage
                                           # B.1 merges only on a FULL equal tuple, so two mentions
                                           # of one real entity that differ only in which OPTIONAL
                                           # key got extracted (one "Hai Duong" carries a country,
                                           # the other does not) never merge — a dedup miss, not a
                                           # false merge, but 52 Location + 8 Authority duplicates
                                           # measured live. Drives resolve_graph() directly on
                                           # synthetic triples (Stage A/B.1/D need no LLM), not on
                                           # a frozen fixture, so it survives a full re-run.
python test/test_esg_kg_gemini_cache.py    # core/llm.py's GeminiContextCache (issue #11):
                                           # PROVIDER-SIDE explicit context caching for the large
                                           # static prefix (schema.json, or
                                           # kpi_definitions_construction.json) that extract,
                                           # extract_triples and fix_triples otherwise resend
                                           # byte-identically on every call. One wrapper around
                                           # client.caches.create so the three call sites don't
                                           # each reimplement "create once, reuse the handle, never
                                           # let a cache failure break the pipeline". NOT the same
                                           # thing as llm_cache.py's ContentCache below — that one
                                           # skips an identical repeat REQUEST; this one discounts
                                           # a shared PREFIX across different requests.
python test/test_esg_kg_llm_cache.py       # core/llm_cache.py's ContentCache (issue #9): the one
                                           # shared content-addressed cache — sha256 content key,
                                           # JSON persisted, dirty-gated save, corrupt-file-safe
                                           # load — that RepairCache (build_validated, step03
                                           # phase-2 repairs) and AdjudicationCache (build_resolved,
                                           # step05 Stage C verdicts) were refactored onto after
                                           # both grew the identical shape by hand. The "no
                                           # behaviour change" acceptance criterion is that the two
                                           # block tests keep passing UNCHANGED, so it is not
                                           # re-tested here.
python test/test_mentions_facility_edge.py # plan items C2/B2 — MediaReport --mentionsFacility-->
                                           # Facility|Location. schema.json could anchor a
                                           # MediaReport to an Organization or a Product but had no
                                           # way to anchor one to the facility or incident location
                                           # the article actually names; observedAtFacility and
                                           # enforcedBy already covered the KPI/penalty cases, so an
                                           # article with neither had no anchor at all — exactly
                                           # what keeps Q7(e) (T2 conduct-node anchoring) low for
                                           # the MediaReport class.
python test/test_quality_hub_set.py        # plan item A1 — esg_kg/metric/hub.py and its wiring
                                           # into report/quality.py's q7_traversability. "The hub"
                                           # used to mean the single globally-highest-degree node,
                                           # which is correct only by accident with ONE issuer in
                                           # config/issuer_registry.json: once a second company is
                                           # merged in, each issuer forms its own high-degree star,
                                           # so a path routed through issuer B's hub was wrongly
                                           # counted "hub-free". Builds a synthetic 2-issuer graph
                                           # that reproduces exactly that bug and proves the WHOLE
                                           # registry-driven hub set is excluded, not just the
                                           # max-degree node. Run after touching metric/hub.py or
                                           # Q7.
python test/test_reasoning_readiness_metrics.py # plan items A2/A3 —
                                           # esg_kg/metric/reasoning_readiness.py: R1 (masked-edge
                                           # re-derivability within 3 undirected hops), R1' (R1
                                           # with hub nodes barred), R7 (hub-free length-3
                                           # metapaths, support >= 50), R1_trainable (R1 minus
                                           # degenerate relations) and the
                                           # config/degenerate_relations.json loader. Deliberately
                                           # NOT a golden-dict capture like the equivalence tests:
                                           # esg_kg/metric is new code with no src/ original to
                                           # compare against, so the plan asked for a small
                                           # synthetic graph with HAND-COMPUTED answers a reader
                                           # can verify by counting hops on paper. Companion to
                                           # test_quality_hub_set.py, which carries the integration
                                           # arm through quality.py.
python test/test_step01_step07_language_guard.py # same defect shape as issue #6, found by
                                           # auditing every OTHER LLM stage's prompt after
                                           # test_step02_language_guard.py (2026-08-05). step01's
                                           # KPIObservation title/snippet (especially the
                                           # kpi_type="other" fallback, which asked for "a
                                           # descriptive title" with no language constraint at all)
                                           # and step07's rationale are free text that ends up IN
                                           # the graph — rationale is written onto llm_supports /
                                           # llm_contradicts edges, synced by neo4j_sync, and
                                           # rendered in the claim ledger and the Evidence View —
                                           # yet neither prompt required Vietnamese output, only
                                           # noted that the SOURCE text is Vietnamese.
                                           # Prompt-text-only, like the step02 guard.
RUN_LLM_INTEGRATION_TESTS=1 python test/test_esg_kg_integration_llm.py
                                           # COSTS MONEY. The only two files that talk to a real
                                           # provider; both no-op (exit 0, skip message) unless
                                           # their env var is set, so they never run in the normal
                                           # offline sweep. This one exercises the Gemini path
                                           # end-to-end at the seam the stubs fake everywhere else:
                                           # a real _GeminiProvider round trip, real JSON-mode
                                           # response shape, real rate limiting. Run it when the
                                           # provider contract itself is in doubt (SDK bump, model
                                           # switch, a 4xx that the stubs cannot reproduce) — not
                                           # as part of a normal change.
RUN_LLM_SYSTEM_TEST=1 python test/test_esg_kg_system_llm.py
                                           # COSTS MONEY. The wider system arm of the same idea:
                                           # a real end-to-end LLM run rather than a single call.
                                           # Same rule — a deliberate, occasional check, never the
                                           # way you verify an ordinary edit.
```

Manual-validation notebooks live in `notebooks/`. `test/` holds only runnable
assert scripts; `test/test_pdf_extraction.ipynb` was deleted during the public-release
cleanup because it imported an `extraction` package that has not existed for some time.
