# Quick Fixes V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 resolver/schema issues: write 6 missing edge properties, fix dynamic prefix boundary matching, auto-detect base module methods, add Python package root detection, parse Go go.mod for ~90% import resolution, parse Ruby Gemfile for gem classification, and update schema.

**Architecture:** Targeted fixes to existing resolvers (dynamic_prefix, base_inheritance, go_resolver, ruby_resolver, python_resolver) and writer (add properties to existing upsert methods). No new resolvers needed.

**Tech Stack:** Python, existing resolver/writer infrastructure, go.mod/Gemfile parsing

---

## File Structure

| File | Action | Tasks |
|------|--------|-------|
| `graph_builder/ingestion/writer.py` | Modify | 1, 7 |
| `graph_builder/ingestion/schema.py` | Modify | 7 |
| `graph_builder/resolvers/dynamic_prefix_resolver.py` | Modify | 2 |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Modify | 3 |
| `graph_builder/resolvers/python_resolver.py` | Modify | 4 |
| `graph_builder/resolvers/go_resolver.py` | Modify | 5 |
| `graph_builder/resolvers/ruby_resolver.py` | Modify | 6 |
| `graph_builder/main.py` | Modify | 1 (metatable ingestion) |
| `graph_builder/tests/test_quick_fixes_v2.py` | Create | All 7 tasks |
| `graph_builder/tests/fixtures/lua/metatable_child.lua` | Create | 1 |
| `graph_builder/tests/fixtures/lua/base_handler.lua` | Create | 3 |
| `graph_builder/tests/fixtures/lua/child_handler.lua` | Create | 3 |
| `graph_builder/tests/fixtures/python/nested_pkg/` | Create | 4 |
| `graph_builder/tests/fixtures/go/go.mod` | Create | 5 |
| `graph_builder/tests/fixtures/go/common/utils.go` | Create | 5 |
| `graph_builder/tests/fixtures/ruby/Gemfile` | Create | 6 |

---

## Task 1: Write Missing Edge Properties to Graph

Six fields are extracted by parsers but never written to Memgraph. Additionally, `CallRef.classification` is written to unresolved CALLS edges but NOT to resolved CALLS edges. This task adds them all to `writer.py` and wires metatable inheritance edges into the build pipeline.

**Files:**
- Modify: `graph_builder/ingestion/writer.py` (lines 119-172 for query templates, line 185-202 for `upsert_function`, line 204-237 for `upsert_class`, line 241-246 for `upsert_import`, line 260-281 for `upsert_call`, line 302-309 for `upsert_ctx_access`, line 390-467 for `ingest_file_ast`)
- Modify: `graph_builder/main.py` (after line 361 to wire metatable ingestion)
- Create: `graph_builder/tests/fixtures/lua/metatable_child.lua`
- Create (start): `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Create test fixtures

- [ ] **1.1: Create Lua fixture with metatable inheritance**

Create `graph_builder/tests/fixtures/lua/metatable_child.lua`:

```lua
-- Child module that inherits via metatable from a base handler
local base_handler = require("common.base.lua.handler")

local _M = {}
local mt = { __index = base_handler }

function _M.new()
    local self = setmetatable({}, mt)
    return self
end

function _M:process(request)
    local result = self:validate(request)
    return result
end

