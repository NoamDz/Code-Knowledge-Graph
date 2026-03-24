# Orphan Elimination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 230+ orphan files (26% of codebase) by fixing the root cause for each language: Go same-package linking, Python same-directory bare imports, Ruby require_relative fixes, and Lua mission dispatch string→file mapping.

**Architecture:** Four independent resolver fixes, each targeting a specific language's dependency model. Go files share a single package (no internal imports — connect via same-package edges). Python services use bare-name imports resolved relative to the same directory. Ruby needs better require_relative path handling. Lua mission dispatch connects files via string-based task routing.

**Tech Stack:** Python 3.11+, Tree-sitter, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/resolvers/go_resolver.py` | Rewrite | Same-package linking + stdlib classification |
| `graph_builder/resolvers/python_resolver.py` | Modify | Same-directory bare-name import resolution |
| `graph_builder/resolvers/ruby_resolver.py` | Modify | Better require_relative + stdlib classification |
| `graph_builder/resolvers/mission_resolver.py` | Create | Map missioner.add_mission("name") → task file |
| `graph_builder/resolvers/builtin_classifier.py` | Modify | Add Go stdlib + Ruby stdlib to builtin lists |
| `graph_builder/main.py` | Modify | Integrate mission resolver |
| `graph_builder/ingestion/writer.py` | Modify | Add same-package edges, mission dispatch edges |
| `graph_builder/tests/test_orphan_fixes.py` | Create | Tests for all 4 fixes |
| `graph_builder/tests/fixtures/go/same_package/` | Create | Go same-package test fixtures |
| `graph_builder/tests/fixtures/python/flat_service/` | Create | Python flat-directory test fixtures |
| `graph_builder/tests/fixtures/lua/mission_caller.lua` | Create | Mission dispatch test fixture |

---

## Task 1: Go Same-Package Linking + Stdlib Classification

All 73 Go files are in a single flat package — they have zero internal imports (all imports are stdlib or external). The resolver should connect files in the same Go package directory, and classify stdlib imports.

**Files:**
- Rewrite: `graph_builder/resolvers/go_resolver.py`
- Create: `graph_builder/tests/fixtures/go/same_package/main.go`
- Create: `graph_builder/tests/fixtures/go/same_package/handler.go`
- Add to: `graph_builder/tests/test_orphan_fixes.py`
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Create test fixtures

- [ ] **1.1: Create same-package Go fixtures**

Create directory `graph_builder/tests/fixtures/go/same_package/` with two files:

`graph_builder/tests/fixtures/go/same_package/main.go`:
```go
package server

import (
	"context"
	"fmt"
	"net/http"
)

func main() {
	handler := NewHandler()
	fmt.Println("Starting server")
	http.ListenAndServe(":8080", handler)
}
```

`graph_builder/tests/fixtures/go/same_package/handler.go`:
```go
package server

import (
	"encoding/json"
	"net/http"
)

type Handler struct{}

func NewHandler() *Handler {
	return &Handler{}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}
```

### Step 2: Write tests

- [ ] **2.1: Create test file**

Create `graph_builder/tests/test_orphan_fixes.py`:

```python
"""Tests for orphan elimination fixes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.resolvers.go_resolver import GoResolver

GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"


def test_go_same_package_files():
    """Files in the same Go package directory should be linked."""
    resolver = GoResolver(str(GO_FIXTURES))
    siblings = resolver.get_package_siblings(
        str(GO_FIXTURES / "same_package" / "main.go")
    )
    sibling_names = [Path(s).name for s in siblings]
    assert "handler.go" in sibling_names
    assert "main.go" not in sibling_names  # Should not include self


def test_go_stdlib_classification():
    """Go stdlib imports like 'fmt', 'context' should be classified."""
    resolver = GoResolver(str(GO_FIXTURES))
    assert resolver.is_stdlib("fmt")
    assert resolver.is_stdlib("context")
    assert resolver.is_stdlib("net/http")
    assert resolver.is_stdlib("encoding/json")
    assert not resolver.is_stdlib("github.com/go-redis/redis/v8")
    assert not resolver.is_stdlib("pinpoint/server/models")


def test_go_resolve_still_works():
    """Existing suffix-match resolve should still work."""
    resolver = GoResolver(str(GO_FIXTURES))
    # Existing fixture from the redis_client test
    result = resolver.resolve("same_package")
    assert result is not None
```

- [ ] **2.2: Run test to verify it fails**

Run: `python -m pytest graph_builder/tests/test_orphan_fixes.py::test_go_same_package_files -v`
Expected: AttributeError — `get_package_siblings` method doesn't exist yet

### Step 3: Implement Go resolver changes

- [ ] **3.1: Rewrite go_resolver.py**

```python
"""Go import resolver.

