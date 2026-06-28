"""Tracing tools: endpoint tracing, call chain traversal."""

from __future__ import annotations

from ..query_engine import QueryEngine
from .endpoint_match import resolve_endpoint, extract_chain

# OpenResty phase execution order
PHASE_ORDER = [
    "init", "init_worker", "ssl_certificate", "ssl_session_fetch",
    "ssl_session_store", "set", "rewrite", "access",
    "content", "header_filter", "body_filter", "log",
]


def resolve_endpoint_path(engine: QueryEngine, endpoint: str) -> str:
    """Map a concrete request URL to a stored Endpoint.path.

    Exact node match wins; otherwise fall back to nginx regex-location matching
    (regex locations are stored verbatim, so '=' lookups never hit them).
    Returns the original string when nothing matches.
    """
    exact = engine.query(
        "MATCH (e:Endpoint {path: $p}) RETURN e.path AS path LIMIT 1", p=endpoint
    )
    if exact:
        return endpoint
    rows = engine.query("MATCH (e:Endpoint) RETURN e.path AS path")
    matched = resolve_endpoint(endpoint, [r["path"] for r in rows if r.get("path")])
    return matched or endpoint


def trace_endpoint(engine: QueryEngine, endpoint_path: str, max_depth: int = 6) -> str:
    """Trace the complete code path for an HTTP endpoint, following internal reroutes."""
    endpoint_path = resolve_endpoint_path(engine, endpoint_path)
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
                # Cypher cannot parameterize variable-length bounds; clamp + interpolate.
                _d = max(1, min(int(max_depth), 6))
                calls = engine.query(f"""
                    MATCH path = (fn:Function {{file: $file}})-[:CALLS*1..{_d}]->(called:Function)
                    RETURN nodes(path) AS ns
                    LIMIT 20
                """, file=lua_file)

                if calls:
                    for c in calls[:5]:
                        names, _files = extract_chain(c["ns"])
                        chain = " → ".join(n for n in names if n)
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

        delegations = engine.query("""
            MATCH (e:Endpoint {path: $endpoint})-[:DELEGATES_TO]->(t:Endpoint)
            RETURN DISTINCT t.path AS target
        """, endpoint=ep_path)
        if delegations:
            all_lines.append(f"{indent}  Delegates to (try_files):")
            for d in delegations:
                all_lines.append(f"{indent}    --> {d['target']}")
                _trace_single(d["target"], depth + 1)

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
        ORDER BY file
    """, name=function_name)

    if not results:
        return f"No callers found for '{function_name}'"

    lines = [f"Callers of '{function_name}' ({len(results)}):"]
    for r in results:
        lines.append(f"  {r['caller']} in {r['file']}")
    return "\n".join(lines)
