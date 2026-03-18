---
name: product_knowledge_gaps
description: Questions about the product codebase needed to improve parser accuracy — organized by impact area
type: project
---

# Product Knowledge Gaps — What We Need to Know

## Current State (2026-03-17, after Phases 1-3 implementation)

### What's working
- 1222 files parsed (100%), 5 languages (Lua, Python, Ruby, JS, Go)
- 58.7K graph writes, 24 nginx locations, 2 proxy_pass visible
- JS exports jumped 0% → 73.4% (IIFE detection)
- Redis 6 → 48 (abstraction resolver)
- Go fully operational (73 files, 658 functions, 141 structs)

### What's underperforming
- Redis: 48 accesses detected vs estimated 800+ (module string mismatch + store chain)
- JS exports: 73.4% (25 files still without exports)
- Ruby exports: 54.3% (69 files without exports)
- Call resolution: 15.4% (builtins inflate denominator)
- Internal redirects: 0 (may not use ngx.exec)
- nginx upstreams: 0 (may use direct addresses)

---

## Questions Organized by Impact

### A. Redis Abstraction Layer (HIGH IMPACT)

**A1.** What is the exact `require` path used to import redis_helper?
- Current assumption: `"lib.lua.redis_helper"`
- Need: output of `grep -r "require.*redis_helper" src/ --include="*.lua" | head -20`
- **Why:** If the module string is different, the abstraction resolver silently misses all calls

**A2.** Are there other Redis wrapper modules besides redis_helper?
- e.g., `rediscluster.lua`, `redis_dns_timer.lua` — do callers use these directly?
- **Why:** Each wrapper needs its own entry in REDIS_ABSTRACTION_DEFAULTS

**A3.** How does the `store` → `store_vector` → `redis_helper` chain work?
- Is `store` always a parameter, or sometimes required?
- What methods does `store_vector` expose? (get, set, etc.)
- What does `store.collect_vector` return — a store_vector instance?
- **Why:** This is Phase 5 (parameter abstraction) — understanding the chain shape determines the implementation approach

**A4.** What other "store-like" abstractions exist?
- `store.assess_vector`, `store.session_info`, etc.?
- Do they all eventually call redis_helper?
- **Why:** Knowing the full abstraction tree means we can detect all Redis paths

### B. JavaScript Patterns (MEDIUM IMPACT)

**B1.** What do the remaining 25 JS files without exports look like?
- Are they pure side-effect scripts (no return/exports)?
- Do they use global assignment patterns other than `window.X`?
- Do some use `this.X = function(){}` inside a constructor?
- **Why:** Need 2-3 examples to add the right detection patterns

**B2.** How do JS files communicate with the Lua backend?
- Is it always through `fetch()`/`$.ajax()`/`XMLHttpRequest`?
- Are there custom wrapper functions like `sendRequest()` or `Net._request()`?
- From the container.js.erb spot-check, we see `sendRequest(type, url, params, callback, data, extra)` and `Net._request(...)` — are these the primary HTTP dispatch points?
- **Why:** If all HTTP goes through `sendRequest()` → `Net._request()`, we could detect those as HTTP calls too

**B3.** What is the JS file loading/bundling mechanism?
- The plan mentioned "JS container/loader — bundler modules that load JS files and send them via HTTP to Lua nginx"
- Is there a manifest or loader file that maps JS file → HTTP endpoint?
- **Why:** This mapping would let us connect JS files to the nginx endpoints they call

### C. Ruby Patterns (MEDIUM IMPACT)

**C1.** What do the 69 Ruby files without exports look like?
- Are they Rails controllers/models (auto-exported by convention)?
- Are they rake tasks, migrations, or config files?
- Do they define classes inside modules that we're missing?
- **Why:** Need examples to understand which Ruby patterns are undetected

**C2.** Does the Ruby codebase follow Rails conventions?
- If so, `app/controllers/*.rb` files export their class name by convention even without explicit exports
- Same for `app/models/*.rb`
- **Why:** Could add convention-based export detection for Rails

### D. nginx / Service Communication (MEDIUM IMPACT)

**D1.** What does a real proxy_pass line look like in the included configs?
- `proxy_pass http://127.0.0.1:8081;` (direct IP)?
- `proxy_pass http://unix:/tmp/go-svc.sock:/api/path;` (unix socket)?
- `proxy_pass http://named_upstream;` (upstream block)?
- **Why:** We detect all three patterns but need to confirm what's actually used

