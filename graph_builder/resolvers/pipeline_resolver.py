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
    """Build a name -> file_path index over every Lua module that declares an
    M.name string constant (module_constants["name"]).

    This is NOT limited to modules living under an assessors/ directory: any
    Lua module that declares a matching M.name is accepted as a candidate.
    Modules whose path contains "/assessors/" take precedence over modules
    that don't -- that precedence is intentional (a real assessor should
    always win over an incidental namesake) and is not warned about. Beyond
    that, name uniqueness is assumed, not enforced: this is a deliberately
    loose string join, and when two candidates of the *same* priority
    (assessor-vs-assessor, or plain-vs-plain) declare the same name, only one
    survives in the returned dict -- see the warning below for that case.
    """
    index: dict[str, str] = {}
    is_assessor: dict[str, bool] = {}
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue
        name = ast.module_constants.get("name")
        if not name:
            continue
        norm = file_path.replace("\\", "/")
        candidate_is_assessor = "/assessors/" in norm
        # Prefer assessor modules, but accept any module declaring a name.
        if candidate_is_assessor:
            if name in index and is_assessor.get(name):
                logger.warning(
                    "Duplicate assessor name '%s': %s was already registered, "
                    "now also declared by %s (last one wins)",
                    name, index[name], file_path,
                )
            index[name] = file_path
            is_assessor[name] = True
        else:
            if name in index:
                if not is_assessor.get(name):
                    logger.warning(
                        "Duplicate module name '%s': %s was already registered, "
                        "now also declared by %s (first one wins)",
                        name, index[name], file_path,
                    )
                continue
            index[name] = file_path
            is_assessor[name] = False
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
