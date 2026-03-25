# Call Resolution Final Push — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push call resolution from 43% to ~55-58% (effective ~72-75% with builtins) by implementing three codebase-specific pattern matchers: parameter name→module mapping, base class method inheritance, and dynamic require prefix→directory expansion.

**Architecture:** Three independent resolvers, each exploiting a known stable pattern confirmed by 4 rounds of BOB investigation. These are NOT general-purpose type inference — they are codebase-specific lookup tables for known conventions (parameter names, base modules, require prefixes). They run after CallResolver, enriching unresolved calls with domain knowledge.

**Tech Stack:** Python 3.11+, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/resolvers/parameter_resolver.py` | Create | Map parameter names (web, store, bundle) to source modules |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Create | Map self:method() to base module methods (3 bases, 1 level) |
| `graph_builder/resolvers/dynamic_prefix_resolver.py` | Create | Expand dynamic require prefixes to directory file lists |
| `graph_builder/resolvers/call_resolver.py` | Modify | Add parameter-name resolution as a new strategy |
| `graph_builder/main.py` | Modify | Integrate new resolvers into build pipeline |
| `graph_builder/validate/graph_health.py` | Modify | Wire Go stdlib + report new resolution stats |
| `graph_builder/tests/test_call_resolution_final.py` | Create | Tests for all 3 resolvers |
| `graph_builder/tests/fixtures/lua/param_handler.lua` | Create | Test fixture with parameter method calls |
| `graph_builder/tests/fixtures/lua/child_handler.lua` | Create | Test fixture with inherited self:method() |

---

## Task 1: Parameter Name→Module Resolver

Handlers receive `(input, bundle, web)` as parameters. BOB confirmed:
- `bundle` is ALWAYS called `bundle` → comes from `lib.lua.bundle`
- `web`/`store` are interchangeable → both are Store instances from `lib.lua.store`
- `assessor_context` is a metadata table, not the `context` module
- `input` is a plain table with NO methods — skip it

When the call resolver sees `bundle:get(key)` and `bundle` is NOT in the binding map, this resolver checks if `bundle` is a known parameter name and resolves the call to the appropriate module.

**Files:**
- Create: `graph_builder/resolvers/parameter_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/param_handler.lua`
- Create: `graph_builder/tests/test_call_resolution_final.py`
- Modify: `graph_builder/resolvers/call_resolver.py`

### Step 1: Create test fixture

- [ ] **1.1: Create handler fixture with parameter calls**

Create `graph_builder/tests/fixtures/lua/param_handler.lua`:

```lua
local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    local feature_enabled = bundle:get("features.fraud_detection", false)
    local session_data = web.store:get("session:" .. input.session_id)
    local user_data = web.store:hget("users", input.user_id)

    if feature_enabled then
        store:set("processed:" .. input.session_id, "true")
    end
end

function M:assess(bundle, store, assessor_context)
    local config_value = bundle:get("config.threshold", 0.5)
    local device_data = store:hget("devices", "device_123")
    store:set("assessment:done", "true")
end

return M
```

### Step 2: Write tests

- [ ] **2.1: Create test file**

Create `graph_builder/tests/test_call_resolution_final.py`:

```python
"""Tests for final call resolution improvements."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.parameter_resolver import resolve_parameter_calls, PARAMETER_TYPE_MAP

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_parameter_type_map_has_known_params():
    """Parameter type map should have bundle, web, store."""
    assert "bundle" in PARAMETER_TYPE_MAP
    assert "web" in PARAMETER_TYPE_MAP
    assert "store" in PARAMETER_TYPE_MAP
    assert "input" not in PARAMETER_TYPE_MAP  # input is a plain table


def test_bundle_get_resolved():
    """bundle:get() should resolve to lib.lua.bundle module."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    all_asts = {"test.lua": ast}

    resolved_count = resolve_parameter_calls(all_asts)
    assert resolved_count > 0

    bundle_calls = [c for c in ast.calls
                    if c.callee_string in ("bundle:get", "bundle.get")
                    and c.resolved_module is not None]
    assert len(bundle_calls) >= 1
    assert bundle_calls[0].resolved_module == "lib.lua.bundle"


