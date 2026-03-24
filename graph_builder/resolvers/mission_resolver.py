"""Mission dispatch resolver: maps missioner.add_mission('name') to task files.

The Lua codebase uses a mission/task system:
  missioner.add_mission("pts_run", params, delay, queue)

Task names map to files by convention: "pts_run" -> tasks/pts_run.lua
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def task_name_to_file_pattern(task_name: str) -> str:
    """Convert a task name to its expected file path pattern."""
    return f"tasks/{task_name}"


def resolve_missions(all_asts: dict[str, FileAST]) -> list[dict]:
    """Find all mission dispatch calls by reading ast.warnings for mission: entries.

    Returns list of dicts with source_file, task_name, line, target_pattern.
    """
    missions: list[dict] = []
    for file_path, ast in all_asts.items():
        for w in ast.warnings:
            if w.startswith("mission:"):
                parts = w.split(":", 2)
                if len(parts) >= 3:
                    task_name = parts[1]
                    try:
                        line = int(parts[2])
                    except ValueError:
                        line = 0
                    missions.append({
                        "source_file": file_path,
                        "task_name": task_name,
                        "line": line,
                        "target_pattern": task_name_to_file_pattern(task_name),
                    })
    return missions
