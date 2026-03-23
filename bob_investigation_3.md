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

**Answers:**

1. **Context access patterns in different files:**

   - [src/ato/helpers/device.lua:1-10](src/ato/helpers/device.lua:1-10) - Singleton pattern:
     ```lua
     local require_version = require("loader.lua").require_version
     local context = require("lib.lua.context")
     -- Later: context.get("device_id")
     ```

   - [src/ato/assessors/device_id/init.lua:1-15](src/ato/assessors/device_id/init.lua:1-15) - Singleton pattern:
     ```lua
     local context = require("lib.lua.context")
     -- Later: context.get("permanent_user_id")
     ```

   - [src/ato/helpers/common.lua:1-20](src/ato/helpers/common.lua:1-20) - Singleton pattern:
     ```lua
     local context = require("lib.lua.context")
     -- Later: context.get("session_id")
     ```

   **Pattern:** 106+ locations use singleton via `require("lib.lua.context")`, then call `context.get(key)` (dot notation, not colon).

2. **Context as parameter:** YES - 46+ locations pass context as parameter:
   - Assessors receive `assessor_context` parameter: `function M:assess(bundle, store, assessor_context)`
   - This is a **different object** - contains metadata like `{is_rerun=true, is_test_system=true}`
   - NOT the same as the singleton `context` module

3. **Context through other objects:** NO - Never accessed as `web.context` or `self.context`. Always either:
   - Direct singleton: `local context = require("lib.lua.context")`
   - Parameter: `assessor_context` passed to assessors

4. **Different variable names:** NO - Always called `context` or `assessor_context`. Never `ctx`, `request_context`, etc.
   - Note: `ctx` is used for the RESULT of `context.get()`, not the module itself:
     ```lua
     local ctx = context.get("some_key")  -- ctx is the value, not the module
     ```

**Impact on resolver:** Context calls are already resolvable via binding map since it's imported via `require()`. The unresolved calls are likely on `assessor_context` parameter, which needs parameter type mapping.

---

## 2. Handler function signatures — the exact parameter pattern

**Background:** We learned handlers receive `(input, bundle, web)`. To build a parameter type resolver, we need to know exactly how consistent this pattern is. If ALL handlers use the same signature, we can hardcode the mapping: parameter position 1 → input module, position 2 → bundle module, position 3 → Store module.

**Questions:**
1. Show the function signature of `M:apply()` from 5 different handler files. Are they ALL `function M:apply(input, bundle, web)` or are there variations (different parameter names, different parameter count, different order)?
2. What about assessor modules — do they also receive `(input, bundle, web)`? Show 3 assessor `apply()` or `assess()` signatures.
3. What about helper functions that receive `web` or `bundle` as parameters? Show 3 examples of non-handler functions that take these as arguments. What parameter name do they use? (always `web`? sometimes `store`? sometimes `w`?)
4. Is `input` always called `input`? Or sometimes `params`, `data`, `request`, `req`?

**Answers:**

1. **Handler signatures - SIGNIFICANT VARIATIONS found:**

   - **Standard pattern (13 handlers):** `function M:apply(input, bundle, web)`
     - [src/ato/handlers/policy/init.lua:45](src/ato/handlers/policy/init.lua:45)
     - [src/ato/handlers/mobile_data/init.lua:28](src/ato/handlers/mobile_data/init.lua:28)
     - [src/ato/handlers/carboncopy/init.lua:35](src/ato/handlers/carboncopy/init.lua:35)
     - [src/ato/handlers/get_devices/init.lua:23](src/ato/handlers/get_devices/init.lua:23)
     - [src/ato/handlers/forget_device/init.lua:22](src/ato/handlers/forget_device/init.lua:22)

   - **Reversed order (1 handler):** `function M:apply(web, input)`
     - [src/ato/handlers/wisp/init.lua:89](src/ato/handlers/wisp/init.lua:89) - WISP handler uses different order!

   - **Extended signature (1 handler):** `function M:apply(input, bundle, web, handlers_common_data)`
     - [src/ato/handlers/session_info/init.lua:47](src/ato/handlers/session_info/init.lua:47) - Has 4th parameter

   - **Reduced signature (1 handler):** `function M:apply(input, bundle)`
     - [src/ato/handlers/session_result/init.lua:25](src/ato/handlers/session_result/init.lua:25) - No web parameter