def test_store_methods_resolved():
    """store:get/hget/set should resolve to lib.lua.store module."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    all_asts = {"test.lua": ast}

    resolve_parameter_calls(all_asts)

    store_calls = [c for c in ast.calls
                   if "store" in c.callee_string.split(":")[0].split(".")[-1]
                   and c.resolved_module is not None]
    # Should resolve store:hget, store:get, store:set
    assert len(store_calls) >= 1


def test_already_resolved_not_overwritten():
    """Calls already resolved by CallResolver should not be overwritten."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    # Manually mark a call as already resolved
    for call in ast.calls:
        if "base" in call.callee_string:
            call.resolved_module = "already.resolved"
            break

    all_asts = {"test.lua": ast}
    resolve_parameter_calls(all_asts)

    # Verify the manually resolved call wasn't overwritten
    for call in ast.calls:
        if call.resolved_module == "already.resolved":
            assert True
            return
```

- [ ] **2.2: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_call_resolution_final.py -v`
Expected: ImportError — `parameter_resolver` module doesn't exist

### Step 3: Implement parameter resolver

- [ ] **3.1: Create parameter_resolver.py**

Create `graph_builder/resolvers/parameter_resolver.py`:

```python
"""Parameter name→module resolver for Lua handler/assessor conventions.

In the Pinpoint codebase, handlers and assessors receive well-known parameters:
  - bundle → lib.lua.bundle (config access via bundle:get())
  - web/store → lib.lua.store (Redis access via store:get/set/hget)
  - context → lib.lua.context (request context, but usually imported via require)

This resolver checks unresolved calls where the table/receiver name matches
a known parameter name, and resolves them to the corresponding module.

This is NOT general-purpose type inference. It's a codebase-specific lookup
table for known, stable conventions confirmed through investigation.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST

# Known parameter name → module string mappings
# Confirmed by BOB investigation rounds 2-3:
#   - bundle is ALWAYS called "bundle", comes from lib.lua.bundle
#   - web and store are interchangeable names for Store instances
#   - context is usually imported via require, not a parameter
#   - input is a plain table with no methods — not mapped
PARAMETER_TYPE_MAP: dict[str, str] = {
    "bundle": "lib.lua.bundle",
    "web": "lib.lua.store",
    "store": "lib.lua.store",
}

# Store sub-objects: web.store → lib.lua.store
# When we see web.store:method(), the receiver chain is "web.store"
CHAINED_PARAMETER_MAP: dict[str, str] = {
    "web.store": "lib.lua.store",
}


def resolve_parameter_calls(all_asts: dict[str, FileAST]) -> int:
    """Resolve unresolved calls on known parameter names.

    For each unresolved Lua call like 'bundle:get' or 'store:hget',
    check if the receiver matches a known parameter name and resolve
    to the corresponding module.

    Returns the number of newly resolved calls.
    """
    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        for call in ast.calls:
            # Skip already resolved
            if call.resolved_module:
                continue

            callee = call.callee_string
            receiver = None
            method = None

            # Split on : or . to get receiver and method
            for sep in (":", "."):
                if sep in callee:
                    parts = callee.split(sep, 1)
                    receiver = parts[0]
                    method = parts[1]
                    break

            if not receiver or not method:
                continue

            # Check chained parameters first (web.store:method → lib.lua.store)
            for chain, module in CHAINED_PARAMETER_MAP.items():
                if callee.startswith(chain + ":") or callee.startswith(chain + "."):
                    actual_method = callee.split(":", 1)[-1] if ":" in callee else callee.split(".")[-1]
                    call.resolved_module = module
                    call.resolved_function = actual_method
                    call.resolution_confidence = "parameter"
                    resolved_count += 1
                    break
            else:
                # Check direct parameter names (bundle:get → lib.lua.bundle)
                if receiver in PARAMETER_TYPE_MAP:
                    call.resolved_module = PARAMETER_TYPE_MAP[receiver]
                    call.resolved_function = method
                    call.resolution_confidence = "parameter"
                    resolved_count += 1

    return resolved_count
```

