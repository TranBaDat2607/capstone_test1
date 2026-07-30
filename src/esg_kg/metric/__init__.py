"""metric — hub-cluster identification and reasoning-readiness measurements.

Pure functions consumed by `esg_kg.report.quality` (step00), added for
GRAPH_IMPROVEMENT_PLAN.md Group A. Not a pipeline stage: nothing here reads or
writes a pipeline artifact directly, so `report/quality.py`'s documented
invariant ("this stage depends on no other stage") is unaffected by importing
from this package, the same way it already depends on `esg_kg.core`.

    hub.py                  issuer-cluster hub identification (A1)
    reasoning_readiness.py  R1 / R1' / R7 / R1_trainable (A2) + degenerate
                             relation filtering (A3)
"""
