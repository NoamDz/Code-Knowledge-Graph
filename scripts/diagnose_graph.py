"""Inspect the current Memgraph graph to classify MCP-tool failures.

Run on the machine with the built graph:
    python scripts/diagnose_graph.py

The output answers: are File paths absolute? how many Function nodes lack a
line? are there Endpoint nodes? do CALLS edges connect Function->Function? are
Go functions present? how are method names stored (X:save vs X.save vs save)?
Those facts decide, per the fix plan, whether each broken tool is a query bug
or a data gap.
"""
from __future__ import annotations

from mcp_server.query_engine import QueryEngine

QUERIES = [
    ("node labels",       "MATCH (n) RETURN labels(n)[0] AS k, count(*) AS c ORDER BY c DESC"),
    ("edge types",        "MATCH ()-[r]->() RETURN type(r) AS k, count(*) AS c ORDER BY c DESC"),
    ("file path samples", "MATCH (f:File) RETURN f.path AS path LIMIT 5"),
    ("function line cov",
     "MATCH (n:Function) RETURN count(*) AS total, "
     "sum(CASE WHEN n.line IS NULL THEN 1 ELSE 0 END) AS null_line"),
    ("endpoint count",    "MATCH (e:Endpoint) RETURN count(*) AS c"),
    ("endpoint samples",  "MATCH (e:Endpoint) RETURN e.path AS path LIMIT 10"),
    ("CALLS endpoints",
     "MATCH (a)-[:CALLS]->(b) RETURN labels(a)[0] AS from_l, labels(b)[0] AS to_l, "
     "count(*) AS c ORDER BY c DESC LIMIT 10"),
    ("IMPORTS count",     "MATCH (:File)-[:IMPORTS]->() RETURN count(*) AS c"),
    ("REQUIRES count",    "MATCH (:File)-[:REQUIRES]->() RETURN count(*) AS c"),
    ("go function cov",
     "MATCH (f:File {language:'go'}) OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function) "
     "RETURN count(DISTINCT f) AS go_files, count(fn) AS go_funcs"),
    ("name format: save",
     "MATCH (n:Function) WHERE n.name CONTAINS 'save' RETURN n.name AS name LIMIT 15"),
]


def main() -> None:
    engine = QueryEngine()  # reads MEMGRAPH_URI itself, defaulting to bolt://localhost:7687
    try:
        for title, cypher in QUERIES:
            print(f"\n=== {title} ===")
            try:
                rows = engine.query(cypher)
                if not rows:
                    print("   (no rows)")
                for row in rows:
                    print("  ", dict(row))
            except Exception as exc:  # keep going so one bad query doesn't abort the report
                print("   ERROR:", exc)
    finally:
        engine.close()


if __name__ == "__main__":
    main()
