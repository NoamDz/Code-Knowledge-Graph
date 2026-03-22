# Graph Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the Code Knowledge Graph's accuracy and usefulness by classifying unresolved calls, linking cross-language HTTP flows, parsing collector registrations, detecting Go Redis calls, and fixing validate's call resolution.

**Architecture:** Five improvements that each enrich the parsed ASTs or graph edges. Tasks 1-4 are independent and can be built in any order. Task 5 depends on Task 1 (imports BuiltinClassifier). Each adds a new resolver/classifier or extends an existing parser, integrated into the main build pipeline.

**Tech Stack:** Python 3.11+, Tree-sitter, Memgraph (Cypher), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/parsers/base.py` | Modify | Add `classification` field to CallRef, add `CollectorInfo` dataclass |
| `graph_builder/resolvers/builtin_classifier.py` | Create | Classify calls as builtin/external/dynamic/truly_unresolved |
| `graph_builder/resolvers/endpoint_linker.py` | Create | Match HTTP call URLs to nginx endpoint handlers |
| `graph_builder/resolvers/collector_resolver.py` | Create | Parse collector init.lua registrations |
| `graph_builder/parsers/go_parser.py` | No change | Already detects Redis calls as regular call expressions |
| `graph_builder/resolvers/redis_abstraction_resolver.py` | Modify | Add Go Redis patterns |
| `graph_builder/main.py` | Modify | Integrate new resolvers into build pipeline |
| `graph_builder/validate/coverage_report.py` | Modify | Add CallResolver + builtin stats |
| `graph_builder/validate/graph_health.py` | Modify | Add builtin classification stats |
| `graph_builder/ingestion/writer.py` | Modify | Write classification property on CALLS edges, write BUNDLES edges |
| `graph_builder/tests/test_builtin_classifier.py` | Create | Tests for builtin classification |
| `graph_builder/tests/test_endpoint_linker.py` | Create | Tests for cross-language URL matching |
| `graph_builder/tests/test_collector_resolver.py` | Create | Tests for collector registration parsing |
| `graph_builder/tests/test_go_redis.py` | Create | Tests for Go Redis detection |
| `graph_builder/tests/fixtures/lua/collector_init.lua` | Create | Test fixture |
| `graph_builder/tests/fixtures/go/redis_client.go` | Create | Test fixture |

---

## Task 1: Builtin Classification

Classify every unresolved call as `builtin`, `external`, `dynamic`, or `truly_unresolved`. This turns the misleading 33.2% call resolution rate into an honest ~60-75% by showing that most "unresolved" calls are to language builtins or external libraries that don't need resolution.

**Files:**
- Create: `graph_builder/resolvers/builtin_classifier.py`
- Create: `graph_builder/tests/test_builtin_classifier.py`
- Modify: `graph_builder/parsers/base.py:56-65`
- Modify: `graph_builder/main.py:196-203`
- Modify: `graph_builder/ingestion/writer.py` (CALLS edge properties)
- Modify: `graph_builder/validate/graph_health.py:162+`

### Step 1: Add classification field to CallRef

- [ ] **1.1: Modify CallRef in base.py**

In `graph_builder/parsers/base.py`, add a new field after `resolution_confidence`:

```python
@dataclass
class CallRef:
    """A function/method call."""
    caller_function: str
    callee_string: str
    line: int
    is_pcall_wrapped: bool = False
    resolved_module: str | None = None
    resolved_function: str | None = None
    resolved_file_path: str | None = None
    resolution_confidence: str | None = None
    classification: str | None = None  # "builtin", "external", "dynamic", "truly_unresolved", or None (resolved)
```

- [ ] **1.2: Verify no tests break**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All 44 tests pass (adding an optional field doesn't break anything)

### Step 2: Write the classifier test

- [ ] **2.1: Create test file**

Create `graph_builder/tests/test_builtin_classifier.py`:

```python
"""Tests for builtin/external call classification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import CallRef, FileAST
from graph_builder.resolvers.builtin_classifier import BuiltinClassifier


def _make_ast(language: str, calls: list[CallRef]) -> FileAST:
    """Helper to create a minimal FileAST with calls."""
    ast = FileAST(file_path=f"test.{language[:2]}", language=language)
    ast.calls = calls
    return ast


def test_lua_builtins():
    """Lua global builtins should be classified as 'builtin'."""
    calls = [
        CallRef(caller_function="foo", callee_string="print", line=1),
        CallRef(caller_function="foo", callee_string="pairs", line=2),
        CallRef(caller_function="foo", callee_string="tonumber", line=3),
        CallRef(caller_function="foo", callee_string="type", line=4),
        CallRef(caller_function="foo", callee_string="pcall", line=5),
        CallRef(caller_function="foo", callee_string="setmetatable", line=6),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_lua_stdlib():
    """Lua stdlib calls (string.*, table.*, math.*) should be 'builtin'."""
    calls = [
        CallRef(caller_function="foo", callee_string="string.format", line=1),
        CallRef(caller_function="foo", callee_string="table.insert", line=2),
        CallRef(caller_function="foo", callee_string="math.floor", line=3),
        CallRef(caller_function="foo", callee_string="os.time", line=4),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_lua_openresty():
    """OpenResty ngx.* calls should be 'builtin'."""
    calls = [
        CallRef(caller_function="foo", callee_string="ngx.log", line=1),
        CallRef(caller_function="foo", callee_string="ngx.say", line=2),
        CallRef(caller_function="foo", callee_string="ngx.exit", line=3),
        CallRef(caller_function="foo", callee_string="ngx.req.get_uri_args", line=4),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_lua_external():
    """External library calls (cjson.*, resty.*) should be 'external'."""
    calls = [
        CallRef(caller_function="foo", callee_string="cjson.encode", line=1),
        CallRef(caller_function="foo", callee_string="cjson.decode", line=2),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    for call in calls:
        assert call.classification == "external", f"{call.callee_string} should be external"


def test_python_builtins():
    """Python builtins should be classified."""
    calls = [
        CallRef(caller_function="foo", callee_string="print", line=1),
        CallRef(caller_function="foo", callee_string="len", line=2),
        CallRef(caller_function="foo", callee_string="isinstance", line=3),
        CallRef(caller_function="foo", callee_string="str", line=4),
    ]
    ast = _make_ast("python", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.py": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_go_builtins():
    """Go builtins (make, len, append, etc.) should be classified."""
    calls = [
        CallRef(caller_function="foo", callee_string="make", line=1),
        CallRef(caller_function="foo", callee_string="len", line=2),
        CallRef(caller_function="foo", callee_string="append", line=3),
        CallRef(caller_function="foo", callee_string="fmt.Println", line=4),
    ]
    ast = _make_ast("go", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.go": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_js_builtins():
    """JS builtins (console.*, JSON.*, etc.) should be classified."""
    calls = [
        CallRef(caller_function="foo", callee_string="console.log", line=1),
        CallRef(caller_function="foo", callee_string="JSON.parse", line=2),
        CallRef(caller_function="foo", callee_string="parseInt", line=3),
        CallRef(caller_function="foo", callee_string="setTimeout", line=4),
    ]
    ast = _make_ast("javascript", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.js": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_ruby_builtins():
    """Ruby builtins (puts, require, etc.) should be classified."""
    calls = [
        CallRef(caller_function="foo", callee_string="puts", line=1),
        CallRef(caller_function="foo", callee_string="raise", line=2),
        CallRef(caller_function="foo", callee_string="require", line=3),
    ]
    ast = _make_ast("ruby", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.rb": ast})

    for call in calls:
        assert call.classification == "builtin", f"{call.callee_string} should be builtin"


def test_dynamic_calls():
    """Calls with is_dynamic or pcall-wrapped dynamic patterns should be 'dynamic'."""
    calls = [
        CallRef(caller_function="foo", callee_string="require", line=1,
                is_pcall_wrapped=True),
    ]
    # Dynamic classification is handled for imports, not plain calls
    # This tests that pcall-wrapped require is classified as dynamic
    ast = _make_ast("lua", calls)
    # require is a builtin — pcall wrapping doesn't change that
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})
    assert calls[0].classification == "builtin"


def test_resolved_calls_not_classified():
    """Already-resolved calls should NOT be classified (classification stays None).

    Note: classifier checks resolved_module (not resolved_file_path) because
    many CallResolver strategies set module without setting file path.
    """
    calls = [
        CallRef(caller_function="foo", callee_string="my_module.do_thing", line=1,
                resolved_module="my_module", resolved_function="do_thing"),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    assert calls[0].classification is None, "Resolved calls should not be classified"


def test_truly_unresolved():
    """Calls that aren't builtin/external/dynamic should be 'truly_unresolved'."""
    calls = [
        CallRef(caller_function="foo", callee_string="some_unknown_func", line=1),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})

    assert calls[0].classification == "truly_unresolved"


