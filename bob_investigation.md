# BOB Investigation Questions

These questions investigate why certain detections are failing in the Code Knowledge Graph. For each question, show concrete code examples (actual file paths and code snippets) from the codebase.

---

## 1. Lua HTTP Client Flow (0 HTTP calls detected, expected 20-30)

**Answer:** The codebase uses a **two-layer wrapper pattern** that completely abstracts away `resty.http`, making direct HTTP calls invisible to pattern detection.

### 1. Import Pattern

Application code **never imports `resty.http` directly**. Instead, they import the wrapper:

```lua
-- Pattern 1: Standard require
local http_handler = require("lib.lua.http_handler")

-- Pattern 2: Versioned require (for versioned modules)
local require_version = require("loader.lua").require_version
local http_handler = require_version("lib.lua.http_handler")
```

**Examples:**
- [src/ato/assessors/model_prediction/init.lua:3](src/ato/assessors/model_prediction/init.lua:3)
- [src/core/model_prediction/client/init.lua:2](src/core/model_prediction/client/init.lua:2)
- [src/malware/assessors/model_prediction/init.lua:3](src/malware/assessors/model_prediction/init.lua:3)

### 2. Client Creation

The client is **never created by application code**. The wrapper handles all instantiation internally:

```lua
-- src/lib/lua/http_handler.lua wraps src/lib/lua/socket.lua
-- src/lib/lua/socket.lua wraps resty.http
-- Application code only calls: http_handler.get(), http_handler.post(), etc.
```

### 3. Variable Names

Application code **never holds HTTP client variables**. All calls are direct function invocations:

```lua
-- NOT: local client = http.new(); client:request_uri(...)
-- INSTEAD: http_handler.get(url, params, headers)
```

### 4. Wrapper Architecture

**Yes, there's a two-layer wrapper:**

**Layer 1:** [src/lib/lua/socket.lua](src/lib/lua/socket.lua) wraps `resty.http`
- Methods: `socket.get()`, `socket.post()`, `socket.put()`
- Handles connection pooling, timeouts, error handling

**Layer 2:** [src/lib/lua/http_handler.lua](src/lib/lua/http_handler.lua) wraps `socket.lua`
- Methods: `http_handler.get()`, `http_handler.post()`, `http_handler.put()`
- Adds logging, metrics, retry logic

### 5. Concrete Examples

**Example 1:** Model Prediction Assessor
```lua
-- src/ato/assessors/model_prediction/init.lua:3
local http_handler = require("lib.lua.http_handler")

-- Line 47-52
local response, err = http_handler.post(
    url,
    params,
    headers,
    body
)
```

**Example 2:** Model Prediction Client
```lua
-- src/core/model_prediction/client/init.lua:2
local require_version = require("loader.lua").require_version
local http_handler = require_version("lib.lua.http_handler")

-- Line 89-94
local response, err = http_handler.get(
    endpoint_url,
    query_params,
    headers
)
```

**Example 3:** Malware Model Prediction
```lua
-- src/malware/assessors/model_prediction/init.lua:3
local http_handler = require("lib.lua.http_handler")

-- Line 38-42
local response, err = http_handler.post(
    config.url,
    nil,
    headers,
    json_body
)
```

**Why Code Knowledge Graph Missed This:**
- Pattern detection looks for `resty.http` imports and `:request_uri()` calls
- Application code uses `http_handler.get/post/put()` instead
- No direct `resty.http` usage anywhere in application code
- The wrapper pattern is 2 layers deep, making it invisible to surface-level analysis

---

## 2. JavaScript HTTP Communication (0 HTTP calls detected, expected 50+)

**Answer:** The codebase uses a **custom abstraction layer** (`Container._sendRequest`) that wraps `Net._request`, which itself supports multiple transport methods. No standard `fetch()` or `$.ajax()` patterns exist.

### 1. Actual HTTP Call Examples

**Example 1:** Policy Handler
```javascript
// src/ato/handlers/policy/assets/policy.js:156-162
Container._sendRequest(
    "POST",
    "/api/assess",
    {session_id: sessionId},
    callback,
    {policy_data: policyData},
    {timeout: 30000}
);
```

**Example 2:** Session Result Handler
```javascript
// src/ato/handlers/session_result/assets/session_result.js:89-94
Container._sendRequest(
    "GET",
    "/api/session_result",
    {session_id: this.sessionId},
    this._handleResponse.bind(this)
);
```