- [ ] **3.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_call_resolution_final.py -v`
Expected: All tests pass

### Step 4: Integrate into pipeline

- [ ] **4.1: Add to main.py**

In `graph_builder/main.py`, after the call resolver step and before the builtin classifier, add:

```python
    # Step 4b2: Resolve parameter name calls
    click.echo("Resolving parameter-name calls...")
    from .resolvers.parameter_resolver import resolve_parameter_calls
    param_resolved = resolve_parameter_calls(all_asts)
    if param_resolved:
        click.echo(f"  Parameter calls resolved: {param_resolved}")
```

- [ ] **4.2: Run all tests and commit**

Run: `python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: parameter name→module resolver for bundle/store/web

Maps known parameter names to their source modules:
bundle → lib.lua.bundle, web/store → lib.lua.store.
Expected: +3,000-5,000 resolved calls."
```

---

## Task 2: Base Class Method Inheritance Resolver

BOB confirmed 3 base modules with single-level inheritance:
- `common.base.lua.handler` → methods: `new, apply, validate_input, handle_error, log_error, user_error, system_error`
- `common.base.lua.assessor` → methods: `new, assess, validate_bundle, get_feature_flag, log_assessment`
- `common.base.lua.collector` → methods: `new, collect, store_data`

When `self:validate_input()` is called in a handler file that inherits from `common.base.lua.handler`, and `validate_input` is NOT defined in the current file, the resolver should check if it's defined in the base module.

**Files:**
- Create: `graph_builder/resolvers/base_inheritance_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/child_handler.lua`
- Add to: `graph_builder/tests/test_call_resolution_final.py`

### Step 1: Create fixture

- [ ] **1.1: Create child handler fixture**

Create `graph_builder/tests/fixtures/lua/child_handler.lua`:

```lua
local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    -- validate_input is defined in the base handler, not here
    if not self:validate_input(input) then
        return self:user_error("Invalid input")
    end

    -- process is defined HERE in this file
    local result = self:process(input, web)

    -- log_error is defined in the base handler
    if not result then
        self:log_error("Processing failed")
    end

    return result
end

function M:process(input, web)
    return {status = "ok"}
end

return M
```

### Step 2: Write tests

- [ ] **2.1: Add inheritance tests**

Add to `graph_builder/tests/test_call_resolution_final.py`:

```python
from graph_builder.resolvers.base_inheritance_resolver import resolve_base_inheritance


def test_inherited_method_resolved():
    """self:validate_input() should resolve to base handler module when not in current file."""
    ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
    all_asts = {"test.lua": ast}

    resolved_count = resolve_base_inheritance(all_asts)
    assert resolved_count > 0

    # validate_input is NOT defined in child_handler.lua
    # It should resolve to common.base.lua.handler
    vi_calls = [c for c in ast.calls
                if "validate_input" in c.callee_string
                and c.resolved_module is not None]
    assert len(vi_calls) >= 1
    assert vi_calls[0].resolved_module == "common.base.lua.handler"


def test_same_file_method_not_overridden():
    """self:process() defined in the same file should NOT be resolved to base."""
    ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
    all_asts = {"test.lua": ast}

    resolve_base_inheritance(all_asts)

    # process IS defined in child_handler.lua
    # self:process should already be resolved by CallResolver's self: handling
    # NOT overridden to base module
    process_calls = [c for c in ast.calls
                     if "process" in c.callee_string
                     and c.resolved_module is not None]
    for pc in process_calls:
        assert pc.resolved_module != "common.base.lua.handler"