return setmetatable(_M, { __index = base_handler })
```

### Step 2: Write tests

- [ ] **1.2: Create test file with property-writing tests**

Create `graph_builder/tests/test_quick_fixes_v2.py`:

```python
"""Tests for the quick-fixes-v2 bundle (Tasks 1-7).

Run with: python -m pytest graph_builder/tests/test_quick_fixes_v2.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import (
    FileAST, FunctionDef, ImportRef, CallRef, ContextAccess, ClassDef, ModuleInfo, ModulePatternType,
)
from graph_builder.ingestion.writer import GraphWriter

LUA_FIXTURES = Path(__file__).parent / "fixtures" / "lua"
PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"
GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"
RUBY_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"


# ───────────────────────────────────────────────────────────────
# Task 1: Missing edge properties
# ───────────────────────────────────────────────────────────────

class TestEdgeProperties:
    """Test that extracted-but-not-written properties are now written."""

    def _make_writer(self):
        """Create a GraphWriter with mocked driver (no Memgraph needed)."""
        with patch("graph_builder.ingestion.writer.GraphDatabase"):
            writer = GraphWriter(uri="bolt://fake:7687")
            writer._run = MagicMock()
            # Track buffered items directly
            return writer

    def test_1a_resolved_call_has_classification_and_confidence(self):
        """Resolved CALLS edges should include classification and resolution_confidence."""
        writer = self._make_writer()

        ast = FileAST(
            file_path="/repo/handler.lua", language="lua",
            calls=[
                CallRef(
                    caller_function="M:process",
                    callee_string="redis.get",
                    line=10,
                    resolved_module="resty.redis",
                    resolved_function="get",
                    resolved_file_path="/repo/lib/redis.lua",
                    resolution_confidence="binding",
                    classification=None,
                ),
            ],
        )
        resolved_imports = {"resty.redis": "/repo/lib/redis.lua"}
        writer.ingest_file_ast(ast, resolved_imports)
        writer.flush_all()

        # Check that CALLS_resolved buffer included confidence and classification
        resolved_batch = writer._edge_buffers.get("CALLS_resolved", [])
        # Flush already happened, check what was buffered by inspecting the query
        # The edge template must have resolution_confidence and classification fields
        query = writer._edge_queries["CALLS_resolved"]
        assert "resolution_confidence" in query, \
            "CALLS_resolved query template missing resolution_confidence"
        assert "classification" in query, \
            "CALLS_resolved query template missing classification"

    def test_1b_imports_edge_has_local_binding(self):
        """IMPORTS edges should include local_binding property."""
        writer = self._make_writer()
        query = writer._edge_queries["IMPORTS"]
        assert "local_binding" in query, \
            "IMPORTS query template missing local_binding"

    def test_1c_function_node_has_decorators(self):
        """Function nodes should include decorators list property."""
        writer = self._make_writer()
        query = writer._node_queries["Function"]
        assert "decorators" in query, \
            "Function node query template missing decorators"

    def test_1d_class_node_has_is_interface(self):
        """Class nodes should include is_interface boolean property."""
        writer = self._make_writer()
        query = writer._node_queries["Class"]
        assert "is_interface" in query, \
            "Class node query template missing is_interface"

    def test_1e_metatable_inheritance_method_exists(self):
        """GraphWriter should have upsert_metatable_inheritance method."""
        writer = self._make_writer()
        assert hasattr(writer, "upsert_metatable_inheritance"), \
            "GraphWriter missing upsert_metatable_inheritance method"

    def test_1f_ctx_access_has_scope(self):
        """CTX_READS/CTX_WRITES edges should include scope property."""
        writer = self._make_writer()
        # upsert_ctx_access should accept scope parameter
        import inspect
        sig = inspect.signature(writer.upsert_ctx_access)
        assert "scope" in sig.parameters, \
            "upsert_ctx_access missing scope parameter"

    def test_1e_metatable_ingestion_creates_edge(self):
        """ingest_file_ast should create INHERITS_VIA_METATABLE edges from metatable_parents."""
        writer = self._make_writer()

        ast = FileAST(
            file_path="/repo/child.lua", language="lua",
            module_name="handlers.child",
            metatable_parents={"_M": "common.base.lua.handler"},
        )
        writer.ingest_file_ast(ast, {})
        writer.flush_all()

        # upsert_metatable_inheritance should have been called
        writer._run.assert_any_call(
            unittest.mock.ANY,
            child_file="/repo/child.lua",
            parent_module="common.base.lua.handler",
            table_var="_M",
        )
```

Fix the import at the top — add `import unittest.mock` after the other imports. Actually, let's use a cleaner approach:

```python
    def test_1e_metatable_ingestion_creates_edge(self):
        """ingest_file_ast should create INHERITS_VIA_METATABLE edges from metatable_parents."""
        writer = self._make_writer()

        ast = FileAST(
            file_path="/repo/child.lua", language="lua",
            module_name="handlers.child",
            metatable_parents={"_M": "common.base.lua.handler"},
        )
        writer.ingest_file_ast(ast, {})
        writer.flush_all()

        # Check that _run was called with a query containing INHERITS_VIA_METATABLE
        calls = writer._run.call_args_list
        meta_calls = [c for c in calls if "INHERITS_VIA_METATABLE" in str(c)]
        assert len(meta_calls) >= 1, (
            f"Expected INHERITS_VIA_METATABLE edge creation, got calls: "
            f"{[str(c)[:80] for c in calls]}"
        )
```

### Step 3: Run tests (expect failure)

- [ ] **1.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestEdgeProperties -xvs
```

All tests should fail: resolved CALLS edges lack `resolution_confidence`/`classification`, IMPORTS lacks `local_binding`, Function lacks `decorators`, Class lacks `is_interface`, `upsert_metatable_inheritance` doesn't exist, and `upsert_ctx_access` lacks `scope`.

### Step 4: Implement the fixes

- [ ] **1.4a: Add `resolution_confidence` and `classification` to resolved CALLS edges**

In `graph_builder/ingestion/writer.py`, modify the `CALLS_resolved` query template at line 162-164:

```python
# Current (line 162-164):
        "CALLS_resolved": """
            UNWIND $batch AS row
            MERGE (a:Function {name: row.from_func, file: row.from_file})
            MERGE (b:Function {name: row.to_func, file: row.to_file})
            MERGE (a)-[:CALLS {line: row.line, is_pcall: row.is_pcall}]->(b)
        """,

# Replace with:
        "CALLS_resolved": """
            UNWIND $batch AS row
            MERGE (a:Function {name: row.from_func, file: row.from_file})
            MERGE (b:Function {name: row.to_func, file: row.to_file})
            MERGE (a)-[:CALLS {line: row.line, is_pcall: row.is_pcall,
                               resolution_confidence: row.resolution_confidence,
                               classification: row.classification}]->(b)
        """,
```

Then modify `upsert_call()` (line 260-281) to pass the new fields to resolved edges:

```python
# Current (line 260-281):
    def upsert_call(self, from_func: str, from_file: str,
                    to_func: str, to_file: str | None = None,
                    line: int = 0, is_pcall: bool = False,
                    classification: str | None = None):
        if to_file:
            self._buffer_edge("CALLS_resolved", {
                "from_func": from_func,
                "from_file": from_file,
                "to_func": to_func,
                "to_file": to_file,
                "line": line,
                "is_pcall": is_pcall,
            })

# Replace with:
    def upsert_call(self, from_func: str, from_file: str,
                    to_func: str, to_file: str | None = None,
                    line: int = 0, is_pcall: bool = False,
                    classification: str | None = None,
                    resolution_confidence: str | None = None):
        if to_file:
            self._buffer_edge("CALLS_resolved", {
                "from_func": from_func,
                "from_file": from_file,
                "to_func": to_func,
                "to_file": to_file,
                "line": line,
                "is_pcall": is_pcall,
                "resolution_confidence": resolution_confidence,
                "classification": classification,
            })
```

Then update `ingest_file_ast()` (around line 427-432) to pass the new fields:

```python
# Current (line 427-432):
            self.upsert_call(
                call.caller_function, ast.file_path,
                to_func, to_file,
                call.line, call.is_pcall_wrapped,
                call.classification,
            )

# Replace with:
            self.upsert_call(
                call.caller_function, ast.file_path,
                to_func, to_file,
                call.line, call.is_pcall_wrapped,
                call.classification,
                call.resolution_confidence,
            )
```

- [ ] **1.4b: Add `local_binding` to IMPORTS edges**

In `graph_builder/ingestion/writer.py`, modify the `IMPORTS` edge query template at line 154-159:

```python
# Current (line 154-159):
        "IMPORTS": """
            UNWIND $batch AS row
            MATCH (a:File {path: row.from_file})
            MATCH (b:File {path: row.to_file})
            MERGE (a)-[r:IMPORTS {module: row.module}]->(b)
        """,

# Replace with:
        "IMPORTS": """
            UNWIND $batch AS row
            MATCH (a:File {path: row.from_file})
            MATCH (b:File {path: row.to_file})
            MERGE (a)-[r:IMPORTS {module: row.module}]->(b)
            SET r.local_binding = row.local_binding
        """,
```

Then modify `upsert_import()` (line 241-246) to accept and pass `local_binding`:

```python
# Current (line 241-246):
    def upsert_import(self, from_file: str, to_file: str, module_string: str):
        self._buffer_edge("IMPORTS", {
            "from_file": from_file,
            "to_file": to_file,
            "module": module_string,
        })

# Replace with:
    def upsert_import(self, from_file: str, to_file: str, module_string: str,
                      local_binding: str | None = None):
        self._buffer_edge("IMPORTS", {
            "from_file": from_file,
            "to_file": to_file,
            "module": module_string,
            "local_binding": local_binding,
        })
```

Then update `ingest_file_ast()` (around line 414-416) to pass `local_binding`:

```python
# Current (line 414-416):
            if resolved_path:
                self.upsert_import(ast.file_path, resolved_path, imp.module_string)

# Replace with:
            if resolved_path:
                self.upsert_import(ast.file_path, resolved_path, imp.module_string,
                                   local_binding=imp.local_binding)
```

- [ ] **1.4c: Add `decorators` to Function nodes**

In `graph_builder/ingestion/writer.py`, modify the `Function` node query template at line 119-128:

```python
# Current (line 119-128):
        "Function": """
            UNWIND $batch AS row
            MERGE (fn:Function {name: row.name, file: row.file})
            SET fn.line = row.line,
                fn.line_end = row.line_end,
                fn.visibility = row.visibility,
                fn.is_method = row.is_method,
                fn.params = row.params,
                fn.qualified_name = row.qualified_name
        """,

# Replace with:
        "Function": """
            UNWIND $batch AS row
            MERGE (fn:Function {name: row.name, file: row.file})
            SET fn.line = row.line,
                fn.line_end = row.line_end,
                fn.visibility = row.visibility,
                fn.is_method = row.is_method,
                fn.params = row.params,
                fn.qualified_name = row.qualified_name,
                fn.decorators = row.decorators
        """,
```

Then modify `upsert_function()` (line 185-202) to include `decorators` in the params dict:

```python
# Current (line 186-195):
        params = {
            "name": func.name,
            "file": file_path,
            "line": func.line,
            "line_end": func.line_end,
            "visibility": func.visibility,
            "is_method": func.is_method,
            "params": func.params,
            "qualified_name": func.qualified_name,
        }

# Replace with:
        params = {
            "name": func.name,
            "file": file_path,
            "line": func.line,
            "line_end": func.line_end,
            "visibility": func.visibility,
            "is_method": func.is_method,
            "params": func.params,
            "qualified_name": func.qualified_name,
            "decorators": func.decorators,
        }
```

- [ ] **1.4d: Add `is_interface` to Class nodes**

In `graph_builder/ingestion/writer.py`, modify the `Class` node query template at line 129-138:

```python
# Current (line 129-138):
        "Class": """
            UNWIND $batch AS row
            MERGE (c:Class {name: row.name, file: row.file})
            SET c.line = row.line,
                c.line_end = row.line_end,
                c.parent_class = row.parent_class,
                c.mixins = row.mixins,
                c.methods = row.methods,
                c.qualified_name = row.qualified_name
        """,

# Replace with:
        "Class": """
            UNWIND $batch AS row
            MERGE (c:Class {name: row.name, file: row.file})
            SET c.line = row.line,
                c.line_end = row.line_end,
                c.parent_class = row.parent_class,
                c.mixins = row.mixins,
                c.methods = row.methods,
                c.qualified_name = row.qualified_name,
                c.is_interface = row.is_interface
        """,
```

Then modify `upsert_class()` (line 204-220) to include `is_interface`:

```python
# Current (line 205-214):
        params = {
            "name": cls.name,
            "file": file_path,
            "line": cls.line,
            "line_end": cls.line_end,
            "parent_class": cls.parent_class,
            "mixins": cls.mixins,
            "methods": cls.methods,
            "qualified_name": cls.qualified_name,
        }

# Replace with:
        params = {
            "name": cls.name,
            "file": file_path,
            "line": cls.line,
            "line_end": cls.line_end,
            "parent_class": cls.parent_class,
            "mixins": cls.mixins,
            "methods": cls.methods,
            "qualified_name": cls.qualified_name,
            "is_interface": cls.is_interface,
        }
```

- [ ] **1.4e: Create `upsert_metatable_inheritance()` method and wire into `ingest_file_ast()`**

In `graph_builder/ingestion/writer.py`, add a new method after `upsert_shared_dict_access()` (after line 318):

```python
    def upsert_metatable_inheritance(self, child_file: str, parent_module: str,
                                      table_var: str):
        """Create an INHERITS_VIA_METATABLE edge from child File to parent Module."""
        self._run("""
            MERGE (child:File {path: $child_file})
            MERGE (parent:Module {name: $parent_module})
            MERGE (child)-[:INHERITS_VIA_METATABLE {table_var: $table_var}]->(parent)
        """, child_file=child_file, parent_module=parent_module, table_var=table_var)
```

Then in `ingest_file_ast()`, add metatable inheritance ingestion after the imports section (after line 418, before the `# Calls` comment):

```python
        # Metatable inheritance (Lua-specific)
        for table_var, parent_module in ast.metatable_parents.items():
            self.upsert_metatable_inheritance(ast.file_path, parent_module, table_var)
```

- [ ] **1.4f: Add `scope` to `upsert_ctx_access()`**

In `graph_builder/ingestion/writer.py`, modify `upsert_ctx_access()` (line 302-309):

```python
# Current (line 302-309):
    def upsert_ctx_access(self, field_name: str, access_type: str,
                           function: str, file_path: str, line: int):
        edge_type = "CTX_WRITES" if access_type == "write" else "CTX_READS"
        self._run(f"""
            MERGE (k:ContextKey {{name: $field}})
            MERGE (fn:Function {{name: $func, file: $file}})
            MERGE (fn)-[:{edge_type} {{line: $line}}]->(k)
        """, field=field_name, func=function, file=file_path, line=line)

# Replace with:
    def upsert_ctx_access(self, field_name: str, access_type: str,
                           function: str, file_path: str, line: int,
                           scope: str | None = None):
        edge_type = "CTX_WRITES" if access_type == "write" else "CTX_READS"
        self._run(f"""
            MERGE (k:ContextKey {{name: $field}})
            MERGE (fn:Function {{name: $func, file: $file}})
            MERGE (fn)-[:{edge_type} {{line: $line, scope: $scope}}]->(k)
        """, field=field_name, func=function, file=file_path, line=line, scope=scope)
```

Then update `ingest_file_ast()` (around line 435-439) to pass `scope`:

```python
# Current (line 435-439):
        for ctx in ast.ctx_accesses:
            self.upsert_ctx_access(
                ctx.field_name, ctx.access_type,
                ctx.function, ast.file_path, ctx.line,
            )

# Replace with:
        for ctx in ast.ctx_accesses:
            self.upsert_ctx_access(
                ctx.field_name, ctx.access_type,
                ctx.function, ast.file_path, ctx.line,
                scope=ctx.scope,
            )
```

### Step 5: Run tests (expect pass)

- [ ] **1.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestEdgeProperties -xvs
```

### Step 6: Commit

- [ ] **1.6: Commit**

```bash
git add graph_builder/ingestion/writer.py graph_builder/main.py graph_builder/tests/test_quick_fixes_v2.py graph_builder/tests/fixtures/lua/metatable_child.lua
git commit -m "fix(1): write 6 missing edge properties to graph and add INHERITS_VIA_METATABLE edge"
```

---

## Task 2: Fix Dynamic Prefix Resolver Boundary Matching

Line 46 of `dynamic_prefix_resolver.py` uses `if prefix in module_name` -- a naive substring check. This means prefix `"handler."` matches `"my_handler_utils"` (false positive). Replace with boundary-aware matching that splits on `.` separators.

**Files:**
- Modify: `graph_builder/resolvers/dynamic_prefix_resolver.py` (line 46)
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Write tests

- [ ] **2.1: Add boundary matching tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
from graph_builder.resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes, _is_prefix_match


# ───────────────────────────────────────────────────────────────
# Task 2: Dynamic prefix boundary matching
# ───────────────────────────────────────────────────────────────

class TestDynamicPrefixBoundary:
    """Test that prefix matching respects namespace boundaries."""

    def test_exact_prefix_match(self):
        """'handlers.' should match 'ato.handlers.auth'."""
        assert _is_prefix_match("handlers.", "ato.handlers.auth") is True

    def test_prefix_at_start(self):
        """'handlers.' should match 'handlers.auth'."""
        assert _is_prefix_match("handlers.", "handlers.auth") is True

    def test_substring_false_positive_rejected(self):
        """'handler.' should NOT match 'my_handler_utils'."""
        assert _is_prefix_match("handler.", "my_handler_utils") is False

    def test_tasks_prefix_match(self):
        """'tasks.' should match 'ato.tasks.pts_run'."""
        assert _is_prefix_match("tasks.", "ato.tasks.pts_run") is True

    def test_tasks_prefix_no_false_positive(self):
        """'tasks.' should NOT match 'multitask_runner'."""
        assert _is_prefix_match("tasks.", "multitask_runner") is False

    def test_multi_segment_prefix(self):
        """'common.base.' should match 'ato.common.base.handler'."""
        assert _is_prefix_match("common.base.", "ato.common.base.handler") is True

    def test_multi_segment_no_match(self):
        """'common.base.' should NOT match 'uncommon.base.handler'."""
        assert _is_prefix_match("common.base.", "uncommon.base.handler") is False

    def test_single_segment_prefix(self):
        """'redis' should match 'redis' exactly."""
        assert _is_prefix_match("redis", "redis") is True

    def test_prefix_without_trailing_dot(self):
        """'handlers' (no trailing dot) should match 'handlers.auth'."""
        assert _is_prefix_match("handlers", "ato.handlers.auth") is True

    def test_full_integration_no_false_positives(self):
        """End-to-end: dynamic import with prefix should not produce false positives."""
        from graph_builder.parsers.base import FileAST, ImportRef

        source_ast = FileAST(
            file_path="/repo/dispatcher.lua", language="lua",
            imports=[ImportRef(
                module_string="handlers.*",
                line=5,
                import_type="require",
                is_dynamic=True,
                static_prefix="handlers.",
            )],
        )
        # True match: module name contains "handlers" as a full segment
        good_target = FileAST(
            file_path="/repo/handlers/auth.lua", language="lua",
            module_name="ato.handlers.auth",
        )
        # False positive: "handler" is a substring, not a segment
        bad_target = FileAST(
            file_path="/repo/my_handler_utils.lua", language="lua",
            module_name="my_handler_utils",
        )

        all_asts = {
            "/repo/dispatcher.lua": source_ast,
            "/repo/handlers/auth.lua": good_target,
            "/repo/my_handler_utils.lua": bad_target,
        }
        edges = resolve_dynamic_prefixes(all_asts)

        targets = {e["target_file"] for e in edges}
        assert "/repo/handlers/auth.lua" in targets, "Should match ato.handlers.auth"
        assert "/repo/my_handler_utils.lua" not in targets, \
            "Should NOT match my_handler_utils (false positive)"

    def test_resolve_returns_stats(self):
        """resolve_dynamic_prefixes should return (edges, stats) tuple."""
        all_asts = {}
        result = resolve_dynamic_prefixes(all_asts)
        # After change, should be (edges, stats) tuple
        assert isinstance(result, tuple), "Should return (edges, stats) tuple"
        edges, stats = result
        assert isinstance(edges, list)
        assert isinstance(stats, dict)
```

### Step 2: Run tests (expect failure)

- [ ] **2.2: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestDynamicPrefixBoundary -xvs
```

Tests should fail: `_is_prefix_match` doesn't exist yet, and the substring `in` check produces false positives.

### Step 3: Implement the fix

- [ ] **2.3: Replace substring matching with boundary-aware matching**

Replace the entire contents of `graph_builder/resolvers/dynamic_prefix_resolver.py`:

```python
"""Dynamic prefix resolver: expands dynamic require prefixes to potential imports.