def test_stats():
    """BuiltinClassifier.stats() should return counts per category."""
    calls = [
        CallRef(caller_function="foo", callee_string="print", line=1),           # builtin
        CallRef(caller_function="foo", callee_string="cjson.encode", line=2),     # external
        CallRef(caller_function="foo", callee_string="unknown_func", line=3),     # truly_unresolved
        CallRef(caller_function="foo", callee_string="my.func", line=4,           # resolved (skip)
                resolved_module="my", resolved_function="func",
                resolved_file_path="src/my.lua"),
    ]
    ast = _make_ast("lua", calls)
    classifier = BuiltinClassifier()
    classifier.classify_all({"test.lu": ast})
    stats = classifier.stats()

    assert stats["builtin"] == 1
    assert stats["external"] == 1
    assert stats["truly_unresolved"] == 1
    assert stats["skipped_resolved"] == 1
```

- [ ] **2.2: Run test to verify it fails**

Run: `python -m pytest graph_builder/tests/test_builtin_classifier.py -v`
Expected: ImportError — `builtin_classifier` module doesn't exist yet

### Step 3: Implement the classifier

- [ ] **3.1: Create builtin_classifier.py**

Create `graph_builder/resolvers/builtin_classifier.py`:

```python
"""Classify unresolved calls as builtin, external, dynamic, or truly_unresolved.

This runs AFTER CallResolver. Any call that CallResolver couldn't resolve
gets classified here so that reporting shows the real resolution gap
(truly_unresolved) vs noise (builtins/externals that don't need resolution).
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


# ---------------------------------------------------------------------------
# Per-language builtin / external lookup tables
# ---------------------------------------------------------------------------

# Lua global builtins (functions available without require)
_LUA_GLOBAL_BUILTINS = {
    "assert", "collectgarbage", "dofile", "error", "getmetatable",
    "ipairs", "load", "loadfile", "next", "pairs", "pcall", "print",
    "rawequal", "rawget", "rawlen", "rawset", "require", "select",
    "setmetatable", "tonumber", "tostring", "type", "unpack", "xpcall",
}

# Lua stdlib module prefixes (string.*, table.*, etc.)
_LUA_STDLIB_PREFIXES = {
    "string", "table", "math", "io", "os", "coroutine", "debug", "package",
    "utf8", "bit",
}

# OpenResty builtin prefixes
_LUA_OPENRESTY_PREFIXES = {
    "ngx", "ndk",
}

# External Lua packages (commonly used, not part of stdlib or application)
_LUA_EXTERNAL_PREFIXES = {
    "cjson", "cmsgpack", "resty", "lfs", "lpeg", "socket",
    "pgmoon", "redis", "mysql",
}

# Python builtins
_PYTHON_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "breakpoint", "bytearray",
    "bytes", "callable", "chr", "classmethod", "compile", "complex",
    "delattr", "dict", "dir", "divmod", "enumerate", "eval", "exec",
    "filter", "float", "format", "frozenset", "getattr", "globals",
    "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max",
    "memoryview", "min", "next", "object", "oct", "open", "ord", "pow",
    "print", "property", "range", "repr", "reversed", "round", "set",
    "setattr", "slice", "sorted", "staticmethod", "str", "sum", "super",
    "tuple", "type", "vars", "zip",
}

# Python stdlib prefixes
_PYTHON_STDLIB_PREFIXES = {
    "os", "sys", "json", "re", "subprocess", "urllib", "collections",
    "datetime", "time", "pathlib", "logging", "threading", "multiprocessing",
    "functools", "itertools", "hashlib", "hmac", "base64", "copy",
    "math", "random", "struct", "io", "abc", "typing", "enum",
    "contextlib", "traceback", "inspect", "signal", "socket", "http",
    "email", "csv", "xml", "argparse", "unittest", "shutil", "tempfile",
    "glob", "fnmatch", "pickle", "shelve", "sqlite3",
}

# Go builtins
_GO_BUILTINS = {
    "append", "cap", "clear", "close", "complex", "copy", "delete",
    "imag", "len", "make", "max", "min", "new", "panic", "print",
    "println", "real", "recover",
}

# Go stdlib prefixes
_GO_STDLIB_PREFIXES = {
    "fmt", "io", "os", "path", "filepath", "strings", "bytes",
    "strconv", "encoding", "json", "net", "http", "sync", "time",
    "regexp", "sort", "errors", "context", "reflect", "testing",
    "log", "math", "crypto", "bufio", "flag", "runtime", "unsafe",
    "database", "html", "text", "image", "archive", "compress",
}

# JavaScript builtins
_JS_BUILTINS = {
    "parseInt", "parseFloat", "isNaN", "isFinite", "decodeURI",
    "decodeURIComponent", "encodeURI", "encodeURIComponent",
    "eval", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "alert", "confirm",
    "prompt", "atob", "btoa",
}

# JS builtin object prefixes
_JS_BUILTIN_PREFIXES = {
    "console", "JSON", "Math", "Date", "Array", "Object", "String",
    "Number", "Boolean", "RegExp", "Error", "Promise", "Map", "Set",
    "WeakMap", "WeakSet", "Symbol", "Proxy", "Reflect", "Intl",
    "ArrayBuffer", "DataView", "Float32Array", "Float64Array",
    "Int8Array", "Int16Array", "Int32Array", "Uint8Array",
    "document", "window", "navigator", "location", "history",
    "localStorage", "sessionStorage", "XMLHttpRequest", "fetch",
    "URL", "URLSearchParams", "FormData", "Headers", "Request",
    "Response", "Blob", "File", "FileReader", "EventSource",
    "WebSocket",
}

# Ruby builtins
_RUBY_BUILTINS = {
    "puts", "print", "p", "pp", "raise", "fail", "require", "require_relative",
    "load", "include", "extend", "prepend", "attr_reader", "attr_writer",
    "attr_accessor", "public", "private", "protected", "module_function",
    "lambda", "proc", "block_given?", "yield", "catch", "throw",
    "loop", "sleep", "exit", "abort", "at_exit", "rand", "srand",
    "gets", "readline", "readlines", "sprintf", "format", "warn",
    "open", "select", "caller", "binding", "eval", "exec", "system",
    "fork", "spawn",
}

# Ruby stdlib prefixes
_RUBY_STDLIB_PREFIXES = {
    "File", "Dir", "IO", "Time", "Date", "DateTime", "Regexp", "MatchData",
    "Array", "Hash", "String", "Integer", "Float", "Numeric", "Range",
    "Enumerable", "Comparable", "Kernel", "Process", "Signal", "Thread",
    "Mutex", "Queue", "ENV", "ARGV", "STDIN", "STDOUT", "STDERR",
    "JSON", "YAML", "CSV", "ERB", "FileUtils", "Pathname", "URI",
    "Net", "Socket", "OpenSSL", "Digest", "Base64", "SecureRandom",
    "Logger", "Tempfile", "StringIO",
}


def _classify_lua(callee: str) -> str | None:
    """Classify a Lua call."""
    bare = callee.split(".")[0].split(":")[0]

    if bare in _LUA_GLOBAL_BUILTINS:
        return "builtin"
    if bare in _LUA_STDLIB_PREFIXES:
        return "builtin"
    if bare in _LUA_OPENRESTY_PREFIXES:
        return "builtin"
    if bare in _LUA_EXTERNAL_PREFIXES:
        return "external"
    return None


def _classify_python(callee: str) -> str | None:
    """Classify a Python call."""
    bare = callee.split(".")[0]

    if bare in _PYTHON_BUILTINS:
        return "builtin"
    if bare in _PYTHON_STDLIB_PREFIXES:
        return "builtin"
    return None


def _classify_go(callee: str) -> str | None:
    """Classify a Go call."""
    bare = callee.split(".")[0]

    if bare in _GO_BUILTINS:
        return "builtin"
    if bare in _GO_STDLIB_PREFIXES:
        return "builtin"
    return None


def _classify_js(callee: str) -> str | None:
    """Classify a JavaScript call."""
    bare = callee.split(".")[0]

    if bare in _JS_BUILTINS:
        return "builtin"
    if bare in _JS_BUILTIN_PREFIXES:
        return "builtin"
    return None


def _classify_ruby(callee: str) -> str | None:
    """Classify a Ruby call."""
    bare = callee.split(".")[0]

    if bare in _RUBY_BUILTINS:
        return "builtin"
    if bare in _RUBY_STDLIB_PREFIXES:
        return "builtin"
    return None


_CLASSIFIERS = {
    "lua": _classify_lua,
    "python": _classify_python,
    "go": _classify_go,
    "javascript": _classify_js,
    "ruby": _classify_ruby,
}


class BuiltinClassifier:
    """Classify unresolved calls as builtin/external/dynamic/truly_unresolved."""

    def __init__(self):
        self._counts = {
            "builtin": 0,
            "external": 0,
            "dynamic": 0,
            "truly_unresolved": 0,
            "skipped_resolved": 0,
        }

    def classify_all(self, all_asts: dict[str, FileAST]):
        """Classify all unresolved calls in all ASTs. Modifies CallRef in place."""
        for file_path, ast in all_asts.items():
            classifier_fn = _CLASSIFIERS.get(ast.language)
            if not classifier_fn:
                continue

            for call in ast.calls:
                # Skip already-resolved calls (check resolved_module, not resolved_file_path,
                # because many resolution strategies set module without file path)
                if call.resolved_module:
                    self._counts["skipped_resolved"] += 1
                    continue

                result = classifier_fn(call.callee_string)
                if result:
                    call.classification = result
                else:
                    call.classification = "truly_unresolved"

                self._counts[call.classification] += 1

    def stats(self) -> dict:
        """Return classification counts."""
        return dict(self._counts)
```

- [ ] **3.2: Run tests to verify they pass**

Run: `python -m pytest graph_builder/tests/test_builtin_classifier.py -v`
Expected: All tests pass

- [ ] **3.3: Run all tests to verify no regressions**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All 44+ tests pass

### Step 4: Integrate into the build pipeline

- [ ] **4.1: Add import in main.py**

In `graph_builder/main.py`, add after line 33:

```python
from .resolvers.builtin_classifier import BuiltinClassifier
```

- [ ] **4.2: Add classifier step in build command**

In `graph_builder/main.py`, after the Redis abstraction block (after line 203), add:

```python
    # Step 4c: Classify unresolved calls
    click.echo("Classifying unresolved calls...")
    classifier = BuiltinClassifier()
    classifier.classify_all(all_asts)
    class_stats = classifier.stats()
    click.echo(f"  Builtins: {class_stats['builtin']}, External: {class_stats['external']}, "
               f"Truly unresolved: {class_stats['truly_unresolved']}")
```

- [ ] **4.3: Add classification property to CALLS edges in writer.py**

In `graph_builder/ingestion/writer.py`, modify the `upsert_call` method to accept and store classification. Add `classification: str | None = None` parameter, then include it in the edge properties:

```python
def upsert_call(self, from_func, from_file, to_func, to_file,
                line, is_pcall=False, classification=None):
```

For unresolved calls (when `to_file` is None), add classification to the CALLS edge:

```python
    MERGE (a)-[:CALLS {line: row.line, is_pcall: row.is_pcall,
                       classification: row.classification}]->(b)
```

And in `ingest_file_ast`, pass the classification when calling `upsert_call`:

```python
    classification=call.classification
```

- [ ] **4.4: Run full test suite**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass

### Step 5: Add classification to health report

- [ ] **5.1: Add BuiltinClassifier to graph_health.py**

In `graph_builder/validate/graph_health.py`, import BuiltinClassifier and run it after call resolution (after line 162):

```python
    # --- Step 4b: Classify unresolved calls ---
    from graph_builder.resolvers.builtin_classifier import BuiltinClassifier
    classifier = BuiltinClassifier()
    classifier.classify_all(all_asts)
    class_stats = classifier.stats()
```

Then add a section in the report output showing:
- Builtin calls: N (X%)
- External calls: N (X%)
- Truly unresolved: N (X%)
- Effective resolution rate: (resolved + builtin + external) / total

- [ ] **5.2: Commit**

```bash
git add graph_builder/parsers/base.py graph_builder/resolvers/builtin_classifier.py \
       graph_builder/tests/test_builtin_classifier.py graph_builder/main.py \
       graph_builder/validate/graph_health.py graph_builder/ingestion/writer.py
git commit -m "feat: add builtin/external call classification

Classifies unresolved calls as builtin, external, dynamic, or truly_unresolved.
Shows effective resolution rate by filtering out noise from builtins/externals."
```

---

## Task 2: Cross-Language URL Matching

Link HTTP call URLs from JS/Lua/Python to their target nginx endpoint handlers. When JS calls `sendRequest("POST", "/api/assess")`, link it to the nginx location `/api/assess` and its Lua handler file. When Lua calls `httpc:connect("unix:/tmp/model_prediction.sock")`, link it to the Go handler at `/predict`.

**Files:**
- Create: `graph_builder/resolvers/endpoint_linker.py`
- Create: `graph_builder/tests/test_endpoint_linker.py`
- Modify: `graph_builder/main.py`
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Write the test

- [ ] **1.1: Create test file**

Create `graph_builder/tests/test_endpoint_linker.py`:

```python
"""Tests for cross-language endpoint linking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import FileAST, HttpCallRef, FunctionDef
from graph_builder.parsers.nginx_parser import NginxConfig, NginxLocation, NginxLuaPhase
from graph_builder.resolvers.endpoint_linker import EndpointLinker


