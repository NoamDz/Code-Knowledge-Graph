# Cross-Service Improvement Analysis

## Executive Summary

After analyzing all 4 BOB investigation rounds, the resolver implementations, and the gap analysis documents, here is a comprehensive assessment of cross-service detection opportunities and the BOB questions needed to unlock them.

---

## 1. Current State Assessment

### What We Detect Well
| Mechanism | Count | Coverage |
|---|---|---|
| Lua Redis (via abstraction resolver) | 1,125 | Excellent -- store, redis_helper, store_vector patterns |
| Lua HTTP calls (via http_handler wrapper) | 17 | Good -- after adding http_handler.get/post/put |
| Go HTTP calls | 3 | Partial -- HandleFunc registrations |
| ngx.ctx accesses | 296 | Excellent -- per-request context tracking |
| ngx.shared accesses | 41 | Good -- shared dict tracking |
| Go same-package edges | 245 | Good -- resolved via go resolver |
| Mission dispatches | 4 | Minimal -- only catching a few |
| Cross-language endpoint links | 4 | Minimal -- nginx->lua->go links |

### What We Miss Completely
| Mechanism | Expected | Detected | Gap |
|---|---|---|---|
| Go Redis | 10-30 | 0 | Custom wrapper methods not matching |
| JS HTTP calls | 8 | 0 | Container._sendRequest not detected in .js.erb |
| Python Redis | 5-15 | 0 | No Python Redis detection patterns |
| Python HTTP | 5-10 | 1 | Barely detecting Python HTTP |
| Ruby HTTP | ? | 0 | Unknown if Ruby makes HTTP calls |
| Cross-language endpoint links | 20-30+ | 4 | Nginx routing not fully modeled |
| Mission dispatches | 74 | 4 | String-based task routing barely covered |
| Redis pub/sub cross-language | ? | 0 | No pub/sub detection |
| Cassandra access | ? | 0 | No Cassandra detection at all |
| MySQL access | ? | 0 | No MySQL detection at all |
| S3/MinIO access | ? | 0 | No object storage detection |
| SQS access | ? | 0 | No queue detection beyond missions |
| Kinesis access | ? | 0 | No event stream detection |
| Event emission | 20+ types | 0 | Event system not modeled |
| Shared config files | 3+ files | 0 | No config sharing detection |
| Cron/scheduler deps | 5+ | 0 | No cron dependency tracking |
| Unix socket connections | 5+ | ~4 | Only model_prediction partially |

---

## 2. IPC Mechanisms Analysis

### Known IPC Mechanisms (from BOB Rounds 1-4)

#### 2.1 HTTP Calls (Partially Detected)
- **Lua -> Go**: Via `http_handler.post()` to Unix sockets (16 call sites)
- **Lua -> Python**: Via `http_handler.post()` to local HTTP
- **JS -> Lua**: Via `Container._sendRequest()` to nginx (8 call sites)
- **Python -> Lua**: Poller HTTP callbacks to `/tasks` endpoint
- **Go -> HTTP handlers**: 3 HandleFunc registrations

**Improvement Opportunity**: Parse nginx config more deeply to map ALL location blocks to their handler chains. Currently only 4 cross-language links exist; the full nginx config has 20+ location blocks.

#### 2.2 Unix Socket Communication (Partially Detected)
Known sockets from BOB Round 4:
- `/data/kashmir/pinpoint/shared/sockets/missioner.sock` (Lua -> Python missioner)
- `/data/kashmir/pinpoint/shared/sockets/model_prediction_1.sock` (Lua -> Go)
- Cassandra communicator socket (Lua -> Cassandra service)
- Tornado bind_unix_socket in Python services (poller, aggregator, atlas, global_data, geo)

**Improvement Opportunity**: Detect ALL socket paths by scanning for `unix:` patterns in strings, `ngx.socket.tcp()` + `sock:connect("unix:...")` in Lua, `bind_unix_socket()` in Python, `net.Listen("unix", ...)` in Go. Create `SOCKET_CONNECTS` edges.

#### 2.3 Mission/Task System (Barely Detected)
- 74 `missioner.add_mission()` call sites in Lua (we detect only 4)
- Task names map to files by convention: `"pts_run"` -> `tasks/pts_run.lua`
- Flow: Lua -> Unix socket -> Python missioner -> SQS -> Python poller -> HTTP callback -> Lua tasks controller