Many Lua files use dynamic requires like:
    require(string.format("handlers.%s", handler_name))

The parser extracts the static_prefix (e.g., "handlers.") from these patterns.
This resolver finds all modules whose name contains that prefix at a namespace
boundary, creating POTENTIAL_IMPORT edges so the graph captures the possible
runtime targets.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def _is_prefix_match(prefix: str, module_name: str) -> bool:
    """Check if prefix matches at a namespace boundary.

    "tasks." should match "ato.tasks.pts_run" but NOT "multitask_runner".
    Splits both on "." and checks for contiguous subsequence match.
    """
    prefix_clean = prefix.rstrip(".")
    prefix_parts = prefix_clean.split(".")
    module_parts = module_name.split(".")

    # Check if prefix_parts appears as a contiguous subsequence in module_parts
    for i in range(len(module_parts) - len(prefix_parts) + 1):
        if module_parts[i:i + len(prefix_parts)] == prefix_parts:
            return True
    return False


def resolve_dynamic_prefixes(all_asts: dict[str, FileAST]) -> tuple[list[dict], dict]:
    """Expand dynamic require prefixes to all matching module targets.

    For each dynamic import with a static_prefix, finds all modules in the
    codebase whose module_name matches that prefix at a namespace boundary
    and creates an edge.

    Args:
        all_asts: Mapping of file_path -> FileAST for all parsed files.

    Returns:
        Tuple of (edges, stats):
        - edges: List of dicts with keys: source_file, target_file, prefix, line.
          Does not include self-references.
        - stats: Dict with counts of prefixes_processed, matches_found, files_scanned.
    """
    # Step 1: Build module_name -> file_path index
    module_index: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.module_name:
            module_index[ast.module_name] = file_path

    # Step 2: Collect all dynamic imports with static_prefix
    edges: list[dict] = []
    prefixes_processed = 0
    for file_path, ast in all_asts.items():
        for imp in ast.imports:
            if not imp.is_dynamic or not imp.static_prefix:
                continue

            prefix = imp.static_prefix
            prefixes_processed += 1

            # Step 3: Find all modules whose name matches the prefix at a boundary
            for module_name, target_file in module_index.items():
                if _is_prefix_match(prefix, module_name) and target_file != file_path:
                    edges.append({
                        "source_file": file_path,
                        "target_file": target_file,
                        "prefix": prefix,
                        "line": imp.line,
                    })

    stats = {
        "prefixes_processed": prefixes_processed,
        "matches_found": len(edges),
        "files_scanned": len(all_asts),
    }
    return edges, stats
```

- [ ] **2.4: Update callers in `main.py` for new return type**

In `graph_builder/main.py`, modify the dynamic prefix expansion call (around line 276-278):

```python
# Current (line 276-278):
    dynamic_edges = resolve_dynamic_prefixes(all_asts)
    if dynamic_edges:
        click.echo(f"  Dynamic prefix expansion: {len(dynamic_edges)} potential imports")

# Replace with:
    dynamic_edges, dynamic_stats = resolve_dynamic_prefixes(all_asts)
    if dynamic_edges:
        click.echo(f"  Dynamic prefix expansion: {len(dynamic_edges)} potential imports "
                   f"({dynamic_stats['prefixes_processed']} prefixes processed)")
```

### Step 4: Run tests (expect pass)

- [ ] **2.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestDynamicPrefixBoundary -xvs
```

### Step 5: Commit

- [ ] **2.6: Commit**

```bash
git add graph_builder/resolvers/dynamic_prefix_resolver.py graph_builder/main.py graph_builder/tests/test_quick_fixes_v2.py
git commit -m "fix(2): replace substring matching with boundary-aware matching in dynamic prefix resolver"
```

---