def _make_nginx_config(locations: list[dict]) -> NginxConfig:
    """Helper to build a minimal NginxConfig."""
    locs = []
    for loc in locations:
        phases = [NginxLuaPhase(
            directive="content_by_lua_block",
            phase=loc.get("phase", "content"),
            is_inline=False,
            lua_file=loc["lua_file"],
            inline_code=None,
            line=1,
        )]
        locs.append(NginxLocation(
            path=loc["path"],
            modifier=loc.get("modifier"),
            line=1,
            phases=phases,
            proxy_pass=loc.get("proxy_pass"),
        ))
    return NginxConfig(locations=locs, upstreams=[])


def test_exact_match():
    """JS HTTP call to /api/assess matches nginx location /api/assess."""
    nginx = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "src/ato/assess.lua"},
    ])
    ast = FileAST(file_path="src/js/collector.js", language="javascript")
    ast.http_calls = [
        HttpCallRef(url_or_path="/api/assess", method="POST",
                    function="sendData", line=10),
    ]

    linker = EndpointLinker(nginx)
    links = linker.link_all({"src/js/collector.js": ast})

    assert len(links) == 1
    assert links[0]["source_file"] == "src/js/collector.js"
    assert links[0]["target_lua_file"] == "src/ato/assess.lua"
    assert links[0]["endpoint"] == "/api/assess"


