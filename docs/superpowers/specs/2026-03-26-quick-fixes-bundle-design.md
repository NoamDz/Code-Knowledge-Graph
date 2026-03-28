# Quick Fixes Bundle — Design Spec

**Date:** 2026-03-26
**Goal:** Eight surgical fixes to existing parsers and resolvers, each 10-50 lines of changes.

---

## 4A. Go Redis `.Result()` Chaining Fix

### Problem

All Go Redis calls chain `.Result()` or `.Err()`:
```go
val, err := r.client.HGet(context.Background(), mainKey, subKey).Result()
err := r.client.HSet(context.Background(), key, subKey, encodedValue).Err()
```

The resolver's `_GO_REDIS_INDICATORS` contains `"redisClient"` but BOB shows the actual field name is `client` (as in `r.client.HGet`). The Redis wrapper struct is `RedisClient` with a field named `client` of type `*redis.Client`.

Tree-sitter extracts the inner call `r.client.HGet` as one `call_expression` and the outer `.Result()` as another. The inner callee string is `r.client.HGet`. Splitting on last `.` gives receiver `r.client`, method `HGet`.

Current check: `any(ind in receiver for ind in _GO_REDIS_INDICATORS)` — `"redisClient"` is NOT in `"r.client"`.

### Root Cause Analysis

The resolver code at `redis_abstraction_resolver.py` line 296 already iterates ALL Go ASTs (`if ast.language != "go": continue`), so it does run on all files. The actual root causes are:

**Root Cause 1 — Missing wrapper methods:** The existing `_GO_REDIS_READ` set (lines 270-280) only contains standard go-redis methods. BOB confirmed the service code calls WRAPPER methods (`HGetAsString`, `GetAsString`, `GetAsInt`, `GetAsFloat`, `HGetAsString`, `HGetAsInt`, `HGetAsFloat`). These are NOT in the method sets. They need to be added.

**Root Cause 2 — Internal redis.go calls use `r.client` not `r.redisClient`:** Inside `redis.go`, the code calls `r.client.HGet(ctx, key, field).Result()`. The receiver `r.client` does NOT contain any of the current `_GO_REDIS_INDICATORS` (`"redisClient"`, `"RedisClient"`, `"redis.Client"`, `"rdb"`, `"redisConn"`). The indicator set needs `"r.client"` or a broader matching strategy.

### Solution

1. Add wrapper-specific methods to the read/write sets:
   ```python
   _GO_REDIS_READ_METHODS |= {"HGetAsString", "HGetAsInt", "HGetAsFloat", "GetAsString", "GetAsInt", "GetAsFloat"}
   _GO_REDIS_WRITE_METHODS |= {"HSetWithExpire"}
   ```

2. Add standard go-redis methods for detecting internal redis.go operations:
   ```python
   _GO_REDIS_READ_METHODS |= {"HGet", "Get", "HGetAll", "MGet", "SMembers", "LRange"}
   _GO_REDIS_WRITE_METHODS |= {"HSet", "Set", "Del", "Expire", "SAdd", "LPush", "EvalSha"}
   ```

3. Broaden indicator matching for internal redis.go detection — add `".client"` check:
   ```python
   # In the indicator check, also match receivers ending with ".client"
   # This is safe because only redis.go has this pattern in the Go codebase
   ```

4. Wire `resolve_go_redis_abstractions()` into `graph_health.py` — currently missing (line 179 only calls `resolve_redis_abstractions()` for Lua).

**Implementation file:** `graph_builder/resolvers/redis_abstraction_resolver.py`

**Expected impact:** 0 → ~93 Go Redis operations detected (BOB confirmed 93 operations in redis.go).

---

## 4B. Python `self.method()` Resolution

### Problem

The CallResolver's self-handling checks `ast.module_info.table_var_name` which is Lua-specific. Python's `self.method()` calls never match because Python ASTs don't have `module_info`.