## Task 3: Auto-Detect Base Module Methods from ASTs

`BASE_MODULE_METHODS` in `base_inheritance_resolver.py` is hardcoded with 31 methods across 4 base modules. Replace with auto-detection from ASTs while keeping the hardcoded dict as a fallback.

**Files:**
- Modify: `graph_builder/resolvers/base_inheritance_resolver.py` (add `_auto_detect_base_modules()`, modify `resolve_base_inheritance()`)
- Create: `graph_builder/tests/fixtures/lua/base_handler.lua`
- Create: `graph_builder/tests/fixtures/lua/child_handler.lua`
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Create test fixtures

- [ ] **3.1: Create Lua base handler fixture**

Create `graph_builder/tests/fixtures/lua/base_handler.lua`:

```lua
-- Base handler module at common.base.lua.handler
local _M = {}

function _M:validate(request)
    if not request then
        return nil, "missing request"
    end
    return true
end

function _M:dispatch(request)
    return self:validate(request)
end

function _M:handle_web_request(req)
    return self:dispatch(req)
end

function _M:add_handler_error(err_msg)
    -- error handling logic
end

function _M:parse_postdata(body)
    return body
end

-- Private helper (should NOT be in public methods)
local function _internal_helper()
    return true
end

return _M
```

- [ ] **3.2: Create Lua child handler fixture**

Create `graph_builder/tests/fixtures/lua/child_handler.lua`:

```lua
-- Child handler that inherits from base
local base = require("common.base.lua.handler")
local _M = base:new()

function _M:process(request)
    -- validate is inherited from base, not defined here
    local ok = self:validate(request)
    if not ok then
        self:add_handler_error("validation failed")
        return nil
    end
    return self:_do_work(request)
end

function _M:_do_work(request)
    return request
end

return _M
```

### Step 2: Write tests

- [ ] **3.3: Add auto-detection tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
from graph_builder.resolvers.base_inheritance_resolver import (
    resolve_base_inheritance, _auto_detect_base_modules, BASE_MODULE_METHODS,
)
from graph_builder.parsers.lua_parser import parse_lua_file


# ───────────────────────────────────────────────────────────────
# Task 3: Auto-detect base module methods
# ───────────────────────────────────────────────────────────────

class TestBaseModuleAutoDetection:
    """Test auto-detection of base module methods from ASTs."""

    def test_auto_detect_finds_base_handler_methods(self):
        """_auto_detect_base_modules should extract public methods from base module ASTs."""
        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        # Simulate the module_name that would be assigned during full build
        base_ast.module_name = "common.base.lua.handler"

        all_asts = {str(LUA_FIXTURES / "base_handler.lua"): base_ast}
        detected = _auto_detect_base_modules(all_asts)

        assert "common.base.lua.handler" in detected, \
            f"Should detect common.base.lua.handler, got: {list(detected.keys())}"
        methods = detected["common.base.lua.handler"]
        assert "validate" in methods, f"Should detect 'validate', got: {methods}"
        assert "dispatch" in methods, f"Should detect 'dispatch', got: {methods}"
        assert "handle_web_request" in methods
        assert "add_handler_error" in methods
        assert "parse_postdata" in methods

    def test_auto_detect_excludes_private_helpers(self):
        """Private/local functions should not appear in auto-detected methods."""
        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        base_ast.module_name = "common.base.lua.handler"

        all_asts = {str(LUA_FIXTURES / "base_handler.lua"): base_ast}
        detected = _auto_detect_base_modules(all_asts)
        methods = detected.get("common.base.lua.handler", set())
        assert "_internal_helper" not in methods, \
            "Private helper should not be in detected methods"

    def test_auto_detect_used_in_resolution(self):
        """resolve_base_inheritance should use auto-detected methods for resolution."""
        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        base_ast.module_name = "common.base.lua.handler"

        child_ast = parse_lua_file(str(LUA_FIXTURES / "child_handler.lua"))
        child_ast.module_name = "handlers.child"

        all_asts = {
            str(LUA_FIXTURES / "base_handler.lua"): base_ast,
            str(LUA_FIXTURES / "child_handler.lua"): child_ast,
        }
        resolved = resolve_base_inheritance(all_asts)
        assert resolved > 0, "Should resolve at least one base-inherited call"

        # Check that self:validate was resolved to base
        validate_calls = [c for c in child_ast.calls
                         if "validate" in c.callee_string
                         and c.resolved_module == "common.base.lua.handler"]
        assert len(validate_calls) >= 1, \
            f"self:validate should resolve to base handler, got: {[(c.callee_string, c.resolved_module) for c in child_ast.calls]}"

    def test_hardcoded_fallback_used_when_no_ast(self):
        """When base module ASTs are not in all_asts, hardcoded fallback should work."""
        child_ast = parse_lua_file(str(LUA_FIXTURES / "child_handler.lua"))
        child_ast.module_name = "handlers.child"

        # Only child AST, no base AST -- should fall back to hardcoded
        all_asts = {str(LUA_FIXTURES / "child_handler.lua"): child_ast}
        resolved = resolve_base_inheritance(all_asts)
        assert resolved > 0, "Hardcoded fallback should resolve base-inherited calls"
```

### Step 3: Run tests (expect failure)

- [ ] **3.4: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestBaseModuleAutoDetection -xvs
```

Tests should fail: `_auto_detect_base_modules` doesn't exist yet.

### Step 4: Implement the fix

- [ ] **3.5: Add auto-detection function and update resolve_base_inheritance**

In `graph_builder/resolvers/base_inheritance_resolver.py`, add the `_auto_detect_base_modules` function after the `BASE_MODULE_METHODS` dict (after line 45) and before `resolve_base_inheritance`:

```python
import logging

logger = logging.getLogger(__name__)


def _auto_detect_base_modules(all_asts: dict[str, FileAST]) -> dict[str, set[str]]:
    """Scan ASTs for files whose module_name matches 'common.base.lua.*'
    and extract their public method names.

    Args:
        all_asts: file_path -> FileAST for all parsed files

    Returns:
        Dict mapping module_name -> set of public method names.
    """
    base_modules: dict[str, set[str]] = {}
    for file_path, ast in all_asts.items():
        if not ast.module_name or ast.language != "lua":
            continue
        if not ast.module_name.startswith("common.base.lua."):
            continue

        public_methods: set[str] = set()
        for func in ast.functions:
            if func.visibility == "public" or func.is_method:
                base_name = func.name.split(".")[-1].split(":")[-1]
                public_methods.add(base_name)

        if public_methods:
            base_modules[ast.module_name] = public_methods

    return base_modules
```

Then modify `resolve_base_inheritance()` (line 48-94) to use auto-detection with hardcoded fallback:

```python
def resolve_base_inheritance(all_asts: dict[str, FileAST]) -> int:
    """Resolve self:method() calls that are inherited from a known base module.

    First attempts auto-detection of base module methods from ASTs.
    Falls back to hardcoded BASE_MODULE_METHODS when base files are not
    present in all_asts.

    Args:
        all_asts: file_path -> FileAST for all parsed files

    Returns:
        Count of newly resolved (re-resolved) calls
    """
    # Auto-detect base modules from ASTs
    auto_detected = _auto_detect_base_modules(all_asts)

    # Merge: auto-detected takes priority, hardcoded fills gaps
    effective_methods: dict[str, set[str]] = dict(BASE_MODULE_METHODS)
    for module_name, methods in auto_detected.items():
        if module_name in effective_methods:
            hardcoded = effective_methods[module_name]
            if methods != hardcoded:
                new_methods = methods - hardcoded
                missing_methods = hardcoded - methods
                if new_methods:
                    logger.info(
                        "Auto-detected %d new methods in %s: %s",
                        len(new_methods), module_name, sorted(new_methods),
                    )
                if missing_methods:
                    logger.debug(
                        "Hardcoded methods not in AST for %s: %s",
                        module_name, sorted(missing_methods),
                    )
            effective_methods[module_name] = methods | hardcoded  # union
        else:
            logger.info(
                "Auto-detected new base module: %s with %d methods",
                module_name, len(methods),
            )
            effective_methods[module_name] = methods

    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        # Step 1: Find which base module (if any) this file imports
        base_module = _find_base_module(ast, effective_methods)
        if not base_module:
            continue

        base_methods = effective_methods[base_module]

        # Step 2: Get the set of methods defined locally in this file
        local_methods = _get_local_methods(ast)

        # Step 3: Re-resolve self:method() calls targeting inherited methods
        for call in ast.calls:
            if not call.callee_string.startswith("self:"):
                continue

            method_name = call.callee_string.split(":", 1)[1]

            # Only re-resolve if: method NOT defined locally AND method IS in base
            if method_name not in local_methods and method_name in base_methods:
                call.resolved_module = base_module
                call.resolved_function = method_name
                call.resolution_confidence = "base_inherited"
                resolved_count += 1

    return resolved_count
```

Then update `_find_base_module` to accept the effective_methods dict:

```python
def _find_base_module(ast: FileAST, known_modules: dict[str, set[str]] | None = None) -> str | None:
    """Check if the file imports a known base module."""
    modules_to_check = known_modules or BASE_MODULE_METHODS
    for imp in ast.imports:
        if imp.module_string in modules_to_check:
            return imp.module_string
    return None
```

### Step 5: Run tests (expect pass)

