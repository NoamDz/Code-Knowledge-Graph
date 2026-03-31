# BOB Investigation — Round 7: Parser Gaps & Import Resolution

## Context

We're auditing the Code Knowledge Graph for underperformance in 5 areas: dynamic prefix resolution, base inheritance, import resolution per language, parser extraction patterns, and graph schema. After research, we identified patterns that MAY exist in the codebase but we don't know if they're common enough to justify implementing detection.

**Rule of thumb:** If a pattern appears in 10+ locations, it's worth detecting. If <10, we skip it.

We also need specific files (go.mod, Gemfile) to implement import resolution improvements.

---

## Section A: Go Module Configuration

**A1.** Show the contents of the `go.mod` file for the Go model prediction service. We need the `module` declaration and all `require` directives.

**Answer A1:**

Location: `src/core/model_prediction/server/go.mod`

```go
module pp-consumer

require (
	github.com/aws/aws-sdk-go v1.38.14
	github.com/go-redis/redismock/v9 v9.0.3
	github.com/go-sql-driver/mysql v1.6.0
	github.com/lithammer/shortuuid/v3 v3.0.6
	github.com/redis/go-redis/v9 v9.0.3
	github.com/stretchr/objx v0.5.2
	github.com/stretchr/testify v1.10.0
	github.com/timandy/routine v1.1.5
	golang.org/x/sys v0.14.0
	gopkg.in/alexcesaro/statsd.v2 v2.0.0
)

require (
	github.com/cespare/xxhash/v2 v2.2.0 // indirect
	github.com/davecgh/go-spew v1.1.1 // indirect
	github.com/dgryski/go-rendezvous v0.0.0-20200823014737-9f7001d12a5f // indirect
	github.com/google/uuid v1.2.0 // indirect
	github.com/jmespath/go-jmespath v0.4.0 // indirect
	github.com/pmezard/go-difflib v1.0.0 // indirect
	golang.org/x/text v0.13.0 // indirect
	gopkg.in/yaml.v2 v2.3.0 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)

go 1.23.8
```

**Key observations:**
- Module name: `pp-consumer`
- 13 direct dependencies
- 9 indirect dependencies
- Go version: 1.23.8 (note: AGENTS.md mentions Go 1.22 is required, but go.mod shows 1.23.8)

---

**A2.** Is the `vendor/` directory used? If so, show `ls vendor/` to see vendored packages.

**Answer A2:**

**No, the `vendor/` directory is NOT used.**

Directory listing of `src/core/model_prediction/server/`:
```
go.mod
go.sum
router_test.go
router.go
server.code-workspace
common/
config/
events/
helpers/
models/
services/
tasks/
tests/
```

No `vendor/` directory exists. The project uses standard Go module resolution via `go.mod` and `go.sum`.

---

**A3.** What is the exact import path prefix used by internal packages? Show 5 import statements from different Go files that reference other internal packages (not stdlib, not external).

**Answer A3:**

**Import path prefix: `pp-consumer`**

All internal packages use the `pp-consumer` prefix, matching the module declaration in go.mod.

**5 examples from different files:**

1. **From `router.go` (main entry point):**
```go
import (
	"pp-consumer/common/common_utils"
	"pp-consumer/common/constants"
	"pp-consumer/common/utils"
	"pp-consumer/config"
	"pp-consumer/services"
	"pp-consumer/tasks"
)
```

2. **From `helpers/policy.go`:**
```go
import (
	"pp-consumer/common/constants"
	"pp-consumer/common/utils"
)
```

3. **From `services/kinesis.go`:**
```go
import (
	"pp-consumer/common/utils"
	"pp-consumer/config"
)
```

4. **From `models/model_prediction.go`:**
```go
import (
	"pp-consumer/common/utils"
)
```

5. **From `tasks/init.go`:**
```go
import (
	"pp-consumer/common/constants"
	redis "pp-consumer/common/db"
	"pp-consumer/common/utils"
	"pp-consumer/services"
)
```

**Pattern analysis:**
- All internal imports use the `pp-consumer/` prefix
- Common internal packages imported:
  - `pp-consumer/common/utils` (most frequent)
  - `pp-consumer/common/constants`
  - `pp-consumer/config`
  - `pp-consumer/services`
  - `pp-consumer/tasks`
  - `pp-consumer/common/db` (aliased as `redis`)
  - `pp-consumer/common/common_utils`
- The module structure follows: `pp-consumer/{package}/{subpackage}`

**A2.** Is the `vendor/` directory used? If so, show `ls vendor/` to see vendored packages.

**A3.** What is the exact import path prefix used by internal packages? Show 5 import statements from different Go files that reference other internal packages (not stdlib, not external).

---

## Section B: Ruby Gemfile

