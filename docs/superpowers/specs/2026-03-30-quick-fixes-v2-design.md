# Quick Fixes V2 — Design Spec

**Date:** 2026-03-30
**Goal:** Fix resolver/schema issues: graph schema gaps (6 missing edge properties), dynamic prefix false positives, base inheritance auto-detection, Python package root detection, Go go.mod parsing for ~90% import resolution, and Ruby Gemfile parsing for gem classification.

---

## 1. Write Missing Edge Properties to Graph

### Problem

6 fields are extracted by parsers but never written to Memgraph:

| Field | Extracted | Written | Impact |
|-------|-----------|---------|--------|
| `CallRef.resolution_confidence` | Yes | No | Can't query high vs low confidence resolutions |
| `ImportRef.local_binding` | Yes | No | Can't trace variable aliases in graph |
| `FunctionDef.decorators` | Yes | No | Python decorators lost |
| `ClassDef.is_interface` | Yes | No | Can't distinguish Go interfaces from structs |
| `FileAST.metatable_parents` | Yes | No edge type | Lua inheritance not in graph |
| `ContextAccess.scope` | Yes | No | Scoped context access loses scope info |

Additionally, `CallRef.classification` is written to unresolved CALLS edges but NOT to resolved CALLS edges.

### Solution

**1a. Add `resolution_confidence` and `classification` to resolved CALLS edges:**
In `writer.py` `upsert_call()`, add these properties to the resolved call MERGE query (currently only on unresolved).

**1b. Add `local_binding` to IMPORTS edges:**
In `writer.py` `upsert_import()`, add `local_binding` property to the IMPORTS edge MERGE.

**1c. Add `decorators` to Function nodes:**
In `writer.py` `upsert_function()`, add `decorators` as a list property on the Function node.

**1d. Add `is_interface` to Class nodes:**
In `writer.py` `upsert_class()`, add `is_interface` boolean property on the Class node.

**1e. Create INHERITS_VIA_METATABLE edge type:**
New edge from child module File to parent module File, with the table var name as property. Populated from `FileAST.metatable_parents`. Add `upsert_metatable_inheritance(child_file, parent_module, table_var)` to writer.

**1f. Add `scope` to CTX_READS/CTX_WRITES edges:**
In `writer.py` `upsert_ctx_access()`, add `scope` property to the edge.

**Expected impact:** Graph becomes queryable for resolution confidence, import bindings, decorators, interfaces, Lua inheritance, and scoped context. No new detection — just writing data already extracted.

---

## 2. Fix Dynamic Prefix Resolver Boundary Matching

### Problem

Line 46 of `dynamic_prefix_resolver.py` uses `if prefix in module_name` — a naive substring check. This means prefix `"handler."` matches `"my_handler_utils"` (false positive).

### Solution

Replace substring matching with boundary-aware matching:

```python
def _is_prefix_match(prefix: str, module_name: str) -> bool:
    """Check if prefix matches at a namespace boundary."""
    # "tasks." should match "ato.tasks.pts_run" but NOT "multitask_runner"
    prefix_clean = prefix.rstrip(".")
    prefix_parts = prefix_clean.split(".")
    module_parts = module_name.split(".")

    # Check if prefix_parts appears as a contiguous subsequence in module_parts
    for i in range(len(module_parts) - len(prefix_parts) + 1):
        if module_parts[i:i + len(prefix_parts)] == prefix_parts:
            return True
    return False
```

Also add edge count reporting — return stats alongside edges.

**Implementation file:** `graph_builder/resolvers/dynamic_prefix_resolver.py`

**Expected impact:** Eliminates false positive POTENTIAL_IMPORT edges. No new edges — just more accurate existing ones.

---

## 3. Auto-Detect Base Module Methods

### Problem

`BASE_MODULE_METHODS` in `base_inheritance_resolver.py` is hardcoded with 31 methods across 4 base modules. This requires manual maintenance and breaks if base modules change.

### Solution

Replace hardcoded dict with auto-detection from ASTs:

```python
def _auto_detect_base_modules(all_asts: dict[str, FileAST]) -> dict[str, set[str]]:
    """Scan ASTs for files whose module_name matches 'common.base.lua.*'
    and extract their public method names."""
    base_modules = {}
    for file_path, ast in all_asts.items():
        if not ast.module_name or ast.language != "lua":
            continue
        if not ast.module_name.startswith("common.base.lua."):
            continue

        public_methods = set()
        for func in ast.functions:
            if func.visibility == "public" or func.is_method:
                base_name = func.name.split(".")[-1].split(":")[-1]
                public_methods.add(base_name)

        if public_methods:
            base_modules[ast.module_name] = public_methods
    return base_modules
```