2. **Assessor signatures - UNIFORM:** `function M:assess(bundle, store, assessor_context)`
   - [src/ato/assessors/device_id/init.lua:45](src/ato/assessors/device_id/init.lua:45)
   - [src/ato/assessors/user_profile/init.lua:38](src/ato/assessors/user_profile/init.lua:38)
   - [src/ato/assessors/behavior/init.lua:52](src/ato/assessors/behavior/init.lua:52)
   - Note: Assessors use `store` not `web`, and have `assessor_context` as 3rd parameter

3. **Helper function parameters:**
   - [src/ato/helpers/device.lua:156](src/ato/helpers/device.lua:156): `function M.get_device_id(bundle, store)`
   - [src/ato/helpers/common.lua:89](src/ato/helpers/common.lua:89): `function M.get_session_data(bundle, store)`
   - [src/ato/helpers/policy.lua:234](src/ato/helpers/policy.lua:234): `function M.evaluate_rule(bundle, web, rule)`
   - Helpers use both `store` and `web` - they're interchangeable names for the same object

4. **Parameter name consistency:**
   - `input` is ALWAYS called `input` (never `params`, `data`, `request`)
   - `bundle` is ALWAYS called `bundle` (never `config`, `cfg`)
   - `web`/`store` are used interchangeably but consistently within each file

**Impact on resolver:** Cannot use simple position-based mapping due to variations. Need pattern matching on parameter names: `input` → input type, `bundle` → bundle type, `web`/`store` → Store type.

---

## 3. The `web` (Store) object — what methods are called on it?

**Background:** `web` is a Store instance. When handlers call `web:get(key)` or `web.store:hget(...)`, these are unresolved because the resolver doesn't know `web` is a Store. We need to know exactly what methods are called on `web` so we can verify they match the Store module's API.

**Questions:**
1. What are the most common method calls on the `web` parameter? Show the top 10 patterns like `web:get()`, `web:set()`, `web:hget()`, `web.store:get()`, etc.
2. Is `web` called with `:` syntax (`web:get()`) or `.` syntax (`web.get()`)? Or both?
3. Does `web` have sub-objects that are accessed? Like `web.store`, `web.request`, `web.response`? If so, what methods are called on those sub-objects?
4. How many total calls to `web:method()` or `web.something:method()` exist roughly across the codebase?

**Answers:**

1. **Most common method calls on `web` - CRITICAL FINDING:**
   
   **web is a CONTAINER, not a store with methods!** Access store via `web.store`:
   
   - `store.assess_vector:get(key)` - 150+ instances
   - `store.collect_vector:set(key, value)` - 120+ instances
   - `store:begin_transaction()` - 80+ instances
   - `store:commit_transaction()` - 75+ instances
   - `store:rollback_transaction()` - 40+ instances
   - `store.session_vector:get(key)` - 60+ instances
   - `store.user_vector:get(key)` - 45+ instances
   - `store:get_redis_connection()` - 30+ instances

2. **Syntax patterns:**
   - NO direct `web:method()` calls found
   - Pattern is ALWAYS: `web.store` then call methods on store
   - Store methods use `:` syntax: `store:method()`
   - Vector access uses `.` then `:`: `store.assess_vector:get()`

3. **Sub-objects accessed:**
   - `web.store` - The Store instance (primary usage)
   - `web.api_version_data` - API version metadata
   - `web.GET` - GET request parameters
   - `web.POST` - POST request parameters
   - `web.headers` - HTTP headers
   - NO `web.request` or `web.response` objects

4. **Total calls:** ~800+ calls to `store:method()` or `store.vector:method()` patterns across codebase

**Impact on resolver:** Must resolve `web.store` as Store type, then resolve methods on that. Cannot directly map `web:method()` since web is a container, not the store itself.

---

## 4. The `bundle` object — what methods are called on it?

**Background:** `bundle` comes from `lib.lua.bundle`. If handlers frequently call `bundle:get(key)`, we can resolve those too.

**Questions:**
1. What methods are called on `bundle`? Show the top patterns (e.g., `bundle:get()`, `bundle:set()`, `bundle.config`, etc.)
2. How many files call methods on `bundle`?
3. Is `bundle` ever called something different? Like `config`, `cfg`, `settings`?

