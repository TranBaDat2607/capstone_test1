"""registry — run-once bootstrap registries (anchors for entity resolution).

    issuer.py      <- step04_build_issuer_registry.py      (issuer name variants) — MIGRATED 2026-07-28

`config/standards_registry.json` is now static config (DESIGN.md §4.2, decided 2026-07-26):
step04b that used to (re)generate it is deliberately NOT ported — it read step05's output
while step05 read its output, a dependency cycle. There is therefore no `standards.py` to
add here; step00's `standards_registry_audit` covers what step04b's scan used to do.
"""
