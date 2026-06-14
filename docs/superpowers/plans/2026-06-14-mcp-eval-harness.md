# MCP Eval Harness (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lightweight pytest harness that fails when any of the 7 MCP tools stops returning meaningful answers, starting with liveness, source-as-answer-key, and escape-hatch differential checks.

**Architecture:** Three files under `tests/`. Pure logic (the `EvalCase` model, the output checker, the source scanner) is unit-tested and runs on any machine including Windows. The graph-hitting eval tests connect to a live Memgraph and **auto-skip when none is reachable**, so they only really execute on the Mac that has the built Pinpoint graph. Cases are data, not code: adding a test = adding a row.

**Tech Stack:** Python 3.10+, pytest (already used by the project), the existing `mcp_server` package. No new dependencies.

---

## Environment note (read before starting)

Tasks are tagged **[anywhere]** or **[mac]**:
- **[anywhere]** — pure logic with unit tests; runs on Windows or Mac with no graph.
- **[mac]** — needs a populated Memgraph + the indexed source. On a machine with no graph these tests **skip** (not fail), so it is safe to commit them from Windows; they get exercised when you pull on the Mac and run `pytest tests/`.

Two environment variables are used by the [mac] tests (set them on the Mac):
- `MEMGRAPH_URI` (default `bolt://localhost:7687`)
- `CODE_GRAPH_REPO_ROOT` — absolute path to the indexed source (e.g. `/Users/il021250/dev/pinpoint`). If unset, the source-oracle tests generate zero cases and are simply absent.

---

## File Structure

- `tests/eval_cases.py` (create) — the `EvalCase` dataclass, the `check_output()` checker, the source scanner `discover_lua_definitions()`, and the case lists (liveness, differential) + tunable sample constants. The only file you curate.
- `tests/conftest.py` (create) — the session-scoped `engine` fixture that pings Memgraph and skips the suite when unreachable.
- `tests/test_eval.py` (create) — generic parametrized tests (`run_tool` dispatch + the liveness / oracle / differential test functions). Does not change when you add cases.
- `mcp_server/tools/composites.py` (modify) — fix the `find_impact` callers query that currently crashes Memgraph (Task 4).

`tests/smoke_test.py` stays as-is (a manual exploration script); the new files supersede it for automated checks.

---

## Task 1: Core model + output checker  [anywhere]

**Files:**
- Create: `tests/eval_cases.py`
- Test: `tests/test_eval_cases.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_cases.py
from tests.eval_cases import EvalCase, check_output


def test_missing_substring_is_reported():
    case = EvalCase("find_symbol", {"symbol_name": "foo"}, must_contain=["foo"], id="c1")
    failures = check_output("nothing here", case)
    assert failures and "foo" in failures[0]


def test_all_conditions_satisfied_returns_no_failures():
    case = EvalCase(
        "find_symbol", {"symbol_name": "foo"},
        must_contain=["foo", r"bar\.lua"], must_not_contain=["ERROR"], min_lines=2, id="c2",
    )
    output = "foo defined in\nbar.lua:10"
    assert check_output(output, case) == []


def test_must_not_contain_is_enforced():
    case = EvalCase("find_impact", {"symbol_or_file": "x"}, must_not_contain=["Traceback"], id="c3")
    failures = check_output("Traceback (most recent call last)", case)
    assert failures and "Traceback" in failures[0]


def test_none_output_is_a_failure():
    case = EvalCase("locate", {"description": "x"}, id="c4")
    assert check_output(None, case) == ["c4: tool returned None"]


def test_min_lines_counts_only_nonempty_lines():
    case = EvalCase("onboard_to", {"area": "x"}, min_lines=3, id="c5")
    failures = check_output("line1\n\nline2", case)  # only 2 non-empty lines
    assert failures and "min" in failures[0].lower() or ">=" in failures[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_eval_cases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.eval_cases'` (or ImportError for `EvalCase`).

- [ ] **Step 3: Write minimal implementation**

```python
# tests/eval_cases.py
"""Declarative eval cases for the MCP tool surface (data + pure helpers only)."""
from __future__ import annotations

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_eval_cases.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/eval_cases.py tests/test_eval_cases.py
git commit -m "test: add EvalCase model and output checker for MCP eval harness"
```

---

## Task 2: Source scanner (the answer key)  [anywhere]

**Files:**
- Modify: `tests/eval_cases.py`
- Test: `tests/test_eval_cases.py`

This finds real `(function_name, file_path)` pairs by reading Lua source directly — an independent answer key the graph tool is checked against. Lua only for Phase 1 (the core language); other languages are a later phase.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_cases.py  (append)
from tests.eval_cases import discover_lua_definitions