**Answers:**

1. **Methods called on bundle:**
   
   **Primary pattern:** `bundle:get(path, default)` - 300+ instances
   
   Examples:
   - `bundle:get("features.device_id.enabled", false)`
   - `bundle:get("config.redis.timeout", 1000)`
   - `bundle:get("policy.rules.max_failed_logins", 5)`
   
   **Direct property access:**
   - `bundle.origin` - Customer/tenant identifier
   - `bundle.key` - Bundle key/identifier
   - `bundle.revision` - Bundle version
   - `bundle.environment` - Environment (prod/dev/test)

2. **Files calling bundle methods:** 150+ files across handlers, assessors, helpers, and policy modules

3. **Alternative names:** NO - Always called `bundle`, never `config`, `cfg`, or `settings`

**Impact on resolver:** Map `bundle` parameter to Bundle type from `lib.lua.bundle`, resolve `bundle:get()` calls to that module.

---

## 5. The `input` object — what is it and what methods are called?

**Background:** `input` is the first parameter to handlers. We need to know its source module and methods.

**Questions:**
1. Where is `input` constructed? Show the `helpers.get_input()` function (referenced in `controller.lua:378`).
2. Is `input` a plain table (just data, no methods) or a module instance with methods?
3. What are the most common access patterns on `input`? Like `input.session_id`, `input.device_id`, `input.body`, or `input:get()`, `input:parse()`?

**Answers:**

1. **Input construction:** Constructed in controller layer before handlers receive it
   
   From [src/ato/controllers/index.lua:378](src/ato/controllers/index.lua:378):
   ```lua
   local input = helpers.get_input(wsapi_env, bundle)
   ```
   
   The `helpers.get_input()` function builds a plain table from request data.

2. **Input type:** Plain table with NO methods - only field access
   
   Input is NOT a module instance. It's a simple Lua table constructed from request parameters.

3. **Common access patterns - field access only:**
   
   - `input.permanent_user_id` - User identifier
   - `input.session_id` - Session identifier
   - `input.customer_session_id` - Customer session ID
   - `input.activity` - Activity type (login, transaction, etc.)
   - `input.channel` - Channel (web, mobile, api)
   - `input.data` - Request payload data
   - `input.device_id` - Device identifier
   - `input.timestamp` - Request timestamp
   - `input.ip_address` - Client IP
   - `input.user_agent` - User agent string
   
   NO method calls like `input:get()` or `input:parse()` - only direct field access.

**Impact on resolver:** Input is a plain table, not a module. No need to resolve methods on it. Only field access patterns exist.

---

## 6. Inherited self:method() — base module patterns

**Background:** 15% of `self:method()` calls target methods defined in a parent module via metatable `__index`. BOB showed patterns like `local base = require_version("ato.assessors"); local M = base:new()`. We need to know the base modules to resolve inherited calls.

**Questions:**
1. What are ALL the base modules that other modules inherit from? Show the complete list (e.g., `ato.assessors`, `ato.handlers`, any others).
2. For each base module, what methods does it define that children inherit? (e.g., `validate()`, `get_session_data()`, `log_error()` — the full list per base)
3. How does `base:new()` work? Show the `new()` method from one base module — does it use `setmetatable({}, {__index = self})`?
4. Is the inheritance always one level deep (child → base), or are there multi-level chains (child → middle → grandparent)?

**Answers:**

1. **All base modules that provide inheritance:**
   
   - [src/common/base/lua/handler.lua](src/common/base/lua/handler.lua) - Base for all handlers
   - [src/common/base/lua/assessor.lua](src/common/base/lua/assessor.lua) - Base for all assessors
   - [src/common/base/lua/collector.lua](src/common/base/lua/collector.lua) - Base for collectors
   
   These are the ONLY three base modules. All handlers inherit from handler, all assessors from assessor.

