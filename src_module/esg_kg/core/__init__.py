"""core — the shared kernel extracted from step01/02/03/04.

These helpers are currently trapped INSIDE pipeline-stage files, so every later
stage imports them from a sibling step (e.g. ``from step03_... import
load_schema_sets``). That step->step coupling is what makes "refactor one step
at a time" impossible today. Extracting them here is the FIRST refactor move;
after it, each stage depends only on ``esg_kg.core`` and can be moved alone.

Planned submodules (each line = symbols to move + where they live now):

    paths.py      REPO_ROOT, DEFAULT_* dirs           <- step01:36-44
    io_jsonl.py   load_pages_from_jsonl, build_page_text, page_has_esg
                                                       <- step01:97-124
    schema.py     load_schema_sets, validate_triple   <- step03:150,260
                  get_identity_keys                    <- step02:100
    naming.py     normalize_name, name_tokens,
                  merge_preserving_edits               <- step04:138,158,399
    dates.py      date_start_key (+ ISO canonicalize)  <- step03:130
    identity.py   parse_source_id                      <- step03b:98
                  PROVENANCE_CLASSES, stable_id        <- step02
    text.py       node_text  (DEDUPE: defined twice,   <- step05d:63 AND step07:133)
    llm.py        RateLimiter                          <- step02:70
                  _Provider / _OpenAIProvider cascade  <- step07:284
    datasync.py   data_sync.py (HF snapshot pull/push) <- src/data_sync.py
"""
