# tests/eval_cases.py
"""Declarative eval cases for the MCP tool surface (data + pure helpers only)."""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field


@dataclass
class EvalCase:
    tool: str                                   # "find_symbol" | "explain_flow" | ...
    input: dict                                 # kwargs passed to the tool function
    must_contain: list[str] = field(default_factory=list)      # regex patterns
    must_not_contain: list[str] = field(default_factory=list)  # regex patterns
    min_lines: int | None = None                # min non-empty lines in output
    note: str = ""                              # why this is true (verification trail)
    id: str = ""                                # short label for pytest param ids

    def label(self) -> str:
        return self.id or f"{self.tool}:{self.input}"


def check_output(output: str | None, case: EvalCase) -> list[str]:
    """Return human-readable failure strings; empty list means the case passed."""
    if output is None:
        return [f"{case.label()}: tool returned None"]
    failures: list[str] = []
    for needle in case.must_contain:
        if not re.search(needle, output):
            failures.append(f"{case.label()}: expected to contain /{needle}/")
    for needle in case.must_not_contain:
        if re.search(needle, output):
            failures.append(f"{case.label()}: expected NOT to contain /{needle}/")
    if case.min_lines is not None:
        n = len([ln for ln in output.splitlines() if ln.strip()])
        if n < case.min_lines:
            failures.append(f"{case.label()}: expected >= {case.min_lines} non-empty lines, got {n}")
    return failures


# Matches "function a.b.c()", "function a:b()", "local function x()", "function x()".
_LUA_DEF = re.compile(r"^\s*(?:local\s+)?function\s+([\w.:]+)", re.MULTILINE)


def discover_lua_definitions(root: str, limit: int = 10) -> list[tuple[str, str]]:
    """Scan *.lua under root, return up to `limit` (bare_name, abs_path) pairs.

    Independent of the project's own parser/graph, so it can serve as an answer
    key. Returns [] when root does not exist (e.g. running with no source).
    """
    base = pathlib.Path(root)
    if not base.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(base.rglob("*.lua")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _LUA_DEF.finditer(text):
            bare = m.group(1).split(".")[-1].split(":")[-1]
            if bare:
                out.append((bare, str(path)))
            if len(out) >= limit:
                return out
    return out
