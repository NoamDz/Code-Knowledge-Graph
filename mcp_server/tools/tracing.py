"""Tracing tools: endpoint tracing, call chain traversal."""

from __future__ import annotations

from ..query_engine import QueryEngine

# OpenResty phase execution order
PHASE_ORDER = [
    "init", "init_worker", "ssl_certificate", "ssl_session_fetch",
    "ssl_session_store", "set", "rewrite", "access",
    "content", "header_filter", "body_filter", "log",
]


def trace_endpoint(engine: QueryEngine, endpoint_path: str, max_depth: int = 6) -> str:
    """Trace the complete code path for an HTTP endpoint."""
    # Get phases for this endpoint
    phases = engine.query("""
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(phase:NginxPhase)
        OPTIONAL MATCH (phase)-[:HANDLES]->(f:File)
        RETURN phase.phase_type AS phase, phase.lua_file AS lua_file,
               phase.is_inline AS is_inline, f.path AS file_path
        ORDER BY phase.phase_type
    """, endpoint=endpoint_path)

    if not phases:
        return f"No endpoint found for '{endpoint_path}'"

    # Sort by phase execution order
    def phase_sort_key(p):
        phase = p.get("phase", "")
        return PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 99

    phases.sort(key=phase_sort_key)

    lines = [f"Endpoint trace: {endpoint_path}"]
    lines.append(f"Phases ({len(phases)}):")

    for p in phases:
        phase = p["phase"]
        lua_file = p.get("lua_file") or p.get("file_path") or "(inline)"
        lines.append(f"  [{phase}] → {lua_file}")

        # Trace calls from this file
        if lua_file and lua_file != "(inline)":
            calls = engine.query("""
                MATCH path = (fn:Function {file: $file})-[:CALLS*1..$depth]->(called:Function)
                RETURN fn.name AS from_func,
                       [node in nodes(path) | node.name] AS chain,
                       [node in nodes(path) | node.file] AS files
                LIMIT 20
            """, file=lua_file, depth=max_depth)

            if calls:
                for c in calls[:5]:
                    chain = " → ".join(c["chain"])
                    lines.append(f"    {chain}")

    return "\n".join(lines)


def find_all_callers(engine: QueryEngine, function_name: str) -> str:
    """Find every function that calls the given function."""
    results = engine.query("""
        MATCH (caller:Function)-[:CALLS]->(fn:Function)
        WHERE fn.name CONTAINS $name
        RETURN caller.name AS caller, caller.file AS file, fn.name AS callee
        ORDER BY caller.file
    """, name=function_name)

    if not results:
        return f"No callers found for '{function_name}'"

    lines = [f"Callers of '{function_name}' ({len(results)}):"]
    for r in results:
        lines.append(f"  {r['caller']} in {r['file']}")
    return "\n".join(lines)
