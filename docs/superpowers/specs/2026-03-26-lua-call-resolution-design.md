# Lua Call Resolution Improvements — Design Spec

**Date:** 2026-03-26
**Goal:** Push Lua call resolution from 53.6% (15,485/28,899) toward ~60% by resolving three categories of currently-unresolved calls.

**Context:** After 5 rounds of BOB investigation, we know the remaining ~5,100-6,400 truly unresolved Lua calls break into identifiable categories. Three are tractable with static analysis.

---

## 1. Local Alias Builtin Classification

### Problem

The #1 source of unresolved Lua calls is local aliases of stdlib/builtin functions. The codebase pervasively uses this pattern:

```lua
local format, gsub, match = string.format, string.gsub, string.match
local encode, decode = cjson.encode, cjson.decode
local insert, remove, concat = table.insert, table.remove, table.concat
```

After aliasing, calls like `format("hello %s", name)` appear as bare unresolved calls because:
- The `BuiltinClassifier` only recognizes dotted forms (`string.format`) not bare aliases
- The `CallResolver` binding map only tracks `require()` bindings, not stdlib field assignments

BOB's top 20 unresolved callees are almost entirely these aliases: `encode` (~500), `decode` (~500), `format` (~1000), `insert` (~200), `match` (~300), `gsub` (~200), `sub` (~150), `len` (~100), `find` (~100), `lower` (~80), etc.

### Solution

Extend `BuiltinClassifier` to build a per-file **alias map** from local assignment nodes in the AST.

**Data source:** The Lua parser does NOT currently store local variable assignments on `FileAST`. We need to add a new field `local_aliases: list[tuple[str, str]]` to `FileAST` (in `base.py`) that stores `(local_name, rhs_expression)` pairs for local assignments where the RHS is a dotted field access. The Lua parser will populate this by walking `local_statement` / `assignment_statement` nodes where the RHS is a `field_expression` (e.g., `string.format`). This field is only needed for alias detection — it does not affect other resolvers.

**Algorithm:**
1. For each Lua file's AST, scan for local variable declarations where the initializer is a field access on a known builtin module
2. Build a map: `{"format": "string.format", "encode": "cjson.encode", ...}`
3. When classifying unresolved calls, if a bare callee (no dots, no colon) matches an alias key, classify it as `"builtin"` (for stdlib aliases) or `"external"` (for cjson/resty aliases)

**Known builtin modules to track aliases from:**
- `string` (format, sub, gsub, match, find, len, lower, upper, rep, byte, char, reverse, dump)
- `table` (insert, remove, concat, sort, unpack, pack)
- `math` (floor, ceil, abs, max, min, random, randomseed, sqrt, log, exp, huge)
- `os` (time, clock, date, difftime)
- `io` (open, read, write, close)
- `cjson` (encode, decode, new)
- `cmsgpack` (pack, unpack)
- `ngx` submodules (already handled by prefix matching)

**Multi-assignment support:** Lua allows `local a, b, c = x.a, x.b, x.c`. The parser needs to handle positional matching of names to values.

**Implementation file:** `graph_builder/resolvers/builtin_classifier.py`

**Expected impact:** ~500-800 calls reclassified from "truly_unresolved" to "builtin"/"external". This doesn't increase the resolved call count but improves effective coverage and reduces noise in unresolved call analysis.

---

## 2. Store Vector Chain Resolution for CALLS Edges

### Problem

The Redis abstraction resolver correctly detects `store.assess_vector:get("key")` and creates Redis edges (1,125 accesses). But the call resolver does NOT create CALLS edges for these same patterns. The callee string `store.assess_vector.get` has 3 levels of dot-chain access, exceeding the parameter resolver's 2-level handling.

BOB confirmed Store's constructor creates exactly two StoreVector instances:
```lua
m.assess_vector = StoreVector.new(m, M.assess_prefix)
m.collect_vector = StoreVector.new(m, M.collect_prefix)
```

No `session_vector` or `user_vector` exists (contrary to earlier assumptions).

StoreVector (`src/common/base/lua/store_vector.lua`) exposes 7 methods: `new`, `set`, `set_sparse_safe`, `setall`, `get`, `getall`, `incr`.

### Solution

Extend `parameter_resolver.py` to handle chained field access on known typed parameters.

**New data structure — field type map:**
```python
FIELD_TYPE_MAP = {
    "lib.lua.store": {
        "assess_vector": "common.base.lua.store_vector",
        "collect_vector": "common.base.lua.store_vector",
    }
}
```