**Improvement Opportunity**: The mission resolver exists but is clearly not matching most patterns. Need to investigate why 70 of 74 sites are missed. BOB Round 4 showed the exact pattern.

#### 2.4 Redis as Cross-Language Data Store (Partially Detected for Lua Only)
- Lua writes session/device/policy data to Redis (1,125 detected accesses)
- Python reads from Redis (0 detected)
- Go reads from Redis (0 detected)
- Shared key patterns like `store:<session_id>`, `bundle:<app_id>`

**Improvement Opportunity**: Add Python Redis and Go Redis detection, then create `SHARED_REDIS_KEY` edges linking files that read/write the same key patterns across languages.

#### 2.5 Redis Pub/Sub (Not Detected)
From BOB Round 4:
- Lua publishes to channels like `policy_updates`
- Python subscribes to those channels
- Go reads shared keys

**Improvement Opportunity**: Detect `redis:publish()` in Lua, `redis_client.subscribe()` in Python, create `REDIS_PUBLISHES` / `REDIS_SUBSCRIBES` edges.

### Potential Additional IPC Mechanisms (Need BOB Confirmation)

#### 2.6 SQS Direct Access
The poller and aggregator use SQS. Are there other SQS consumers? Do any services produce to SQS directly (bypassing the missioner)?

#### 2.7 Kinesis
Event extractor uploads to Kinesis. Are there other Kinesis producers? Any in-codebase consumers?

#### 2.8 S3/MinIO
Docker-compose includes MinIO. What services read/write objects? Could be model files, config, exports.

#### 2.9 Cassandra Direct Access
Is Cassandra only accessed through the communicator service, or do some services have direct CQL drivers?

---

## 3. Database Access Matrix (Needs Completion)

### Current Knowledge

| Database | Lua | Python | Go | Ruby |
|---|---|---|---|---|
| **Redis** | 1,125 accesses | Confirmed (geo.py) but 0 detected | Confirmed (RedisClient) but 0 detected | Unknown |
| **MySQL** | Unknown (maybe via service) | global_data uses `mysql.connector` | Unknown | Unknown |
| **Cassandra** | Via communicator service | Unknown | Unknown | Unknown |
| **S3/MinIO** | Unknown | Unknown | Unknown | Unknown (generator?) |
| **SQS** | Via missioner | Poller, aggregator | Unknown | Unknown |
| **Kinesis** | Unknown | event_extractor | Unknown | Unknown |

### What We Need from BOB
- Complete the matrix above
- For shared datastores (especially Redis), map key patterns written by one language and read by another
- For MySQL, identify shared tables
- For Cassandra, identify shared tables/keyspaces

---

## 4. Shared Configuration Analysis

### Known Shared Config Files (from BOB Round 4)

| Config File | Lua | Python | Go | Ruby |
|---|---|---|---|---|
| `config.json` | `require("config")` | `Config.load()` | `config.LoadConfig()` | `Utils.load_config` |
| `features.json` | `require("features.lua")` | Via HTTP to Lua | Unknown | `Features.new()` |
| `redis.json` | `RedisHelper.new()` | `RedisClient()` | `redis.NewClient()` | Unknown |

### Improvement Opportunity
- Create `READS_CONFIG` edges from File nodes to shared config files
- This links services without direct code dependencies
- A change to `redis.json` affects Lua, Python, Go, and Ruby -- the graph should show this

### What We Need from BOB
- Are there more shared config files?
- Environment variables that connect services
- Docker-compose environment/volume sharing

---

## 5. Service Topology Analysis

### Known Services (from BOB Round 4 / docker-compose)

| Service | Language | Purpose |
|---|---|---|
| OpenResty (nginx+Lua) | Lua | Core request handling, fraud assessment |
| Generator | Ruby | Build-time JS/config generation |
| Cacher | Ruby | Redis cache management |
| Cassandra Communicator | ? | Cassandra proxy |
| Model Prediction | Go | ML model inference |
| Event Extractor | Python | Event -> Kinesis pipeline |
| Aggregator | Python | Task batching |
| Poller | Python | Task execution from SQS |
| Missioner | Python | Task queuing to SQS |
| Atlas | Python | IP geolocation lookup |
| Global Data | Python | MySQL alerted transaction storage |
| Geo | Python | Geo-location MySQL queries |

