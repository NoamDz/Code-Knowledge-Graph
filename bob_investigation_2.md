# BOB Investigation — Round 2

## Context

We're building a **Code Knowledge Graph** — a tool that parses this codebase using Tree-sitter, extracts functions/calls/imports, and builds a graph in Memgraph. The goal is to let an AI agent understand the codebase structure, trace request flows, and find dependencies.

**The problem:** Our static analysis tool is missing many connections because the codebase uses abstraction patterns that hide the real dependencies. For example:
- Lua HTTP calls go through `http_handler.post()` instead of raw `resty.http` — we detect 0 HTTP calls
- JavaScript HTTP calls go through `Container._sendRequest()` — we detect 0 JS HTTP calls
- Go Redis calls use custom wrapper methods (`HGetAsString`, `GetAsInt`) — we detect 0 Go Redis calls
- ~22,000 Lua function calls are unresolved because they're method calls on parameter objects (like `runtime.web.store:get()`) whose type we can't infer

**What we need from you:** Concrete code examples showing the actual patterns used, so we can teach the parser to recognize them. For each answer, show **real file paths and code snippets** from the codebase.

---

## Questions

Follow-up questions based on Round 1 findings.

---

## 1. Runtime Object Structure (critical — unlocks ~5,000-10,000 call resolutions)

**Background:** From Round 1, we learned that most Lua handlers receive a `runtime` parameter via `handler:apply(runtime)`. The most common unresolved calls look like `runtime.web.store:get(key)`, `runtime.web.request:get_body()`, etc. If we can map the fields of `runtime` to their source modules (e.g., `runtime.web.store` comes from `require("lib.lua.store")`), we can resolve thousands of calls that are currently invisible to static analysis.

The `runtime` object is passed to every handler via `handler:apply(runtime)`. I need its full shape.

1. Where is `runtime` constructed? Show the `build_runtime` function (likely in `global_controller.lua` or similar) — the full function body.
2. What are ALL the top-level fields on `runtime`? (e.g., `runtime.web`, `runtime.config`, `runtime.store`)
3. For each field that is a module/object, what module does it come from? Show the require/assignment. For example: `runtime.web.store` = `require("lib.lua.store")`, `runtime.web.request` = `ngx.req` wrapper, etc.
4. Are there nested objects beyond 2 levels that are commonly accessed? (e.g., `runtime.web.store.redis`, `runtime.config.services.model_prediction`)
5. Are there other parameter objects besides `runtime` that get passed around widely? (e.g., `context`, `bundle`, `wsapi_env`)

---

## 2. Lua HTTP Handler Wrapper (needed for HTTP abstraction resolver)

**Background:** From Round 1, we learned that application code never calls `resty.http` directly. Instead it calls `http_handler.post(url, params, headers, body)`. Our parser currently only detects raw `resty.http` usage, which is why we see 0 Lua HTTP calls. We need to build an abstraction resolver (similar to how we already handle `store.lua` wrapping `redis_helper.lua`) that recognizes `http_handler.get/post/put` as HTTP operations.

BOB said `http_handler.lua` wraps `socket.lua` which wraps `resty.http`. I need the exact API.

1. Show the full list of public methods on `http_handler` (e.g., `get`, `post`, `put`, `delete`, `request`). Just the function signatures, not the bodies.
2. What parameters does each method take? Specifically: does the URL parameter contain the unix socket path (like `"http://unix:/var/run/model_prediction.sock:/predict"`) or is the socket path separate?
3. How many files in the codebase call `http_handler.get()`, `http_handler.post()`, etc.? A count per method would be helpful.
4. Are there other HTTP wrapper modules besides `http_handler`? (e.g., does anything call `socket.get()` directly, bypassing `http_handler`?)

---

## 3. Container._sendRequest in JS (needed for JS HTTP detection fix)

**Background:** Our JS parser detects `sendRequest()` (bare function) and `Net._request()` as HTTP calls. From Round 1, we learned the actual pattern is `Container._sendRequest("POST", "/api/assess", ...)` — the `Container.` prefix means our callee-string matching misses it entirely. We need to know the exact and only call pattern so we can add it.

