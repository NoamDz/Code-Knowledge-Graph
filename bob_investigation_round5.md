# BOB Investigation — Round 5: Comprehensive Coverage Improvement

## Context

We're building a **Code Knowledge Graph** that parses a polyglot fraud detection platform (1234 files, 5 languages) with Tree-sitter and builds a semantic graph in Memgraph. After 4 rounds of BOB investigation and many improvements, here's our current state:

**Current coverage:**
- Import resolution: 84.9% (5,556/6,543)
- Call resolution: 46.2% (21,011/45,436) — 63.0% effective with builtins
- Redis (Lua): 1,125 accesses — Excellent
- HTTP calls: 21 total (Lua: 17, Go: 3, Python: 1)
- Graph writes: 70,939 edges across 17+ edge types

**Per-language gaps we're targeting:**

| Language | Key Gap | Current | Goal |
|----------|---------|---------|------|
| Lua | Unresolved calls (self:inherited, store vectors, parameter map) | 53.6% call res | ~60% |
| Ruby | 0 outgoing calls, 88 orphans, 12.8% call res | Broken metrics | Working metrics + edges |
| JS | 100% orphaned, 0 HTTP detection, no connection model | 0 edges between files | Global-sharing model |
| Python | Only 42/391 functions have calls, 0 Redis | 41.8% call res | ~55% + Redis detection |
| Go | 0 Redis, 5 orphans, no interface/embedding edges | 58.5% call res | Redis + new edge types |
| Cross-service | 4 endpoint links, 4 missions, missing IPC | Minimal | Complete service map |

---

## SECTION A: Ruby Deep Dive (151 files, 88 orphans, 0 outgoing calls)

**Background:** Our Ruby parser extracts 809 functions and 5,681 calls, but reports "0 functions with outgoing calls." This is likely a metric bug (name format mismatch between `ClassName#method` vs `method`). But Ruby also has 88 orphan files and only 12.8% call resolution. We need to understand Ruby's role and structure.

**A1.** Show the directory structure of all Ruby files in the codebase (first 2-3 levels, with file counts per directory).

**A2.** Categorize the 151 Ruby files by role:
- How many are **generator/preprocessor** scripts (build-time code generation)?
- How many are **standalone utility scripts** (invoked from CLI or shell)?
- How many are **library/helper modules** (imported by other Ruby files)?
- How many are **test files**?
- How many are **Rake tasks** or **config files** (Gemfile, Rakefile, etc.)?

**A3.** Show 10 representative `require` and `require_relative` statements from different Ruby files. For each:
- The exact string argument
- The actual file path the import should resolve to
- Whether it's a gem (external), stdlib, or internal project code

**A4.** Show all Ruby class inheritance chains (`class Foo < Bar`). For each:
- The child class and its file path
- The parent class and its file path
- Whether the parent is in the same file, another project file, or from a gem

**A5.** Show all `include` and `extend` statements in Ruby classes/modules. For each:
- What module is being included/extended?
- Is that module defined in the codebase or from a gem?

**A6.** For 10 of the 88 orphan Ruby files, show:
- The file path and what it does
- All its `require`/`require_relative` statements
- Whether any other Ruby file imports it
- Why it's disconnected (truly standalone? or should it be connected?)

**A7.** Are any orphan Ruby files invoked by shell scripts, Docker commands, cron jobs, or Makefiles? Show examples.

**A8.** Do Ruby files communicate with other parts of the system via mechanisms other than require? (Writing files that Lua reads, HTTP calls, Redis access, shell commands)

---

## SECTION B: JavaScript Connection Model (94 files, 100% orphaned)

**Background:** JS files are browser IIFEs sharing globals via `window.Container`, `window.Net`, etc. Our import-based model finds zero connections. We need to understand the global-sharing model and Ruby build system to create edges.

**B1.** Show the final HTML output that loads JavaScript in the browser:
- A single `<script>` tag with all JS concatenated?
- Multiple `<script>` tags in order?
- A `<script src="bundle.js">` loading a pre-built bundle?
Show the actual HTML/ERB template that produces the script tags.

**B2.** When the Ruby generator runs, what is the **output file** it produces? For example, does `container.js.erb` processing produce `build/output/container.js`? Show the actual output path and format.

**B3.** For each of these major JS files, show what global variable(s) they **define** (assign to `window.*`):
- `net.js` (or wherever Net is defined)
- `container.js.erb`
- `device.js` or wherever DeviceContainer is defined
- `behave.js` or wherever Behave is defined
- Any other files that define major globals

For each, show the exact line like `window.Container = Container;`

**B4.** For each global from B3, list which other JS files **consume** (reference) that global. For example:
- Files that call `Container._sendRequest(...)` — which files?
- Files that reference `Net._request(...)` — which files?

**B5.** Is there a **dependency hierarchy** among the globals?
- Does `Container` depend on `Net`?
- Do collectors depend on `Container`?
- Is there a clear layering: `Net` → `Container` → collectors?