Note: `dirty_flags`, `cache`, `session_id`, `in_transaction`, `changed` are plain tables/primitives — not typed sub-objects, so they are excluded.

Also note: the existing `redis_abstraction_resolver.py` has `_STORE_VECTOR_READ` and `_STORE_VECTOR_WRITE` sets with methods like `add`, `delete`, `zadd` etc. that do NOT exist on the actual StoreVector module (BOB confirmed only: `new`, `set`, `set_sparse_safe`, `setall`, `get`, `getall`, `incr`). These sets should be updated to match reality as part of this work.

**Algorithm for chained resolution:**
1. When callee is `X.Y:method()` or `X.Y.method()`:
   - Check if `X` is in `PARAMETER_TYPE_MAP` → get module (e.g., `store` → `lib.lua.store`)
   - Check if `Y` is in `FIELD_TYPE_MAP[module]` → get sub-module (e.g., `assess_vector` → `common.base.lua.store_vector`)
   - Resolve `method` against the sub-module's exports in the global symbol table
2. Also handle `web.store.assess_vector:get()` (3-level chain):
   - The existing `parameter_resolver.py` already handles chained access by splitting on `.` and checking prefixes against `PARAMETER_TYPE_MAP` (lines 81-100). `web.store` resolves because `web` matches the map and the suffix `store` also matches.
   - Extend this existing chain logic: after resolving `web.store` → `lib.lua.store`, check if the remaining chain part (`assess_vector`) is in `FIELD_TYPE_MAP["lib.lua.store"]` → if yes, resolve to `common.base.lua.store_vector`.

**No aliasing support needed:** BOB confirmed `local av = store.assess_vector` pattern is NOT used in the codebase. Direct chained access is universal.

**Additional PARAMETER_TYPE_MAP entries from BOB C10/C11:**

BOB confirmed ALL actors receive the same signature:
```lua
function ActorName:act(bundle, store_object, session_id, old_assess_vector, new_assess_vector)
```

`store_object` is a Store instance across all ~23 actors. Add to PARAMETER_TYPE_MAP:
```python
PARAMETER_TYPE_MAP["store_object"] = "lib.lua.store"
```

This is a one-line addition that resolves calls like `store_object.assess_vector:get()` and `store_object:hget()` across all actor modules. Expected: +50-100 additional resolved calls.

**Implementation file:** `graph_builder/resolvers/parameter_resolver.py`

**Expected impact:** ~250-400 additional resolved CALLS edges (200-300 from store vector chains + 50-100 from `store_object` parameter mapping).

---

## 3. self:method() Inherited Fallback

### Problem

When a child module calls `self:validate()` and `validate` is defined in the base class (not overridden), the call goes unresolved. The CallResolver's self-handling finds no match in the current file and gives up.

BOB confirmed the inheritance structure:
- `handler.lua`: 20+ methods (complex base class, ~30 children)
- `collector.lua`: 11 methods (~40 children)
- `assessor.lua`: 1 method — `assess()` (minimal, always overridden)
- `actor.lua`: 1 method — `act()` (minimal, always overridden)

The handler base class has the most inheritable methods: `validate`, `response_map`, `add_handler_error`, `check_mark_store_save_async`, plus static methods like `user_error`, `parse_postdata`, `dispatch`, etc.

The metatable parent data IS already collected in `ast.metatable_parents` by the Lua parser. The `_resolve_via_inheritance` method exists in the CallResolver but is not invoked for `self:` calls.

### Solution

**Relationship to existing `base_inheritance_resolver.py`:** A dedicated resolver already exists at `graph_builder/resolvers/base_inheritance_resolver.py` that handles this exact problem — but with a hardcoded set of base module methods (`validate_input`, `handle_error`, `log_error`, `user_error`, `system_error` for handler; `validate_bundle`, `get_feature_flag`, `log_assessment` for assessor; `store_data` for collector). BOB's investigation shows the actual base module methods are DIFFERENT from what's hardcoded:

- **handler.lua actual methods:** `validate`, `response_map`, `add_handler_error`, `check_mark_store_save_async`, `user_error`, `parse_postdata`, `dispatch`, `handle_web_request`, `handle_ep_request`, `handle_pmc`, `handle_tma`, `handle_internal_request`, `add_error_metrics`, `parse_api_version_data`, `verify_store_size_limit`, `add_general_handler_error`, `create_handler`, `sanitize_error_output`, `user_error_format`, `create_handler_event`
- **collector.lua actual methods:** `trigger`, `collect`, `get_trigger_collector`, `trigger_web_request`, `get_collect_collector`, `decrypt_collect_data`, `collect_web_request`, `fake_collect_web_request`, `get_store`
- **assessor.lua:** just `assess` (always overridden)
- **actor.lua:** just `act` (always overridden, NEW — not in current resolver)

