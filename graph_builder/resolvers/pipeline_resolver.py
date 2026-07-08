"""Pipeline resolver: dirty-flag -> assessor data-flow edges.

A set_dirty_flag("<name>", component) call signals the assessor module whose
M.name == "<name>". We build a name->file index from module_constants and join
the dirty-flag write accesses (produced by redis_abstraction_resolver, keyed
"dirty:<component>:<flag>") to that index.
"""
from __future__ import annotations

import logging

from graph_builder.parsers.base import FileAST

logger = logging.getLogger(__name__)


def _build_assessor_index(all_asts: dict[str, FileAST]) -> dict[str, str]:
    """Build a name -> file_path index over Lua modules under an assessors/
    directory that declare an M.name string constant (module_constants["name"]).

    Only modules whose path contains an "/assessors/" directory segment are
    indexed -- a module declaring a matching M.name elsewhere is not a
    candidate target. Name uniqueness across assessors is assumed, not
    enforced: if two different assessor files declare the same name, a
    warning is logged and the later one wins.
    """
    index: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue
        name = ast.module_constants.get("name")
        if not name:
            continue
        norm = file_path.replace("\\", "/")
        if "/assessors/" not in norm:
            continue
        if name in index:
            logger.warning(
                "Duplicate assessor name '%s': %s was already registered, "
                "now also declared by %s (last one wins)",
                name, index[name], file_path,
            )
        index[name] = file_path
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