BOB showed Python methods extensively use:
- `self._retry_failed_databases()` — same-class method call
- `self.logger.debug(...)` — attribute chain (self → attribute → method)
- `self.create_new_batch(task)` — same-class method call
- `self.connection.hset(...)` — attribute chain

### Solution

In `CallResolver._resolve_call()`, add Python-specific self-handling:

```python
if table_name == "self" and ast.language == "python":
    # Strategy: resolve self.method() to same-file function
    # Note: Python FunctionDef.name stores bare names (e.g., "process_record"),
    # not "ClassName.process_record", so a bare name match works.
    # Caveat: if multiple classes in the same file define methods with the same
    # name, this may produce false positives. This is acceptable — single-class
    # files are the norm in this codebase.
    for func in ast.functions:
        if func.name == method_name:
            call.resolved_module = ast.module_name or ast.file_path
            call.resolved_function = method_name
            call.resolution_confidence = "self_python"
            return True
    # For self.attribute.method() chains, mark as same-class access
    # Don't try to resolve the attribute's type
    return False
```

Also fix the health report metric: Python's "functions with outgoing calls" is artificially low because the enclosing function lookup may also have format mismatches (similar to Ruby's `ClassName#method` issue).

**Implementation file:** `graph_builder/resolvers/call_resolver.py`

**Expected impact:** Python "functions with outgoing calls" increases from 42 to ~200+. Call resolution improves moderately.

---

## 4C. Python Redis `RedisCluster` Factory

### Problem

Python Redis detection finds 0 because `RedisCluster` is not in the `redis_factories` set (only `Redis`, `StrictRedis`, `from_url`). BOB confirmed only 1 file (`geo.py`) uses Redis, with `RedisCluster` via try/except import.

### Solution

1. Add to `redis_factories` in `python_parser.py`:
```python
redis_factories = {"Redis", "StrictRedis", "from_url", "RedisCluster", "StrictRedisCluster"}
```

2. Handle `self.connection = RedisCluster(...)` pattern — currently only local variable assignments are tracked (lines 313-325 of `python_parser.py` check `left.type == "identifier"`). For `self.connection = RedisCluster(...)`, the Tree-sitter LHS node type is `attribute` (not `identifier`). Extend the check to also handle `left.type == "attribute"`, traversing to extract both `self` and `connection`, then add `self.connection` to `redis_vars`.

3. Handle try/except import:
```python
try:
    from redis.cluster import RedisCluster
except ImportError:
    from rediscluster import RedisCluster
```
Both import forms should register `RedisCluster` as a Redis factory binding.

**Implementation file:** `graph_builder/parsers/python_parser.py`

**Expected impact:** 0 → 1 Redis access detected (only 1 `hset` operation exists). Small number but proves the detection works.

---

## 4D. Ruby Preprocessor Loading Model

### Problem

63 preprocessor files are loaded via directory scanning, 2 task files via `class_eval(IO.read(entry))`. Neither uses `require`, so all appear as orphans.

BOB showed:
```ruby
# Preprocessor loading — src/core/generator/preprocessor.rb:15
scan_for_preprocess(@config["base_path"])

# Task loading — src/core/generator/generator.rb:53-54
klass = Class.new
klass.class_eval(IO.read(entry))
```

### Solution

Add two heuristic loading patterns to the Ruby resolver:

**4D-1. Directory-scan convention:**
When a Ruby file contains `Dir.glob`, `Dir.entries`, `Dir["pattern"]`, or a method named `scan_for_*`, and the glob pattern targets `.rb` files, create `LOADS_DYNAMICALLY` edges from the scanning file to all `.rb` files matching the pattern in the target directory.

Specifically for this codebase: `preprocessor.rb` scans `*/generator/preprocess/` directories. Create edges from `preprocessor.rb` to all 63 preprocessor files.