### Known Cross-Service Connections
```
JS (browser) --HTTP--> Nginx --Lua--> OpenResty
OpenResty --Unix socket--> Model Prediction (Go)
OpenResty --Unix socket--> Missioner (Python)
OpenResty --Unix socket--> Cassandra Communicator
OpenResty --Unix socket--> Atlas (Python)
OpenResty --Redis--> Redis
Missioner --SQS--> Poller (Python)
Poller --HTTP--> OpenResty (callback)
Poller --SQS<-- Aggregator (Python)
Event Extractor --Kinesis--> AWS
All services --Redis--> Redis
Global Data --MySQL--> MySQL
Geo --MySQL--> MySQL
Generator --ERB--> JS templates
Cacher --Redis--> Redis
```

### Improvement Opportunity
- Create `Service` nodes for each service
- Create `COMMUNICATES_WITH` edges with mechanism labels
- This gives a high-level architecture view queryable via MCP tools

---

## 6. Event System Analysis

### Known Event Patterns (from BOB Round 4)
- Lua emits events via dedicated event modules (`src/ato/events/*.lua`)
- Event extractor receives events (mechanism unknown -- need BOB confirmation)
- Events uploaded to Kinesis
- 20+ event types mentioned (BOB G1 showed `pinpoint_saturated_users`, `pinpoint_ato_dump`, etc.)

### Improvement Opportunity
- Detect event emission in Lua (`event:emit()` or similar patterns)
- Create `EMITS_EVENT` edges from Lua files to event type nodes
- Create `CONSUMES_EVENT` edges from event_extractor to those events
- This completes the Lua -> Python data flow for analytics

---

## 7. Nginx Deep Routing Analysis

### Current Limitation
Our endpoint linker uses `_location_index` built from parsed nginx locations. But we only detect 4 cross-language links. The problem is likely:
1. Not all nginx locations are being parsed
2. The dynamic routing (`router/main.lua` -> controller -> handler) isn't being followed
3. Go socket handler registration isn't matching

### From BOB Rounds 1 & 4
The nginx config has:
- Direct `*_by_lua_file` directives (4 files)
- Inline `*_by_lua_block` directives (5+ modules)
- `@router` named location -> `router/main.lua` -> dynamic dispatch
- URL pattern: `/{component}/controllers/{controller}/{action}`
- 6 controllers total (ato: 3, common: 2, malware: 1)

### Improvement Opportunity
- Parse ALL location blocks (including named locations and regex)
- Build static controller mapping: URL pattern -> controller file -> handler directory
- Create `HANDLES_ENDPOINT` edges from handler files to endpoint nodes
- Link JS `Container._sendRequest` URLs to their handling chain

### What We Need from BOB
- Complete list of ALL nginx location blocks with their targets
- ALL upstream blocks with server addresses
- Whether there are multiple nginx config files (includes)
- Any dynamic routing via nginx `map` blocks or variables

---

## 8. Cron and Timer Dependencies

### Known Patterns (from BOB Round 4)
- Cron templates in `src/ato/cron/template/`
- Shell scripts in `src/ato/scripts/`
- Lua cron scripts: `super_users.lua`, `backcolor.lua`, `update_monitoring.lua`
- Pattern: cron -> shell script -> Lua script -> require modules + Redis access

### Improvement Opportunity
- Parse cron templates to extract schedules and script paths
- Follow shell scripts to find their Lua/Python script targets
- Create `SCHEDULED_BY` edges from scripts to cron entries
- Create `CRON_ENTRY` nodes with schedule metadata

### What We Need from BOB
- ALL cron jobs with schedules and targets
- ALL ngx.timer background tasks
- ALL Python background threads/loops

---

## 9. Priority-Ranked Improvement Opportunities

### Tier 1: High Impact, Achievable Now
| # | Improvement | Expected New Edges | Effort |
|---|---|---|---|
| 1 | Fix Go Redis detection (0 -> ~30 accesses) | 30+ REDIS_READS/WRITES | Low -- debug existing resolver |
| 2 | Fix JS HTTP detection (.js.erb Container._sendRequest) | 8 HTTP_CALLS | Low -- add pattern to JS parser |
| 3 | Fix mission dispatch detection (4 -> 74) | 70 DISPATCHES_MISSION | Low -- debug existing resolver |
| 4 | Add Python Redis detection | 10-20 REDIS_READS/WRITES | Medium -- new detection patterns |
| 5 | Deeper nginx location parsing -> endpoint linking | 20+ HANDLES_ENDPOINT | Medium -- extend nginx parser |

