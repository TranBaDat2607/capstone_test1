"""Canonical run order for the pipeline (stage C of the whole system).

This preserves the information the ``stepNN_`` filename prefixes used to encode,
now that modules are grouped by role instead of numbered. Pure data — no imports
of stage code — so it stays importable while the package is half-migrated.

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
    ("04",  "step04_build_issuer_registry",        "esg_kg.registry.issuer",          "run-once bootstrap"),
    ("04b", "step04b_build_standards_registry",    "esg_kg.registry.standards",       "run-once bootstrap"),
    ("05",  "step05_resolve_entities",             "esg_kg.resolve.entities",         "entity resolution"),
    ("05b", "step05b_stamp_provenance",            "esg_kg.resolve.provenance",       "offline; after 05"),
    ("05c", "step05c_link_standard_indicators",    "esg_kg.resolve.indicators",       "offline; after 05b"),
    ("05d", "step05d_align_claims_to_indicators",  "esg_kg.resolve.align_claims",     "OPTIONAL LLM; after 05c"),
    ("06",  "step06_load_graph_to_neo4j",          "esg_kg.load.neo4j_load",          "needs Neo4j running"),
    ("07",  "step07_crosscheck_claims_vs_conduct", "esg_kg.crosscheck.claims_vs_conduct", "LLM adjudication (mandatory)"),
    ("07b", "step07b_enrich_dossiers",             "esg_kg.crosscheck.enrich_dossiers",   "offline softmax scores"),
    ("08",  "step08_sync_crosscheck_to_neo4j",     "esg_kg.load.neo4j_sync",          "advisory layer -> Neo4j"),
    ("09",  "step09_report_claim_ledger",          "esg_kg.report.claim_ledger",      "Neo4j-only; run after 08"),
    ("10",  "step10_evaluate",                     "esg_kg.report.evaluate",          "P6 evaluation report"),
]

# data_sync is a utility, not a pipeline stage:
#   src/data_sync.py -> esg_kg.core.datasync
