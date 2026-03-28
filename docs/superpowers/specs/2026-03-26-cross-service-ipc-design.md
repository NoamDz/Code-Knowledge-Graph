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

Four languages access MySQL with zero detection.

### BOB's Findings

| Language | Client | Pattern |
|----------|--------|---------|
| Lua | `lib/lua/mysql` (custom) | `db:query(sql)`, `db:execute(sql)` |
| Python | `mysql.connector` | `cursor.execute(sql)`, `MySQLConnectionPool(...)` |
| Ruby | `sequel` gem | `Sequel.connect(...)`, `@db.fetch(sql)` |
| Go | `db.MysqlClient` (custom) | `mysqlClient.Query(...)` — BOB E3 showed `ModelPredictionTask` has `mysqlClient *db.MysqlClient` field |

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

**Go MySQL detection:**
- Track `db.MysqlClient` field access on structs (BOB E3: `mps.mysqlClient`)
- Detect method calls on the MySQL client
- The Go parser already extracts these as regular calls; the cross-service resolver needs to recognize `mysqlClient` as a MySQL indicator (similar to Go Redis indicator matching)

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

## 6. SQS Queue Detection

### Problem

SQS is a major IPC mechanism between the aggregator and poller Python services, with zero detection.

### BOB's Findings (F1, F4)

```python
# src/deferrer/aggregator/aggregator/clients/sqs.py:26
self.sqs_client.send_message(QueueUrl=self.queue_url, MessageBody=data)

# src/deferrer/poller/poller/utils/clients/sqs.py:84
session = boto3.session.Session()
```

Both aggregator (producer) and poller (consumer) use boto3 SQS client. ~10 call sites total.

### Solution

Detect SQS operations in Python files:
- Track `boto3` imports and `sqs_client` / `sqs` variable bindings
- Detect `send_message()`, `receive_message()`, `delete_message()` method calls
- Create `SQSQueue` nodes and `PRODUCES_TO` / `CONSUMES_FROM` edges

**Expected impact:** ~10 edges.

---

## 7. Kinesis Firehose Detection

### Problem

Go and Ruby upload events to Kinesis Firehose with zero detection.

### BOB's Findings (F1, F4)

```go
// src/core/model_prediction/server/services/kinesis.go:62
func (kinesis *Kinesis) UploadEvent(eventType string, event []byte, sessionID string, ...)
```

```ruby
# src/core/multi_events_uploader/lib/clients/kinesis_firehose.rb:31
response = client.put_record({delivery_stream_name: stream, record: { data: event }})
```

### Solution

Detect Kinesis operations:
- **Go:** Track `*services.Kinesis` fields, detect `UploadEvent`, `PutRecord` calls
- **Ruby:** Track `Aws::Firehose::Client` construction, detect `put_record` calls
- Create `KinesisStream` nodes and `STREAMS_TO` edges

**Expected impact:** ~5 edges.

---

## 8. S3 Access Detection

### Problem

Ruby uploads bundles and events to S3 with zero detection.

### BOB's Findings (A8, F4)

```ruby
# src/core/generator/clients/s3.rb:14
class S3Client  # Uploads generated bundles to S3

# src/core/multi_events_uploader/lib/clients/s3.rb:13-14
client = Aws::S3::Client.new(get_client_opts(client_config))
obj = bucket.object(s3_key)
obj.upload_file(file_name, server_side_encryption: 'AES256')
```

3 Ruby files use S3. Go also has S3 access via aws-sdk-go.

### Solution

Detect S3 operations:
- **Ruby:** Track `Aws::S3::Client`, `Aws::S3::Resource` construction. Detect `put_object`, `get_object`, `upload_file` calls.
- **Go:** Track S3 client construction and method calls.
- Create `ACCESSES_S3` edges from files to S3 bucket identifiers.

**Expected impact:** ~10 edges.

---

## 9. Shared Configuration File Edges

### Problem

Multiple languages read the same config files, creating invisible coupling with zero detection.

### BOB's Findings (F6)

| Config | Lua | Python | Go | Ruby |
|--------|-----|--------|----|------|
| `config.lua` / config.json | `require("config")` | `Config.load()` | `config.LoadConfig()` | `Utils.load_config` |
| `features.lua` / features.json | `require("features.lua")` | Via HTTP to Lua | — | `Features.new()` |
| Bundle JSON (in Redis) | Lua reads | — | — | Ruby writes |
| model_prediction_service.json | Lua client reads | — | Go service reads | — |

### Solution

Use a static configuration approach (like shared Redis keys):

```python
SHARED_CONFIG_FILES = [
    {"config": "config.json", "readers": {
        "lua": ["lib/lua/config.lua"],
        "python": ["deferrer/*/lib/config.py"],
        "go": ["core/model_prediction/server/config/init.go"],
        "ruby": ["core/utils/ruby/utils.rb"],
    }},
    {"config": "model_prediction_service.json", "readers": {
        "lua": ["core/model_prediction/client/unix_socket_client.lua"],
        "go": ["core/model_prediction/server/config/init.go"],
    }},
]
```

