"""Canonical run order for the pipeline (stage C of the whole system).

This preserves the information the ``stepNN_`` filename prefixes used to encode, back
when `src/` held one file per stage. `src/` is gone (deleted 2026-07-29, refactor
complete — DESIGN.md §7): the ``old_step`` field is now a historical label only (it is
what `run.py <old_id>` still resolves by, e.g. ``run.py 05b``), not a live file-existence
check. Pure data — no imports of stage code.

Each entry: (order, old_step, new_module, note). ``order`` is the run sequence;
'b'/'c'/'d' suffixes are offline patches that must run right after their base.
"""

STAGES = [
    ("00",  "step00_graph_quality_report",        "esg_kg.report.quality",           "offline Q1-Q8 snapshot; run before AND after any change"),
    ("01",  "step01_extract_kpi_from_jsonl",       "esg_kg.kpi.extract",              "LLM"),
    ("02",  "step02_extract_triplet_from_jsonl",   "esg_kg.graph.extract_triples",    "LLM; --source report|news"),
    ("03",  "step03_fix_invalid_triplets",         "esg_kg.graph.fix_triples",        "validate + repair + aggregate"),
    ("03b", "step03b_anchor_kpi_facilities",       "esg_kg.graph.anchor_kpi",         "offline; after 03, before 03c"),
    ("03c", "step03c_canonicalize_kpis",           "esg_kg.kpi.canonicalize",         "offline; after 03b, before 04"),
    ("04",  "step04_build_issuer_registry",        "esg_kg.registry.issuer",          "run-once bootstrap; writes a TRACKED, hand-edited config file"),
    ("05",  "step05_resolve_entities",             "esg_kg.resolve.entities",         "entity resolution; migrated 2026-07-29 (14th stage) — also runnable as part of the build_resolved block"),
    ("05b", "step05b_stamp_provenance",            "esg_kg.resolve.provenance",       "offline; after 05"),
    ("05c", "step05c_link_standard_indicators",    "esg_kg.resolve.indicators",       "offline; after 05b"),
    ("05d", "step05d_align_claims_to_indicators",  "esg_kg.resolve.align_claims",     "OPTIONAL LLM; after 05c"),
    ("06",  "step06_load_graph_to_neo4j",          "esg_kg.load.neo4j_load",          "needs Neo4j running"),
    ("07",  "step07_crosscheck_claims_vs_conduct", "esg_kg.crosscheck.claims_vs_conduct",
     "LLM adjudication (mandatory); migrating it unblocks 08 (node_text)"),
    ("08",  "step08_sync_crosscheck_to_neo4j",     "esg_kg.load.neo4j_sync",          "advisory layer -> Neo4j; first Neo4j-touching stage migrated"),
    ("09",  "step09_report_claim_ledger",          "esg_kg.report.claim_ledger",      "Neo4j-only; run after 08"),
    ("11",  "step11_export_kgc_hub_decomposition", "esg_kg.export.export_kgc",
     "offline; hub-cluster decomposition for an SSRL export view ONLY — never patches "
     "resolved_graph.json/Neo4j (P6 boundary); this is only the hub-decomposition piece "
     "of the future SSRL step11, not its full design; run after build_resolved"),
]

# Three stages that were never ported and have NO row here — all REMOVED outright, not
# merely unported, so there is nothing left for a STAGES row to point at:
#   step10 (P6 evaluation report) — removed 2026-07-28: the project dropped this style of
#     measurement (coverage/case-study/ablation without ground truth) as a deliverable
#     outright, no replacement mechanism. DESIGN.md §4.3, PIPELINE.md §4.
#   step04b (standards-registry reseed) — removed 2026-07-29 with `src/`: it read step05's
#     output while step05 read its output (a cycle), and the scan earned nothing (every
#     alias was a hardcoded seed). config/standards_registry.json stays static config;
#     step00's `standards_registry_audit` is what replaced its coverage-checking role.
#     Rebuilding it from scratch now means hand-editing the JSON, not running a script.
#   step07b (softmax evidence-balance scores) — removed 2026-07-29 with `src/`: nothing on
#     the delivered UI surface ever read `assessment_scores`/`score_components`; the
#     categorical `assessment` from step07 was always the primary output
#     (docs/SYSTEM_DESIGN.md §1.1 — no ground truth exists for a greenwashing probability).

# --------------------------------------------------------------------------- #
# BLOCKS — several stages collapsed into ONE unit that writes its artifact once.
#
# Each entry: (name, module, member step ids, note).
#
# A block is NOT a stage: it has no `old_step` label of its own, and its member stages
# stay individually runnable, which is why it lives in its own table instead of as a
# STAGES row. Blocks were `esg_kg`'s redesign against `src/`'s three-separate-stages
# shape while `src/` still existed (Model A, now historical — DESIGN.md §7).
#
# The rule that produces a block (DESIGN.md §5.7): when N stages each read AND write
# the same artifact, they are not N stages, they are one. The intermediate file is
# internal state that leaked into being a contract, and re-running the first stage
# silently destroys what the later ones added — including results that were paid for.
#
# Member stages stay individually runnable. A block ADDS an entry point; it never
# removes the per-stage ones, or the ability to diagnose one stage alone goes too.
BLOCKS = [
    ("build_validated", "esg_kg.graph.build_validated", ("03", "03b", "03c"),
     "03 -> 03b -> 03c in memory, writing all_validated_triples.json ONCE; phase-2 "
     "repairs are cached so a re-run is free and deterministic (DESIGN.md §5.7)"),
    ("build_resolved", "esg_kg.resolve.build_resolved", ("05", "05b", "05c"),
     "05 -> 05b -> 05c in memory, writing resolved_graph.json ONCE; Stage C entity "
     "adjudication is cached (Stage B embeddings are not — see build_resolved.py "
     "docstring). 05d (align_claims) stays a separate, optional, post-block LLM "
     "stage, unchanged (DESIGN.md §5.7)"),
]

# data_sync is a utility, not a pipeline stage: esg_kg.core.datasync
# (moved from src/data_sync.py 2026-07-29, the last file blocking src/ deletion)