### Tier 2: Medium Impact, Moderate Effort
| # | Improvement | Expected New Edges | Effort |
|---|---|---|---|
| 6 | Unix socket connection mapping | 10-15 SOCKET_CONNECTS | Medium |
| 7 | Shared Redis key pattern linking | 50+ SHARED_DATA | Medium-High |
| 8 | Event emission/consumption tracking | 40+ EMITS/CONSUMES | Medium |
| 9 | Python HTTP call detection (requests lib) | 5-10 HTTP_CALLS | Low-Medium |
| 10 | Cron/timer dependency tracking | 10-20 SCHEDULED_BY | Medium |

### Tier 3: Lower Priority but Valuable
| # | Improvement | Expected New Edges | Effort |
|---|---|---|---|
| 11 | MySQL/Cassandra access detection | 10-30 DB_READS/WRITES | Medium |
| 12 | S3/MinIO access detection | 5-10 STORES_OBJECT | Medium |
| 13 | Shared config file linking | 10-20 READS_CONFIG | Low |
| 14 | SQS queue modeling | 5-10 PRODUCES_TO/CONSUMES_FROM | Medium |
| 15 | Service topology nodes and edges | 20-30 SERVICE edges | Medium |
| 16 | Kinesis stream modeling | 3-5 STREAMS_TO | Low |

---

## 10. New Graph Schema Elements Needed

### New Node Types
| Node | Purpose |
|---|---|
| `Service` | Docker/systemd service (e.g., model_prediction, poller) |
| `Queue` | SQS queue or Redis list used as queue |
| `EventType` | Named event type (e.g., pinpoint_saturated_users) |
| `CronJob` | Scheduled task with schedule expression |
| `ConfigFile` | Shared configuration file |
| `UnixSocket` | Unix domain socket endpoint |
| `DatabaseTable` | MySQL/Cassandra table |
| `S3Bucket` | Object storage bucket |
| `KinesisStream` | Event stream |

### New Edge Types
| Edge | From | To | Purpose |
|---|---|---|---|
| `COMMUNICATES_WITH` | Service | Service | Service-level dependency |
| `SOCKET_CONNECTS` | File | UnixSocket | File connects to socket |
| `SOCKET_LISTENS` | File | UnixSocket | File creates/listens on socket |
| `EMITS_EVENT` | Function | EventType | Function emits named event |
| `CONSUMES_EVENT` | Service | EventType | Service processes event |
| `READS_CONFIG` | File | ConfigFile | File reads config |
| `PRODUCES_TO` | File | Queue | File enqueues messages |
| `CONSUMES_FROM` | File | Queue | File dequeues messages |
| `QUERIES_TABLE` | File | DatabaseTable | File reads from DB table |
| `WRITES_TABLE` | File | DatabaseTable | File writes to DB table |
| `STORES_OBJECT` | File | S3Bucket | File writes to S3 |
| `LOADS_OBJECT` | File | S3Bucket | File reads from S3 |
| `SCHEDULED_BY` | File | CronJob | File executed on schedule |
| `REDIS_PUBLISHES` | File | RedisKey | File publishes to channel |
| `REDIS_SUBSCRIBES` | File | RedisKey | File subscribes to channel |
| `SHARED_REDIS_KEY` | File | File | Two files share Redis key pattern |

---

## 11. What the BOB Investigation Questions Will Unlock

### Section A (IPC Inventory) -> Sections 2 & 9
Confirms all communication mechanisms exist and provides code examples for detection patterns.

### Section B (Database Access) -> Sections 3 & 9
Completes the database matrix, enables MySQL/Cassandra/S3 detection, and maps shared data flows.

### Section C (Shared Config) -> Section 4
Lists all config files and env vars for config-based edge creation.

### Section D (Service Topology) -> Section 5
Provides the complete service map for Service node creation.

### Section E (Deployment) -> Implicit dependencies
Reveals boot-order dependencies and infrastructure requirements.

### Section F (Events & Logging) -> Section 6
Maps the complete event pipeline for event edge creation.

### Section G (External Services) -> Additional edges
Catalogs all external connections.

### Section H (Nginx Deep Dive) -> Section 7
Enables complete endpoint-to-handler linking.
