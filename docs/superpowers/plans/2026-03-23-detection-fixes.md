# Detection Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the root causes of low detection rates discovered through 3 rounds of product codebase investigation. The single biggest fix — tracking `require_version()` — should resolve 5,000-10,000+ calls. Combined with 6 other targeted fixes, this brings effective call resolution from ~50% to ~75%+.

**Architecture:** Seven independent fixes, each targeting a specific detection gap identified by BOB. No dependencies between tasks except Task 7 (cleanup) which should run last.

**Tech Stack:** Python 3.11+, Tree-sitter, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/parsers/lua_parser.py` | Modify | Track `require_version()` as `require()`, add `http_handler` HTTP detection |
| `graph_builder/parsers/js_parser.py` | Modify | Add `Container._sendRequest` + alias detection |
| `graph_builder/resolvers/redis_abstraction_resolver.py` | Modify | Add Go Redis custom method names |
| `graph_builder/resolvers/collector_resolver.py` | Delete | Pattern doesn't exist in product codebase |
| `graph_builder/parsers/base.py` | Modify | Remove `CollectorInfo`, `collector_info` field |
| `graph_builder/main.py` | Modify | Remove collector resolver call, add http_handler step |
| `graph_builder/ingestion/writer.py` | Modify | Remove `upsert_collector_bundle` |
| `graph_builder/tests/test_require_version.py` | Create | Tests for require_version tracking |
| `graph_builder/tests/test_detection_fixes.py` | Create | Tests for JS HTTP, Go Redis, Lua HTTP fixes |
| `graph_builder/tests/fixtures/lua/require_version.lua` | Create | Test fixture |
| `graph_builder/tests/fixtures/lua/http_handler_caller.lua` | Create | Test fixture |
| `graph_builder/tests/fixtures/js/container_send.js` | Create | Test fixture |

---

## Task 1: Track `require_version()` as `require()` (HIGHEST IMPACT)

90% of the product codebase uses `require_version("module.path")` instead of `require("module.path")`. The Lua parser has a hard check on line 147: `if _text(name_node, source) != "require": continue` — so 90% of module bindings are missing from the binding map, causing thousands of unresolved calls.

`require_version` is defined as a wrapper around `require` that adds forbidden-module checks and error handling, but returns the exact same module table. The pattern is always:
```lua
local require_version = require("loader.lua").require_version
local module = require_version("path.to.module")
```

**Files:**
- Modify: `graph_builder/parsers/lua_parser.py:139-186`
- Create: `graph_builder/tests/test_require_version.py`
- Create: `graph_builder/tests/fixtures/lua/require_version.lua`

### Step 1: Create test fixture

- [ ] **1.1: Create fixture file**

Create `graph_builder/tests/fixtures/lua/require_version.lua`:

```lua
-- Pattern: require_version used for most imports
local require_version = require("loader.lua").require_version

local base = require_version("common.base.lua.handler")
local helpers = require_version("ato.helpers")
local context = require("lib.lua.context")
local store = require_version("lib.lua.store")

local M = base:new()

function M:apply(input, bundle, web)
    local device_id = context.get("device_id")
    local config = bundle:get("features.enabled", false)
    local data = store:get("user:" .. input.user_id)
    helpers.do_thing(data)
end

return M
```

### Step 2: Write test

- [ ] **2.1: Create test file**

Create `graph_builder/tests/test_require_version.py`:

```python
"""Tests for require_version() tracking in Lua parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_require_version_in_binding_map():
    """require_version() calls should populate the binding map like require()."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))

    # Check imports: should include both require and require_version calls
    mod_strings = [imp.module_string for imp in ast.imports]
    assert "common.base.lua.handler" in mod_strings
    assert "ato.helpers" in mod_strings
    assert "lib.lua.context" in mod_strings
    assert "lib.lua.store" in mod_strings

    # Check that require_version imports have local bindings
    bindings = {imp.module_string: imp.local_binding for imp in ast.imports}
    assert bindings.get("common.base.lua.handler") == "base"
    assert bindings.get("ato.helpers") == "helpers"
    assert bindings.get("lib.lua.context") == "context"
    assert bindings.get("lib.lua.store") == "store"


