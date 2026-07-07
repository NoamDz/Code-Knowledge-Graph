"""Pipeline resolver: dirty-flag -> assessor data-flow edges.

A set_dirty_flag("<name>", component) call signals the assessor module whose
M.name == "<name>". We build a name->file index from module_constants and join
the dirty-flag write accesses (produced by redis_abstraction_resolver, keyed
"dirty:<component>:<flag>") to that index.
"""
from __future__ import annotations

from graph_builder.parsers.base import FileAST


def _build_assessor_index(all_asts: dict[str, FileAST]) -> dict[str, str]:
    """name -> file_path for every module that declares M.name and lives under assessors/."""
    index: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue
        name = ast.module_constants.get("name")
        if not name:
            continue
        norm = file_path.replace("\\", "/")
        # Prefer assessor modules, but accept any module declaring a name.
        if "/assessors/" in norm:
            index[name] = file_path
        else:
            index.setdefault(name, file_path)
    return index


def resolve_pipeline_edges(all_asts: dict[str, FileAST]) -> list[dict]:
    """Return [{source_file, target_file, flag, line}] for dirty-flag -> assessor."""
    assessor_index = _build_assessor_index(all_asts)
    edges: list[dict] = []
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue
        for acc in ast.redis_accesses:
            if not acc.key_name.startswith("dirty:") or acc.access_type != "write":
                continue
            # key format: dirty:<component>:<flag>
            parts = acc.key_name.split(":", 2)
            if len(parts) != 3:
                continue
            flag = parts[2]
            target = assessor_index.get(flag)
            if not target or target == file_path:
                continue
            edges.append({
                "source_file": file_path,
                "target_file": target,
                "flag": flag,
                "line": acc.line,
            })
    return edges
