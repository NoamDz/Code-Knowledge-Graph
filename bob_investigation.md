# BOB Investigation Questions

These questions investigate why certain detections are failing in the Code Knowledge Graph. For each question, show concrete code examples (actual file paths and code snippets) from the codebase.

---

## 1. Lua HTTP Client Flow (0 HTTP calls detected, expected 20-30)

Trace how HTTP client calls are made in the Lua codebase:

1. How is `resty.http` (or whatever HTTP library) imported? Show the exact `require` line from 2-3 files that make HTTP calls.
2. How is the client object created? Is it `http.new()` directly, or wrapped in a helper function?
3. What variable name holds the client when `:connect()` or `:request_uri()` is called? Is it always `httpc`, or different names?
4. Is there a shared HTTP helper/utility module that wraps HTTP calls, similar to how `store.lua` wraps Redis? If so, show the wrapper function signatures and how callers invoke it.
5. Show 2-3 concrete examples of actual HTTP calls from different files — the full function that makes the call, with the require/import at the top.

---

## 2. JavaScript HTTP Communication (0 HTTP calls detected, expected 50+)

Investigate how JavaScript files communicate with the Lua backend:

1. Show 2-3 examples of actual HTTP calls from JS files. Are they using `sendRequest()`, `Net._request()`, `fetch()`, `$.ajax()`, or something else?
2. Is `sendRequest` called as a bare function like `sendRequest("POST", "/api/assess")`, or as a method like `this.sendRequest(...)` or `SomeModule.sendRequest(...)`?
3. How is `Net._request` actually called? Show the exact call syntax from 2-3 files.
4. Are there `.js.erb` files that make HTTP calls? If so, does the ERB templating interfere with the call pattern (e.g., is the URL constructed from Ruby variables)?
5. Are there any other HTTP patterns beyond sendRequest/Net._request that we might be missing?

---

## 3. Go Redis Client (0 Redis accesses detected, expected 10-30)

Investigate the Go Redis usage:

1. What is the Redis client variable called? Show the struct definition and field name (e.g., `redisClient`, `cache`, `db`, `rdb`).
2. Show 2-3 examples of actual Redis calls in Go code — the function that calls Redis with the full receiver chain (e.g., `s.redisClient.Get(ctx, key)` vs `s.cache.Get(key)` vs something else).
3. Is there an interface or abstraction layer between the code and Redis? (e.g., a `Cache` interface that wraps `go-redis`)
4. What method names are used? Are they standard `go-redis` methods (`Get`, `Set`, `HGet`) or custom wrapper methods (`GetAsString`, `GetJSON`, `FetchModel`)?

---

## 4. Truly Unresolved Lua Calls (22,744 unresolved — what are they?)

The call resolver can't match ~19,000 Lua calls. I need to understand the dominant patterns:

1. Show 3-5 examples of **method calls on local variables** — where a function receives an object (like `runtime`, `context`, `handler`) as a parameter and calls methods on it. This is the `runtime.web.store:get()` pattern.
2. How common is the `self:method()` pattern? Show 2-3 examples of Lua "classes" that use `self:` calls. What is the self variable — the module table, or an instance created with `setmetatable`?
3. When handlers are loaded via `pcall(require, format("handlers.%s", name))` and then `handler.run(runtime)` is called — what does `handler.run` look like in a typical handler file? Is `run` always the entry point, or are there other method names?
4. Are there calls like `parent.child.method()` — multi-level dot chains beyond 2 levels?

---

## 5. Collector Registration (detecting JS bundling)

Investigate the collector init.lua pattern:

1. Show 2-3 actual `init.lua` files from different collectors (e.g., device, behave). Do they all follow the same `local collector = { name = "...", js_files = {...}, endpoint = "..." }` pattern, or are there variations?
2. Is the table always assigned to a variable called `collector`, or different names?
3. Are the `js_files` always string literals, or sometimes constructed dynamically?
4. How many collector init.lua files exist in total?

---

## 6. Cross-Language Endpoint Mapping

Investigate the nginx location to handler mapping:

1. When a JS file calls `/api/assess` — what nginx location handles it, and what Lua file does that location point to (via `content_by_lua_file` or similar)?
2. The Lua files that handle HTTP endpoints — do they all follow a similar structure (e.g., they all define a function and call it, or they're all dispatched through a router)?
3. When Lua calls Go via unix socket — is it always through `resty.http`, or are there other mechanisms (like `ngx.socket.tcp`)?

---

## 7. Import Resolution Gaps

For the languages with low import resolution:

1. **Ruby (2.3% import resolution)**: Show 3 examples of `require` statements that fail to resolve. Are they all gem imports (external), or are some internal files that should resolve?
2. **Python (36.7%)**: Show 3 examples of unresolved Python imports. Are they third-party packages (redis, flask, watchdog) or internal modules?
3. **Go (0%)**: Confirm — are ALL Go imports either stdlib or external modules (github.com/...)? Or are there internal package imports that should resolve?