def test_require_version_calls_resolved():
    """Calls on require_version'd modules should be resolvable."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))

    # helpers.do_thing should have resolved_module from binding map
    helpers_calls = [c for c in ast.calls if "helpers" in c.callee_string]
    assert len(helpers_calls) >= 1
    # The parser should resolve this through binding map
    assert any(c.resolved_module == "ato.helpers" for c in helpers_calls)


def test_require_version_import_type():
    """require_version imports should have import_type='require_version'."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))

    rv_imports = [imp for imp in ast.imports if imp.module_string == "common.base.lua.handler"]
    assert len(rv_imports) == 1
    assert rv_imports[0].import_type == "require_version"


def test_loader_require_not_treated_as_module_import():
    """The initial require('loader.lua').require_version should be tracked as an import
    but should not pollute the binding map with require_version as a module."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))

    # 'require_version' variable should NOT be in binding map as a module
    # (it's a function, not a module)
    # But 'loader.lua' should appear as an import
    loader_imports = [imp for imp in ast.imports if "loader" in imp.module_string]
    assert len(loader_imports) >= 1
```

- [ ] **2.2: Run test to verify it fails**

Run: `python -m pytest graph_builder/tests/test_require_version.py -v`
Expected: Failures — `require_version` calls not tracked yet

### Step 3: Implement require_version tracking

- [ ] **3.1: Modify `_extract_requires` in lua_parser.py**

The current function (lines 139-186) only handles `require()`. We need to also handle `require_version()`. The key change is in the function call detection logic.

In `graph_builder/parsers/lua_parser.py`, modify `_extract_requires`:

1. **Track `require_version` as a known require-like function.** After extracting standard `require()` calls, also scan for `require_version()` calls. The `require_version` variable is always created via `local require_version = require("loader.lua").require_version`, so it's already in the AST as a function_call with name `require_version`.

2. **Change the name check** on line 147 from exact match to a set check:

```python
_REQUIRE_FUNCTIONS = {"require", "require_version"}
```

Then change line 147 from:
```python
if _text(name_node, source) != "require":
```
To:
```python
func_name = _text(name_node, source)
if func_name not in _REQUIRE_FUNCTIONS:
```

3. **Set the import_type** based on which function was called:

```python
import_type = "require_version" if func_name == "require_version" else "require"
```

4. **Handle the `require("loader.lua").require_version` pattern.** When parsing `local require_version = require("loader.lua").require_version`, the `require("loader.lua")` part is a standard require that should be tracked as an import (module_string="loader.lua"), but the `.require_version` property access means the binding for `require_version` should NOT go into the binding map as a module (it's a function reference, not a module table).

The existing `_find_require_binding` function handles the AST path `variable_declaration > assignment_statement > expression_list > function_call`. For `require("loader.lua").require_version`, the AST path is different — the function_call is inside a `field_expression` (dot access). So `_find_require_binding` will return `None` for the `require("loader.lua")` call, which is correct — `require_version` won't be added to binding_map as a module string.

However, we DO want to track `loader.lua` as an import. The existing code already does this (line 179-184 adds to `ast.imports` regardless of binding).

- [ ] **3.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_require_version.py -v`
Expected: All tests pass

- [ ] **3.3: Run full test suite**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All 105+ tests pass

- [ ] **3.4: Commit**

```bash
git add graph_builder/parsers/lua_parser.py \
       graph_builder/tests/test_require_version.py \
       graph_builder/tests/fixtures/lua/require_version.lua
git commit -m "feat: track require_version() as require() in Lua parser

90% of the product codebase uses require_version() instead of require().
Both return the same module table. This fix adds require_version to the
set of tracked require-like functions, populating the binding map for
thousands of previously invisible module bindings."
```

---

## Task 2: Add `Container._sendRequest` to JS parser

All JS HTTP calls in the product go through `Container._sendRequest(method, url, params, callback, data, extra)`. The parser only checks for bare `sendRequest` — the `Container.` prefix means callee string is `Container._sendRequest`, which doesn't match.

There's also an alias: `backwardCommunicator._sendRequest`. Total: 8 calls across 6 files.

**Files:**
- Modify: `graph_builder/parsers/js_parser.py:525-537`
- Create: `graph_builder/tests/fixtures/js/container_send.js`
- Add to: `graph_builder/tests/test_detection_fixes.py`

- [ ] **2.1: Create JS fixture**

Create `graph_builder/tests/fixtures/js/container_send.js`:

```javascript
var Container = {};

Container._sendRequest = function(method, url, params, callback, data, extra) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.send(JSON.stringify(params));
};

var backwardCommunicator = {
    _sendRequest: Container._sendRequest
};

function assessUser(userId) {
    Container._sendRequest(
        "POST",
        "/api/assess",
        {user_id: userId},
        handleResponse,
        {session: "abc"},
        {timeout: 30000}
    );
}

function getDevices(userId) {
    Container._sendRequest(
        "POST",
        "/api/get_devices",
        null,
        onDevicesReceived,
        {user_id: userId}
    );
}

function sendBackward(data) {
    backwardCommunicator._sendRequest(
        "POST",
        "/api/backward",
        data,
        handleBackwardResponse
    );
}
```

- [ ] **2.2: Modify JS parser**

In `graph_builder/parsers/js_parser.py`, find the `sendRequest` detection block (line 525). Change the check from matching only the bare name to also matching the `Container._sendRequest` and `backwardCommunicator._sendRequest` patterns.

Replace line 525:
```python
if callee == "sendRequest" and args and args.named_child_count >= 2:
```

With:
```python
_SEND_REQUEST_CALLEES = {"sendRequest", "Container._sendRequest", "backwardCommunicator._sendRequest"}

# ... in the detection loop:
if callee in _SEND_REQUEST_CALLEES and args and args.named_child_count >= 2:
```

The `Container._sendRequest` call has the same argument positions as `sendRequest`: method is arg[0], url is arg[1]. So the existing extraction logic (lines 526-537) works unchanged.

Define `_SEND_REQUEST_CALLEES` as a module-level constant near the top of the file (outside the function).

- [ ] **2.3: Write test, run, commit**

Add to `graph_builder/tests/test_detection_fixes.py`:

```python
def test_js_container_send_request():
    """Container._sendRequest should be detected as HTTP call."""
    ast = parse_js_file(str(JS_FIXTURES / "container_send.js"))
    assert len(ast.http_calls) >= 3

    urls = {h.url_or_path for h in ast.http_calls}
    assert "/api/assess" in urls
    assert "/api/get_devices" in urls
    assert "/api/backward" in urls

    methods = {h.method for h in ast.http_calls}
    assert "POST" in methods
```

Run: `python -m pytest graph_builder/tests/test_detection_fixes.py -v`

Commit:
```bash
git commit -m "feat: detect Container._sendRequest as JS HTTP call

Product codebase uses Container._sendRequest() and
backwardCommunicator._sendRequest() instead of bare sendRequest().
Add both patterns to the JS HTTP call detector."
```

---

## Task 3: Add Go Redis custom method names

The product's Go `RedisClient` wrapper has 22 custom methods (`HGetAsString`, `GetAsInt`, `GetAsFloat`, `HGetAsFloat`, `HSetWithExpire`, etc.) that aren't in our standard `go-redis` method sets. The field name is always `redisClient` (already in our indicator set).

**Files:**
- Modify: `graph_builder/resolvers/redis_abstraction_resolver.py:269-287`

- [ ] **3.1: Update method sets**

In `graph_builder/resolvers/redis_abstraction_resolver.py`, update the `_GO_REDIS_READ` and `_GO_REDIS_WRITE` sets to include the product's custom wrapper methods:

```python
_GO_REDIS_READ = {
    # Standard go-redis
    "Get", "GetRange", "GetSet", "GetEx", "GetDel",
    "Strlen", "Exists", "Type", "TTL", "PTTL", "Keys", "Scan",
    "HGet", "HGetAll", "HMGet", "HExists", "HKeys", "HVals", "HLen",
    "SMembers", "SIsMember", "SCard", "SRandMember",
    "ZRange", "ZRangeByScore", "ZRank", "ZScore", "ZCard",
    "LRange", "LLen", "LIndex",
    # Product custom wrapper methods
    "GetAsString", "GetAsInt", "GetAsFloat",
    "HGetAsString", "HGetAsInt", "HGetAsFloat",
    "Ping",
}

_GO_REDIS_WRITE = {
    # Standard go-redis
    "Set", "SetEX", "SetNX", "Append", "Incr", "IncrBy", "Decr", "DecrBy",
    "Del", "Expire", "ExpireAt", "PExpire", "Persist",
    "HSet", "HMSet", "HDel", "HIncrBy",
    "SAdd", "SRem", "SPop",
    "ZAdd", "ZRem", "ZIncrBy",
    "LPush", "RPush", "LPop", "RPop", "LSet", "LTrim",
    "Publish",
    # Product custom wrapper methods
    "HSetWithExpire",
    "Close",
}
```

- [ ] **3.2: Update test fixture**

Update `graph_builder/tests/fixtures/go/redis_client.go` to include the custom methods:

Add a function that calls `HGetAsString`, `GetAsInt`, `HSetWithExpire`:

```go
func (s *Server) customMethods(sessionID string) {
	val, _ := s.redisClient.HGetAsString("cache:models", "default")
	count, _ := s.redisClient.GetAsInt("counter:" + sessionID)
	s.redisClient.HSetWithExpire("session:"+sessionID, "count", count, 24*time.Hour)
}
```

- [ ] **3.3: Update test**

In `graph_builder/tests/test_go_redis.py`, add assertions for custom methods:

```python
def test_go_redis_custom_methods():
    """Custom wrapper methods (HGetAsString, GetAsInt, HSetWithExpire) should be detected."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))
    all_asts = {"test.go": ast}
    resolve_go_redis_abstractions(all_asts)
    ops = {a.operation for a in ast.redis_accesses}
    assert "HGetAsString" in ops
    assert "GetAsInt" in ops
    assert "HSetWithExpire" in ops