def test_prefix_match():
    """HTTP call to /api/assess/result matches nginx location /api/assess."""
    nginx = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "src/ato/assess.lua"},
    ])
    ast = FileAST(file_path="src/js/collector.js", language="javascript")
    ast.http_calls = [
        HttpCallRef(url_or_path="/api/assess/result", method="POST",
                    function="sendData", line=10),
    ]

    linker = EndpointLinker(nginx)
    links = linker.link_all({"src/js/collector.js": ast})

    assert len(links) == 1
    assert links[0]["endpoint"] == "/api/assess"


def test_unix_socket_to_go():
    """Lua unix socket call should link to Go handler."""
    nginx = _make_nginx_config([])  # No nginx locations for Go services
    ast = FileAST(file_path="src/lib/lua/predictor.lua", language="lua")
    ast.http_calls = [
        HttpCallRef(url_or_path="unix:/tmp/model_prediction.sock",
                    method="UNIX_CONNECT", function="call_model", line=15),
    ]

    linker = EndpointLinker(nginx)
    linker.register_go_handlers({
        "/tmp/model_prediction.sock": {
            "/predict": "src/core/model_prediction/server/main.go",
            "/health": "src/core/model_prediction/server/main.go",
        }
    })
    links = linker.link_all({"src/lib/lua/predictor.lua": ast})

    assert len(links) == 1
    assert links[0]["target_go_file"] == "src/core/model_prediction/server/main.go"
    assert links[0]["socket"] == "/tmp/model_prediction.sock"


def test_no_match():
    """External URLs should not match nginx locations."""
    nginx = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "src/ato/assess.lua"},
    ])
    ast = FileAST(file_path="src/js/external.js", language="javascript")
    ast.http_calls = [
        HttpCallRef(url_or_path="https://external-api.com/v1/data",
                    method="GET", function="fetchExternal", line=5),
    ]

    linker = EndpointLinker(nginx)
    links = linker.link_all({"src/js/external.js": ast})

    assert len(links) == 0


def test_longest_prefix_wins():
    """When multiple locations match, longest prefix wins (nginx behavior)."""
    nginx = _make_nginx_config([
        {"path": "/api", "lua_file": "src/api_root.lua"},
        {"path": "/api/assess", "lua_file": "src/ato/assess.lua"},
    ])
    ast = FileAST(file_path="src/js/collector.js", language="javascript")
    ast.http_calls = [
        HttpCallRef(url_or_path="/api/assess", method="POST",
                    function="sendData", line=10),
    ]

    linker = EndpointLinker(nginx)
    links = linker.link_all({"src/js/collector.js": ast})

    assert len(links) == 1
    assert links[0]["target_lua_file"] == "src/ato/assess.lua"