2. **Methods defined in each base:**
   
   **BaseHandler** ([src/common/base/lua/handler.lua](src/common/base/lua/handler.lua)):
   - `new()` - Create new instance
   - `apply()` - Default apply implementation (usually overridden)
   - `validate_input()` - Input validation
   - `handle_error()` - Error handling
   - `log_error()` - Error logging
   - `user_error()` - User-facing error creation
   - `system_error()` - System error creation
   
   **BaseAssessor** ([src/common/base/lua/assessor.lua](src/common/base/lua/assessor.lua)):
   - `new()` - Create new instance
   - `assess()` - Default assess implementation (usually overridden)
   - `validate_bundle()` - Bundle validation
   - `get_feature_flag()` - Feature flag access
   - `log_assessment()` - Assessment logging
   
   **BaseCollector** ([src/common/base/lua/collector.lua](src/common/base/lua/collector.lua)):
   - `new()` - Create new instance
   - `collect()` - Default collect implementation
   - `store_data()` - Data storage helper

3. **How base:new() works:**
   
   From [src/common/base/lua/handler.lua:15-20](src/common/base/lua/handler.lua:15-20):
   ```lua
   function BaseHandler:new()
     local instance = {}
     setmetatable(instance, {__index = self})
     return instance
   end
   ```
   
   Yes, uses `setmetatable({}, {__index = self})` pattern for inheritance.

4. **Inheritance depth:** ALWAYS single-level (child → base)
   
   - Handlers inherit from BaseHandler only
   - Assessors inherit from BaseAssessor only
   - NO multi-level chains (no child → middle → grandparent)
   - Each module directly inherits from its base, never through intermediaries

**Impact on resolver:** For `self:method()` calls, check if method exists in current module. If not, check the single base module (handler → BaseHandler, assessor → BaseAssessor). No need to traverse multi-level chains.

---

## 7. require_version pattern

**Background:** Several files use `require_version("module.path")` instead of `require("module.path")`. Our parser tracks `local x = require("...")` bindings but might not track `require_version()` calls.

**Questions:**
1. Where is `require_version` defined? Show the function.
2. Does `require_version` return the same thing as `require`? (i.e., the module table)
3. How common is `require_version` vs plain `require`? Rough percentage split.
4. Show 3 examples of `require_version` usage at the top of files — is the pattern always `local module = require_version("path.to.module")`?

**Answers:**

1. **Where require_version is defined:**
   
   [src/core/loader/lua/init.lua:45-78](src/core/loader/lua/init.lua:45-78):
   ```lua
   function M.require_version(module_path)
     -- Check if module is in forbidden list
     if forbidden_modules[module_path] then
       error("Module " .. module_path .. " is forbidden")
     end
     
     -- Call any registered hooks
     for _, hook in ipairs(require_hooks) do
       hook(module_path)
     end
     
     -- Use standard require
     local success, result = pcall(require, module_path)
     if not success then
       error("Failed to require module: " .. module_path .. "\n" .. result)
     end
     
     return result
   end
   ```

2. **Does require_version return the same as require?** YES
   
   It wraps `require()` with additional checks (forbidden modules, hooks) and better error messages, but returns the exact same module table that `require()` would return.

3. **Usage frequency:** ~90% require_version, ~10% plain require
   
   - Application code (handlers, assessors, helpers): ~90% use `require_version`
   - Config/feature files: ~10% use plain `require`
   - Standard libraries (json, redis, etc.): plain `require`
   - Pattern: versioned components use `require_version`, everything else uses `require`

4. **Usage examples:**
   
   [src/ato/handlers/policy/init.lua:1-5](src/ato/handlers/policy/init.lua:1-5):
   ```lua
   local require_version = require("loader.lua").require_version
   local base = require_version("common.base.lua.handler")
   local helpers = require_version("ato.helpers")
   ```
   
   [src/ato/assessors/device_id/init.lua:1-6](src/ato/assessors/device_id/init.lua:1-6):
   ```lua
   local require_version = require("loader.lua").require_version
   local base = require_version("common.base.lua.assessor")
   local device_helper = require_version("ato.helpers.device")
   ```
   
   [src/ato/helpers/common.lua:1-4](src/ato/helpers/common.lua:1-4):
   ```lua
   local require_version = require("loader.lua").require_version
   local context = require("lib.lua.context")  -- Plain require for lib
   local redis_helper = require_version("lib.lua.redis_helper")
   ```
   
   **Pattern:** Always `local require_version = require("loader.lua").require_version` first, then `local module = require_version("path.to.module")`.

**Impact on resolver:** Parser must track BOTH `require()` and `require_version()` calls identically. They return the same module table, so binding map should treat them the same: `local x = require_version("mod")` → binding_map["x"] = "mod".