```

- [ ] **3.4: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_go_redis.py -v`

Commit:
```bash
git commit -m "feat: add Go Redis custom wrapper methods

Product uses HGetAsString, GetAsInt, GetAsFloat, HGetAsFloat,
HSetWithExpire wrapper methods on RedisClient struct."
```

---

## Task 4: Add Lua `http_handler` HTTP abstraction detection

All Lua HTTP calls go through `http_handler.get/post/put/send_request`. The unix socket path is a **separate parameter** (not embedded in URL). 16 total calls across the codebase.

**Files:**
- Modify: `graph_builder/parsers/lua_parser.py` (in `_extract_http_calls_lua`)
- Create: `graph_builder/tests/fixtures/lua/http_handler_caller.lua`
- Add to: `graph_builder/tests/test_detection_fixes.py`

- [ ] **4.1: Create fixture**

Create `graph_builder/tests/fixtures/lua/http_handler_caller.lua`:

```lua
local http_handler = require("lib.lua.http_handler")

local function call_model_prediction(data, headers)
    local response, err = http_handler.post(
        "/predict",
        nil,
        "unix:/var/run/model_prediction.sock",
        headers,
        data
    )
    return response
end

local function get_health(headers)
    local response, err = http_handler.get(
        "/health",
        nil,
        "unix:/var/run/model_prediction.sock",
        headers
    )
    return response
end
```