def test_discover_finds_global_and_local_lua_functions(tmp_path):
    f = tmp_path / "sample.lua"
    f.write_text(
        "function Helpers.get_session() end\n"
        "local function internal_helper() end\n"
        "function plain_global() end\n",
        encoding="utf-8",
    )
    found = discover_lua_definitions(str(tmp_path), limit=10)
    names = {name for name, _ in found}
    assert {"get_session", "internal_helper", "plain_global"} <= names
    # paths point at the real file
    assert all(path.endswith("sample.lua") for _, path in found)


def test_discover_returns_empty_for_missing_root():
    assert discover_lua_definitions("/no/such/dir", limit=10) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_eval_cases.py -k discover -v`
Expected: FAIL with `ImportError: cannot import name 'discover_lua_definitions'`.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/eval_cases.py  (append)
import pathlib

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_eval_cases.py -k discover -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/eval_cases.py tests/test_eval_cases.py
git commit -m "test: add independent Lua definition scanner as eval answer key"
```

---

## Task 3: Engine fixture that skips without a graph  [anywhere to write, [mac] to exercise]

**Files:**
- Create: `tests/conftest.py`

There is no pure unit test for pytest plumbing; verification is running the suite with no graph and seeing it skip.

- [ ] **Step 1: Write the fixture**

```python
# tests/conftest.py
"""Shared fixtures for the eval suite."""
import os

import pytest


@pytest.fixture(scope="session")
def engine():
    """Yield a QueryEngine connected to Memgraph, or skip the whole eval suite.

    Skips (never fails) when the driver is missing or no graph is reachable, so
    the graph-hitting tests are inert on machines without a built graph.
    """
    try:
        from mcp_server.query_engine import QueryEngine
    except Exception as exc:  # neo4j driver not installed, etc.
        pytest.skip(f"QueryEngine import failed: {exc}")

    uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
    eng = QueryEngine(uri)
    try:
        eng.query("RETURN 1 AS ok")  # forces a real connection
    except Exception as exc:
        eng.close()
        pytest.skip(f"no graph reachable at {uri}: {exc}")
    yield eng
    eng.close()
```

- [ ] **Step 2: Verify it skips cleanly with no graph**

Run (on a machine with no Memgraph, e.g. Windows): `python -m pytest tests/ -v`
Expected: existing pure tests PASS; no errors about connection refused (graph tests will only appear once Task 5/6 add them, and must show as SKIPPED, not ERROR).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add Memgraph engine fixture that skips when no graph is reachable"
```

---

## Task 4: Reproduce and fix the `find_impact` crash  [mac]

**Files:**
- Modify: `tests/eval_cases.py` (add liveness cases)
- Create: `tests/test_eval.py` (dispatch + liveness test)
- Modify: `mcp_server/tools/composites.py` (the callers query, around line 253)

**REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging for the fix — reproduce, isolate the offending Cypher clause, then change one thing. Do not apply a fix before the raw query reproduces the error.

- [ ] **Step 1: Add liveness cases + dispatch + the liveness test**

```python
# tests/eval_cases.py  (append)
# --- tunable sample anchors: confirmed-real symbols from a prior run; ---
# --- fill SAMPLE_FILE / SAMPLE_ENDPOINT on the Mac (see Task 5 Step 0).  ---
SAMPLE_SYMBOL = "get_current"      # a function known to exist in the graph
SAMPLE_FILE = None                 # e.g. "/abs/path/.../helpers.lua"
SAMPLE_ENDPOINT = None             # e.g. "/api/..." (a real Endpoint node)

LIVENESS_CASES = [
    EvalCase("find_symbol",      {"symbol_name": SAMPLE_SYMBOL},          min_lines=1, id="live-find_symbol"),
    EvalCase("get_code_snippet", {"name": SAMPLE_SYMBOL},                 min_lines=1, id="live-get_code_snippet"),
    EvalCase("find_impact",      {"symbol_or_file": SAMPLE_SYMBOL},       min_lines=1, id="live-find_impact"),
    EvalCase("locate",           {"description": "session info", "limit": 5}, min_lines=1, id="live-locate"),
    EvalCase("onboard_to",       {"area": "session_info"},                min_lines=1, id="live-onboard_to"),
    EvalCase("get_file_outline", {"file_path": SAMPLE_FILE},              min_lines=1, id="live-get_file_outline"),
    EvalCase("explain_flow",     {"endpoint": SAMPLE_ENDPOINT},           min_lines=1, id="live-explain_flow"),
]
```

```python
# tests/test_eval.py
"""Graph-hitting eval tests. Require the `engine` fixture (skips without a graph)."""
import pytest