- [ ] **3.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestBaseModuleAutoDetection -xvs
```

### Step 6: Commit

- [ ] **3.7: Commit**

```bash
git add graph_builder/resolvers/base_inheritance_resolver.py graph_builder/tests/test_quick_fixes_v2.py graph_builder/tests/fixtures/lua/base_handler.lua graph_builder/tests/fixtures/lua/child_handler.lua
git commit -m "fix(3): auto-detect base module methods from ASTs with hardcoded fallback"
```

---

## Task 4: Python Package Root Detection + Stdlib Classification

Python resolver builds a flat module index without understanding package hierarchy. Add package root detection and Python stdlib classification (analogous to Go's `is_stdlib`).

**Files:**
- Modify: `graph_builder/resolvers/python_resolver.py` (add `PYTHON_STDLIB_TOP`, `_find_package_roots()`, `is_stdlib()`, update `resolve()`)
- Modify: `graph_builder/main.py` (add Python stdlib classification in resolution loop, around line 168-192)
- Create: `graph_builder/tests/fixtures/python/nested_pkg/__init__.py`
- Create: `graph_builder/tests/fixtures/python/nested_pkg/services/__init__.py`
- Create: `graph_builder/tests/fixtures/python/nested_pkg/services/models.py`
- Create: `graph_builder/tests/fixtures/python/nested_pkg/services/handler.py`
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Create test fixtures

- [ ] **4.1: Create nested Python package fixture**

Create the directory structure:

```bash
mkdir -p graph_builder/tests/fixtures/python/nested_pkg/services
```

Create `graph_builder/tests/fixtures/python/nested_pkg/__init__.py`:
```python
```

Create `graph_builder/tests/fixtures/python/nested_pkg/services/__init__.py`:
```python
```

Create `graph_builder/tests/fixtures/python/nested_pkg/services/models.py`:
```python
"""Models for the nested package test."""

class Task:
    def __init__(self, name):
        self.name = name
```

Create `graph_builder/tests/fixtures/python/nested_pkg/services/handler.py`:
```python
"""Handler that imports from sibling module via absolute import."""
import os
import json
import logging
from services.models import Task


def handle(name):
    task = Task(name)
    return task
```

### Step 2: Write tests

- [ ] **4.2: Add Python resolver tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
from graph_builder.resolvers.python_resolver import PythonResolver


# ───────────────────────────────────────────────────────────────
# Task 4: Python package root detection + stdlib classification
# ───────────────────────────────────────────────────────────────

class TestPythonResolver:
    """Test Python package root detection and stdlib classification."""

    def test_is_stdlib_recognizes_common_modules(self):
        """is_stdlib should recognize os, sys, json, logging, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os") is True
        assert resolver.is_stdlib("sys") is True
        assert resolver.is_stdlib("json") is True
        assert resolver.is_stdlib("logging") is True
        assert resolver.is_stdlib("collections") is True
        assert resolver.is_stdlib("pathlib") is True
        assert resolver.is_stdlib("typing") is True
        assert resolver.is_stdlib("datetime") is True
        assert resolver.is_stdlib("re") is True
        assert resolver.is_stdlib("unittest") is True

    def test_is_stdlib_rejects_third_party(self):
        """is_stdlib should reject known third-party packages."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("flask") is False
        assert resolver.is_stdlib("django") is False
        assert resolver.is_stdlib("requests") is False
        assert resolver.is_stdlib("numpy") is False
        assert resolver.is_stdlib("boto3") is False

    def test_is_stdlib_handles_submodules(self):
        """is_stdlib should recognize os.path, collections.abc, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os.path") is True
        assert resolver.is_stdlib("collections.abc") is True
        assert resolver.is_stdlib("http.server") is True
        assert resolver.is_stdlib("urllib.parse") is True
        assert resolver.is_stdlib("email.mime.text") is True

    def test_find_package_roots(self):
        """_find_package_roots should detect nested_pkg as a package root."""
        resolver = PythonResolver(str(PY_FIXTURES))
        roots = resolver._find_package_roots()
        # nested_pkg/ contains __init__.py, so it should be detected
        root_dirs = {str(v) for v in roots.values()}
        nested_pkg_dir = str((PY_FIXTURES / "nested_pkg").resolve())
        has_nested = any(nested_pkg_dir in d for d in root_dirs)
        assert has_nested, f"Should detect nested_pkg as package root, got: {root_dirs}"

    def test_package_root_resolution(self):
        """Absolute import 'services.models' should resolve relative to package root."""
        resolver = PythonResolver(str(PY_FIXTURES / "nested_pkg"))
        handler_file = str(PY_FIXTURES / "nested_pkg" / "services" / "handler.py")
        result = resolver.resolve("services.models", handler_file)
        assert result is not None, "services.models should resolve within nested_pkg"
        assert "models.py" in result

    def test_resolver_stats_include_package_roots(self):
        """stats() should include package_roots count."""
        resolver = PythonResolver(str(PY_FIXTURES))
        stats = resolver.stats()
        assert "package_roots" in stats, f"stats should include package_roots, got: {stats}"
```

### Step 3: Run tests (expect failure)

- [ ] **4.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestPythonResolver -xvs
```

Tests should fail: `is_stdlib` method doesn't exist, `_find_package_roots` doesn't exist.

### Step 4: Implement the fix

- [ ] **4.4: Add stdlib set, package root detection, and is_stdlib to PythonResolver**

In `graph_builder/resolvers/python_resolver.py`, add the stdlib set after the imports (after line 5):

```python
# Python standard library top-level packages (Python 3.10+)
# Used for classification (not resolution — stdlib imports are always "external")
PYTHON_STDLIB_TOP = frozenset({
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
    "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
    "binhex", "bisect", "builtins", "bz2",
    "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
    "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "cProfile", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest",
    "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
    "fractions", "ftplib", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "grp", "gzip",
    "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect",
    "io", "ipaddress", "itertools",
    "json",
    "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma",
    "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
    "modulefinder", "multiprocessing",
    "netrc", "nis", "nntplib", "numbers",
    "operator", "optparse", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
    "pydoc",
    "queue", "quopri",
    "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy",
    "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "sunau", "symtable",
    "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing",
    "unicodedata", "unittest", "urllib", "uu", "uuid",
    "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref",
    "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    # Also common aliases/sub-packages that appear as top-level
    "_thread", "__future__",
})
```

Then add `is_stdlib()` and `_find_package_roots()` methods to the `PythonResolver` class:

```python
    def is_stdlib(self, module_string: str) -> bool:
        """Check if a module string is a Python standard library module.

        Args:
            module_string: e.g., "os", "os.path", "collections.abc"

        Returns:
            True if the top-level package is in the Python stdlib.
        """
        top = module_string.split(".")[0]
        return top in PYTHON_STDLIB_TOP

    def _find_package_roots(self) -> dict[str, Path]:
        """Find the topmost __init__.py for each package tree.

        Walks upward from each .py file to find the highest directory
        that still contains __init__.py. This identifies package roots
        for resolving absolute imports.

        Returns:
            Dict mapping .py file path string -> topmost package root Path.
        """
        skip = {"node_modules", ".git", "__pycache__", ".mypy_cache",
                "vendor", "venv", ".venv", "dist", "build", ".tox", ".eggs"}
        roots: dict[str, Path] = {}
        for py_file in self.repo_root.rglob("*.py"):
            if any(s in py_file.parts for s in skip):
                continue
            current = py_file.parent
            topmost = None
            while current != self.repo_root and current != current.parent:
                if (current / "__init__.py").exists():
                    topmost = current
                else:
                    break
                current = current.parent
            if topmost:
                roots[str(py_file)] = topmost
        return roots
```

Then update `stats()` (line 171-176) to include package_roots:

```python
    def stats(self) -> dict:
        index = self._build_index()
        roots = self._find_package_roots()
        return {
            "indexed_modules": len(index),
            "repo_root": str(self.repo_root),
            "package_roots": len(set(roots.values())),
        }
```

- [ ] **4.5: Add Python stdlib classification to main.py resolution loop**

In `graph_builder/main.py`, add Python stdlib classification alongside the existing Go stdlib classification (around line 174-178). After the Go stdlib block and before the generic resolver call:

```python
# Current (line 168-191):
    for file_path, ast in all_asts.items():
        file_resolved = {}
        for imp in ast.imports:
            if imp.is_dynamic:
                continue
            # Go stdlib classification: mark stdlib imports before normal resolution
            if ast.language == "go":
                go_res = resolvers.get("go")
                if go_res and hasattr(go_res, 'is_stdlib') and go_res.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "__go_stdlib__"
                    continue
            resolver_key = lang_to_resolver.get(ast.language)
            ...

# Replace the loop body with:
    for file_path, ast in all_asts.items():
        file_resolved = {}
        for imp in ast.imports:
            if imp.is_dynamic:
                continue
            # Go stdlib classification
            if ast.language == "go":
                go_res = resolvers.get("go")
                if go_res and hasattr(go_res, 'is_stdlib') and go_res.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "__go_stdlib__"
                    continue
            # Python stdlib classification
            if ast.language == "python":
                py_res = resolvers.get("python")
                if py_res and hasattr(py_res, 'is_stdlib') and py_res.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "__python_stdlib__"
                    continue
            resolver_key = lang_to_resolver.get(ast.language)
            resolver = resolvers.get(resolver_key) if resolver_key else None
            if resolver:
                if ast.language == "ruby":
                    file_resolved[imp.module_string] = resolver.resolve(
                        imp.module_string, file_path, import_type=imp.import_type,
                    )
                else:
                    file_resolved[imp.module_string] = resolver.resolve(
                        imp.module_string, file_path,
                    )
            else:
                file_resolved[imp.module_string] = None
        resolved_imports[file_path] = file_resolved
