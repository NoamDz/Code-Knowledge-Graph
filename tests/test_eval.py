# tests/test_eval.py
"""Graph-hitting eval tests for the MCP tool surface.

These require a populated Memgraph. The `engine` fixture (tests/conftest.py)
skips the whole suite when no graph is reachable, so these are inert on
machines without a built graph and only execute where the graph lives.
"""
from __future__ import annotations

import os
import pathlib

import pytest

from mcp_server.tools import composites, search, snippets
from tests.eval_cases import (
    BOB_CASES,
    DIFFERENTIAL_CASES,
    LIVENESS_CASES,
    check_output,
    discover_lua_definitions,
)


def run_tool(engine, tool: str, inp: dict) -> str:
    """Dispatch an EvalCase to the matching tool function."""
    if tool == "explain_flow":
        return composites.explain_flow(engine, **inp)
    if tool == "find_impact":
        return composites.find_impact(engine, **inp)
    if tool == "onboard_to":
        return composites.onboard_to(engine, **inp)
    if tool == "locate":
        return composites.locate(engine, **inp)
    if tool == "find_symbol":
        return search.find_symbol(engine, **inp)
    if tool == "get_code_snippet":
        return snippets.get_code_snippet(engine, **inp)
    if tool == "get_file_outline":
        return snippets.get_file_outline(engine, **inp)
    raise ValueError(f"unknown tool {tool!r}")


@pytest.mark.parametrize("case", LIVENESS_CASES, ids=lambda c: c.id)
def test_tool_is_alive(engine, case):
    """Each tool runs on a known input and returns non-empty output."""
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: sample anchor not set (fill it in eval_cases.py)")
    output = run_tool(engine, case.tool, case.input)  # must not raise
    failures = check_output(output, case)
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("case", DIFFERENTIAL_CASES, ids=lambda c: c.id)
def test_escape_hatch_changes_output(engine, case):
    """escape_hatch=True must visibly change a composite's output."""
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: sample anchor not set")
    filtered = run_tool(engine, case.tool, {**case.input, "escape_hatch": False})
    expanded = run_tool(engine, case.tool, {**case.input, "escape_hatch": True})
    assert filtered != expanded, (
        f"{case.id}: escape_hatch=True produced identical output -- the composite's "
        f"filtering/rerank had no effect (or the chosen input has nothing to filter)."
    )


@pytest.mark.parametrize("case", BOB_CASES, ids=lambda c: c.id)
def test_bob_anchor(engine, case):
    """Ground-truth anchors from the BOB answer key (red until the tools are fixed)."""
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: anchor not set")
    output = run_tool(engine, case.tool, case.input)
    failures = check_output(output, case)
    assert not failures, "\n".join(failures)


_REPO_ROOT = os.environ.get("CODE_GRAPH_REPO_ROOT", "")
_DEFS = discover_lua_definitions(_REPO_ROOT, limit=10) if _REPO_ROOT else []


@pytest.mark.skipif(not _DEFS, reason="CODE_GRAPH_REPO_ROOT not set or no Lua defs found")
@pytest.mark.parametrize("name,path", _DEFS, ids=[n for n, _ in _DEFS])
def test_find_symbol_points_at_real_file(engine, name, path):
    """Source-as-answer-key: find_symbol must mention the file the def really lives in."""
    out = search.find_symbol(engine, name)
    basename = pathlib.Path(path).name
    assert basename in out, (
        f"find_symbol({name!r}) did not mention {basename}; the graph disagrees "
        f"with the source. Output:\n{out}"
    )