Go imports are package paths. This resolver:
1. Resolves import paths to file paths via suffix matching
2. Identifies same-package siblings (files in same directory = same Go package)
3. Classifies stdlib imports
"""

from __future__ import annotations

from pathlib import Path


# Go stdlib top-level packages (Go 1.21+)
_GO_STDLIB = {
    "archive", "bufio", "bytes", "cmp", "compress", "container", "context",
    "crypto", "database", "debug", "embed", "encoding", "errors", "expvar",
    "flag", "fmt", "go", "hash", "html", "image", "index", "io", "iter",
    "log", "maps", "math", "mime", "net", "os", "path", "plugin",
    "reflect", "regexp", "runtime", "slices", "sort", "strconv", "strings",
    "struct", "sync", "syscall", "testing", "text", "time", "unicode",
    "unsafe", "internal",
}


class GoResolver:
    """Resolves Go import paths and tracks same-package relationships."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}  # suffix → directory
        self._package_dirs: dict[str, list[str]] = {}  # dir → [file_paths]
        self._build_index()

    def _build_index(self):
        """Build index of Go package directories and their files."""
        for go_file in self.repo_root.rglob("*.go"):
            parts = go_file.relative_to(self.repo_root).parts
            if any(p in ("vendor", "node_modules", ".git") for p in parts):
                continue

            dir_path = str(go_file.parent)
            rel_dir = str(go_file.parent.relative_to(self.repo_root)).replace("\\", "/")

            if rel_dir not in self._index:
                self._index[rel_dir] = dir_path

            # Track all files per directory (for same-package linking)
            if dir_path not in self._package_dirs:
                self._package_dirs[dir_path] = []
            self._package_dirs[dir_path].append(str(go_file))

    def resolve(self, import_path: str, from_file: str | None = None) -> str | None:
        """Resolve a Go import path to a .go file path."""
        parts = import_path.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if suffix in self._index:
                dir_path = Path(self._index[suffix])
                go_files = sorted(dir_path.glob("*.go"))
                for gf in go_files:
                    if not gf.name.endswith("_test.go"):
                        return str(gf)
                if go_files:
                    return str(go_files[0])
                return self._index[suffix]
        return None

    def is_stdlib(self, import_path: str) -> bool:
        """Check if an import path is a Go standard library package."""
        top = import_path.split("/")[0]
        return top in _GO_STDLIB

    def get_package_siblings(self, file_path: str) -> list[str]:
        """Get all Go files in the same package directory (excluding self).

        Files in the same Go directory share the same package and can
        reference each other's symbols without imports.
        """
        file_path_resolved = str(Path(file_path).resolve())
        dir_path = str(Path(file_path_resolved).parent)

        siblings = []
        for d, files in self._package_dirs.items():
            if Path(d).resolve() == Path(dir_path).resolve():
                for f in files:
                    f_resolved = str(Path(f).resolve())
                    if f_resolved != file_path_resolved:
                        siblings.append(f)
                break
        return siblings

    def stats(self) -> dict:
        return {
            "indexed_packages": len(self._index),
            "package_dirs": len(self._package_dirs),
            "total_files": sum(len(f) for f in self._package_dirs.values()),
        }
```

### Step 4: Add same-package edge ingestion

- [ ] **4.1: Add SAME_PACKAGE edge to writer.py**

In `graph_builder/ingestion/writer.py`, add a new method:

```python
def upsert_same_package(self, file_a: str, file_b: str, package_name: str):
    """Create a SAME_PACKAGE edge between two files in the same Go package."""
    self._run("""
        MERGE (a:File {path: $file_a})
        MERGE (b:File {path: $file_b})
        MERGE (a)-[:SAME_PACKAGE {package: $pkg}]->(b)
    """, file_a=file_a, file_b=file_b, pkg=package_name)