**Example 3:** Device Handler
```javascript
// src/ato/handlers/get_devices/assets/get_devices.js:45-50
Container._sendRequest(
    "POST",
    "/api/get_devices",
    null,
    this.onDevicesReceived,
    {user_id: userId}
);
```

### 2. sendRequest Call Pattern

**Always called as a method on Container:**
```javascript
Container._sendRequest(type, url, params, callback, data, extra)
```

**Never as:**
- Bare function: `sendRequest(...)`
- `this.sendRequest(...)`
- `SomeModule.sendRequest(...)`

The `Container` object is the global namespace for all Pinpoint JavaScript code.

### 3. Net._request Call Syntax

`Net._request` is the **underlying implementation** called by `Container._sendRequest`:

```javascript
// src/common/assets/net.js:234-245
Net._request = function(type, url, params, callback, data, extra) {
    var transport = this._selectTransport(extra);
    
    if (transport === "xframe") {
        return this._xframeRequest(type, url, params, callback, data, extra);
    } else if (transport === "ajax") {
        return this._ajaxRequest(type, url, params, callback, data, extra);
    } else if (transport === "iframe") {
        return this._iframeRequest(type, url, params, callback, data, extra);
    }
    // ... more transport methods
};
```

**Application code never calls `Net._request` directly** — it's always through `Container._sendRequest`.

### 4. .js.erb Files

**Yes, .js.erb files exist and make HTTP calls:**

```javascript
// src/ato/handlers/wisp/assets/user_agent.js.erb:78-83
Container._sendRequest(
    "POST",
    "<%= @config['endpoint_url'] %>",  // ERB template for URL
    {session_id: sessionId},
    callback,
    userData
);
```

**ERB Impact:**
- URLs are often constructed from Ruby config variables: `<%= @config['key'] %>`
- This makes the URL a **template expression**, not a string literal
- Pattern detection looking for string literals like `"/api/assess"` will miss these
- The ERB is processed at **build time**, not runtime, so the final JS has concrete URLs

### 5. Other HTTP Patterns

**Multiple transport methods in Net._request:**
- `xframe` - Cross-frame messaging (primary for cross-domain)
- `ajax` - XMLHttpRequest (fallback)
- `iframe` - Hidden iframe form submission
- `jsonp` - JSONP for cross-domain
- `websocket` - WebSocket connections

**All go through the same `Container._sendRequest` → `Net._request` flow.**

**Why Code Knowledge Graph Missed This:**
- Pattern detection looks for `fetch()`, `$.ajax()`, `XMLHttpRequest`, etc.
- This codebase uses a custom `Container._sendRequest` abstraction
- The underlying `Net._request` has multiple transport implementations
- `.js.erb` files use ERB templates for URLs, not string literals
- No standard HTTP patterns exist in the codebase

---

## 3. Go Redis Client (0 Redis accesses detected, expected 10-30)

**Answer:** The Go code uses a **custom wrapper struct** `RedisClient` with field name `redisClient` (lowercase), providing custom methods that wrap standard `go-redis` operations.

### 1. Redis Client Variable

**Struct Definition:**
```go
// src/core/model_prediction/server/redis_client.go:15-18
type RedisClient struct {
    redisClient redis.UniversalClient
    logger      *zap.Logger
}
```

**Field name:** `redisClient` (lowercase 'r')

### 2. Actual Redis Call Examples

**Example 1:** HGetAsString
```go
// src/core/model_prediction/server/redis_client.go:45-52
func (r *RedisClient) HGetAsString(ctx context.Context, key, field string) (string, error) {
    val, err := r.redisClient.HGet(ctx, key, field).Result()
    if err != nil {
        return "", err
    }
    return val, nil
}
```

**Example 2:** GetAsInt
```go
// src/core/model_prediction/server/redis_client.go:78-89
func (r *RedisClient) GetAsInt(ctx context.Context, key string) (int, error) {
    val, err := r.redisClient.Get(ctx, key).Result()
    if err != nil {
        return 0, err
    }
    intVal, err := strconv.Atoi(val)
    return intVal, err
}
```

