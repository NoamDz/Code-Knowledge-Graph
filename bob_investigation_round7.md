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
