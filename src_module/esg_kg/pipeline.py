"""Canonical run order for the pipeline (stage C of the whole system).

This preserves the information the ``stepNN_`` filename prefixes used to encode,
now that modules are grouped by role instead of numbered. Pure data — no imports
of stage code — so it stays importable while the package is half-migrated.

Each entry: (order, old_step, new_module, note). ``order`` is the run sequence;
'b'/'c'/'d' suffixes are offline patches that must run right after their base.

``new_module`` is ``None`` for a stage that is deliberately NOT being ported. That is a
decision, not a backlog item, and the distinction is load-bearing: ``run.py --list`` would
otherwise render it as merely "not yet migrated" and keep dead work on the queue forever.
The row itself stays, because the stage still exists and still runs from ``src/`` — its
position in the run order is real knowledge that would be lost by deleting the line.
"""

STAGES = [
    ("00",  "step00_graph_quality_report",        "esg_kg.report.quality",           "offline Q1-Q8 snapshot; run before AND after any change"),
    ("01",  "step01_extract_kpi_from_jsonl",       "esg_kg.kpi.extract",              "LLM"),
    ("02",  "step02_extract_triplet_from_jsonl",   "esg_kg.graph.extract_triples",    "LLM; --source report|news"),
    ("03",  "step03_fix_invalid_triplets",         "esg_kg.graph.fix_triples",        "validate + repair + aggregate"),
    ("03b", "step03b_anchor_kpi_facilities",       "esg_kg.graph.anchor_kpi",         "offline; after 03, before 03c"),
    ("03c", "step03c_canonicalize_kpis",           "esg_kg.kpi.canonicalize",         "offline; after 03b, before 04"),
    ("04",  "step04_build_issuer_registry",        "esg_kg.registry.issuer",          "run-once bootstrap; writes a TRACKED, hand-edited config file"),
    ("04b", "step04b_build_standards_registry",    None,                                  "NOT PORTED by decision (2026-07-26): it read step05's output while step05 read its output — a cycle. config/standards_registry.json is static config now and step00 audits its coverage; src/ keeps the file for a from-scratch reseed"),
    ("05",  "step05_resolve_entities",             "esg_kg.resolve.entities",         "entity resolution; migrated 2026-07-29 (14th stage) — also runnable as part of the build_resolved block"),
    ("05b", "step05b_stamp_provenance",            "esg_kg.resolve.provenance",       "offline; after 05"),
    ("05c", "step05c_link_standard_indicators",    "esg_kg.resolve.indicators",       "offline; after 05b"),
    ("05d", "step05d_align_claims_to_indicators",  "esg_kg.resolve.align_claims",     "OPTIONAL LLM; after 05c"),
    ("06",  "step06_load_graph_to_neo4j",          "esg_kg.load.neo4j_load",          "needs Neo4j running"),
    ("07",  "step07_crosscheck_claims_vs_conduct", "esg_kg.crosscheck.claims_vs_conduct",
     "LLM adjudication (mandatory); migrating it unblocks 08 (node_text)"),
    ("07b", "step07b_enrich_dossiers",             None,                                  "offline softmax scores — NOT PORTED by decision (2026-07-25): nothing on the delivered surface reads them; stays runnable in src/"),
    ("08",  "step08_sync_crosscheck_to_neo4j",     "esg_kg.load.neo4j_sync",          "advisory layer -> Neo4j; first Neo4j-touching stage migrated"),
    ("09",  "step09_report_claim_ledger",          "esg_kg.report.claim_ledger",      "Neo4j-only; run after 08"),
]

# step10 (P6 evaluation report) is REMOVED, not merely unported — decided 2026-07-28: the
# project dropped this style of measurement (coverage/case-study/ablation without ground
# truth) as a deliverable outright, no replacement mechanism. Unlike 04b/07b it has no row
# here and no src/ file: a STAGES row must point at a real file, and this one no longer
# exists. See src_module/esg_kg/DESIGN.md §4.3 and src_module/PIPELINE.md §4 for the record.

# --------------------------------------------------------------------------- #
# BLOCKS — several stages collapsed into ONE unit that writes its artifact once.
#
# Each entry: (name, module, member step ids, note).
#
# A block is NOT a stage and deliberately has NO `src/` counterpart: `src/` keeps the
# stages separate for ever (Model A), while `esg_kg` is allowed to redesign the shape.
# That is why blocks live in their own table instead of as STAGES rows — a STAGES row
# must point at a real `src/` file, and a block never can.
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
]

# data_sync is a utility, not a pipeline stage:
#   src/data_sync.py -> esg_kg.core.datasync
