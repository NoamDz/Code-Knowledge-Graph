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

    Scanning stops mid-file once `limit` pairs are collected, and the regex may
    capture a `function` keyword inside a Lua block comment -- acceptable because
    this only needs to yield some true pairs, not an exhaustive list.
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


# ---------------------------------------------------------------------------
# Graph-hitting eval cases (require a populated Memgraph; conftest.py skips
# without one). Fill SAMPLE_FILE / SAMPLE_ENDPOINT on the machine with the
# graph -- use scripts/diagnose_graph.py to discover real values. Any case
# whose input contains None is skipped automatically by the tests.
# ---------------------------------------------------------------------------
SAMPLE_SYMBOL = "get_current"   # a function known to exist in the graph
SAMPLE_FILE = None              # e.g. "/abs/path/.../helpers.lua"
SAMPLE_ENDPOINT = None          # e.g. "/api/..." (a real Endpoint node path)

LIVENESS_CASES = [
    EvalCase("find_symbol", {"symbol_name": SAMPLE_SYMBOL}, min_lines=1, id="live-find_symbol"),
    EvalCase("get_code_snippet", {"name": SAMPLE_SYMBOL}, min_lines=1, id="live-get_code_snippet"),
    EvalCase("find_impact", {"symbol_or_file": SAMPLE_SYMBOL}, min_lines=1, id="live-find_impact"),
    EvalCase("locate", {"description": "session info", "limit": 5}, min_lines=1, id="live-locate"),
    EvalCase("onboard_to", {"area": "session_info"}, min_lines=1, id="live-onboard_to"),
    EvalCase("get_file_outline", {"file_path": SAMPLE_FILE}, min_lines=1, id="live-get_file_outline"),
    EvalCase("explain_flow", {"endpoint": SAMPLE_ENDPOINT}, min_lines=1, id="live-explain_flow"),
]

# escape_hatch=True must visibly change a composite's output (proves the
# filtering/rerank does something). Compares the tool to itself -- no anchors.
DIFFERENTIAL_CASES = [
    EvalCase("explain_flow", {"endpoint": SAMPLE_ENDPOINT}, id="diff-explain_flow"),
    EvalCase("find_impact", {"symbol_or_file": SAMPLE_SYMBOL}, id="diff-find_impact"),
    EvalCase("onboard_to", {"area": "session_info"}, id="diff-onboard_to"),
    EvalCase("locate", {"description": "session info", "limit": 10}, id="diff-locate"),
]

# Ground-truth anchors from research/code-graph-testing/answer-key.md (BOB-verified).
# These start RED for the broken tools -- that is the point; each Phase-2 fix
# turns its anchor green.
BOB_CASES = [
    EvalCase("find_symbol", {"symbol_name": "require_version"},
             must_contain=[r"loader/lua/init\.lua"], id="bob-find_symbol-require_version",
             note="answer-key S1: defined in src/core/loader/lua/init.lua:81"),
    EvalCase("get_code_snippet", {"name": "require_version"},
             must_contain=[r"function .*require_version"],
             must_not_contain=["line info not available"],
             id="bob-snippet-require_version", note="answer-key S1: must return real source"),
    EvalCase("get_file_outline", {"file_path": "src/ato/models/session_device_data.lua"},
             must_contain=["save", "find_by_session_id"], id="bob-outline-session_device_data",
             note="answer-key S2: known public functions"),
    EvalCase("find_impact", {"symbol_or_file": "src/ato/models/session_device_data.lua"},
             must_not_contain=[r"\(none\)", "Traceback"], id="bob-impact-session_device_data",
             note="answer-key S2: 100+ usages exist; must not be empty/crash"),
    EvalCase("onboard_to", {"area": "src/ato"},
             must_contain=["models", "handlers"],
             must_not_contain=["Unbound variable", "Traceback"],
             id="bob-onboard-ato", note="answer-key S3: ATO has models/, handlers/"),
]