from mcp_server.tools import composites, search, snippets
from tests.eval_cases import LIVENESS_CASES, check_output


def run_tool(engine, tool: str, inp: dict) -> str:
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
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: sample anchor not set (fill it in eval_cases.py)")
    output = run_tool(engine, case.tool, case.input)  # must not raise
    failures = check_output(output, case)
    assert not failures, "\n".join(failures)
```

- [ ] **Step 2: Run the liveness test — confirm `find_impact` fails the way `logs.txt` shows**

Run: `python -m pytest tests/test_eval.py::test_tool_is_alive -v`
Expected: most cases PASS; `live-find_impact` FAILS with `neo4j.exceptions.ClientError: ... Only nodes, edges, maps, temporal types and graphs have properties to be looked up.`

- [ ] **Step 3: Isolate the offending clause (systematic-debugging)**

Run the raw query directly to reproduce outside the tool, then bisect:

```bash
python - <<'PY'
from mcp_server.query_engine import QueryEngine
eng = QueryEngine()
q = """
MATCH (caller:Function)-[:CALLS*1..5]->(fn:Function)
WHERE fn.name CONTAINS $name
RETURN DISTINCT caller.name AS caller, caller.file AS file, fn.name AS callee
ORDER BY file LIMIT 100
"""
print(eng.query(q, name="get_current"))
PY
```
Confirm it raises the same error. Then re-run with the variable-length split out (candidate fix below) to confirm the error disappears before editing source.

- [ ] **Step 4: Apply the fix in `composites.py`**

Replace the callers query (currently around `composites.py:253`) with the split form that matches the target functions first, then expands callers into them:

```python
        callers = engine.query(f"""
            MATCH (fn:Function)
            WHERE fn.name CONTAINS $name
            WITH fn
            MATCH (caller:Function)-[:CALLS*1..{depth}]->(fn)
            RETURN DISTINCT caller.name AS caller, caller.file AS file, fn.name AS callee
            ORDER BY file
            LIMIT 100
        """, name=symbol_or_file)
```

If Step 3 shows the variable-length expansion itself is the trigger (not the planner ordering), fall back to direct callers only:

```python
        callers = engine.query("""
            MATCH (caller:Function)-[:CALLS]->(callee:Function)
            WHERE callee.name CONTAINS $name
            RETURN DISTINCT caller.name AS caller, caller.file AS file, callee.name AS callee
            ORDER BY file
            LIMIT 100
        """, name=symbol_or_file)
```

Pick whichever the Step 3 experiment proves resolves the error while still returning callers.

- [ ] **Step 5: Re-run the liveness test — all green**

Run: `python -m pytest tests/test_eval.py::test_tool_is_alive -v`
Expected: PASS for all cases whose anchors are set (`live-explain_flow` / `live-get_file_outline` may SKIP until Task 5 Step 0 fills their constants).

- [ ] **Step 6: Commit**

```bash
git add tests/eval_cases.py tests/test_eval.py mcp_server/tools/composites.py
git commit -m "fix: repair find_impact callers query; add liveness eval for all 7 tools"
```

---

## Task 5: Source-oracle test for `find_symbol`  [mac]

**Files:**
- Modify: `tests/test_eval.py`

This is the "is it telling the truth?" check: for real Lua definitions found by the independent scanner, `find_symbol` must point at the file that actually contains them.

- [ ] **Step 0: Fill the sample constants (one-time, semi-automatic)**

On the Mac, get a real file path and endpoint from the graph and paste them into `SAMPLE_FILE` / `SAMPLE_ENDPOINT` in `tests/eval_cases.py`:

```bash
python - <<'PY'
from mcp_server.query_engine import QueryEngine
eng = QueryEngine()
print("FILE:", eng.query("MATCH (f:File) WHERE f.language='lua' RETURN f.path AS p LIMIT 3"))
print("ENDPOINT:", eng.query("MATCH (e:Endpoint) RETURN e.path AS p LIMIT 3"))
PY
```
Also `export CODE_GRAPH_REPO_ROOT=/Users/il021250/dev/pinpoint` (your indexed source root).

- [ ] **Step 1: Write the oracle test**

```python
# tests/test_eval.py  (append)
import os
import pathlib

from tests.eval_cases import discover_lua_definitions

_REPO_ROOT = os.environ.get("CODE_GRAPH_REPO_ROOT", "")
_DEFS = discover_lua_definitions(_REPO_ROOT, limit=10) if _REPO_ROOT else []