**4D-2. class_eval(IO.read(...)) pattern:**
When a Ruby file contains `class_eval(IO.read(` pattern, and the argument references a file path, create a `LOADS_DYNAMICALLY` edge to that file.

Specifically for this codebase: `generator.rb` loads `tasks.rb` files. Create edges from `generator.rb` to `ato/generator/tasks.rb` and `malware/generator/tasks.rb`.

**Implementation:** These are pattern-based heuristics added to `ruby_resolver.py`. Since the patterns are specific to this codebase's conventions, keep them configurable or clearly documented.

**Implementation file:** `graph_builder/resolvers/ruby_resolver.py`

**Expected impact:** Ruby orphans reduced from 88 to ~20-25 (63 preprocessors + 2 tasks + a few others connected).

---

## 4E. Ruby `module_name` and Health Metric Fix

### Problem

Two separate bugs:

1. **"0 functions with outgoing calls"** — The health report's `_find_enclosing()` returns `ClassName#method` but `FunctionDef.name` stores `method`. They never match, so every call appears to have no enclosing function.

2. **No `module_name` on Ruby FileAST** — Without this, Ruby files are invisible to the global symbol table in CallResolver, preventing cross-file call resolution.

### Solution

**4E-1. Fix enclosing function lookup in health report:**
In `graph_health.py`, when matching calls to enclosing functions for Ruby, strip the class prefix:
```python
func_name = func.name.split("#")[-1] if "#" in func.name else func.name
```
Or: store both the qualified name and bare name, match against either.

**4E-2. Set module_name on Ruby FileAST:**
In `ruby_parser.py`, after parsing, set `ast.module_name` to the primary class or module name found in the file. Derive from:
- The first `class ClassName` or `module ModuleName` declaration
- Or from the relative file path as fallback (e.g., `core/generator/generator` from `src/core/generator/generator.rb`)

**Format:** Use dot-separated format (e.g., `Generator.Templates`) to match how `CallResolver.build_symbol_table()` constructs keys (`module_name.function`). Ruby's native `::` separator should be converted to `.` for consistency with the global symbol table. Example: `class ObfuscationArbitraryCodeFunctions` → module_name `ObfuscationArbitraryCodeFunctions`, symbol key `ObfuscationArbitraryCodeFunctions.method_name`.

**Implementation files:** `graph_builder/validate/graph_health.py`, `graph_builder/parsers/ruby_parser.py`

**Expected impact:** Ruby health metrics become accurate (showing actual outgoing calls). Ruby call resolution may improve slightly from module_name enabling global symbol table lookups.

---

## 4F. Go Interface `IMPLEMENTS` Edges

### Problem

Go has 7 interfaces with known implementors but no `IMPLEMENTS` edges in the graph.

### BOB's Interface Inventory

| Interface | Methods | Implementor(s) |
|-----------|---------|-----------------|
| `TasksReader` | `ReadTasks` | `GeneralTasksReader` |
| `TasksService` | `Run`, `Close` | `GeneralTasksService` |
| `Task` | `Process`, `Close` | `ModelPredictionTask` |
| `BehaveData` | `UrlDataArr`, `GetUserAgent` | Multiple models |
| `Config` | (empty) | Any type |
| `SagemakerClientFactory` | `GetSagemakerClient` | Test mocks |
| `KinesisFirehoseClientFactory` | `GetFirehoseClient` | Test mocks |

BOB confirmed: zero struct embeddings exist.

### Solution

After Go parsing, compare interface method sets against struct method sets:

```python
def resolve_go_interfaces(all_asts):
    interfaces = {}  # name -> set of method names
    structs = {}     # name -> set of method names

    for ast in all_asts:
        if ast.language != "go":
            continue
        for cls in ast.classes:
            if cls.is_interface:
                interfaces[cls.name] = {m.name for m in cls.methods}
            else:
                structs[cls.name] = {m.name for m in cls.methods}

    implements = []
    for iface_name, iface_methods in interfaces.items():
        if not iface_methods:  # Skip empty interfaces
            continue
        for struct_name, struct_methods in structs.items():
            if iface_methods.issubset(struct_methods):
                implements.append((struct_name, iface_name))
    return implements
```

