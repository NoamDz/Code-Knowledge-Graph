# MCP Tool & Graph Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Several tasks ALSO require superpowers:systematic-debugging — flagged inline.

**Goal:** Fix the 4 broken / 1 partial MCP tools that BOB testing surfaced (`get_code_snippet`, `find_impact`, `onboard_to`, `explain_flow`, `get_file_outline`) and close the underlying graph-data gaps (Go functions, import edges, endpoint indexing), gated by eval cases built from the BOB answer key.

**Architecture:** Three phases. **Phase 0 (diagnostic, Mac)** inspects the *current* built graph and re-runs all 7 tools to produce a fact table classifying each failure as query-bug vs data-gap — because the code has changed since BOB tested and assumptions must be re-baselined. **Phase 1** turns the BOB answer key into eval cases (extends the harness in `tests/`). **Phase 2** fixes the MCP query/formatting layer. **Phase 3** fixes the graph builder/ingestion and rebuilds. A CHECKPOINT after Phase 0 confirms or adjusts every fix below against real data.

**Tech Stack:** Python 3.10+, Memgraph/Bolt (`neo4j` driver), Tree-sitter parsers, pytest. No new deps.

---

## Environment & evidence note (read first)

- **Source of requirements:** `research/code-graph-testing/` — BOB ran the real MCP server against Pinpoint. `answer-key.md` holds verified ground truth; `research-notes/scenario-*.md` hold the per-tool failures.
- **Staleness warning:** BOB's run predates recent "server fixes" commits. The *current* code already differs from what BOB tested (e.g. `onboard_to` has no obvious unbound-`f` bug now; the Go parser already emits functions). **Do not fix from BOB's notes alone — Phase 0 re-runs every tool to capture current behavior.**
- **Where it runs:** everything except Phase 1's pure-logic additions needs the **built Pinpoint graph on the Mac**. Set `MEMGRAPH_URI` and `CODE_GRAPH_REPO_ROOT`. The graph-hitting eval tests skip elsewhere (conftest already handles this).
- **Tag key:** **[mac]** needs the graph; **[anywhere]** is pure logic.

---

## File Structure

- `scripts/diagnose_graph.py` (create) — one-shot graph inspector: node/edge counts, path format, line-coverage, endpoint count, CALLS/IMPORTS edge endpoints, Go function coverage, name-format samples. Phase 0.
- `tests/eval_cases.py` (modify) — add `BOB_*` eval cases from the answer key. Phase 1.
- `tests/test_eval.py` (create if absent / modify) — graph-hitting eval tests (liveness + the BOB anchors). Builds on the harness already committed.
- `mcp_server/tools/snippets.py` (modify) — `get_code_snippet` line filter; `get_file_outline` empties. Phase 2.
- `mcp_server/tools/composites.py` (modify) — `find_impact` path+name+crash; `onboard_to` (if Phase 0 reconfirms a bug); `explain_flow` UX. Phase 2.
- `graph_builder/parsers/go_parser.py` and/or `graph_builder/ingestion/*.py` (modify) — Go functions / import edges / endpoints, **only what Phase 0 proves missing**. Phase 3.

---

## Phase 0 — Diagnostic & re-baseline [mac]

### Task 0.1: Graph inspector script

**Files:**
- Create: `scripts/diagnose_graph.py`

- [ ] **Step 1: Write the script**

