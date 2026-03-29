# How the Code Knowledge Graph is Built

**Codebase:** Pinpoint fraud detection platform (1234 files, 5 languages)
**Last updated:** 2026-03-29

---

## Pipeline Overview

```
Source Files (1234)
    │
    ▼
FileScanner ──── scan repo, filter by extension/ignore patterns
    │
    ▼
Language Parsers (5) ──── Tree-sitter AST extraction → FileAST objects
    │
    ▼
Import Resolvers (5) ──── require/import string → file path
    │
    ▼
CallResolver ──── binding map + 9 strategies → resolved function calls
    │
    ▼
Specialized Resolvers (10) ──── Redis, parameters, inheritance, builtins, endpoints, missions, dynamic, JS ERB, cross-service IPC
    │
    ▼
GraphWriter ──── batched Cypher MERGE → Memgraph
    │
    ▼
Memgraph (17 node types, 23+ edge types, ~71,000 edges)
```

---

## Stage 1: Scanning

`FileScanner` walks the repo and collects files by extension:
- `.lua` → 820 files (core fraud detection logic, OpenResty handlers)
- `.rb` → 151 files (Ruby generators, preprocessors, event uploaders)
- `.py` → 96 files (Python services: missioner, poller, aggregator, atlas, geo, global_data)
- `.js` / `.js.erb` → 94 files (browser collectors for device fingerprinting, behavior tracking)
- `.go` → 73 files (Go model prediction service)
- `nginx.conf` → parsed separately for endpoint/phase mapping

Directories matching `ignore_patterns` from config.yml are skipped (e.g., `node_modules/`, `vendor/`, `.git/`).

---

## Stage 2: Parsing (Tree-sitter AST Extraction)

Each language has a dedicated parser that returns a `FileAST` — a language-agnostic data model containing:

| Field | Type | What it captures |
|-------|------|-----------------|
| `functions` | `list[FunctionDef]` | All function/method definitions with name, params, visibility, decorators |
| `classes` | `list[ClassDef]` | Class/struct/interface definitions with inheritance, methods, mixins |
| `imports` | `list[ImportRef]` | require/import statements with module string, local binding, dynamic flag |
| `calls` | `list[CallRef]` | All function calls with callee string, caller function, line number |
| `exports` | `list[str]` | Exported symbols |
| `redis_accesses` | `list[RedisKeyAccess]` | Detected Redis operations (key, operation, read/write) |
| `http_calls` | `list[HttpCallRef]` | HTTP client calls (url, method) |
| `mission_dispatches` | `list[MissionDispatch]` | missioner.add_mission() calls (task name, queue) |
| `db_accesses` | `list[DatabaseAccess]` | MySQL/Cassandra operations |
| `aws_accesses` | `list[AwsServiceAccess]` | SQS/Kinesis/S3 operations |
| `ctx_accesses` | `list[ContextAccess]` | ngx.ctx field reads/writes (Lua only) |
| `shared_dict_accesses` | `list[SharedDictAccess]` | ngx.shared dict operations (Lua only) |
| `metatable_parents` | `dict[str, str]` | setmetatable inheritance (Lua only) |
| `local_aliases` | `list[tuple[str, str]]` | Local aliases of stdlib functions (Lua only) |
| `module_info` | `ModuleInfo` | Module return pattern (Lua only) |

### What each parser extracts specifically for this codebase:

### Lua Parser (820 files)
- **`require_version()` tracking** — 90% of the codebase uses `require_version()` instead of `require()`. Parser treats both identically via `_REQUIRE_FUNCTIONS = {"require", "require_version"}`.
- **Module pattern detection** — identifies how each file exports its module table: `local M = {}; return M` (592 files), named tables (186), side-effect modules (17), direct returns (14).
- **OpenResty-specific extraction:**
  - `ngx.ctx.field` reads/writes (296 detected) — per-request context passing between phases
  - `ngx.shared.DICT` operations (41 detected) — shared memory dict access
  - `ngx.exec` / `ngx.redirect` internal redirects
  - `pcall`-wrapped calls flagged for error handling analysis
- **Redis abstraction detection** — identifies calls on bindings to known Redis modules (`redis_helper`, `store`, `store_vector`)
- **HTTP call detection** — identifies `http_handler.get/post/put` calls (17 detected)
- **Mission dispatch detection** — identifies `missioner.add_mission("task_name", ...)` calls
- **Metatable inheritance tracking** — `setmetatable(Child, {__index = Parent})` creates parent links
- **Local alias extraction** — `local format = string.format` creates alias entries for builtin classification