Create `IMPLEMENTS` edges from struct to interface.

**Required change:** `ClassDef` in `base.py` (lines 121-129) does NOT have an `is_interface` field. Add `is_interface: bool = False` to `ClassDef`. In `go_parser.py`, when creating `ClassDef` from `type_spec` nodes containing `interface_type` (lines 153-170), set `is_interface=True`. Currently interfaces and structs are indistinguishable after parsing — this flag is necessary for the implementation matching algorithm.

**Implementation files:** `graph_builder/resolvers/go_resolver.py`, `graph_builder/parsers/go_parser.py` (if `is_interface` flag needed)

**Expected impact:** ~7-10 IMPLEMENTS edges (excluding empty Config interface and test mocks).

---

## 4G. Ruby Redis Detection

### Problem

BOB A8 revealed 5 Ruby files use Redis (`redis_helper.rb`, `redis_connection.rb`, `redis_lists.rb`, `redis_lists/event.rb`, `redis_lists/cache_buffer.rb`). Ruby writes bundle data to Redis that Lua reads — a critical cross-language data flow. Zero Ruby Redis detection exists.

### BOB's Findings

```ruby
# src/core/utils/ruby/redis_helper.rb:13
@redis = Redis.new(redis_cluster_config)

# Operations:
def get(key)
def set(key, value)
def get_json(key)
def set_json(key, value)
def hget(key, sub_key)
def eval(script, keys, values)

# src/core/generator/clients/redis.rb
# Stores generated bundles in Redis
# Keys: "bundles/<origin>/<revision>/<environment>/<key>"
```

### Solution

Add Ruby Redis detection to the Ruby parser, similar to the Python pattern:
- Track `require "redis"` and `Redis.new(...)` construction
- Detect method calls: `get`, `set`, `hget`, `hset`, `get_json`, `set_json`, `eval`, `del`
- Track `@redis` instance variable assignments (Ruby uses `@` for instance vars)
- Create REDIS_READS/REDIS_WRITES edges

**Implementation file:** `graph_builder/parsers/ruby_parser.py`

**Expected impact:** ~5-10 Ruby Redis operations detected, enabling cross-language Redis data flow edges.

---

## 4H. Tornado Route Registration Detection

### Problem

BOB D6 revealed Python services define routes via `tornado.web.Application(handlers=[...])` tuples, not decorators. These are detectable route registrations that would create Endpoint→Handler edges for Python services.

### BOB's Findings

```python
# src/deferrer/missioner/missioner.py:20-26
application = tornado.web.Application(
    handlers = [
        ("/add_mission", AddMissionHandler),
        ("/monitor", MonitorHandler),
    ],
)

# src/core/atlas/app.py:30-36
return tornado.web.Application([
    (r"/lookup", IPLookupHandler, {"lookup_service": lookup_service}),
    (r"/health", HealthHandler),
])
```

3 Python services define routes this way: Missioner (2 routes), Atlas (2 routes), Global Data (~3 routes).

### Solution

Add Tornado route detection to the Python parser:
- Detect `tornado.web.Application(handlers=[...])` or `tornado.web.Application([...])` constructor calls
- Extract `(path_string, HandlerClass)` tuples from the handlers list
- Create `Endpoint` nodes for each path and `HANDLES` edges from the handler class file to the endpoint
- Resolve `HandlerClass` to its file via imports in the same file

**Implementation file:** `graph_builder/parsers/python_parser.py`

**Expected impact:** ~7-10 endpoint-to-handler edges for Python services, connecting them to the nginx endpoint model.

---

## Testing Strategy

### Unit Tests per Fix