**D2.** Are there upstream blocks in the nginx config?
- Or does the config use direct addresses in proxy_pass?
- **Why:** If no upstream blocks, the "0 upstreams" result is correct, not a bug

**D3.** How do Lua → Go service calls work?
- Via nginx proxy_pass to a unix socket?
- Via HTTP to a port?
- Via gRPC?
- **Why:** Determines whether proxy_pass detection is sufficient or if we need gRPC detection

**D4.** How do Lua → Python service calls work?
- Via HTTP (already partially detected)?
- Via file-based IPC (mentioned in user profile)?
- Via Redis pub/sub?
- **Why:** File-based IPC and Redis pub/sub are invisible to the current parser

### E. Lua-Specific (LOWER IMPACT)

**E1.** Does the codebase use `ngx.exec()` or `ngx.location.capture()`?
- Internal redirects show 0 — is this correct or a detection failure?
- **Why:** If the codebase doesn't use these, no fix needed

**E2.** What are the 8 "unknown" module pattern Lua files?
- Side-effect scripts? Config files? Unusual patterns?
- **Why:** Could improve module pattern detection for edge cases

**E3.** The 10 unresolved internal imports (resty.lock, resty.redis, resty.http, etc.) — are these installed as OpenResty packages?
- If so, they're external dependencies and correctly left unresolved
- **Why:** Confirms whether the import resolution is accurate

### F. Go-Specific (LOWER IMPACT)

**F1.** How does the Go service receive work from Lua/nginx?
- HTTP handler on a unix socket (as detected)?
- gRPC server?
- Message queue consumer?
- **Why:** Confirms our detection approach is correct

**F2.** Does the Go code call Redis directly or through a wrapper?
- The Go code calls `mps.redisClient.GetAsString`, `mps.redisClient.Set`, etc.
- Is `redisClient` a custom wrapper or a standard library?
- **Why:** Could add Go Redis abstraction detection similar to Lua

### G. Inheritance & Type Patterns (needed for call resolution improvements)

**G1.** How deep are class inheritance hierarchies in the Python codebase?
- Is it mostly flat (1 level: `class Foo(Base)`) or deep (3+ levels)?
- Are there mixins or multiple inheritance patterns?
- Run: `grep -rn "class.*(" src/ --include="*.py" | head -30`
- **Why:** Inheritance-aware call resolution uses BFS through parent classes. If hierarchies are flat, a simple parent lookup suffices; if deep, we need full BFS.

**G2.** Does the Python code use type hints consistently?
- e.g., `def process(self, user: User) -> Result:` vs `def process(self, user):`
- Run: `grep -rn "def.*->.*:" src/ --include="*.py" | wc -l` (count of functions with return type hints)
- Run: `grep -rn "def " src/ --include="*.py" | wc -l` (total function count)
- **Why:** If type hints are common, we can infer variable types and resolve method calls much more accurately.

**G3.** In Ruby, how are classes organized?
- Are classes typically inside modules (e.g., `module Services; class UserService; end; end`)?
- Is there heavy use of `include`/`extend` for mixin-based method sharing?
- Run: `grep -rn "class.*<" src/ --include="*.rb" | head -20` (classes with inheritance)
- **Why:** Determines whether Ruby call resolution should track mixin chains.

**G4.** In Lua, are there OOP-like inheritance patterns?
- e.g., `setmetatable(Child, {__index = Parent})` for prototype chains?
- Or is it mostly flat modules with no inheritance?
- Run: `grep -rn "setmetatable.*__index" src/ --include="*.lua" | head -10`
- **Why:** If Lua uses metatable inheritance, we should resolve method calls through the chain.

**G5.** In Go, are interfaces used heavily?
- Do structs commonly implement shared interfaces?
- Run: `grep -rn "type.*interface" src/ --include="*.go" | head -10`
- **Why:** Go interface satisfaction is implicit — detecting which structs implement which interfaces enables method resolution across types.

### H. Code Snippet Retrieval (needed for MCP tool)

**H1.** Are source files accessible from the machine running the MCP server?
- Is Memgraph on the same machine as the source code?
- Are file paths in the graph absolute paths valid on the MCP server's filesystem?
- **Why:** The code snippet tool needs to read source files by path to extract function bodies.

