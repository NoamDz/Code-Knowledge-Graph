# Lua Call Resolution Deep Analysis

**Date:** 2026-03-25
**Focus:** Analyzing the ~13,414 unresolved Lua calls and strategies to improve resolution

---

## Current State

| Metric | Count | % |
|--------|-------|---|
| Total Lua calls | 28,899 | 100% |
| Resolved (CallResolver) | ~14,173 | 49.0% |
| Resolved (Parameter resolver) | +1,419 | +4.9% |
| **Total resolved** | **15,485** | **53.6%** |
| Builtins classified | 7,601 | 26.3% |
| External classified | 8 | ~0% |
| **Effective coverage** | **23,094** | **79.9%** |
| **Truly unresolved** | **~5,805** | **~20.1%** |

Wait — the report says 13,414 unresolved calls, but this mixes Lua + other languages in the "truly_unresolved" bucket. Looking more carefully at the report:

- Total calls across all languages: ~45,436
- Resolved: 21,011 (46.2%)
- Builtins: 7,601
- Truly unresolved: 16,816

For Lua specifically (28,899 total):
- Resolved: 15,485 (53.6%)
- The remainder (13,414) includes builtins + truly unresolved for Lua

**Lua-specific breakdown (estimated):**
| Category | Estimated Count | Strategy |
|----------|----------------|----------|
| Resolved calls | 15,485 | Already done |
| Lua builtins (string.*, table.*, etc.) | ~5,500-6,000 | Classified by BuiltinClassifier |
| OpenResty builtins (ngx.*) | ~1,000-1,500 | Classified by BuiltinClassifier |
| External libs (cjson.*, resty.*) | ~500-800 | Classified by BuiltinClassifier |
| **Truly unresolved Lua calls** | **~5,100-6,400** | **Target for improvement** |

---

## Taxonomy of Truly Unresolved Lua Calls

Based on the 4 BOB investigation rounds, here is a detailed categorization:

### Category 1: Multi-Level Dot Chain Calls (~1,500-2,000 calls, ~25-30%)

**Pattern:** `a.b.c:method()` or `a.b.c.d:method()` where the chain depth exceeds the resolver's 2-level tracking.

**Sub-patterns found in BOB investigations:**

| Pattern | Estimated Count | Example | Can Resolve Statically? |
|---------|----------------|---------|------------------------|
| `store.assess_vector:method()` | ~150 | `store.assess_vector:get(key)` | YES — already handled by Redis abstraction resolver for Redis detection, but NOT for call resolution |
| `store.collect_vector:method()` | ~120 | `store.collect_vector:set(key, val)` | YES — same as above |
| `store.session_vector:method()` | ~60 | `store.session_vector:get(key)` | YES — need to add as known vector |
| `store.user_vector:method()` | ~45 | `store.user_vector:get(key)` | YES — need to add as known vector |
| `web.store:method()` | ~200 | `web.store:begin_transaction()` | YES — `web` maps to Store, `.store` is Store property |
| `web.store.vector:method()` | ~100 | `web.store.assess_vector:get()` | YES — 3-level chain, known types |
| `runtime.web.store:method()` | ~50 | `runtime.web.store:get(key)` | PARTIAL — `runtime` is not directly a known parameter |
| `crypto.base64.encode()` | ~30 | `crypto.base64.encode(data)` | YES — if crypto module is tracked |
| `runtime.config.X.Y` | ~20 | `runtime.config.services.endpoint` | NO — config is a plain table with dynamic structure |
| Other deep chains | ~200 | Various 3-5 level chains | DEPENDS |

**Key Insight:** The Redis abstraction resolver DOES handle store vector chains for Redis detection, but the call resolver does NOT resolve these for call graph edges. There's a gap: ~575+ store vector calls create Redis edges but NOT CALLS edges.