```

### Step 5: Run tests (expect pass)

- [ ] **4.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestPythonResolver -xvs
```

### Step 6: Commit

- [ ] **4.7: Commit**

```bash
git add graph_builder/resolvers/python_resolver.py graph_builder/main.py graph_builder/tests/test_quick_fixes_v2.py graph_builder/tests/fixtures/python/nested_pkg/
git commit -m "fix(4): add Python stdlib classification and package root detection"
```

---

## Task 5: Go go.mod Parsing for Internal Package Resolution

Go import resolution is 60.2%. The resolver can't match `"pp-consumer/common/utils"` because the actual directory is `common/utils/` relative to the Go project root. Parse `go.mod` to extract the module name and strip it from import paths.

**Files:**
- Modify: `graph_builder/resolvers/go_resolver.py` (add `_parse_go_mod()`, `_parse_go_mod_requires()`, modify `__init__()` and `resolve()`)
- Create: `graph_builder/tests/fixtures/go/go.mod`
- Create: `graph_builder/tests/fixtures/go/common/utils.go`
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Create test fixtures

- [ ] **5.1: Create go.mod fixture**

Create `graph_builder/tests/fixtures/go/go.mod`:

```
module pp-consumer

go 1.22

require (
	github.com/aws/aws-sdk-go v1.44.0
	github.com/go-redis/redismock/v9 v9.0.0
	github.com/go-sql-driver/mysql v1.7.0
	github.com/lithammer/shortuuid/v3 v3.0.7
	github.com/redis/go-redis/v9 v9.0.2
	github.com/stretchr/objx v0.5.0
	github.com/stretchr/testify v1.8.4
	github.com/timandy/routine v1.1.1
	golang.org/x/sys v0.8.0
	gopkg.in/alexcesaro/statsd.v2 v2.0.0
)
```

- [ ] **5.2: Create Go internal package fixture**

Create `graph_builder/tests/fixtures/go/common/utils.go`:

```go
package common

// Utility functions for pp-consumer internal packages.

func FormatKey(prefix, id string) string {
	return prefix + ":" + id
}

func ParseConfig(path string) (map[string]string, error) {
	return nil, nil
}
```

### Step 2: Write tests

- [ ] **5.3: Add Go go.mod tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
from graph_builder.resolvers.go_resolver import GoResolver


# ───────────────────────────────────────────────────────────────
# Task 5: Go go.mod parsing
# ───────────────────────────────────────────────────────────────

class TestGoModParsing:
    """Test go.mod parsing and module prefix stripping."""

    def test_parse_go_mod_extracts_module_name(self):
        """GoResolver should parse go.mod and extract 'pp-consumer' module name."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver._module_name == "pp-consumer", \
            f"Expected module name 'pp-consumer', got: {resolver._module_name}"

    def test_internal_import_resolves_with_module_prefix(self):
        """'pp-consumer/common' should resolve by stripping module prefix."""
        resolver = GoResolver(str(GO_FIXTURES))
        result = resolver.resolve("pp-consumer/common")
        assert result is not None, \
            "'pp-consumer/common' should resolve to common/utils.go"
        assert "common" in result

    def test_internal_import_without_module_prefix_still_works(self):
        """'common' should still resolve via suffix matching."""
        resolver = GoResolver(str(GO_FIXTURES))
        result = resolver.resolve("common")
        assert result is not None, "'common' should resolve via suffix matching"

    def test_external_dep_classified(self):
        """External dependencies from go.mod require block should be classified."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("github.com/aws/aws-sdk-go") is True
        assert resolver.is_external("github.com/redis/go-redis/v9") is True
        assert resolver.is_external("github.com/stretchr/testify") is True

    def test_internal_not_classified_as_external(self):
        """Internal imports should not be classified as external."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("pp-consumer/common") is False
        assert resolver.is_external("common") is False

    def test_stdlib_not_classified_as_external(self):
        """Stdlib imports should not be classified as external."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("fmt") is False
        assert resolver.is_external("net/http") is False

    def test_go_mod_root_detected(self):
        """The Go project root should be the directory containing go.mod."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver._go_project_root is not None
        assert resolver._go_project_root == str(Path(GO_FIXTURES).resolve()), \
            f"Go project root should be fixtures dir, got: {resolver._go_project_root}"

    def test_stats_include_module_name(self):
        """stats() should include module_name and external_deps count."""
        resolver = GoResolver(str(GO_FIXTURES))
        stats = resolver.stats()
        assert "module_name" in stats, f"stats should include module_name, got: {stats}"
        assert "external_deps" in stats, f"stats should include external_deps, got: {stats}"
        assert stats["module_name"] == "pp-consumer"
        assert stats["external_deps"] >= 10  # 10 deps in go.mod
```

### Step 3: Run tests (expect failure)

- [ ] **5.4: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestGoModParsing -xvs
```

Tests should fail: `_module_name`, `_go_project_root`, and `is_external` don't exist.

### Step 4: Implement the fix

- [ ] **5.5: Add go.mod parsing and module prefix stripping to GoResolver**

In `graph_builder/resolvers/go_resolver.py`, modify the `GoResolver` class:

First, update `__init__()` (line 32-38):

```python
# Current (line 32-38):
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        # Map of package_path_suffix -> directory containing .go files
        self._index: dict[str, str] = {}
        # Map of directory -> list of .go file paths (for same-package linking)
        self._dir_files: dict[str, list[str]] = {}
        self._build_index()

# Replace with:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        # Map of package_path_suffix -> directory containing .go files
        self._index: dict[str, str] = {}
        # Map of directory -> list of .go file paths (for same-package linking)
        self._dir_files: dict[str, list[str]] = {}
        # go.mod parsing
        self._module_name: str | None = None
        self._go_project_root: str | None = None
        self._external_deps: set[str] = set()
        self._parse_go_mod()
        self._build_index()
```

Then add the `_parse_go_mod()` method before `_build_index()`:

```python
    def _parse_go_mod(self):
        """Find go.mod and extract the module name and external dependencies."""
        for go_mod in self.repo_root.rglob("go.mod"):
            # Skip vendor directories
            if "vendor" in go_mod.parts:
                continue
            self._go_project_root = str(go_mod.parent)
            in_require_block = False
            with open(go_mod, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("module "):
                        self._module_name = stripped.split()[1].strip()
                    elif stripped == "require (":
                        in_require_block = True
                    elif stripped == ")" and in_require_block:
                        in_require_block = False
                    elif in_require_block and stripped:
                        # "github.com/aws/aws-sdk-go v1.44.0"
                        parts = stripped.split()
                        if parts:
                            self._external_deps.add(parts[0])
                    elif stripped.startswith("require ") and "(" not in stripped:
                        # Single-line require: require github.com/foo v1.0.0
                        parts = stripped.split()
                        if len(parts) >= 2:
                            self._external_deps.add(parts[1])
            break  # Use the first go.mod found
```

Then add `is_external()`:

```python
    def is_external(self, import_path: str) -> bool:
        """Check if an import path is a known external dependency.

        Matches against the require entries in go.mod. Also matches
        sub-packages of external deps (e.g., "github.com/aws/aws-sdk-go/service/s3"
        matches "github.com/aws/aws-sdk-go").

        Args:
            import_path: e.g., "github.com/aws/aws-sdk-go/service/s3"

        Returns:
            True if the import is a known external dependency.
        """
        if self.is_stdlib(import_path):
            return False
        for dep in self._external_deps:
            if import_path == dep or import_path.startswith(dep + "/"):
                return True
        return False
```

Then modify `resolve()` (line 59-85) to strip the module prefix:

```python
# Current (line 59-85):
    def resolve(self, import_path: str, from_file: str | None = None) -> str | None:
        """Resolve a Go import path to a .go file path."""
        # Try progressively shorter suffixes of the import path
        parts = import_path.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if suffix in self._index:
                dir_path = Path(self._index[suffix])
                go_files = sorted(dir_path.glob("*.go"))
                for gf in go_files:
                    if not gf.name.endswith("_test.go"):
                        return str(gf)
                if go_files:
                    return str(go_files[0])
                return self._index[suffix]
        return None

# Replace with:
    def resolve(self, import_path: str, from_file: str | None = None) -> str | None:
        """Resolve a Go import path to a .go file path.

        If a go.mod module name is known, strips it from the import path
        before suffix matching. E.g., "pp-consumer/common/utils" becomes
        "common/utils" when module name is "pp-consumer".

        Args:
            import_path: e.g., "github.com/org/repo/internal/auth" or "pp-consumer/common"
            from_file: (unused) the file containing the import, for API consistency

        Returns:
            Absolute path to a representative .go file, or None if not found.
        """
        # Strip module prefix for internal packages
        local_path = import_path
        if self._module_name and import_path.startswith(self._module_name + "/"):
            local_path = import_path[len(self._module_name) + 1:]

        # Try progressively shorter suffixes
        for path_to_try in [local_path, import_path]:
            parts = path_to_try.split("/")
            for i in range(len(parts)):
                suffix = "/".join(parts[i:])
                if suffix in self._index:
                    dir_path = Path(self._index[suffix])
                    go_files = sorted(dir_path.glob("*.go"))
                    for gf in go_files:
                        if not gf.name.endswith("_test.go"):
                            return str(gf)
                    if go_files:
                        return str(go_files[0])
                    return self._index[suffix]

        return None
```

Then update `stats()` (line 126-130):

```python
# Current (line 126-130):
    def stats(self) -> dict:
        return {
            "indexed_packages": len(self._index),
            "indexed_directories": len(self._dir_files),
        }

# Replace with:
    def stats(self) -> dict:
        return {
            "indexed_packages": len(self._index),
            "indexed_directories": len(self._dir_files),
            "module_name": self._module_name,
            "go_project_root": self._go_project_root,
            "external_deps": len(self._external_deps),
        }
```

### Step 5: Run tests (expect pass)

- [ ] **5.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestGoModParsing -xvs
```

### Step 6: Commit

- [ ] **5.7: Commit**

```bash
git add graph_builder/resolvers/go_resolver.py graph_builder/tests/test_quick_fixes_v2.py graph_builder/tests/fixtures/go/go.mod graph_builder/tests/fixtures/go/common/utils.go
git commit -m "fix(5): parse go.mod for module name, strip prefix for ~90% import resolution"
```

---

## Task 6: Ruby Gemfile Parsing for Import Classification

Ruby import resolution is 42.3%. Most unresolved are external gems. Parse Gemfile to classify unresolved imports as gem (expected) vs truly unresolved (investigation targets).

**Files:**
- Modify: `graph_builder/resolvers/ruby_resolver.py` (add `_parse_gemfiles()`, `is_gem()`, update `resolve()`)
- Modify: `graph_builder/main.py` (add Ruby gem classification, around line 182-186)
- Create: `graph_builder/tests/fixtures/ruby/Gemfile`
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Create test fixtures

- [ ] **6.1: Create Ruby Gemfile fixture**

Create `graph_builder/tests/fixtures/ruby/Gemfile`:

```ruby
source 'https://rubygems.org'

gem 'activesupport', '~> 7.0'
gem 'aws-sdk-s3'
gem 'cassandra-driver'
gem 'concurrent-ruby'
gem 'dalli'
gem 'mysql2'
gem 'oj'
gem 'redis', '~> 5.0'
gem 'rest-client'
gem 'statsd-instrument', '~> 3.0'

group :development, :test do
  gem 'pry'
  gem 'rspec', '~> 3.0'
  gem 'rubocop'
end
```

### Step 2: Write tests

- [ ] **6.2: Add Ruby Gemfile tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
import re
from graph_builder.resolvers.ruby_resolver import RubyResolver


# ───────────────────────────────────────────────────────────────
# Task 6: Ruby Gemfile parsing
# ───────────────────────────────────────────────────────────────

class TestRubyGemfileParsing:
    """Test Ruby Gemfile parsing and gem classification."""

    def test_parse_gemfiles_finds_gems(self):
        """_parse_gemfiles should extract gem names from Gemfile."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        gems = resolver._parsed_gems
        assert "activesupport" in gems, f"Should find activesupport, got: {gems}"
        assert "redis" in gems, f"Should find redis, got: {gems}"
        assert "aws-sdk-s3" in gems, f"Should find aws-sdk-s3, got: {gems}"
        assert "rest-client" in gems, f"Should find rest-client, got: {gems}"
        assert "pry" in gems, f"Should find pry (dev gem), got: {gems}"

    def test_is_gem_matches_known_gems(self):
        """is_gem should match gem names and common aliases."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("redis") is True
        assert resolver.is_gem("active_support") is True  # underscore variant
        assert resolver.is_gem("rest-client") is True
        assert resolver.is_gem("rest_client") is True  # underscore variant
        assert resolver.is_gem("oj") is True
        assert resolver.is_gem("dalli") is True

    def test_is_gem_rejects_unknown(self):
        """is_gem should reject unknown modules."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("my_custom_lib") is False
        assert resolver.is_gem("nonexistent_gem") is False

    def test_is_gem_handles_submodules(self):
        """is_gem should match 'active_support/core_ext' via base name."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("active_support/core_ext") is True
        assert resolver.is_gem("aws-sdk-s3/resource") is True

    def test_resolve_returns_gem_sentinel(self):
        """Unresolved gem imports should return '__ruby_gem__' sentinel."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        result = resolver.resolve("redis")
        # redis is not in our test fixtures as a .rb file, so it should
        # resolve as a gem sentinel (not stdlib, not in index)
        assert result == "__ruby_gem__", \
            f"'redis' should resolve to '__ruby_gem__', got: {result}"

    def test_resolve_unknown_returns_none(self):
        """Truly unknown imports should return None."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        result = resolver.resolve("completely_unknown_thing")
        assert result is None, \
            f"Unknown module should return None, got: {result}"

    def test_stats_include_gems(self):
        """stats() should include parsed_gems count."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        stats = resolver.stats()
        assert "parsed_gems" in stats, f"stats should include parsed_gems, got: {stats}"
        assert stats["parsed_gems"] >= 10