```

- [ ] **4.2: Wire into main.py build command**

In `graph_builder/main.py`, after the file ingestion loop, add Go same-package linking:

```python
    # Go same-package linking
    go_resolver = resolvers.get("go")
    if go_resolver and hasattr(go_resolver, "get_package_siblings"):
        pkg_edges = 0
        for file_path, ast in all_asts.items():
            if ast.language == "go":
                siblings = go_resolver.get_package_siblings(file_path)
                for sibling in siblings:
                    writer.upsert_same_package(file_path, sibling, "server")
                    pkg_edges += 1
        if pkg_edges:
            click.echo(f"  Go same-package edges: {pkg_edges}")
```

### Step 5: Add Go stdlib to builtin classifier

- [ ] **5.1: Verify Go stdlib classification works**

The existing `BuiltinClassifier` already has `GO_STDLIB_PREFIXES` which includes `fmt`, `io`, `os`, etc. However, for IMPORT classification (not call classification), we need the Go resolver's `is_stdlib()` method.

In `graph_builder/main.py`, in the import resolution loop, add special handling for Go stdlib:

```python
    # In the import resolution loop, after resolver.resolve():
    if ast.language == "go" and resolver_key == "go":
        go_res = resolvers.get("go")
        if go_res and go_res.is_stdlib(imp.module_string):
            file_resolved[imp.module_string] = "__stdlib__"
```

This marks stdlib imports as resolved (to a sentinel value) instead of unresolved.

- [ ] **5.2: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_orphan_fixes.py -v && python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: Go same-package linking + stdlib classification

Go files in the same directory share a package and can reference each
other's symbols. Creates SAME_PACKAGE edges between sibling .go files.
Also classifies stdlib imports as resolved. Fixes 73 orphan Go files."
```

---

## Task 2: Python Same-Directory Bare Import Resolution

Python services like `event_extractor` use flat directories with bare imports: `from config import Config` (no package prefix, no relative dot). The resolver expects package-style paths but these are actually same-directory imports.

**Files:**
- Modify: `graph_builder/resolvers/python_resolver.py`
- Create: `graph_builder/tests/fixtures/python/flat_service/`
- Add to: `graph_builder/tests/test_orphan_fixes.py`

### Step 1: Create fixtures

- [ ] **1.1: Create flat Python service fixtures**

Create directory `graph_builder/tests/fixtures/python/flat_service/`:

`graph_builder/tests/fixtures/python/flat_service/runner.py`:
```python
import logging
from config import Config
from record_handler import RecordHandler
from error_handler import ErrorHandler

def main():
    config = Config()
    handler = RecordHandler(config)
    handler.run()

if __name__ == "__main__":
    main()
```

`graph_builder/tests/fixtures/python/flat_service/config.py`:
```python
class Config:
    def __init__(self):
        self.host = "localhost"
        self.port = 8080
```

`graph_builder/tests/fixtures/python/flat_service/record_handler.py`:
```python
from config import Config

class RecordHandler:
    def __init__(self, config):
        self.config = config

    def run(self):
        pass
```

`graph_builder/tests/fixtures/python/flat_service/error_handler.py`:
```python
class ErrorHandler:
    def handle(self, error):
        pass
```

### Step 2: Write tests

- [ ] **2.1: Add Python tests**

Add to `graph_builder/tests/test_orphan_fixes.py`:

```python
from graph_builder.resolvers.python_resolver import PythonResolver

PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"


def test_python_bare_import_same_directory():
    """Bare imports like 'from config import Config' should resolve to same directory."""
    resolver = PythonResolver(str(PY_FIXTURES / "flat_service"))

    runner_path = str(PY_FIXTURES / "flat_service" / "runner.py")

    # 'config' should resolve to config.py in same directory
    result = resolver.resolve("config", runner_path)
    assert result is not None
    assert "config.py" in result

    # 'record_handler' should resolve to record_handler.py in same directory
    result = resolver.resolve("record_handler", runner_path)
    assert result is not None
    assert "record_handler.py" in result


def test_python_bare_import_not_stdlib():
    """Bare imports that match stdlib names should still prefer local files."""
    resolver = PythonResolver(str(PY_FIXTURES / "flat_service"))
    runner_path = str(PY_FIXTURES / "flat_service" / "runner.py")

    # 'config' exists as a local file AND as a potential stdlib import
    # Local file should win
    result = resolver.resolve("config", runner_path)
    assert result is not None
    assert str(PY_FIXTURES) in result
```

