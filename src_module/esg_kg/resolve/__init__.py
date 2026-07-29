"""resolve — entity resolution and the offline patches layered on top of it.

    entities.py      <- step05_resolve_entities.py            (Stage A-D dedup/merge; DSU, consolidate)
    provenance.py    <- step05b_stamp_provenance.py           (source_doc/source_page stamping)
    indicators.py    <- step05c_link_standard_indicators.py   (TT96/GRI indicator axis; GraphPatch)
    align_claims.py  <- step05d_align_claims_to_indicators.py (OPTIONAL LLM claim->indicator)
"""