**Resolution Strategy:**
1. **Extend parameter resolver to handle chained access:** When we see `store.assess_vector:get()`, split the chain. If `store` maps to `lib.lua.store`, and `assess_vector` is a known factory, resolve the call to `lib.lua.store_vector.get`.
2. **Add session_vector and user_vector** to `STORE_VECTOR_FACTORIES` (currently only `collect_vector` and `assess_vector`).
3. **Support 3-level chains:** `web.store.assess_vector:get()` — resolve `web` → Store, `.store` → Store internal, `.assess_vector` → StoreVector.

### Category 2: Method Calls on Untyped Parameters (~1,200-1,800 calls, ~25-30%)

**Pattern:** Functions receive objects as parameters, and the resolver doesn't know the type.

**Sub-patterns:**

| Parameter Name | Type | Estimated Calls | In Parameter Map? |
|---------------|------|----------------|-------------------|
| `bundle` | `lib.lua.bundle` | ~300 | YES (already resolving) |
| `store` | `lib.lua.store` | ~200 | YES (already resolving) |
| `web` | `lib.lua.store` | ~200 | YES (already resolving) |
| `assessor_context` | Plain table (metadata) | ~46 | NO — but it's a plain table, no methods |
| `handler` | Varies (handler modules) | ~100 | NO — type depends on caller |
| `redis_client` | `resty.redis` instance | ~80 | PARTIAL — direct redis tracked, but parameter passing isn't |
| `task` | Plain table (task data) | ~60 | NO — plain table |
| `response` | Plain table | ~50 | NO — plain table |
| `err` | String or table | ~30 | NO — doesn't need resolution |
| Unknown others | Various | ~300 | NO |

**Already Handled:** `bundle`, `store`, `web` (1,419 calls via parameter resolver)

**What Could Be Added:**

The parameter resolver currently maps only 3 names. From BOB investigations, we could add:

```python
PARAMETER_TYPE_MAP = {
    "bundle": "lib.lua.bundle",
    "web": "lib.lua.store",
    "store": "lib.lua.store",
    # NEW: Could add these
    "assessor_context": None,  # Plain table, no methods — skip
    "redis_helper": "lib.lua.redis_helper",
    "redis": "lib.lua.redis_helper",  # When passed as parameter
    "logger": "lib.lua.logger",
    "context": "lib.lua.context",  # When not required directly
}
```

**However:** Most parameter calls beyond the top 3 are on objects whose types vary by caller (e.g., `handler` could be any handler module). These need **call-site type propagation**, not simple name mapping.

### Category 3: self:method() Calls to Inherited Methods (~300-500 calls, ~5-8%)

**Pattern:** `self:validate()` where the method is defined in a base class, not the current file.

**From BOB Round 2 & 3:**
- 85% of `self:method()` calls are same-file (already resolved)
- 15% are inherited from base classes
- Only 3 base classes: `common.base.lua.handler`, `common.base.lua.assessor`, `common.base.lua.collector`
- Inheritance is always single-level (no grandparent chains)

**What the call resolver already does (from code review):**
```python
# self:method() resolution — already implemented
if table_name == "self":
    if ast.module_info and ast.module_info.table_var_name:
        call.resolved_module = ast.module_name or ast.file_path
        call.resolved_function = method_name
        call.resolution_confidence = "self"
        return True
    for func in ast.functions:
        func_base = func.name.split(".")[-1].split(":")[-1]
        if func_base == method_name:
            call.resolved_module = ast.module_name or ast.file_path
            call.resolved_function = method_name
            call.resolution_confidence = "self"
            return True
```

**Problem:** When `self:validate()` is called and `validate` is NOT defined in the current file, the resolver falls through and the call remains unresolved. The metatable inheritance data IS being tracked (`ast.metatable_parents`), and the `_resolve_via_inheritance` method exists, but it's only used for class-based resolution, not for `self:` calls.

**Fix:** After the same-file self: check fails, check `ast.metatable_parents` to find the parent module and try resolving there:

```python
if table_name == "self":
    # ... existing same-file logic ...

    # NEW: Check inherited methods via metatable
    if ast.module_info and ast.module_info.table_var_name:
        table_var = ast.module_info.table_var_name
        parent_module = ast.metatable_parents.get(table_var)
        if parent_module:
            # Look up parent in global symbols
            parent_key = f"{parent_module}.{method_name}"
            if parent_key in self.global_symbols:
                call.resolved_module = parent_module
                call.resolved_function = method_name
                call.resolution_confidence = "inherited"
                return True
```