```

- [ ] **1.2: Run test to verify it fails**

Run: `python -m pytest graph_builder/tests/test_endpoint_linker.py -v`
Expected: ImportError — `endpoint_linker` module doesn't exist yet

### Step 2: Implement the linker

- [ ] **2.1: Create endpoint_linker.py**

Create `graph_builder/resolvers/endpoint_linker.py`:

```python
"""Cross-language endpoint linker.

Matches HTTP call URLs from any language to their target endpoint handlers:
  - Internal paths (/api/assess) → nginx location → Lua handler file
  - Unix socket paths → Go HTTP handler registration
  - Proxy paths → upstream service

Uses nginx's longest-prefix-match rule for location matching.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


class EndpointLinker:
    """Links HTTP calls across languages to their handler endpoints."""

    def __init__(self, nginx_config=None):
        # nginx location path → {lua_file, phase, proxy_target}
        self._locations: dict[str, dict] = {}
        # unix socket path → {http_path → go_file}
        self._go_handlers: dict[str, dict[str, str]] = {}

        if nginx_config:
            for loc in nginx_config.locations:
                handler_info = {"path": loc.path}
                for phase in loc.phases:
                    if phase.lua_file:
                        handler_info["lua_file"] = phase.lua_file
                        break
                if loc.proxy_pass:
                    handler_info["proxy_target"] = loc.proxy_pass.target
                self._locations[loc.path] = handler_info

    def register_go_handlers(self, handlers: dict[str, dict[str, str]]):
        """Register Go HTTP handlers by unix socket path.

        Args:
            handlers: {socket_path: {http_path: go_file_path}}
        """
        self._go_handlers = handlers

    def _match_location(self, url_path: str) -> dict | None:
        """Find the best nginx location match using longest-prefix rule."""
        best_match = None
        best_len = 0

        for loc_path, info in self._locations.items():
            if url_path == loc_path or url_path.startswith(loc_path + "/"):
                if len(loc_path) > best_len:
                    best_match = info
                    best_len = len(loc_path)

        return best_match

    def _match_unix_socket(self, url: str) -> dict | None:
        """Match a unix socket URL to a Go handler."""
        # url format: "unix:/tmp/model_prediction.sock" or similar
        socket_path = url
        if socket_path.startswith("unix:"):
            socket_path = socket_path[5:]

        if socket_path in self._go_handlers:
            handlers = self._go_handlers[socket_path]
            # Return the first handler file (they're typically all in the same file)
            first_file = next(iter(handlers.values()), None)
            return {
                "socket": socket_path,
                "target_go_file": first_file,
                "handlers": handlers,
            }
        return None

    def link_all(self, all_asts: dict[str, FileAST]) -> list[dict]:
        """Link all HTTP calls to their target handlers.

        Returns a list of link dicts with source and target info.
        """
        links = []

        for file_path, ast in all_asts.items():
            for http_call in ast.http_calls:
                url = http_call.url_or_path

                # Case 1: Unix socket connection (Lua → Go)
                if http_call.method == "UNIX_CONNECT" or url.startswith("unix:"):
                    match = self._match_unix_socket(url)
                    if match:
                        links.append({
                            "source_file": file_path,
                            "source_function": http_call.function,
                            "source_line": http_call.line,
                            "method": http_call.method,
                            **match,
                        })
                    continue

                # Case 2: Internal path → nginx location
                if url.startswith("/"):
                    match = self._match_location(url)
                    if match:
                        link = {
                            "source_file": file_path,
                            "source_function": http_call.function,
                            "source_line": http_call.line,
                            "method": http_call.method,
                            "endpoint": match["path"],
                        }
                        if "lua_file" in match:
                            link["target_lua_file"] = match["lua_file"]
                        if "proxy_target" in match:
                            link["proxy_target"] = match["proxy_target"]
                        links.append(link)

                # Case 3: External URLs — skip (already marked in graph)

        return links

    def build_go_handler_registry(self, all_asts: dict[str, FileAST]) -> dict[str, dict[str, str]]:
        """Scan Go ASTs for unix socket listeners and HTTP handlers.

        Returns: {socket_path: {http_path: go_file_path}}
        """
        # Step 1: Find socket paths from warnings (unix_socket:path)
        socket_files: dict[str, str] = {}  # socket_path → file_path
        for file_path, ast in all_asts.items():
            if ast.language != "go":
                continue
            for warning in ast.warnings:
                if warning.startswith("unix_socket:"):
                    socket_path = warning[len("unix_socket:"):]
                    socket_files[socket_path] = file_path

        # Step 2: Find HTTP handlers in Go files with sockets
        registry: dict[str, dict[str, str]] = {}
        for socket_path, file_path in socket_files.items():
            ast = all_asts.get(file_path)
            if not ast:
                continue
            handlers: dict[str, str] = {}
            for http_call in ast.http_calls:
                # Go parser stores HandleFunc paths as http_calls
                handlers[http_call.url_or_path] = file_path
            if handlers:
                registry[socket_path] = handlers

        return registry
```

- [ ] **2.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_endpoint_linker.py -v`
Expected: All tests pass

### Step 3: Integrate into pipeline

- [ ] **3.1: Add EndpointLinker to main.py build command**

In `graph_builder/main.py`, after the classifier step and before ingestion, add:

```python
    # Step 4d: Cross-language endpoint linking
    click.echo("Linking cross-language endpoints...")
    from .resolvers.endpoint_linker import EndpointLinker
    nginx_config_obj = None
    if config.nginx_conf and Path(config.nginx_conf).exists():
        nginx_config_obj = parse_nginx_conf_recursive(
            config.nginx_conf, config.nginx_base_path,
        )
    linker = EndpointLinker(nginx_config_obj)
    go_registry = linker.build_go_handler_registry(all_asts)
    linker.register_go_handlers(go_registry)
    endpoint_links = linker.link_all(all_asts)
    if endpoint_links:
        click.echo(f"  Linked {len(endpoint_links)} cross-language HTTP calls to endpoints")
```

- [ ] **3.2: Add SERVES edge to writer.py**

In `graph_builder/ingestion/writer.py`, add a method to write cross-language links:

```python
    def upsert_endpoint_link(self, source_file: str, source_function: str,
                              endpoint_path: str, target_file: str,
                              method: str, line: int):
        """Create a cross-language endpoint link edge."""
        self._run("""
            MERGE (fn:Function {name: $func, file: $src_file})
            MERGE (e:Endpoint {path: $endpoint})
            MERGE (tf:File {path: $target_file})
            MERGE (fn)-[:HTTP_CALLS {method: $method, line: $line, cross_language: true}]->(e)
            MERGE (e)-[:SERVES]->(tf)
        """, func=source_function, src_file=source_file,
             endpoint=endpoint_path, target_file=target_file,
             method=method, line=line)
```

- [ ] **3.3: Wire endpoint links into ingestion**

After `writer.flush_all()` in main.py, iterate `endpoint_links` and call `upsert_endpoint_link` for each link.

- [ ] **3.4: Run all tests**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass

- [ ] **3.5: Commit**

```bash
git add graph_builder/resolvers/endpoint_linker.py \
       graph_builder/tests/test_endpoint_linker.py \
       graph_builder/main.py graph_builder/ingestion/writer.py
git commit -m "feat: add cross-language endpoint linking

Matches HTTP call URLs to nginx locations and Go unix socket handlers.
Enables tracing full request flows: JS -> nginx -> Lua -> Go."
```

---

## Task 3: Collector Registration Parsing

Parse Lua `init.lua` files that define collector registrations mapping JS files to endpoints, creating BUNDLES edges in the graph.

**Files:**
- Create: `graph_builder/resolvers/collector_resolver.py`
- Create: `graph_builder/tests/test_collector_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/collector_init.lua`
- Modify: `graph_builder/parsers/base.py`
- Modify: `graph_builder/parsers/lua_parser.py`
- Modify: `graph_builder/main.py`
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Create test fixture

- [ ] **1.1: Create collector init.lua fixture**

Create `graph_builder/tests/fixtures/lua/collector_init.lua`:

```lua
-- Collector registration file (init.lua)
local collector = {
    name = "device",
    js_files = {
        "device_utils.js.erb",
        "device_id.js.erb",
        "sensor.js.erb",
        "device_container.js.erb",
    },
    endpoint = "/api/device_id",
}

return collector
```

### Step 2: Add data model and write test

- [ ] **2.1: Add CollectorInfo to base.py**

In `graph_builder/parsers/base.py`, after the `HttpCallRef` class (after line 116), add:

```python
@dataclass
class CollectorInfo:
    """A collector registration from an init.lua file."""
    name: str                                     # "device", "behave", etc.
    endpoint: str                                  # "/api/device_id"
    js_files: list[str] = field(default_factory=list)  # ["device_utils.js.erb", ...]
    line: int = 0
```

Add to `FileAST` after `http_calls` (after line 163):

```python
    collector_info: CollectorInfo | None = None
```

- [ ] **2.2: Create test file**

Create `graph_builder/tests/test_collector_resolver.py`:

```python
"""Tests for collector registration parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.collector_resolver import resolve_collectors

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_parse_collector_init():
    """Parser should detect collector registration in init.lua."""
    ast = parse_lua_file(str(FIXTURES / "collector_init.lua"))
    assert ast.collector_info is not None
    assert ast.collector_info.name == "device"
    assert ast.collector_info.endpoint == "/api/device_id"
    assert len(ast.collector_info.js_files) == 4
    assert "device_utils.js.erb" in ast.collector_info.js_files