```

### Step 3: Implement

- [ ] **3.1: Create base_inheritance_resolver.py**

```python
"""Base class method inheritance resolver for Lua OOP patterns.

The Pinpoint codebase has 3 base modules that children inherit from via
setmetatable({}, {__index = base}). When self:method() is called and
the method is NOT defined in the current file, it's inherited from the base.

Base modules (confirmed by BOB investigation round 3):
  - common.base.lua.handler → validate_input, handle_error, log_error, user_error, system_error
  - common.base.lua.assessor → validate_bundle, get_feature_flag, log_assessment
  - common.base.lua.collector → store_data

This resolver checks:
1. Does the file import a known base module via require/require_version?
2. Is there a self:method() call that's unresolved?
3. Is the method NOT defined in the current file?
4. Is the method defined in the base module?
If all yes → resolve to the base module.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST

# Base module → set of methods they define
# Only methods that children commonly inherit (not 'new' or the overridable entry points)
BASE_MODULE_METHODS: dict[str, set[str]] = {
    "common.base.lua.handler": {
        "validate_input", "handle_error", "log_error",
        "user_error", "system_error",
    },
    "common.base.lua.assessor": {
        "validate_bundle", "get_feature_flag", "log_assessment",
    },
    "common.base.lua.collector": {
        "store_data",
    },
}

# All base module paths (for matching imports)
_BASE_MODULE_STRINGS = set(BASE_MODULE_METHODS.keys())


def resolve_base_inheritance(all_asts: dict[str, FileAST]) -> int:
    """Resolve inherited self:method() calls to base module methods.

    Returns the number of newly resolved calls.
    """
    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        # Step 1: Does this file import a known base module?
        base_module = None
        for imp in ast.imports:
            if imp.module_string in _BASE_MODULE_STRINGS:
                base_module = imp.module_string
                break

        if not base_module:
            continue

        base_methods = BASE_MODULE_METHODS[base_module]

        # Step 2: Get methods defined in THIS file
        local_methods = set()
        for func in ast.functions:
            bare_name = func.name.split(".")[-1].split(":")[-1]
            local_methods.add(bare_name)

        # Step 3: For each unresolved self:method() call,
        # if method is in base_methods but NOT in local_methods → resolve
        for call in ast.calls:
            if call.resolved_module:
                continue

            callee = call.callee_string
            if not (callee.startswith("self:") or callee.startswith("self.")):
                continue

            method = callee.split(":", 1)[-1] if ":" in callee else callee.split(".", 1)[-1]

            # Only resolve if method is NOT in the current file
            # (same-file self: calls should already be resolved by CallResolver)
            if method in local_methods:
                continue

            if method in base_methods:
                call.resolved_module = base_module
                call.resolved_function = method
                call.resolution_confidence = "base_inherited"
                resolved_count += 1

    return resolved_count
```

- [ ] **3.2: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_call_resolution_final.py -v && python -m pytest graph_builder/tests/ -v`

### Step 4: Integrate

- [ ] **4.1: Add to main.py**

After the parameter resolver step:

```python
    # Step 4b3: Resolve inherited base class methods
    from .resolvers.base_inheritance_resolver import resolve_base_inheritance
    base_resolved = resolve_base_inheritance(all_asts)
    if base_resolved:
        click.echo(f"  Base-inherited calls resolved: {base_resolved}")
```

- [ ] **4.2: Commit**

```bash
git commit -m "feat: base class inheritance resolver for self:method()

When self:method() is unresolved and the method exists in a known base
module (handler/assessor/collector) but not in the current file, resolve
to the base module. 3 bases, single-level, ~2500 calls."
```

---

## Task 3: Dynamic Require Prefix→Directory Resolution

76 dynamic requires use `require(format("handlers.%s", name))`. The `static_prefix` is already extracted by the parser (e.g., `"handlers."`). This resolver expands each prefix to create potential edges to ALL files in the matching directory.

**Files:**
- Create: `graph_builder/resolvers/dynamic_prefix_resolver.py`
- Add to: `graph_builder/tests/test_call_resolution_final.py`
- Modify: `graph_builder/main.py`
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Write tests

- [ ] **1.1: Add dynamic prefix tests**

Add to `graph_builder/tests/test_call_resolution_final.py`:

```python
from graph_builder.resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes


def test_dynamic_prefix_expansion():
    """Dynamic requires with static_prefix should expand to potential targets."""
    from graph_builder.parsers.base import FileAST, ImportRef

    # Simulate a file with dynamic require
    ast = FileAST(file_path="src/tasks/dispatcher.lua", language="lua")
    ast.imports.append(ImportRef(
        module_string='format("tasks.%s", task_name)',
        line=10,
        import_type="require",
        is_dynamic=True,
        static_prefix="tasks.",
    ))

    # Simulate some task files that should match
    task_ast1 = FileAST(file_path="src/ato/tasks/pts_run.lua", language="lua")
    task_ast1.module_name = "ato.tasks.pts_run"
    task_ast2 = FileAST(file_path="src/ato/tasks/assess.lua", language="lua")
    task_ast2.module_name = "ato.tasks.assess"
    unrelated = FileAST(file_path="src/lib/lua/store.lua", language="lua")
    unrelated.module_name = "lib.lua.store"

    all_asts = {
        "src/tasks/dispatcher.lua": ast,
        "src/ato/tasks/pts_run.lua": task_ast1,
        "src/ato/tasks/assess.lua": task_ast2,
        "src/lib/lua/store.lua": unrelated,
    }

    edges = resolve_dynamic_prefixes(all_asts)

    # Should find the task files matching the "tasks." prefix
    assert len(edges) >= 2
    target_files = [e["target_file"] for e in edges]
    assert "src/ato/tasks/pts_run.lua" in target_files
    assert "src/ato/tasks/assess.lua" in target_files
    assert "src/lib/lua/store.lua" not in target_files


def test_no_dynamic_prefix_no_edges():
    """Files without dynamic requires should produce no edges."""
    ast = FileAST(file_path="src/normal.lua", language="lua")
    all_asts = {"src/normal.lua": ast}

    edges = resolve_dynamic_prefixes(all_asts)
    assert len(edges) == 0
```

### Step 2: Implement

- [ ] **2.1: Create dynamic_prefix_resolver.py**

```python
"""Dynamic require prefix→directory resolution.