- [ ] **4.2: Add http_handler detection to Lua parser**

In `graph_builder/parsers/lua_parser.py`, in the `_extract_http_calls_lua` function, add detection for `http_handler.get/post/put/send_request` calls AFTER the existing resty.http detection block.

The key: check binding_map for variables bound to `"lib.lua.http_handler"`, then detect `.get()`, `.post()`, `.put()`, `.send_request()` calls on those variables.

```python
# --- HTTP handler wrapper detection ---
# Pattern: http_handler.post(url, params, unix_socket_path, headers, body)
_HTTP_HANDLER_MODULES = {"lib.lua.http_handler"}
_HTTP_HANDLER_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "send_request": "unknown",  # method is first arg for send_request
}

http_handler_vars = set()
for var, mod in binding_map.items():
    if mod in _HTTP_HANDLER_MODULES:
        http_handler_vars.add(var)

for call_node in _walk_all(root, "function_call"):
    name_node = call_node.child_by_field_name("name")
    if not name_node:
        continue
    callee = _text(name_node, source)

    # Check for http_handler_var.method() pattern
    if "." in callee:
        parts = callee.split(".", 1)
        if parts[0] in http_handler_vars and parts[1] in _HTTP_HANDLER_METHODS:
            method = _HTTP_HANDLER_METHODS[parts[1]]
            args = _first_child_of_type(call_node, "arguments")
            url = None
            unix_socket = None

            if args and args.named_child_count >= 1:
                url_arg = args.named_children[0]
                if url_arg.type == "string":
                    url = _get_string_value(url_arg, source)

                # For send_request, method is first arg, url is second
                if parts[1] == "send_request" and args.named_child_count >= 2:
                    method_arg = args.named_children[0]
                    url_arg = args.named_children[1]
                    if method_arg.type == "string":
                        method = _get_string_value(method_arg, source).upper()
                    if url_arg.type == "string":
                        url = _get_string_value(url_arg, source)

                # Unix socket path (3rd param for get, post, put)
                socket_idx = 2 if parts[1] != "send_request" else 3
                if args.named_child_count > socket_idx:
                    socket_arg = args.named_children[socket_idx]
                    if socket_arg.type == "string":
                        unix_socket = _get_string_value(socket_arg, source)

            if url:
                enclosing = _find_enclosing_function(call_node, source)
                ast.http_calls.append(HttpCallRef(
                    url_or_path=unix_socket or url,
                    method=method,
                    function=enclosing,
                    line=call_node.start_point[0] + 1,
                ))
```