```

### Step 3: Run tests (expect failure)

- [ ] **6.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestRubyGemfileParsing -xvs
```

Tests should fail: `_parsed_gems`, `is_gem` don't exist, and `resolve()` doesn't return `__ruby_gem__`.

### Step 4: Implement the fix

- [ ] **6.4: Add Gemfile parsing, gem classification, and update resolve()**

In `graph_builder/resolvers/ruby_resolver.py`, add `import re` at the top (after `from pathlib import Path`):

```python
import re
```

Add a `KNOWN_GEM_ALIASES` dict after `_RUBY_STDLIB` (after line 34):

```python
# Common aliases for gems where the require name differs from gem name.
# Maps normalized (lowercase, underscored) require base -> True
_KNOWN_GEM_ALIASES: dict[str, str] = {
    "active_support": "activesupport",
    "rest_client": "rest-client",
    "restclient": "rest-client",
    "statsd": "statsd-instrument",
    "concurrent": "concurrent-ruby",
    "aws": "aws-sdk-s3",
}
```

Then modify `__init__()` (line 40-43) to parse Gemfiles:

```python
# Current (line 40-43):
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}
        self._build_index()

# Replace with:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}
        self._parsed_gems: set[str] = set()
        self._build_index()
        self._parse_gemfiles()
```

Add the `_parse_gemfiles()` method after `_build_index()`:

```python
    def _parse_gemfiles(self):
        """Find all Gemfiles in the repo and extract gem names."""
        for gemfile in self.repo_root.rglob("Gemfile"):
            # Skip vendor directories
            if "vendor" in gemfile.parts or ".bundle" in gemfile.parts:
                continue
            try:
                with open(gemfile, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        match = re.match(r"^\s*gem\s+['\"]([^'\"]+)['\"]", line)
                        if match:
                            self._parsed_gems.add(match.group(1))
            except OSError:
                pass

    def is_gem(self, module_string: str) -> bool:
        """Check if a require string is a known gem (from Gemfile or aliases).

        Normalizes the base name (lowercase, replace '-' with '_') and checks
        against parsed Gemfile gems and known aliases.

        Args:
            module_string: e.g., "redis", "active_support/core_ext"

        Returns:
            True if the import is a known gem.
        """
        base = module_string.split("/")[0].split("::")[0]
        normalized = base.lower().replace("-", "_")

        # Check direct match in parsed gems (also normalized)
        normalized_gems = {g.lower().replace("-", "_") for g in self._parsed_gems}
        if normalized in normalized_gems:
            return True

        # Check known aliases
        if normalized in _KNOWN_GEM_ALIASES:
            return True

        return False
```

Then modify `resolve()` (line 60-99) to return `__ruby_gem__` for unresolved gems:

```python
# Current end of resolve() (line 95-99):
        # Suffix match: require "models/user" should match "app/models/user"
        for key, path in self._index.items():
            if key.endswith(f"/{module_string}") or key == module_string:
                return path

        return None  # external gem

# Replace with:
        # Suffix match: require "models/user" should match "app/models/user"
        for key, path in self._index.items():
            if key.endswith(f"/{module_string}") or key == module_string:
                return path

        # Check if it's a known gem before returning None
        if self.is_gem(module_string):
            return "__ruby_gem__"

        return None  # truly unresolved
```

Then update `stats()` (line 151-152):

```python
# Current (line 151-152):
    def stats(self) -> dict:
        return {"indexed_files": len(self._index)}

# Replace with:
    def stats(self) -> dict:
        return {
            "indexed_files": len(self._index),
            "parsed_gems": len(self._parsed_gems),
        }
```

### Step 5: Run tests (expect pass)

- [ ] **6.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestRubyGemfileParsing -xvs
```

### Step 6: Commit

- [ ] **6.6: Commit**

```bash
git add graph_builder/resolvers/ruby_resolver.py graph_builder/tests/test_quick_fixes_v2.py graph_builder/tests/fixtures/ruby/Gemfile
git commit -m "fix(6): parse Ruby Gemfile for gem classification, return __ruby_gem__ sentinel"
```

---

## Task 7: Update Schema for New Properties/Edges

Update `schema.py` to document the new properties and edge types added in Tasks 1-6. Add any new indexes needed.

**Files:**
- Modify: `graph_builder/ingestion/schema.py`
- Modify: `graph_builder/tests/test_quick_fixes_v2.py`

### Step 1: Write tests

- [ ] **7.1: Add schema validation tests**

Append to `graph_builder/tests/test_quick_fixes_v2.py`:

```python
from graph_builder.ingestion.schema import NODE_TYPES, EDGE_TYPES


