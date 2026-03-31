# Parser Pattern Extraction — Design Spec

**Date:** 2026-03-31
**Goal:** Add detection for 13 language-specific patterns confirmed by BOB as common (10+ occurrences) across all 5 parsers. Focus on call flow accuracy, concurrency, error flow, and data flow.

---

## Patterns to Implement (confirmed by BOB)

| # | Language | Pattern | Count | Why It Matters |
|---|----------|---------|-------|----------------|
| 1 | Lua | Coroutine patterns | 50+ files | Async control flow (yield/resume) |
| 2 | Lua | Table-based dispatch | 30+ | Routing, event handling, validation |
| 3 | Python | yield in Tornado coroutines | 200+ | Async operations (DB, HTTP, Redis) |
| 4 | Python | getattr/setattr dynamic dispatch | 20-30 | Dynamic routing, plugins, events |
| 5 | Python | Custom decorator tracking | 10-15 | Cross-cutting concerns (timing, retry, auth) |
| 6 | Go | Goroutine detection | 40+ | Concurrent execution paths |
| 7 | Go | Defer call tracking | 100+ | Resource cleanup, panic recovery |
| 8 | Go | Channel operations | 30+ | Inter-goroutine communication |
| 9 | Ruby | Block callback detection | 500+ | Collection processing, business logic |
| 10 | Ruby | send/public_send dispatch | 30-40 | Dynamic method invocation |
| 11 | Ruby | Metaprogramming (define_method, method_missing) | 15-20 | DSLs, proxies, dynamic attributes |
| 12 | JS | Event listener detection | 20-30 | Event-driven control flow |
| 13 | JS | setTimeout/setInterval callbacks | 25-35 | Async timing, polling, debouncing |

**Skipped (BOB: too rare):** Lua __call (<10), Python class method calls (<10), JS arrow functions (<5).

**Maybe (implement if easy):** Lua method chains (15-20), Ruby method refs (10-15), JS Promises (10-15).

---

## 1. Lua: Coroutine Pattern Detection

### What to Detect

```lua
local co = coroutine.running()       -- Get current coroutine
coroutine.resume(co, response)       -- Resume with value
coroutine.yield()                    -- Suspend execution
local co = coroutine.create(func)    -- Create new coroutine
local wrapped = coroutine.wrap(func) -- Create wrapped coroutine
```

### Data Model Addition

Add to `CallRef` or new field on `FileAST`:
```python
is_coroutine_call: bool = False  # on CallRef — marks yield/resume as async boundaries
```

Or simpler: classify `coroutine.*` calls via the existing BuiltinClassifier as a new category `"coroutine"` instead of `"builtin"`. This avoids data model changes.

### Implementation

In `lua_parser.py`, detect `coroutine.running()`, `coroutine.resume()`, `coroutine.yield()`, `coroutine.create()`, `coroutine.wrap()` calls. Mark them with a classification or extract as a separate list.

In `builtin_classifier.py`, add `"coroutine"` as a classification alongside `"builtin"` and `"external"`. When callee starts with `coroutine.`, classify as `"coroutine"` instead of `"builtin"`.

**Expected impact:** 50+ coroutine calls correctly classified. Async boundaries visible in graph.

---

## 2. Lua: Table-Based Dispatch Detection

### What to Detect

```lua
local handlers = {
    GET = function(self) return self:handle_get() end,
    POST = function(self) return self:handle_post() end,
}
local handler = handlers[method]      -- Dynamic lookup
handler(self)                         -- Indirect call

local processors = {
    ["event_type_a"] = require("events.event_type_a"),
}
local processor = processors[event_type]
processor:handle(data)                -- Indirect call via require
```

### Implementation

In `lua_parser.py`, detect table construction with `require()` values:
1. Find table constructors where values are `require()` calls
2. Extract the `require()` module strings as potential dispatch targets
3. Create `DISPATCHES_VIA_TABLE` edges or `POTENTIAL_IMPORT` edges from the dispatching function to each target module

This reuses the existing `POTENTIAL_IMPORT` edge type since the pattern is similar to dynamic requires — we know the targets but not which one is selected at runtime.

**Expected impact:** ~30 additional POTENTIAL_IMPORT or dispatch edges for routing and event processing.

---

## 3. Python: Tornado yield/coroutine Detection

### What to Detect

```python
@tornado.gen.coroutine
def process(self):
    result = yield self.db.execute(query)     # Async boundary
    data = yield self.http_client.fetch(url)   # Another async boundary
    raise tornado.gen.Return(result)           # Coroutine return
```

### Implementation

In `python_parser.py`:
1. Detect functions with `@tornado.gen.coroutine` decorator (already extracted)
2. Within those functions, find `yield` expressions and extract the call being yielded
3. Mark these calls with `is_async: True` or classify as `"async_yield"`
4. Detect `raise tornado.gen.Return(value)` as the return pattern

The simplest approach: treat `yield expr` as a call to `expr` with a special marker. The yielded expression is already captured as a regular call — just flag the enclosing function as a coroutine.

Add `is_coroutine: bool = False` to `FunctionDef`. Set to `True` when function has `@tornado.gen.coroutine` decorator.