**B6.** Show 3 concrete `Container._sendRequest` calls from actual `.js.erb` files with **full surrounding context** (5 lines before and after). We need to see:
- Is the URL a string literal or an ERB template?
- Is the call inside an IIFE, a named function, or at top level?

**B7.** Are there JS→backend communication patterns other than `Container._sendRequest`?
- Image pixel tracking (`new Image().src = "/track?..."`)
- WebSocket connections
- Beacon API (`navigator.sendBeacon(...)`)
- Form submissions

**B8.** When the Ruby generator assembles the JS bundle, what **order** are files included in? Show the sequence for one concrete bundle.

**B9.** Are all 94 JS files in **one bundle**, or multiple bundles? How many bundles, and which files go into each?

**B10.** List ALL directories containing `.js` or `.js.erb` files with file counts per directory.

**B11.** Categorize the 94 JS files into:
- **Core infrastructure** (Net, Container, crypto, encoding)
- **Collector implementations** (device, behave, browser, etc.)
- **Handler UI** (policy, session_result, etc.)
- **Templates** (included into other files via ERB render)
- **Other**

---

## SECTION C: Lua Call Resolution — Closing the Gap (13,414 unresolved)

**Background:** Lua call resolution is 53.6% (15,485/28,899). After builtin classification, ~5,100-6,400 are truly unresolved. Three specific fixes could push this to ~60%: (1) self:inherited() calls, (2) store vector CALLS edges, (3) more parameter mappings.

**C1.** What are the **20 most common callee strings** across all Lua files that are NOT:
- Lua builtins (`print`, `pairs`, `ipairs`, `type`, `tonumber`, `tostring`, `error`, `assert`, `next`, `setmetatable`, `pcall`, `xpcall`, `select`, `unpack`)
- Lua stdlib (`string.*`, `table.*`, `math.*`, `os.*`, `io.*`)
- OpenResty (`ngx.*`)
- External (`cjson.*`, `resty.*`, `cmsgpack.*`)
- Already resolved via require (calls on variables with `require()` bindings)
- Parameter resolver (`bundle`, `store`, `web`)

For each, show: callee string, approximate count, and an example file.

**C2.** Show the **constructor/new method** of the Store module from `src/lib/lua/store.lua`:
```lua
function Store:new(...)
    local instance = {
        -- SHOW ALL FIELDS SET HERE
    }
end
```
We need: `self.assess_vector`, `self.collect_vector`, `self.session_vector`, `self.user_vector`, and any other sub-objects.

**C3.** What module is `store_vector`? (the type of assess_vector, collect_vector, etc.)
- File path?
- Full list of public methods?

**C4.** For `src/common/base/lua/handler.lua` — show ALL method names defined on the module table (just signatures, not bodies).

**C5.** For `src/common/base/lua/assessor.lua` — show ALL method names.

**C6.** For `src/common/base/lua/collector.lua` — show ALL method names.

**C7.** Are there other base modules beyond handler, assessor, collector? (Round 4 mentioned `actor.lua`) If so, show their methods too.

**C8.** Show 3 concrete examples of a child module calling `self:method()` where the method is defined ONLY in the base class (not overridden in the child). Include file path and line.

**C9.** For each base module, approximately how many child modules inherit from it?

**C10.** Inside actor modules (`src/ato/actors/*/init.lua`), what parameters do main functions receive? Show 5 actor entry-point signatures.

**C11.** Inside task modules (`src/ato/tasks/*.lua`), what parameters do main functions receive? Show 5 task entry-point signatures.

**C12.** How common is this sub-object aliasing pattern?
```lua
local av = store.assess_vector
av:get("some_key")
```
Show 3 files that do this, or confirm it's rare.

**C13.** Is there a common pattern where modules are loaded into a table and iterated?
```lua
local assessors = {require_version("ato.assessors.device_id"), ...}
for _, assessor in ipairs(assessors) do assessor:assess(bundle, store) end
```
How common is this pattern?

**C14.** In a handler like `src/ato/handlers/policy/init.lua`, how does it invoke assessors? Direct require+call, list iteration, or dispatch function?

---

## SECTION D: Python Gaps (42/391 functions with calls, 0 Redis)

**Background:** Our Python parser extracts calls, but only 42/391 functions show outgoing call edges. The call resolver can't handle `self.method()` calls (Lua-specific self-resolution doesn't fire for Python). Also, 0 Redis detected despite redis-py being imported.

**D1.** Pick 5 Python functions that have actual code (not just `pass`/`return`). Show:
- File path and function name
- Function body (first 10-15 lines)
- What function calls appear inside

**D2.** Pick 3 Python class methods that call `self.other_method()` or `self.attribute.method()`. Show the call pattern.

**D3.** Show ALL Python files that import `redis` (any form). For each, show:
- The exact import statement
- How the Redis client is created (direct, cluster, from_url, pool?)
- 2-3 actual Redis operation calls with variable names