Keep the hardcoded dict as a fallback for when the base files aren't in `all_asts` (e.g., during testing or partial builds). Log a warning if auto-detected methods differ from hardcoded.

**Implementation file:** `graph_builder/resolvers/base_inheritance_resolver.py`

**Expected impact:** Maintenance-free base module detection. May resolve a few more calls if auto-detection finds methods the hardcoded list missed.

---

## 4. Python Package Root Detection

### Problem

Python resolver builds a flat module index without understanding package hierarchy. It can't reliably resolve absolute imports within nested packages because it doesn't know where each package starts.

Current: 36.7% resolution (150/409). Most unresolved are third-party (correct), but some internal imports fail.

### Solution

Add package root detection by traversing upward from each `.py` file to find the topmost directory containing `__init__.py`:

```python
def _find_package_roots(self) -> dict[str, Path]:
    """Find topmost __init__.py for each package tree."""
    roots = {}
    for py_file in self.repo_root.rglob("*.py"):
        current = py_file.parent
        topmost = None
        while current != self.repo_root and current != current.parent:
            if (current / "__init__.py").exists():
                topmost = current
            else:
                break
            current = current.parent
        if topmost:
            roots[str(py_file)] = topmost
    return roots
```

Use package roots to improve resolution:
1. When resolving `from services.models import X`, check if `services/` is a known package root
2. If so, resolve relative to the package root's parent directory
3. This handles the common pattern where Python services add their parent to `sys.path`