**Expected impact:** 200+ yield expressions tracked. Coroutine functions flagged.

---

## 4. Python: getattr/setattr Dynamic Dispatch

### What to Detect

```python
handler_method = getattr(self, f'handle_{action}', None)
handler_method(params)                    # Dynamic call

processor = getattr(self, method_name, self.process_unknown)
processor(data)                           # Dynamic call
```

### Implementation

In `python_parser.py`, detect `getattr()` calls:
1. Extract the attribute name argument (second arg)
2. If it's a string literal like `"handle_get"`, create a potential call to `self.handle_get`
3. If it's an f-string or format call, extract the prefix pattern and create potential calls to matching methods
4. Create calls with `resolution_confidence = "dynamic_getattr"`

**Expected impact:** 20-30 dynamic dispatch patterns detected. Method routing visible in graph.

---

## 5. Python: Custom Decorator Tracking

### What to Detect

```python
@timing_decorator          # Wraps function, adds timing
@retry(max_attempts=5)     # Wraps function, adds retry logic
@require_auth              # Wraps function, adds auth check
```

### Implementation

Decorators are already extracted in `FunctionDef.decorators`. Two additions needed:

1. **Write decorators to Function nodes** (already planned in Quick Fixes V2 spec section 1c)
2. **Detect decorator definitions** — functions that return wrapper functions. Look for the pattern:
   ```python
   def decorator_name(func):
       @functools.wraps(func)
       def wrapper(*args, **kwargs):
           ...
           return func(*args, **kwargs)
       return wrapper
   ```
   Mark these functions as `is_decorator_factory: True`.

The main value is writing existing `decorators` list to graph (Quick Fixes V2) + flagging decorator factory functions.

**Expected impact:** Decorators queryable in graph. Custom decorator definitions identifiable.

---

## 6. Go: Goroutine Detection

### What to Detect

```go
go func() {
    result := t.processor.Process(task)
    t.resultChannel <- result
}()

go handler.Process()
```

### Data Model Addition

Add to `CallRef`:
```python
is_goroutine: bool = False   # True when call is spawned as goroutine
```

### Implementation

In `go_parser.py`, detect `go_statement` nodes in the AST:
1. Walk tree for `go_statement` nodes
2. Extract the function call inside
3. Mark with `is_goroutine = True`
4. The call itself is already captured — just add the flag

In `writer.py`, write `is_goroutine` property on CALLS edges.

**Expected impact:** 40+ goroutine launches flagged. Concurrent execution paths visible.

---

## 7. Go: Defer Call Tracking

### What to Detect

```go
defer conn.Close()
defer mutex.RUnlock()
defer func() {
    if err := recover(); err != nil { ... }
}()
```

### Data Model Addition

Add to `CallRef`:
```python
is_deferred: bool = False    # True when call is deferred
```

### Implementation

In `go_parser.py`, detect `defer_statement` nodes:
1. Walk tree for `defer_statement` nodes
2. Extract the function call inside
3. Mark with `is_deferred = True`

**Expected impact:** 100+ deferred calls flagged. Resource cleanup patterns visible.

---

## 8. Go: Channel Operation Detection

### What to Detect

```go
ch <- value                          // Send
result := <-ch                       // Receive
taskQueue := make(chan *Task, 100)    // Create
close(ch)                            // Close
select {                             // Select
    case result := <-resultChan: ...
    case <-time.After(5*time.Second): ...
}
```

### Data Model Addition

New dataclass:
```python
@dataclass
class ChannelAccess:
    channel_name: str
    operation: str         # "send", "receive", "create", "close"
    function: str
    line: int
    element_type: str | None = None   # e.g., "*Task", "error"
```

Add `channel_accesses: list[ChannelAccess]` to `FileAST`.

### Implementation

In `go_parser.py`:
1. Detect `send_statement` nodes (`ch <- value`) → operation "send"
2. Detect `unary_expression` with `<-` operator → operation "receive"
3. Detect `make(chan Type)` calls → operation "create"
4. Detect `close(ch)` calls → operation "close"

In `writer.py`, add `upsert_channel_access()` to create Channel nodes and CHAN_SENDS/CHAN_RECEIVES edges.

**Expected impact:** 30+ channel operations detected. Inter-goroutine data flow visible.

---

## 9. Ruby: Block Callback Detection

### What to Detect

```ruby
users.map { |user| user.normalize() }
     .select { |user| user.valid? }
     .each { |user| user.save() }
```

### Implementation

In `ruby_parser.py`, when extracting calls:
1. Check if a `call` node has a `block` child
2. Extract calls INSIDE the block as regular CallRef entries
3. The enclosing function for these inner calls is the block's parent function
4. Already partially working — Tree-sitter walks into blocks. Verify inner calls are captured.

