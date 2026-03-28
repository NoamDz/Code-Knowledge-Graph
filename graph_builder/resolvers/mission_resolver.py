"""Mission dispatch resolver: maps missioner.add_mission('name') to task files.

Two-phase approach:
  Phase 1 (resolve_missions): Scan CallRef objects for mission dispatch calls.
    - missioner.add_mission("task_name", ...) -- direct calls
    - missioner_timer.post(...) -- timer-based dispatch
    - Binding-aware: local var bound to missioner module via require/require_version
    Populates ast.mission_dispatches with MissionDispatch entries.

  Phase 2 (resolve_mission_targets): Match task names to task files.
    Searches multiple directory patterns:
    - tasks/{name}.lua
    - src/ato/tasks/{name}.lua
    - src/common/tasks/{name}.lua
    - src/malware/tasks/{name}.lua
"""

from __future__ import annotations

import re

from graph_builder.parsers.base import FileAST, MissionDispatch

# Module strings that indicate a missioner import
_MISSIONER_MODULES = {
    "deferrer.missioner.client",
    "common.deferrer.missioner.client",
    "lib.lua.missioner",
    "missioner",
}

# Callee patterns that indicate a mission dispatch
_MISSION_CALL_PATTERNS = {
    "missioner.add_mission",
    "missioner_timer.post",
    "add_mission",
}

# Directories to search for task files
_TASK_DIR_PATTERNS = [
    "tasks/",
    "src/ato/tasks/",
    "src/common/tasks/",
    "src/malware/tasks/",
]


def resolve_missions(all_asts: dict[str, FileAST]) -> None:
    """Phase 1: Scan all Lua ASTs for mission dispatch calls.

    Populates ast.mission_dispatches for each file.
    """
    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        # Build binding map: local_var -> module_string
        binding_to_module: dict[str, str] = {}
        for imp in ast.imports:
            if imp.local_binding and not imp.is_dynamic:
                binding_to_module[imp.local_binding] = imp.module_string

        # Identify missioner bindings
        missioner_bindings: set[str] = set()
        for binding, mod_str in binding_to_module.items():
            if mod_str in _MISSIONER_MODULES:
                missioner_bindings.add(binding)

        for call in ast.calls:
            callee = call.callee_string
            is_mission_call = False

            # Check direct pattern match
            for pattern in _MISSION_CALL_PATTERNS:
                if callee == pattern or callee.endswith("." + pattern):
                    is_mission_call = True
                    break

            # Check binding-based match: <binding>.add_mission
            if not is_mission_call and "." in callee:
                parts = callee.split(".", 1)
                if parts[0] in missioner_bindings and parts[1] in (
                    "add_mission", "post"
                ):
                    is_mission_call = True

            if not is_mission_call:
                continue

            # Extract task name from the source file at the given line.
            # Since CallRef doesn't store arguments, we read the source.
            task_name = _extract_task_name_from_file_context(file_path, call.line)

            ast.mission_dispatches.append(MissionDispatch(
                task_name=task_name or "<unknown>",
                queue=None,
                caller_function=call.caller_function,
                line=call.line,
            ))

        # Also check legacy warning-based detection for backward compat
        for w in ast.warnings:
            if w.startswith("mission:"):
                parts = w.split(":", 2)
                if len(parts) >= 3:
                    task_name = parts[1]
                    try:
                        line = int(parts[2])
                    except ValueError:
                        line = 0
                    # Avoid duplicates
                    already = any(
                        d.task_name == task_name and d.line == line
                        for d in ast.mission_dispatches
                    )
                    if not already:
                        ast.mission_dispatches.append(MissionDispatch(
                            task_name=task_name,
                            caller_function="<module>",
                            line=line,
                        ))


def _extract_task_name_from_file_context(file_path: str, line: int) -> str | None:
    """Try to extract the task name from the source file at the given line.

    Reads the source file and looks for the string literal argument to
    add_mission() or post() on the specified line.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if 0 < line <= len(lines):
            source_line = lines[line - 1]
            # Match: add_mission("task_name" or post("task_name"
            match = re.search(
                r'(?:add_mission|post)\s*\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']',
                source_line,
            )
            if match:
                return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return None


def resolve_mission_targets(all_asts: dict[str, FileAST]) -> list[dict]:
    """Phase 2: Match task names to task handler files.

    Returns list of dicts:
        [{"source_file", "task_name", "line", "target_file", "target_pattern"}]
    """
    results: list[dict] = []

    for file_path, ast in all_asts.items():
        for dispatch in ast.mission_dispatches:
            if dispatch.task_name == "<unknown>":
                continue

            target_file = None
            target_pattern = f"tasks/{dispatch.task_name}"

            # Search for a file matching any of the task directory patterns
            for fp in all_asts:
                fp_normalized = fp.replace("\\", "/")
                for dir_pattern in _TASK_DIR_PATTERNS:
                    expected = f"{dir_pattern}{dispatch.task_name}.lua"
                    if fp_normalized.endswith(expected) or expected in fp_normalized:
                        target_file = fp
                        break
                    # Also match without .lua extension in the path
                    if dispatch.task_name in fp_normalized and "tasks/" in fp_normalized:
                        # Verify it's the right task file
                        filename = fp_normalized.rsplit("/", 1)[-1]
                        if filename == f"{dispatch.task_name}.lua":
                            target_file = fp
                            break
                if target_file:
                    break

            results.append({
                "source_file": file_path,
                "task_name": dispatch.task_name,
                "line": dispatch.line,
                "target_file": target_file,
                "target_pattern": target_pattern,
            })

    return results
