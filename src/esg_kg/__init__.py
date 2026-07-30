"""esg_kg — Graph-RAG greenwashing-detection pipeline (module refactor of src/).

This package is the modular re-home of the flat ``src/step*.py`` scripts.
It is populated INCREMENTALLY: one stage is moved from ``src/`` at a time, its
shared helpers pulled into ``esg_kg.core`` so later stages import from a stable
kernel instead of from a sibling step file.

See DESIGN.md for the full layout and the old-file -> new-module mapping,
and pipeline.py for the canonical run order (the stepNN ordering, preserved).

NOTE: the package name ``esg_kg`` is a suggestion — rename freely before you
start moving code (it appears only here and in DESIGN.md/pipeline.py).
"""
