"""load — pushing the resolved graph and the advisory layer into Neo4j.

    neo4j_load.py  <- step06_load_graph_to_neo4j.py        (base property graph)
    neo4j_sync.py  <- step08_sync_crosscheck_to_neo4j.py   (advisory assessment layer)

NOTE: named ``load`` (not ``neo4j``) on purpose — the repo already has a
top-level ``neo4j/`` dir of .cypher files; a package named ``neo4j`` would also
shadow the neo4j driver import.
"""