def test_resolve_collectors():
    """Collector resolver should map JS files to endpoints."""
    ast = parse_lua_file(str(FIXTURES / "collector_init.lua"))
    all_asts = {str(FIXTURES / "collector_init.lua"): ast}

    mappings = resolve_collectors(all_asts)
    assert len(mappings) == 1

    m = mappings[0]
    assert m["collector_name"] == "device"
    assert m["endpoint"] == "/api/device_id"
    assert len(m["js_files"]) == 4


def test_no_collector_in_normal_file():
    """Normal Lua files should not have collector_info."""
    # Use any existing fixture that is not a collector init
    other_fixtures = list(FIXTURES.glob("*.lua"))
    for f in other_fixtures:
        if "collector" not in f.name:
            ast = parse_lua_file(str(f))
            assert ast.collector_info is None
            break
```

- [ ] **2.3: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_collector_resolver.py -v`
Expected: ImportError or assertion failures

### Step 3: Implement collector detection in Lua parser

- [ ] **3.1: Add collector table detection to lua_parser.py**

In `graph_builder/parsers/lua_parser.py`, add a function to detect collector registration tables. Look for the pattern: a local variable assignment where the right side is a table constructor containing keys `name`, `js_files`, and `endpoint`. This should be called near the end of `parse_lua_file()`.

```python
def _detect_collector_registration(root, source, ast):
    """Detect collector = { name = ..., js_files = {...}, endpoint = ... } patterns."""
    from graph_builder.parsers.base import CollectorInfo

    for assign in _walk_all(root, "variable_declaration"):
        # Look for local X = { ... }
        for declarator in _walk_all(assign, "assignment_statement"):
            pass  # simpler: walk all table constructors in assignments

    # Walk all assignment statements looking for table constructors
    # with js_files key
    for node in _walk_all(root, "assignment_statement"):
        rhs_list = [c for c in node.children if c.type == "table_constructor"]
        if not rhs_list:
            continue

        for table in rhs_list:
            keys_found = {}
            for field_node in _walk_all(table, "field"):
                name_node = field_node.child_by_field_name("name")
                value_node = field_node.child_by_field_name("value")
                if not name_node or not value_node:
                    continue
                key = _text(name_node, source)
                if key == "name" and value_node.type == "string":
                    keys_found["name"] = _text(value_node, source).strip("'\"")
                elif key == "endpoint" and value_node.type == "string":
                    keys_found["endpoint"] = _text(value_node, source).strip("'\"")
                elif key == "js_files" and value_node.type == "table_constructor":
                    js_files = []
                    for item in value_node.named_children:
                        if item.type == "string":
                            js_files.append(_text(item, source).strip("'\""))
                    keys_found["js_files"] = js_files

            if "name" in keys_found and "js_files" in keys_found and "endpoint" in keys_found:
                ast.collector_info = CollectorInfo(
                    name=keys_found["name"],
                    endpoint=keys_found["endpoint"],
                    js_files=keys_found["js_files"],
                    line=node.start_point[0] + 1,
                )
                return  # Only one collector per file
```

Note: The exact Tree-sitter node traversal will need adaptation based on how Lua's tree-sitter grammar represents table fields. The above is a guide — check `_extract_table_keys()` in the existing parser for the exact pattern.

### Step 4: Implement collector resolver

- [ ] **4.1: Create collector_resolver.py**

Create `graph_builder/resolvers/collector_resolver.py`:

```python
"""Resolve collector registrations: map JS files to endpoints.

Scans all ASTs for collector_info and produces a mapping:
  collector_name → {endpoint, js_files[], init_file}
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def resolve_collectors(all_asts: dict[str, FileAST]) -> list[dict]:
    """Find all collector registrations and return their mappings.

    Returns list of dicts:
        [{"collector_name": "device", "endpoint": "/api/device_id",
          "js_files": ["device_utils.js.erb", ...], "init_file": "path/to/init.lua"}]
    """
    mappings = []

    for file_path, ast in all_asts.items():
        if ast.collector_info is None:
            continue

        mappings.append({
            "collector_name": ast.collector_info.name,
            "endpoint": ast.collector_info.endpoint,
            "js_files": ast.collector_info.js_files,
            "init_file": file_path,
        })

    return mappings
```