Also add Python stdlib classification (similar to Go's `is_stdlib`):
```python
PYTHON_STDLIB_TOP = {"os", "sys", "json", "re", "time", "datetime", "collections",
                     "pathlib", "typing", "abc", "io", "math", "logging", "unittest",
                     "subprocess", "threading", "multiprocessing", "socket", "http",
                     "urllib", "email", "html", "xml", "sqlite3", "csv", ...}
```

This won't increase resolution rate but will reclassify unresolved stdlib imports from "unresolved" to "stdlib" (similar to what Go resolver does).

**Implementation file:** `graph_builder/resolvers/python_resolver.py`

**Expected impact:** Small improvement in internal import resolution. Major improvement in import classification (stdlib vs third-party vs truly unresolved).

---

## 6. Go go.mod Parsing for Internal Package Resolution

### Problem

Go import resolution is 60.2% (308/512). The resolver uses suffix matching on directory paths without understanding Go's module system. BOB confirmed:
- Module name: `pp-consumer` (from `src/core/model_prediction/server/go.mod`)
- No vendor/ directory
- All internal imports use `pp-consumer/` prefix (e.g., `pp-consumer/common/db`, `pp-consumer/config`)

The resolver can't match `"pp-consumer/common/utils"` because it tries to find a directory `pp-consumer/common/utils/` which doesn't exist — the actual directory is `common/utils/` relative to the Go project root.

### Solution

Parse `go.mod` to extract the module name, then strip it from import paths before suffix matching:

1. **Find and parse go.mod:**
```python
def _parse_go_mod(self) -> str | None:
    """Find go.mod and extract module name."""
    for go_mod in self.repo_root.rglob("go.mod"):
        with open(go_mod) as f:
            for line in f:
                if line.startswith("module "):
                    return line.split()[1].strip()
    return None
```

2. **Strip module prefix during resolution:**
```python
def resolve(self, import_path, from_file=None):
    if self.is_stdlib(import_path):
        return "__go_stdlib__"

    # Strip module prefix for internal packages
    if self._module_name and import_path.startswith(self._module_name + "/"):
        local_path = import_path[len(self._module_name) + 1:]
    else:
        local_path = import_path

    # Existing suffix matching on local_path
    parts = local_path.split("/")
    for i in range(len(parts)):
        suffix = "/".join(parts[i:])
        if suffix in self._index:
            # return first non-test .go file
            ...
```

3. **Build index relative to go.mod location** — the Go project root is the directory containing go.mod, not necessarily the repo root. Index directories relative to that root.

4. **Extract external dependencies from `require` blocks** — classify imports matching require entries as external (expected unresolved).

**Go external dependencies from BOB:**
```
github.com/aws/aws-sdk-go
github.com/go-redis/redismock/v9
github.com/go-sql-driver/mysql
github.com/lithammer/shortuuid/v3
github.com/redis/go-redis/v9
github.com/stretchr/objx
github.com/stretchr/testify
github.com/timandy/routine
golang.org/x/sys
gopkg.in/alexcesaro/statsd.v2
```

**Implementation file:** `graph_builder/resolvers/go_resolver.py`

**Expected impact:** Go import resolution from 60.2% to ~85-90%. Internal packages like `pp-consumer/common/utils` correctly resolved. External dependencies correctly classified.

---

## 7. Ruby Gemfile Parsing for Import Classification

### Problem

Ruby import resolution is 42.3% (145/343). Most unresolved are external gems — correct behavior, but we can't distinguish gems from truly unresolved imports.

BOB confirmed all 3 Ruby components share the same Gemfile with 10 gems:
- activesupport, aws-sdk-s3, cassandra-driver, concurrent-ruby, dalli, mysql2, oj, redis, rest-client, statsd-instrument

### Solution

Parse Gemfile to build a known gems set and classify unresolved imports:

```python
KNOWN_GEMS = {
    "active_support", "activesupport",
    "aws-sdk-s3", "aws/sdk", "Aws",
    "cassandra-driver", "cassandra",
    "concurrent-ruby", "concurrent",
    "dalli",
    "mysql2",
    "oj",
    "redis",
    "rest-client", "rest_client", "RestClient",
    "statsd-instrument", "statsd", "StatsD",
    # Dev/test gems:
    "pry", "rspec", "rubocop",
}

def is_gem(self, module_string: str) -> bool:
    """Check if import is a known gem."""
    base = module_string.split("/")[0].split("::")[0]
    return base.lower().replace("-", "_") in {g.lower().replace("-", "_") for g in KNOWN_GEMS}
```

In `resolve()`, when an import is unresolved, check `is_gem()` before returning None:
- If gem → return `"__ruby_gem__"` sentinel (like `"__ruby_stdlib__"`)
- If not gem and not stdlib → truly unresolved

Also scan for `Gemfile` files in the repo and parse them dynamically:
```python
def _parse_gemfiles(self) -> set[str]:
    """Find all Gemfiles and extract gem names."""
    gems = set()
    for gemfile in self.repo_root.rglob("Gemfile"):
        with open(gemfile) as f:
            for line in f:
                match = re.match(r"^\s*gem\s+['\"]([^'\"]+)['\"]", line)
                if match:
                    gems.add(match.group(1))
    return gems
```

**Implementation file:** `graph_builder/resolvers/ruby_resolver.py`

**Expected impact:** Ruby import classification improves. Unresolved imports split into gems (expected) vs truly unresolved (investigation targets). Resolution rate stays ~42.3% but the 57.7% unresolved is now explained.

---

## 5. Update Schema to Match New Properties

Add to `schema.py`:
- CALLS edge properties: `classification`, `resolution_confidence`
- IMPORTS edge properties: `local_binding`
- Function node properties: `decorators`
- Class node properties: `is_interface`
- New edge type: `INHERITS_VIA_METATABLE` (File → File, properties: `table_var`)
- CTX_READS/CTX_WRITES edge properties: `scope`

---

## Testing Strategy

1. **Edge properties:** Parse a fixture, ingest, query Memgraph for the new properties
2. **Dynamic prefix:** Test boundary matching with known false-positive cases
3. **Base inheritance:** Compare auto-detected vs hardcoded methods on test fixtures
4. **Python package root:** Test with nested package structure fixture
5. **Go go.mod:** Test with fixture containing `pp-consumer/common/utils` import → resolves
6. **Ruby Gemfile:** Test that `redis` import → `__ruby_gem__`, unknown import → None
7. **Schema:** Verify indexes created for new types

---

## Expected Impact Summary

| Fix | Metric | Before | After |
|-----|--------|--------|-------|
| Edge properties | Graph queryability | 6 fields lost | All written |
| Dynamic prefix | False positive edges | Unknown | Eliminated |
| Base inheritance | Auto-detection | Hardcoded 31 methods | Dynamic from AST |
| Python package root | Import classification | 36.7% resolved, rest unknown | Stdlib/third-party/internal split |
| Go go.mod | Go import resolution | 60.2% | ~85-90% |
| Ruby Gemfile | Ruby import classification | 42.3% resolved, rest unknown | Gem/stdlib/internal split |

---

## Files Modified

| File | Change |
|------|--------|
| `graph_builder/ingestion/writer.py` | Add properties to upsert_call, upsert_import, upsert_function, upsert_class, upsert_ctx_access. New upsert_metatable_inheritance. |
| `graph_builder/ingestion/schema.py` | Add new properties and INHERITS_VIA_METATABLE edge type |
| `graph_builder/resolvers/dynamic_prefix_resolver.py` | Replace `in` with boundary-aware matching |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Add auto-detection, keep hardcoded as fallback |
| `graph_builder/resolvers/python_resolver.py` | Add package root detection, Python stdlib set |
| `graph_builder/resolvers/go_resolver.py` | Parse go.mod, strip module prefix, classify external deps |
| `graph_builder/resolvers/ruby_resolver.py` | Parse Gemfile, classify gem imports |
| `graph_builder/main.py` | Wire metatable inheritance edges into ingestion |
| `graph_builder/tests/test_quick_fixes_v2.py` | New test file |
