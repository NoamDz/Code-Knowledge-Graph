"""Composite tools: task-shaped answers built from multiple Cypher queries.

Design: see /DESIGN.md. These are the agent-facing surface. Each composite
accepts escape_hatch=True to return primitive output when heuristics hide
something the agent needs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..query_engine import QueryEngine
from . import impact as impact_tools
from . import tracing as tracing_tools


# ---------------------------------------------------------------------------
# Middleware filtering — substring rules + ngx.ctx state-key heuristic
# ---------------------------------------------------------------------------

_DEFAULT_MIDDLEWARE_FILE_SUBSTRINGS = ("middleware", "filter", "/common/", "/shared/auth")
_DEFAULT_MIDDLEWARE_FUNC_SUBSTRINGS = ("authenticate", "authorize", "log_request", "rate_limit")

_config_cache: dict | None = None
_state_mw_cache: set[tuple[str, str]] | None = None


def _load_config_middleware() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve middleware substring rules. Precedence: env vars > config.yml > defaults."""
    global _config_cache

    file_env = os.environ.get("CODE_GRAPH_MIDDLEWARE_FILES")
    func_env = os.environ.get("CODE_GRAPH_MIDDLEWARE_FUNCTIONS")
    if file_env is not None or func_env is not None:
        files = tuple(s.strip() for s in (file_env or "").split(",") if s.strip()) or _DEFAULT_MIDDLEWARE_FILE_SUBSTRINGS
        funcs = tuple(s.strip() for s in (func_env or "").split(",") if s.strip()) or _DEFAULT_MIDDLEWARE_FUNC_SUBSTRINGS
        return files, funcs

    if _config_cache is None:
        cfg_path = os.environ.get("CODE_GRAPH_CONFIG", "config.yml")
        try:
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f) or {}
        except (FileNotFoundError, OSError, ImportError):
            _config_cache = {}

    files = tuple(_config_cache.get("middleware_files") or _DEFAULT_MIDDLEWARE_FILE_SUBSTRINGS)
    funcs = tuple(_config_cache.get("middleware_functions") or _DEFAULT_MIDDLEWARE_FUNC_SUBSTRINGS)
    return files, funcs


def _is_middleware_substring(file_path: str | None, func_name: str | None) -> bool:
    files, funcs = _load_config_middleware()
    if file_path and any(s in file_path for s in files):
        return True
    if func_name and any(s in func_name for s in funcs):
        return True
    return False


def _state_key_middleware(engine: QueryEngine) -> set[tuple[str, str]]:
    """ngx.ctx state-key heuristic: a function counts as middleware if every
    ctx key it writes is read by another function and it has no other
    side-effect outputs (HTTP_CALLS / REDIS_WRITES / REROUTES_TO).

    Cached per process — the result is a function of graph state and only
    invalidates when the graph is rebuilt.
    """
    global _state_mw_cache
    if _state_mw_cache is not None:
        return _state_mw_cache

    try:
        rows = engine.query("""
            MATCH (fn:Function)-[:CTX_WRITES]->(k:ContextKey)
            WITH fn, k
            OPTIONAL MATCH (other:Function)-[:CTX_READS]->(k)
            WHERE other <> fn
            WITH fn, k, count(other) AS readers
            WITH fn,
                 count(k) AS total_keys,
                 sum(CASE WHEN readers > 0 THEN 1 ELSE 0 END) AS consumed_keys
            WHERE total_keys > 0 AND total_keys = consumed_keys
            WITH fn
            OPTIONAL MATCH (fn)-[r:HTTP_CALLS|REDIS_WRITES|REROUTES_TO]->()
            WITH fn, count(r) AS side_effects
            WHERE side_effects = 0
            RETURN fn.file AS file, fn.name AS name
        """)
        _state_mw_cache = {(r["file"], r["name"]) for r in rows if r.get("name")}
    except Exception:
        # Schema may not have ctx edges (non-OpenResty repos); skip silently.
        _state_mw_cache = set()
    return _state_mw_cache