**Estimated impact:** ~300-500 additional resolutions.

### Category 4: Dynamic Dispatch / Dynamic Require (~76 calls, ~1-2%)

**Pattern:** `require(string.format("handlers.%s", name))` — the module string is computed at runtime.

**From BOB investigations:**
- 76 dynamic requires found
- Controller dispatch: `require(format("%s.controllers.%s", component, controller_name))`
- Handler dispatch: `require(format("%s.handlers.%s", component, handler_name))`
- Task dispatch: task name → task file mapping

**Already handled:**
- Dynamic prefix resolver expands `require("handlers." .. x)` to POTENTIAL_IMPORT edges for all files under `handlers/`
- Mission dispatch maps `missioner.add_mission("pts_run", ...)` to `tasks/pts_run.lua`
- 76 calls is small; further improvement here has minimal impact

### Category 5: Calls on Return Values of Functions (~500-800 calls, ~8-12%)

**Pattern:** `some_function():method()` or `local obj = some_function(); obj:method()`

**Examples from BOB:**
```lua
local data = runtime.web.request:get_body():parse_json()
-- `:parse_json()` is called on the RETURN VALUE of `:get_body()`
```

**This is very hard to resolve statically because:**
1. Need to know the return type of `get_body()`
2. Lua has no type annotations
3. Would need full return-type inference (essentially type checking)

**Feasibility:** LOW — would require a Lua type inference engine. Not worth the complexity for ~500-800 calls.

### Category 6: Calls Through Unknown Local Variables (~800-1,200 calls, ~15-20%)

**Pattern:** A local variable is assigned from a function call or table access, then methods are called on it.

```lua
local result = some_module.get_handler(name)
result:process()  -- What type is `result`?
```

**Sub-patterns:**
- Variables assigned from function returns (most common)
- Variables assigned from table lookups
- Variables assigned from conditional expressions
- Loop variables from `pairs()` / `ipairs()`

**Feasibility:** MEDIUM-LOW — Could handle some patterns with heuristics:
- If `some_module.get_handler` returns a handler-like object, and we know handler modules have `process()`, we could infer the type
- But this requires function return type tracking across files

### Category 7: Truly Ambiguous / Unreachable (~500-800 calls, ~8-12%)

**Pattern:** Calls that are genuinely ambiguous without runtime information.

Examples:
- Callback functions: `callback(result)` where `callback` is a parameter
- Generic iterators: `func(key, value)` inside custom iteration
- Error handlers: `on_error(err)` passed as a function reference
- Metaprogramming: `rawget(t, k)()` — calling a dynamically retrieved function

**Feasibility:** NONE — These represent the true floor of static analysis.

---

## Prioritized Improvement Plan

### Tier 1: High Impact, Low Effort (estimated +800-1,200 resolved calls)

#### 1A. Fix self:method() inherited resolution
- **What:** When `self:method()` fails same-file lookup, check `ast.metatable_parents` for parent module
- **Where:** `call_resolver.py`, `_resolve_call()` method, self: branch
- **Impact:** ~300-500 calls
- **Effort:** Small — data already collected, just need to connect it

#### 1B. Extend parameter resolver with more vector types
- **What:** Add `session_vector`, `user_vector` to `STORE_VECTOR_FACTORIES`; add known parameter names
- **Where:** `parameter_resolver.py` and `redis_abstraction_resolver.py`
- **Impact:** ~200-300 calls resolved + ~105 more Redis detections
- **Effort:** Trivial — just add entries to existing maps

#### 1C. Resolve chained parameter access for call resolution (not just Redis)
- **What:** When we see `store.assess_vector:get()`, resolve the CALL edge (not just Redis edge)
- **Where:** `parameter_resolver.py` — extend chained access logic to also set `resolved_module`
- **Impact:** ~375+ calls (store vectors accessed ~375 times: 150+120+60+45)
- **Effort:** Small — extend existing logic