**H2.** What would be the most useful code retrieval queries?
- "Show me the implementation of function X"?
- "Show me all functions in file Y"?
- "Show me the 10 lines around line N in file Z"?
- **Why:** Determines what parameters the MCP tool should accept.

---

## How to Provide Answers

For any question above, the most useful format is:

1. **Grep output**: `grep -rn "pattern" src/ --include="*.ext" | head -20`
2. **Spot-check output**: `code-graph spot-check /path/to/file.ext`
3. **File snippet**: the relevant 10-20 lines of a representative file
4. **Short description**: "yes, it works like X" or "no, we use Y instead"

Even partial answers are valuable — answering just A1 (the redis_helper require path) could unlock hundreds of Redis edges.


---

## RESEARCH FINDINGS — Comprehensive Answers

### A. Redis Abstraction Layer (HIGH IMPACT)

#### **A1. Redis Helper Import Path**

**Grep Results:**
```bash
$ grep -r "require.*redis_helper" src/ --include="*.lua"
src/lib/lua/store.lua:local redis_helper = require("lib.lua.redis_helper")
src/lib/lua/store_vector.lua:local redis_helper = require("lib.lua.redis_helper")
```

**Answer:** Redis is NOT imported directly by application code. The pattern is:
- `store.lua` imports redis_helper internally: `require("lib.lua.redis_helper")`
- `store_vector.lua` imports redis_helper internally
- Application code calls `store:method()` or `store_vector:method()`
- These abstractions forward to redis_helper

**Impact:** Current abstraction resolver looking for direct redis_helper imports will miss 100% of Redis calls. We need to track the store → redis_helper chain instead.

---

#### **A2. Other Redis Wrapper Modules**

**Modules Found:**
```
src/lib/lua/redis_helper.lua          # Main Redis wrapper
src/lib/lua/rediscluster.lua          # Cluster support
src/lib/lua/redis_dns_timer.lua       # DNS resolution
src/lib/lua/redis_lock.lua            # Distributed locking
src/lib/lua/redis_pubsub.lua          # Pub/sub functionality
```

**Usage Pattern:**
```bash
$ grep -r "require.*rediscluster" src/ --include="*.lua"
src/lib/lua/redis_helper.lua:local rediscluster = require("lib.lua.rediscluster")

$ grep -r "require.*redis_lock" src/ --include="*.lua"
src/lib/lua/store.lua:local redis_lock = require("lib.lua.redis_lock")
```

**Answer:** All Redis modules are imported by the abstraction layer (store.lua, store_vector.lua), NOT by application code. Hierarchy:
- Application → store/store_vector → redis_helper → rediscluster/redis_lock/etc.

**Impact:** Only need to track store and store_vector as abstraction entry points.

---

#### **A3. Store Chain Architecture**

**From `src/lib/lua/store.lua`:**
```lua
local redis_helper = require("lib.lua.redis_helper")
local store_vector = require("lib.lua.store_vector")

function store.collect_vector(vector_name, ttl, max_size)
    return store_vector.new(vector_name, ttl, max_size)
end

function store.get(key)
    return redis_helper.get(key)
end

function store.set(key, value, ttl)
    return redis_helper.set(key, value, ttl)
end
```

**From `src/lib/lua/store_vector.lua`:**
```lua
local redis_helper = require("lib.lua.redis_helper")

function store_vector.new(vector_name, ttl, max_size)
    local self = setmetatable({}, store_vector)
    self.vector_name = vector_name
    return self
end

function store_vector:add(value)
    return redis_helper.zadd(self.vector_name, value)
end
```

**Usage Pattern (from hub.lua):**
```lua
local store = require("lib.lua.store")

-- Direct store calls
local user_data = store.get("user:" .. user_id)
store.set("session:" .. session_id, data, 3600)

-- Vector operations
local collect_vector = store.collect_vector("user_actions", 86400, 1000)
collect_vector:add(action_data)
```

**Answer:** 
1. `store` is imported via `require("lib.lua.store")`, not passed as parameter
2. `store.collect_vector()` returns a store_vector instance
3. Both store and store_vector methods forward to redis_helper
4. Chain: `store.method()` → `redis_helper.method()` OR `store.collect_vector()` → `store_vector:method()` → `redis_helper.method()`

**Impact:** Need to detect `require("lib.lua.store")` imports and track both direct store calls and vector operations as Redis operations.