Create `ConfigFile` nodes and `READS_CONFIG` edges from files to shared configs.

**Expected impact:** ~10 edges.

---

## 10. Nginx Endpoint Linker Expansion

### Problem

BOB documented all 23 nginx locations but we only link 4 cross-language endpoints. The existing `endpoint_linker.py` uses longest-prefix matching on nginx locations, but the dynamic routing through `@router` → `main.lua` → controller dispatch isn't followed.

### BOB's Findings (F9)

Key locations with Lua handlers:
- `= /tasks` — internal from Poller (Python → Lua cross-language)
- `= /missions` — internal from Missioner
- `= /get_bundle` — internal from Model Prediction (Go → Lua)
- `~ ^/(?<module>.+)/controllers/...` — dynamic router → 6 controllers
- `= /monitor`, `= /status` — health checks
- `= /events` — event endpoint

### Solution

Extend the endpoint linker with BOB's confirmed routing data:

1. **Static internal endpoint mapping:** For internal-only locations (`/tasks`, `/missions`, `/get_bundle`), create direct cross-language endpoint links from the known callers (Python poller, Go model_prediction) to the Lua handler files.

2. **Controller route expansion:** The `@router` catch-all dispatches to `router/main.lua` which routes to controllers. Use BOB's confirmed controller list to create `HANDLES_ENDPOINT` edges from controller files to endpoint patterns.

**Expected impact:** +10-16 additional endpoint links (4 → ~20).

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
   - Go `mps.mysqlClient.Query(...)` → QUERIES_DB edge

5. **SQS detection:**
   - Python `sqs_client.send_message(QueueUrl=url, ...)` → PRODUCES_TO edge
   - Python `sqs.receive_message(...)` → CONSUMES_FROM edge

6. **Kinesis/S3 detection:**
   - Go `kinesis.UploadEvent(...)` → STREAMS_TO edge
   - Ruby `obj.upload_file(...)` → ACCESSES_S3 edge

7. **Config file edges:**
   - Static config map resolves file paths correctly
   - Multiple languages reading same config → READS_CONFIG edges

8. **Endpoint linker expansion:**
   - Internal endpoints (/tasks, /missions, /get_bundle) create cross-language links
   - Controller routes create HANDLES_ENDPOINT edges

### Integration Verification

After implementation, run `code-graph health` and verify:
- Cross-service section shows Unix socket, SQS, Kinesis, S3 edges
- Mission dispatches increase from 4 to 50+
- New Redis pattern, MySQL, Cassandra, and config edges appear in graph writes
- Endpoint links increase from 4 to ~20

---

## Expected Impact Summary

| Component | New Edges | Type |
|-----------|-----------|------|
| Unix socket mapping | ~15 | SOCKET_CONNECTS/LISTENS |
| Mission dispatch expansion | +46-70 | DISPATCHES |
| Shared Redis key patterns | ~20-30 | WRITES/READS_REDIS_PATTERN |
| MySQL detection (Lua/Python/Ruby/Go) | ~20-25 | QUERIES_DB |
| Cassandra detection | ~10 | QUERIES_CASSANDRA |
| SQS queue detection | ~10 | PRODUCES_TO/CONSUMES_FROM |
| Kinesis Firehose detection | ~5 | STREAMS_TO |
| S3 access detection | ~10 | ACCESSES_S3 |
| Shared config file edges | ~10 | READS_CONFIG |
| Nginx endpoint linker expansion | +10-16 | HANDLES_ENDPOINT |
| **Total** | **~152-211** | **Cross-service** |

---

## Files Modified/Created

| File | Change |
|------|--------|
| `graph_builder/resolvers/cross_service_resolver.py` | **New** — Unix socket, MySQL, Cassandra, SQS, Kinesis, S3, shared config detection |
| `graph_builder/resolvers/mission_resolver.py` | Expand detection from warnings to call scanning |
| `graph_builder/resolvers/endpoint_linker.py` | Add internal endpoint mapping and controller route expansion |
| `graph_builder/parsers/lua_parser.py` | Add MySQL/Cassandra call pattern extraction |
| `graph_builder/parsers/python_parser.py` | Add SQS detection patterns (boto3 sqs_client) |
| `graph_builder/parsers/go_parser.py` | Add MySQL indicator detection (mysqlClient) |
| `graph_builder/ingestion/writer.py` | Add upsert methods for new node/edge types (SQSQueue, KinesisStream, ConfigFile, ACCESSES_S3, etc.) |
| `graph_builder/main.py` | Wire cross-service resolver into pipeline |
| `graph_builder/parsers/base.py` | Add dataclasses for new node types if needed |
| `graph_builder/validate/graph_health.py` | Add Go Redis call (`resolve_go_redis_abstractions`). Report all new cross-service edge types |
| `graph_builder/tests/test_cross_service.py` | New test file |