- [ ] **4.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_collector_resolver.py -v`
Expected: All tests pass

### Step 5: Integrate and commit

- [ ] **5.1: Add to main.py build command**

After endpoint linking step:

```python
    # Step 4e: Collector registration
    from .resolvers.collector_resolver import resolve_collectors
    collector_mappings = resolve_collectors(all_asts)
    if collector_mappings:
        click.echo(f"  Found {len(collector_mappings)} collector registrations")
```

- [ ] **5.2: Add BUNDLES edge to writer.py**

```python
    def upsert_collector_bundle(self, collector_name: str, endpoint: str,
                                 js_file: str, init_file: str):
        """Create a BUNDLES edge from a collector File to JS File via Endpoint."""
        self._run("""
            MERGE (init:File {path: $init_file})
            MERGE (js:File {path: $js_file})
            MERGE (e:Endpoint {path: $endpoint})
            MERGE (init)-[:BUNDLES {collector: $collector}]->(js)
            MERGE (js)-[:SERVES]->(e)
        """, init_file=init_file, js_file=js_file,
             endpoint=endpoint, collector=collector_name)
```

- [ ] **5.3: Run all tests**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass

- [ ] **5.4: Commit**

```bash
git add graph_builder/parsers/base.py graph_builder/parsers/lua_parser.py \
       graph_builder/resolvers/collector_resolver.py \
       graph_builder/tests/test_collector_resolver.py \
       graph_builder/tests/fixtures/lua/collector_init.lua \
       graph_builder/main.py graph_builder/ingestion/writer.py
git commit -m "feat: parse collector registrations (js_files -> endpoint)

Detects collector init.lua files with js_files arrays and endpoint strings.
Creates BUNDLES edges connecting JS files to their serving endpoints."
```

---

## Task 4: Go Redis Abstraction Detection

Detect Redis calls in Go code through the `redisClient.Method()` wrapper pattern, similar to how the Lua store abstraction resolver works.

**Files:**
- Create: `graph_builder/tests/test_go_redis.py`
- Create: `graph_builder/tests/fixtures/go/redis_client.go`
- Modify: `graph_builder/resolvers/redis_abstraction_resolver.py`
- Modify: `graph_builder/main.py`
- Note: `graph_builder/parsers/go_parser.py` needs NO changes — it already captures `s.redisClient.GetAsString` as regular call expressions

### Step 1: Create test fixture

- [ ] **1.1: Create Go Redis fixture**

Create `graph_builder/tests/fixtures/go/redis_client.go`:

```go
package server

import (
	"context"
	"github.com/go-redis/redis/v8"
	"time"
)

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

type Server struct {
	redisClient *RedisClient
}

func (s *Server) predict(sessionID string) string {
	modelData, _ := s.redisClient.GetAsString("model:latest")
	s.redisClient.Set("prediction:"+sessionID, modelData, 24*time.Hour)
	cached, _ := s.redisClient.HGet("cache:models", "default")
	return cached
}
```

### Step 2: Write test

- [ ] **2.1: Create test file**

Create `graph_builder/tests/test_go_redis.py`:

```python
"""Tests for Go Redis abstraction detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_go_redis_abstractions

FIXTURES = Path(__file__).parent / "fixtures" / "go"


def test_go_parser_detects_redis_calls():
    """Go parser should detect redisClient.Method() calls."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))

    # The predict function calls redisClient 3 times
    redis_calls = [c for c in ast.calls
                   if "redisClient" in c.callee_string or "redis" in c.callee_string.lower()]
    assert len(redis_calls) >= 3, f"Expected 3+ Redis calls, got {len(redis_calls)}"