@pytest.mark.skipif(not _DEFS, reason="CODE_GRAPH_REPO_ROOT not set or no Lua defs found")
@pytest.mark.parametrize("name,path", _DEFS, ids=[f"{n}" for n, _ in _DEFS])
def test_find_symbol_points_at_real_file(engine, name, path):
    out = search.find_symbol(engine, name)
    basename = pathlib.Path(path).name
    assert basename in out, (
        f"find_symbol({name!r}) did not mention {basename}; "
        f"the graph disagrees with the source. Output:\n{out}"
    )
```

- [ ] **Step 2: Run the oracle test**

Run: `CODE_GRAPH_REPO_ROOT=/Users/il021250/dev/pinpoint python -m pytest tests/test_eval.py::test_find_symbol_points_at_real_file -v`
Expected: PASS for each discovered definition. A failure means a real resolver/ingestion gap — investigate (that is the harness doing its job), and if it is a known acceptable gap, drop that name or record it in the case `note`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_eval.py tests/eval_cases.py
git commit -m "test: add source-as-answer-key oracle test for find_symbol"
```

---

## Task 6: Differential (escape-hatch) tests for the composites  [mac]

**Files:**
- Modify: `tests/eval_cases.py` (add differential cases)
- Modify: `tests/test_eval.py` (add differential test)

This is the "is the clever part clever?" check: the filtered answer must differ from the expanded one, proving middleware-collapse / centrality-rerank / primitive-summarisation actually happen.

- [ ] **Step 1: Add the differential cases**

```python
# tests/eval_cases.py  (append)
# Composite + input; escape_hatch=True must visibly change the result.
DIFFERENTIAL_CASES = [
    EvalCase("explain_flow", {"endpoint": SAMPLE_ENDPOINT},                 id="diff-explain_flow"),
    EvalCase("find_impact",  {"symbol_or_file": SAMPLE_SYMBOL},             id="diff-find_impact"),
    EvalCase("onboard_to",   {"area": "session_info"},                      id="diff-onboard_to"),
    EvalCase("locate",       {"description": "session info", "limit": 10},  id="diff-locate"),
]
```

- [ ] **Step 2: Write the differential test**

```python
# tests/test_eval.py  (append)
from tests.eval_cases import DIFFERENTIAL_CASES


@pytest.mark.parametrize("case", DIFFERENTIAL_CASES, ids=lambda c: c.id)
def test_escape_hatch_changes_output(engine, case):
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: sample anchor not set")
    filtered = run_tool(engine, case.tool, {**case.input, "escape_hatch": False})
    expanded = run_tool(engine, case.tool, {**case.input, "escape_hatch": True})
    assert filtered != expanded, (
        f"{case.id}: escape_hatch=True produced identical output — the "
        f"composite's filtering/rerank had no effect (or the chosen input has "
        f"nothing to filter; pick an input where it should)."
    )
```

- [ ] **Step 3: Run the differential test**

Run: `python -m pytest tests/test_eval.py::test_escape_hatch_changes_output -v`
Expected: PASS for composites whose anchors are set. If `diff-explain_flow` fails with identical output, the chosen endpoint may have no middleware to collapse — pick an endpoint that routes through middleware, or record the choice in the case `note`.

- [ ] **Step 4: Run the whole suite once**

Run: `python -m pytest tests/ -v`
Expected: pure tests PASS everywhere; graph tests PASS on the Mac, SKIP elsewhere.

- [ ] **Step 5: Commit**

```bash
git add tests/eval_cases.py tests/test_eval.py
git commit -m "test: add escape-hatch differential checks for the four composites"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** kind 1 (liveness) → Task 4; kind 2 (truth-vs-source) → Tasks 2+5; kind 4 (differential) → Task 6; `find_impact` crash reproduced+fixed → Task 4; clean skip with no graph → Task 3; cases-as-data → Task 1. Kinds 3 (ranking) and 5 (agent dogfood) are explicitly deferred in the spec — no tasks here, by design.
- **Placeholder scan:** the only intentional "fill-ins" are `SAMPLE_FILE` / `SAMPLE_ENDPOINT`, which are real data values that can only come from the live graph; Task 5 Step 0 gives the exact commands to obtain them. No vague "add error handling" steps.
- **Type/name consistency:** `EvalCase`, `check_output`, `discover_lua_definitions`, `run_tool` are defined once (Tasks 1/2/4) and used with the same signatures throughout. Tool kwarg names match the real signatures in `mcp_server/tools/` (`symbol_name`, `symbol_or_file`, `endpoint`, `area`, `description`, `name`, `file_path`).
- **Known caveat:** the `find_impact` fix in Task 4 offers two candidate queries because the exact Memgraph root cause must be confirmed against the live graph (Step 3); the task gates the edit on reproducing the error first, per systematic-debugging.