### Step 3: Implement

- [ ] **3.1: Add same-directory resolution to PythonResolver**

In `graph_builder/resolvers/python_resolver.py`, modify the `resolve` method to try same-directory resolution for bare-name imports (no dots, no relative prefix):

```python
def resolve(self, module_string: str, from_file: str | None = None) -> str | None:
    # Handle relative imports
    if module_string.startswith(".") and from_file:
        return self._resolve_relative(module_string, from_file)

    # Try absolute resolution first
    result = self._resolve_absolute(module_string)
    if result:
        return result

    # For bare-name imports (no dots), try same-directory resolution
    # This handles flat Python services that use 'from config import Config'
    if "." not in module_string and from_file:
        return self._resolve_same_directory(module_string, from_file)

    return None
```

Add a new method:

```python
def _resolve_same_directory(self, module_string: str, from_file: str) -> str | None:
    """Resolve a bare import by looking in the same directory as the importing file.

    Handles flat Python services (no __init__.py) that use:
        from config import Config  (config.py in same dir)
        from record_handler import RecordHandler  (record_handler.py in same dir)
    """
    from_dir = Path(from_file).parent
    candidate = from_dir / f"{module_string}.py"
    if candidate.exists():
        return str(candidate)

    # Try as a package directory
    candidate_pkg = from_dir / module_string / "__init__.py"
    if candidate_pkg.exists():
        return str(candidate_pkg)

    return None
```

- [ ] **3.2: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_orphan_fixes.py -v && python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: Python same-directory bare import resolution

Python services using flat directories (no __init__.py) import siblings
with bare names: 'from config import Config'. Resolver now tries
same-directory lookup as fallback for non-dotted imports."
```

---

## Task 3: Ruby require_relative Fix + Stdlib Classification

Ruby resolution is at 2.3% with 139 orphans. The resolver has `require_relative` handling but it may be failing on path resolution. Also, Ruby stdlib imports (`require 'erb'`, `require 'fileutils'`) should be classified as builtin, not unresolved.

**Files:**
- Modify: `graph_builder/resolvers/ruby_resolver.py`
- Modify: `graph_builder/resolvers/builtin_classifier.py`
- Add to: `graph_builder/tests/test_orphan_fixes.py`

### Step 1: Write tests

- [ ] **1.1: Add Ruby tests**

Add to `graph_builder/tests/test_orphan_fixes.py`:

```python
from graph_builder.resolvers.ruby_resolver import RubyResolver

RB_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"


def test_ruby_require_relative_resolution():
    """require_relative should resolve to files relative to the importing file."""
    resolver = RubyResolver(str(RB_FIXTURES))
    # The existing fixture has ruby files — use one as the from_file
    rb_files = list(RB_FIXTURES.glob("*.rb"))
    if rb_files:
        from_file = str(rb_files[0])
        # require_relative of another file in same dir (without .rb)
        other = [f for f in rb_files if f != rb_files[0]]
        if other:
            rel_name = other[0].stem
            result = resolver.resolve(rel_name, from_file, import_type="require_relative")
            assert result is not None, f"require_relative '{rel_name}' from {from_file} should resolve"


def test_ruby_stdlib_classification():
    """Ruby stdlib imports should be classified as builtin."""
    from graph_builder.resolvers.builtin_classifier import BuiltinClassifier
    from graph_builder.parsers.base import CallRef, FileAST

    # Test that Ruby stdlib requires are classified correctly
    # The classifier handles call classification, not import classification
    # But we can verify the builtin lists include Ruby stdlib
    classifier = BuiltinClassifier()
    result = classifier.classify_call("ERB", "ruby")
    assert result == "builtin", "ERB should be classified as builtin"

    result = classifier.classify_call("FileUtils", "ruby")
    assert result == "builtin", "FileUtils should be classified as builtin"