Lua files with dynamic requires like:
    require(format("handlers.%s", name))
have a static_prefix extracted by the parser (e.g., "handlers.").

This resolver expands each prefix by finding all modules whose
module_name starts with a matching path segment. This creates
POTENTIAL_IMPORT edges — we know the source file MIGHT import
any of these targets, though we can't know which one at static time.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def resolve_dynamic_prefixes(all_asts: dict[str, FileAST]) -> list[dict]:
    """Expand dynamic require prefixes to potential import targets.

    Returns list of dicts:
        [{"source_file": "...", "target_file": "...", "prefix": "...", "line": N}]
    """
    edges = []

    # Collect all module names for matching
    module_to_file: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.module_name:
            module_to_file[ast.module_name] = file_path

    # Find dynamic imports with static prefixes
    for file_path, ast in all_asts.items():
        for imp in ast.imports:
            if not imp.is_dynamic or not imp.static_prefix:
                continue

            prefix = imp.static_prefix
            # Normalize prefix: "handlers." → "handlers."
            # The prefix is the start of the module string before the dynamic part

            # Find all modules matching this prefix
            for mod_name, target_file in module_to_file.items():
                # Check if module name contains the prefix as a path segment
                # "tasks." should match "ato.tasks.pts_run" (contains "tasks.")
                # "handlers." should match "ato.handlers.policy" (contains "handlers.")
                if prefix in mod_name:
                    # Don't self-reference
                    if target_file != file_path:
                        edges.append({
                            "source_file": file_path,
                            "target_file": target_file,
                            "prefix": prefix,
                            "line": imp.line,
                        })

    return edges