### Tier 2: Medium Impact, Medium Effort (estimated +500-1,000 resolved calls)

#### 2A. Track local variable assignments from known modules
- **What:** When we see `local foo = store:get_handler()`, and we know `store` is `lib.lua.store`, record that `foo` might be a handler type
- **Where:** New resolver pass or extension to `_build_type_map`
- **Impact:** ~300-500 calls
- **Effort:** Medium — need to track assignment chains, not just require bindings

#### 2B. Contextual parameter type propagation
- **What:** When `handler:apply(input, bundle, web)` is called and we know `handler` was loaded from a specific module, propagate the parameter types into the handler file's AST
- **Where:** New resolver pass that runs after `CallResolver`
- **Impact:** ~200-400 calls (particularly for assessor/helper parameters)
- **Effort:** Medium — need inter-file analysis

#### 2C. Add more known parameter names
- **What:** Map additional conventional parameter names: `redis_helper` → `lib.lua.redis_helper`, `logger` → `lib.lua.logger`, `config` → config module
- **Where:** `parameter_resolver.py` PARAMETER_TYPE_MAP
- **Impact:** ~100-200 calls
- **Effort:** Low — just add entries, BUT need BOB confirmation on conventions

### Tier 3: Low Impact, High Effort (diminishing returns)

#### 3A. Lua type inference engine
- **What:** Build a basic type inference system that tracks types through assignments, function returns, and table constructions
- **Impact:** ~500-800 calls
- **Effort:** HIGH — essentially building a type checker for a dynamically typed language

#### 3B. Call frequency analysis
- **What:** Analyze which unresolved callee_strings appear most frequently, then manually map the top 20
- **Impact:** Variable — depends on concentration
- **Effort:** Medium — needs runtime data or manual investigation

#### 3C. Return type tracking
- **What:** Track what types functions return (by analyzing their return statements) and use that to type local variables
- **Impact:** ~300-500 calls
- **Effort:** HIGH — requires building a return-type inference system

---

## What Patterns Require Runtime Analysis?

These patterns CANNOT be resolved by static analysis alone:

1. **Dynamic dispatch via string computation:** `require(format("handlers.%s", name))` where `name` comes from user input or database
2. **Callback chains:** `register_handler(function() some_call() end)` — the callback's context is unknown
3. **Metatable magic:** `setmetatable(t, {__call = fn})` — `t()` calls `fn` but this is invisible to static analysis
4. **pcall return value usage:** `local ok, result = pcall(require, module_name)` — `result` type depends on which module loaded
5. **Table-as-namespace patterns:** `local handlers = {}; handlers[name] = require(path)` — dynamic table population
6. **Generic function objects:** `local fn = get_function_by_name(name); fn(args)` — function identity unknown

---

## Could Lua Type Inference Help?

### What's feasible (lightweight inference):
1. **Constructor tracking:** `local obj = Module:new()` → `obj` has type `Module`
   - Already partially implemented in `_build_type_map` for classes
   - Could extend to Lua module `:new()` patterns

2. **Require-to-type:** `local Store = require("lib.lua.store"); local s = Store:new()` → `s` has type `Store`/`lib.lua.store`
   - Combines existing binding map with constructor detection

3. **Field access propagation:** If `runtime.web` is type Store, then `runtime.web.store` is type StoreInternal
   - Requires a type schema for Store's fields

### What's not feasible (full inference):
1. **Flow-sensitive typing:** Different types on different branches (`if x then ... else ...`)
2. **Table structural typing:** Inferring type from which fields are set
3. **Higher-order function types:** Functions returning functions with specific signatures
4. **Metatype inference:** Types arising from metatable chains

### Recommendation:
Implement a **lightweight, hardcoded type schema** for the 5-6 most important modules (Store, Bundle, Context, RedisHelper, Logger, BaseHandler). Map their constructor patterns and method sets. This would be a more targeted version of what the parameter resolver already does.

---