```python
# scripts/diagnose_graph.py
"""Inspect the current Memgraph graph to classify MCP-tool failures.

Run on the machine with the built graph:
    python scripts/diagnose_graph.py
"""
import os
from mcp_server.query_engine import QueryEngine

Q = [
    ("node labels",        "MATCH (n) RETURN labels(n)[0] AS k, count(*) AS c ORDER BY c DESC"),
    ("edge types",         "MATCH ()-[r]->() RETURN type(r) AS k, count(*) AS c ORDER BY c DESC"),
    ("file path samples",  "MATCH (f:File) RETURN f.path AS k LIMIT 5"),
    ("function line cov",   "MATCH (n:Function) RETURN count(*) AS total, "
                            "sum(CASE WHEN n.line IS NULL THEN 1 ELSE 0 END) AS null_line"),
    ("endpoint count",     "MATCH (e:Endpoint) RETURN count(*) AS c"),
    ("endpoint samples",   "MATCH (e:Endpoint) RETURN e.path AS k LIMIT 10"),
    ("CALLS endpoints",    "MATCH (a)-[:CALLS]->(b) RETURN labels(a)[0] AS from_l, "
                            "labels(b)[0] AS to_l, count(*) AS c ORDER BY c DESC LIMIT 10"),
    ("IMPORTS count",      "MATCH (:File)-[:IMPORTS]->() RETURN count(*) AS c"),
    ("REQUIRES count",     "MATCH (:File)-[:REQUIRES]->() RETURN count(*) AS c"),
    ("go function cov",    "MATCH (f:File {language:'go'}) OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function) "
                            "RETURN count(DISTINCT f) AS go_files, count(fn) AS go_funcs"),
    ("name format: save",  "MATCH (n:Function) WHERE n.name CONTAINS 'save' RETURN n.name AS k LIMIT 15"),
]


def main():
    eng = QueryEngine(os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687"))
    for title, cypher in Q:
        print(f"\n=== {title} ===")
        try:
            for row in eng.query(cypher):
                print("  ", dict(row))
        except Exception as exc:
            print("   ERROR:", exc)
    eng.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and save the output**

Run: `python scripts/diagnose_graph.py | tee research/code-graph-testing/diagnostic-$(date +%F).txt`
Capture: are paths absolute? how many Functions have null line? are there Endpoint nodes? do CALLS go Function→Function? are there Go functions? how are method names stored (`X:save` vs `X.save` vs `save`)?

- [ ] **Step 3: Commit**

```bash
git add scripts/diagnose_graph.py research/code-graph-testing/diagnostic-*.txt
git commit -m "diag: add graph inspector and capture current-state baseline"
```

### Task 0.2: Re-baseline the 7 tools

- [ ] **Step 1: Run each tool with the BOB inputs, capture current behavior**

```python
python - <<'PY'
from mcp_server.query_engine import QueryEngine
from mcp_server.tools import composites, search, snippets
e = QueryEngine()
print("## find_symbol\n", search.find_symbol(e, "require_version")[:500])
print("## get_code_snippet\n", snippets.get_code_snippet(e, "require_version")[:500])
print("## get_file_outline policy\n", snippets.get_file_outline(e, "src/ato/structured_policy/policy.lua")[:500])
print("## find_impact file\n", composites.find_impact(e, "src/lib/lua/crypto/init.lua")[:500])
print("## find_impact symbol\n", composites.find_impact(e, "SessionDeviceData:save")[:500])
print("## onboard_to\n", composites.onboard_to(e, "src/ato")[:500])
print("## explain_flow\n", composites.explain_flow(e, "/api/auth/login")[:300])
PY
```

- [ ] **Step 2: Write the classification table** into `research/code-graph-testing/diagnostic-<date>.txt`: for each tool, current behavior (works / empty / crash + message) and verdict (query-bug | data-gap | already-fixed).

---

## CHECKPOINT (controller, after Phase 0)

Read the diagnostic output. For EACH fix task in Phases 2–3, confirm its stated root cause matches reality and adjust the code before dispatching. Specifically resolve:
1. **Paths absolute?** → confirms `find_impact`/`get_file_outline` need suffix matching.
2. **Endpoint count == 0?** → `explain_flow` is a *data gap* (nginx not indexed): Phase 3 Task 3.3 applies. If > 0, it's a UX/matching bug: Phase 2 Task 2.5 applies.
3. **Go functions present?** → if `go_funcs > 0`, the Go-functions gap is already fixed; drop Phase 3 Task 3.1.
4. **`onboard_to` still errors?** → if it works now, drop Phase 2 Task 2.3; else fix the exact failing query named in the error.
5. **Method-name format** (`X:save` vs `save`) → sets the matching strategy in `find_impact` Task 2.2.

If any tool already works, delete its task. If a root cause differs from below, edit the task before implementing.

---

## Phase 1 — BOB answer key → eval anchors [anywhere to write, [mac] to run]

### Task 1.1: Add BOB-derived eval cases

**Files:**
- Modify: `tests/eval_cases.py`
- Modify/Create: `tests/test_eval.py`

- [ ] **Step 1: Add anchor cases from the answer key**

```python
# tests/eval_cases.py  (append)
# Ground-truth anchors from research/code-graph-testing/answer-key.md (BOB-verified).
BOB_CASES = [
    EvalCase("find_symbol", {"symbol_name": "require_version"},
             must_contain=[r"loader/lua/init\.lua"], id="bob-find_symbol-require_version",
             note="answer-key S1: defined in src/core/loader/lua/init.lua:81"),
    EvalCase("get_code_snippet", {"name": "require_version"},
             must_contain=[r"function .*require_version"], must_not_contain=["line info not available"],
             id="bob-snippet-require_version", note="answer-key S1: must return the actual source"),
    EvalCase("get_file_outline", {"file_path": "src/ato/models/session_device_data.lua"},
             must_contain=["save", "find_by_session_id"], id="bob-outline-session_device_data",
             note="answer-key S2: known public functions"),
    EvalCase("find_impact", {"symbol_or_file": "src/ato/models/session_device_data.lua"},
             must_not_contain=[r"\(none\)", "Traceback"], id="bob-impact-session_device_data",
             note="answer-key S2: 100+ usages exist; must not be empty/crash"),
    EvalCase("onboard_to", {"area": "src/ato"},
             must_contain=["models", "handlers"], must_not_contain=["Unbound variable", "Traceback"],
             id="bob-onboard-ato", note="answer-key S3: ATO has models/, handlers/, etc."),
]
```

- [ ] **Step 2: Wire the cases into a parametrized test** (extend the liveness test added in the harness plan; if `tests/test_eval.py` does not yet exist, create it per `docs/superpowers/plans/2026-06-14-mcp-eval-harness.md` Task 4 first, then add):

```python
# tests/test_eval.py  (append)
import pytest
from tests.eval_cases import BOB_CASES, check_output


