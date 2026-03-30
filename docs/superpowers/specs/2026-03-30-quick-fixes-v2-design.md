# Quick Fixes V2 — Design Spec

**Date:** 2026-03-30
**Goal:** Fix known issues that don't require BOB investigation: graph schema gaps, dynamic prefix false positives, base inheritance auto-detection, Python package root detection, and missing edge properties.

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
5. **Schema:** Verify indexes created for new types

---

## Files Modified

| File | Change |
|------|--------|
| `graph_builder/ingestion/writer.py` | Add properties to upsert_call, upsert_import, upsert_function, upsert_class, upsert_ctx_access. New upsert_metatable_inheritance. |
| `graph_builder/ingestion/schema.py` | Add new properties and INHERITS_VIA_METATABLE edge type |
| `graph_builder/resolvers/dynamic_prefix_resolver.py` | Replace `in` with boundary-aware matching |
| `graph_builder/resolvers/base_inheritance_resolver.py` | Add auto-detection, keep hardcoded as fallback |
| `graph_builder/resolvers/python_resolver.py` | Add package root detection, Python stdlib set |
| `graph_builder/main.py` | Wire metatable inheritance edges into ingestion |
| `graph_builder/tests/test_quick_fixes_v2.py` | New test file |