# ───────────────────────────────────────────────────────────────
# Task 7: Schema updates
# ───────────────────────────────────────────────────────────────

class TestSchemaUpdates:
    """Test that schema.py documents all new properties and edge types."""

    def test_calls_edge_has_classification(self):
        """CALLS edge type should list 'classification' property."""
        assert "classification" in EDGE_TYPES["CALLS"], \
            f"CALLS edge missing 'classification', has: {EDGE_TYPES['CALLS']}"

    def test_calls_edge_has_resolution_confidence(self):
        """CALLS edge type should list 'resolution_confidence' property."""
        assert "resolution_confidence" in EDGE_TYPES["CALLS"], \
            f"CALLS edge missing 'resolution_confidence', has: {EDGE_TYPES['CALLS']}"

    def test_imports_edge_has_local_binding(self):
        """IMPORTS edge type should list 'local_binding' property."""
        assert "local_binding" in EDGE_TYPES["IMPORTS"], \
            f"IMPORTS edge missing 'local_binding', has: {EDGE_TYPES['IMPORTS']}"

    def test_function_node_has_decorators(self):
        """Function node type should list 'decorators' property."""
        assert "decorators" in NODE_TYPES["Function"], \
            f"Function node missing 'decorators', has: {NODE_TYPES['Function']}"

    def test_class_node_has_is_interface(self):
        """Class node type should list 'is_interface' property."""
        assert "is_interface" in NODE_TYPES["Class"], \
            f"Class node missing 'is_interface', has: {NODE_TYPES['Class']}"

    def test_inherits_via_metatable_edge_exists(self):
        """INHERITS_VIA_METATABLE edge type should exist with 'table_var' property."""
        assert "INHERITS_VIA_METATABLE" in EDGE_TYPES, \
            f"Missing INHERITS_VIA_METATABLE edge type, edges: {list(EDGE_TYPES.keys())}"
        assert "table_var" in EDGE_TYPES["INHERITS_VIA_METATABLE"]

    def test_ctx_edges_have_scope(self):
        """CTX_READS and CTX_WRITES edge types should list 'scope' property."""
        assert "scope" in EDGE_TYPES["CTX_READS"], \
            f"CTX_READS edge missing 'scope', has: {EDGE_TYPES['CTX_READS']}"
        assert "scope" in EDGE_TYPES["CTX_WRITES"], \
            f"CTX_WRITES edge missing 'scope', has: {EDGE_TYPES['CTX_WRITES']}"

    def test_potential_import_edge_documented(self):
        """POTENTIAL_IMPORT edge should be documented (already exists in writer)."""
        assert "POTENTIAL_IMPORT" in EDGE_TYPES, \
            f"Missing POTENTIAL_IMPORT edge type"

    def test_same_package_edge_documented(self):
        """SAME_PACKAGE edge should be documented (already exists in writer)."""
        assert "SAME_PACKAGE" in EDGE_TYPES, \
            f"Missing SAME_PACKAGE edge type"

    def test_loads_dynamically_edge_documented(self):
        """LOADS_DYNAMICALLY edge should be documented (already exists in writer)."""
        assert "LOADS_DYNAMICALLY" in EDGE_TYPES, \
            f"Missing LOADS_DYNAMICALLY edge type"

    def test_implements_edge_documented(self):
        """IMPLEMENTS edge should be documented (already exists in writer)."""
        assert "IMPLEMENTS" in EDGE_TYPES, \
            f"Missing IMPLEMENTS edge type"
```

### Step 2: Run tests (expect failure)

- [ ] **7.2: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestSchemaUpdates -xvs
```

Tests should fail: schema doesn't have the new properties or edge types.

### Step 3: Implement the fix

- [ ] **7.3: Update schema.py with new properties and edge types**

In `graph_builder/ingestion/schema.py`, update `NODE_TYPES` (line 32-50):

```python
# Current (line 32-50):
NODE_TYPES = {
    "File": ["path", "language", "last_indexed"],
    "Module": ["name", "file", "pattern_type"],
    "Function": ["name", "file", "line", "line_end", "visibility", "is_method"],
    "Class": ["name", "file", "line", "line_end", "parent_class"],
    ...
}

# Replace Function and Class entries:
NODE_TYPES = {
    "File": ["path", "language", "last_indexed"],
    "Module": ["name", "file", "pattern_type"],
    "Function": ["name", "file", "line", "line_end", "visibility", "is_method", "decorators"],
    "Class": ["name", "file", "line", "line_end", "parent_class", "is_interface"],
    "Endpoint": ["path", "method"],
    "NginxPhase": ["phase_type", "endpoint", "lua_file", "is_inline"],
    "ContextKey": ["name"],
    "SharedDict": ["name"],
    "RedisKey": ["name"],
    "SharedFile": ["path"],
    "Service": ["name", "type", "socket_path"],
    "UnixSocket": ["path", "protocol"],
    "SQSQueue": ["name"],
    "KinesisStream": ["name"],
    "SharedRedisPattern": ["pattern"],
    "ConfigFile": ["name"],
    "DatabaseTable": ["name"],
}
```

Then update `EDGE_TYPES` (line 53-83):

```python
# Replace entire EDGE_TYPES dict:
EDGE_TYPES = {
    "IMPORTS": ["module", "local_binding"],
    "DEFINES": [],
    "CALLS": ["line", "is_pcall", "classification", "resolution_confidence"],
    "HANDLES": [],
    "HAS_PHASE": [],
    "EXTENDS": [],
    "INCLUDES": [],
    "REQUIRES": ["module"],
    "EXPORTS": [],
    "CTX_WRITES": ["function", "line", "scope"],
    "CTX_READS": ["function", "line", "scope"],
    "USES_SHARED": ["operation", "function", "line"],
    "REROUTES_TO": ["redirect_type", "line"],
    "REDIS_READS": ["operation", "line"],
    "REDIS_WRITES": ["operation", "line"],
    "HTTP_CALLS": ["method", "line"],
    "PROXIES_TO": ["upstream_name"],
    "DISPATCHES": ["task", "line"],
    "SOCKET_LISTENS": [],
    "SOCKET_CONNECTS": [],
    "WRITES_REDIS_PATTERN": [],
    "READS_REDIS_PATTERN": [],
    "QUERIES_DB": ["db_type", "operation", "table"],
    "QUERIES_CASSANDRA": ["operation"],
    "PRODUCES_TO": ["operation"],
    "CONSUMES_FROM": ["operation"],
    "STREAMS_TO": ["operation"],
    "ACCESSES_S3": ["operation"],
    "READS_CONFIG": [],
    "INHERITS_VIA_METATABLE": ["table_var"],
    "POTENTIAL_IMPORT": ["prefix", "line", "dynamic"],
    "SAME_PACKAGE": ["package"],
    "LOADS_DYNAMICALLY": ["load_type"],
    "IMPLEMENTS": [],
    "SERVES": [],
}
```

### Step 4: Run tests (expect pass)

- [ ] **7.4: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py::TestSchemaUpdates -xvs
```

### Step 5: Run full test suite

- [ ] **7.5: Run all quick-fixes-v2 tests**

```bash
python -m pytest graph_builder/tests/test_quick_fixes_v2.py -v
```

All tests across all 7 tasks should pass.

### Step 6: Run existing tests for regression

- [ ] **7.6: Run existing test suite to verify no regressions**

```bash
python -m pytest graph_builder/tests/ -v --tb=short
```

Pay special attention to:
- `test_lua_parser.py` -- Lua parsing still works
- `test_all_parsers.py` -- all parsers still produce valid output
- `test_quick_fixes.py` -- previous quick-fixes bundle still passes

### Step 7: Commit

- [ ] **7.7: Commit**

```bash
git add graph_builder/ingestion/schema.py graph_builder/tests/test_quick_fixes_v2.py
git commit -m "fix(7): update schema with new properties, edge types, and document existing undocumented edges"
```

---

## Final Verification

- [ ] **Final: Full build smoke test**

Run a full build against the target codebase to verify all changes work end-to-end:

```bash
code-graph build -c config.yml
```

Verify in the output:
1. New edge properties appear in Memgraph (query: `MATCH ()-[r:CALLS]->() WHERE r.resolution_confidence IS NOT NULL RETURN count(r)`)
2. Dynamic prefix expansion shows stats (prefixes processed)
3. Go import resolution improved from ~60% to ~85-90%
4. Ruby gem classification shows `__ruby_gem__` sentinel usage
5. Python stdlib imports classified as `__python_stdlib__`

---

## Expected Impact Summary

| Task | Metric | Before | After |
|------|--------|--------|-------|
| 1. Edge properties | Graph queryability | 6 fields lost | All written |
| 2. Dynamic prefix | False positive edges | Unknown | Eliminated |
| 3. Base inheritance | Auto-detection | Hardcoded 31 methods | Dynamic from AST |
| 4. Python stdlib | Import classification | 36.7% resolved, rest unknown | Stdlib/third-party split |
| 5. Go go.mod | Go import resolution | 60.2% | ~85-90% |
| 6. Ruby Gemfile | Ruby import classification | 42.3% resolved, rest unknown | Gem/stdlib/internal split |
| 7. Schema | Documentation | Missing properties/edges | All documented |
