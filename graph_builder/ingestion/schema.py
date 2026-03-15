"""Graph schema: Memgraph indexes and type definitions.

Run create_indexes() once against a fresh Memgraph instance to set up
the schema. These are idempotent — safe to re-run.
"""

from __future__ import annotations


# Cypher statements to create indexes
INDEX_STATEMENTS = [
    "CREATE INDEX ON :File(path);",
    "CREATE INDEX ON :Module(name);",
    "CREATE INDEX ON :Function(name);",
    "CREATE INDEX ON :Class(name);",
    "CREATE INDEX ON :Endpoint(path);",
    "CREATE INDEX ON :NginxPhase(phase_type);",
    "CREATE INDEX ON :ContextKey(name);",
    "CREATE INDEX ON :SharedDict(name);",
    "CREATE INDEX ON :RedisKey(name);",
    "CREATE INDEX ON :SharedFile(path);",
]

# Node labels and their key properties
NODE_TYPES = {
    "File": ["path", "language", "last_indexed"],
    "Module": ["name", "file", "pattern_type"],
    "Function": ["name", "file", "line", "line_end", "visibility", "is_method"],
    "Class": ["name", "file", "line", "line_end", "parent_class"],
    "Endpoint": ["path", "method"],
    "NginxPhase": ["phase_type", "endpoint", "lua_file", "is_inline"],
    "ContextKey": ["name"],
    "SharedDict": ["name"],
    "RedisKey": ["name"],
    "SharedFile": ["path"],
}

# Edge types and their properties
EDGE_TYPES = {
    "IMPORTS": ["module"],
    "DEFINES": [],
    "CALLS": ["line", "is_pcall"],
    "HANDLES": [],
    "HAS_PHASE": [],
    "EXTENDS": [],
    "INCLUDES": [],
    "REQUIRES": ["module"],
    "EXPORTS": [],
    "CTX_WRITES": ["function", "line"],
    "CTX_READS": ["function", "line"],
    "USES_SHARED": ["operation", "function", "line"],
    "REROUTES_TO": ["redirect_type", "line"],
    "REDIS_READS": ["operation", "line"],
    "REDIS_WRITES": ["operation", "line"],
    "HTTP_CALLS": ["method", "line"],
}


def create_indexes(session) -> list[str]:
    """Run all CREATE INDEX statements. Returns list of executed statements."""
    executed = []
    for stmt in INDEX_STATEMENTS:
        try:
            session.run(stmt)
            executed.append(stmt)
        except Exception as e:
            # Index may already exist — that's fine
            if "already exists" not in str(e).lower():
                raise
            executed.append(f"{stmt} (already exists)")
    return executed
