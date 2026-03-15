"""Impact analysis tools: blast radius, implicit dependencies."""

from __future__ import annotations

from ..query_engine import QueryEngine, format_file_list


def find_impacted_files(engine: QueryEngine, file_path: str, max_depth: int = 5) -> str:
    """Find all files that could be affected by changes to the given file."""
    results = engine.query("""
        MATCH (dep:File)-[:IMPORTS*1..$depth]->(f:File {path: $path})
        RETURN DISTINCT dep.path AS path, dep.language AS language
        ORDER BY dep.path
    """, path=file_path, depth=max_depth)
    return format_file_list(f"Files impacted by changes to {file_path}", results)


def get_implicit_dependencies(engine: QueryEngine, file_path: str) -> str:
    """Find implicit dependencies via ngx.ctx and ngx.shared coupling."""
    # ctx coupling
    ctx_results = engine.query("""
        MATCH (fn:Function {file: $path})-[:CTX_WRITES]->(k:ContextKey)
        OPTIONAL MATCH (other:Function)-[:CTX_READS]->(k)
        WHERE other.file <> $path
        RETURN k.name AS field, fn.name AS writer, collect(DISTINCT other.file) AS reader_files
    """, path=file_path)

    ctx_reads = engine.query("""
        MATCH (fn:Function {file: $path})-[:CTX_READS]->(k:ContextKey)
        OPTIONAL MATCH (other:Function)-[:CTX_WRITES]->(k)
        WHERE other.file <> $path
        RETURN k.name AS field, fn.name AS reader, collect(DISTINCT other.file) AS writer_files
    """, path=file_path)

    # shared dict coupling
    shared_results = engine.query("""
        MATCH (fn:Function {file: $path})-[:USES_SHARED]->(d:SharedDict)
        OPTIONAL MATCH (other:Function)-[:USES_SHARED]->(d)
        WHERE other.file <> $path
        RETURN d.name AS dict, collect(DISTINCT other.file) AS other_files
    """, path=file_path)

    lines = [f"Implicit dependencies for {file_path}:"]

    if ctx_results:
        lines.append("\nngx.ctx writes (other files read these):")
        for r in ctx_results:
            if r["reader_files"]:
                files = ", ".join(r["reader_files"])
                lines.append(f"  ngx.ctx.{r['field']} (written by {r['writer']}) → read by: {files}")

    if ctx_reads:
        lines.append("\nngx.ctx reads (other files write these):")
        for r in ctx_reads:
            if r["writer_files"]:
                files = ", ".join(r["writer_files"])
                lines.append(f"  ngx.ctx.{r['field']} (read by {r['reader']}) ← written by: {files}")

    if shared_results:
        lines.append("\nngx.shared dict coupling:")
        for r in shared_results:
            if r["other_files"]:
                files = ", ".join(r["other_files"])
                lines.append(f"  ngx.shared.{r['dict']} — also used by: {files}")

    if len(lines) == 1:
        lines.append("  (no implicit dependencies found)")

    return "\n".join(lines)