Note: Check the exact helper function names in the parser (`_find_enclosing_function` vs `_find_enclosing`, `_first_child_of_type`, `_get_string_value`). Use whichever names the parser already defines.

- [ ] **4.3: Write test, run, commit**

Add to `graph_builder/tests/test_detection_fixes.py`:

```python
def test_lua_http_handler_calls():
    """http_handler.post/get should be detected as HTTP calls."""
    ast = parse_lua_file(str(LUA_FIXTURES / "http_handler_caller.lua"))
    assert len(ast.http_calls) >= 2

    methods = {h.method for h in ast.http_calls}
    assert "POST" in methods
    assert "GET" in methods

    # Should capture the unix socket path
    sockets = [h.url_or_path for h in ast.http_calls if "unix:" in h.url_or_path]
    assert len(sockets) >= 1
```

Commit:
```bash
git commit -m "feat: detect http_handler.get/post/put as Lua HTTP calls

Product wraps resty.http in http_handler module. Application code calls
http_handler.post(url, params, unix_socket_path, headers, body) instead
of using resty.http directly. Detects all 16 HTTP calls in codebase."
```

---

## Task 5: Improve self:method() same-file resolution

85% of `self:method()` calls target methods defined in the SAME file. The call resolver's Strategy 3 (same-file resolution) already does bare-name matching, but it doesn't handle the `self:` prefix properly. When the parser extracts `self:validate`, the callee_string is `"self:validate"`. The resolver splits on `:` and gets `table_name="self"`, `method_name="validate"`. But `"self"` is never in the binding_map, so Strategy 1 fails. Strategy 3 then tries bare `"self:validate"` against function names, which doesn't match `"M:validate"`.

