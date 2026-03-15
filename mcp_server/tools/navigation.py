"""Navigation tools: dependency lookup, repo overview."""

from __future__ import annotations

from ..query_engine import QueryEngine, format_file_list


def get_dependencies(engine: QueryEngine, file_path: str) -> str:
    """Returns all files that the given file imports or depends on."""
    results = engine.query("""
        MATCH (f:File {path: $path})-[:IMPORTS*1..]->(dep:File)
        RETURN DISTINCT dep.path AS path, dep.language AS language
        ORDER BY dep.path
    """, path=file_path)
    return format_file_list(f"Dependencies of {file_path}", results)


def get_dependents(engine: QueryEngine, file_path: str) -> str:
    """Returns all files that import or depend on the given file."""
    results = engine.query("""
        MATCH (dep:File)-[:IMPORTS*1..]->(f:File {path: $path})
        RETURN DISTINCT dep.path AS path, dep.language AS language
        ORDER BY dep.path
    """, path=file_path)
    return format_file_list(f"Files that depend on {file_path}", results)


def get_repo_overview(engine: QueryEngine, limit: int = 40) -> str:
    """Returns a condensed map of the most central files in the codebase."""
    results = engine.query("""
        MATCH (f:File)<-[:IMPORTS]-(caller:File)
        WITH f, count(caller) AS import_count
        WHERE import_count > 1
        RETURN f.path AS path, f.language AS language, import_count
        ORDER BY import_count DESC
        LIMIT $limit
    """, limit=limit)
    if not results:
        return "No import relationships found in the graph."
    lines = [f"Top {len(results)} most-imported files:"]
    for r in results:
        lines.append(f"  {r['path']} [{r['language']}] — imported by {r['import_count']} files")
    return "\n".join(lines)