### Python Parser (96 files)
- **Class hierarchy extraction** — class definitions with parent classes (98 classes)
- **Decorator extraction** — `@classmethod`, `@staticmethod`, `@run_on_executor`, `@tornado.gen.coroutine`
- **Redis detection** — tracks `RedisCluster` / `StrictRedisCluster` factories and `self.connection` attribute assignments (1 file: geo.py)
- **Tornado route extraction** — detects `tornado.web.Application(handlers=[("/path", Handler)])` tuples (3 services: missioner, atlas, global_data)
- **MySQL detection** — tracks `mysql.connector` imports and `cursor.execute()` calls

### Go Parser (73 files)
- **Package/import extraction** — Go module paths with stdlib classification
- **Struct and interface parsing** — 141 classes total, with `is_interface` flag to distinguish interfaces from structs
- **Method receiver extraction** — `func (r *RedisClient) HGet(...)` tracks which struct owns each method
- **HTTP handler detection** — `http.HandleFunc` and mux patterns (3 handlers)
- **Unix socket listener detection** — `net.Listen("unix", path)` patterns
- **Redis client detection** — tracks `redisClient`, `r.client` field access patterns for go-redis operations
- **MySQL client detection** — tracks `mysqlClient` field access patterns

### Ruby Parser (151 files)
- **require/require_relative extraction** — with `./` prefix convention for generator infrastructure
- **Class inheritance and mixins** — 91 classes, 6 inheritance chains, `include Singleton`, `include ErbMethods`
- **Module name derivation** — sets `module_name` from primary class/module declaration
- **Redis detection** — tracks `Redis.new()`, `@redis` instance variables, and operation methods (17 detected across 5 files)
- **Dynamic loading patterns** — `Dir.glob("preprocess/*.rb")` and `class_eval(IO.read(entry))` for preprocessor convention

### JavaScript Parser (94 files)
- **ERB stripping** — removes `<%...%>`, `<%=...%>`, `<%-...%>` tags before Tree-sitter parsing, allowing JS inside `.js.erb` templates to be parsed
- **IIFE/revealing module pattern detection** — `var Container = (function(){...})()` as exports
- **Global export detection** — `window.X = value` assignments
- **HTTP call detection** — `Container._sendRequest(type, url, ...)` with dynamic URL placeholder support, plus `Container._collect()` and `Container._collectImmediateWithType()` data exfiltration calls (45 HTTP calls detected)
- **CommonJS/ESM import detection** — `require()` and `import` (only 3 exist — JS files are browser IIFEs, not Node.js)

### Nginx Parser
- **Location blocks** — 24 locations with path/modifier, Lua phase directives, proxy_pass targets
- **Lua phases** — `*_by_lua_file` and `*_by_lua_block` directives (13 location phases, 4 global phases)
- **lua_package_path** — 24 template patterns for mapping `require()` strings to file paths
- **Proxy pass** — 2 locations with upstream/service targets
- **Shared dicts** — 26 `lua_shared_dict` declarations
- **Include chain** — 8 included config files, parsed recursively

---

## Stage 3: Import Resolution

Each language has a resolver that maps import strings to file paths.

### Lua Resolver (93.9% resolution — 4,953/5,276)
- Builds a module index from `lua_package_path` templates (29 templates from nginx.conf + config)
- Maps `require("ato.handlers.policy")` → `src/ato/handlers/policy/init.lua`
- Handles `require_version()` identically to `require()`
- 323 unresolved are mostly `resty.*` OpenResty library modules (not in the repo — external)

### Python Resolver (36.7% resolution — 150/409)
- Converts file paths to module names: `foo/bar/baz.py` → `foo.bar.baz`
- Resolves relative imports using `from_file` context
- Same-directory bare-name imports: `import helpers` in same dir as `helpers.py`
- 259 unresolved are mostly third-party packages (redis, tornado, pandas, boto3) — correct behavior

### Go Resolver (60.2% resolution — 308/512)
- Suffix-matching on import paths: `"pinpoint/model_prediction/server/models"` → directory match
- `GO_STDLIB_PACKAGES` frozenset (47 packages) for stdlib classification → returns `"__go_stdlib__"` sentinel
- Same-package edges: all `.go` files in same directory get `SAME_PACKAGE` edges (245 edges)

