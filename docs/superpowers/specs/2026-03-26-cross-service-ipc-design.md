# Cross-Service IPC Edges — Design Spec

**Date:** 2026-03-26
**Goal:** Map the full inter-process communication topology: Unix sockets, mission dispatch expansion, shared Redis key patterns, MySQL access, and Cassandra access across 5 languages.

**Context:** BOB's Round 5 revealed 9 IPC mechanisms, 7 Unix sockets, a complete Redis key namespace map, and MySQL/Cassandra access patterns across multiple languages. We currently detect only 21 HTTP calls, 4 mission dispatches, and 4 cross-language endpoint links.

---

## 1. Unix Socket Connection Mapping

### Problem

7 Unix sockets connect services but we have zero socket-level edges in the graph.

### BOB's Socket Inventory

| Socket Path | Listener | Connectors | Protocol |
|------------|----------|------------|----------|
| `glider.sock` | Redis Glider | All Lua | Redis protocol |
| `missioner.sock` | Python missioner | Lua | HTTP |
| `prediction_tcp_router_*.sock` | Go model_prediction | Lua | Custom JSON |
| `global_data.sock` | Python global_data | Lua | HTTP |
| `atlas.sock` | Python atlas | Lua | HTTP |
| `cassandra_communicator_*.sock` | Lua cassandra_comm | Lua | Custom |
| `/dev/log` | rsyslog | All | Syslog |

### Solution

Detect socket connections through two complementary approaches:

**Approach 1 — Static string scanning (Python, Go):**
For languages where socket paths appear as string literals:

Python:
```python
bind_unix_socket("/path/to/socket.sock")
tornado.netutil.bind_unix_socket(socket_path)
```

Go:
```go
net.Listen("unix", "/path/to/socket.sock")
```

Scan string literals for `.sock` suffix or `unix:` prefix.

**Approach 2 — Config-based static mapping (Lua):**
Most Lua socket connections use dynamic path construction: `sock:connect(format("unix:%s", socket_file))` where `socket_file` comes from config. String scanning won't catch these. Instead, use BOB's confirmed socket inventory as a static configuration:

```python
KNOWN_SOCKET_CONNECTIONS = [
    {"socket": "glider.sock", "listener_lang": "external",
     "connector_files": ["lib/lua/redis/redisglider.lua"]},
    {"socket": "missioner.sock",
     "listener_files": ["deferrer/missioner/missioner.py"],
     "connector_files": ["core/deferrer/missioner/client.lua"]},
    {"socket": "prediction_tcp_router.sock",
     "listener_files": ["core/model_prediction/server/router.go"],
     "connector_files": ["core/model_prediction/client/unix_socket_client.lua"]},
    # ... etc for global_data, atlas, cassandra_communicator
]
```

This is pragmatic: the socket inventory is stable and fully known from BOB's investigation.

**Algorithm:**
1. For Python/Go ASTs, scan string literals for `.sock` or `unix:` patterns
2. For Lua, use the static mapping to create edges directly
3. Normalize socket paths (strip `unix:` prefix)
4. Create `UnixSocket` nodes with path and protocol metadata
5. Determine listener vs connector from context:
   - `bind_unix_socket()`, `net.Listen("unix", ...)` → SOCKET_LISTENS
   - `sock:connect("unix:...")`, client code → SOCKET_CONNECTS

**New graph elements:**
- Node type: `UnixSocket` with properties: `path`, `protocol`
- Edge types: `SOCKET_LISTENS` (File → UnixSocket), `SOCKET_CONNECTS` (File → UnixSocket)

**Expected impact:** ~15 edges (7 sockets × ~2 edges each: 1 listener + 1 connector)

---

## 2. Mission Dispatch Expansion (4 → 74)

### Problem

The mission resolver detects only 4 of 74 `missioner.add_mission()` call sites. The current resolver looks for mission-related entries in `ast.warnings`, but the Lua parser only flags a small subset.

### BOB's Examples

```lua
-- src/ato/controllers/pts.lua:107
missioner.add_mission("pts_run", parameters, MISSION_DELAY, "policy")

-- src/ato/helpers/device_analyzer.lua:507
missioner.add_mission("device_analyzer_dry_run", task_data, 0, "default")

-- src/common/tasks/rules_engine_rulegen_check.lua:61
missioner.add_mission("rules_engine_rulegen_regenerate", parameters, 0, "default")
```