## Summary: Expected Resolution After All Tier 1+2 Improvements

| Current | After Tier 1 | After Tier 2 | After All |
|---------|-------------|-------------|-----------|
| 53.6% | 56-58% | 59-62% | ~60-62% |
| 15,485 resolved | +800-1,200 | +500-1,000 | +1,300-2,200 total new |

The ceiling for static Lua call resolution in this codebase is approximately **60-65%**. Beyond that would require runtime analysis, LLM-based inference, or developer annotations.

---

## BOB Investigation Questions — Round 5: Call Resolution Deep Dive

### Q1. Most Common Unresolved Callee Strings

**Context:** We've resolved 53.6% of Lua calls. The remaining ~13,414 unresolved calls include builtins (classified) and truly unresolved. To prioritize which patterns to tackle, we need to know which callee strings appear most frequently in the "truly unresolved" bucket.

**Questions:**

1. Run this mental exercise: across all Lua files in `src/`, what are the **20 most common method/function calls** that would NOT match any of these:
   - Lua builtins: `print`, `pairs`, `ipairs`, `type`, `tonumber`, `tostring`, `error`, `assert`, `next`, `setmetatable`, `pcall`, `xpcall`, `select`, `unpack`
   - Lua stdlib: `string.*`, `table.*`, `math.*`, `os.*`, `io.*`
   - OpenResty: `ngx.*`
   - External: `cjson.*`, `resty.*`
   - Already resolved via require: calls on variables that have `require()` bindings
   - Parameter resolver: calls on `bundle`, `store`, `web`

   Show the top 20 callee strings with approximate call counts. For example: `store.assess_vector:get` (150), `self:validate` (45), etc.

2. Of those top 20, which ones are calls on **store vectors** (assess_vector, collect_vector, session_vector, user_vector)?

3. Which are calls on **variables assigned from function returns** (e.g., `local x = some_func(); x:method()`)? Show the assignment pattern.

4. Are there any **recurring local variable names** used across many files that aren't in our parameter map? For example, if 30+ files have `local helpers = require_version("ato.helpers")` and then call `helpers.something()`, that's already resolved. But if 30+ files have `local result = process(); result:save()`, that's unresolved.

---

### Q2. Multi-Level Dot Chain Usage Examples

**Context:** We know `store.assess_vector:get()` is common (~150 calls). We need to understand the full set of dot-chain patterns to build a chain resolver.

**Questions:**

1. What are ALL the sub-objects accessed on `store` (the Store instance)? We know about `assess_vector` and `collect_vector`. Are there others? Show the complete list: `store.X` where X is accessed as a sub-object. For each one, what module/type does it come from?

2. For `store.assess_vector`, what is the actual implementation? Is it a table with methods? A separate module? Show where `assess_vector` is defined in the Store module (file path and code).

3. Are there multi-level chains beyond the `store.*` pattern? For example:
   - `bundle.config.X:method()` — does bundle have nested objects with methods?
   - `helpers.X.Y:method()` — do helper modules have sub-objects?
   - `context.X:method()` — does context have nested objects?
   Show any patterns with 3+ levels that are NOT store-related.

4. What about chains that start with a local variable assignment? Like:
   ```lua
   local av = store.assess_vector
   av:get("some_key")
   ```
   How common is this "aliasing" pattern? If common, we'd need to track local variable assignments to resolve `av:get()`.

---

### Q3. Variable Naming Conventions for Type Inference

**Context:** We want to build a lightweight type inference system based on variable naming conventions. If `redis_client` always means a Redis client instance, we can resolve methods on it.

**Questions:**

1. What are the most common local variable names used for objects across the Lua codebase? Show the top 30 local variable names that have methods called on them (via `:` syntax), with:
   - The variable name
   - What module/type it typically refers to
   - Whether it's assigned from `require()` (already tracked) or from a function call/parameter
   - How many files use this name

2. Are there any naming conventions for temporary/loop variables that would help? For example:
   - `actor` → always an actor module?
   - `assessor` → always an assessor module?
   - `collector` → always a collector module?
   - `task` → always a task data table?