### Ruby Resolver (42.3% resolution — 145/343)
- `require_relative` resolved relative to importing file
- `_RUBY_STDLIB` set (~40 modules: erb, fileutils, json, yaml, etc.) → returns `"__ruby_stdlib__"` sentinel
- `require("./generator/templates.rb")` resolved from execution directory
- Dynamic loading: `Dir.glob("preprocess/*.rb")` creates `LOADS_DYNAMICALLY` edges (63 preprocessors connected)
- `class_eval(IO.read(entry))` detected for task file loading

### JavaScript Resolver (0% standard import resolution — 0/3)
- Only 3 JS files have `require()` calls — the IIFE architecture doesn't use imports
- **JS ERB Resolver** (separate) handles the actual connection model — see Stage 4

---

## Stage 4: Call Resolution and Specialized Resolvers

After imports are resolved, 10 specialized resolvers run in sequence:

### 4a. CallResolver — Cross-file function call resolution
**Result: 50.9% (23,139/45,436)**

Builds a global symbol table mapping `module.function` → file path, then resolves calls using 9 strategies:

1. **Binding map** — `local helpers = require("ato.helpers"); helpers.get_device()` → resolved via binding
2. **Self-calls (Lua)** — `self:method()` resolved to current file if method exists locally; falls through to base inheritance if not
3. **Self-calls (Python)** — `self.method()` resolved to same-file function (added specifically for this codebase)
4. **Same-file** — unqualified `helper_func()` matched against functions in same file
5. **Class hierarchy (BFS)** — method calls resolved through parent class chain
6. **Type-inferred** — `obj = ClassName()` followed by `obj.method()` → resolved to class
7. **Unqualified global** — bare function name looked up in global symbol table
8. **Qualified names** — dotted names looked up in qualified symbol table
9. **Class methods** — direct method resolution via class method sets

### 4b. Redis Abstraction Resolver
**Result: 1,000 Redis accesses (Lua: 982 via abstractions, Go: 39, Ruby: 17, Python: 1)**

Understands the Redis wrapper chain in this codebase:
```
Application code
    → store.assess_vector:get("key")        # StoreVector wrapper
    → store:hget(full_key)                   # Store wrapper
    → redis_helper:hget(hash_name, key)      # RedisHelper wrapper
    → rediscluster:hget(key)                 # Actual Redis call via Glider
```

**4 detection passes for Lua:**
1. **Direct calls** — callee bound to redis_helper/store module → check method against read/write sets
2. **Chained vector** — `store.assess_vector:get()` → StoreVector methods (`get`, `getall`, `set`, `set_sparse_safe`, `setall`, `incr`)
3. **Deep chain** — multi-level access through store → redis_helper chain
4. **Unbound variables** — heuristic matching on variable names containing "redis"

**Go Redis detection:** Matches `r.client.HGet(...)` pattern using `_GO_REDIS_INDICATORS` (redisClient, RedisClient, client) + method sets for both wrapper methods (HGetAsString, GetAsInt, etc.) and standard go-redis methods (HGet, Get, Set, HSet, etc.)

**Ruby Redis detection:** Tracks `Redis.new()` construction, `@redis` instance variables, and operation method calls.

**Python Redis detection:** Tracks `RedisCluster` factory construction and `self.connection` attribute assignments.

### 4c. Parameter Name → Module Resolver
**Result: 1,617 additional calls resolved**

Maps well-known parameter names to their module types:

| Parameter | Module | Why |
|-----------|--------|-----|
| `bundle` | `lib.lua.bundle` | Configuration bundle passed to all handlers/assessors/actors |
| `web` | `lib.lua.store` | Web container (contains store) |
| `store` | `lib.lua.store` | Session store passed directly |
| `store_object` | `lib.lua.store` | Store passed to actors with this name |

**Chain resolution** for nested field access:
- `store.assess_vector:get("key")` → resolves `store` to Store, then `assess_vector` to StoreVector via `FIELD_TYPE_MAP`
- `web.store.collect_vector:set("key", val)` → resolves through 3-level chain

### 4d. Base Inheritance Resolver
**Result: 28 additional calls resolved**

Handles Lua's metatable-based inheritance. When `self:validate()` is called in a handler but `validate` is NOT defined in that file, checks if it's inherited from a base class:

| Base Module | Methods | Children |
|------------|---------|----------|
| `common.base.lua.handler` | validate, response_map, add_handler_error, check_mark_store_save_async, user_error, parse_postdata, dispatch, handle_web_request, handle_ep_request, handle_pmc, handle_tma, handle_internal_request, add_error_metrics, parse_api_version_data, verify_store_size_limit, add_general_handler_error, create_handler, sanitize_error_output, user_error_format, create_handler_event | ~30 handlers |
| `common.base.lua.collector` | trigger, collect, get_trigger_collector, trigger_web_request, get_collect_collector, decrypt_collect_data, collect_web_request, fake_collect_web_request, get_store | ~40 collectors |
| `common.base.lua.assessor` | assess | ~33 assessors |
| `common.base.lua.actor` | act | ~23 actors |

### 4e. Builtin Classifier
**Result: 8,503 builtins + 185 external classified → 70.0% effective coverage**

Classifies unresolved calls into 3 buckets:
- **Builtin** — language stdlib functions (string.format, table.insert, print, pairs, ngx.*, etc.)
- **External** — third-party library calls (cjson.encode, resty.*, cmsgpack.*, etc.)
- **Truly unresolved** — genuine unknowns (13,609 remaining)

**Per-file Lua alias maps** — detects `local format = string.format` patterns and reclassifies bare `format()` calls as builtins. This was the single biggest improvement (+902 builtins, +177 external).

### 4f. Endpoint Linker
**Result: 8 cross-language endpoint links + 8 controller routes**

Links HTTP client calls to their server-side handlers:

1. **Nginx location matching** — longest-prefix match of call URL against 24 nginx locations
2. **Go socket handler matching** — maps unix socket URLs to Go HTTP handlers
3. **Internal endpoint mapping** — 6 BOB-confirmed internal endpoints:
   - `/tasks` (Python poller → Lua task controller)
   - `/missions` (Python missioner → Lua)
   - `/get_bundle` (Go model_prediction → Lua bundle API)
   - `/monitor`, `/status`, `/events`
4. **Controller route matching** — URL pattern → controller file mapping (8 routes for 6 controllers: ato 3, common 2, malware 1)

### 4g. Mission Dispatch Resolver
**Result: 6 dispatches detected, 4 resolved to files**

Two-phase detection:
1. **Phase 1** — scans CallRef objects for `missioner.add_mission` and `missioner_timer.post` patterns, also checks binding map for missioner module imports
2. **Phase 2** — maps task names to files: `"pts_run"` → searches `tasks/pts_run.lua` across `src/ato/tasks/`, `src/common/tasks/`, `src/malware/tasks/`

### 4h. Dynamic Prefix Resolver
**Result: POTENTIAL_IMPORT edges for 76 dynamic requires**

Expands `require(string.format("handlers.%s", name))` patterns:
- Extracts the static prefix `"handlers."` from the format string
- Finds all module files whose names start with `"handlers."`
- Creates `POTENTIAL_IMPORT` edges to each possible target

### 4i. JS ERB Render-Chain Resolver
**Result: 49 render includes + 56 collector loop includes = 105 INCLUDES edges**

The JS architecture is a single IIFE assembled at build time by Ruby ERB templates:
```javascript
(function(){
  <%=env["template"].render("base64.js", env)%>    // Layer 1: Utilities
  <%=env["template"].render("net.js.erb", env)%>    // Layer 2: Network
  var Container = (function(){...})();               // Layer 3: Container
  <% env['collectors_rendered'].each { |code| %>     // Layer 4: Collectors
    <%=code%>
  <% } %>
  Container._setup();
})();
```

The resolver reads raw `.js.erb` files (before ERB stripping) and extracts:
1. **Explicit renders** — `env["template"].render("filename.js.erb", env)` → INCLUDES edge
2. **Collector loop** — `env['collectors_rendered'].each` → INCLUDES edges to all collector entry-point templates

### 4j. Cross-Service IPC Resolver
**Result: 9 socket edges, 8 Redis patterns, 54 DB accesses, 16 AWS accesses, 5 config edges**

Detects inter-process communication across the polyglot architecture:

**Unix Sockets (9 edges across 6 sockets):**
| Socket | Listener | Connector | Protocol |
|--------|----------|-----------|----------|
| glider.sock | Redis Glider (external) | All Lua services | Redis protocol |
| missioner.sock | Python missioner | Lua (missioner client) | HTTP |
| prediction_tcp_router.sock | Go model_prediction | Lua (socket client) | Custom JSON |
| global_data.sock | Python global_data | Lua (HTTP client) | HTTP |
| atlas.sock | Python atlas | Lua (geoip utils) | HTTP |
| cassandra_communicator.sock | Lua cassandra_comm | Lua (cassandra client) | Custom |

**Shared Redis Key Patterns (8 cross-language edges):**
| Key Pattern | Writer | Reader |
|------------|--------|--------|
| `store:{session_id}` | Lua | Go |
| `bundles` | Ruby | Lua |
| `bundle:{business}:{app}` | Ruby | Lua |
| `model_prediction:{session_id}` | Go | Lua |
| `model_prediction_tasks:{session_id}` | Lua | Go |

**Database Access (54 edges):**
- MySQL: 14 accesses (Lua via `lib.lua.mysql`, Python via `mysql.connector`, Ruby via `sequel`, Go via `db.MysqlClient`)
- Cassandra: 40 accesses (Lua via cassandra communicator client)

**AWS Services (16 edges):**
- SQS: 4 (Python aggregator/poller — produce and consume)
- S3: 10 (Ruby generator + multi_events_uploader)
- Kinesis Firehose: 2 (Go model_prediction + Ruby event uploader)

**Shared Config Files (5 edges):**
- `config.json` — read by Lua, Python, Go, Ruby
- `model_prediction_service.json` — read by Lua client + Go service
- `features.json` — read by Lua + Ruby

---

## Stage 5: Graph Ingestion (Memgraph)

`GraphWriter` translates all FileAST data into Memgraph nodes and edges via batched Cypher MERGE statements.

### Node Types (17)

| Node Type | Count | Description |
|-----------|-------|-------------|
| File | 1,234 | Source files across 5 languages |
| Function | 7,822 | Functions/methods (5,641 public) |
| Class | 330 | Classes/structs/interfaces (141 Go, 98 Python, 91 Ruby) |
| Endpoint | 24+ | nginx locations + Python Tornado routes |
| NginxPhase | 13 | Lua phase handlers (access_by_lua, content_by_lua, etc.) |
| ContextKey | ~296 | ngx.ctx field names |
| SharedDict | ~26 | ngx.shared dict names |
| RedisKey | ~1,000 | Redis key access points |
| Service | 2 | proxy_pass targets |
| UnixSocket | 6 | Unix domain sockets |
| SharedRedisPattern | 5 | Cross-language Redis key patterns |
| ConfigFile | 3 | Shared config files |
| DatabaseTable | ~14 | MySQL/Cassandra tables |
| SQSQueue | ~2 | SQS queue endpoints |
| KinesisStream | ~1 | Kinesis Firehose stream |

### Edge Types (23+)

| Edge Type | Description | Count/Notes |
|-----------|-------------|-------------|
| DEFINES | File → Function/Class | All files |
| IMPORTS | File → File (resolved imports) | 5,556 |
| CALLS (resolved) | Function → Function | 23,139 |
| CALLS (unresolved) | Function → callee string | 13,609 truly unresolved |
| SAME_PACKAGE | Go file → Go file | 245 |
| HAS_PHASE | Endpoint → NginxPhase | 13 |
| HANDLES | NginxPhase → File | Lua files per phase |
| PROXIES_TO | Endpoint → Service | 2 |
| HTTP_CALLS | Function → Endpoint | 70 |
| REDIS_READS/WRITES | Function → RedisKey | ~1,000 |
| CTX_READS/WRITES | Function → ContextKey | 296 |
| USES_SHARED | Function → SharedDict | 41 |
| DISPATCHES | File → File (mission dispatch) | 6 detected |
| POTENTIAL_IMPORT | File → File (dynamic require) | 76 patterns |
| INCLUDES | File → File (JS ERB render) | 105 |
| EXTENDS | Class → Class (inheritance) | Per language |
| IMPLEMENTS | Struct → Interface (Go) | ~7-10 |
| SOCKET_LISTENS/CONNECTS | File → UnixSocket | 9 |
| WRITES/READS_REDIS_PATTERN | File → SharedRedisPattern | 8 |
| QUERIES_DB | Function → DatabaseTable | 14 MySQL |
| QUERIES_CASSANDRA | Function → string | 40 |
| PRODUCES_TO/CONSUMES_FROM | File → SQSQueue | 4 |
| STREAMS_TO | File → KinesisStream | 2 |
| ACCESSES_S3 | File → string | 10 |
| READS_CONFIG | File → ConfigFile | 5 |
| LOADS_DYNAMICALLY | File → File (Ruby) | ~65 |