@pytest.mark.parametrize("case", BOB_CASES, ids=lambda c: c.id)
def test_bob_anchor(engine, case):
    if any(v is None for v in case.input.values()):
        pytest.skip(f"{case.id}: anchor not set")
    out = run_tool(engine, case.tool, case.input)  # run_tool defined in harness Task 4
    failures = check_output(out, case)
    assert not failures, "\n".join(failures)
```

- [ ] **Step 3: Run — expect RED for the broken tools** (this is the failing-test baseline that each Phase-2 fix will turn green):

Run: `python -m pytest tests/test_eval.py -k bob -v`
Expected: `find_symbol` passes; `get_code_snippet`, `find_impact`, possibly `onboard_to` FAIL. This RED state is correct — it proves the anchors catch the real bugs.

- [ ] **Step 4: Commit**

```bash
git add tests/eval_cases.py tests/test_eval.py
git commit -m "test: add BOB answer-key anchors as eval cases (red until tools fixed)"
```

---

## Phase 2 — MCP-layer fixes [mac]

### Task 2.1: Fix `get_code_snippet` line filter

**Files:** Modify `mcp_server/tools/snippets.py:32-39`

Root cause: the match `n.name CONTAINS $name` includes call-reference / placeholder Function nodes that have `line = NULL`; with `LIMIT 10` the real definition is crowded out, so every shown match reports "line info not available".

- [ ] **Step 1: Confirm the bob-snippet test is RED**

Run: `python -m pytest tests/test_eval.py::test_bob_anchor -k snippet -v` → FAIL.

- [ ] **Step 2: Fix the query to prefer real definitions with line info**

```python
    results = engine.query("""
        MATCH (n)
        WHERE (n:Function OR n:Class)
          AND n.name CONTAINS $name
          AND n.line IS NOT NULL
        RETURN n.name AS name, n.file AS file, n.line AS line,
               n.line_end AS line_end, labels(n) AS labels
        ORDER BY CASE WHEN n.name = $name THEN 0 ELSE 1 END, n.line
        LIMIT 10
    """, name=name)
