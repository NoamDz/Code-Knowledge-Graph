# BOB Investigation — Round 3

## Context

We're building a **Code Knowledge Graph** that parses this codebase with Tree-sitter and builds a semantic graph of functions, calls, imports, and dependencies. From Rounds 1-2, we learned:

- Handlers receive `(input, bundle, web)` as separate parameters (NOT a unified `runtime` object)
- `web` is a Store instance (`Store:new(wsapi_env, bundle)`) from `lib.lua.store`
- `context` is a separate singleton module from `lib.lua.context` with 17 methods and 121+ usage locations
- `self:method()` calls are 85% same-file, 15% inherited via metatable
- Our call resolver currently can't resolve calls on parameters (`web:get()`, `context:get_device_id()`) because it doesn't know their types

We're now designing a **parameter type resolver** that maps parameter names to their source modules, so calls like `web:get(key)` resolve to `lib.lua.store.get`. This round's questions determine exactly how to implement it.

---

## 1. How is `context` accessed — require or parameter?

**Background:** BOB said `context` is imported via `require("lib.lua.context")` and has 121+ usage locations. If it's always imported via `require`, our existing call resolver should already resolve `context:get_device_id()` through its binding map (`local context = require("lib.lua.context")` → binding_map["context"] = "lib.lua.context"`). But these calls are showing as unresolved in our health report, which means something is different.

**Questions:**
1. Show 3-4 different files that call `context:get_device_id()` or `context:get()`. For each one, show the **top of the file** (the require/import section) — how does `context` get into scope?
2. Is `context` ever passed as a function parameter instead of being required? For example: `function M:apply(input, bundle, web, context)` or `function assess(context, data)`
3. Is there a case where `context` is accessed through another object? Like `web.context:get_device_id()` or `self.context:get()`
4. Is `context` sometimes imported under a different variable name? Like `local ctx = require("lib.lua.context")` or `local request_context = require("lib.lua.context")`

---

## 2. Handler function signatures — the exact parameter pattern

**Background:** We learned handlers receive `(input, bundle, web)`. To build a parameter type resolver, we need to know exactly how consistent this pattern is. If ALL handlers use the same signature, we can hardcode the mapping: parameter position 1 → input module, position 2 → bundle module, position 3 → Store module.

**Questions:**
1. Show the function signature of `M:apply()` from 5 different handler files. Are they ALL `function M:apply(input, bundle, web)` or are there variations (different parameter names, different parameter count, different order)?
2. What about assessor modules — do they also receive `(input, bundle, web)`? Show 3 assessor `apply()` or `assess()` signatures.
3. What about helper functions that receive `web` or `bundle` as parameters? Show 3 examples of non-handler functions that take these as arguments. What parameter name do they use? (always `web`? sometimes `store`? sometimes `w`?)
4. Is `input` always called `input`? Or sometimes `params`, `data`, `request`, `req`?

---

## 3. The `web` (Store) object — what methods are called on it?

**Background:** `web` is a Store instance. When handlers call `web:get(key)` or `web.store:hget(...)`, these are unresolved because the resolver doesn't know `web` is a Store. We need to know exactly what methods are called on `web` so we can verify they match the Store module's API.

**Questions:**
1. What are the most common method calls on the `web` parameter? Show the top 10 patterns like `web:get()`, `web:set()`, `web:hget()`, `web.store:get()`, etc.
2. Is `web` called with `:` syntax (`web:get()`) or `.` syntax (`web.get()`)? Or both?
3. Does `web` have sub-objects that are accessed? Like `web.store`, `web.request`, `web.response`? If so, what methods are called on those sub-objects?
4. How many total calls to `web:method()` or `web.something:method()` exist roughly across the codebase?

---

## 4. The `bundle` object — what methods are called on it?

**Background:** `bundle` comes from `lib.lua.bundle`. If handlers frequently call `bundle:get(key)`, we can resolve those too.

**Questions:**
1. What methods are called on `bundle`? Show the top patterns (e.g., `bundle:get()`, `bundle:set()`, `bundle.config`, etc.)
2. How many files call methods on `bundle`?
3. Is `bundle` ever called something different? Like `config`, `cfg`, `settings`?

---

## 5. The `input` object — what is it and what methods are called?

**Background:** `input` is the first parameter to handlers. We need to know its source module and methods.

**Questions:**
1. Where is `input` constructed? Show the `helpers.get_input()` function (referenced in `controller.lua:378`).
2. Is `input` a plain table (just data, no methods) or a module instance with methods?
3. What are the most common access patterns on `input`? Like `input.session_id`, `input.device_id`, `input.body`, or `input:get()`, `input:parse()`?

---

## 6. Inherited self:method() — base module patterns

**Background:** 15% of `self:method()` calls target methods defined in a parent module via metatable `__index`. BOB showed patterns like `local base = require_version("ato.assessors"); local M = base:new()`. We need to know the base modules to resolve inherited calls.

**Questions:**
1. What are ALL the base modules that other modules inherit from? Show the complete list (e.g., `ato.assessors`, `ato.handlers`, any others).
2. For each base module, what methods does it define that children inherit? (e.g., `validate()`, `get_session_data()`, `log_error()` — the full list per base)
3. How does `base:new()` work? Show the `new()` method from one base module — does it use `setmetatable({}, {__index = self})`?
4. Is the inheritance always one level deep (child → base), or are there multi-level chains (child → middle → grandparent)?

---

## 7. require_version pattern

**Background:** Several files use `require_version("module.path")` instead of `require("module.path")`. Our parser tracks `local x = require("...")` bindings but might not track `require_version()` calls.

**Questions:**
1. Where is `require_version` defined? Show the function.
2. Does `require_version` return the same thing as `require`? (i.e., the module table)
3. How common is `require_version` vs plain `require`? Rough percentage split.
4. Show 3 examples of `require_version` usage at the top of files — is the pattern always `local module = require_version("path.to.module")`?