**D4.** Do any Python files use a Redis wrapper class? If so, show the class definition.

**D5.** Show ALL unique decorator patterns in the Python codebase:
- `@app.route("/path")`, `@staticmethod`, custom decorators
- For each: one example file/line and what it means semantically

**D6.** Do Python files use Tornado route decorators? List all routes with decorator and file path.

**D7.** How many Python functions are trivially simple (just `pass`, `return value`, property getters)?

---

## SECTION E: Go Gaps (0 Redis, interface/embedding edges)

**Background:** Go Redis resolver has correct indicator patterns (`redisClient`, `RedisClient`) and method lists (`HGetAsString`, `GetAsInt`, etc.) but detects 0. We suspect `.Result()` chaining changes the callee string.

**E1.** Show 5 actual Go Redis calls with EXACT syntax:
- File path and line number
- Full call expression (e.g., `mps.redisClient.HGetAsString(ctx, key, field)`)
- Any chaining (`.Result()` at the end)

**E2.** CRITICAL: Does Go code chain `.Result()` on Redis calls?
```go
val, err := mps.redisClient.HGet(ctx, key, field).Result()
```
Show 3 examples with and without `.Result()` chaining.

**E3.** Show ALL interface definitions in the Go codebase:
- Interface name and file path
- Method signatures
- What concrete types implement it

**E4.** Show ALL struct embeddings in Go:
- The embedding struct (e.g., `type Server struct { *BaseServer; ... }`)
- The embedded type
- What methods get promoted

**E5.** What are the 5 orphan Go files? For each:
- File path, package declaration
- First 10 lines of imports
- Is it a test file? Main file? Utility?

---

## SECTION F: Cross-Service Communication (Missing IPC, 4/74 missions)

**Background:** We detect Lua Redis (1,125), some HTTP (21), and 4 mission dispatches. But the system has extensive IPC we're missing: Unix sockets, Redis pub/sub, SQS, Kinesis, MySQL, Cassandra, shared config.

**F1.** List ALL mechanisms by which services communicate. For each:
- Mechanism (HTTP, Redis, Unix socket, SQS, file-based, etc.)
- Sender → receiver
- 1-2 concrete code examples (file path + relevant lines)
- Approximate number of call sites

**F2.** Show ALL Unix socket paths referenced anywhere in the codebase:
- Exact socket file paths
- Which service creates/listens on the socket
- Which service connects to it
- Protocol used over the socket

**F3.** Redis key namespace map (CRITICAL for cross-service data flow). For ALL Redis key prefixes/patterns:
- Key format (e.g., `store:{session_id}`, `bundle:{app_id}`)
- What data it stores
- Which language/service WRITES it
- Which language/service READS it
- Approximate TTL

**F4.** For EACH database technology (Redis, MySQL, Cassandra, S3/MinIO, SQS, Kinesis), create a matrix:
- Which languages/services access it
- Client library in each language
- 2-3 example operations per language

**F5.** The mission system: we detect only 4 of 74 `missioner.add_mission()` calls. Show 5 concrete examples of `missioner.add_mission()` calls with full context (3 lines before/after):
- What file is the call in?
- What's the first argument (task name)?
- Is it the string `"missioner"` module name, or renamed?

**F6.** List ALL configuration files read by more than one language/service:
- File path
- Which languages read it (with the code that loads it)
- What configuration it contains

**F7.** For the full request lifecycle of a fraud assessment (user login), trace EVERY service hop:
1. Browser JS → HTTP POST → which nginx location?
2. Nginx → which Lua entry file?
3. Lua handler → assessors?
4. Each assessor → external calls? (Redis, HTTP, Unix socket)
5. Mission created → queue → poller → callback?
6. Results stored where?

**F8.** List ALL cron jobs with schedules, shell scripts, and Lua/Python scripts they invoke.

**F9.** Show ALL nginx `location` blocks. For each:
- Location pattern
- What it does (proxy_pass, content_by_lua_file, static files, redirect)
- Target (Lua file, upstream, file path)

**F10.** Show ALL nginx `upstream` blocks:
- Upstream name
- Server addresses (including Unix sockets)
- Which locations reference it

---

## Summary: What Each Section Enables

| Section | Enables | Expected Impact |
|---------|---------|-----------------|
| A (Ruby) | Fix Ruby call metrics, reduce 88 orphans, understand connection model | Ruby becomes queryable |
| B (JS) | Build global-sharing dependency model, fix HTTP detection, connect 94 orphans | JS files connected |
| C (Lua) | Fix self:inherited, store vector CALLS, expand parameter map | +975-1,875 resolved calls |
| D (Python) | Fix self.method() resolution, add Redis detection, decorator edges | Python call res ~55% |
| E (Go) | Fix Redis detection, add interface/embedding edges | Go fully covered |
| F (Cross-service) | Complete IPC map, service topology, shared data edges | 130+ new cross-service edges |
