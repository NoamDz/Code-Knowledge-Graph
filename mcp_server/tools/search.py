"""Search tools: symbol lookup, module exports, graph statistics."""

from __future__ import annotations

from ..query_engine import QueryEngine, format_symbol_results


def find_symbol(engine: QueryEngine, symbol_name: str) -> str:
    """Find where a function, class, or module is defined."""
    results = engine.query("""
        MATCH (node)
        WHERE (node:Function OR node:Class OR node:Module)
          AND node.name CONTAINS $name
        RETURN labels(node)[0] AS type, node.name AS name,
               node.file AS file, node.line AS line
        ORDER BY node.file
        LIMIT 20
    """, name=symbol_name)
    return format_symbol_results(symbol_name, results)


def get_module_exports(engine: QueryEngine, module_name: str) -> str:
    """Return the public API of a module."""
    results = engine.query("""
        MATCH (f:File)-[:DEFINES]->(fn:Function)
        WHERE f.path CONTAINS replace($module, '.', '/')
          AND fn.visibility = 'public'
        RETURN fn.name AS function, fn.line AS line, f.path AS file
        ORDER BY fn.line
    """, module=module_name)

    if not results:
        return f"No exports found for module '{module_name}'"

    lines = [f"Exports of '{module_name}' ({len(results)}):"]
    for r in results:
        lines.append(f"  {r['function']} (line {r['line']}) in {r['file']}")
    return "\n".join(lines)


def get_graph_stats(engine: QueryEngine) -> str:
    """Return aggregate statistics about the code graph."""
    # Node counts
    nodes = engine.query("""
        MATCH (n)
        RETURN labels(n)[0] AS type, count(n) AS count
        ORDER BY count DESC
    """)

    # Edge counts
    edges = engine.query("""
        MATCH ()-[r]->()
        RETURN type(r) AS type, count(r) AS count
        ORDER BY count DESC
    """)

    # Language distribution
    langs = engine.query("""
        MATCH (f:File)
        RETURN f.language AS language, count(f) AS count
        ORDER BY count DESC
    """)

    lines = ["Graph Statistics:"]
    lines.append("\nNodes:")
    for r in nodes:
        lines.append(f"  {r['type']:>15}: {r['count']}")

    lines.append("\nEdges:")
    for r in edges:
        lines.append(f"  {r['type']:>15}: {r['count']}")

    lines.append("\nFiles by language:")
    for r in langs:
        lines.append(f"  {r['language']:>15}: {r['count']}")

    return "\n".join(lines)


def find_unresolved(engine: QueryEngine, language: str | None = None) -> str:
    """Return imports that could not be resolved to files."""
    lang_filter = "AND f.language = $language" if language else ""
    results = engine.query(f"""
        MATCH (f:File)-[:REQUIRES]->(m:Module {{is_external: true}})
        {lang_filter}
        RETURN m.name AS module, collect(DISTINCT f.path) AS importing_files,
               m.is_dynamic AS is_dynamic
        ORDER BY size(importing_files) DESC
        LIMIT 30
    """, language=language)

    if not results:
        return "No unresolved imports found (or graph is empty)"

    lines = [f"Unresolved imports ({len(results)}):"]
    for r in results:
        dynamic = " [DYNAMIC]" if r.get("is_dynamic") else ""
        count = len(r["importing_files"])
        lines.append(f"  {r['module']}{dynamic} — imported by {count} files")
        for f in r["importing_files"][:3]:
            lines.append(f"    {f}")
        if count > 3:
            lines.append(f"    ... and {count - 3} more")

    return "\n".join(lines)