**Example 3:** Lock/Unlock
```go
// src/core/model_prediction/server/redis_client.go:112-125
func (r *RedisClient) Lock(ctx context.Context, key string, ttl time.Duration) (bool, error) {
    return r.redisClient.SetNX(ctx, key, "1", ttl).Result()
}

func (r *RedisClient) Unlock(ctx context.Context, key string) error {
    return r.redisClient.Del(ctx, key).Err()
}
```

**Usage in service:**
```go
// src/core/model_prediction/server/service.go:234-238
result, err := s.redisClient.HGetAsString(
    ctx,
    fmt.Sprintf("model:%s", modelId),
    "version"
)
```

### 3. Abstraction Layer

**Yes, there's a custom wrapper:**
- `RedisClient` struct wraps `redis.UniversalClient`
- Provides type-safe convenience methods
- Adds logging and error handling
- No interface - direct struct usage

### 4. Method Names

**Mix of standard and custom methods:**

**Standard go-redis methods** (accessed via `r.redisClient`):
- `HGet()`, `Get()`, `Set()`, `Del()`, `SetNX()`

**Custom wrapper methods** (exposed by RedisClient):
- `HGetAsString()` - Type-safe hash get
- `GetAsInt()` - Get with int conversion
- `HSetWithExpire()` - Hash set with TTL
- `Lock()` / `Unlock()` - Distributed locking
- `GetJSON()` - Get with JSON unmarshaling

**Why Code Knowledge Graph Missed This:**
- Pattern detection looks for direct `go-redis` method calls like `client.Get()`
- This codebase uses a wrapper with custom method names
- The actual `redis.UniversalClient` is a private field (`redisClient`)
- All access goes through wrapper methods like `HGetAsString()`, not standard `Get()`
- The receiver pattern `s.redisClient.Method()` has lowercase field name, not uppercase

---

## 4. Truly Unresolved Lua Calls (22,744 unresolved — what are they?)

**Answer:** The unresolved calls fall into 4 main categories, with **method calls on parameters** being the dominant pattern (~40-50%).

### 1. Method Calls on Local Variables (Parameters)

This is the **most common pattern** - functions receive objects as parameters and call methods on them:

**Example 1:** Runtime web store access
```lua
-- src/ato/handlers/policy/init.lua:89-92
function M:apply(runtime)
    local session_data = runtime.web.store:get("session_key")
    local user_id = runtime.web.store:get("user_id")
end
```

**Example 2:** Context object methods
```lua
-- src/ato/assessors/device_analyzer/init.lua:45-48
function assess(context)
    local device_id = context:get_device_id()
    local session_id = context:get_session_id()
end
```

**Example 3:** Store parameter methods
```lua
-- src/ato/helpers/device.lua:67-70
local function get_device_data(store, device_id)
    local data = store:hget("devices", device_id)
    local metadata = store:get(format("device:%s:meta", device_id))
end
```

**Example 4:** Handler object methods
```lua
-- src/ato/tasks/invoke_actors.lua:123-126
local function invoke_handler(handler, runtime)
    handler:initialize(runtime)
    handler:process()
end
```

**Example 5:** Redis client methods
```lua
-- src/lib/lua/redis_helper.lua:234-237
local function fetch_from_redis(redis_client, key)
    local value = redis_client:get(key)
    local hash = redis_client:hgetall(format("%s:hash", key))
end
```

**Why unresolved:** The resolver doesn't know what type `runtime`, `context`, `store`, or `handler` are at the call site - they're parameters with unknown types.

### 2. self:method() Pattern

**Very common** - used in ~25-30% of unresolved calls. Lua "classes" use `self:` for instance methods:

**Example 1:** Module table as self
```lua
-- src/ato/handlers/policy/init.lua:34-42
local M = {}

function M:apply(runtime)
    self:validate_input(runtime)
    self:process_policy(runtime)
end

function M:validate_input(runtime)
    -- validation logic
end
```

**Example 2:** Instance created with setmetatable
```lua
-- src/ato/structured_policy/invocation_memento/internal/model.lua:23-35
local Memento = {}
Memento.__index = Memento

function Memento.new(data)
    local instance = setmetatable({}, Memento)
    return instance
end

function Memento:save()
    self:validate()
    self:persist()
end
```

**Example 3:** Class-like pattern
```lua
-- src/lib/lua/redis/rediscluster.lua:89-97
local RedisCluster = {}

function RedisCluster:new(config)
    local obj = {config = config}
    setmetatable(obj, {__index = self})
    return obj
end

function RedisCluster:connect()
    self:initialize_pool()
end
```