def _is_middleware(engine: QueryEngine, file_path: str | None, func_name: str | None) -> bool:
    if _is_middleware_substring(file_path, func_name):
        return True
    if file_path and func_name and (file_path, func_name) in _state_key_middleware(engine):
        return True
    return False


# ---------------------------------------------------------------------------
# explain_flow
# ---------------------------------------------------------------------------

def explain_flow(engine: QueryEngine, endpoint: str, escape_hatch: bool = False) -> str:
    """Phase chain + call graph + reroutes + HTTP calls for an HTTP endpoint.

    Honors Phase-1 task-fit rows: cross-service tracing + endpoint comprehension.
    With escape_hatch=False (default), middleware is collapsed by substring rules
    and the ngx.ctx state-key heuristic.
    With escape_hatch=True, returns the raw call-centric trace including middleware.
    """
    if escape_hatch:
        raw = tracing_tools.trace_endpoint(engine, endpoint, max_depth=6)
        cross = impact_tools.trace_cross_service_flow(engine, endpoint)
        return f"{raw}\n\n--- cross-service (raw) ---\n{cross}"

    phases = engine.query("""
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(p:NginxPhase)
        OPTIONAL MATCH (p)-[:HANDLES]->(f:File)
        RETURN p.phase_type AS phase, p.lua_file AS lua_file,
               p.is_inline AS is_inline, f.path AS file_path
    """, endpoint=endpoint)

    if not phases:
        return f"Endpoint '{endpoint}' not found in graph."

    phases.sort(key=lambda p: tracing_tools.PHASE_ORDER.index(p["phase"]) if p.get("phase") in tracing_tools.PHASE_ORDER else 99)

    lines = [f"Flow for {endpoint}", f"Phases ({len(phases)}):"]
    middleware_collapsed: list[str] = []

    for p in phases:
        phase = p["phase"]
        fpath = p.get("lua_file") or p.get("file_path")
        if fpath and _is_middleware(engine, fpath, None):
            middleware_collapsed.append(f"[{phase}] {fpath}")
            continue
        lines.append(f"  [{phase}] {fpath or '(inline)'}")

        if not fpath:
            continue

        calls = engine.query("""
            MATCH path = (fn:Function {file: $file})-[:CALLS*1..3]->(called:Function)
            RETURN [n in nodes(path) | n.name] AS chain,
                   [n in nodes(path) | n.file] AS files
            LIMIT 10
        """, file=fpath)

        for c in calls[:5]:
            chain = list(zip(c["chain"], c["files"]))
            non_mw = [n for n, f in chain if not _is_middleware(engine, f, n)]
            if not non_mw:
                middleware_collapsed.append(" → ".join(c["chain"]))
                continue
            chain_items = []
            for name, file in chain:
                if _is_middleware(engine, file, name):
                    chain_items.append(f"<mw:{name}>")
                else:
                    chain_items.append(name)
            lines.append(f"    {' → '.join(chain_items)}")

    reroutes = engine.query("""
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
        MATCH (fn:Function {file: f.path})-[r:REROUTES_TO]->(target:Endpoint)
        RETURN DISTINCT target.path AS target_path, r.redirect_type AS redirect_type,
               fn.name AS from_function
    """, endpoint=endpoint)
    if reroutes:
        lines.append("\nInternal reroutes:")
        for r in reroutes:
            lines.append(f"  {r['from_function']} --[{r['redirect_type']}]--> {r['target_path']}")

    http_calls = engine.query("""
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
        MATCH (fn:Function {file: f.path})-[r:HTTP_CALLS]->(target:Endpoint)
        RETURN DISTINCT target.path AS target_path, r.method AS method,
               fn.name AS from_function
    """, endpoint=endpoint)
    if http_calls:
        lines.append("\nCross-service HTTP calls:")
        for h in http_calls:
            lines.append(f"  {h['from_function']} --[{h['method']}]--> {h['target_path']}")

    if middleware_collapsed:
        lines.append(f"\nMiddleware collapsed ({len(middleware_collapsed)}) — pass escape_hatch=true to expand.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# find_impact
# ---------------------------------------------------------------------------

_PATH_SUFFIXES = (".lua", ".py", ".rb", ".js", ".go", ".erb")


def _looks_like_path(s: str) -> bool:
    if "/" in s or "\\" in s:
        return True
    # Treat trailing extension as path only if there's a separator OR no dot
    # before the extension (so a function literally named `foo.py` is a symbol,
    # but `foo/bar.py` is a path).
    return any(s.endswith(suf) and "/" in s for suf in _PATH_SUFFIXES)


def find_impact(engine: QueryEngine, symbol_or_file: str, max_depth: int = 5,
                escape_hatch: bool = False) -> str:
    """Blast radius for a change. Accepts a file path or a symbol name.

    Honors Phase-1 task-fit row: impact analysis (graph >> grep / embeddings).
    Returns: direct callers, transitive file-level dependents, and implicit couplings
    (ngx.ctx, ngx.shared, Redis keys, HTTP calls). escape_hatch=True appends raw
    primitive output for both file and symbol branches.
    """
    looks_like_path = _looks_like_path(symbol_or_file)
    depth = max(1, min(int(max_depth), 10))

    sections: list[str] = [f"Impact for {symbol_or_file}"]

    if looks_like_path:
        file_path = symbol_or_file.replace("\\", "/")
        deps = engine.query(f"""
            MATCH (dep:File)-[:IMPORTS*1..{depth}]->(f:File {{path: $path}})
            RETURN DISTINCT dep.path AS path, dep.language AS language
            ORDER BY dep.path
        """, path=file_path)
        if deps:
            sections.append(f"\nTransitive dependents ({len(deps)} files, depth ≤ {depth}):")
            for d in deps[:30]:
                sections.append(f"  {d['path']} [{d.get('language') or '?'}]")
            if len(deps) > 30:
                sections.append(f"  ... and {len(deps) - 30} more")
        else:
            sections.append("\nTransitive dependents: (none)")

        implicit = impact_tools.get_implicit_dependencies(engine, file_path)
        sections.append("\n" + implicit)

        if escape_hatch:
            sections.append("\n--- escape hatch: raw primitives ---")
            sections.append(impact_tools.find_impacted_files(engine, file_path, depth))
    else:
        callers = engine.query(f"""
            MATCH (caller:Function)-[:CALLS*1..{depth}]->(fn:Function)
            WHERE fn.name CONTAINS $name
            RETURN DISTINCT caller.name AS caller, caller.file AS file, fn.name AS callee
            ORDER BY caller.file
            LIMIT 100
        """, name=symbol_or_file)
        if callers:
            sections.append(f"\nCallers (transitive, depth ≤ {depth}, {len(callers)} found):")
            for c in callers[:30]:
                sections.append(f"  {c['caller']} in {c['file']} → {c['callee']}")
            if len(callers) > 30:
                sections.append(f"  ... and {len(callers) - 30} more")
        else:
            sections.append("\nCallers: (none)")

        files_defining = engine.query("""
            MATCH (f:File)-[:DEFINES]->(fn:Function)
            WHERE fn.name = $name
            RETURN DISTINCT f.path AS path
            LIMIT 5
        """, name=symbol_or_file)
        if files_defining:
            sections.append("\nDefined in:")
            for f in files_defining:
                sections.append(f"  {f['path']}")
                implicit = impact_tools.get_implicit_dependencies(engine, f["path"])
                sections.append("  " + implicit.replace("\n", "\n  "))

        if escape_hatch:
            sections.append("\n--- escape hatch: raw primitives ---")
            sections.append(tracing_tools.find_all_callers(engine, symbol_or_file))
            for f in files_defining:
                sections.append(impact_tools.find_impacted_files(engine, f["path"], depth))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# onboard_to
# ---------------------------------------------------------------------------

def onboard_to(engine: QueryEngine, area: str, escape_hatch: bool = False) -> str:
    """Ramp-up pack for a feature area. `area` is a path prefix, module name, or endpoint.

    Honors Phase-1 task-fit row: onboarding / repo overview (graph reranks tame
    grep noise). escape_hatch=True widens the central-files filter (no min import
    threshold) and includes non-public exports.
    """
    if area.startswith("/"):
        # Endpoint case — delegate to explain_flow.
        return explain_flow(engine, area, escape_hatch=escape_hatch)

    area_norm = area.replace("\\", "/").strip("/")
    lines = [f"Onboarding to {area}"]

    central_min = 0 if escape_hatch else 1
    central_limit = 30 if escape_hatch else 10
    central = engine.query(f"""
        MATCH (f:File)
        WHERE f.path CONTAINS $area
        OPTIONAL MATCH (f)<-[:IMPORTS]-(caller:File)
        WITH f, count(caller) AS import_count
        WHERE import_count >= {central_min}
        RETURN f.path AS path, f.language AS language, import_count
        ORDER BY import_count DESC
        LIMIT {central_limit}
    """, area=area_norm)

    if central:
        label = "Files" if escape_hatch else "Most-imported files"
        lines.append(f"\n{label} in '{area_norm}' ({len(central)}):")
        for c in central:
            lines.append(f"  {c['path']} [{c.get('language') or '?'}] — imported by {c['import_count']}")
    else:
        lines.append(f"\nNo files matched '{area_norm}'.")

    # Exports — public-only by default, all visibility under escape_hatch.
    visibility_clause = "" if escape_hatch else "AND fn.visibility = 'public'"
    exports = engine.query(f"""
        MATCH (f:File)-[:DEFINES]->(fn:Function)
        WHERE f.path CONTAINS $area {visibility_clause}
        RETURN f.path AS file, collect(fn.name) AS names
        ORDER BY f.path
        LIMIT 20
    """, area=area_norm)
    if exports:
        label = "Exports (all visibilities)" if escape_hatch else "Public exports"
        lines.append(f"\n{label}:")
        for e in exports:
            names = ", ".join(e["names"][:8])
            more = f" (+{len(e['names']) - 8})" if len(e["names"]) > 8 else ""
            lines.append(f"  {e['file']}: {names}{more}")

    endpoints = engine.query("""
        MATCH (e:Endpoint)-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
        WHERE f.path CONTAINS $area
        RETURN DISTINCT e.path AS endpoint
        ORDER BY e.path
        LIMIT 15
    """, area=area_norm)
    if endpoints:
        lines.append("\nEndpoints served from this area:")
        for e in endpoints:
            lines.append(f"  {e['endpoint']}")

    redis = engine.query("""
        MATCH (fn:Function)-[:REDIS_READS|REDIS_WRITES]->(k:RedisKey)
        WHERE fn.file CONTAINS $area
        RETURN DISTINCT k.name AS key
        ORDER BY k.name
        LIMIT 15
    """, area=area_norm)
    if redis:
        lines.append("\nRedis keys touched:")
        for r in redis:
            lines.append(f"  {r['key']}")

    if not escape_hatch and central:
        lines.append("\n(escape_hatch=true to drop the centrality filter and include all visibilities)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# locate
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
    "that", "this", "is", "are", "by", "from", "as", "be", "it",
    "function", "class", "file", "module", "code", "find", "where", "what",
    "how", "when", "which", "use", "using", "used",
})


