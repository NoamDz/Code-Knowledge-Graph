"""Snippet tools: source code retrieval, file outlines."""

from __future__ import annotations

from pathlib import Path

from ..query_engine import QueryEngine


# Map languages to markdown fence hints
_LANG_HINTS = {
    "lua": "lua",
    "python": "python",
    "ruby": "ruby",
    "javascript": "javascript",
    "go": "go",
}


def get_code_snippet(engine: QueryEngine, name: str, context_lines: int = 0) -> str:
    """Given a function or class name, find it in the graph, read the source file,
    and return the relevant source code lines.

    Args:
        engine: QueryEngine instance
        name: Function or class name (can be partial - will search)
        context_lines: Extra lines to show before/after the function (default 0)

    Returns formatted source code with file location header.
    """
    # Query graph for Function or Class nodes matching the name
    results = engine.query("""
        MATCH (n)
        WHERE (n:Function OR n:Class)
          AND n.name CONTAINS $name
        RETURN n.name AS name, n.file AS file, n.line AS line,
               n.line_end AS line_end, labels(n) AS labels
        LIMIT 10
    """, name=name)

    if not results:
        return f"No function or class matching '{name}' found in the graph."

    sections: list[str] = []

    for r in results:
        node_name = r["name"]
        file_path = r["file"]
        line_start = r.get("line")
        line_end = r.get("line_end")
        labels = r.get("labels", [])
        node_type = "Class" if "Class" in labels else "Function"

        # Validate we have line info
        if not line_start:
            sections.append(
                f"{node_type} '{node_name}' in {file_path} (line info not available)"
            )
            continue

        # Read the source file
        source_path = Path(file_path)
        if not source_path.exists():
            sections.append(
                f"{node_type} '{node_name}' in {file_path} — file not found on disk"
            )
            continue

        try:
            source_lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            sections.append(
                f"{node_type} '{node_name}' in {file_path} — error reading file: {e}"
            )
            continue

        # Determine line range (1-indexed in graph, convert to 0-indexed for list)
        start = max(1, line_start - context_lines)
        end = (line_end or line_start) + context_lines
        end = min(end, len(source_lines))

        snippet_lines = source_lines[start - 1 : end]
        snippet = "\n".join(snippet_lines)

        # Detect language hint from file extension
        lang_hint = ""
        suffix = source_path.suffix.lower()
        for lang, hint in _LANG_HINTS.items():
            if lang in suffix or suffix.lstrip(".") == hint:
                lang_hint = hint
                break
        if not lang_hint:
            ext_map = {".lua": "lua", ".py": "python", ".rb": "ruby",
                       ".js": "javascript", ".go": "go"}
            lang_hint = ext_map.get(suffix, "")

        sections.append(
            f"{node_type} '{node_name}' in {file_path} (lines {start}-{end}):\n"
            f"```{lang_hint}\n{snippet}\n```"
        )

    return "\n\n".join(sections)


def get_file_outline(engine: QueryEngine, file_path: str) -> str:
    """Show the structural outline of a file: all classes, functions, and their line ranges.

    Returns a formatted summary of defined symbols, exports, and imports.
    """
    # Get file metadata
    file_info = engine.query("""
        MATCH (f:File {path: $path})
        RETURN f.language AS language, f.module_name AS module_name
    """, path=file_path)

    if not file_info:
        return f"File '{file_path}' not found in the graph."

    language = file_info[0].get("language", "unknown")
    module_name = file_info[0].get("module_name")

    # Get all defined symbols
    symbols = engine.query("""
        MATCH (f:File {path: $path})-[:DEFINES]->(n)
        RETURN n.name AS name, n.line AS line, n.line_end AS line_end,
               labels(n) AS labels, n.visibility AS visibility
        ORDER BY n.line
    """, path=file_path)

    functions = []
    classes = []
    for s in symbols:
        labels = s.get("labels", [])
        entry = {
            "name": s["name"],
            "line": s.get("line", "?"),
            "line_end": s.get("line_end"),
            "visibility": s.get("visibility", "unknown"),
        }
        if "Class" in labels:
            classes.append(entry)
        elif "Function" in labels:
            functions.append(entry)

    # Get import count
    imports = engine.query("""
        MATCH (f:File {path: $path})-[:IMPORTS|REQUIRES]->(target)
        RETURN count(target) AS count
    """, path=file_path)
    import_count = imports[0]["count"] if imports else 0

    # Get exports (public functions)
    exports = [f["name"] for f in functions if f["visibility"] == "public"]

    # Build output
    header = f"File: {file_path} ({language})"
    if module_name:
        header += f"\nModule: {module_name}"

    lines = [header]

    # Functions section
    lines.append("\nFunctions:")
    if functions:
        for f in functions:
            line_range = f"lines {f['line']}-{f['line_end']}" if f["line_end"] else f"line {f['line']}"
            vis = f["visibility"] or "unknown"
            lines.append(f"  {f['name']} ({line_range}, {vis})")
    else:
        lines.append("  (none)")

    # Classes section
    lines.append("\nClasses:")
    if classes:
        for c in classes:
            line_range = f"lines {c['line']}-{c['line_end']}" if c["line_end"] else f"line {c['line']}"
            vis = c["visibility"] or "unknown"
            lines.append(f"  {c['name']} ({line_range}, {vis})")
    else:
        lines.append("  (none)")

    # Exports section
    lines.append(f"\nExports: {', '.join(exports) if exports else '(none)'}")

    # Imports section
    lines.append(f"Imports: {import_count} total")

    return "\n".join(lines)