1. Where is `Container._sendRequest` defined? Show the function signature and the first few lines.
2. Is `Container` always a global object, or is it sometimes imported/required?
3. The callee string the parser sees would be `Container._sendRequest` — confirm this is the ONLY call pattern. Are there aliases like `C._sendRequest`, `self._sendRequest`, `window.Container._sendRequest`?
4. How many total `Container._sendRequest` calls exist across all JS files? (rough count)
5. Are there JS files that make HTTP calls through OTHER patterns (not Container._sendRequest)? Like direct XMLHttpRequest, fetch, or any other wrapper?

---

## 4. Go Redis Custom Methods (needed for Go Redis fix)

**Background:** Our Go Redis detector looks for standard `go-redis` method names (`Get`, `Set`, `HGet`) on variables containing "redisClient". From Round 1, we learned the Go code uses a custom `RedisClient` wrapper struct with non-standard method names like `HGetAsString`, `GetAsInt`, `HSetWithExpire`. These aren't in our lookup tables, so we detect 0 Go Redis accesses. We need the complete method list to add them.

1. Show the COMPLETE list of all public methods on the `RedisClient` struct. Just the method names and whether they read or write Redis.
2. What is the receiver variable name in the service code? Is it always `s.redisClient`, or sometimes `mps.redisClient`, `server.redis`, etc.?
3. Are there other structs/services besides the model_prediction service that use Redis? If so, what are their Redis field names?

---

## 5. Self:method() Resolution Context

**Background:** Our call resolver can't resolve `self:method()` calls because `self` isn't in the binding map (it's an implicit parameter in Lua's `:` syntax, not a `require`'d module). From Round 1, we learned `self:validate()` and `self:process_policy()` are extremely common (~25-30% of unresolved calls). If most `self:method()` calls target methods in the SAME file, we can resolve them by matching the method name against the file's own function definitions. If they target inherited methods (via metatable `__index`), we need the inheritance chain.

BOB showed `self:validate()`, `self:process_policy()`, `self:persist()` patterns.

1. When `self:validate()` is called inside `M:apply(runtime)`, is `self` always the same module table `M`? Or can it be a different object (like an instance created with `setmetatable`)?
2. Show 2-3 examples where `self:method()` calls a method defined in the SAME file. This is the easy case we can resolve.
3. Show 1-2 examples where `self:method()` calls a method defined in a PARENT class (via metatable `__index`). This is the harder case.
4. Roughly what percentage of `self:method()` calls are same-file vs inherited?

---

## 6. The `context` Object

**Background:** Besides `runtime`, BOB mentioned `context` as another widely-passed parameter object with method calls like `context:get_device_id()`. If `context` is a known module (like `runtime`), we can map its methods the same way. We need to know if it's a separate concept or just another view of `runtime`.

BOB mentioned `context:get_device_id()`, `context:get_session_id()` patterns.

1. Where is the `context` object defined/constructed? What module?
2. What methods does it expose? Show the list of public methods.
3. Is `context` the same as `runtime`, or a separate object? How are they related?
4. How many files call methods on `context`?

---

## 7. Dynamic Dispatch Chain (endpoint → handler)

**Background:** Our endpoint linker tries to match HTTP call URLs to nginx locations and their Lua handler files directly. From Round 1, we learned the real chain is 4 layers deep: nginx → `router/main.lua` → `global_controller.run()` → controller → handler. The controller name is extracted dynamically from the URL (`require(format("ato.controllers.%s", name))`). If there's a finite, enumerable set of controllers, we could build a static URL→controller→handler mapping even though the dispatch is dynamic.

BOB showed: nginx → `router/main.lua` → `global_controller.run()` → controller → handler.

1. In `router/main.lua`, how is the controller name extracted from the URL? Is it always `format("ato.controllers.%s", name)` or are there other patterns (e.g., `malware.controllers.%s`)?
2. Is there a fixed mapping of URL paths to controller names? Or is it purely dynamic (string extraction from URL)?
3. How many controllers exist? Can you list them with their file paths?
4. Do all controllers follow the exact same pattern (`M.run(wsapi_env)` → `global_controller.run(wsapi_env, component, handler_name)`)? Or are there variations?