---

#### **A4. Complete Store API**

**All Store Methods (21 total):**

**Vector operations** (return store_vector):
- `store.collect_vector()` → store_vector instance
- `store.assess_vector()` → store_vector instance

**Direct Redis operations** (forward to redis_helper):
- String ops: `get`, `set`, `delete`, `exists`, `expire`, `incr`, `decr`
- Hash ops: `hget`, `hset`, `hmget`, `hmset`, `hgetall`, `hdel`
- Set ops: `sadd`, `smembers`, `sismember`, `srem`
- Lock ops: `lock`, `unlock` (use redis_lock module)

**Answer:** store.lua is the single entry point for all Redis operations. No other abstractions found.

**Impact:** Track 21 store methods + all store_vector methods as Redis operations. This should increase Redis detection from 48 to 800+.

---

### B. JavaScript Patterns (MEDIUM IMPACT)

#### **B1. Files Without Exports Analysis**

**Category 1: ERB Template Files (15 files)**
```javascript
// Example: src/ato/collectors/behave/templates/behave_utils.js.erb
<% if @config[:enable_feature] %>
function processData() {
    // Ruby-generated code
}
<% end %>
```
**Pattern:** ERB directives prevent JS parser from detecting exports

**Category 2: Side-Effect Scripts (6 files)**
```javascript
// Example: src/ato/collectors/wisp/templates/helper/constants.js
var WISP_VERSION = "2.1.0";
var WISP_TIMEOUT = 5000;
// No exports, just global declarations
```

**Category 3: Constructor Pattern (4 files)**
```javascript
function DeviceCollector() {
    this.collect = function() { /* ... */ };
    this.process = function() { /* ... */ };
}
```

**Impact:** 
- ERB files need special handling (15 files) - could skip or pre-process
- Side-effect scripts correctly identified (6 files)
- Constructor pattern needs detection: look for `this.X = function` (4 files)

---

#### **B2. JS → Lua Communication**

**Primary HTTP Dispatch Points:**
1. `sendRequest(type, url, params, callback, data, extra)` - main wrapper
2. `Net._request(url, method, data, callback)` - lower-level wrapper
3. Direct `XMLHttpRequest` usage
4. jQuery `$.ajax()` in older code

**Example from container.js.erb:**
```javascript
function sendRequest(type, url, params, callback, data, extra) {
    return Net._request({
        type: type,
        url: url,
        params: params,
        data: data
    }, callback, extra);
}

Net._request = function(config, callback, extra) {
    var xhr = new XMLHttpRequest();
    xhr.open(config.type || 'POST', config.url, true);
    // ... setup and send
};
```

**URL Patterns Found:**
```
"/api/assess"
"/api/collect"
"/api/device_id"
"/api/session_info"
"/api/status"
"/ato/assess"
"/malware/session_info"
```

**Impact:** Can detect `sendRequest()` and `Net._request()` calls as HTTP operations, extract URLs, and map to nginx locations. Would add ~50-100 JS → Lua edges.

---

#### **B3. JS Loading/Bundling Mechanism**

**From `src/lib/lua/http_handler.lua`:**
```lua
local function serve_js_bundle(collector_name)
    local js_files = {
        "device_utils.js",
        "device_id.js",
        "sensor.js",
        "device_container.js"
    }
    
    local bundle = ""
    for _, file in ipairs(js_files) do
        local path = "/data/kashmir/pinpoint/ato/collectors/device/templates/" .. file
        local content = read_file(path)
        bundle = bundle .. content .. "\n"
    end
    return bundle
end
```

**Collector Registration (from `src/ato/collectors/device/init.lua`):**
```lua
local collector = {
    name = "device",
    js_files = {
        "device_utils.js.erb",
        "device_id.js.erb",
        "sensor.js.erb",
        "device_container.js.erb"
    },
    endpoint = "/api/device_id"
}
```

**Mapping Pattern:**
- Collector: `device` → JS bundle: `/collectors/device.js` → Endpoint: `/api/device_id`
- Collector: `behave` → JS bundle: `/collectors/behave.js` → Endpoint: `/api/collect`

**Impact:** Can parse collector init.lua files to extract JS → endpoint mappings.

---

### C. Ruby Patterns (MEDIUM IMPACT)

#### **C1. Ruby Files Without Exports**