### Total: ~71,238 graph writes

---

## What Was Built Specifically for This Codebase

Everything below was custom-built based on investigating the actual Pinpoint codebase through 6 rounds of BOB (codebase expert) investigation:

### Lua/OpenResty Specific
1. `require_version()` support — custom require wrapper used by 90% of the codebase
2. Module pattern detection — 8 different patterns for how Lua modules export their tables
3. Redis abstraction chain — store → store_vector → redis_helper → rediscluster
4. Store vector factory tracking — `assess_vector`, `collect_vector` as typed sub-objects
5. Parameter name → module mapping — `bundle`, `web`, `store`, `store_object`
6. Base class inheritance — handler/assessor/collector/actor metatable patterns
7. `http_handler.get/post/put` detection — custom HTTP wrapper
8. ngx.ctx/ngx.shared tracking — OpenResty-specific context sharing
9. Mission dispatch detection — `missioner.add_mission()` → task file mapping
10. Local alias classification — `local format = string.format` pattern
11. Dynamic prefix expansion — `require(format("handlers.%s", name))` → POTENTIAL_IMPORT

### JavaScript Specific
12. ERB stripping for Tree-sitter parsing — removes Ruby template tags
13. ERB render-chain resolver — `env["template"].render()` → INCLUDES edges
14. Collector loop detection — `collectors_rendered.each` → entry point templates
15. `Container._sendRequest` detection with dynamic URL placeholders
16. `Container._collect` / `_collectImmediateWithType` as data exfiltration calls

### Go Specific
17. Same-package edges — all Go files in same directory linked
18. Go stdlib classification — 47 stdlib packages
19. Go Redis with `.Result()`/`.Err()` chaining — `r.client.HGet(ctx, key).Result()`
20. Interface IMPLEMENTS edges via structural typing (method set comparison)
21. `mysqlClient` field access pattern detection

### Python Specific
22. `self.method()` resolution for Python (separate from Lua self-handling)
23. `RedisCluster` / `StrictRedisCluster` factory detection with `self.connection` attribute tracking
24. Tornado route detection — `tornado.web.Application(handlers=[...])` tuple parsing
25. Same-directory bare-name import resolution

### Ruby Specific
26. Ruby stdlib classification (~40 modules)
27. `require("./relative/path")` convention for generator infrastructure
28. Preprocessor loading convention — `Dir.glob("preprocess/*.rb")` → LOADS_DYNAMICALLY edges
29. `class_eval(IO.read(entry))` → dynamic task loading
30. Ruby Redis detection — `Redis.new()`, `@redis`, operation methods
31. Module name derivation from class/module declarations

### Cross-Service Specific
32. Unix socket inventory — 6 sockets mapped between services
33. Shared Redis key patterns — 5 cross-language data flow patterns
34. MySQL detection across 4 languages
35. Cassandra detection through communicator proxy
36. SQS queue detection (Python boto3)
37. Kinesis Firehose detection (Go + Ruby)
38. S3 access detection (Ruby aws-sdk)
39. Shared config file edges (config.json, features.json, model_prediction_service.json)
40. Nginx internal endpoint mapping (6 endpoints)
41. Controller route mapping (6 controllers, 8 routes)

### Nginx Specific
42. Recursive include parsing
43. Lua phase directive extraction (`*_by_lua_file`, `*_by_lua_block`)
44. lua_package_path template extraction (29 templates)
45. Location → handler chain linking

---

## Current Coverage Summary

| Metric | Value |
|--------|-------|
| Files parsed | 1,234/1,234 (100%, 0 errors) |
| Import resolution | 84.9% (5,556/6,543) |
| Call resolution | 50.9% (23,139/45,436) |
| Effective coverage | 70.0% (resolved + builtin + external) |
| Redis accesses | 1,000 (Lua: 982, Go: 39, Ruby: 17, Python: 1) |
| HTTP calls | 70 (JS: 45, Lua: 17, Python: 5, Go: 3) |
| Cross-service edges | 92 (sockets: 9, Redis patterns: 8, DB: 54, AWS: 16, config: 5) |
| Graph writes | 71,238 |
| Tests | 286 passing |