1. **4A Go Redis:** File with `r.client.HGet(ctx, key).Result()` → Redis READ detected; `mps.redisClient.HGetAsString(key, field)` → Redis READ detected
2. **4B Python self:** File with `self.process_record(data)` where `process_record` defined in same file → resolved; `self.logger.debug(msg)` → not resolved (attribute chain)
3. **4C Python Redis:** File importing `RedisCluster` with `self.connection = RedisCluster(...)` and `self.connection.hset(key, field, val)` → 1 Redis WRITE detected
4. **4D Ruby loading:** File with `Dir.glob("preprocess/*.rb")` → LOADS_DYNAMICALLY edges to all .rb files in preprocess/
5. **4E Ruby metrics:** Ruby file with `class Foo; def bar; baz(); end; def baz; end; end` → `bar` has 1 outgoing call
6. **4F Go interfaces:** Interface `Task` with `Process`, `Close`; struct `ModelPredictionTask` with `Process`, `Close`, `Init` → IMPLEMENTS edge created
7. **4G Ruby Redis:** File with `@redis = Redis.new(config)` and `@redis.hget(key, field)` → Redis READ detected
8. **4H Tornado routes:** File with `tornado.web.Application(handlers=[("/lookup", IPLookupHandler)])` → Endpoint node + HANDLES edge

### Integration Verification

Run `code-graph build` + `code-graph health` and verify:
- Go Redis: 0 → ~93
- Python functions with calls: 42 → ~200+
- Python Redis: 0 → 1
- Ruby Redis: 0 → ~5-10
- Ruby orphans: 88 → ~20-25
- Ruby functions with calls: 0 → ~800+
- Go IMPLEMENTS edges appear
- Python Tornado endpoints appear

---

## Expected Impact Summary

| Fix | Before | After |
|-----|--------|-------|
| 4A Go Redis | 0 ops | ~93 ops |
| 4B Python self | 42 functions w/ calls | ~200+ |
| 4C Python RedisCluster | 0 ops | 1 op |
| 4D Ruby loading | 88 orphans | ~20-25 orphans |
| 4E Ruby metrics | 0 functions w/ calls | ~800+ (display fix) |
| 4F Go interfaces | 0 IMPLEMENTS edges | ~7-10 edges |
| 4G Ruby Redis | 0 ops | ~5-10 ops |
| 4H Tornado routes | 0 Python endpoints | ~7-10 endpoint edges |

---

## Files Modified

| File | Fixes |
|------|-------|
| `graph_builder/resolvers/redis_abstraction_resolver.py` | 4A: Go Redis indicators and method lists |
| `graph_builder/resolvers/call_resolver.py` | 4B: Python self-resolution |
| `graph_builder/parsers/python_parser.py` | 4C: RedisCluster factory, self.attr assignment |
| `graph_builder/resolvers/ruby_resolver.py` | 4D: Directory-scan and class_eval loading |
| `graph_builder/parsers/ruby_parser.py` | 4E: Set module_name on FileAST |
| `graph_builder/validate/graph_health.py` | 4E: Fix enclosing function lookup for Ruby |
| `graph_builder/resolvers/go_resolver.py` | 4F: Interface implementation matching |
| `graph_builder/parsers/base.py` | 4F: Add `is_interface: bool = False` to ClassDef |
| `graph_builder/parsers/go_parser.py` | 4F: Set `is_interface=True` for interface type_spec nodes |
| `graph_builder/validate/graph_health.py` | 4A: Add `resolve_go_redis_abstractions()` call (currently missing) |
| `graph_builder/parsers/ruby_parser.py` | 4G: Ruby Redis detection (Redis.new, @redis instance var, get/set/hget methods) |
| `graph_builder/parsers/python_parser.py` | 4H: Tornado route detection (Application(handlers=[...])) |
| `graph_builder/ingestion/writer.py` | 4D, 4F, 4G, 4H: New edge types |
| `graph_builder/tests/test_quick_fixes.py` | New test file for all 8 fixes |