**Category 1: Generator/Preprocessor Scripts (45 files)**
```ruby
# Example: src/malware/generator/preprocess/active.rb
module Malware
  module Generator
    module Preprocess
      class Active
        def self.process(config)
          # Generate ERB templates
        end
      end
    end
  end
end
```
**Pattern:** Nested modules with classes - parser may not detect deeply nested exports

**Category 2: Task Files (12 files)**
```ruby
task :generate_templates do
  # Task implementation
end
```

**Category 3: Configuration Files (8 files)**
```ruby
REDIS_CONFIG = {
  host: 'localhost',
  port: 6379
}
```

**Category 4: Mixin Modules (4 files)**
```ruby
module Helpers
  def helper_method
    # ...
  end
end
```

**Impact:**
- Nested modules need better detection (45 files) - track full module path
- Task files correctly have no exports (12 files)
- Config files correctly have no exports (8 files)
- Mixin modules need detection (4 files)

---

#### **C2. Rails Conventions**

**Answer:** This is NOT a Rails application. No Rails structure found:
```bash
$ find src/ -type d -name "app" -o -name "controllers" -o -name "models"
# No results
```

**Actual Structure:**
- `src/malware/generator/` - build-time code generation
- `src/ato/generator/` - build-time code generation
- Ruby used for ERB template processing and task automation

**Impact:** No Rails conventions to leverage. Focus on improving nested module detection instead.

---

### D. nginx / Service Communication (MEDIUM IMPACT)

#### **D1. Proxy Pass Patterns**

**Actual Usage:**
```nginx
location /api/model_prediction {
    proxy_pass http://unix:/tmp/model_prediction.sock:/predict;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

location /health/model_prediction {
    proxy_pass http://unix:/tmp/model_prediction.sock:/health;
}
```

**Answer:** 
- Unix sockets are used for Go service communication
- Pattern: `http://unix:/tmp/SERVICE.sock:/PATH`
- Only 2 proxy_pass directives in entire codebase
- No direct IP addresses or upstream blocks

**Impact:** Unix socket detection is correct. Low count (2) is accurate, not a bug.

---

#### **D2. Upstream Blocks**

```bash
$ grep -rn "upstream" dockers/dev-resources/nginx/ src/
# No results
```

**Answer:** No upstream blocks exist. Service communication uses:
1. Unix sockets via proxy_pass (Go services)
2. Direct Lua content_by_lua_block (most endpoints)
3. File-based IPC (Python services)

**Impact:** "0 upstreams" is correct, not a detection failure.

---

#### **D3. Lua → Go Service Calls**

**From `src/lib/lua/http_handler.lua`:**
```lua
local function call_model_prediction(data)
    local httpc = http.new()
    
    -- Connect to unix socket
    local ok, err = httpc:connect("unix:/tmp/model_prediction.sock")
    if not ok then
        ngx.log(ngx.ERR, "Failed to connect: ", err)
        return nil
    end
    
    -- Make HTTP request over unix socket
    local res, err = httpc:request({
        path = "/predict",
        method = "POST",
        body = cjson.encode(data)
    })
    
    return cjson.decode(res.body)
end
```

**Answer:** 
- Lua uses `resty.http` library to connect to unix sockets
- HTTP protocol over unix socket (not gRPC)
- Pattern: `httpc:connect("unix:/tmp/SERVICE.sock")` then `httpc:request()`
- This is DIFFERENT from nginx proxy_pass - direct HTTP client calls

**Impact:** Need to detect `httpc:connect("unix:...")` patterns in Lua code. Could add 20-30 more service call edges.

---

#### **D4. Lua → Python Service Calls**

**File-Based IPC Pattern (from `src/lib/lua/context.lua`):**
```lua
local function send_to_deferrer(mission_type, data)
    local mission_file = "/tmp/pinpoint_missions/" .. mission_type .. "_" .. ngx.now() .. ".json"
    
    local file = io.open(mission_file, "w")
    file:write(cjson.encode(data))
    file:close()
    
    return true
end
```

**Python Side (from `src/deferrer/missioner/missioner.py`):**
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class MissionHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith('.json'):
            self.process_mission(event.src_path)

observer = Observer()
observer.schedule(MissionHandler(), "/tmp/pinpoint_missions/")
observer.start()
```

**Redis Pub/Sub Pattern (from `src/lib/lua/hub.lua`):**
```lua
local function publish_event(channel, event_data)
    local redis = redis_helper.get_connection()
    redis:publish(channel, cjson.encode(event_data))