The main gap may be that inner calls like `user.normalize()` have `user` as an unresolvable receiver (it's a block parameter, not a binding). Mark these with `resolution_confidence = "block_param"`.

**Expected impact:** Verify existing 500+ block calls are captured. Add block parameter context.

---

## 10. Ruby: send/public_send Dynamic Dispatch

### What to Detect

```ruby
send(method_name, params)              # Dynamic call
send("handle_#{action}", params)       # Constructed method name
object.send(field)                     # Accessor dispatch
```

### Implementation

In `ruby_parser.py`:
1. Detect `send` and `public_send` calls
2. Extract the method name argument (first arg)
3. If string literal → create call to that method with `resolution_confidence = "dynamic_send"`
4. If string interpolation (`"handle_#{action}"`) → extract prefix, create potential calls to matching methods

**Expected impact:** 30-40 dynamic dispatch patterns detected.

---

## 11. Ruby: Metaprogramming Detection

### What to Detect

```ruby
ATTRIBUTES.each { |attr| define_method(attr) { @attributes[attr] } }
def method_missing(method, *args, &block)
    @backend.send(method, *args, &block)
end
```

### Implementation

In `ruby_parser.py`:
1. Detect `define_method` calls → extract the method name argument, create synthetic FunctionDef
2. Detect `method_missing` definitions → flag the class as having dynamic dispatch
3. Create `DynamicMethod` entries or tag the class with `has_method_missing: True`

Simplest approach: when `define_method(:name)` is found, add a FunctionDef with `name` and `visibility = "dynamic"`.

**Expected impact:** 15-20 dynamically defined methods visible in graph.

---

## 12. JS: Event Listener Detection

### What to Detect

```javascript
element.addEventListener('click', function(event) { handleClick(); });
emitter.on('user-login', function(data) { updateUI(data); });
$('#form').on('submit', function(e) { handleLogin(); });
```

### Implementation

In `js_parser.py`:
1. Detect `addEventListener`, `.on(` calls
2. Extract event name (first string arg) and handler (second arg)
3. Extract calls inside the handler function
4. Create HttpCallRef-like entries or tag calls with `is_event_handler = True`

Simplest approach: treat event listeners as regular calls but extract the handler's inner calls. The handler's calls are already captured by Tree-sitter walk — verify and tag.

**Expected impact:** 20-30 event listener registrations detected.

---

## 13. JS: Timer Callback Detection

### What to Detect

```javascript
setTimeout(function() { hideNotification(); }, 3000);
setInterval(function() { checkStatus(); }, 2000);
```

### Implementation

In `js_parser.py`:
1. Detect `setTimeout` and `setInterval` calls
2. Extract the callback function (first arg)
3. Extract calls inside the callback
4. Mark with `is_timer_callback = True` or create a timing classification

**Expected impact:** 25-35 timer callbacks detected. Deferred execution visible.

---

## Data Model Changes Summary

| Addition | Location | Purpose |
|----------|----------|---------|
| `FunctionDef.is_coroutine` | base.py | Flag Tornado coroutine functions |
| `CallRef.is_goroutine` | base.py | Flag goroutine-spawned calls |
| `CallRef.is_deferred` | base.py | Flag deferred calls |
| `ChannelAccess` dataclass | base.py | Go channel operations |
| `FileAST.channel_accesses` | base.py | Per-file channel ops |

---

## Files Modified

| File | Changes |
|------|---------|
| `graph_builder/parsers/base.py` | Add is_coroutine to FunctionDef, is_goroutine/is_deferred to CallRef, ChannelAccess dataclass, channel_accesses to FileAST |
| `graph_builder/parsers/lua_parser.py` | Coroutine classification, table dispatch detection |
| `graph_builder/parsers/python_parser.py` | Tornado yield detection, getattr dispatch, decorator factory detection |
| `graph_builder/parsers/go_parser.py` | Goroutine, defer, channel extraction |
| `graph_builder/parsers/ruby_parser.py` | Block verification, send/public_send, define_method/method_missing |
| `graph_builder/parsers/js_parser.py` | Event listener, timer callback detection |
| `graph_builder/resolvers/builtin_classifier.py` | Add "coroutine" classification for Lua |
| `graph_builder/ingestion/writer.py` | Add is_goroutine, is_deferred to CALLS edges. New upsert_channel_access. |
| `graph_builder/ingestion/schema.py` | Channel node type, CHAN_SENDS/CHAN_RECEIVES edges |
| `graph_builder/main.py` | Wire channel access ingestion |
| `graph_builder/tests/test_parser_patterns.py` | New test file for all 13 patterns |

---

## Expected Impact Summary

| Language | New Detection | Count |
|----------|--------------|-------|
| Lua | Coroutine async boundaries | 50+ calls classified |
| Lua | Table dispatch targets | ~30 edges |
| Python | Coroutine functions flagged | ~50 functions |
| Python | Yield async boundaries | 200+ calls |
| Python | getattr dynamic dispatch | 20-30 patterns |
| Python | Decorator definitions | 10-15 factories |
| Go | Goroutine launches | 40+ flagged |
| Go | Deferred calls | 100+ flagged |
| Go | Channel operations | 30+ edges |
| Ruby | Block callbacks verified | 500+ existing |
| Ruby | Dynamic send dispatch | 30-40 patterns |
| Ruby | Dynamic method defs | 15-20 synthetic functions |
| JS | Event listeners | 20-30 patterns |
| JS | Timer callbacks | 25-35 patterns |