def test_go_redis_resolver():
    """Go Redis resolver should create RedisKeyAccess entries."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))
    all_asts = {str(FIXTURES / "redis_client.go"): ast}

    before = len(ast.redis_accesses)
    resolve_go_redis_abstractions(all_asts)
    after = len(ast.redis_accesses)

    assert after > before, f"Expected Redis accesses to increase, got {before} -> {after}"
    assert after >= 3, f"Expected at least 3 Redis accesses, got {after}"

    # Check read/write classification
    reads = [a for a in ast.redis_accesses if a.access_type == "read"]
    writes = [a for a in ast.redis_accesses if a.access_type == "write"]
    assert len(reads) >= 2, "GetAsString and HGet should be reads"
    assert len(writes) >= 1, "Set should be a write"
```

- [ ] **2.2: Run test to verify it fails**

Run: `python -m pytest graph_builder/tests/test_go_redis.py -v`
Expected: Failures (no Redis detection yet)

### Step 3: Implement Go Redis detection

- [ ] **3.1: Add Go Redis method map to redis_abstraction_resolver.py**

In `graph_builder/resolvers/redis_abstraction_resolver.py`, add after the existing module maps:

```python
# Go Redis client methods (go-redis library + custom wrappers)
_GO_REDIS_READ = {
    "Get", "GetAsString", "GetRange", "GetSet", "GetEx", "GetDel",
    "Strlen", "Exists", "Type", "TTL", "PTTL", "Keys", "Scan",
    "HGet", "HGetAll", "HMGet", "HExists", "HKeys", "HVals", "HLen",
    "SMembers", "SIsMember", "SCard", "SRandMember",
    "ZRange", "ZRangeByScore", "ZRank", "ZScore", "ZCard",
    "LRange", "LLen", "LIndex",
}

_GO_REDIS_WRITE = {
    "Set", "SetEX", "SetNX", "Append", "Incr", "IncrBy", "Decr", "DecrBy",
    "Del", "Expire", "ExpireAt", "PExpire", "Persist",
    "HSet", "HMSet", "HDel", "HIncrBy",
    "SAdd", "SRem", "SPop",
    "ZAdd", "ZRem", "ZIncrBy",
    "LPush", "RPush", "LPop", "RPop", "LSet", "LTrim",
    "Publish",
}

_GO_REDIS_INDICATORS = {"redisClient", "RedisClient", "redis.Client", "rdb", "redisConn"}


def resolve_go_redis_abstractions(all_asts: dict[str, "FileAST"]):
    """Detect Redis calls in Go code through client wrapper patterns.

    Looks for calls like:
        s.redisClient.GetAsString(key)
        r.client.Get(ctx, key)
        redisClient.Set(key, val, ttl)
    """
    from graph_builder.parsers.base import RedisKeyAccess

    for file_path, ast in all_asts.items():
        if ast.language != "go":
            continue

        for call in ast.calls:
            callee = call.callee_string
            parts = callee.rsplit(".", 1)
            if len(parts) != 2:
                continue

            receiver, method = parts

            # Check if receiver contains a Redis indicator
            is_redis = any(indicator in receiver for indicator in _GO_REDIS_INDICATORS)
            if not is_redis:
                # Also check if the receiver ends with a lowercase redis-ish name
                receiver_tail = receiver.rsplit(".", 1)[-1]
                is_redis = receiver_tail.lower() in {"redisclient", "redis", "rdb", "redisconn", "rclient"}

            if not is_redis:
                continue

            if method in _GO_REDIS_READ:
                access_type = "read"
            elif method in _GO_REDIS_WRITE:
                access_type = "write"
            else:
                continue

            ast.redis_accesses.append(RedisKeyAccess(
                key_name=f"<via go:{receiver}>",
                operation=method,
                access_type=access_type,
                function=call.caller_function,
                line=call.line,
            ))
```

- [ ] **3.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_go_redis.py -v`
Expected: All tests pass

### Step 4: Integrate and commit

- [ ] **4.1: Add to main.py**

In `graph_builder/main.py`, after `resolve_redis_abstractions(all_asts)` (line 199), add:

```python
    resolve_go_redis_abstractions(all_asts)
```

And add the import at the top:

```python
from .resolvers.redis_abstraction_resolver import resolve_redis_abstractions, resolve_go_redis_abstractions
```

- [ ] **4.2: Run all tests**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass

- [ ] **4.3: Commit**

```bash
git add graph_builder/resolvers/redis_abstraction_resolver.py \
       graph_builder/parsers/go_parser.py \
       graph_builder/tests/test_go_redis.py \
       graph_builder/tests/fixtures/go/redis_client.go \
       graph_builder/main.py
git commit -m "feat: detect Go Redis calls through redisClient wrapper

Identifies Redis read/write operations in Go code via redisClient.Method()
patterns. Adds RedisKeyAccess entries for Go files."
```

---

## Task 5: Validate Running CallResolver

**Depends on:** Task 1 (imports `BuiltinClassifier` from `builtin_classifier.py`). Build Task 1 first.

Wire up CallResolver in the `validate` command so it shows the same 33.2% resolution rate as `health` instead of the misleading lower number.

**Files:**
- Modify: `graph_builder/validate/coverage_report.py`
- Modify: `graph_builder/main.py:269-275`

### Step 1: Modify coverage_report.py

- [ ] **1.1: Add CallResolver to coverage_report.py**

In `graph_builder/validate/coverage_report.py`, add imports at the top:

```python
from graph_builder.resolvers.call_resolver import CallResolver
from graph_builder.resolvers.lua_resolver import LuaResolver
from graph_builder.resolvers.python_resolver import PythonResolver
from graph_builder.resolvers.go_resolver import GoResolver
from graph_builder.resolvers.js_resolver import JsResolver
from graph_builder.resolvers.ruby_resolver import RubyResolver
from graph_builder.resolvers.builtin_classifier import BuiltinClassifier
```

- [ ] **1.2: Modify run_coverage_report to accept config**

Change the signature of `run_coverage_report` to optionally accept a full `Config` object (keeping backward compatibility):

```python
def run_coverage_report(repo_root: str, nginx_conf: str | None = None,
                        nginx_base_path: str | None = None,
                        config=None) -> str:
```

After parsing all files, if config is provided, build resolvers and run CallResolver:

```python
    # Optional: run full call resolution if config provided
    if config:
        resolvers = _build_resolvers_for_validate(all_asts, config)
        call_resolver = CallResolver(all_asts, resolvers)
        call_resolver.resolve_all()
        call_stats = call_resolver.stats()

        classifier = BuiltinClassifier()
        classifier.classify_all(all_asts)
        class_stats = classifier.stats()
```

Add this helper function in `coverage_report.py` (copy structure from `graph_health.py:_build_resolvers`):

```python
def _build_resolvers_for_validate(all_asts, config):
    """Build language-specific resolvers for call resolution."""
    from graph_builder.resolvers.lua_resolver import LuaResolver
    from graph_builder.resolvers.python_resolver import PythonResolver
    from graph_builder.resolvers.go_resolver import GoResolver
    from graph_builder.resolvers.js_resolver import JsResolver
    from graph_builder.resolvers.ruby_resolver import RubyResolver

    resolvers = {}

    lua_files = [fp for fp, ast in all_asts.items() if ast.language == "lua"]
    py_files = [fp for fp, ast in all_asts.items() if ast.language == "python"]
    go_files = [fp for fp, ast in all_asts.items() if ast.language == "go"]
    js_files = [fp for fp, ast in all_asts.items() if ast.language == "javascript"]
    rb_files = [fp for fp, ast in all_asts.items() if ast.language == "ruby"]

    if lua_files:
        lua_package_paths = getattr(config, "lua_package_paths", None) or []
        resolvers["lua"] = LuaResolver(lua_files, lua_package_paths)
    if py_files:
        resolvers["python"] = PythonResolver(py_files)
    if go_files:
        resolvers["go"] = GoResolver(go_files)
    if js_files:
        resolvers["js"] = JsResolver(js_files)
    if rb_files:
        resolvers["ruby"] = RubyResolver(rb_files)

    return resolvers
```

- [ ] **1.3: Update validate command in main.py**

In `graph_builder/main.py`, modify the validate command to pass the full config:

```python
@cli.command()
@click.pass_context
def validate(ctx):
    """Run the coverage report against the codebase."""
    config = ctx.obj["config"]
    report = run_coverage_report(
        config.repo_root, config.nginx_conf, config.nginx_base_path,
        config=config,
    )
    click.echo(report)
```

- [ ] **1.4: Run all tests**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: All tests pass

- [ ] **1.5: Commit**

```bash
git add graph_builder/validate/coverage_report.py graph_builder/main.py
git commit -m "feat: add CallResolver + builtin classification to validate command

Validate now runs the full resolution pipeline (import resolution, call
resolution, builtin classification) matching the health command's output."
```

---

## Integration Verification

After all 5 tasks are complete:

- [ ] **Run the full test suite**

```bash
python -m pytest graph_builder/tests/ -v
```

Expected: All tests pass (44 original + ~20 new)

- [ ] **Run against the product codebase** (on Mac)

```bash
code-graph health -c config.yml
code-graph validate -c config.yml
code-graph build -c config.yml
```

Verify:
- Health report shows builtin/external/truly_unresolved breakdown
- Validate shows same resolution rate as health
- Build completes with endpoint linking and collector detection messages
- Redis accesses include Go Redis calls

---

## Summary

| Task | New Edges/Metrics | Effort |
|------|-------------------|--------|
| 1. Builtin Classification | Shows ~60-75% effective resolution (was misleading 33%) | Medium |
| 2. Cross-Language URL Matching | +50-100 JS→Lua and Lua→Go links | Medium |
| 3. Collector Registration | +20-40 JS→endpoint→collector links | Small |
| 4. Go Redis Abstraction | +10-30 Go Redis access edges | Small |
| 5. Validate + CallResolver | Accurate validate output | Small |