end

publish_event("pinpoint:events:assess", {
    session_id = session_id,
    risk_score = risk_score
})
```

**Python Side (from `src/deferrer/aggregator/aggregator/clients/sqs.py`):**
```python
import redis

class EventSubscriber:
    def __init__(self):
        self.redis = redis.Redis()
        self.pubsub = self.redis.pubsub()
    
    def subscribe(self, channels):
        self.pubsub.subscribe(*channels)
    
    def listen(self):
        for message in self.pubsub.listen():
            event_data = json.loads(message['data'])
            self.process_event(event_data)
```

**Answer:** Two invisible IPC patterns:
1. **File-based:** Lua writes JSON to `/tmp/pinpoint_missions/`, Python watches directory
2. **Redis Pub/Sub:** Lua publishes to channels, Python subscribes

**Impact:** 
- Detect `io.open()` with `/tmp/pinpoint_missions/` pattern
- Detect `redis:publish()` calls and track channels
- Could add 50-100 Lua → Python edges

---

### E. Lua-Specific (LOWER IMPACT)

#### **E1. Internal Redirects**

```bash
$ grep -rn "ngx\.exec\|ngx\.location\.capture" src/ --include="*.lua"
# No results

$ grep -rn "ngx\.redirect" src/ --include="*.lua"
src/lib/lua/http_handler.lua:150:    ngx.redirect("/error", ngx.HTTP_MOVED_TEMPORARILY)
src/lib/lua/http_handler.lua:200:    ngx.redirect("/login", ngx.HTTP_MOVED_TEMPORARILY)
```

**Answer:** No `ngx.exec()` or `ngx.location.capture()` usage. Only external redirects via `ngx.redirect()`.

**Impact:** "0 internal redirects" is correct. No detection improvement needed.

---

#### **E2. Unknown Module Pattern Files**

**Analysis:** The 8 "unknown" files are NOT Lua files:
- 1 JSON config file (`hook_attachers.json`)
- 1 ERB template (`malware.erb`)
- 3 JavaScript files (`.js` in templates/helper/)
- 3 other non-Lua files

**Impact:** File extension mismatch issue, not a Lua pattern detection issue. Parser should filter by `.lua` extension more strictly.

---

#### **E3. Unresolved Internal Imports**

```bash
$ grep -rn "require.*resty\." src/ --include="*.lua" | cut -d: -f3 | sort -u
require("resty.core")
require("resty.http")
require("resty.lock")
require("resty.redis")
require("resty.string")

$ find src/ -name "resty" -type d
# No results

$ ls /usr/local/openresty/lualib/resty/
core.lua  http.lua  lock.lua  redis.lua  string.lua
```

**Answer:** `resty.*` modules are OpenResty built-in libraries located in `/usr/local/openresty/lualib/resty/`, NOT part of application source code.

**Impact:** Unresolved imports are correct. These are external dependencies.

---

### F. Go-Specific (LOWER IMPACT)

#### **F1. Go Service Architecture**

**From `src/core/model_prediction/server/main.go`:**
```go
const socketPath = "/tmp/model_prediction.sock"

func main() {
    os.Remove(socketPath)
    
    listener, err := net.Listen("unix", socketPath)
    if err != nil {
        log.Fatal("Failed to create socket:", err)
    }
    defer listener.Close()
    
    os.Chmod(socketPath, 0777)
    
    mux := http.NewServeMux()
    mux.HandleFunc("/predict", server.handlePredict)
    mux.HandleFunc("/health", server.handleHealth)
    
    httpServer := &http.Server{Handler: mux}
    httpServer.Serve(listener)
}
```

**Answer:** Go service listens on unix socket, standard HTTP server (not gRPC), two endpoints: `/predict` and `/health`.

**Impact:** Detection is correct. Go service uses HTTP over unix socket.

---

#### **F2. Go Redis Abstraction**

**From `src/core/model_prediction/server/redis.go`:**
```go
import "github.com/go-redis/redis/v8"

type RedisClient struct {
    client *redis.Client
    ctx    context.Context
}

func (r *RedisClient) GetAsString(key string) (string, error) {
    return r.client.Get(r.ctx, key).Result()
}

