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
    "CREATE INDEX ON :Service(name);",
    "CREATE INDEX ON :UnixSocket(path);",
    "CREATE INDEX ON :SQSQueue(name);",
    "CREATE INDEX ON :KinesisStream(name);",
    "CREATE INDEX ON :SharedRedisPattern(pattern);",
    "CREATE INDEX ON :ConfigFile(name);",
    "CREATE INDEX ON :DatabaseTable(name);",
    "CREATE INDEX ON :SharedDataStructure(name);",
    "CREATE INDEX ON :SharedConstant(name);",
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
    "Service": ["name", "type", "socket_path"],
    "UnixSocket": ["path", "protocol"],
    "SQSQueue": ["name"],
    "KinesisStream": ["name"],
    "SharedRedisPattern": ["pattern"],
    "ConfigFile": ["name"],
    "DatabaseTable": ["name"],
    "SharedDataStructure": ["name", "fields", "serialization_format"],
    "SharedConstant": ["name", "values"],
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
    "PROXIES_TO": ["upstream_name"],
    "DISPATCHES": ["task", "line"],
    "SOCKET_LISTENS": [],
    "SOCKET_CONNECTS": [],
    "WRITES_REDIS_PATTERN": [],
    "READS_REDIS_PATTERN": [],
    "QUERIES_DB": ["db_type", "operation", "table"],
    "QUERIES_CASSANDRA": ["operation"],
    "PRODUCES_TO": ["operation"],
    "CONSUMES_FROM": ["operation"],
    "STREAMS_TO": ["operation"],
    "ACCESSES_S3": ["operation"],
    "READS_CONFIG": [],
    "DEFINES_SHARED_STRUCTURE": ["language", "field_count"],
    "DEFINES_CONSTANT": ["language"],
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