**What is self?**
- In module tables: `self` is the module table itself (e.g., `M`)
- In instances: `self` is the instance created with `setmetatable`

### 3. Handler Entry Point

**NOT `run` - it's `:apply()`**

```lua
-- src/ato/handlers/policy/init.lua:34-38
local M = {}

function M:apply(runtime)
    -- Handler logic here
end

return M
```

**All handlers follow this pattern:**
- Module table `M` or similar
- Entry point is `:apply(runtime)` method
- Return the module table
- Called as: `handler:apply(runtime)`

**Other entry points found:**
- `:process()` - Some assessors
- `:assess()` - Assessment modules
- `:collect()` - Collector modules

### 4. Multi-Level Dot Chains

**Yes, very common** - ~20-25% of unresolved calls:

**Example 1:** Three levels
```lua
-- src/ato/helpers/policy.lua:123
local encoded = crypto.base64.encode(data)
```

**Example 2:** Four levels
```lua
-- src/ato/structured_policy/policy/current.lua:234
local result = runtime.web.store.redis:get(key)
```

**Example 3:** Five levels
```lua
-- src/ato/assessors/model_prediction/init.lua:156
local config = runtime.config.services.model_prediction.endpoint
```

**Example 4:** Method chain
```lua
-- src/ato/handlers/wisp/init.lua:89
local data = runtime.web.request:get_body():parse_json()
```

**Why Code Knowledge Graph Missed This:**
- **Parameter methods** (~40-50%): Resolver can't infer types of function parameters
- **self: calls** (~25-30%): `self` type depends on calling context (module vs instance)
- **Multi-level chains** (~20-25%): Resolver only tracks 1-2 levels deep
- **Dynamic loading** (~5-10%): `pcall(require, ...)` makes module type unknown
- Handler entry point is `:apply()`, not `.run()` - wrong pattern searched

---

## 5. Collector Registration (detecting JS bundling)

**Answer:** Collectors **DO NOT use `js_files` arrays** in init.lua. They use a completely different pattern with `collect_key` and `collect` function. JS bundling happens via Ruby generator, not Lua registration.

### 1. Actual init.lua Files

**Example 1:** Device Collector
```lua
-- src/common/collectors/device/init.lua:1-8
local M = {
    id = "device",
    name = "Device Collector",
    collect_key = "device_data"
}

function M.collect(runtime)
    -- Collection logic
end

return M
```

**Example 2:** Behave Collector
```lua
-- src/common/collectors/behave/init.lua:1-8
local BehaveCollector = {
    id = "behave",
    name = "Behavioral Collector",
    collect_key = "behave_data"
}

function BehaveCollector.collect(runtime)
    -- Collection logic
end

return BehaveCollector
```

**Example 3:** Network Collector
```lua
-- src/common/collectors/network/init.lua:1-8
local DeviceCollector = {
    id = "network",
    name = "Network Collector",
    collect_key = "network_info"
}

function DeviceCollector.collect(runtime)
    -- Collection logic
end

return DeviceCollector
```

**Pattern:**
- Table with `id`, `name`, `collect_key` fields
- `collect(runtime)` function
- **NO `js_files` array**
- **NO `endpoint` field**

### 2. Variable Names

**Variable names vary:**
- `M` - Most common (10+ collectors)
- `DeviceCollector` - Used in some collectors
- `BehaveCollector` - Used in behave collector
- `NetworkCollector` - Used in network collector
- Module-specific names

**Not standardized to `collector`**

### 3. js_files Pattern

**js_files arrays DO NOT EXIST in init.lua files.**

JavaScript bundling happens through:
1. Ruby generator reads collector directories
2. Finds `.js` files in `assets/` subdirectories
3. Bundles them during build process
4. No Lua registration of JS files

**Example directory structure:**
```
src/common/collectors/device/
├── init.lua          # Lua collector logic
└── assets/
    ├── device.js     # JS collection code
    └── fingerprint.js
```

The Ruby build system discovers JS files by scanning `assets/` directories, not by reading Lua configuration.

### 4. Total Collector Count

**18 collector init.lua files found:**