def locate(engine: QueryEngine, description: str, limit: int = 10,
           escape_hatch: bool = False) -> str:
    """Natural-language symbol localization.

    Honors Phase-1 task-fit row: NL → symbol localization. v1 = grep-rerank-
    by-graph-centrality (no embeddings). Score = hits * log(2 + in_edges).
    escape_hatch=True returns raw lexical matches with no centrality reranking
    (useful when the target is a leaf utility with low in-degree).
    """
    raw_tokens = [t.lower() for t in _TOKEN_RE.findall(description)]
    # Token floor 2 keeps short language tokens (js, go, py, db, id).
    tokens = [t for t in raw_tokens if t not in _STOPWORDS and len(t) >= 2]
    if not tokens:
        return f"locate: no usable tokens in '{description}'."

    if escape_hatch:
        # Memgraph does not support size([t IN $tokens WHERE ...]) over a
        # parameter list, so we count token hits via UNWIND + sum instead.
        cypher = """
            MATCH (n)
            WHERE (n:Function OR n:Class OR n:Module OR n:File)
              AND ANY(t IN $tokens WHERE
                    toLower(coalesce(n.name, '')) CONTAINS t
                    OR toLower(coalesce(n.file, n.path, '')) CONTAINS t)
            WITH n
            UNWIND $tokens AS tok
            WITH n, sum(CASE WHEN
                    toLower(coalesce(n.name, '')) CONTAINS tok
                    OR toLower(coalesce(n.file, n.path, '')) CONTAINS tok
                 THEN 1 ELSE 0 END) AS hits
            RETURN labels(n)[0] AS type,
                   coalesce(n.name, n.path) AS name,
                   coalesce(n.file, n.path) AS file,
                   n.line AS line,
                   hits
            ORDER BY hits DESC
            LIMIT $limit
        """
        results = engine.query(cypher, tokens=tokens, limit=limit)
        if not results:
            return f"locate: no matches for tokens {tokens}."
        lines = [f"locate '{description}' — escape_hatch raw matches, tokens {tokens}:"]
        for r in results:
            line_s = f":{r['line']}" if r.get("line") else ""
            lines.append(f"  [{r['type']}] {r['name']} — {r['file']}{line_s} (hits={r['hits']})")
        return "\n".join(lines)

    # Default: rerank by centrality. log(2 + in_edges) ensures a hit on a
    # leaf node still scores above zero, so well-named entry points and
    # utilities don't collapse to the bottom.
    cypher = """
        MATCH (n)
        WHERE (n:Function OR n:Class OR n:Module OR n:File)
          AND ANY(t IN $tokens WHERE
                toLower(coalesce(n.name, '')) CONTAINS t
                OR toLower(coalesce(n.file, n.path, '')) CONTAINS t)
        WITH n
        UNWIND $tokens AS tok
        WITH n, sum(CASE WHEN
                toLower(coalesce(n.name, '')) CONTAINS tok
                OR toLower(coalesce(n.file, n.path, '')) CONTAINS tok
             THEN 1 ELSE 0 END) AS hits
        OPTIONAL MATCH (n)<-[r:IMPORTS|CALLS|DEFINES|HANDLES]-()
        WITH n, hits, count(r) AS in_edges
        RETURN labels(n)[0] AS type,
               coalesce(n.name, n.path) AS name,
               coalesce(n.file, n.path) AS file,
               n.line AS line,
               hits,
               in_edges,
               (toFloat(hits) * log(2.0 + in_edges)) AS score
        ORDER BY score DESC, hits DESC
        LIMIT $limit
    """
    results = engine.query(cypher, tokens=tokens, limit=limit)
    if not results:
        return f"locate: no matches for tokens {tokens}."

    lines = [f"locate '{description}' — tokens {tokens}, top {len(results)}:"]
    for r in results:
        line_s = f":{r['line']}" if r.get("line") else ""
        lines.append(
            f"  [{r['type']}] {r['name']} — {r['file']}{line_s} "
            f"(hits={r['hits']}, in_edges={r['in_edges']}, score={r['score']:.2f})"
        )
    return "\n".join(lines)