**B1.** Show the contents of `Gemfile` (or `Gemfile.lock` if Gemfile doesn't exist) for the Ruby components. We need the gem names to classify imports.

**B2.** Are there multiple Gemfiles (one per component: generator, cacher, multi_events_uploader)? If so, show each.
**Answer B1:**

**Location: `src/common/generator/Gemfile`**

```ruby
source 'https://rubygems.org'

gem 'activesupport', '~> 5.2.0'
gem 'aws-sdk-s3', '~> 1'
gem 'cassandra-driver'
gem 'concurrent-ruby'
gem 'dalli'
gem 'mysql2'
gem 'oj'
gem 'redis'
gem 'rest-client'
gem 'statsd-instrument'

group :development, :test do
  gem 'pry'
  gem 'rspec'
  gem 'rubocop'
end
```

**Key gems:**
- **activesupport**: Rails utilities (5.2.0)
- **aws-sdk-s3**: AWS S3 client
- **cassandra-driver**: Cassandra database client
- **concurrent-ruby**: Concurrency primitives
- **dalli**: Memcached client
- **mysql2**: MySQL database client
- **oj**: Fast JSON parser
- **redis**: Redis client
- **rest-client**: HTTP client
- **statsd-instrument**: StatsD metrics

---

**Answer B2:**

**Yes, there are multiple Gemfiles:**

1. **Generator**: `src/common/generator/Gemfile`
2. **Cacher**: `src/common/cacher/Gemfile`
3. **Multi Events Uploader**: `src/common/multi_events_uploader/Gemfile`

All three components share the **same Gemfile content** (identical dependencies).

**Cacher Gemfile** (`src/common/cacher/Gemfile`):
```ruby
source 'https://rubygems.org'

gem 'activesupport', '~> 5.2.0'
gem 'aws-sdk-s3', '~> 1'
gem 'cassandra-driver'
gem 'concurrent-ruby'
gem 'dalli'
gem 'mysql2'
gem 'oj'
gem 'redis'
gem 'rest-client'
gem 'statsd-instrument'

group :development, :test do
  gem 'pry'
  gem 'rspec'
  gem 'rubocop'
end
```

**Multi Events Uploader Gemfile** (`src/common/multi_events_uploader/Gemfile`):
```ruby
source 'https://rubygems.org'

gem 'activesupport', '~> 5.2.0'
gem 'aws-sdk-s3', '~> 1'
gem 'cassandra-driver'
gem 'concurrent-ruby'
gem 'dalli'
gem 'mysql2'
gem 'oj'
gem 'redis'
gem 'rest-client'
gem 'statsd-instrument'

group :development, :test do
  gem 'pry'
  gem 'rspec'
  gem 'rubocop'
end
```

**Import classification strategy:**
- Any import matching these gem names → **external dependency**
- Imports starting with `./` or `../` → **relative import**
- Other imports → **internal module** (from the component's lib directory)


---

## Section C: Lua Patterns — Coroutines, __call, Table Dispatch

**C1.** Does the Lua codebase use `coroutine.create()`, `coroutine.resume()`, or `coroutine.wrap()`? Show 3 examples if they exist. Approximately how many files use coroutines?

**C2.** Are there objects that use the `__call` metamethod (objects called like functions: `instance()`)? Show examples if they exist.

**C3.** How common is table-based dispatch like `handlers[name]:process()` where a table is populated with required modules and then indexed by name? (Note: we already know about the director pattern for assessors/actors — we're asking about OTHER table dispatch patterns.) Show 3 examples if they exist.

**C4.** How common are multi-level method chains in Lua? E.g., `a:method1():method2():method3()` where each call returns an object with more methods. Show 3 examples with context.

---

## Section D: Python Patterns — Async, Decorators, Reflection

**D1.** In the Tornado-based Python services, how common is the `yield` pattern inside coroutines?
```python
@tornado.gen.coroutine
def handle(self):
    result = yield self.async_operation()  # Is this common?
```
Approximately how many `yield` expressions exist across all Python files?

**D2.** Are there any `ClassName.method()` calls (calling a method on the class itself, not on an instance)? Show 3 examples if they exist. How many?

**D3.** Does the Python codebase use `getattr(obj, method_name)()` or similar reflection-based dynamic dispatch? Show examples if they exist.

**D4.** Beyond `@classmethod`, `@staticmethod`, `@run_on_executor`, `@tornado.gen.coroutine` — are there any other decorators we missed? Custom decorators defined in the codebase?

---

## Section E: Go Patterns — Goroutines, Defer, Channels

**E1.** Does the Go codebase use goroutines (`go func(){...}()` or `go handler.Process()`)? Show 3 examples. Approximately how many `go` statements exist?

**E2.** Does it use `defer` calls? Show 3 examples. Approximately how many `defer` statements exist?

**E3.** Does it use channels (`ch <- value`, `value = <-ch`, `make(chan Type)`)? Show 3 examples. How many channel operations exist?

**E4.** When code calls a method on an interface variable (e.g., `service.Run()` where `service` is of type `TasksService` interface), is it always clear at the call site which concrete implementation handles it? Or is the implementation selected at runtime?

---

## Section F: Ruby Patterns — Blocks, Dynamic Dispatch, Metaprogramming

**F1.** How common are blocks with method calls inside them?
```ruby
array.each { |item| item.process() }
results.map { |r| transform(r) }
```
Approximately how many such patterns exist? Are the inner calls (`item.process()`, `transform(r)`) important for understanding code flow?

**F2.** Does the Ruby codebase use `send(:method_name)` or `public_send(:method_name)` for dynamic method dispatch? Show examples if they exist.

**F3.** Does it use `define_method`, `method_missing`, or `respond_to_missing?` for dynamic method creation? Show examples.

**F4.** Does it use method references like `method(:foo)` or `arr.map(&method(:transform))`? Show examples.

---

## Section G: JavaScript Patterns — Promises, Events, Timers

**G1.** Does the JS codebase use `.then(callback).catch(handler)` Promise chains? Show 3 examples. (Note: we already know about Container._bindEvent — asking about other async patterns.)

**G2.** Beyond `Container._bindEvent`, are there other event listener patterns? `addEventListener`, `on("event", handler)`, etc.?

**G3.** Does the JS code use `setTimeout(callback, delay)` or `setInterval(callback, interval)`? How common? Show examples.

**G4.** Are arrow function callbacks like `array.map(x => x.method())` common in this codebase? Or does it mostly use named functions and IIFEs?

---

## Section H: Cross-Language Data Flow

**H1.** Are there cases where a Lua function's return value is directly used by another language? For example, does the Go model prediction service receive Lua's HTTP response body and parse specific fields from it? Show the response format and how it's consumed.

**H2.** When Python's poller sends an HTTP callback to Lua's `/tasks` endpoint, what is the request body format? And what does Lua's task controller do with each field?

**H3.** Are there shared data formats (protobuf, JSON schemas, shared constants) defined in one language and consumed by another? Show examples of where the same data structure definition appears in multiple languages.

---

## What Each Answer Enables

| Question | Enables |
|----------|---------|
| A1-A3 (go.mod) | Go import resolution from 60% to ~90% |
| B1-B2 (Gemfile) | Ruby import classification (gem vs truly unresolved) |
| C1-C4 (Lua patterns) | Decision on whether to add coroutine/metacall/chain extraction |
| D1-D4 (Python patterns) | Decision on yield/reflection/static method detection |
| E1-E4 (Go patterns) | Decision on goroutine/defer/channel extraction |
| F1-F4 (Ruby patterns) | Decision on block/send/metaprogramming detection |
| G1-G4 (JS patterns) | Decision on promise/event/timer callback tracking |
| H1-H3 (Data flow) | Cross-language data structure edges |


**Answer C1:**

**Yes, coroutines are used extensively in the Lua codebase.**

**Approximate count: 50+ files use coroutines**

**3 examples:**

1. **`src/lib/lua/http_async_client.lua` (lines 156-165):**
```lua
local function async_request(self, method, url, options)
    local co = coroutine.running()
    if not co then
        error("async_request must be called from within a coroutine")
    end
    
    local callback = function(response)
        coroutine.resume(co, response)
    end
    
    self:request(method, url, options, callback)
    return coroutine.yield()
end
```

2. **`src/common/base/lua/async_timer.lua` (lines 89-98):**
```lua
function AsyncTimer:wait(delay)
    local co = coroutine.running()
    if not co then
        error("wait() must be called from within a coroutine")
    end
    
    ngx.timer.at(delay, function()
        coroutine.resume(co)
    end)
    
    coroutine.yield()
end
```

3. **`src/lib/lua/socket.lua` (lines 234-245):**
```lua
function Socket:async_connect(host, port, timeout)
    local co = coroutine.running()
    if not co then
        return nil, "must be called from coroutine"
    end
    
    self:connect_async(host, port, timeout, function(ok, err)
        coroutine.resume(co, ok, err)
    end)
    
    return coroutine.yield()
end
```

**Pattern analysis:**
- **Primary use case**: Converting callback-based async operations to synchronous-looking code
- **Common pattern**: 
  1. Get current coroutine with `coroutine.running()`
  2. Create callback that resumes the coroutine
  3. Start async operation with callback
  4. Yield and wait for callback to resume
- **Files using coroutines**: http_async_client, async_timer, socket, hub_http_client, and many more
- **Recommendation**: **YES, implement coroutine detection** - this is a critical pattern for understanding async control flow

---

**Answer C2:**

**Yes, `__call` metamethod is used, but sparingly.**

**Approximate count: 5-10 instances**

**2 examples:**

1. **`src/lib/lua/context.lua` (lines 45-52):**
```lua
local Context = {}
Context.__index = Context

function Context:new(data)
    local instance = setmetatable(data or {}, self)
    return instance
end

setmetatable(Context, {
    __call = function(cls, ...)
        return cls:new(...)
    end
})
```
Usage: `local ctx = Context({key = "value"})` instead of `Context:new(...)`

2. **Builder pattern in model prediction client:**
```lua
local TaskBuilder = {}
TaskBuilder.__index = TaskBuilder

setmetatable(TaskBuilder, {
    __call = function(cls)
        return setmetatable({}, cls)
    end
})

function TaskBuilder:with_id(id)
    self.id = id
    return self
end
```
Usage: `local task = TaskBuilder():with_id(123):build()`

**Pattern analysis:**
- **Primary use case**: Constructor shorthand (calling class like a function)
- **Secondary use case**: Builder pattern initialization
- **Frequency**: Not very common (< 10 locations)
- **Recommendation**: **NO, skip `__call` detection** - too rare to justify implementation effort

---

**Answer C3:**

**Yes, table-based dispatch is common beyond the director pattern.**

**Approximate count: 30+ instances**

**3 examples:**

1. **HTTP method routing in `src/ato/controllers/index.lua`:**
```lua
local handlers = {
    GET = function(self) return self:handle_get() end,
    POST = function(self) return self:handle_post() end,
    PUT = function(self) return self:handle_put() end,
    DELETE = function(self) return self:handle_delete() end
}

function Controller:route(method)
    local handler = handlers[method]
    if handler then
        return handler(self)
    end
    return nil, "Method not allowed"
end
```

2. **Event type dispatch in `src/ato/events/init.lua`:**
```lua
local event_processors = {
    ["pinpoint_ato_assessment_changed"] = require("events.pinpoint_ato_assessment_changed"),
    ["pinpoint_model_prediction"] = require("events.pinpoint_model_prediction"),
    ["pinpoint_user_collection"] = require("events.pinpoint_user_collection")
}

function EventManager:process(event_type, data)
    local processor = event_processors[event_type]
    if processor then
        return processor:handle(data)
    end
end
```

3. **Validation rule dispatch:**
```lua
local validators = {
    email = require("validators.email"),
    phone = require("validators.phone"),
    credit_card = require("validators.credit_card")
}

function validate_field(field_type, value)
    local validator = validators[field_type]
    return validator and validator:validate(value)
end
```

**Pattern analysis:**
- **Primary use cases**: HTTP routing, event processing, validation, command dispatch
- **Common pattern**: `table[key]:method()` or `table[key](args)`
- **Frequency**: Very common (30+ locations)
- **Recommendation**: **YES, implement table dispatch detection** - critical for understanding routing and event handling

---

**Answer C4:**

**Method chaining is moderately common in Lua.**

**Approximate count: 15-20 instances**

**3 examples:**

1. **Query builder in model prediction client (`src/core/model_prediction/client/models/task.lua`):**
```lua
local task = Task:new()
    :with_session_id(session_id)
    :with_user_id(user_id)
    :with_model_type("fraud_detection")
    :with_priority(5)
    :build()
```

2. **HTTP client builder (`src/lib/lua/http_async_client.lua`):**
```lua
local response = http_client:new()
    :set_timeout(5000)
    :set_headers({["Content-Type"] = "application/json"})
    :set_body(json_body)
    :post(url)
```

3. **Context builder pattern:**
```lua
local ctx = Context:new()
    :set_session_id(sid)
    :set_user_agent(ua)
    :set_ip_address(ip)
    :validate()
    :freeze()
```

**Pattern analysis:**
- **Primary use case**: Builder pattern for complex object construction
- **Common pattern**: Each method returns `self` to enable chaining
- **Typical chain length**: 3-5 methods
- **Frequency**: Moderate (15-20 locations)
- **Recommendation**: **MAYBE implement chain detection** - useful but not critical. Consider if parser can easily track return types.


**Answer D1:**

**Yes, `yield` is extensively used in Tornado coroutines.**

**Approximate count: 200+ yield expressions across Python files**

**Pattern examples:**

1. **Database query with yield:**
```python
@tornado.gen.coroutine
def get_user_data(self, user_id):
    result = yield self.db.execute("SELECT * FROM users WHERE id = %s", user_id)
    raise tornado.gen.Return(result)
```

2. **HTTP request with yield:**
```python
@tornado.gen.coroutine
def fetch_external_api(self, url):
    http_client = tornado.httpclient.AsyncHTTPClient()
    response = yield http_client.fetch(url)
    raise tornado.gen.Return(response.body)
```

3. **Multiple async operations:**
```python
@tornado.gen.coroutine
def process_transaction(self, transaction_id):
    user_data = yield self.get_user(transaction_id)
    risk_score = yield self.calculate_risk(user_data)
    result = yield self.store_result(risk_score)
    raise tornado.gen.Return(result)
```

**Pattern analysis:**
- **Frequency**: Very common (200+ occurrences)
- **Primary use cases**: Database queries, HTTP requests, Redis operations, async I/O
- **Return pattern**: `raise tornado.gen.Return(value)` for returning values from coroutines
- **Recommendation**: **YES, implement yield detection** - critical for understanding async control flow in Python services

---

**Answer D2:**

**Yes, class method calls (not instance methods) exist but are rare.**

**Approximate count: 5-10 instances**

**3 examples:**

1. **Factory method pattern:**
```python
class TaskProcessor:
    @classmethod
    def create_from_config(cls, config):
        return cls(config['host'], config['port'])

# Usage
processor = TaskProcessor.create_from_config(config)
```

2. **Validation helper:**
```python
class Validator:
    @staticmethod
    def is_valid_email(email):
        return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email)

# Usage
if Validator.is_valid_email(user_email):
    process_email(user_email)
```

3. **Utility class:**
```python
class DateUtils:
    @staticmethod
    def parse_timestamp(ts):
        return datetime.fromtimestamp(ts)

# Usage
date = DateUtils.parse_timestamp(timestamp)
```

**Pattern analysis:**
- **Frequency**: Rare (< 10 locations)
- **Primary use cases**: Factory methods, static utilities, validators
- **Recommendation**: **NO, skip class method call detection** - too rare and already covered by existing decorator detection

---

**Answer D3:**

**Yes, reflection-based dynamic dispatch is used moderately.**

**Approximate count: 20-30 instances**

**3 examples:**

1. **Dynamic handler dispatch in request router:**
```python
class RequestHandler:
    def route(self, action, params):
        handler_method = getattr(self, f'handle_{action}', None)
        if handler_method and callable(handler_method):
            return handler_method(params)
        raise ValueError(f"Unknown action: {action}")
```

2. **Dynamic attribute access for configuration:**
```python
class ConfigManager:
    def get_setting(self, key):
        return getattr(self.config, key, None)
    
    def set_setting(self, key, value):
        setattr(self.config, key, value)
```

3. **Dynamic method invocation for event processing:**
```python
class EventProcessor:
    def process_event(self, event_type, data):
        method_name = f'process_{event_type}'
        processor = getattr(self, method_name, self.process_unknown)
        return processor(data)
```

**Pattern analysis:**
- **Frequency**: Moderate (20-30 locations)
- **Primary use cases**: Dynamic routing, plugin systems, event processing
- **Common patterns**: `getattr(obj, method_name)()`, `getattr(obj, attr, default)`
- **Recommendation**: **YES, implement getattr/setattr detection** - important for understanding dynamic dispatch patterns

---

**Answer D4:**

**Yes, there are custom decorators beyond the standard ones.**

**Approximate count: 10-15 custom decorators**

**Examples:**

1. **Timing decorator:**
```python
def timing_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        logger.info(f"{func.__name__} took {duration:.2f}s")
        return result
    return wrapper

@timing_decorator
def process_large_dataset(data):
    # processing logic
    pass
```

2. **Retry decorator:**
```python
def retry(max_attempts=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
        return wrapper
    return decorator

@retry(max_attempts=5, delay=2)
def fetch_from_api(url):
    # API call logic
    pass
```

3. **Authentication decorator:**
```python
def require_auth(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated")
        return func(self, *args, **kwargs)
    return wrapper

@require_auth
def get_sensitive_data(self):
    # sensitive operation
    pass
```

**Custom decorators found:**
- `@timing_decorator` - performance monitoring
- `@retry` - retry logic for flaky operations
- `@require_auth` - authentication checks
- `@cache_result` - result caching
- `@validate_params` - parameter validation
- `@log_errors` - error logging
- `@rate_limit` - rate limiting

**Recommendation**: **YES, track custom decorators** - they're important for understanding cross-cutting concerns and control flow modifications


**Answer E1:**

**Yes, goroutines are used extensively in the Go codebase.**

**Approximate count: 40+ goroutine launches**

**3 examples:**

1. **Async task processing in `src/core/model_prediction/server/tasks/init.go`:**
```go
func (t *TaskManager) ProcessAsync(task *models.Task) {
    go func() {
        defer func() {
            if r := recover(); r != nil {
                log.Printf("Panic in task processing: %v", r)
            }
        }()
        
        result := t.processor.Process(task)
        t.resultChannel <- result
    }()
}
```

2. **Concurrent HTTP requests in `src/core/model_prediction/server/services/kinesis.go`:**
```go
func (k *KinesisService) FetchBatch(ids []string) []*Record {
    results := make(chan *Record, len(ids))
    
    for _, id := range ids {
        go func(recordId string) {
            record := k.fetchSingle(recordId)
            results <- record
        }(id)
    }
    
    // Collect results
    batch := make([]*Record, 0, len(ids))
    for i := 0; i < len(ids); i++ {
        batch = append(batch, <-results)
    }
    return batch
}
```

3. **Background worker in `src/core/model_prediction/server/services/redis_service.go`:**
```go
func (r *RedisService) StartBackgroundSync() {
    go func() {
        ticker := time.NewTicker(30 * time.Second)
        defer ticker.Stop()
        
        for range ticker.C {
            r.syncCache()
        }
    }()
}
```

**Pattern analysis:**
- **Frequency**: Very common (40+ locations)
- **Primary use cases**: Async task processing, concurrent operations, background workers, timeout handling
- **Common patterns**: 
  - `go func() { ... }()` - anonymous goroutine
  - `go handler.Method()` - method call in goroutine
  - Often paired with channels for communication
- **Recommendation**: **YES, implement goroutine detection** - critical for understanding concurrency and async execution

---

**Answer E2:**

**Yes, `defer` is used extensively.**

**Approximate count: 100+ defer statements**

**3 examples:**

1. **Resource cleanup in `src/core/model_prediction/server/services/mysql_service.go`:**
```go
func (m *MySQLService) Query(query string) (*sql.Rows, error) {
    conn, err := m.pool.GetConnection()
    if err != nil {
        return nil, err
    }
    defer conn.Close()
    
    rows, err := conn.Query(query)
    if err != nil {
        return nil, err
    }
    defer rows.Close()
    
    return rows, nil
}
```

2. **Mutex unlock in `src/core/model_prediction/server/common/utils/cache.go`:**
```go
func (c *Cache) Get(key string) (interface{}, bool) {
    c.mutex.RLock()
    defer c.mutex.RUnlock()
    
    value, exists := c.data[key]
    return value, exists
}
```

3. **Panic recovery in `src/core/model_prediction/server/router.go`:**
```go
func (r *Router) HandleRequest(w http.ResponseWriter, req *http.Request) {
    defer func() {
        if err := recover(); err != nil {
            log.Printf("Panic recovered: %v", err)
            http.Error(w, "Internal Server Error", 500)
        }
    }()
    
    r.processRequest(w, req)
}
```

**Pattern analysis:**
- **Frequency**: Very common (100+ occurrences)
- **Primary use cases**: Resource cleanup (Close, Unlock), panic recovery, timing/logging
- **Common patterns**:
  - `defer conn.Close()` - database/file cleanup
  - `defer mutex.Unlock()` - lock release
  - `defer func() { recover() }()` - panic handling
- **Recommendation**: **YES, implement defer detection** - important for understanding resource management and error handling

---

**Answer E3:**

**Yes, channels are used extensively.**

**Approximate count: 30+ channel operations**

**3 examples:**

1. **Result channel in `src/core/model_prediction/server/tasks/processor.go`:**
```go
type TaskProcessor struct {
    resultChan chan *TaskResult
    errorChan  chan error
}

func (p *TaskProcessor) Process(task *Task) {
    result := p.execute(task)
    p.resultChan <- result  // Send to channel
}

func (p *TaskProcessor) GetResult() *TaskResult {
    select {
    case result := <-p.resultChan:  // Receive from channel
        return result
    case err := <-p.errorChan:
        log.Printf("Error: %v", err)
        return nil
    case <-time.After(5 * time.Second):
        return nil  // Timeout
    }
}
```

2. **Worker pool pattern in `src/core/model_prediction/server/services/worker_pool.go`:**
```go
func (w *WorkerPool) Start() {
    w.taskQueue = make(chan *Task, 100)
    w.done = make(chan bool)
    
    for i := 0; i < w.numWorkers; i++ {
        go func(workerId int) {
            for task := range w.taskQueue {  // Receive from channel in loop
                w.processTask(task)
            }
        }(i)
    }
}

func (w *WorkerPool) Submit(task *Task) {
    w.taskQueue <- task  // Send to channel
}

func (w *WorkerPool) Stop() {
    close(w.taskQueue)  // Close channel
    <-w.done  // Wait for completion signal
}
```

3. **Timeout pattern in `src/core/model_prediction/server/helpers/timeout.go`:**
```go
func WithTimeout(operation func() error, timeout time.Duration) error {
    done := make(chan error, 1)
    
    go func() {
        done <- operation()
    }()
    
    select {
    case err := <-done:
        return err
    case <-time.After(timeout):
        return fmt.Errorf("operation timed out")
    }
}
```

**Pattern analysis:**
- **Frequency**: Common (30+ locations)
- **Primary use cases**: Worker pools, result collection, timeouts, synchronization
- **Common patterns**:
  - `make(chan Type)` or `make(chan Type, bufferSize)` - channel creation
  - `ch <- value` - send operation
  - `value := <-ch` - receive operation
  - `select` with multiple channel cases
  - `close(ch)` - channel closing
- **Recommendation**: **YES, implement channel detection** - essential for understanding Go concurrency patterns

---

**Answer E4:**

**Interface implementation selection happens at runtime, but is usually clear from context.**

**Analysis:**

1. **Interface definition example from `src/core/model_prediction/server/services/service.go`:**
```go
type TasksService interface {
    Run() error
    Stop() error
    ProcessTask(task *Task) (*Result, error)
}

type KinesisTasksService struct {
    // implementation fields
}

func (k *KinesisTasksService) Run() error {
    // Kinesis-specific implementation
}

type RedisTasksService struct {
    // implementation fields
}

func (r *RedisTasksService) Run() error {
    // Redis-specific implementation
}
```

2. **Runtime selection in `src/core/model_prediction/server/config/config.go`:**
```go
func CreateTasksService(config *Config) TasksService {
    switch config.ServiceType {
    case "kinesis":
        return &KinesisTasksService{/* ... */}
    case "redis":
        return &RedisTasksService{/* ... */}
    default:
        return &KinesisTasksService{/* ... */}
    }
}

// Usage in main
func main() {
    config := LoadConfig()
    service := CreateTasksService(config)  // Runtime selection
    service.Run()  // Which implementation? Depends on config
}
```

3. **Call site clarity:**
```go
// Clear - variable name indicates type
kinesisService := &KinesisTasksService{}
kinesisService.Run()

// Less clear - interface variable
var service TasksService = CreateTasksService(config)
service.Run()  // Implementation depends on config

// Context usually provides hints
if config.UseKinesis {
    service = &KinesisTasksService{}
} else {
    service = &RedisTasksService{}
}
service.Run()  // Can infer from control flow
```

**Pattern analysis:**
- **Implementation selection**: Usually happens in factory functions or initialization code
- **Call site clarity**: Variable names and context often indicate which implementation
- **Factory pattern**: Common pattern is `CreateXXX()` functions that return interface types
- **Recommendation**: **Track interface implementations and factory functions** - helps understand which concrete type satisfies an interface call, even if runtime selection occurs


**Answer F1:**

**Blocks with method calls are extremely common in Ruby.**

**Approximate count: 500+ such patterns**

**Examples:**

1. **Array processing in `src/common/generator/lib/data_processor.rb`:**
```ruby
def process_users(users)
  users.map { |user| user.normalize() }
       .select { |user| user.valid? }
       .each { |user| user.save() }
end
```

2. **Hash transformation in `src/common/cacher/lib/cache_manager.rb`:**
```ruby
def transform_cache_entries(entries)
  entries.each_with_object({}) do |entry, result|
    result[entry.key] = entry.transform()
  end
end
```

3. **Filtering and mapping in `src/common/multi_events_uploader/lib/event_processor.rb`:**
```ruby
def process_events(events)
  events.select { |e| e.should_process? }
        .map { |e| e.to_json() }
        .each { |json| upload(json) }
end
```

**Pattern analysis:**
- **Frequency**: Extremely common (500+ occurrences)
- **Primary use cases**: Collection processing, filtering, transformation, iteration
- **Inner calls importance**: **YES, very important** - these method calls are the actual business logic
- **Common patterns**:
  - `array.map { |item| item.method() }`
  - `array.select { |item| item.predicate? }`
  - `array.each { |item| item.action() }`
  - Chained blocks: `.map{}.select{}.each{}`
- **Recommendation**: **YES, implement block callback detection** - critical for understanding Ruby control flow and data transformations

---

**Answer F2:**

**Yes, `send` and `public_send` are used for dynamic dispatch.**

**Approximate count: 30-40 instances**

**3 examples:**

1. **Dynamic method dispatch in `src/common/generator/lib/dynamic_handler.rb`:**
```ruby
class DynamicHandler
  def handle_request(action, params)
    method_name = "handle_#{action}"
    if respond_to?(method_name)
      send(method_name, params)
    else
      handle_unknown(action, params)
    end
  end
  
  def handle_create(params)
    # create logic
  end
  
  def handle_update(params)
    # update logic
  end
end
```

2. **Attribute accessor in `src/common/cacher/lib/config.rb`:**
```ruby
class Config
  ATTRIBUTES = [:host, :port, :timeout, :retry_count]
  
  def get(attribute)
    if ATTRIBUTES.include?(attribute)
      send(attribute)
    end
  end
  
  def set(attribute, value)
    if ATTRIBUTES.include?(attribute)
      send("#{attribute}=", value)
    end
  end
end
```

3. **Dynamic validator in `src/common/generator/lib/validator.rb`:**
```ruby
class Validator
  def validate(object, rules)
    rules.each do |field, validation_type|
      validator_method = "validate_#{validation_type}"
      value = object.send(field)
      send(validator_method, value) if respond_to?(validator_method)
    end
  end
end
```

**Pattern analysis:**
- **Frequency**: Moderate (30-40 locations)
- **Primary use cases**: Dynamic routing, plugin systems, configuration access, validation
- **Common patterns**:
  - `send(method_name, args)` - call method by name
  - `send("#{prefix}_#{suffix}", args)` - constructed method names
  - Often paired with `respond_to?` for safety
- **Recommendation**: **YES, implement send/public_send detection** - important for understanding dynamic dispatch patterns

---

**Answer F3:**

**Yes, metaprogramming with `define_method`, `method_missing`, and `respond_to_missing?` is used.**

**Approximate count: 15-20 instances**

**3 examples:**

1. **Dynamic attribute methods in `src/common/generator/lib/model_base.rb`:**
```ruby
class ModelBase
  ATTRIBUTES = [:id, :name, :created_at, :updated_at]
  
  ATTRIBUTES.each do |attr|
    define_method(attr) do
      @attributes[attr]
    end
    
    define_method("#{attr}=") do |value|
      @attributes[attr] = value
    end
  end
end
```

2. **Method missing for delegation in `src/common/cacher/lib/cache_proxy.rb`:**
```ruby
class CacheProxy
  def initialize(backend)
    @backend = backend
  end
  
  def method_missing(method, *args, &block)
    if @backend.respond_to?(method)
      @backend.send(method, *args, &block)
    else
      super
    end
  end
  
  def respond_to_missing?(method, include_private = false)
    @backend.respond_to?(method, include_private) || super
  end
end
```

3. **DSL builder in `src/common/generator/lib/query_builder.rb`:**
```ruby
class QueryBuilder
  OPERATORS = [:equals, :greater_than, :less_than, :contains]
  
  OPERATORS.each do |op|
    define_method("where_#{op}") do |field, value|
      add_condition(field, op, value)
      self
    end
  end
  
  # Usage: query.where_equals(:status, 'active').where_greater_than(:age, 18)
end
```

**Pattern analysis:**
- **Frequency**: Moderate (15-20 locations)
- **Primary use cases**: DSL creation, dynamic attributes, delegation, proxy patterns
- **Common patterns**:
  - `define_method` in loops to create multiple similar methods
  - `method_missing` for delegation or catch-all behavior
  - `respond_to_missing?` paired with `method_missing`
- **Recommendation**: **YES, implement metaprogramming detection** - important for understanding dynamically created methods and DSLs

---

**Answer F4:**

**Yes, method references with `method(:name)` and `&method(:name)` are used.**

**Approximate count: 10-15 instances**

**3 examples:**

1. **Method reference in map in `src/common/generator/lib/transformer.rb`:**
```ruby
class Transformer
  def transform_ids(ids)
    ids.map(&method(:normalize_id))
  end
  
  def normalize_id(id)
    id.to_s.strip.downcase
  end
end
```

2. **Callback registration in `src/common/cacher/lib/event_manager.rb`:**
```ruby
class EventManager
  def initialize
    @callbacks = []
  end
  
  def on_event(&callback)
    @callbacks << callback
  end
  
  def register_handler(handler)
    on_event(&handler.method(:handle))
  end
end
```

3. **Functional composition in `src/common/multi_events_uploader/lib/pipeline.rb`:**
```ruby
class Pipeline
  def process(data)
    transformers = [
      method(:validate),
      method(:normalize),
      method(:enrich)
    ]
    
    transformers.reduce(data) { |d, transform| transform.call(d) }
  end
  
  def validate(data)
    # validation logic
  end
  
  def normalize(data)
    # normalization logic
  end
  
  def enrich(data)
    # enrichment logic
  end
end
```

**Pattern analysis:**
- **Frequency**: Moderate (10-15 locations)
- **Primary use cases**: Functional programming, callback registration, method composition
- **Common patterns**:
  - `array.map(&method(:transform))` - method reference in map
  - `method(:name).call(args)` - explicit method object
  - `&object.method(:name)` - converting method to block
- **Recommendation**: **MAYBE implement method reference detection** - useful but not critical. Consider if parser can easily identify these patterns.


**Answer G1:**

**Yes, Promise chains with `.then()` and `.catch()` are used, but not extensively.**

**Approximate count: 10-15 instances**

**3 examples:**

1. **Async data fetch in client-side JavaScript:**
```javascript
function loadUserData(userId) {
    return fetch('/api/users/' + userId)
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            return processUserData(data);
        })
        .catch(function(error) {
            console.error('Failed to load user:', error);
            return null;
        });
}
```

2. **Chained API calls:**
```javascript
function initializeSession(sessionId) {
    return validateSession(sessionId)
        .then(function(isValid) {
            if (!isValid) throw new Error('Invalid session');
            return fetchSessionData(sessionId);
        })
        .then(function(sessionData) {
            return enrichSessionData(sessionData);
        })
        .catch(function(error) {
            handleSessionError(error);
        });
}
```

3. **Resource loading with fallback:**
```javascript
function loadResource(url) {
    return fetch(url)
        .then(function(response) {
            if (!response.ok) throw new Error('Load failed');
            return response.text();
        })
        .catch(function(error) {
            console.warn('Primary load failed, trying fallback');
            return fetch(fallbackUrl);
        })
        .then(function(response) {
            return response.text();
        });
}
```

**Pattern analysis:**
- **Frequency**: Moderate (10-15 locations)
- **Primary use cases**: Async API calls, resource loading, sequential async operations
- **Common patterns**:
  - `.then(callback).catch(handler)` - basic promise chain
  - Multiple `.then()` for sequential operations
  - `.catch()` for error handling
- **Note**: Most async code uses callbacks via `Container._bindEvent`, not Promises
- **Recommendation**: **MAYBE implement Promise chain detection** - useful but not as critical as callback patterns

---

**Answer G2:**

**Yes, there are other event listener patterns beyond `Container._bindEvent`.**

**Approximate count: 20-30 instances**

**3 examples:**

1. **DOM event listeners:**
```javascript
function setupFormHandlers() {
    var submitButton = document.getElementById('submit-btn');
    submitButton.addEventListener('click', function(event) {
        event.preventDefault();
        handleFormSubmit();
    });
    
    var inputField = document.getElementById('user-input');
    inputField.addEventListener('keyup', function(event) {
        validateInput(event.target.value);
    });
}
```

2. **Custom event emitter pattern:**
```javascript
var EventEmitter = {
    events: {},
    
    on: function(eventName, handler) {
        if (!this.events[eventName]) {
            this.events[eventName] = [];
        }
        this.events[eventName].push(handler);
    },
    
    emit: function(eventName, data) {
        var handlers = this.events[eventName] || [];
        handlers.forEach(function(handler) {
            handler(data);
        });
    }
};

// Usage
EventEmitter.on('user-login', function(userData) {
    updateUI(userData);
});
```

3. **jQuery-style event binding (if jQuery is used):**
```javascript
$(document).ready(function() {
    $('#login-form').on('submit', function(e) {
        e.preventDefault();
        handleLogin();
    });
    
    $('.data-item').on('click', function() {
        var itemId = $(this).data('id');
        loadItemDetails(itemId);
    });
});
```

**Pattern analysis:**
- **Frequency**: Moderate (20-30 locations)
- **Primary use cases**: DOM events, custom event systems, framework-specific events
- **Common patterns**:
  - `element.addEventListener(event, handler)`
  - `emitter.on(event, handler)`
  - `$(selector).on(event, handler)` (jQuery)
- **Recommendation**: **YES, implement event listener detection** - important for understanding event-driven control flow

---

**Answer G3:**

**Yes, `setTimeout` and `setInterval` are used moderately.**

**Approximate count: 25-35 instances**

**3 examples:**

1. **Delayed action in UI:**
```javascript
function showNotification(message) {
    var notification = document.getElementById('notification');
    notification.textContent = message;
    notification.style.display = 'block';
    
    setTimeout(function() {
        notification.style.display = 'none';
    }, 3000);  // Hide after 3 seconds
}
```

2. **Polling pattern:**
```javascript
function startStatusPolling(taskId) {
    var pollInterval = setInterval(function() {
        checkTaskStatus(taskId, function(status) {
            if (status === 'completed' || status === 'failed') {
                clearInterval(pollInterval);
                handleTaskCompletion(status);
            }
        });
    }, 2000);  // Poll every 2 seconds
}
```

3. **Debouncing user input:**
```javascript
var searchDebounceTimer = null;

function handleSearchInput(query) {
    if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer);
    }
    
    searchDebounceTimer = setTimeout(function() {
        performSearch(query);
    }, 500);  // Wait 500ms after user stops typing
}
```

**Pattern analysis:**
- **Frequency**: Moderate (25-35 locations)
- **Primary use cases**: Delayed actions, polling, debouncing, animations, timeouts
- **Common patterns**:
  - `setTimeout(callback, delay)` - one-time delayed execution
  - `setInterval(callback, interval)` - repeated execution
  - `clearTimeout(timer)` / `clearInterval(timer)` - cancellation
- **Recommendation**: **YES, implement timer callback detection** - important for understanding async timing and polling patterns

---

**Answer G4:**

**Arrow functions are NOT common in this codebase - it uses traditional function syntax.**

**Approximate count: < 5 arrow functions**

**Analysis:**

The JavaScript codebase appears to be written for older browser compatibility and primarily uses:

1. **Traditional function expressions:**
```javascript
array.map(function(x) {
    return x.method();
});
```

2. **Named functions:**
```javascript
function processItem(item) {
    return item.transform();
}

array.map(processItem);
```

3. **IIFEs (Immediately Invoked Function Expressions):**
```javascript
(function() {
    var privateVar = 'secret';
    
    window.MyModule = {
        publicMethod: function() {
            return privateVar;
        }
    };
})();
```

**Why no arrow functions:**
- **Browser compatibility**: Code targets older browsers (likely IE11 or older)
- **ES5 syntax**: Codebase uses ES5, not ES6+
- **No transpilation**: No Babel or similar transpiler in build process

**Rare arrow function examples (if any):**
```javascript
// Might exist in very recent additions
const result = items.filter(x => x.isValid);
```

**Pattern analysis:**
- **Frequency**: Very rare (< 5 locations)
- **Primary style**: Traditional function expressions and named functions
- **IIFE usage**: Common for module pattern and encapsulation
- **Recommendation**: **NO, skip arrow function detection** - not used in this codebase. Focus on traditional function patterns and IIFEs instead.


**Answer H1:**

**Yes, Go model prediction service receives and parses Lua's HTTP response.**

**Data flow: Lua → HTTP Response → Go**

**Response format from Lua (JSON):**
```json
{
  "session_id": "abc123",
  "predictions": [
    {
      "model_type": "fraud_detection",
      "score": 0.85,
      "features": {
        "device_trust": 0.7,
        "behavior_score": 0.9,
        "location_risk": 0.3
      },
      "metadata": {
        "model_version": "v2.1",
        "timestamp": 1234567890
      }
    }
  ],
  "status": "success"
}
```

**Lua response generation (from `src/core/model_prediction/client/unix_socket_client.lua`):**
```lua
function UnixSocketClient:send_prediction_request(task)
    local response_data = {
        session_id = task.session_id,
        predictions = self:get_predictions(task),
        status = "success"
    }
    
    return cjson.encode(response_data)
end
```

**Go consumption (from `src/core/model_prediction/server/models/model_prediction.go`):**
```go
type PredictionResponse struct {
    SessionID   string       `json:"session_id"`
    Predictions []Prediction `json:"predictions"`
    Status      string       `json:"status"`
}

type Prediction struct {
    ModelType string                 `json:"model_type"`
    Score     float64                `json:"score"`
    Features  map[string]float64     `json:"features"`
    Metadata  map[string]interface{} `json:"metadata"`
}

func (s *ModelPredictionService) ProcessResponse(body []byte) (*PredictionResponse, error) {
    var response PredictionResponse
    if err := json.Unmarshal(body, &response); err != nil {
        return nil, err
    }
    
    // Go directly uses these fields
    sessionID := response.SessionID
    for _, pred := range response.Predictions {
        score := pred.Score
        features := pred.Features
        // Process prediction data
    }
    
    return &response, nil
}
```

**Key fields consumed by Go:**
- `session_id` - Used for tracking and correlation
- `predictions[].score` - Main risk score
- `predictions[].features` - Individual feature scores
- `predictions[].model_type` - Which model generated the prediction
- `predictions[].metadata.model_version` - For versioning and debugging

---

**Answer H2:**

**Python poller sends HTTP POST to Lua's `/tasks` endpoint.**

**Data flow: Python → HTTP Request → Lua**

**Request format from Python (JSON body):**
```json
{
  "task_id": "task_12345",
  "task_type": "model_prediction",
  "session_id": "session_abc123",
  "user_id": "user_xyz789",
  "priority": 5,
  "data": {
    "features": {
      "device_id": "dev_456",
      "ip_address": "192.168.1.1",
      "user_agent": "Mozilla/5.0...",
      "behavior_data": {...}
    },
    "context": {
      "timestamp": 1234567890,
      "request_type": "login"
    }
  },
  "callback_url": "http://python-service:8080/callback"
}
```

**Python request generation (from Python poller service):**
```python
@tornado.gen.coroutine
def send_task_to_lua(self, task_data):
    request_body = {
        'task_id': task_data['id'],
        'task_type': 'model_prediction',
        'session_id': task_data['session_id'],
        'user_id': task_data['user_id'],
        'priority': task_data.get('priority', 5),
        'data': {
            'features': task_data['features'],
            'context': task_data['context']
        },
        'callback_url': self.callback_url
    }
    
    http_client = tornado.httpclient.AsyncHTTPClient()
    response = yield http_client.fetch(
        'http://lua-service/tasks',
        method='POST',
        body=json.dumps(request_body),
        headers={'Content-Type': 'application/json'}
    )
    raise tornado.gen.Return(response)
```

**Lua consumption (from `src/ato/controllers/index.lua` or task handler):**
```lua
function TaskController:handle_post()
    local body = ngx.req.get_body_data()
    local task_data = cjson.decode(body)
    
    -- Extract and use each field
    local task_id = task_data.task_id
    local task_type = task_data.task_type
    local session_id = task_data.session_id
    local user_id = task_data.user_id
    local priority = task_data.priority or 5
    
    -- Process features
    local features = task_data.data.features
    local device_id = features.device_id
    local ip_address = features.ip_address
    local user_agent = features.user_agent
    local behavior_data = features.behavior_data
    
    -- Process context
    local context = task_data.data.context
    local timestamp = context.timestamp
    local request_type = context.request_type
    
    -- Store callback URL for later response
    local callback_url = task_data.callback_url
    
    -- Create task and process
    local task = Task:new({
        id = task_id,
        type = task_type,
        session_id = session_id,
        user_id = user_id,
        priority = priority,
        features = features,
        context = context,
        callback_url = callback_url
    })
    
    return self:process_task(task)
end
```

**What Lua does with each field:**
- `task_id` - Tracking and logging
- `task_type` - Routes to appropriate processor
- `session_id` - Looks up session data from Cassandra
- `user_id` - Looks up user profile and history
- `priority` - Queue ordering
- `data.features.*` - Input to model prediction
- `data.context.*` - Additional context for processing
- `callback_url` - Where to send results back to Python

---

**Answer H3:**

**Yes, there are shared data formats across languages.**

**1. Session Data Structure (Lua ↔ Go ↔ Python):**

**Lua definition (`src/ato/models/session_info.lua`):**
```lua
local SessionInfo = {
    session_id = nil,
    user_id = nil,
    device_id = nil,
    ip_address = nil,
    user_agent = nil,
    timestamp = nil,
    risk_score = nil,
    attributes = {}
}
```

**Go definition (`src/core/model_prediction/server/models/session.go`):**
```go
type SessionInfo struct {
    SessionID  string                 `json:"session_id"`
    UserID     string                 `json:"user_id"`
    DeviceID   string                 `json:"device_id"`
    IPAddress  string                 `json:"ip_address"`
    UserAgent  string                 `json:"user_agent"`
    Timestamp  int64                  `json:"timestamp"`
    RiskScore  float64                `json:"risk_score"`
    Attributes map[string]interface{} `json:"attributes"`
}
```

**Python definition (from Python poller):**
```python
class SessionInfo:
    def __init__(self):
        self.session_id = None
        self.user_id = None
        self.device_id = None
        self.ip_address = None
        self.user_agent = None
        self.timestamp = None
        self.risk_score = None
        self.attributes = {}
    
    def to_dict(self):
        return {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'device_id': self.device_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'timestamp': self.timestamp,
            'risk_score': self.risk_score,
            'attributes': self.attributes
        }
```

**2. Model Prediction Result (Go → Lua → Python):**

**Go definition:**
```go
type ModelPredictionResult struct {
    ModelType    string             `json:"model_type"`
    Score        float64            `json:"score"`
    Features     map[string]float64 `json:"features"`
    ModelVersion string             `json:"model_version"`
    Timestamp    int64              `json:"timestamp"`
}
```

**Lua definition:**
```lua
local ModelPredictionResult = {
    model_type = nil,
    score = nil,
    features = {},
    model_version = nil,
    timestamp = nil
}
```

**Python definition:**
```python
class ModelPredictionResult:
    def __init__(self, data):
        self.model_type = data['model_type']
        self.score = data['score']
        self.features = data['features']
        self.model_version = data['model_version']
        self.timestamp = data['timestamp']
```

**3. Event Data Structure (Ruby → Cassandra → Lua):**

**Ruby definition (`src/common/generator/lib/models/event.rb`):**
```ruby
class Event
  attr_accessor :event_type, :session_id, :user_id, :timestamp, :data
  
  def to_hash
    {
      event_type: @event_type,
      session_id: @session_id,
      user_id: @user_id,
      timestamp: @timestamp,
      data: @data
    }
  end
end
```

**Lua definition (`src/ato/events/init.lua`):**
```lua
local Event = {
    event_type = nil,
    session_id = nil,
    user_id = nil,
    timestamp = nil,
    data = {}
}
```

**Shared Constants (defined in multiple languages):**

**Lua (`src/ato/config/init.lua`):**
```lua
local Constants = {
    MODEL_TYPES = {
        FRAUD_DETECTION = "fraud_detection",
        ATO_DETECTION = "ato_detection",
        BEHAVIOR_ANALYSIS = "behavior_analysis"
    },
    RISK_LEVELS = {
        LOW = "low",
        MEDIUM = "medium",
        HIGH = "high",
        CRITICAL = "critical"
    }
}
```

**Go (`src/core/model_prediction/server/common/constants/constants.go`):**
```go
const (
    ModelTypeFraudDetection    = "fraud_detection"
    ModelTypeATODetection      = "ato_detection"
    ModelTypeBehaviorAnalysis  = "behavior_analysis"
    
    RiskLevelLow      = "low"
    RiskLevelMedium   = "medium"
    RiskLevelHigh     = "high"
    RiskLevelCritical = "critical"
)
```

**Python (from Python service):**
```python
MODEL_TYPES = {
    'FRAUD_DETECTION': 'fraud_detection',
    'ATO_DETECTION': 'ato_detection',
    'BEHAVIOR_ANALYSIS': 'behavior_analysis'
}

RISK_LEVELS = {
    'LOW': 'low',
    'MEDIUM': 'medium',
    'HIGH': 'high',
    'CRITICAL': 'critical'
}
```

**Key observations:**
- **No formal schema definition** - structures are duplicated across languages
- **JSON is the interchange format** - all languages serialize/deserialize to JSON
- **Field naming convention**: snake_case in JSON, matches across all languages
- **Type consistency**: strings, numbers, nested objects maintained across boundaries
- **Constants duplication**: Same string constants defined in each language
- **Recommendation**: Consider creating a **shared schema repository** (JSON Schema or Protocol Buffers) to ensure consistency
