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

    # Redis key coupling
    redis_results = engine.query("""
        MATCH (fn:Function {file: $path})-[r:REDIS_READS|REDIS_WRITES]->(k:RedisKey)
        OPTIONAL MATCH (other:Function)-[:REDIS_READS|REDIS_WRITES]->(k)
        WHERE other.file <> $path
        RETURN k.name AS key, type(r) AS edge_type, fn.name AS function,
               collect(DISTINCT other.file) AS other_files
    """, path=file_path)

    if redis_results:
        lines.append("\nRedis key coupling:")
        for r in redis_results:
            if r["other_files"]:
                direction = "writes" if "WRITES" in r["edge_type"] else "reads"
                files = ", ".join(r["other_files"])
                lines.append(f"  redis:{r['key']} ({direction} by {r['function']}) — also used by: {files}")

    # HTTP call coupling
    http_results = engine.query("""
        MATCH (fn:Function {file: $path})-[r:HTTP_CALLS]->(e:Endpoint)
        RETURN e.path AS endpoint, r.method AS method, fn.name AS function
    """, path=file_path)

    if http_results:
        lines.append("\nHTTP calls to other services:")
        for r in http_results:
            lines.append(f"  {r['function']} → {r['method']} {r['endpoint']}")

    if len(lines) == 1:
        lines.append("  (no implicit dependencies found)")

    return "\n".join(lines)


def get_redis_coupling(engine: QueryEngine, key_pattern: str) -> str:
    """Find all services that read or write a Redis key matching the pattern."""
    results = engine.query("""
        MATCH (fn:Function)-[r:REDIS_READS|REDIS_WRITES]->(k:RedisKey)
        WHERE k.name CONTAINS $pattern
        RETURN k.name AS key, fn.name AS function, fn.file AS file,
               type(r) AS edge_type, r.operation AS operation
        ORDER BY k.name, fn.file
    """, pattern=key_pattern)

    if not results:
        return f"No Redis key accesses found matching '{key_pattern}'"

    lines = [f"Redis coupling for keys matching '{key_pattern}':"]

    # Group by key
    by_key: dict[str, list] = {}
    for r in results:
        by_key.setdefault(r["key"], []).append(r)

    for key, accesses in by_key.items():
        lines.append(f"\n  Key: {key}")
        writers = [a for a in accesses if "WRITES" in a["edge_type"]]
        readers = [a for a in accesses if "READS" in a["edge_type"]]

        if writers:
            lines.append("    Writers:")
            for w in writers:
                lines.append(f"      {w['function']} in {w['file']} ({w['operation']})")
        if readers:
            lines.append("    Readers:")
            for r_item in readers:
                lines.append(f"      {r_item['function']} in {r_item['file']} ({r_item['operation']})")

    return "\n".join(lines)


def trace_cross_service_flow(engine: QueryEngine, endpoint: str) -> str:
    """Follow internal reroutes and HTTP calls to trace cross-service data flow."""
    results = engine.query("""
        MATCH (e:Endpoint {path: $endpoint})
        OPTIONAL MATCH (fn:Function)-[:REROUTES_TO]->(e)
        OPTIONAL MATCH (fn2:Function)-[:HTTP_CALLS]->(e)
        RETURN 'reroute_source' AS type, fn.name AS function, fn.file AS file
        UNION
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
        MATCH (fn:Function {file: f.path})-[:REROUTES_TO]->(target:Endpoint)
        RETURN 'reroute_target' AS type, fn.name AS function, target.path AS file
        UNION
        MATCH (e:Endpoint {path: $endpoint})-[:HAS_PHASE]->(:NginxPhase)-[:HANDLES]->(f:File)
        MATCH (fn:Function {file: f.path})-[r:HTTP_CALLS]->(target:Endpoint)
        RETURN 'http_target' AS type, fn.name AS function, target.path AS file
    """, endpoint=endpoint)

    if not results:
        return f"No cross-service flow found for endpoint '{endpoint}'"

    lines = [f"Cross-service flow for {endpoint}:"]
    for r in results:
        if r["function"]:
            lines.append(f"  [{r['type']}] {r['function']} → {r['file']}")

    return "\n".join(lines)