```

(Exact-name matches first, then partial; only nodes that have a line. Keep the rest of the function unchanged.)

- [ ] **Step 3: Verify GREEN**

Run: `python -m pytest tests/test_eval.py::test_bob_anchor -k snippet -v` → PASS. Also spot-check: `python -c "from mcp_server.query_engine import QueryEngine as Q; from mcp_server.tools import snippets; print(snippets.get_code_snippet(Q(),'require_version'))"` shows real Lua source.

- [ ] **Step 4: Commit** `git commit -am "fix: get_code_snippet skips line-less nodes, prefers exact definitions"`

### Task 2.2: Fix `find_impact` path matching, name matching, and the crash [systematic-debugging]

**Files:** Modify `mcp_server/tools/composites.py:230-288`

**REQUIRED SUB-SKILL: superpowers:systematic-debugging** for the crash. Root causes (confirm against Phase-0 facts): (a) file branch uses exact `{path: $path}` so relative input never matches absolute stored paths; (b) symbol branch matches `fn.name CONTAINS $name` but methods are stored with `:`/qualified names; (c) the variable-length callers query crashed in an earlier run.

- [ ] **Step 1: Confirm the bob-impact test is RED** — `python -m pytest tests/test_eval.py::test_bob_anchor -k impact -v`.

- [ ] **Step 2: Fix the file branch to match by suffix** (mirror the working fallback already in `get_file_outline`):

```python
    if looks_like_path:
        file_path = symbol_or_file.replace("\\", "/")
        # Resolve to the stored (absolute) path via suffix match first.
        resolved = engine.query("""
            MATCH (f:File)
            WHERE f.path = $path OR f.path ENDS WITH $suffix
            RETURN f.path AS path LIMIT 1
        """, path=file_path, suffix=file_path if file_path.startswith("/") else "/" + file_path)
        target = resolved[0]["path"] if resolved else file_path
        deps = engine.query(f"""
            MATCH (dep:File)-[:IMPORTS|REQUIRES*1..{depth}]->(f:File {{path: $path}})
            RETURN DISTINCT dep.path AS path, dep.language AS language
            ORDER BY dep.path
        """, path=target)
        # ... rest unchanged, but pass `target` to get_implicit_dependencies/find_impacted_files
```

- [ ] **Step 3: Isolate the symbol-branch crash before editing it.** Run the raw query (Task 0.2 style) with `name="save"`; if it raises `Only nodes, edges, maps... properties`, bisect by removing `ORDER BY file`, then the `*1..N` expansion, then each `caller.*` projection, to find the offending clause. Record which clause triggers it.

- [ ] **Step 4: Fix the symbol branch** — match the bare name and (per Step 3) restructure to avoid the crash. Candidate (confirm edge direction Function→Function from Phase 0 "CALLS endpoints"):

```python
    else:
        # bare name: strip module/table prefix so "Mod:save" and "Mod.save" match "save"
        bare = symbol_or_file.split(":")[-1].split(".")[-1]
        callers = engine.query(f"""
            MATCH (fn:Function)
            WHERE fn.name CONTAINS $bare
            WITH fn
            MATCH (caller:Function)-[:CALLS*1..{depth}]->(fn)
            RETURN DISTINCT caller.name AS caller, caller.file AS file, fn.name AS callee
            ORDER BY file
            LIMIT 100
        """, bare=bare)
        # files_defining: also match by bare name
        files_defining = engine.query("""
            MATCH (f:File)-[:DEFINES]->(fn:Function)
            WHERE fn.name = $bare OR fn.name ENDS WITH $dotted
            RETURN DISTINCT f.path AS path LIMIT 5
        """, bare=bare, dotted="." + bare)
        # ... rest unchanged