BOB also noted: "Most missions use async timers (`missioner_timer.post()`) rather than direct `add_mission()` calls."

### Solution

Two-pronged fix:

**2A. Expand mission detection in Lua parser:**
Instead of relying on `ast.warnings`, detect mission calls directly from the call list:
- Scan all `CallRef` objects where callee matches `missioner.add_mission` or `missioner_timer.post`
- Also match via binding map: if a local variable was bound to the missioner module via `require` or `require_version`, match calls on that variable. Note: `require_version` imports should have `is_dynamic = False` in the AST since the parser already handles `require_version` identically to `require` (added in earlier work). Verify this during implementation.
- Extract the first string argument as the task name
- Store as structured data (not warnings)

**2B. Expand task name → file resolution:**
Current resolver maps task names like `"pts_run"` to files matching `tasks/pts_run.lua`. Extend to also search:
- `src/ato/tasks/{name}.lua`
- `src/common/tasks/{name}.lua`
- `src/malware/tasks/{name}.lua`

Create `DISPATCHES` edges from the calling file to the task file.

**Expected impact:** 4 → ~50-74 DISPATCHES edges.

---

## 3. Shared Redis Key Cross-Language Linking

### Problem

Redis is the primary implicit data bus between services. Lua writes session data that Go reads for model prediction. Ruby writes bundle configs that Lua reads. But we have no cross-language data flow edges.

### BOB's Key Namespace Map (Cross-Language Patterns)

| Key Pattern | Writer | Reader |
|------------|--------|--------|
| `store:{session_id}` | Lua (Store) | Go (model_prediction helpers/store.go) |
| `bundles`, `bundle:{business}:{app}` | Ruby (Generator) | Lua (Bundles) |
| `model_prediction:{session_id}:*` | Go (ModelPrediction) | Lua (Policy) |
| `model_prediction_tasks:{session_id}` | Lua (ModelPrediction) | Go (ModelPrediction) |

### Solution

This is a lightweight, pattern-based approach — not full key tracking.

**Algorithm:**
1. Define known cross-language Redis key patterns as a configuration:
```python
CROSS_LANGUAGE_REDIS_PATTERNS = [
    {
        "pattern": "store:{session_id}",
        "writers": ["lua"],
        "readers": ["go"],
        "writer_files": ["lib/lua/store.lua", "lib/lua/redis_helper.lua"],
        "reader_files": ["helpers/store.go"],
    },
    {
        "pattern": "bundles",
        "writers": ["ruby"],
        "readers": ["lua"],
        "writer_files": ["generator/clients/redis.rb"],
        "reader_files": ["lib/lua/bundles.lua"],
    },
    {
        "pattern": "model_prediction:{session_id}",
        "writers": ["go"],
        "readers": ["lua"],
        "writer_files": ["tasks/model_prediction.go"],
        "reader_files": ["ato/assessors/model_prediction/init.lua"],
    },
]
```

2. For each pattern, resolve file paths against the repo and create edges:
   - `SharedRedisPattern` node with pattern string and description
   - `WRITES_REDIS_PATTERN` edge from writer file to pattern node
   - `READS_REDIS_PATTERN` edge from reader file to pattern node

This is a static configuration approach (not dynamic detection) because cross-language key sharing requires semantic understanding that can't be reliably extracted from code alone. BOB's investigation provides the ground truth.

**Expected impact:** ~20-30 cross-language data flow edges.

---

## 4. MySQL Access Detection

### Problem

Three languages access MySQL with zero detection.

### BOB's Findings

| Language | Client | Pattern |
|----------|--------|---------|
| Lua | `lib/lua/mysql` (custom) | `db:query(sql)`, `db:execute(sql)` |
| Python | `mysql.connector` | `cursor.execute(sql)`, `MySQLConnectionPool(...)` |
| Ruby | `sequel` gem | `Sequel.connect(...)`, `@db.fetch(sql)` |

### Solution

Add MySQL detection to each language parser, following the same pattern as Redis detection.

**Lua MySQL detection:**
- Track bindings to `lib.lua.mysql` module
- Detect method calls: `query`, `execute`, `fetch`, `prepare`
- Extract table names from SQL string arguments when possible (regex for `FROM table`, `INTO table`, `UPDATE table`). Note: table extraction is best-effort — subqueries, CTEs, and dynamically constructed SQL will produce false negatives. This is acceptable; the primary value is the QUERIES_DB edge itself, not the table name.