The fix: in Strategy 1, when the table_name is `"self"`, treat it as a self-call on the module table (same as Strategy 2's self-call check).

**Files:**
- Modify: `graph_builder/resolvers/call_resolver.py`

- [ ] **5.1: Modify call_resolver.py**

In `graph_builder/resolvers/call_resolver.py`, in the `_resolve_call` method, after the binding_map check for Strategy 1 (around line 186-199), add a check for `self`:

```python
# Strategy 1a: If table_name is "self", resolve as self-call on module table
if table_name == "self":
    # In Lua, self refers to the module table in M:method() definitions
    if ast.module_info and ast.module_info.table_var_name:
        call.resolved_module = ast.module_name or ast.file_path
        call.resolved_function = method_name
        call.resolution_confidence = "self"
        return True
    # Also try same-file: does this file define a function with this method name?
    for func in ast.functions:
        func_base = func.name.split(".")[-1].split(":")[-1]
        if func_base == method_name:
            call.resolved_module = ast.module_name or ast.file_path
            call.resolved_function = method_name
            call.resolution_confidence = "self"
            return True
```

This check should come BEFORE Strategy 2 (direct binding map lookup for unqualified calls), since `self:method()` is a very specific pattern.

- [ ] **5.2: Run tests and commit**

Run: `python -m pytest graph_builder/tests/ -v`

Commit:
```bash
git commit -m "feat: resolve self:method() calls to same-file functions

When callee is self:X(), treat it as a self-call on the module table.
Match method name against functions defined in the same file. Resolves
~85% of self: calls (~4,000+ in the product codebase)."
```

---

## Task 6: Add `http_handler` to Lua external prefix list

The builtin classifier should classify calls on `http_handler` (when unresolved) as internal project calls, not truly_unresolved. However, since Task 1 (require_version) will cause most `http_handler` calls to be resolved through the binding map, this is a lower priority. Skip this task if require_version fixes the classification automatically.

---

## Task 7: Remove dead collector resolver

The collector `js_files` pattern from the plan doesn't exist in the product codebase. Collectors use `collect_key` + `collect()` function. JS bundling happens through Ruby generator scanning `assets/` directories.

**Files:**
- Delete: `graph_builder/resolvers/collector_resolver.py`
- Delete: `graph_builder/tests/test_collector_resolver.py`
- Delete: `graph_builder/tests/fixtures/lua/collector_init.lua`
- Modify: `graph_builder/parsers/base.py` — remove `CollectorInfo` class and `collector_info` field from FileAST
- Modify: `graph_builder/parsers/lua_parser.py` — remove `_detect_collector_registration` function and its call
- Modify: `graph_builder/main.py` — remove collector resolver import and call
- Modify: `graph_builder/ingestion/writer.py` — remove `upsert_collector_bundle` method

- [ ] **7.1: Remove collector_resolver.py and tests**

```bash
git rm graph_builder/resolvers/collector_resolver.py
git rm graph_builder/tests/test_collector_resolver.py
git rm graph_builder/tests/fixtures/lua/collector_init.lua
```

- [ ] **7.2: Remove CollectorInfo from base.py**

Remove the `CollectorInfo` dataclass and the `collector_info` field from `FileAST`.

- [ ] **7.3: Remove collector detection from lua_parser.py**

Remove the `_detect_collector_registration` function and its call in `parse_lua_file()`.

- [ ] **7.4: Remove collector resolver from main.py**

Remove the `resolve_collectors` import and the step that calls it.

- [ ] **7.5: Remove upsert_collector_bundle from writer.py**

Remove the method.

- [ ] **7.6: Run all tests**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass (collector tests are deleted, everything else unchanged)

- [ ] **7.7: Commit**

```bash
git commit -m "fix: remove collector resolver (pattern doesn't exist)

Product collectors use collect_key + collect() function, not js_files
arrays. JS bundling is done by Ruby generator scanning assets/ dirs.
The collector resolver was built on incorrect assumptions."
```

---

## Integration Verification

After all tasks:

- [ ] **Run full test suite**

```bash
python -m pytest graph_builder/tests/ -v
```

- [ ] **Run on product codebase** (on Mac)

```bash
code-graph health -c config.yml
```

Expected improvements:
- Call resolution: 33% → 55-65% (from require_version tracking)
- Lua HTTP calls: 0 → 16 (from http_handler detection)
- JS HTTP calls: 0 → 8 (from Container._sendRequest detection)
- Go Redis: 0 → 10-30 (from custom method names)
- Self:method() resolution: thousands more resolved
- Truly unresolved: 22,744 → ~10,000-15,000

---

## Summary

| Task | Expected Impact | Effort |
|------|----------------|--------|
| 1. require_version tracking | +5,000-10,000 resolved calls | Small |
| 2. Container._sendRequest | +8 JS HTTP calls | Tiny |
| 3. Go Redis custom methods | +10-30 Redis accesses | Tiny |
| 4. Lua http_handler detection | +16 HTTP calls | Small |
| 5. self:method() same-file | +4,000 resolved calls | Small |
| 6. http_handler classification | Low (covered by Task 1) | Skip |
| 7. Remove dead collector resolver | Cleanup | Tiny |