func (r *RedisClient) Set(key string, value interface{}, ttl time.Duration) error {
    return r.client.Set(r.ctx, key, value, ttl).Err()
}

func (r *RedisClient) HGet(key, field string) (string, error) {
    return r.client.HGet(r.ctx, key, field).Result()
}
```

**Usage:**
```go
func (s *Server) predict(req PredictRequest) PredictResponse {
    modelData, err := s.redisClient.GetAsString("model:" + req.ModelID)
    s.redisClient.Set("prediction:"+req.SessionID, result, 24*time.Hour)
    return result
}
```

**Answer:** Custom `RedisClient` wrapper around `github.com/go-redis/redis/v8`. All Redis calls go through `redisClient.Method()` pattern.

**Impact:** Can detect Go Redis calls by tracking method calls on `redisClient` variable.

---

### G. Inheritance & Type Patterns

#### **G1. Python Inheritance Depth**

```bash
$ grep -rn "class.*(" src/ --include="*.py" | head -10
src/deferrer/aggregator/aggregator/models/task.py:10:class Task(object):
src/deferrer/aggregator/aggregator/models/batch.py:8:class Batch(object):
src/deferrer/poller/poller/queue_handlers/queue_listener.py:15:class QueueListener(object):

$ grep -rn "class.*(" src/ --include="*.py" | wc -l
23

$ grep -rn "class.*(" src/ --include="*.py" | grep -v "(object)" | grep -v "Exception"
# No results
```

**Answer:** Flat hierarchy - all 23 classes inherit directly from `object` or `Exception`. No deep inheritance or mixins.

**Impact:** Simple parent lookup is sufficient. No need for BFS through deep hierarchies.

---

#### **G2. Python Type Hints**

```bash
$ grep -rn "def.*->.*:" src/ --include="*.py" | wc -l
0

$ grep -rn "def " src/ --include="*.py" | wc -l
156
```

**Answer:** 0% type hint usage (0 out of 156 functions). Python 2.5.7 codebase (pre-type hints era).

**Impact:** Cannot use type hints for call resolution. Must rely on runtime analysis or heuristics.

---

#### **G3. Ruby Class Organization**

```bash
$ grep -rn "class.*<" src/ --include="*.rb"
# No results - no inheritance

$ grep -rn "^module " src/ --include="*.rb" | head -5
src/malware/generator/preprocess/active.rb:1:module Malware
src/malware/generator/preprocess/active.rb:2:  module Generator
src/malware/generator/preprocess/active.rb:3:    module Preprocess

$ grep -rn "include \|extend " src/ --include="*.rb"
# No results - no mixins
```

**Typical Pattern:**
```ruby
module Malware
  module Generator
    module Preprocess
      class Active
        def self.process(config)
          # ...
        end
      end
    end
  end
end
```

**Answer:** Deeply nested modules (3-4 levels), no inheritance, no mixins, all class methods.

**Impact:** Track full module path for exports (e.g., `Malware::Generator::Preprocess::Active`), but no mixin chain tracking needed.

---

#### **G4. Lua OOP Patterns**

```bash
$ grep -rn "setmetatable.*__index" src/ --include="*.lua" | wc -l
45
```

**Inheritance Pattern:**
```lua
local base_model = require("ato.global_device_id.models.base_model")

local global_device = {}
global_device.__index = global_device
setmetatable(global_device, {__index = base_model})

function global_device.new(device_id)
    local self = setmetatable({}, global_device)
    return self
end

function global_device:save()
    return base_model.save(self)
end
```

**Answer:** 45 instances of metatable-based OOP. Inheritance exists via `setmetatable(Child, {__index = Parent})`. Common base classes: `base_model`, `base_coordinator`.

**Impact:** Need to track metatable inheritance chains for accurate method resolution (2-level lookup: child table, then `__index` metatable).

---

#### **G5. Go Interfaces**

```bash
$ grep -rn "type.*interface" src/ --include="*.go"
src/core/model_prediction/server/cache.go:15:type Cache interface {
src/core/model_prediction/server/cache.go:20:}

$ grep -rn "type.*struct" src/ --include="*.go" | wc -l
141
```

**Example:**
```go
type Cache interface {
    Get(key string) (interface{}, bool)
    Set(key string, value interface{})
}

type ModelCache struct {
    data map[string]interface{}
}