```

### Step 2: Fix Ruby resolver

- [ ] **2.1: Debug and fix require_relative**

Read `graph_builder/resolvers/ruby_resolver.py` lines 52-61. The `require_relative` handler resolves the path and checks `.exists()`. The issue may be:
1. `from_file` paths use forward slashes but `Path` on Windows uses backslashes
2. The `.resolve()` call may fail on relative paths

Fix: Ensure the `from_file` path is resolved before computing relative targets. Also handle the case where the target doesn't have `.rb` suffix:

```python
if import_type == "require_relative" and from_file:
    from_dir = Path(from_file).resolve().parent
    target = (from_dir / module_string).resolve()
    # Try with .rb suffix first
    candidate_rb = target.with_suffix(".rb")
    if candidate_rb.exists():
        return str(candidate_rb)
    # Try exact path (if already has extension)
    if target.exists() and target.is_file():
        return str(target)
    # Try as directory with init file (Ruby doesn't have this, but be safe)
    return None
```

- [ ] **2.2: Add Ruby stdlib to builtin classifier**

In `graph_builder/resolvers/builtin_classifier.py`, verify that the `RUBY_STDLIB_PREFIXES` set includes common stdlib modules. Check that `ERB`, `FileUtils`, `JSON`, `YAML`, `Pathname`, `URI`, `Net`, `Socket`, `Digest`, `Base64`, `Logger` are all present.

These are already in the classifier's `RUBY_STDLIB_PREFIXES` set, so call classification should already work. However, for IMPORT classification, add a `is_ruby_stdlib` function or constant to the Ruby resolver.

- [ ] **2.3: Add Ruby stdlib imports constant**

In `graph_builder/resolvers/ruby_resolver.py`, add:

```python
# Ruby stdlib modules (returned by require, not gems)
_RUBY_STDLIB = {
    "erb", "fileutils", "json", "yaml", "csv", "set", "ostruct",
    "pathname", "uri", "net/http", "net/https", "net/smtp",
    "socket", "openssl", "digest", "base64", "securerandom",
    "logger", "tempfile", "stringio", "pp", "optparse", "getoptlong",
    "find", "benchmark", "date", "time", "bigdecimal", "cgi",
    "drb", "fiddle", "monitor", "mutex_m", "observer", "open3",
    "open-uri", "rake", "rdoc", "readline", "rinda", "shellwords",
    "singleton", "strscan", "timeout", "tmpdir", "webrick",
    "zlib", "forwardable", "abbrev", "English",
}
```

Then in the `resolve` method, before returning None for unmatched requires:

```python
# Check if it's a stdlib module
if module_string in _RUBY_STDLIB or module_string.split("/")[0] in _RUBY_STDLIB:
    return "__ruby_stdlib__"  # Sentinel: resolved as stdlib
```

- [ ] **2.4: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_orphan_fixes.py -v && python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: Ruby require_relative fix + stdlib classification

Fix path resolution for require_relative. Add Ruby stdlib recognition
so 'require erb' and 'require fileutils' are classified as resolved
instead of unresolved. Should fix many of the 139 Ruby orphan files."
```

---

## Task 4: Lua Mission Dispatch String→File Mapping

74 mission creation sites use `missioner.add_mission("task_name", ...)`. The task name maps to a Lua file: `"pts_run"` → `tasks/pts_run.lua`. This creates cross-file edges that are completely invisible to import resolution.

**Files:**
- Create: `graph_builder/resolvers/mission_resolver.py`
- Create: `graph_builder/tests/fixtures/lua/mission_caller.lua`
- Add to: `graph_builder/tests/test_orphan_fixes.py`
- Modify: `graph_builder/main.py`
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Create fixture

- [ ] **1.1: Create mission caller fixture**

Create `graph_builder/tests/fixtures/lua/mission_caller.lua`:

```lua
local require_version = require("loader.lua").require_version
local missioner = require_version("core.deferrer.missioner.client")

local M = {}

function M:apply(input, bundle, web)
    missioner.add_mission("pts_run", {
        component = "ato",
        session_id = input.session_id,
    }, 0, "policy")

    missioner.add_mission("model_prediction", {
        component = "ato",
        model_data = input.data,
    }, 0, "model_prediction")
end

return M
```

### Step 2: Write tests

- [ ] **2.1: Add mission resolver tests**

Add to `graph_builder/tests/test_orphan_fixes.py`:

```python
from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.mission_resolver import resolve_missions

LUA_FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_mission_dispatch_detection():
    """missioner.add_mission('task_name', ...) should detect task names."""
    ast = parse_lua_file(str(LUA_FIXTURES / "mission_caller.lua"))

    # The parser extracts calls. Mission resolver should find add_mission calls.
    missions = resolve_missions({"test.lua": ast})

    task_names = [m["task_name"] for m in missions]
    assert "pts_run" in task_names
    assert "model_prediction" in task_names


def test_mission_to_file_mapping():
    """Task names should map to task file paths via convention."""
    from graph_builder.resolvers.mission_resolver import task_name_to_file_pattern

    assert task_name_to_file_pattern("pts_run") == "tasks/pts_run"
    assert task_name_to_file_pattern("model_prediction") == "tasks/model_prediction"
```

### Step 3: Implement

- [ ] **3.1: Create mission_resolver.py**

```python
"""Mission dispatch resolver: maps missioner.add_mission("name") to task files.

The Lua codebase uses a mission/task system for async work:
  missioner.add_mission("pts_run", params, delay, queue)

This creates a hidden cross-file dependency:
  calling_file → "pts_run" string → tasks/pts_run.lua

This resolver:
1. Scans all ASTs for missioner.add_mission() calls
2. Extracts the task name (first string argument)
3. Maps task names to file paths using convention: tasks/{name}.lua
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def task_name_to_file_pattern(task_name: str) -> str:
    """Convert a task name to its expected file path pattern.

    Convention: task "pts_run" → file at "tasks/pts_run" (with .lua extension).
    """
    return f"tasks/{task_name}"


def resolve_missions(all_asts: dict[str, FileAST]) -> list[dict]:
    """Find all mission dispatch calls and map them to task files.

    Scans all Lua files for calls matching:
        missioner.add_mission("task_name", ...)
        missioner_client.add_mission("task_name", ...)

    Returns list of dicts:
        [{"source_file": "...", "source_function": "...", "task_name": "...",
          "line": N, "target_pattern": "tasks/task_name"}]
    """
    missions = []

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        for call in ast.calls:
            # Match: missioner.add_mission, missioner_client.add_mission, etc.
            callee = call.callee_string
            if not callee.endswith(".add_mission") and not callee.endswith(":add_mission"):
                continue

            # The task name is typically the first argument
            # We can't easily extract it from the AST via CallRef alone.
            # Instead, we'll need to check if the callee was resolved through
            # the binding map to a missioner module.
            receiver = callee.rsplit(".", 1)[0] if "." in callee else callee.rsplit(":", 1)[0]

            # Check if receiver is bound to a missioner module
            is_missioner = False
            for imp in ast.imports:
                if imp.local_binding == receiver and "missioner" in imp.module_string:
                    is_missioner = True
                    break

            if not is_missioner:
                # Also check if callee string contains 'missioner'
                if "missioner" not in callee.lower():
                    continue

            missions.append({
                "source_file": file_path,
                "source_function": call.caller_function,
                "task_name": None,  # Can't extract from CallRef alone
                "line": call.line,
                "callee": callee,
            })

    return missions
```

**Note:** Extracting the actual task name string from CallRef is limited — the parser stores `callee_string` but not the arguments. For full mission detection, we'd need to enhance the Lua parser to extract the first string argument of `add_mission` calls. However, even detecting "this function calls missioner.add_mission" is valuable — it marks the function as a mission creator.

For extracting the actual task name, add mission detection to the Lua parser's `_extract_http_calls_lua`-style detection:

- [ ] **3.2: Add mission detection to Lua parser**

In `graph_builder/parsers/lua_parser.py`, add a mission detection function similar to the http_handler detection. Add a new field to base.py or reuse warnings:

In the `_extract_http_calls_lua` function (or a new parallel function), after the http_handler detection block, add mission detection:

```python
# --- Mission dispatch detection ---
# Pattern: missioner.add_mission("task_name", params, delay, queue)
_MISSIONER_MODULES = {"core.deferrer.missioner.client"}
missioner_vars = set()
for var, mod in binding_map.items():
    if mod in _MISSIONER_MODULES or "missioner" in mod:
        missioner_vars.add(var)

for call_node in _walk_all(root, "function_call"):
    name_node = call_node.child_by_field_name("name")
    if not name_node:
        continue
    callee = _text(name_node, source)

    if "." in callee:
        parts = callee.split(".", 1)
        if parts[0] in missioner_vars and parts[1] == "add_mission":
            args = _first_child_of_type(call_node, "arguments")
            if args and args.named_child_count >= 1:
                first_arg = args.named_children[0]
                if first_arg.type == "string":
                    task_name = _get_string_value(first_arg, source)
                    ast.warnings.append(f"mission:{task_name}:{call_node.start_point[0] + 1}")
```

This stores mission dispatches in `ast.warnings` as `"mission:task_name:line"` — the same pattern used for Go unix socket detection.

Then the `resolve_missions` function reads these warnings:

```python
def resolve_missions(all_asts, repo_root=None):
    missions = []
    for file_path, ast in all_asts.items():
        for w in ast.warnings:
            if w.startswith("mission:"):
                parts = w.split(":", 2)
                if len(parts) >= 3:
                    task_name = parts[1]
                    line = int(parts[2])
                    missions.append({
                        "source_file": file_path,
                        "task_name": task_name,
                        "line": line,
                        "target_pattern": task_name_to_file_pattern(task_name),
                    })
    return missions
```

- [ ] **3.3: Add DISPATCHES edge to writer.py**

```python
def upsert_mission_dispatch(self, source_file: str, task_name: str,
                             target_file: str | None, line: int):
    """Create a DISPATCHES edge from a file to a task handler file."""
    if target_file:
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:DISPATCHES {task: $task, line: $line}]->(tgt)
        """, source=source_file, target=target_file, task=task_name, line=line)
    else:
        # Task file not found — create unresolved edge
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:Function {name: $task})
            MERGE (src)-[:DISPATCHES {task: $task, line: $line, unresolved: true}]->(tgt)
        """, source=source_file, task=task_name, line=line)
```

- [ ] **3.4: Wire into main.py**

After the endpoint linking step in `main.py`:

```python
    # Step 4f: Mission dispatch resolution
    from .resolvers.mission_resolver import resolve_missions, task_name_to_file_pattern
    missions = resolve_missions(all_asts)
    if missions:
        # Try to resolve task names to actual files
        for m in missions:
            pattern = m["target_pattern"]
            # Search all_asts for files matching the task pattern
            for fp in all_asts:
                if pattern in fp.replace("\\", "/"):
                    m["target_file"] = fp
                    break
        resolved_missions = [m for m in missions if m.get("target_file")]
        click.echo(f"  Missions: {len(missions)} dispatches, {len(resolved_missions)} resolved to files")
```

- [ ] **3.5: Run tests and commit**

Run: `python -m pytest graph_builder/tests/test_orphan_fixes.py -v && python -m pytest graph_builder/tests/ -v`

```bash
git commit -m "feat: Lua mission dispatch string-to-file mapping

Detects missioner.add_mission('task_name', ...) calls and maps them to
task handler files via naming convention: 'pts_run' → tasks/pts_run.lua.
Creates DISPATCHES edges, connecting 74 mission creation sites to their
task handlers across the Lua/Python boundary."
```

---

## Integration Verification

After all 4 tasks:

- [ ] **Run full test suite**

```bash
python -m pytest graph_builder/tests/ -v
```

- [ ] **Run on product codebase** (on Mac)

```bash
code-graph health -c config.yml
```

Expected improvements:
- Go orphans: 73 → 0 (same-package linking)
- Go import resolution: 0% → some % (stdlib classified)
- Python orphans: 22 → ~5 (same-directory resolution)
- Ruby orphans: 139 → ~50-80 (require_relative fix + stdlib)
- Lua: +74 mission dispatch edges
- Overall: 324 orphans → ~60-90 orphans

---

## Summary

| Task | Orphans Fixed | New Edges | Effort |
|------|--------------|-----------|--------|
| 1. Go same-package + stdlib | 73 → 0 | ~200 same-package edges | Medium |
| 2. Python same-directory | 22 → ~5 | ~50 import edges | Small |
| 3. Ruby require_relative + stdlib | 139 → ~50-80 | ~100 import edges | Small |
| 4. Lua mission dispatch | 0 (but connectivity) | +74 dispatch edges | Medium |