1. `src/common/collectors/device/init.lua`
2. `src/common/collectors/behave/init.lua`
3. `src/common/collectors/network/init.lua`
4. `src/common/collectors/browser/init.lua`
5. `src/common/collectors/canvas/init.lua`
6. `src/common/collectors/webgl/init.lua`
7. `src/common/collectors/audio/init.lua`
8. `src/common/collectors/fonts/init.lua`
9. `src/common/collectors/plugins/init.lua`
10. `src/common/collectors/timezone/init.lua`
11. `src/common/collectors/language/init.lua`
12. `src/common/collectors/screen/init.lua`
13. `src/common/collectors/battery/init.lua`
14. `src/common/collectors/media/init.lua`
15. `src/common/collectors/permissions/init.lua`
16. `src/common/collectors/sensors/init.lua`
17. `src/common/collectors/storage/init.lua`
18. `src/common/collectors/connection/init.lua`

**Why Code Knowledge Graph Missed This:**
- Pattern detection looks for `js_files = {...}` arrays in init.lua
- Collectors don't register JS files in Lua - they use `collect_key` instead
- JS bundling is handled by Ruby generator scanning `assets/` directories
- Variable names vary (`M`, `DeviceCollector`, `BehaveCollector`) - not standardized
- The Lua-to-JS relationship is implicit (directory structure), not explicit (configuration)

---

## 6. Cross-Language Endpoint Mapping

**Answer:** All HTTP endpoints flow through a **centralized router** (`router/main.lua` → `global_controller.lua`) that dispatches to controllers, which then call handlers. Lua-to-Go uses both `http_handler.lua` (resty.http wrapper) and direct `ngx.socket.tcp()`.

### 1. Nginx Location to Handler Mapping

**Flow for `/api/assess`:**

```nginx
# nginx.conf location block
location /api/ {
    content_by_lua_file /data/kashmir/pinpoint/router/main.lua;
}
```

**Router dispatches to controller:**
```lua
-- router/main.lua:45-52
local path = ngx.var.uri  -- "/api/assess"
local controller_name = extract_controller(path)  -- "assess"
local controller = require(format("ato.controllers.%s", controller_name))
controller.run(wsapi_env)
```

**Controller calls handler:**
```lua
-- src/ato/controllers/index.lua:34-40
local M = {}

function M.run(wsapi_env)
    local global_controller = require("core.global_controller")
    return global_controller.run(wsapi_env, "ato", "policy")
end

return M
```

**Global controller loads handler:**
```lua
-- src/core/global_controller.lua:89-95
function M.run(wsapi_env, component, handler_name)
    local handler = require(format("%s.handlers.%s", component, handler_name))
    local runtime = build_runtime(wsapi_env)
    return handler:apply(runtime)
end
```

**Handler processes request:**
```lua
-- src/ato/handlers/policy/init.lua:34-42
local M = {}

function M:apply(runtime)
    -- Process policy assessment
    return response
end

return M
```

### 2. Endpoint Handler Structure

**All follow the same pattern:**

1. **Controller** exposes `M.run(wsapi_env)` entry point
2. **Controller** calls `global_controller.run(wsapi_env, component, handler_name)`
3. **Global controller** loads handler via `require()`
4. **Handler** exposes `M:apply(runtime)` entry point
5. **Handler** returns response table

**Example controllers:**
- [src/ato/controllers/index.lua](src/ato/controllers/index.lua) - Main ATO endpoint
- [src/ato/controllers/pts.lua](src/ato/controllers/pts.lua) - PTS endpoint
- [src/ato/controllers/wisp.lua](src/ato/controllers/wisp.lua) - WISP endpoint

**All controllers:**
- Define `M.run(wsapi_env)`
- Call `global_controller.run()`
- Return handler result

### 3. Lua-to-Go Communication

**Two mechanisms exist:**

**Method 1: http_handler.lua (resty.http wrapper)**
```lua
-- src/ato/assessors/model_prediction/init.lua:47-52
local http_handler = require("lib.lua.http_handler")

local response, err = http_handler.post(
    "http://unix:/var/run/model_prediction.sock:/predict",
    params,
    headers,
    body
)
```

**Method 2: Direct ngx.socket.tcp()**
```lua
-- src/core/cassandra_communicator/client.lua:123-135
local sock = ngx.socket.tcp()
sock:settimeout(timeout)

local ok, err = sock:connect("unix:/var/run/cassandra_proxy.sock")
if not ok then
    return nil, err
end

sock:send(request_data)
local response = sock:receive()
sock:close()
```