```

- [ ] **2.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_call_resolution_final.py -v`

### Step 3: Integrate

- [ ] **3.1: Add POTENTIAL_IMPORT edge to writer.py**

```python
def upsert_potential_import(self, source_file: str, target_file: str,
                             prefix: str, line: int):
    """Create a POTENTIAL_IMPORT edge from dynamic require prefix expansion."""
    self._run("""
        MERGE (src:File {path: $source})
        MERGE (tgt:File {path: $target})
        MERGE (src)-[:POTENTIAL_IMPORT {prefix: $prefix, line: $line, dynamic: true}]->(tgt)
    """, source=source_file, target=target_file, prefix=prefix, line=line)
```

- [ ] **3.2: Add to main.py**

After the base inheritance step:

```python
    # Step 4b4: Expand dynamic require prefixes
    from .resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes
    dynamic_edges = resolve_dynamic_prefixes(all_asts)
    if dynamic_edges:
        click.echo(f"  Dynamic prefix expansion: {len(dynamic_edges)} potential imports")
```

- [ ] **3.3: Run all tests and commit**

Run: `python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: dynamic require prefix→directory expansion

Expands require(format('handlers.%s', name)) prefixes to all matching
module files. Creates POTENTIAL_IMPORT edges showing which files a
dynamic dispatcher MIGHT load. 76 dynamic requires → ~200-300 edges."
```

---

## Task 4: Wire Go Stdlib Into Health Report

The Go stdlib classification exists in the resolver but health report doesn't use it, so Go still shows 0% import resolution and 73 orphans in health output.

**Files:**
- Modify: `graph_builder/validate/graph_health.py`

- [ ] **4.1: Add Go stdlib handling to health report**

In `graph_builder/validate/graph_health.py`, find the import resolution loop (similar to main.py's). Add the same Go stdlib check:

```python
# In the import resolution section of health report:
if ast.language == "go":
    go_resolver = resolvers.get("go")
    if go_resolver and hasattr(go_resolver, 'is_stdlib') and go_resolver.is_stdlib(imp.module_string):
        file_resolved[imp.module_string] = "__go_stdlib__"
        continue
```

- [ ] **4.2: Run all tests and commit**

```bash
git commit -m "fix: wire Go stdlib classification into health report

Health report now recognizes Go stdlib imports (fmt, context, net/http)
as resolved. Fixes misleading 0% Go import resolution in health output."
```

---

## Integration Verification

After all 4 tasks:

- [ ] **Run full test suite**

```bash
python -m pytest graph_builder/tests/ -v
```

- [ ] **Run on product codebase** (on Mac)

```bash
code-graph health -c config.yml
```

Expected improvements:
- Call resolution: 43.1% → ~55-58%
- Effective coverage: 59.8% → ~72-75%
- Truly unresolved: 18,235 → ~10,000-12,000
- Go import resolution: 0% → ~60%+ (stdlib classified)
- Parameter calls: +3,000-5,000 (bundle:get, store:get/set/hget)
- Base-inherited calls: +2,500 (self:validate_input, self:log_error, etc.)
- Dynamic prefix edges: +200-300 potential import edges

---

## Summary

| Task | Expected Impact | Method |
|------|----------------|--------|
| 1. Parameter resolver | +3,000-5,000 calls | Lookup table: bundle→Bundle, store/web→Store |
| 2. Base inheritance | +2,500 calls | 3 base modules × known methods |
| 3. Dynamic prefix | +200-300 edges | Expand static_prefix to matching files |
| 4. Health Go stdlib | Fix 0% → ~60% | Wire existing is_stdlib() into health |