```

If Step 3 proves variable-length expansion is the trigger, fall back to depth-1 callers (`-[:CALLS]->`).

- [ ] **Step 5: Verify GREEN** — `python -m pytest tests/test_eval.py::test_bob_anchor -k impact -v` PASS; also run `find_impact` for both a file and a symbol manually and confirm non-empty, no traceback.

- [ ] **Step 6: Commit** `git commit -am "fix: find_impact suffix path match, bare-name symbol match, resolve callers crash"`

### Task 2.3: Re-confirm and fix `onboard_to` (only if Phase 0 shows it still errors)

**Files:** Modify `mcp_server/tools/composites.py:295-374`

- [ ] **Step 1:** If Phase-0 re-baseline shows `onboard_to` returns a result with no "Unbound variable"/Traceback, **delete this task** (already fixed) and mark the bob-onboard test expectation accordingly. Otherwise continue.
- [ ] **Step 2:** Reproduce the exact error; the message names the failing clause. The likely culprit is an f-string-interpolated query where a `WITH` drops `f` before a later reference — fix by carrying the needed variable through the `WITH`, or by splitting into separate `MATCH` blocks that each rebind `f:File`.
- [ ] **Step 3:** Verify `python -m pytest tests/test_eval.py::test_bob_anchor -k onboard -v` PASS.
- [ ] **Step 4:** Commit `git commit -am "fix: onboard_to Cypher scoping error"`.

### Task 2.4: Fix `get_file_outline` empty-result cases

**Files:** Modify `mcp_server/tools/snippets.py:105-200`

Root cause (confirm via Phase 0): files like `policy.lua` returned empty though `locate` finds them. Either (a) suffix fallback returned >1 candidate and bailed, or (b) the File node has no `DEFINES` edges. The current suffix fallback uses `LIMIT 2` and refuses when ambiguous.

- [ ] **Step 1:** Reproduce: `get_file_outline("src/ato/structured_policy/policy.lua")`. Inspect whether the File node exists and how many `DEFINES` edges it has (`MATCH (f:File) WHERE f.path ENDS WITH '/policy.lua' RETURN f.path, size((f)-[:DEFINES]->())`).
- [ ] **Step 2:** If it's an ambiguity/path issue, make the suffix match prefer an exact tail segment and, when multiple, pick the shortest path or list candidates with their DEFINES counts instead of bailing. If the File genuinely has no DEFINES edges, that is a data gap → record for Phase 3.
- [ ] **Step 3:** Add an eval case for the previously-empty file once it works; verify GREEN.
- [ ] **Step 4:** Commit `git commit -am "fix: get_file_outline resolves ambiguous/relative paths"`.

### Task 2.5: `explain_flow` discovery UX (only if Phase 0 shows Endpoint nodes EXIST)

**Files:** Modify `mcp_server/tools/composites.py:112-133`

- [ ] **Step 1:** If Phase-0 endpoint count is 0, **skip this task** — it's a data gap handled in Phase 3 Task 3.3. If endpoints exist, the failure is exact-match: an agent can't guess exact paths.
- [ ] **Step 2:** On "not found", return helpful guidance: list up to ~15 closest endpoints (substring/edit-distance on `e.path`) so the agent can retry. Keep the happy path unchanged.
- [ ] **Step 3:** Add an eval case using a real endpoint path from the Phase-0 endpoint samples; verify GREEN.
- [ ] **Step 4:** Commit `git commit -am "feat: explain_flow suggests near-match endpoints when exact path is absent"`.

---

## Phase 3 — Graph builder / ingestion gaps [mac] (gated by Phase-0 verdicts)

### Task 3.1: Go function ingestion (only if Phase-0 `go_funcs == 0`)

The Go parser already emits `FunctionDef` for `function_declaration` and `method_declaration` (`go_parser.py:282-340`), so missing Go functions is an **ingestion** gap, not a parser gap.

- [ ] **Step 1:** Verify with a unit test that the parser returns functions for a Go fixture: add `graph_builder/tests/test_go_functions.py` parsing a small `.go` string and asserting `parse_go_file` yields the expected `FunctionDef` names. Run it ([anywhere], no graph).
- [ ] **Step 2:** If the parser is fine, inspect the ingestion path (`graph_builder/ingestion/`) for where `FunctionDef`s become `Function` nodes + `DEFINES` edges, and confirm Go files flow through it. Fix the gap (e.g. a language guard that skips Go).
- [ ] **Step 3:** Rebuild affected files and re-run `scripts/diagnose_graph.py`; confirm `go_funcs > 0`.
- [ ] **Step 4:** Commit.

### Task 3.2: Import/REQUIRES edge coverage (only if Phase-0 IMPORTS+REQUIRES counts are ~0)

- [ ] **Step 1:** From Phase 0, if import edges are near-zero but `find_symbol`/`locate` work, the gap is ingestion of `ImportRef` → `IMPORTS`/`REQUIRES` edges. Add/confirm a unit test that the resolver+ingestion produce import edges for a known file.
- [ ] **Step 2:** Fix the ingestion/resolution step; rebuild; confirm counts via the diagnostic.
- [ ] **Step 3:** Commit.

### Task 3.3: Endpoint / nginx indexing (only if Phase-0 endpoint count == 0)

- [ ] **Step 1:** Confirm `config.yml` used for the build sets `nginx_conf` (or `lua_package_paths`) so `nginx_parser.py` runs. If unset, that is the fix: document it in README and rebuild with it set.
- [ ] **Step 2:** If `nginx_conf` is set but no Endpoint nodes appear, add a parser unit test for `nginx_parser.py` against a sample location block and fix extraction.
- [ ] **Step 3:** Rebuild; confirm endpoint count > 0; then `explain_flow` Task 2.5 becomes applicable.
- [ ] **Step 4:** Commit.

### Task 3.4: Re-run the full eval suite

- [ ] **Step 1:** `python -m pytest tests/ -v` on the Mac. All BOB anchors GREEN; pure-logic tests GREEN.
- [ ] **Step 2:** Re-run `scripts/diagnose_graph.py` and update the diagnostic file. Commit.

---

## Self-Review (plan author)

- **Spec coverage:** all 5 BOB-flagged tools have a fix task (2.1–2.5) + an eval anchor (1.1); data gaps (Go funcs, imports, endpoints) → Phase 3; "code changed since BOB" risk → Phase 0 re-baseline + CHECKPOINT.
- **Placeholders:** Phase 0 + Phase 1 + Task 2.1 are fully concrete. Tasks 2.2/2.4/3.x are intentionally diagnostic-gated (the exact fix depends on the live graph schema, which is not available where this plan was written); each gives a concrete reproduction, a candidate fix with code, and a verification gate — not vague "handle it" steps. This is deliberate and noted, not an omission.
- **Consistency:** `run_tool`, `EvalCase`, `check_output` come from the harness plan (`2026-06-14-mcp-eval-harness.md`); this plan assumes that harness's Task 4 (`tests/test_eval.py` + `run_tool`) exists or is created first.
- **Ordering:** Phase 0 (facts) → CHECKPOINT (adjust) → Phase 1 (red anchors) → Phase 2 (MCP fixes, each red→green) → Phase 3 (data gaps + rebuild) → full green. Each fix is gated by an eval anchor flipping red→green.
