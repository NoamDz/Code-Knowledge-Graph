# Parser & Import Investigation — Design Spec

**Date:** 2026-03-30
**Goal:** Investigate parser extraction gaps and import resolution improvements that require BOB confirmation before implementation. Covers Go go.mod parsing, Ruby Gemfile classification, and parser extraction patterns across all 5 languages.

**This spec defines WHAT to investigate. Implementation depends on BOB's answers.**

---

## 1. Go Import Resolution via go.mod Parsing

### Current State
Go import resolution is 60.2% (308/512). The resolver uses suffix matching on directory paths without understanding Go's module system.

### What We Need from BOB
- Location of `go.mod` file
- Module name declared in `go.mod` (e.g., `module github.com/org/pinpoint`)
- Whether vendor/ directory is used
- Complete list of `require` directives (external dependencies)

### Proposed Fix (pending BOB confirmation)
Parse `go.mod` to extract module name, strip it from import paths before suffix matching. Example: import `"pp-consumer/common/db"` with module `"pp-consumer"` → resolve `"common/db"` as local path.

**Expected impact:** Go resolution from 60.2% to ~85-90%.

---

## 2. Ruby Gemfile Classification

### Current State
Ruby import resolution is 42.3% (145/343). Most unresolved are external gems — correct behavior, but we can't distinguish gems from truly unresolved imports.

### What We Need from BOB
- Contents of Gemfile and/or Gemfile.lock
- Whether gems are vendored locally or installed system-wide

### Proposed Fix (pending BOB confirmation)
Parse Gemfile to build KNOWN_GEMS set. Mark unresolved imports as `"external_gem"` vs `"truly_unresolved"`. This improves classification without increasing resolution rate.

**Expected impact:** Better import classification. Gems correctly tagged as external.

---

## 3. Lua Parser Gaps

### Patterns to Investigate

**3a. Coroutine patterns:**
Does the codebase use `coroutine.create()`, `coroutine.resume()`, `coroutine.wrap()`? These create deferred execution flows not captured as regular calls.

**3b. __call metamethod:**
Are there objects invoked directly like `instance()` via `__call` in the metatable? The parser tracks `setmetatable` but not `__call`.

**3c. Table-based dispatch:**
How common is `handlers[name]:process()` where `handlers` is a table populated from requires? This is different from the director iteration pattern we already know about.

**3d. Multi-level method chains:**
How common is `a.b():c():d()` chaining in the Lua codebase? Currently only 1 level of method chaining is captured.

---

## 4. Python Parser Gaps

### Patterns to Investigate

**4a. Async/await and Tornado coroutines:**
The codebase uses Tornado with `@tornado.gen.coroutine` + `yield` pattern. Calls inside coroutines are captured as regular calls, but the `yield` expression itself is a call to an async operation. Should we track `yield` as a special call type?

**4b. Decorator execution:**
Decorators like `@run_on_executor` are extracted but not tracked as calls. Should `@decorator` be treated as a call to `decorator(func)`?

**4c. Static/class method calls:**
`ClassName.method()` calls — are these common in the Python codebase? Current parser handles `self.method()` but not `ClassName.method()`.

**4d. getattr/reflection patterns:**
Does the codebase use `getattr(obj, method_name)()` or similar dynamic dispatch? If so, how common?

---

## 5. Go Parser Gaps

### Patterns to Investigate

**5a. Goroutines:**
Does the Go codebase use `go func(){}()` or `go handler.Process()`? If so, these are concurrent execution paths not marked in the call graph.

**5b. Defer calls:**
Does it use `defer cleanup()` or `defer file.Close()`? Deferred calls execute at function exit — semantically different from normal calls.

**5c. Channel operations:**
Does the codebase use channels (`ch <- value`, `value = <-ch`)? These are data flow connections between goroutines.

**5d. Interface method invocation tracking:**
When code calls `service.Run()` where `service` is an interface, can we track which concrete implementation handles it?

---

## 6. Ruby Parser Gaps

### Patterns to Investigate

**6a. Block/yield patterns:**
How common is `array.each { |x| x.process() }` or `def run; yield; end`? Blocks passed to methods contain calls that are currently captured but the block→method relationship is lost.

**6b. Dynamic dispatch (send):**
Does the codebase use `object.send(:method_name, args)` or `object.public_send(:method_name)`? This is runtime method dispatch invisible to static analysis.

**6c. Method references:**
Does the codebase use `method(:foo)` to create callable references? Or `proc = lambda { |x| ... }; arr.map(&proc)`?

**6d. Metaprogramming:**
Does the codebase use `define_method`, `method_missing`, or `respond_to_missing?`? These create methods dynamically.

---

## 7. JavaScript Parser Gaps

### Patterns to Investigate

**7a. Promise chains:**
Does the JS code use `.then(callback).catch(handler)` chains? These are sequential execution flows not tracked.

**7b. Event listeners:**
Does it use `element.addEventListener("click", handler)` or `Container._bindEvent("event", callback)`? The latter is codebase-specific.

**7c. setTimeout/setInterval:**
Are timer-based callbacks used? `setTimeout(callback, delay)` creates deferred execution.

**7d. Arrow function callbacks:**
How common is `array.map(x => x.method())` where the arrow function's calls aren't traced to the enclosing function?

---

## BOB Investigation File

All questions from sections 1-7 are compiled into `bob_investigation_round7.md` for BOB to answer. Implementation decisions depend on BOB's responses:

| BOB Answer | Action |
|-----------|--------|
| Pattern exists and is common (10+ occurrences) | Add detection to parser |
| Pattern exists but rare (<10 occurrences) | Skip, not worth complexity |
| Pattern doesn't exist in this codebase | Skip entirely |
| go.mod / Gemfile provided | Implement resolution improvement |

---

## Files That Would Be Modified (pending BOB answers)

| File | Potential Changes |
|------|-------------------|
| `graph_builder/resolvers/go_resolver.py` | go.mod parsing, module prefix stripping |
| `graph_builder/resolvers/ruby_resolver.py` | Gemfile parsing, gem classification |
| `graph_builder/parsers/lua_parser.py` | Coroutine, __call, table dispatch extraction |
| `graph_builder/parsers/python_parser.py` | Async/yield, decorator calls, static methods |
| `graph_builder/parsers/go_parser.py` | Goroutine, defer, channel extraction |
| `graph_builder/parsers/ruby_parser.py` | Block/yield, send, metaprogramming |
| `graph_builder/parsers/js_parser.py` | Promise chains, event listeners, timers |
| `graph_builder/parsers/base.py` | New fields if needed (is_goroutine, is_deferred, etc.) |