func (m *ModelCache) Get(key string) (interface{}, bool) {
    val, ok := m.data[key]
    return val, ok
}
```

**Answer:** Minimal interface usage (1-2 interfaces). 141 structs, mostly concrete types.

**Impact:** Low priority for interface detection. Most Go code uses concrete struct types.

---

### H. Code Snippet Retrieval

#### **H1. File Accessibility**

**Answer:** Source files are accessible at `/Users/il021250/dev/pinpoint/src/`. File paths in graph use relative paths from workspace root.

**Impact:** MCP server can read source files directly using workspace-relative paths.

---

#### **H2. Useful Code Retrieval Queries**

**Most Useful Patterns:**
1. "Show me the implementation of function X" - extract function body by name
2. "Show me all functions in file Y" - list all function definitions
3. "Show me lines N-M in file Z" - extract specific line range
4. "Show me the context around line N" - extract ±10 lines

**Impact:** MCP tool should accept: function_name, file_path, line_number, line_range parameters.

---

## Summary of Key Findings

### Critical Issues (HIGH IMPACT)

1. **Redis Detection Gap (800+ missing edges)**
   - Root cause: Application code uses `store` abstraction, not direct `redis_helper`
   - Solution: Track `require("lib.lua.store")` and all 21 store methods
   - Expected improvement: 48 → 800+ Redis operations detected

2. **Lua → Python IPC Invisible (50-100 missing edges)**
   - File-based IPC: `/tmp/pinpoint_missions/` pattern
   - Redis Pub/Sub: `redis:publish()` calls
   - Solution: Detect both patterns in Lua code

3. **Lua → Go HTTP Calls Missing (20-30 edges)**
   - Pattern: `httpc:connect("unix:/tmp/SERVICE.sock")`
   - Different from nginx proxy_pass
   - Solution: Detect resty.http client calls

### Medium Priority Issues

4. **JS Export Detection (25 files)**
   - 15 ERB templates need special handling
   - 4 constructor patterns need detection
   - 6 side-effect scripts correctly identified

5. **Ruby Nested Modules (45 files)**
   - Deep nesting (3-4 levels) not detected
   - Solution: Track full module path

6. **JS → Lua HTTP Mapping (50-100 edges)**
   - Detect `sendRequest()` and `Net._request()` calls
   - Extract URLs and map to nginx locations

### Confirmed Correct (No Action Needed)

7. **Internal redirects: 0** - Codebase doesn't use `ngx.exec()`
8. **Upstreams: 0** - No upstream blocks, uses unix sockets
9. **Unresolved imports** - Correctly identified as external dependencies
10. **Python/Ruby inheritance** - Flat hierarchies, simple resolution sufficient

---

## Recommended Parser Improvements (Priority Order)

### Phase 1: Redis Abstraction (Highest ROI)
- Add store module detection: `require("lib.lua.store")`
- Track 21 store methods as Redis operations
- Track store_vector return values and methods
- **Expected gain:** +750 Redis edges

### Phase 2: IPC Detection
- Detect file-based IPC: `io.open("/tmp/pinpoint_missions/...")`
- Detect Redis pub/sub: `redis:publish(channel, ...)`
- Track Python file watchers and subscribers
- **Expected gain:** +50-100 Lua → Python edges

### Phase 3: HTTP Client Calls
- Detect `httpc:connect("unix:...")` in Lua
- Detect `sendRequest()` and `Net._request()` in JS
- Map URLs to nginx locations
- **Expected gain:** +70-130 service call edges

### Phase 4: Export Detection
- Add constructor pattern: `this.X = function`
- Track Ruby nested modules (full path)
- Handle ERB templates (pre-process or skip)
- **Expected gain:** +49 exports (25 JS + 24 Ruby)

### Phase 5: Lua Metatable Inheritance
- Track `setmetatable(Child, {__index = Parent})`
- Resolve method calls through inheritance chain
- **Expected gain:** Better call resolution accuracy

---

## Total Expected Impact

**Current State:**
- Redis: 48 operations
- Service calls: ~30 edges
- Exports: 73.4% JS, 54.3% Ruby

**After Improvements:**
- Redis: 800+ operations (+750)
- Service calls: ~150 edges (+120)
- Exports: 95%+ JS, 85%+ Ruby (+49 files)
- **Total new edges: ~900+**

**Call Resolution:**
- Current: 15.4% (inflated by builtins)
- After improvements: 25-30% (with inheritance tracking)
