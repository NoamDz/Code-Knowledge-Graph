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

---

## How to Provide Answers

For any question above, the most useful format is:

1. **Grep output**: `grep -rn "pattern" src/ --include="*.ext" | head -20`
2. **Spot-check output**: `code-graph spot-check /path/to/file.ext`
3. **File snippet**: the relevant 10-20 lines of a representative file
4. **Short description**: "yes, it works like X" or "no, we use Y instead"

Even partial answers are valuable — answering just A1 (the redis_helper require path) could unlock hundreds of Redis edges.