3. When functions extract sub-objects into local variables, what names do they use?
   ```lua
   local store = web.store          -- Is this common?
   local av = store.assess_vector   -- Is this common?
   local config = bundle:get("...")  -- Returns what type?
   ```
   Show 5 examples of this "destructuring into locals" pattern.

---

### Q4. Module Composition and Factory Patterns

**Context:** We need to understand how the Store, Bundle, and Context modules are composed internally. If `Store:new()` creates an object with sub-objects (`.assess_vector`, `.collect_vector`), we need to know the shape to resolve chains.

**Questions:**

1. Show the `Store:new()` constructor (or equivalent) from `src/lib/lua/store.lua`. What fields does it set on the new instance? Specifically:
   - `self.assess_vector = ???` — what is this?
   - `self.collect_vector = ???` — what is this?
   - `self.session_vector = ???`
   - `self.user_vector = ???`
   - Any other sub-objects?

2. Is `store_vector` (the type of assess_vector, collect_vector) a separate Lua module? If so, what's its module path (e.g., `lib.lua.store_vector`)? What methods does it expose?

3. Are there factory functions in the codebase that return objects of known types? For example:
   ```lua
   function M.create_handler(name)
       return require(format("ato.handlers.%s", name))
   end
   ```
   Show any factory/builder patterns that produce typed objects.

4. Does `Bundle:get(path)` return different types depending on the path? For example:
   - `bundle:get("features.X.enabled")` returns boolean
   - `bundle:get("config.redis")` returns table
   - `bundle:get("assessors")` returns list of assessor config objects
   Understanding this helps us know whether to try resolving methods on `bundle:get()` return values.

---

### Q5. Actor and Task Patterns

**Context:** BOB mentioned actors (~20 actors) and tasks as significant parts of the codebase. These likely have many method calls on parameters that could be resolved.

**Questions:**

1. What is the standard function signature for actors? Do they follow a pattern like `function M:execute(store, params)` or `function M.run(bundle, store, data)`? Show 3 actor signatures.

2. What is the standard function signature for tasks? Show the entry point signature for 3 different task files (e.g., `pts_run.lua`, `invoke_actors.lua`, `assess.lua`).

3. Inside actors and tasks, what are the most common unresolved calls? For example, do actors call `store.assess_vector:set()` frequently? Do tasks call `handler:apply()` frequently?

4. How many actor files and task files exist? These have predictable structures, so if we can map their parameter types, it would resolve a concentrated set of calls.

---

### Q6. The "helpers" Pattern

**Context:** Helper modules appear throughout the codebase (`ato.helpers.device`, `ato.helpers.common`, `ato.helpers.policy`). They're typically required and their methods are called directly, so they should already be resolved. But we want to confirm.

**Questions:**

1. How many helper modules exist under `src/ato/helpers/`? Do they follow a consistent pattern (local M = {}, function M.helper_name, return M)?

2. Do helper functions receive typed parameters? For example, does `helpers.get_device_id(bundle, store)` always receive bundle and store with those types? If so, calls INSIDE helper functions on `bundle` and `store` should be resolved by the parameter resolver.

3. Are there helper functions that receive objects whose type varies? Show an example of a helper that receives a parameter we can't type-map.

4. Are there "shared helpers" that multiple modules import differently? For example, if `ato.helpers` has an `init.lua` that re-exports functions from sub-modules, calls through different import paths might create resolution issues.

---

### Q7. Format of Unresolved Call Data

**Context:** To validate our analysis, we need actual data from the graph build.

**Questions (these are for running against the codebase, not for BOB):**

1. If you run `code-graph spot-check` on `src/ato/handlers/policy/init.lua`, what unresolved calls appear?
2. If you run `code-graph spot-check` on `src/ato/assessors/device_analyzer/init.lua`, what unresolved calls appear?
3. If you run `code-graph spot-check` on `src/ato/actors/save_policy_results/init.lua`, what unresolved calls appear?

These would show us the actual callee_strings that remain unresolved after all current resolvers run.