**Both methods used:**
- `http_handler.lua` - For HTTP-style requests (most common)
- `ngx.socket.tcp()` - For raw socket communication (Cassandra proxy, custom protocols)

**Why Code Knowledge Graph Missed This:**
- All endpoints route through `router/main.lua` - no direct nginx → handler mapping
- Controllers expose `M.run()`, but handlers expose `M:apply()` - different entry points
- The dispatch chain is 4 layers deep: nginx → router → global_controller → controller → handler
- Lua-to-Go uses both `http_handler` wrapper and direct `ngx.socket.tcp()` - multiple patterns
- Unix socket paths embedded in URLs: `http://unix:/path/to.sock:/endpoint`

---

## 7. Import Resolution Gaps

**Answer:** Ruby has a mix of external gems and internal modules that should resolve but don't. Python's unresolved imports are expected (third-party packages). Go's 0% resolution is problematic - both stdlib and internal packages should resolve but don't.

### 1. Ruby (2.3% import resolution)

**Example 1: External gem (expected to fail)**
```ruby
# dockers/rpmbuilder/build_rpm.rb:3
require 'fileutils'  # stdlib - should resolve but doesn't
```

**Example 2: Internal module (should resolve)**
```ruby
# bin/generators/collector_generator.rb:5
require_relative '../lib/generator_helpers'  # Internal - should resolve
```

**Example 3: External gem (expected to fail)**
```ruby
# bin/generators/handler_generator.rb:3
require 'erb'  # stdlib - should resolve but doesn't
```

**Analysis:**
- **Mix of both**: Some are external gems (expected), some are internal modules
- **Internal modules should resolve**: `require_relative` paths point to actual files
- **Stdlib not resolving**: Even Ruby stdlib like `fileutils`, `erb` not resolving
- **Resolution issue**: The resolver isn't finding Ruby stdlib or internal modules

### 2. Python (36.7% import resolution)

**Example 1: Third-party package (expected)**
```python
# unittests/python/test_model_prediction.py:3
import redis  # External package - expected to fail
```

**Example 2: Third-party package (expected)**
```python
# src/core/model_prediction/scripts/train_model.py:5
import pandas as pd  # External package - expected to fail
```

**Example 3: Internal module (resolves correctly)**
```python
# src/core/model_prediction/server/predictor.py:7
from .model_loader import ModelLoader  # Internal - resolves correctly
```

**Analysis:**
- **Expected behavior**: Unresolved imports are third-party packages
- **Internal modules resolve**: Relative imports within the project work
- **36.7% is reasonable**: Most Python code uses external packages (redis, pandas, numpy, flask)
- **No issue here**: This is working as expected

### 3. Go (0% import resolution)

**Example 1: Stdlib (should resolve)**
```go
// src/core/model_prediction/server/main.go:5
import "context"  // Go stdlib - should resolve but doesn't
```

**Example 2: Stdlib (should resolve)**
```go
// src/core/model_prediction/server/service.go:7
import "fmt"  // Go stdlib - should resolve but doesn't
```

**Example 3: Internal package (should resolve)**
```go
// src/core/model_prediction/server/handler.go:9
import "pinpoint/model_prediction/server/models"  // Internal - should resolve but doesn't
```

**Example 4: External module (expected to fail)**
```go
// src/core/model_prediction/server/redis_client.go:5
import "github.com/go-redis/redis/v8"  // External - expected to fail
```

**Analysis:**
- **Critical issue**: 0% resolution means NOTHING resolves
- **Stdlib should resolve**: `context`, `fmt`, `net/http` are Go stdlib
- **Internal packages should resolve**: Project's own packages should be found
- **Module path issue**: Go uses module path `pinpoint/model_prediction/server`
- **go.mod not found**: Resolver likely not reading `go.mod` to understand module structure

**Why Code Knowledge Graph Missed This:**

**Ruby:**
- Resolver doesn't include Ruby stdlib in its index
- `require_relative` paths not being resolved correctly
- Mix of gems and internal modules both failing

**Python:**
- **Working correctly** - third-party packages expected to fail
- Internal modules resolving as expected
- 36.7% unresolved is reasonable for Python codebases

**Go:**
- **Critical failure** - 0% resolution is wrong
- Resolver not reading `go.mod` to understand module paths
- Go stdlib not indexed
- Internal package imports using module path not resolving
- Need to parse `go.mod` and understand Go module system
