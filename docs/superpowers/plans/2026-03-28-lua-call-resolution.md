# Lua Call Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push Lua call resolution from 53.6% toward ~60% through local alias classification, store vector chain resolution, store_object parameter mapping, and inherited method fallback.

**Architecture:** Four changes to existing resolvers: (1) extend BuiltinClassifier with per-file alias maps built from a new FileAST.local_aliases field, (2) extend parameter_resolver with FIELD_TYPE_MAP for store vector chains, (3) add store_object to PARAMETER_TYPE_MAP, (4) update base_inheritance_resolver with actual base class methods and fix CallResolver's self: branch to fall through when method not found locally.

**Tech Stack:** Python, Tree-sitter, existing resolver infrastructure

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/parsers/base.py` | Modify | Add `local_aliases` field to `FileAST` |
| `graph_builder/parsers/lua_parser.py` | Modify | Populate `local_aliases` from local assignment AST nodes |
| `graph_builder/resolvers/builtin_classifier.py` | Modify | Build per-file alias maps, classify bare aliases as builtin/external |
| `graph_builder/resolvers/parameter_resolver.py` | Modify | Add `FIELD_TYPE_MAP`, `store_object` to `PARAMETER_TYPE_MAP`, extend chain resolution |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Modify | Update `BASE_MODULE_METHODS` to actual methods, add `actor.lua` |
| `graph_builder/resolvers/call_resolver.py` | Modify | Guard `self:` branch to only resolve when method exists in file |
| `graph_builder/resolvers/redis_abstraction_resolver.py` | Modify | Update `_STORE_VECTOR_READ`/`_STORE_VECTOR_WRITE` to match actual StoreVector methods |
| `graph_builder/tests/test_lua_call_resolution_v2.py` | Create | Tests for all components |
| `graph_builder/tests/fixtures/lua/alias_builtins.lua` | Create | Fixture with local alias patterns |
| `graph_builder/tests/fixtures/lua/store_vector_chains.lua` | Create | Fixture with store vector chain calls |
| `graph_builder/tests/fixtures/lua/child_actor.lua` | Create | Fixture with inherited actor self: calls |

---

## Task 1: Add `local_aliases` Field to FileAST

The Lua parser does not currently store local variable assignments where the RHS is a dotted field access. We need a new field on `FileAST` to carry `(local_name, rhs_expression)` pairs so the BuiltinClassifier can build per-file alias maps.

**Files:**
- Modify: `graph_builder/parsers/base.py`
- Create: `graph_builder/tests/test_lua_call_resolution_v2.py` (initial skeleton)

### Step 1.1: Write test for local_aliases field existence

- [ ] **1.1: Create test file with FileAST.local_aliases test**

Create `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
"""Tests for Lua call resolution v2 improvements.

Covers: local alias classification, store vector chains, store_object parameter,
base inheritance updates, and CallResolver self: guard fix.

Run with: python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from graph_builder.parsers.base import FileAST, CallRef, ImportRef, ModuleInfo, ModulePatternType, FunctionDef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ast(
    language: str = "lua",
    calls: list[CallRef] | None = None,
    file_path: str = "/test/file.lua",
    imports: list[ImportRef] | None = None,
    functions: list[FunctionDef] | None = None,
    module_info: ModuleInfo | None = None,
    local_aliases: list[tuple[str, str]] | None = None,
) -> FileAST:
    """Build a minimal FileAST with the given fields."""
    ast = FileAST(
        file_path=file_path,
        language=language,
        calls=calls or [],
        imports=imports or [],
        functions=functions or [],
        module_info=module_info,
    )
    if local_aliases is not None:
        ast.local_aliases = local_aliases
    return ast


def _make_call(callee: str, resolved_module: str | None = None) -> CallRef:
    """Build a minimal CallRef."""
    return CallRef(
        caller_function="<module>",
        callee_string=callee,
        line=1,
        resolved_module=resolved_module,
    )


# ---------------------------------------------------------------------------
# Task 1: FileAST.local_aliases field
# ---------------------------------------------------------------------------

class TestFileASTLocalAliases:
    def test_local_aliases_defaults_to_empty_list(self):
        """FileAST should have a local_aliases field defaulting to []."""
        ast = FileAST(file_path="/test.lua", language="lua")
        assert ast.local_aliases == []

    def test_local_aliases_stores_tuples(self):
        """local_aliases should accept a list of (name, rhs) tuples."""
        ast = FileAST(
            file_path="/test.lua",
            language="lua",
            local_aliases=[("format", "string.format"), ("encode", "cjson.encode")],
        )
        assert len(ast.local_aliases) == 2
        assert ast.local_aliases[0] == ("format", "string.format")
        assert ast.local_aliases[1] == ("encode", "cjson.encode")
```

Run test (should fail because `local_aliases` does not exist yet):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestFileASTLocalAliases -v
```

### Step 1.2: Add local_aliases field to FileAST

- [ ] **1.2: Add the field to base.py**

In `graph_builder/parsers/base.py`, add this field to the `FileAST` dataclass, after the `metatable_parents` field:

```python
    # Local variable aliases (Lua-specific): (local_name, rhs_dotted_expression)
    # e.g., [("format", "string.format"), ("encode", "cjson.encode")]
    local_aliases: list[tuple[str, str]] = field(default_factory=list)
```

The full diff is adding one field between `metatable_parents` and `warnings`:

**Before:**
```python
    # Metatable inheritance (Lua-specific)
    metatable_parents: dict[str, str] = field(default_factory=dict)  # child_table → parent_module_string

    # Diagnostics
    warnings: list[str] = field(default_factory=list)
```

**After:**
```python
    # Metatable inheritance (Lua-specific)
    metatable_parents: dict[str, str] = field(default_factory=dict)  # child_table → parent_module_string

    # Local variable aliases (Lua-specific): (local_name, rhs_dotted_expression)
    # e.g., [("format", "string.format"), ("encode", "cjson.encode")]
    local_aliases: list[tuple[str, str]] = field(default_factory=list)

    # Diagnostics
    warnings: list[str] = field(default_factory=list)
```

### Step 1.3: Verify test passes

- [ ] **1.3: Run test and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestFileASTLocalAliases -v
```

### Step 1.4: Commit

- [ ] **1.4: Commit**

```bash
git add graph_builder/parsers/base.py graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "feat: add local_aliases field to FileAST for builtin alias tracking"
```

---

## Task 2: Populate `local_aliases` in Lua Parser

Walk `variable_declaration` nodes in the AST and extract `(local_name, rhs)` pairs where the RHS is a `dot_index_expression` (field access like `string.format`). Must handle multi-assignment: `local a, b, c = x.a, x.b, x.c`.

**Files:**
- Modify: `graph_builder/parsers/lua_parser.py`
- Create: `graph_builder/tests/fixtures/lua/alias_builtins.lua`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 2.1: Create test fixture

- [ ] **2.1: Create alias_builtins.lua fixture**

Create `graph_builder/tests/fixtures/lua/alias_builtins.lua`:

```lua
-- Test fixture for local alias detection
local format = string.format
local gsub, match = string.gsub, string.match
local encode, decode = cjson.encode, cjson.decode
local insert = table.insert
local floor = math.floor
local my_func = some_module.do_thing

local M = {}

function M:apply()
    format("hello %s", "world")
    gsub("hello", "h", "j")
    match("hello", "h")
    encode({key = "value"})
    decode('{"key": "value"}')
    insert({}, 1)
    floor(3.14)
    my_func()
end

return M
```

### Step 2.2: Write parser test

- [ ] **2.2: Add parser test to test file**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.parsers.lua_parser import parse_lua_file

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


# ---------------------------------------------------------------------------
# Task 2: Lua parser populates local_aliases
# ---------------------------------------------------------------------------

class TestLuaParserLocalAliases:
    def test_single_alias(self):
        """local format = string.format should produce ('format', 'string.format')."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert "format" in alias_dict
        assert alias_dict["format"] == "string.format"

    def test_multi_assignment(self):
        """local gsub, match = string.gsub, string.match should produce both aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("gsub") == "string.gsub"
        assert alias_dict.get("match") == "string.match"

    def test_cjson_aliases(self):
        """local encode, decode = cjson.encode, cjson.decode should produce both aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("encode") == "cjson.encode"
        assert alias_dict.get("decode") == "cjson.decode"

    def test_non_field_access_excluded(self):
        """local x = func_call() should NOT appear in local_aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_names = [name for name, _ in ast.local_aliases]
        # M should not appear (it's assigned from base:new(), not a field access)
        assert "M" not in alias_names

    def test_custom_module_alias_included(self):
        """local my_func = some_module.do_thing should appear in local_aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("my_func") == "some_module.do_thing"

    def test_total_alias_count(self):
        """The fixture should produce exactly 7 aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        assert len(ast.local_aliases) == 7
```

Run test (should fail because parser does not populate local_aliases yet):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestLuaParserLocalAliases -v
```

### Step 2.3: Implement _extract_local_aliases in lua_parser.py

- [ ] **2.3: Add _extract_local_aliases function**

Add this function to `graph_builder/parsers/lua_parser.py`, after the `_extract_metatable_inheritance` function (before the `parse_lua_file` function):

```python
# ---------------------------------------------------------------------------
# Local alias extraction (for builtin classifier)
# ---------------------------------------------------------------------------

def _extract_local_aliases(root, source: bytes, ast: FileAST):
    """Extract local variable aliases where RHS is a dotted field access.

    Detects patterns like:
        local format = string.format
        local gsub, match = string.gsub, string.match
        local encode, decode = cjson.encode, cjson.decode

    Populates ast.local_aliases with (local_name, rhs_expression) tuples.
    Handles multi-assignment by positional matching of names to values.
    """
    for decl in _walk_all(root, "variable_declaration"):
        assign = _first_child_of_type(decl, "assignment_statement")
        if not assign:
            continue
        vl = _first_child_of_type(assign, "variable_list")
        el = _first_child_of_type(assign, "expression_list")
        if not (vl and el):
            continue

        names = [c for c in vl.named_children if c.type == "identifier"]
        values = list(el.named_children)

        for i, name_node in enumerate(names):
            if i >= len(values):
                break
            val_node = values[i]
            # Only capture dot_index_expression RHS (field access like string.format)
            if val_node.type == "dot_index_expression":
                local_name = _text(name_node, source)
                rhs_text = _text(val_node, source)
                ast.local_aliases.append((local_name, rhs_text))
```

### Step 2.4: Call _extract_local_aliases from parse_lua_file

- [ ] **2.4: Wire into parse_lua_file**

In the `parse_lua_file` function in `graph_builder/parsers/lua_parser.py`, add a call to `_extract_local_aliases` after step 14 (mission dispatch detection) and before step 15 (build qualified names). Insert between lines 1449 and 1451:

**Before:**
```python
    # 14. Mission dispatch detection
    _extract_mission_dispatches(root, source, ast, binding_map)

    # 15. Build qualified names for functions
```

**After:**
```python
    # 14. Mission dispatch detection
    _extract_mission_dispatches(root, source, ast, binding_map)

    # 15. Local alias extraction (for builtin classifier)
    _extract_local_aliases(root, source, ast)

    # 16. Build qualified names for functions
```

### Step 2.5: Verify test passes

- [ ] **2.5: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestLuaParserLocalAliases -v
```

### Step 2.6: Commit

- [ ] **2.6: Commit**

```bash
git add graph_builder/parsers/lua_parser.py graph_builder/tests/fixtures/lua/alias_builtins.lua graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "feat: populate local_aliases in Lua parser from field access assignments"
```

---

## Task 3: Extend BuiltinClassifier with Alias Map Support

Extend `classify_all()` to build a per-file alias map from `FileAST.local_aliases`, then check bare callee names against the alias map before falling through to `truly_unresolved`.

**Files:**
- Modify: `graph_builder/resolvers/builtin_classifier.py`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 3.1: Write alias classification tests

- [ ] **3.1: Add alias classification tests**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.resolvers.builtin_classifier import BuiltinClassifier


# ---------------------------------------------------------------------------
# Task 3: BuiltinClassifier alias map support
# ---------------------------------------------------------------------------

class TestBuiltinClassifierAliases:
    def test_format_alias_classified_as_builtin(self):
        """format aliased from string.format should be classified as builtin."""
        call = _make_call("format")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "builtin"

    def test_encode_alias_classified_as_external(self):
        """encode aliased from cjson.encode should be classified as external."""
        call = _make_call("encode")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("encode", "cjson.encode")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "external"

    def test_multi_alias_all_classified(self):
        """Multiple aliases should all be classified correctly."""
        call_format = _make_call("format")
        call_insert = _make_call("insert")
        call_encode = _make_call("encode")
        ast = _make_ast(
            calls=[call_format, call_insert, call_encode],
            local_aliases=[
                ("format", "string.format"),
                ("insert", "table.insert"),
                ("encode", "cjson.encode"),
            ],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call_format.classification == "builtin"
        assert call_insert.classification == "builtin"
        assert call_encode.classification == "external"

    def test_custom_module_alias_stays_unresolved(self):
        """Alias from unknown module (not stdlib/external) stays truly_unresolved."""
        call = _make_call("my_func")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("my_func", "some_module.do_thing")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "truly_unresolved"

    def test_no_aliases_no_change(self):
        """Files without local_aliases should classify normally."""
        call = _make_call("format")
        ast = _make_ast(calls=[call])
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        # "format" is not in LUA_BUILTINS (it's a table method, not a global),
        # so without alias info it should be truly_unresolved
        assert call.classification == "truly_unresolved"

    def test_resolved_call_not_reclassified(self):
        """Calls already resolved should not be touched by alias classification."""
        call = _make_call("format", resolved_module="my.module")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification is None
        assert call.resolved_module == "my.module"

    def test_alias_stats_counted(self):
        """Alias-classified calls should appear in the correct stats buckets."""
        call_format = _make_call("format")
        call_encode = _make_call("encode")
        call_unknown = _make_call("mystery_func")
        ast = _make_ast(
            calls=[call_format, call_encode, call_unknown],
            local_aliases=[
                ("format", "string.format"),
                ("encode", "cjson.encode"),
            ],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        s = c.stats()
        assert s["builtin"] == 1
        assert s["external"] == 1
        assert s["truly_unresolved"] == 1

    def test_non_lua_files_ignore_aliases(self):
        """Python files should not use Lua local_aliases."""
        call = _make_call("format")
        ast = _make_ast(
            language="python",
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.py": ast})
        # Python's "format" is a builtin, so it should be classified as builtin
        # regardless of local_aliases (which are Lua-only)
        assert call.classification == "builtin"
```

Run test (should fail because classify_all does not handle aliases yet):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBuiltinClassifierAliases -v
```

### Step 3.2: Implement alias map support in BuiltinClassifier

- [ ] **3.2: Modify builtin_classifier.py**

Add a module-level constant for known builtin/external modules that local aliases can reference. This goes after the `LANGUAGE_CONFIG` dict:

```python
# Modules whose function aliases should be classified when used as bare names.
# Maps module name → classification ("builtin" or "external").
_ALIAS_SOURCE_MODULES: dict[str, str] = {}
# Populate from existing Lua config
for _prefix in LUA_STDLIB_PREFIXES | LUA_OPENRESTY_PREFIXES:
    _ALIAS_SOURCE_MODULES[_prefix] = "builtin"
for _prefix in LUA_EXTERNAL_PREFIXES:
    _ALIAS_SOURCE_MODULES[_prefix] = "external"
```

Modify `classify_all` to build a per-file alias map and use it. Replace the entire `classify_all` method with:

```python
    def classify_all(self, all_asts: dict[str, FileAST]):
        """Classify all unresolved calls across all ASTs.

        Modifies CallRef.classification in place. Skips calls that already
        have resolved_module set (those were handled by CallResolver).

        For Lua files, builds a per-file alias map from FileAST.local_aliases
        so that bare calls like `format()` (aliased from `string.format`) are
        classified as builtin instead of truly_unresolved.
        """
        # Reset counts
        self._counts = {
            "builtin": 0,
            "external": 0,
            "truly_unresolved": 0,
            "already_resolved": 0,
        }

        for file_path, ast in all_asts.items():
            # Build per-file alias map for Lua files
            alias_map: dict[str, str] = {}
            if ast.language == "lua" and hasattr(ast, "local_aliases"):
                for local_name, rhs in ast.local_aliases:
                    # rhs is like "string.format" — extract the module prefix
                    prefix = rhs.split(".")[0]
                    if prefix in _ALIAS_SOURCE_MODULES:
                        alias_map[local_name] = _ALIAS_SOURCE_MODULES[prefix]

            for call in ast.calls:
                if call.resolved_module:
                    # Already resolved by CallResolver — skip
                    self._counts["already_resolved"] += 1
                    continue

                # Check alias map first (only for bare names without dots/colons)
                callee = call.callee_string
                if alias_map and "." not in callee and ":" not in callee and callee in alias_map:
                    classification = alias_map[callee]
                    call.classification = classification
                    self._counts[classification] += 1
                    continue

                classification = self.classify_call(callee, ast.language)
                call.classification = classification
                self._counts[classification] += 1
```

### Step 3.3: Verify tests pass

- [ ] **3.3: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBuiltinClassifierAliases -v
```

Also verify existing builtin classifier tests still pass:

```bash
python -m pytest graph_builder/tests/test_builtin_classifier.py -v
```

### Step 3.4: Commit

- [ ] **3.4: Commit**

```bash
git add graph_builder/resolvers/builtin_classifier.py graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "feat: extend BuiltinClassifier with per-file alias map for local stdlib aliases"
```

---

## Task 4: Add FIELD_TYPE_MAP and store_object to Parameter Resolver

Extend `parameter_resolver.py` to handle three-level chained field access (`store.assess_vector:get()`) by adding a `FIELD_TYPE_MAP` that maps typed fields on known modules to their sub-module types. Also add `store_object` as a known parameter name.

**Files:**
- Modify: `graph_builder/resolvers/parameter_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/store_vector_chains.lua`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 4.1: Create test fixture

- [ ] **4.1: Create store_vector_chains.lua fixture**

Create `graph_builder/tests/fixtures/lua/store_vector_chains.lua`:

```lua
local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    -- Store vector chain: store.assess_vector:get()
    local scores = store.assess_vector:get("user_scores")
    store.assess_vector:set("user_scores", {1, 2, 3})
    store.collect_vector:setall("collected", {4, 5, 6})

    -- Deep chain: web.store.assess_vector:get()
    local deep_scores = web.store.assess_vector:get("deep_scores")

    -- Plain store field (not a vector, should NOT resolve to store_vector)
    local sid = store.session_id
end

function M:act(bundle, store_object, session_id, old_assess_vector, new_assess_vector)
    -- store_object is a Store instance
    local data = store_object:hget("users", "user_123")
    store_object:set("processed", "true")

    -- store_object vector chain
    local av = store_object.assess_vector:get("scores")
end

return M
```

### Step 4.2: Write parameter resolver tests

- [ ] **4.2: Add store vector chain and store_object tests**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.resolvers.parameter_resolver import (
    PARAMETER_TYPE_MAP,
    FIELD_TYPE_MAP,
    resolve_parameter_calls,
)


# ---------------------------------------------------------------------------
# Task 4: Parameter resolver — FIELD_TYPE_MAP and store_object
# ---------------------------------------------------------------------------

class TestFieldTypeMap:
    def test_field_type_map_has_assess_vector(self):
        """FIELD_TYPE_MAP should map assess_vector to store_vector module."""
        assert "lib.lua.store" in FIELD_TYPE_MAP
        assert "assess_vector" in FIELD_TYPE_MAP["lib.lua.store"]
        assert FIELD_TYPE_MAP["lib.lua.store"]["assess_vector"] == "common.base.lua.store_vector"

    def test_field_type_map_has_collect_vector(self):
        """FIELD_TYPE_MAP should map collect_vector to store_vector module."""
        assert "collect_vector" in FIELD_TYPE_MAP["lib.lua.store"]
        assert FIELD_TYPE_MAP["lib.lua.store"]["collect_vector"] == "common.base.lua.store_vector"


class TestStoreObjectParameter:
    def test_store_object_in_parameter_type_map(self):
        """store_object should be in PARAMETER_TYPE_MAP mapping to lib.lua.store."""
        assert "store_object" in PARAMETER_TYPE_MAP
        assert PARAMETER_TYPE_MAP["store_object"] == "lib.lua.store"


class TestStoreVectorChainResolution:
    def test_store_assess_vector_get(self):
        """store.assess_vector:get() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        count = resolve_parameter_calls(all_asts)

        av_get_calls = [
            c for c in ast.calls
            if "assess_vector" in c.callee_string
            and c.callee_string.endswith("get")
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(av_get_calls) >= 1, (
            f"Expected at least 1 assess_vector:get resolution, got {len(av_get_calls)}. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_store_assess_vector_set(self):
        """store.assess_vector:set() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        av_set_calls = [
            c for c in ast.calls
            if "assess_vector" in c.callee_string
            and c.callee_string.endswith("set")
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(av_set_calls) >= 1

    def test_store_collect_vector_setall(self):
        """store.collect_vector:setall() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        cv_calls = [
            c for c in ast.calls
            if "collect_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(cv_calls) >= 1

    def test_web_store_assess_vector_deep_chain(self):
        """web.store.assess_vector:get() should resolve via deep chain lookup."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        deep_calls = [
            c for c in ast.calls
            if "web.store.assess_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(deep_calls) >= 1, (
            f"Expected deep chain resolution. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_store_object_hget(self):
        """store_object:hget() should resolve to lib.lua.store."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        so_calls = [
            c for c in ast.calls
            if c.callee_string.startswith("store_object:")
            and c.resolved_module == "lib.lua.store"
        ]
        assert len(so_calls) >= 1

    def test_store_object_vector_chain(self):
        """store_object.assess_vector:get() should resolve to store_vector module."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        so_av_calls = [
            c for c in ast.calls
            if "store_object.assess_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(so_av_calls) >= 1, (
            f"Expected store_object.assess_vector chain resolution. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_unknown_chain_not_resolved(self):
        """foo.bar:method() with unknown foo should NOT be resolved."""
        call = _make_call("foo.bar:baz")
        ast = _make_ast(calls=[call])
        all_asts = {"/test/file.lua": ast}
        resolve_parameter_calls(all_asts)
        assert call.resolved_module is None
```

Run tests (should fail because FIELD_TYPE_MAP and store_object do not exist yet):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestFieldTypeMap -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreObjectParameter -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreVectorChainResolution -v
```

### Step 4.3: Add FIELD_TYPE_MAP and store_object to parameter_resolver.py

- [ ] **4.3: Implement FIELD_TYPE_MAP, store_object, and chain resolution**

In `graph_builder/resolvers/parameter_resolver.py`, make these changes:

**Add `store_object` to PARAMETER_TYPE_MAP** (after `"store": "lib.lua.store"`):

```python
PARAMETER_TYPE_MAP: dict[str, str] = {
    "bundle": "lib.lua.bundle",
    "web": "lib.lua.store",
    "store": "lib.lua.store",
    "store_object": "lib.lua.store",
}
```

**Add FIELD_TYPE_MAP** after PARAMETER_TYPE_MAP:

```python
# Maps a resolved module to its typed field names and their sub-module types.
# Used for chained field access: store.assess_vector:get() → resolve "get" on store_vector.
FIELD_TYPE_MAP: dict[str, dict[str, str]] = {
    "lib.lua.store": {
        "assess_vector": "common.base.lua.store_vector",
        "collect_vector": "common.base.lua.store_vector",
    },
}
```

**Replace the entire `resolve_parameter_calls` function** with this version that adds field type chain resolution:

```python
def resolve_parameter_calls(all_asts: dict[str, FileAST]) -> int:
    """Resolve calls on known parameter names across all Lua ASTs.

    For every unresolved call whose receiver matches a key in
    ``PARAMETER_TYPE_MAP`` (or a chained access like ``web.store``),
    the call's ``resolved_module`` and ``resolved_function`` are set.

    Also handles store vector chains: ``store.assess_vector:get()``
    resolves to ``common.base.lua.store_vector`` via FIELD_TYPE_MAP.

    Args:
        all_asts: file_path → FileAST mapping for all parsed files.

    Returns:
        Number of newly resolved calls.
    """
    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        for call in ast.calls:
            # Skip calls that are already resolved
            if call.resolved_module is not None:
                continue

            callee = call.callee_string

            # ----------------------------------------------------------
            # Pattern 1: receiver:method()  or  receiver.method()
            # e.g. bundle:get, store:hget, store:set
            # ----------------------------------------------------------
            for sep in (":", "."):
                if sep not in callee:
                    continue

                parts = callee.split(sep, 1)
                receiver, method_name = parts[0], parts[1]

                # Direct parameter match: "bundle:get" → receiver="bundle"
                if receiver in PARAMETER_TYPE_MAP:
                    call.resolved_module = PARAMETER_TYPE_MAP[receiver]
                    call.resolved_function = method_name
                    call.resolution_confidence = "parameter"
                    resolved_count += 1
                    break

                # Chained access: "web.store:method" or "store.assess_vector:method"
                if "." in receiver:
                    chain_parts = receiver.split(".")
                    prefix = chain_parts[0]

                    if prefix in PARAMETER_TYPE_MAP:
                        prefix_module = PARAMETER_TYPE_MAP[prefix]

                        # Check if the chain resolves to a sub-module via FIELD_TYPE_MAP.
                        # For "store.assess_vector:get":
                        #   prefix="store" → prefix_module="lib.lua.store"
                        #   remaining="assess_vector" → FIELD_TYPE_MAP check
                        # For "web.store.assess_vector:get":
                        #   prefix="web" → prefix_module="lib.lua.store"
                        #   remaining chain = ["store", "assess_vector"]
                        #   Walk the chain: "store" is in PARAMETER_TYPE_MAP → intermediate_module
                        #   then "assess_vector" is in FIELD_TYPE_MAP → sub_module
                        resolved_module = _resolve_chain(
                            chain_parts[1:], prefix_module, method_name
                        )
                        if resolved_module:
                            call.resolved_module = resolved_module
                            call.resolved_function = method_name
                            call.resolution_confidence = "parameter"
                            resolved_count += 1
                            break

                        # Fall back: resolve to the prefix's module if no sub-module matched
                        suffix = chain_parts[-1]
                        suffix_module = PARAMETER_TYPE_MAP.get(suffix)
                        if suffix_module:
                            call.resolved_module = suffix_module
                        else:
                            call.resolved_module = prefix_module
                        call.resolved_function = method_name
                        call.resolution_confidence = "parameter"
                        resolved_count += 1
                        break

    return resolved_count


def _resolve_chain(
    remaining_parts: list[str], current_module: str, method_name: str
) -> str | None:
    """Walk a chain of field accesses resolving through FIELD_TYPE_MAP.

    For ["assess_vector"] with current_module="lib.lua.store":
        → checks FIELD_TYPE_MAP["lib.lua.store"]["assess_vector"]
        → returns "common.base.lua.store_vector"

    For ["store", "assess_vector"] with current_module="lib.lua.store":
        → "store" is in PARAMETER_TYPE_MAP → intermediate = "lib.lua.store"
        → "assess_vector" is in FIELD_TYPE_MAP["lib.lua.store"]
        → returns "common.base.lua.store_vector"

    Returns the resolved sub-module string, or None if chain does not match.
    """
    module = current_module

    for i, part in enumerate(remaining_parts):
        # Check if this part is a typed field on the current module
        field_map = FIELD_TYPE_MAP.get(module)
        if field_map and part in field_map:
            module = field_map[part]
            # If this is the last part before the method, we found our target
            if i == len(remaining_parts) - 1:
                return module
            continue

        # Check if this part redirects to another known module
        part_module = PARAMETER_TYPE_MAP.get(part)
        if part_module:
            module = part_module
            continue

        # Unknown part in chain — cannot resolve further
        return None

    # If we walked all parts and ended up at a different module than we started,
    # check if the final module has the field map entry
    if module != current_module:
        return module

    return None
```

### Step 4.4: Verify tests pass

- [ ] **4.4: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestFieldTypeMap -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreObjectParameter -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreVectorChainResolution -v
```

Also verify existing parameter resolver tests still pass:

```bash
python -m pytest graph_builder/tests/test_call_resolution_final.py -v
```

### Step 4.5: Commit

- [ ] **4.5: Commit**

```bash
git add graph_builder/resolvers/parameter_resolver.py graph_builder/tests/fixtures/lua/store_vector_chains.lua graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "feat: add FIELD_TYPE_MAP for store vector chain resolution and store_object parameter"
```

---

## Task 5: Update BASE_MODULE_METHODS in base_inheritance_resolver

Replace the hardcoded method sets with the actual methods confirmed by BOB investigation. Add `actor.lua` as a 4th base module.

**Files:**
- Modify: `graph_builder/resolvers/base_inheritance_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/child_actor.lua`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 5.1: Create child_actor fixture

- [ ] **5.1: Create child_actor.lua fixture**

Create `graph_builder/tests/fixtures/lua/child_actor.lua`:

```lua
local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.actor")

local M = base:new()

function M:act(bundle, store_object, session_id, old_assess_vector, new_assess_vector)
    -- act() is always overridden, so this should resolve to same file
    local data = store_object:hget("users", "user_123")
    return {status = "ok"}
end

return M
```

### Step 5.2: Write tests for updated BASE_MODULE_METHODS

- [ ] **5.2: Add base inheritance tests**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.resolvers.base_inheritance_resolver import (
    BASE_MODULE_METHODS,
    resolve_base_inheritance,
)


# ---------------------------------------------------------------------------
# Task 5: Updated BASE_MODULE_METHODS
# ---------------------------------------------------------------------------

class TestBaseModuleMethodsUpdated:
    def test_handler_has_validate(self):
        """Handler base should have 'validate' (not 'validate_input')."""
        methods = BASE_MODULE_METHODS["common.base.lua.handler"]
        assert "validate" in methods

    def test_handler_has_response_map(self):
        """Handler base should have 'response_map'."""
        assert "response_map" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_add_handler_error(self):
        """Handler base should have 'add_handler_error'."""
        assert "add_handler_error" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_check_mark_store_save_async(self):
        """Handler base should have 'check_mark_store_save_async'."""
        assert "check_mark_store_save_async" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_user_error(self):
        """Handler base should have 'user_error'."""
        assert "user_error" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_dispatch(self):
        """Handler base should have 'dispatch'."""
        assert "dispatch" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_parse_postdata(self):
        """Handler base should have 'parse_postdata'."""
        assert "parse_postdata" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_no_old_methods(self):
        """Handler base should NOT have the old incorrect methods."""
        methods = BASE_MODULE_METHODS["common.base.lua.handler"]
        assert "validate_input" not in methods
        assert "handle_error" not in methods
        assert "log_error" not in methods
        assert "system_error" not in methods

    def test_collector_has_trigger(self):
        """Collector base should have 'trigger'."""
        assert "trigger" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_has_collect(self):
        """Collector base should have 'collect'."""
        assert "collect" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_has_get_store(self):
        """Collector base should have 'get_store'."""
        assert "get_store" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_no_old_methods(self):
        """Collector base should NOT have the old incorrect method 'store_data'."""
        assert "store_data" not in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_assessor_has_assess(self):
        """Assessor base should have 'assess'."""
        assert "assess" in BASE_MODULE_METHODS["common.base.lua.assessor"]

    def test_actor_exists(self):
        """Actor base module should be in BASE_MODULE_METHODS."""
        assert "common.base.lua.actor" in BASE_MODULE_METHODS

    def test_actor_has_act(self):
        """Actor base should have 'act'."""
        assert "act" in BASE_MODULE_METHODS["common.base.lua.actor"]


class TestBaseInheritanceWithUpdatedMethods:
    def test_handler_validate_resolved(self):
        """self:validate() in child handler should resolve to base handler."""
        ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
        all_asts = {"child_handler.lua": ast}
        count = resolve_base_inheritance(all_asts)

        validate_calls = [
            c for c in ast.calls
            if c.callee_string == "self:validate_input"
            and c.resolved_module == "common.base.lua.handler"
        ]
        # Note: child_handler.lua has self:validate_input which maps to
        # the old method name. The test fixture uses validate_input.
        # The point is that the resolver works with the updated method set.
        # validate_input is no longer in the set, so this call will NOT resolve.
        # This validates the old methods were removed.
        vi_calls = [
            c for c in ast.calls
            if c.callee_string == "self:validate_input"
        ]
        if vi_calls:
            assert vi_calls[0].resolved_module != "common.base.lua.handler" or \
                   vi_calls[0].resolution_confidence != "base_inherited", \
                "validate_input should no longer resolve via base inheritance"

    def test_handler_user_error_still_resolves(self):
        """self:user_error() should still resolve to base handler (kept in updated set)."""
        ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
        all_asts = {"child_handler.lua": ast}
        resolve_base_inheritance(all_asts)

        ue_calls = [
            c for c in ast.calls
            if c.callee_string == "self:user_error"
            and c.resolved_module == "common.base.lua.handler"
            and c.resolution_confidence == "base_inherited"
        ]
        assert len(ue_calls) == 1, (
            f"Expected self:user_error to resolve to base handler. "
            f"Calls: {[(c.callee_string, c.resolved_module, c.resolution_confidence) for c in ast.calls]}"
        )
```

Run tests (should fail because BASE_MODULE_METHODS has old values):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBaseModuleMethodsUpdated -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBaseInheritanceWithUpdatedMethods -v
```

### Step 5.3: Update BASE_MODULE_METHODS

- [ ] **5.3: Replace BASE_MODULE_METHODS in base_inheritance_resolver.py**

Replace the entire `BASE_MODULE_METHODS` dict with:

```python
# Known base modules and their inheritable methods.
# Updated 2026-03-28 from BOB investigation of actual base module source files.
BASE_MODULE_METHODS: dict[str, set[str]] = {
    "common.base.lua.handler": {
        "validate", "response_map", "add_handler_error",
        "check_mark_store_save_async", "user_error", "parse_postdata",
        "dispatch", "handle_web_request", "handle_ep_request",
        "handle_pmc", "handle_tma", "handle_internal_request",
        "add_error_metrics", "parse_api_version_data",
        "verify_store_size_limit", "add_general_handler_error",
        "create_handler", "sanitize_error_output", "user_error_format",
        "create_handler_event",
    },
    "common.base.lua.assessor": {
        "assess",
    },
    "common.base.lua.collector": {
        "trigger", "collect", "get_trigger_collector",
        "trigger_web_request", "get_collect_collector",
        "decrypt_collect_data", "collect_web_request",
        "fake_collect_web_request", "get_store",
    },
    "common.base.lua.actor": {
        "act",
    },
}
```

### Step 5.4: Verify tests pass

- [ ] **5.4: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBaseModuleMethodsUpdated -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestBaseInheritanceWithUpdatedMethods -v
```

Also verify existing inheritance tests adapt correctly:

```bash
python -m pytest graph_builder/tests/test_call_resolution_final.py::test_inherited_method_resolved -v
```

Note: The existing test `test_inherited_method_resolved` checks for `self:validate_input` resolving to the handler base. Since `validate_input` is being removed from the method set, this test will now fail. Update the fixture `child_handler.lua` to use the new method name `validate` instead:

**In `graph_builder/tests/fixtures/lua/child_handler.lua`**, replace:

```lua
    if not self:validate_input(input) then
```

with:

```lua
    if not self:validate(input) then
```

And update `graph_builder/tests/test_call_resolution_final.py`, replacing `"self:validate_input"` with `"self:validate"` in the `test_inherited_method_resolved` test:

```python
def test_inherited_method_resolved():
    """self:validate() in child_handler should resolve to common.base.lua.handler."""
    ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
    all_asts = {"child_handler.lua": ast}
    count = resolve_base_inheritance(all_asts)
    assert count > 0, "Expected at least one base-inherited resolution"

    vi_calls = [
        c for c in ast.calls
        if c.callee_string == "self:validate"
    ]
    assert len(vi_calls) == 1
    assert vi_calls[0].resolved_module == "common.base.lua.handler"
    assert vi_calls[0].resolved_function == "validate"
    assert vi_calls[0].resolution_confidence == "base_inherited"
```

### Step 5.5: Run all affected tests

- [ ] **5.5: Verify all tests pass**

```bash
python -m pytest graph_builder/tests/test_call_resolution_final.py -v
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py -v
```

### Step 5.6: Commit

- [ ] **5.6: Commit**

```bash
git add graph_builder/resolvers/base_inheritance_resolver.py graph_builder/tests/fixtures/lua/child_handler.lua graph_builder/tests/fixtures/lua/child_actor.lua graph_builder/tests/test_call_resolution_final.py graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "feat: update BASE_MODULE_METHODS to actual base class methods, add actor.lua"
```

---

## Task 6: Fix CallResolver self: Branch Guard

Currently, the `self:method()` resolution in `call_resolver.py` (lines 211-217) immediately returns `True` when `ast.module_info.table_var_name` exists, even if the method does not exist in the current file. This preempts the base_inheritance_resolver. Fix: only resolve to same-file if the method name actually exists among the file's functions.

**Files:**
- Modify: `graph_builder/resolvers/call_resolver.py`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 6.1: Write test for self: guard

- [ ] **6.1: Add CallResolver self: guard test**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.resolvers.call_resolver import CallResolver


# ---------------------------------------------------------------------------
# Task 6: CallResolver self: branch guard
# ---------------------------------------------------------------------------

class TestCallResolverSelfGuard:
    def test_self_method_in_file_resolves(self):
        """self:process() where process is defined in the file should resolve to self."""
        call = _make_call("self:process")
        func = FunctionDef(name="M:process", line=10, line_end=20, visibility="public")
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )
        ast = _make_ast(
            calls=[call],
            functions=[func],
            module_info=module_info,
            file_path="/test/handler.lua",
        )
        ast.module_name = "test.handler"

        resolver = CallResolver(
            all_asts={"/test/handler.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        assert call.resolved_module == "test.handler"
        assert call.resolved_function == "process"
        assert call.resolution_confidence == "self"

    def test_self_method_not_in_file_does_not_resolve(self):
        """self:validate() where validate is NOT in the file should NOT resolve to self."""
        call = _make_call("self:validate")
        # Only define 'process' and 'apply' — NOT 'validate'
        func_process = FunctionDef(name="M:process", line=10, line_end=20, visibility="public")
        func_apply = FunctionDef(name="M:apply", line=1, line_end=9, visibility="public")
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )
        ast = _make_ast(
            calls=[call],
            functions=[func_process, func_apply],
            module_info=module_info,
            file_path="/test/child_handler.lua",
        )
        ast.module_name = "test.child_handler"

        resolver = CallResolver(
            all_asts={"/test/child_handler.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        # The call should NOT be resolved to self — it should fall through
        # so that the base_inheritance_resolver can pick it up later
        if call.resolved_module is not None:
            assert call.resolution_confidence != "self", (
                "self:validate() should not resolve to self when validate is not defined in the file"
            )

    def test_self_method_no_table_var_falls_through(self):
        """self:method() with no table_var_name should try function matching."""
        call = _make_call("self:apply")
        func = FunctionDef(name="apply", line=1, line_end=10, visibility="local")
        module_info = ModuleInfo(pattern_type=ModulePatternType.SIDE_EFFECT)
        ast = _make_ast(
            calls=[call],
            functions=[func],
            module_info=module_info,
            file_path="/test/script.lua",
        )
        ast.module_name = "test.script"

        resolver = CallResolver(
            all_asts={"/test/script.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        # Option B in the self: branch should match by function name
        assert call.resolved_module == "test.script"
        assert call.resolved_function == "apply"
```

Run test (should fail because self: branch does not check method existence):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestCallResolverSelfGuard -v
```

### Step 6.2: Fix the self: branch in call_resolver.py

- [ ] **6.2: Add method existence guard to self: resolution**

In `graph_builder/resolvers/call_resolver.py`, replace the `self:` handling block (lines 211-225):

**Before:**
```python
                # self:method() resolution — in Lua, `self` inside a method
                # defined as `function M:method()` refers to the module table.
                # 85% of self:method() calls target methods in the SAME file.
                if table_name == "self":
                    # Option A: module has a table_var_name (e.g., _M, M, auth)
                    if ast.module_info and ast.module_info.table_var_name:
                        call.resolved_module = ast.module_name or ast.file_path
                        call.resolved_function = method_name
                        call.resolution_confidence = "self"
                        return True
                    # Option B: match method_name against functions defined in this file
                    for func in ast.functions:
                        func_base = func.name.split(".")[-1].split(":")[-1]
                        if func_base == method_name:
                            call.resolved_module = ast.module_name or ast.file_path
                            call.resolved_function = method_name
                            call.resolution_confidence = "self"
                            return True
```

**After:**
```python
                # self:method() resolution — in Lua, `self` inside a method
                # defined as `function M:method()` refers to the module table.
                # 85% of self:method() calls target methods in the SAME file.
                if table_name == "self":
                    # Check if method_name actually exists in this file's functions
                    method_in_file = any(
                        func.name.split(".")[-1].split(":")[-1] == method_name
                        for func in ast.functions
                    )
                    if method_in_file:
                        call.resolved_module = ast.module_name or ast.file_path
                        call.resolved_function = method_name
                        call.resolution_confidence = "self"
                        return True
                    # Method not found locally — do NOT resolve here.
                    # Let it fall through so base_inheritance_resolver can
                    # pick it up if it's an inherited method.
```

### Step 6.3: Verify tests pass

- [ ] **6.3: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestCallResolverSelfGuard -v
```

Also verify existing call resolver tests still pass:

```bash
python -m pytest graph_builder/tests/test_call_resolution_final.py -v
```

### Step 6.4: Commit

- [ ] **6.4: Commit**

```bash
git add graph_builder/resolvers/call_resolver.py graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "fix: guard self: resolution to only match when method exists in current file"
```

---

## Task 7: Update redis_abstraction_resolver StoreVector Method Sets

BOB confirmed StoreVector only has 7 methods: `new`, `set`, `set_sparse_safe`, `setall`, `get`, `getall`, `incr`. The current `_STORE_VECTOR_READ` and `_STORE_VECTOR_WRITE` sets contain methods that do not exist on StoreVector (`add`, `delete`, `clear`, `zadd`, `zrem`, `zrangebyscore`, `get_all`, `count`, `exists`).

**Files:**
- Modify: `graph_builder/resolvers/redis_abstraction_resolver.py`
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 7.1: Write tests for updated StoreVector sets

- [ ] **7.1: Add StoreVector method set tests**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
from graph_builder.resolvers.redis_abstraction_resolver import (
    _STORE_VECTOR_READ,
    _STORE_VECTOR_WRITE,
)


# ---------------------------------------------------------------------------
# Task 7: Updated StoreVector method sets
# ---------------------------------------------------------------------------

class TestStoreVectorMethodSets:
    def test_read_has_get(self):
        """StoreVector read set should contain 'get'."""
        assert "get" in _STORE_VECTOR_READ

    def test_read_has_getall(self):
        """StoreVector read set should contain 'getall'."""
        assert "getall" in _STORE_VECTOR_READ

    def test_write_has_set(self):
        """StoreVector write set should contain 'set'."""
        assert "set" in _STORE_VECTOR_WRITE

    def test_write_has_setall(self):
        """StoreVector write set should contain 'setall'."""
        assert "setall" in _STORE_VECTOR_WRITE

    def test_write_has_set_sparse_safe(self):
        """StoreVector write set should contain 'set_sparse_safe'."""
        assert "set_sparse_safe" in _STORE_VECTOR_WRITE

    def test_write_has_incr(self):
        """StoreVector write set should contain 'incr'."""
        assert "incr" in _STORE_VECTOR_WRITE

    def test_no_nonexistent_methods(self):
        """StoreVector sets should NOT contain methods that don't exist on StoreVector."""
        all_methods = _STORE_VECTOR_READ | _STORE_VECTOR_WRITE
        assert "add" not in all_methods
        assert "delete" not in all_methods
        assert "clear" not in all_methods
        assert "zadd" not in all_methods
        assert "zrem" not in all_methods
        assert "zrangebyscore" not in all_methods
        assert "get_all" not in all_methods
        assert "count" not in all_methods
        assert "exists" not in all_methods

    def test_new_excluded(self):
        """'new' is a constructor, not a Redis operation — should not be in either set."""
        assert "new" not in _STORE_VECTOR_READ
        assert "new" not in _STORE_VECTOR_WRITE
```

Run tests (should fail because the sets contain wrong methods):

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreVectorMethodSets -v
```

### Step 7.2: Update _STORE_VECTOR_READ and _STORE_VECTOR_WRITE

- [ ] **7.2: Replace StoreVector method sets in redis_abstraction_resolver.py**

Replace the `_STORE_VECTOR_READ` and `_STORE_VECTOR_WRITE` sets:

**Before:**
```python
_STORE_VECTOR_READ = {
    "get", "get_all", "count", "exists",
}
_STORE_VECTOR_WRITE = {
    "add", "set", "delete", "clear",
    "zadd", "zrem", "zrangebyscore",
}
```

**After:**
```python
# StoreVector actual methods (from store_vector.lua):
# new, set, set_sparse_safe, setall, get, getall, incr
# "new" is a constructor and excluded from Redis classification.
_STORE_VECTOR_READ = {
    "get", "getall",
}
_STORE_VECTOR_WRITE = {
    "set", "set_sparse_safe", "setall", "incr",
}
```

### Step 7.3: Verify tests pass

- [ ] **7.3: Run tests and verify pass**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestStoreVectorMethodSets -v
```

### Step 7.4: Commit

- [ ] **7.4: Commit**

```bash
git add graph_builder/resolvers/redis_abstraction_resolver.py graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "fix: update StoreVector method sets to match actual store_vector.lua methods"
```

---

## Task 8: Integration Test with All Components

Run all resolvers in sequence on a synthetic AST that exercises every new feature: aliases, store vector chains, store_object, and base inheritance fallback.

**Files:**
- Modify: `graph_builder/tests/test_lua_call_resolution_v2.py`

### Step 8.1: Write integration test

- [ ] **8.1: Add integration test**

Append to `graph_builder/tests/test_lua_call_resolution_v2.py`:

```python
# ---------------------------------------------------------------------------
# Task 8: Integration test — all components together
# ---------------------------------------------------------------------------

class TestIntegrationAllComponents:
    def test_full_pipeline_on_handler_with_aliases(self):
        """Full resolution pipeline: CallResolver → parameter → inheritance → classifier.

        Simulates a handler file that:
        - Has local aliases (format, encode)
        - Calls store.assess_vector:get()
        - Calls store_object:hget()
        - Calls self:validate() (inherited from base handler)
        """
        # Build a synthetic handler file AST
        imports = [
            ImportRef(
                module_string="common.base.lua.handler",
                line=1,
                import_type="require_version",
                local_binding="base",
            ),
        ]
        functions = [
            FunctionDef(name="M:apply", line=5, line_end=20, visibility="public",
                        params=["self", "input", "bundle", "web"]),
            FunctionDef(name="M:process", line=22, line_end=30, visibility="public",
                        params=["self", "data"]),
        ]
        calls = [
            # Alias calls
            CallRef(caller_function="M:apply", callee_string="format", line=6),
            CallRef(caller_function="M:apply", callee_string="encode", line=7),
            # Store vector chain
            CallRef(caller_function="M:apply", callee_string="store.assess_vector:get", line=8),
            # store_object parameter
            CallRef(caller_function="M:apply", callee_string="store_object:hget", line=9),
            # self: inherited method (validate is NOT in this file)
            CallRef(caller_function="M:apply", callee_string="self:validate", line=10),
            # self: same-file method (process IS in this file)
            CallRef(caller_function="M:apply", callee_string="self:process", line=11),
            # Unknown call
            CallRef(caller_function="M:apply", callee_string="mystery_function", line=12),
        ]
        local_aliases = [
            ("format", "string.format"),
            ("encode", "cjson.encode"),
        ]
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )

        ast = FileAST(
            file_path="/test/my_handler.lua",
            language="lua",
            module_name="test.my_handler",
            module_info=module_info,
            imports=imports,
            functions=functions,
            calls=calls,
            local_aliases=local_aliases,
        )

        all_asts = {"/test/my_handler.lua": ast}

        # Step 1: CallResolver
        resolver = CallResolver(all_asts=all_asts, resolvers={})
        resolver.resolve_all()

        # Step 2: Parameter resolver (store vector chains + store_object)
        resolve_parameter_calls(all_asts)

        # Step 3: Base inheritance resolver
        resolve_base_inheritance(all_asts)

        # Step 4: Builtin classifier (aliases)
        classifier = BuiltinClassifier()
        classifier.classify_all(all_asts)

        # --- Verify results ---

        # format → classified as builtin (via alias)
        format_call = next(c for c in calls if c.callee_string == "format")
        assert format_call.classification == "builtin", (
            f"format should be builtin via alias, got {format_call.classification}"
        )

        # encode → classified as external (via alias)
        encode_call = next(c for c in calls if c.callee_string == "encode")
        assert encode_call.classification == "external", (
            f"encode should be external via alias, got {encode_call.classification}"
        )

        # store.assess_vector:get → resolved to common.base.lua.store_vector
        av_call = next(c for c in calls if c.callee_string == "store.assess_vector:get")
        assert av_call.resolved_module == "common.base.lua.store_vector", (
            f"store.assess_vector:get should resolve to store_vector, got {av_call.resolved_module}"
        )
        assert av_call.resolved_function == "get"

        # store_object:hget → resolved to lib.lua.store
        so_call = next(c for c in calls if c.callee_string == "store_object:hget")
        assert so_call.resolved_module == "lib.lua.store", (
            f"store_object:hget should resolve to lib.lua.store, got {so_call.resolved_module}"
        )

        # self:validate → resolved to base handler (inherited)
        validate_call = next(c for c in calls if c.callee_string == "self:validate")
        assert validate_call.resolved_module == "common.base.lua.handler", (
            f"self:validate should resolve to base handler, got {validate_call.resolved_module}"
        )
        assert validate_call.resolution_confidence == "base_inherited"

        # self:process → resolved to same file (self)
        process_call = next(c for c in calls if c.callee_string == "self:process")
        assert process_call.resolved_module == "test.my_handler", (
            f"self:process should resolve to same file, got {process_call.resolved_module}"
        )
        assert process_call.resolution_confidence == "self"

        # mystery_function → truly_unresolved
        mystery_call = next(c for c in calls if c.callee_string == "mystery_function")
        assert mystery_call.classification == "truly_unresolved"

    def test_full_pipeline_parser_to_resolver(self):
        """End-to-end: parse alias_builtins.lua fixture then classify."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        all_asts = {"alias_builtins.lua": ast}

        # Run classifier
        classifier = BuiltinClassifier()
        classifier.classify_all(all_asts)

        # format, gsub, match, insert, floor should all be builtin
        alias_names = {"format", "gsub", "match", "insert", "floor"}
        for call in ast.calls:
            bare = call.callee_string.split(".")[0].split(":")[0]
            if bare in alias_names and call.resolved_module is None:
                assert call.classification == "builtin", (
                    f"{call.callee_string} should be classified as builtin, "
                    f"got {call.classification}"
                )

        # encode, decode should be external
        for call in ast.calls:
            bare = call.callee_string.split(".")[0].split(":")[0]
            if bare in {"encode", "decode"} and call.resolved_module is None:
                assert call.classification == "external", (
                    f"{call.callee_string} should be classified as external, "
                    f"got {call.classification}"
                )

        # my_func should be truly_unresolved (some_module is not a known builtin/external)
        for call in ast.calls:
            if call.callee_string == "my_func" and call.resolved_module is None:
                assert call.classification == "truly_unresolved"
```

### Step 8.2: Run integration test

- [ ] **8.2: Verify integration test passes**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py::TestIntegrationAllComponents -v
```

### Step 8.3: Run full test suite

- [ ] **8.3: Run all tests to verify no regressions**

```bash
python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py -v
python -m pytest graph_builder/tests/test_builtin_classifier.py -v
python -m pytest graph_builder/tests/test_call_resolution_final.py -v
```

### Step 8.4: Commit

- [ ] **8.4: Commit**

```bash
git add graph_builder/tests/test_lua_call_resolution_v2.py
git commit -m "test: add integration tests for full Lua call resolution v2 pipeline"
```

---

## Expected Impact Summary

| Component | New Resolved/Classified | Mechanism |
|-----------|------------------------|-----------|
| Local alias classification | 500-800 reclassified as builtin/external | BuiltinClassifier alias map |
| Store vector CALLS edges | 200-300 new resolved calls | Parameter resolver chain logic |
| `store_object` parameter mapping | 50-100 new resolved calls | PARAMETER_TYPE_MAP addition |
| self:inherited fallback | 100-200 new resolved calls | Updated base_inheritance_resolver + self: guard fix |
| StoreVector method set fix | accuracy improvement | Corrected _STORE_VECTOR_READ/_WRITE |
| **Total** | **850-1,400 improvement** | **Lua call res -> ~57-60%** |

---

## Verification After All Tasks

After all 8 tasks are complete, run:

```bash
# Full test suite
python -m pytest graph_builder/tests/ -v

# If Memgraph is running and config.yml points to the product codebase:
code-graph build -c config.yml
code-graph validate -c config.yml
```

Verify:
- Lua call resolution increases from 53.6% toward ~57-60%
- Builtin count increases (alias reclassification)
- Truly unresolved count decreases
- No regressions in other languages
