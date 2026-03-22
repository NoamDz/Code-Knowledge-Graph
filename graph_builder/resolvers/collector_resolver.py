"""Collector resolver: finds collector registration patterns in parsed ASTs.

Collector registrations are Lua init.lua files that declare a table with
name, endpoint, and js_files fields. This resolver iterates all ASTs and
returns the collector mappings for graph ingestion.
"""

from __future__ import annotations

from ..parsers.base import FileAST


def resolve_collectors(all_asts: dict[str, FileAST]) -> list[dict]:
    """Find all collector registrations and return their mappings."""
    mappings = []
    for file_path, ast in all_asts.items():
        if ast.collector_info is None:
            continue
        mappings.append({
            "collector_name": ast.collector_info.name,
            "endpoint": ast.collector_info.endpoint,
            "js_files": ast.collector_info.js_files,
            "init_file": file_path,
        })
    return mappings