**Python MySQL detection:**
- Track `mysql.connector` imports and `MySQLConnectionPool` construction
- Detect `cursor.execute()` calls
- Extract table names from SQL strings

**Ruby MySQL detection:**
- Track `sequel` gem require and `Sequel.connect()` calls
- Detect query method calls

**New graph elements:**
- Edge type: `QUERIES_DB` (Function → string label with table name if extractable)
- Store as metadata on the edge: `{db_type: "mysql", operation: "query", table: "alerted_transactions"}`

**Expected impact:** ~15-20 QUERIES_DB edges.

---

## 5. Cassandra Access Detection

### Problem

Cassandra is accessed only through the communicator service via Unix socket, but the Cassandra client code has detectable patterns.

### BOB's Findings

```lua
-- src/lib/lua/cassandra/client.lua:90
ok, err = connection_socket:connect(format("unix:%s", socket_file), context.get_pool_params(CTX))

-- Operations:
CassandraDB.execute_statement(query, params)
CassandraDB.prepare_statement(query)
```

### Solution

Detect Cassandra operations in Lua files:
- Track bindings to `lib.lua.cassandra.client` module
- Detect calls to `execute_statement`, `prepare_statement`, `batch_execute`
- Create `QUERIES_CASSANDRA` edges

**Expected impact:** ~10 edges.

---

## Testing Strategy

### Unit Tests

1. **Socket detection:**
   - Lua file with `sock:connect("unix:/path/to/missioner.sock")` → SOCKET_CONNECTS edge
   - Python file with `bind_unix_socket(path)` → SOCKET_LISTENS edge
   - Go file with `net.Listen("unix", path)` → SOCKET_LISTENS edge

2. **Mission expansion:**
   - `missioner.add_mission("pts_run", params, delay, "policy")` → DISPATCHES edge to tasks/pts_run.lua
   - `missioner_timer.post(...)` variant → also detected
   - Task name not matching any file → edge with unresolved target logged

3. **Redis key patterns:**
   - Configuration-based patterns create correct nodes and edges
   - File paths resolve correctly against repo

4. **MySQL detection:**
   - Lua `db:query("SELECT * FROM users")` → QUERIES_DB edge with table "users"
   - Python `cursor.execute("INSERT INTO alerts ...")` → QUERIES_DB edge

### Integration Verification

After implementation, run `code-graph health` and verify:
- Cross-service section shows Unix socket edges
- Mission dispatches increase from 4 to 50+
- New Redis pattern, MySQL, and Cassandra edges appear in graph writes

---

## Expected Impact Summary

| Component | New Edges | Type |
|-----------|-----------|------|
| Unix socket mapping | ~15 | SOCKET_CONNECTS/LISTENS |
| Mission dispatch expansion | +46-70 | DISPATCHES |
| Shared Redis key patterns | ~20-30 | WRITES/READS_REDIS_PATTERN |
| MySQL detection | ~15-20 | QUERIES_DB |
| Cassandra detection | ~10 | QUERIES_CASSANDRA |
| **Total** | **~106-145** | **Cross-service** |

---

## Files Modified/Created

| File | Change |
|------|--------|
| `graph_builder/resolvers/cross_service_resolver.py` | **New** — Unix socket, MySQL, Cassandra detection |
| `graph_builder/resolvers/mission_resolver.py` | Expand detection from warnings to call scanning |
| `graph_builder/parsers/lua_parser.py` | Add MySQL/Cassandra call pattern extraction |
| `graph_builder/ingestion/writer.py` | Add upsert methods for new node/edge types |
| `graph_builder/main.py` | Wire cross-service resolver into pipeline |
| `graph_builder/validate/graph_health.py` | Report new edge types in cross-service section |
| `graph_builder/parsers/base.py` | Add dataclasses for UnixSocket, SharedRedisPattern if needed to carry data from resolvers to writer |
| `graph_builder/validate/graph_health.py` | Add Go Redis call (`resolve_go_redis_abstractions`) — currently missing. Report new cross-service edge types |
| `graph_builder/tests/test_cross_service.py` | New test file |