**Approach:** Update the existing `base_inheritance_resolver.py` rather than duplicating logic in `CallResolver`:
1. Update `BASE_MODULE_METHODS` to match BOB's actual method lists
2. Add `actor.lua` as a 4th base module
3. Keep the existing resolver's approach (scan self: calls, check if method is in base but not in local file)

**Additional fix in CallResolver:** The current `self:` resolution at lines 213-217 in `call_resolver.py` immediately returns `True` when `ast.module_info.table_var_name` exists, even if the method doesn't exist in the current file. This preempts the base inheritance resolver from correcting it later. Fix: add a guard — only resolve to same-file if the method name actually exists among the file's functions. If not, let it fall through so the base inheritance resolver can pick it up.

**Edge case — static method calls:** BOB showed handlers also call base methods via `Handler.user_error(...)` (using the required module name directly). These should already resolve through the binding map since `Handler` is a local variable bound via `require("common.base.lua.handler")`. Verify this works; if not, it's a separate issue.

**Implementation file:** `graph_builder/resolvers/call_resolver.py`

**Expected impact:** ~100-200 additional resolved calls, primarily handler children calling `validate`, `add_handler_error`, `response_map`, `check_mark_store_save_async`.

---

## Testing Strategy

### Unit Tests

1. **Alias classification tests:**
   - File with `local format = string.format; format("x")` → classified as builtin
   - File with `local encode = cjson.encode; encode(data)` → classified as external
   - Multi-assignment: `local a, b = string.format, string.sub` → both classified
   - Non-alias: `local x = some_module.func; x()` → NOT classified as builtin
   - Shadowing: `local format = custom_module.format; format()` → NOT classified (custom module not in builtin list)

2. **Store vector chain tests:**
   - `store.assess_vector:get("key")` → resolved to `store_vector.get`
   - `store.collect_vector:set("key", val)` → resolved to `store_vector.set`
   - `web.store.assess_vector:get("key")` → resolved via chained lookup
   - `store.session_id` → NOT resolved (plain string, not in FIELD_TYPE_MAP)
   - Unknown chain `foo.bar:method()` → NOT resolved

3. **Inherited self: tests:**
   - Child handler calling `self:validate()` → resolved to `handler.validate`
   - Child handler calling `self:apply()` → resolved to same-file (overridden)
   - Child collector calling `self:trigger()` → resolved to same-file (always overridden)
   - Non-inheriting module calling `self:method()` → stays unresolved (no parent)
   - CallResolver self: branch with `module_info.table_var_name` present but method NOT in file → does NOT resolve to same file (falls through to base inheritance resolver)

### Integration Verification

After implementation, run `code-graph build` + `code-graph health` and verify:
- Lua call resolution increases from 53.6% toward ~57-60%
- Builtin count increases (alias reclassification)
- Truly unresolved count decreases
- No regressions in other languages

---

## Expected Impact Summary

| Component | New Resolved/Classified | Mechanism |
|-----------|------------------------|-----------|
| Local alias classification | 500-800 reclassified as builtin/external | BuiltinClassifier alias map |
| Store vector CALLS edges | 200-300 new resolved calls | Parameter resolver chain logic |
| `store_object` parameter mapping | 50-100 new resolved calls | PARAMETER_TYPE_MAP addition |
| self:inherited fallback | 100-200 new resolved calls | Updated base_inheritance_resolver |
| **Total** | **850-1,400 improvement** | **Lua call res → ~57-60%** |

---

## Files Modified

| File | Change |
|------|--------|
| `graph_builder/resolvers/builtin_classifier.py` | Add `_build_alias_maps()`, extend `classify_all()` |
| `graph_builder/resolvers/parameter_resolver.py` | Add `FIELD_TYPE_MAP`, extend chain resolution logic |
| `graph_builder/resolvers/call_resolver.py` | Guard self: resolution to only match when method exists in file |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Update BASE_MODULE_METHODS to match actual base class methods, add actor.lua |
| `graph_builder/parsers/base.py` | Add `local_aliases: list[tuple[str, str]]` field to FileAST |
| `graph_builder/parsers/lua_parser.py` | Populate `local_aliases` from local assignment nodes |
| `graph_builder/resolvers/redis_abstraction_resolver.py` | Update _STORE_VECTOR_READ/_WRITE to match actual StoreVector methods |
| `graph_builder/tests/test_lua_call_resolution_v2.py` | New test file for all 3 components |
