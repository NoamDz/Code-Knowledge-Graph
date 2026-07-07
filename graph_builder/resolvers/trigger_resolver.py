"""Trigger pub/sub resolver (two-phase, mirrors mission_resolver).

Phase 1 (resolve_trigger_events): scan calls to triggers.bind/defer/fire;
  recover the trigger name string by re-reading the source line.
    bind("name", fn)              -> subscriber, name = 1st string arg
    defer("name", data, opts)     -> publisher,  name = 1st string arg
    fire(bundle, store, "name")   -> publisher,  name = 3rd arg

Phase 2 (resolve_trigger_edges): join publishers -> subscribers on name.
"""
from __future__ import annotations

import re

from graph_builder.parsers.base import FileAST, TriggerEvent

_TRIGGER_MODULES = {"core.triggers", "triggers"}


def _source_line(file_path: str, line: int) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    return lines[line - 1] if 0 < line <= len(lines) else ""


def _name_for(method: str, src: str) -> str | None:
    if method == "fire":
        m = re.search(r'fire\s*\(\s*[^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']', src)
    else:  # bind / defer
        m = re.search(rf'{method}\s*\(\s*["\']([^"\']+)["\']', src)
    return m.group(1) if m else None


def resolve_trigger_events(all_asts: dict[str, FileAST]) -> None:
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue
        binding_to_module = {
            imp.local_binding: imp.module_string
            for imp in ast.imports
            if imp.local_binding and not imp.is_dynamic
        }
        trigger_bindings = {
            b for b, m in binding_to_module.items() if m in _TRIGGER_MODULES
        }
        for call in ast.calls:
            callee = call.callee_string
            if "." not in callee:
                continue
            recv, method = callee.split(".", 1)
            if method not in ("bind", "defer", "fire"):
                continue
            if recv not in trigger_bindings and recv != "triggers":
                continue
            name = _name_for(method, _source_line(file_path, call.line))
            if not name:
                continue
            role = "subscriber" if method == "bind" else "publisher"
            ast.trigger_events.append(TriggerEvent(
                name=name, role=role,
                caller_function=call.caller_function, line=call.line,
            ))


def resolve_trigger_edges(all_asts: dict[str, FileAST]) -> list[dict]:
    subscribers: dict[str, list[str]] = {}
    for file_path, ast in all_asts.items():
        for ev in ast.trigger_events:
            if ev.role == "subscriber":
                subscribers.setdefault(ev.name, []).append(file_path)
    edges: list[dict] = []
    for file_path, ast in all_asts.items():
        for ev in ast.trigger_events:
            if ev.role != "publisher":
                continue
            for target in subscribers.get(ev.name, []):
                if target == file_path:
                    continue
                edges.append({
                    "source_file": file_path,
                    "target_file": target,
                    "name": ev.name,
                    "line": ev.line,
                })
    return edges
