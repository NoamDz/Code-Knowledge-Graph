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
    """Trace the complete code path for an HTTP endpoint, following internal reroutes."""
    visited: set[str] = set()
    all_lines: list[str] = []

    def _trace_single(ep_path: str, depth: int = 0):
        if ep_path in visited or depth > 5:
            return
        visited.add(ep_path)

        indent = "  " * depth

        # Get phases for this endpoint
        phases = engine.query("""
            MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(phase:NginxPhase)
            OPTIONAL MATCH (phase)-[:HANDLES]->(f:File)
            RETURN phase.phase_type AS phase, phase.lua_file AS lua_file,
                   phase.is_inline AS is_inline, f.path AS file_path
            ORDER BY phase
        """, endpoint=ep_path)

        if not phases:
            all_lines.append(f"{indent}Endpoint: {ep_path} (no phases found)")
            return

        # Sort by phase execution order
        def phase_sort_key(p):
            phase = p.get("phase", "")
            return PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 99
        phases.sort(key=phase_sort_key)

        all_lines.append(f"{indent}Endpoint: {ep_path}")
        all_lines.append(f"{indent}Phases ({len(phases)}):")

        for p in phases:
            phase = p["phase"]
            lua_file = p.get("lua_file") or p.get("file_path") or "(inline)"
            all_lines.append(f"{indent}  [{phase}] → {lua_file}")

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
                        all_lines.append(f"{indent}    {chain}")

        # Follow REROUTES_TO edges from functions in this endpoint's files
        reroutes = engine.query("""
            MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
            MATCH (fn:Function {file: f.path})-[r:REROUTES_TO]->(target:Endpoint)
            RETURN DISTINCT target.path AS target_path, r.redirect_type AS redirect_type,
                   fn.name AS from_function
        """, endpoint=ep_path)

        if reroutes:
            all_lines.append(f"{indent}  Internal reroutes:")
            for r in reroutes:
                all_lines.append(f"{indent}    {r['from_function']} --[{r['redirect_type']}]--> {r['target_path']}")
                _trace_single(r["target_path"], depth + 1)

        # Follow HTTP_CALLS edges
        http_calls = engine.query("""
            MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
            MATCH (fn:Function {file: f.path})-[r:HTTP_CALLS]->(target:Endpoint)
            RETURN DISTINCT target.path AS target_path, r.method AS method,
                   fn.name AS from_function
        """, endpoint=ep_path)

        if http_calls:
            all_lines.append(f"{indent}  HTTP calls:")
            for h in http_calls:
                all_lines.append(f"{indent}    {h['from_function']} --[{h['method']}]--> {h['target_path']}")

    _trace_single(endpoint_path)

    if not all_lines:
        return f"No endpoint found for '{endpoint_path}'"

    return "\n".join(all_lines)


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
