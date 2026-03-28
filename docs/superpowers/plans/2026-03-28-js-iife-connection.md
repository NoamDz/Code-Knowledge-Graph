# JS IIFE Connection Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect 94 orphaned JavaScript files by detecting ERB render-chain inclusions and fixing HTTP call detection for dynamic URLs.

**Architecture:** New js_erb_resolver.py reads raw .js.erb file content (before ERB stripping) to extract render() calls, resolves filenames to file paths, and creates INCLUDES edges. HTTP fix updates _extract_js_http_calls() to use placeholder for non-string URLs.

**Tech Stack:** Python, regex, existing GraphWriter INCLUDES edge support

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/resolvers/js_erb_resolver.py` | Create | ERB render-chain parser: detects `env["template"].render("file", env)` patterns, resolves filenames to file paths, detects collector loop |
| `graph_builder/ingestion/writer.py` | Modify | Add `upsert_js_includes()` method for File-to-File INCLUDES edges |
| `graph_builder/parsers/js_parser.py` | Modify | Fix `_extract_js_http_calls()`: use `__dynamic_url__` for non-string URLs, add `Container._collect*` callees |
| `graph_builder/main.py` | Modify | Wire `JsErbResolver` into build pipeline after parsing, before ingestion |
| `graph_builder/tests/test_js_iife_connection.py` | Create | Tests for ERB resolver, collector loop, HTTP fix |
| `graph_builder/tests/fixtures/js/container.js.erb` | Create | Test fixture simulating real container with render calls and collector loop |
| `graph_builder/tests/fixtures/js/net.js.erb` | Create | Test fixture for a sub-template with nested render calls |
| `graph_builder/tests/fixtures/js/utils.js` | Create | Test fixture for a plain .js file (no ERB, no render calls) |

---

## Task 1: Create js_erb_resolver.py with ERB render pattern detection

The resolver reads raw `.js.erb` file content (before ERB stripping is applied by the parser) and extracts all `env["template"].render("filename", env)` calls using regex. Each filename is resolved to a full file path.

**Files:**
- Create: `graph_builder/resolvers/js_erb_resolver.py`
- Create: `graph_builder/tests/fixtures/js/container.js.erb`
- Create: `graph_builder/tests/fixtures/js/net.js.erb`
- Create: `graph_builder/tests/fixtures/js/utils.js`
- Create: `graph_builder/tests/test_js_iife_connection.py`

### Step 1: Create test fixtures

- [ ] **1.1: Create container.js.erb fixture**

Create `graph_builder/tests/fixtures/js/container.js.erb`:

```javascript
(function(){
  <%=env["template"].render("utils.js", env)%>
  <%=env["template"].render("net.js.erb", env)%>
  <%=env['template'].render("base64.js", env)%>

  var Container = (function(){
    function _setup() {}
    function _sendRequest(type, url, params, callback, data, extra) {}
    return { _setup: _setup, _sendRequest: _sendRequest };
  })();

  <% env['collectors_rendered'].each { |code| %>
    <%=code%>
  <% } %>

  Container._setup();
})();
```

- [ ] **1.2: Create net.js.erb fixture**

Create `graph_builder/tests/fixtures/js/net.js.erb`:

```javascript
<%=env["template"].render("base64.js", env)%>

var Net = (function(){
  function _request(config) {
    var url = config.url;
    var method = config.type || "GET";
  }
  return { _request: _request };
})();
```

- [ ] **1.3: Create utils.js fixture (plain JS, no ERB)**

Create `graph_builder/tests/fixtures/js/utils.js`:

```javascript
var Utils = (function(){
  function isString(val) { return typeof val === "string"; }
  function isArray(val) { return Array.isArray(val); }
  return { isString: isString, isArray: isArray };
})();
```

### Step 2: Write tests

- [ ] **2.1: Create test file with ERB render detection tests**

Create `graph_builder/tests/test_js_iife_connection.py`:

```python
"""Tests for JS IIFE connection model: ERB render-chain and HTTP call fix.

Covers:
  - ERB render() pattern detection from raw .js.erb content
  - Filename-to-filepath resolution
  - Collector loop detection
  - HTTP call fix for dynamic URLs
  - Container._collect* as data exfiltration calls
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.resolvers.js_erb_resolver import JsErbResolver, ERB_RENDER_PATTERN

FIXTURES = Path(__file__).parent / "fixtures" / "js"


# --- ERB render pattern regex ---

def test_erb_render_pattern_double_quotes():
    """Detects env["template"].render("net.js.erb", env)."""
    line = '<%=env["template"].render("net.js.erb", env)%>'
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["net.js.erb"]


def test_erb_render_pattern_single_quotes():
    """Detects env['template'].render("utils.js", env)."""
    line = "<%=env['template'].render(\"utils.js\", env)%>"
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["utils.js"]


def test_erb_render_pattern_with_path():
    """Detects render calls with paths: render("path/to/file.js.erb", env)."""
    line = '<%=env["template"].render("path/to/file.js.erb", env)%>'
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["path/to/file.js.erb"]


def test_erb_render_pattern_multiple_on_different_lines():
    """Detects multiple render calls in multi-line content."""
    content = '''<%=env["template"].render("base64.js", env)%>
<%=env["template"].render("json.js", env)%>
<%=env["template"].render("utils.js", env)%>'''
    matches = ERB_RENDER_PATTERN.findall(content)
    assert matches == ["base64.js", "json.js", "utils.js"]


def test_erb_render_pattern_no_match_on_plain_js():
    """Plain JS without ERB tags should yield no render matches."""
    content = 'var x = template.render("foo.js");'
    matches = ERB_RENDER_PATTERN.findall(content)
    assert matches == []


# --- Render extraction from fixtures ---

def test_extract_renders_from_container():
    """container.js.erb should yield render calls for utils.js, net.js.erb, base64.js."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "container.js.erb"))
    assert "utils.js" in renders
    assert "net.js.erb" in renders
    assert "base64.js" in renders


def test_extract_renders_from_net():
    """net.js.erb should yield render call for base64.js."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "net.js.erb"))
    assert "base64.js" in renders


def test_extract_renders_from_plain_js():
    """utils.js (plain JS) should yield no render calls."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "utils.js"))
    assert renders == []
```

- [ ] **2.2: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py::test_erb_render_pattern_double_quotes -v`
Expected: ImportError -- `js_erb_resolver` module doesn't exist yet

### Step 3: Implement ERB render detection

- [ ] **3.1: Create js_erb_resolver.py**

Create `graph_builder/resolvers/js_erb_resolver.py`:

```python
"""JS ERB render-chain resolver.

Detects the inclusion hierarchy in .js.erb files by parsing ERB template
render() calls. These files are assembled at build time by a Ruby generator
that uses env["template"].render("filename.js.erb", env) to concatenate
JavaScript files into a single IIFE bundle.

This resolver:
  1. Reads raw .js.erb file content (BEFORE ERB stripping)
  2. Extracts all render("filename", env) calls via regex
  3. Resolves each filename to a file path
  4. Detects the collector loop pattern in container.js.erb
  5. Returns INCLUDES edges (source_file -> included_file)

Usage:
    resolver = JsErbResolver("/path/to/repo")
    edges = resolver.resolve_all(all_asts)
"""

from __future__ import annotations

import re
from pathlib import Path

from ..parsers.base import FileAST

# Matches: env["template"].render("filename.js.erb", env)
# Handles both single and double quotes around "template" and the filename.
ERB_RENDER_PATTERN = re.compile(
    r'''env\[['"]template['"]\]\.render\(\s*['"]([^'"]+)['"]\s*,'''
)

# Matches the collector loop: env['collectors_rendered'].each
COLLECTOR_LOOP_PATTERN = re.compile(
    r'''env\[['"]collectors_rendered['"]\]\.each'''
)


class JsErbResolver:
    """Resolves ERB render-chain inclusions in .js.erb files."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._file_index: dict[str, str] = {}  # filename -> full path
        self._build_file_index()

    def _build_file_index(self):
        """Index all .js and .js.erb files by their basename for resolution."""
        skip = {"node_modules", ".git", "vendor", "dist", "build"}
        for ext in ("*.js", "*.js.erb"):
            for js_file in self.repo_root.rglob(ext):
                if any(s in js_file.parts for s in skip):
                    continue
                # Index by filename (basename)
                name = js_file.name
                full_path = str(js_file)
                # First occurrence wins; collisions handled in resolve_filename
                if name not in self._file_index:
                    self._file_index[name] = full_path

    def extract_render_calls(self, file_path: str) -> list[str]:
        """Extract all rendered filenames from a .js.erb file's raw content.

        Args:
            file_path: Path to the .js.erb file

        Returns:
            List of rendered filenames (e.g., ["net.js.erb", "utils.js"])
        """
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, IOError):
            return []

        return ERB_RENDER_PATTERN.findall(content)

    def has_collector_loop(self, file_path: str) -> bool:
        """Check if the file contains the collectors_rendered.each loop."""
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, IOError):
            return False

        return bool(COLLECTOR_LOOP_PATTERN.search(content))

    def resolve_filename(self, filename: str, from_file: str) -> str | None:
        """Resolve a rendered filename to a full file path.

        Search order:
          1. Same directory as the rendering file
          2. Global file index (all known JS/JS.ERB files)

        Args:
            filename: The filename from the render() call (e.g., "net.js.erb")
            from_file: The file containing the render() call

        Returns:
            Full file path, or None if not found.
        """
        from_dir = Path(from_file).parent

        # 1. Check same directory
        candidate = from_dir / filename
        if candidate.exists():
            return str(candidate.resolve())

        # 2. If filename contains a path separator, try relative to repo root
        if "/" in filename:
            candidate = self.repo_root / filename
            if candidate.exists():
                return str(candidate.resolve())

        # 3. Search the global file index by basename
        basename = Path(filename).name
        if basename in self._file_index:
            return self._file_index[basename]

        return None

    def find_collector_entry_points(self, all_asts: dict[str, FileAST]) -> list[str]:
        """Find collector entry-point files for the collectors_rendered loop.

        Collector entry points are .js.erb files inside */templates/ directories
        that define collector behavior. These are the top-level files loaded by
        the Ruby generator's snippet['collectors'].each loop.

        Returns:
            List of file paths for collector entry-point templates.
        """
        collectors = []
        for file_path, ast in all_asts.items():
            if ast.language != "javascript":
                continue
            # Collector entry points live in templates/ directories
            # and are .js.erb files
            normalized = file_path.replace("\\", "/")
            if "/templates/" in normalized and file_path.endswith(".js.erb"):
                collectors.append(file_path)
        return collectors

    def resolve_all(self, all_asts: dict[str, FileAST]) -> list[dict]:
        """Resolve all ERB render-chain inclusions across all JS files.

        Returns list of edge dicts:
            [{"source_file": "...", "target_file": "...", "type": "render"}]
        """
        edges = []
        container_file = None

        for file_path, ast in all_asts.items():
            if ast.language != "javascript":
                continue
            if not file_path.endswith(".erb"):
                continue

            # Extract render calls from raw file content
            rendered_filenames = self.extract_render_calls(file_path)

            for filename in rendered_filenames:
                target = self.resolve_filename(filename, file_path)
                if target:
                    edges.append({
                        "source_file": file_path,
                        "target_file": target,
                        "type": "render",
                    })

            # Detect the collector loop container
            if self.has_collector_loop(file_path):
                container_file = file_path

        # If we found a container with collectors_rendered.each,
        # create INCLUDES edges to all collector entry points
        if container_file:
            collector_files = self.find_collector_entry_points(all_asts)
            for coll_path in collector_files:
                # Don't include the container itself
                if coll_path == container_file:
                    continue
                # Don't duplicate edges already created by explicit render() calls
                existing_targets = {e["target_file"] for e in edges
                                    if e["source_file"] == container_file}
                if coll_path not in existing_targets:
                    edges.append({
                        "source_file": container_file,
                        "target_file": coll_path,
                        "type": "collector_loop",
                    })

        return edges

    def stats(self) -> dict:
        return {"indexed_files": len(self._file_index)}
```

- [ ] **3.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "erb_render"` and `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "extract_renders"`
Expected: All 8 regex and extraction tests pass

- [ ] **3.3: Commit**

```bash
git add graph_builder/resolvers/js_erb_resolver.py graph_builder/tests/test_js_iife_connection.py graph_builder/tests/fixtures/js/
git commit -m "feat: ERB render-chain resolver for JS IIFE connection model

Detects env['template'].render('file.js.erb', env) patterns in raw
.js.erb content and resolves filenames to file paths. Lays the
foundation for connecting 94 orphaned JavaScript files."
```

---

## Task 2: Add filename-to-filepath resolution logic

Expand the resolver tests to cover the filename-to-filepath resolution with same-directory priority and global fallback.

**Files:**
- Modify: `graph_builder/tests/test_js_iife_connection.py`

### Step 1: Write resolution tests

- [ ] **1.1: Add filename resolution tests**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- Filename-to-filepath resolution ---

def test_resolve_filename_same_directory():
    """Resolver finds file in the same directory as the rendering file."""
    resolver = JsErbResolver(str(FIXTURES))
    # container.js.erb renders "utils.js" -> should find fixtures/js/utils.js
    result = resolver.resolve_filename("utils.js", str(FIXTURES / "container.js.erb"))
    assert result is not None
    assert result.replace("\\", "/").endswith("utils.js")


def test_resolve_filename_global_index():
    """Resolver falls back to global file index when not in same directory."""
    resolver = JsErbResolver(str(FIXTURES))
    # Look up from a hypothetical subdirectory; should still find via index
    result = resolver.resolve_filename("utils.js", str(FIXTURES / "subdir" / "fake.js.erb"))
    assert result is not None
    assert result.replace("\\", "/").endswith("utils.js")


def test_resolve_filename_not_found():
    """Resolver returns None for a filename that doesn't exist anywhere."""
    resolver = JsErbResolver(str(FIXTURES))
    result = resolver.resolve_filename("nonexistent_file.js", str(FIXTURES / "container.js.erb"))
    assert result is None


def test_resolve_all_produces_edges():
    """resolve_all should produce INCLUDES edges from container -> utils, net, base64."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    # Build minimal ASTs representing the fixture files
    container_path = str(FIXTURES / "container.js.erb")
    net_path = str(FIXTURES / "net.js.erb")
    utils_path = str(FIXTURES / "utils.js")

    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
        net_path: FileAST(file_path=net_path, language="javascript"),
        utils_path: FileAST(file_path=utils_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    # container.js.erb should have edges to utils.js, net.js.erb, base64.js
    container_edges = [e for e in edges if e["source_file"] == container_path]
    container_targets = {Path(e["target_file"]).name for e in container_edges}

    assert "utils.js" in container_targets
    assert "net.js.erb" in container_targets
    # base64.js doesn't exist as a fixture, so it won't resolve


def test_resolve_all_nested_includes():
    """net.js.erb renders base64.js -> nested chain detected."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    net_path = str(FIXTURES / "net.js.erb")
    all_asts = {
        net_path: FileAST(file_path=net_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    net_edges = [e for e in edges if e["source_file"] == net_path]
    # base64.js doesn't exist as fixture, so this tests that we attempt resolution
    # but get 0 edges (file not found). The important thing is no crash.
    assert isinstance(net_edges, list)
```

- [ ] **1.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "resolve_filename or resolve_all"`
Expected: All resolution tests pass

- [ ] **1.3: Commit**

```bash
git add graph_builder/tests/test_js_iife_connection.py
git commit -m "test: filename-to-filepath resolution for ERB render-chain

Covers same-directory priority, global index fallback, not-found case,
and end-to-end resolve_all edge production."
```

---

## Task 3: Add collector loop detection for container.js.erb pattern

The container file uses `env['collectors_rendered'].each { |code| }` to include collector files at runtime. Since the filenames are runtime data, we create INCLUDES edges from the container to all collector entry-point templates (files matching `*/templates/*.js.erb`).

**Files:**
- Modify: `graph_builder/tests/test_js_iife_connection.py`

### Step 1: Write collector loop tests

- [ ] **1.1: Add collector loop tests**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- Collector loop detection ---

def test_collector_loop_detected_in_container():
    """container.js.erb has the collectors_rendered.each pattern."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "container.js.erb")) is True


def test_collector_loop_not_in_plain_js():
    """utils.js (plain JS) has no collector loop."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "utils.js")) is False


def test_collector_loop_not_in_sub_template():
    """net.js.erb (sub-template) has no collector loop."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "net.js.erb")) is False


def test_find_collector_entry_points():
    """Collector entry points are .js.erb files in templates/ directories."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    # Simulate ASTs with template paths
    all_asts = {
        "src/ato/templates/device_container.js.erb": FileAST(
            file_path="src/ato/templates/device_container.js.erb", language="javascript"),
        "src/malware/templates/malware_collector.js.erb": FileAST(
            file_path="src/malware/templates/malware_collector.js.erb", language="javascript"),
        "src/lib/js/utils.js": FileAST(
            file_path="src/lib/js/utils.js", language="javascript"),
        "src/common/base/js/container.js.erb": FileAST(
            file_path="src/common/base/js/container.js.erb", language="javascript"),
    }

    collectors = resolver.find_collector_entry_points(all_asts)

    # Only files in templates/ directories that end in .js.erb
    assert "src/ato/templates/device_container.js.erb" in collectors
    assert "src/malware/templates/malware_collector.js.erb" in collectors
    # Non-template files should NOT be collector entry points
    assert "src/lib/js/utils.js" not in collectors
    assert "src/common/base/js/container.js.erb" not in collectors


def test_resolve_all_with_collector_loop():
    """Container with collector loop should include collector entry points."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    container_path = str(FIXTURES / "container.js.erb")

    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
        "src/ato/templates/device_collector.js.erb": FileAST(
            file_path="src/ato/templates/device_collector.js.erb", language="javascript"),
        "src/malware/templates/mal_collector.js.erb": FileAST(
            file_path="src/malware/templates/mal_collector.js.erb", language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    # Container should have collector_loop edges to the template files
    collector_edges = [e for e in edges
                       if e["source_file"] == container_path
                       and e["type"] == "collector_loop"]
    collector_targets = {e["target_file"] for e in collector_edges}

    assert "src/ato/templates/device_collector.js.erb" in collector_targets
    assert "src/malware/templates/mal_collector.js.erb" in collector_targets
```

- [ ] **1.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "collector"`
Expected: All collector loop tests pass

- [ ] **1.3: Commit**

```bash
git add graph_builder/tests/test_js_iife_connection.py
git commit -m "test: collector loop detection for container.js.erb

Detects env['collectors_rendered'].each pattern and creates INCLUDES
edges from container to all .js.erb files in templates/ directories."
```

---

## Task 4: Wire resolver into main.py build pipeline

Add `JsErbResolver` as a new step in the build pipeline. It runs after parsing but before ingestion, producing INCLUDES edges that the writer ingests.

**Files:**
- Modify: `graph_builder/main.py`

### Step 1: Write integration test

- [ ] **1.1: Add pipeline integration test**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- Pipeline integration ---

def test_resolver_can_be_instantiated_with_repo_root():
    """JsErbResolver can be instantiated with any directory."""
    resolver = JsErbResolver(str(FIXTURES))
    stats = resolver.stats()
    assert stats["indexed_files"] >= 3  # container.js.erb, net.js.erb, utils.js


def test_resolve_all_returns_list_of_dicts():
    """resolve_all returns correctly structured edge dicts."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    container_path = str(FIXTURES / "container.js.erb")
    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)
    for edge in edges:
        assert "source_file" in edge
        assert "target_file" in edge
        assert "type" in edge
        assert edge["type"] in ("render", "collector_loop")
```

### Step 2: Modify main.py

- [ ] **2.1: Add ERB resolver step to build command**

In `graph_builder/main.py`, add the following import at the top of the file:

```python
# No top-level import needed -- imported lazily in the build function
```

In the `build()` function, add a new step **after Step 4f (dynamic prefix expansion) and before Step 5 (ingest into Memgraph)**:

```python
    # Step 4g: Resolve JS ERB render-chain inclusions
    click.echo("Resolving JS ERB render-chain inclusions...")
    from .resolvers.js_erb_resolver import JsErbResolver
    js_erb_resolver = JsErbResolver(config.repo_root)
    js_erb_edges = js_erb_resolver.resolve_all(all_asts)
    if js_erb_edges:
        render_edges = [e for e in js_erb_edges if e["type"] == "render"]
        collector_edges = [e for e in js_erb_edges if e["type"] == "collector_loop"]
        click.echo(f"  ERB render includes: {len(render_edges)}, "
                   f"collector loop includes: {len(collector_edges)}")
```

Then inside the ingestion block (after the existing `# Ingest dynamic prefix edges` block and before `click.echo(f"  {writer.write_count} graph writes")`), add:

```python
        # Ingest JS ERB render-chain edges
        if js_erb_edges:
            for edge in js_erb_edges:
                writer.upsert_js_includes(
                    edge["source_file"], edge["target_file"], edge["type"],
                )
```

- [ ] **2.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v`
Expected: All tests pass

- [ ] **2.3: Commit**

```bash
git add graph_builder/main.py graph_builder/tests/test_js_iife_connection.py
git commit -m "feat: wire JsErbResolver into build pipeline

Adds Step 4g: resolve JS ERB render-chain inclusions. Runs after all
other resolvers, produces INCLUDES edges ingested by GraphWriter."
```

---

## Task 5: Add GraphWriter upsert_js_includes method

Add a method to `GraphWriter` that creates `INCLUDES` edges between `File` nodes. The existing `INCLUDES` edge type in the schema (used for Ruby mixins Class->Module) is different from this File->File usage, so we use separate edge properties to distinguish them.

**Files:**
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Write test

- [ ] **1.1: Add writer test**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- Writer method ---

def test_upsert_js_includes_method_exists():
    """GraphWriter should have an upsert_js_includes method."""
    from graph_builder.ingestion.writer import GraphWriter
    assert hasattr(GraphWriter, "upsert_js_includes")


def test_upsert_js_includes_signature():
    """upsert_js_includes should accept source_file, target_file, include_type."""
    import inspect
    from graph_builder.ingestion.writer import GraphWriter
    sig = inspect.signature(GraphWriter.upsert_js_includes)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "source_file" in params
    assert "target_file" in params
    assert "include_type" in params
```

### Step 2: Implement

- [ ] **2.1: Add upsert_js_includes to writer.py**

Add to `graph_builder/ingestion/writer.py`, after the `upsert_potential_import` method (around line 514):

```python
    def upsert_js_includes(self, source_file: str, target_file: str,
                            include_type: str = "render"):
        """Create an INCLUDES edge between two File nodes (JS ERB render-chain).

        Args:
            source_file: The .js.erb file that contains the render() call
            target_file: The file being rendered/included
            include_type: "render" for explicit render() calls,
                          "collector_loop" for collectors_rendered.each
        """
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:INCLUDES {include_type: $include_type, language: "javascript"}]->(tgt)
        """, source=source_file, target=target_file, include_type=include_type)
```

- [ ] **2.2: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "upsert_js_includes"`
Expected: Both writer tests pass

- [ ] **2.3: Commit**

```bash
git add graph_builder/ingestion/writer.py
git commit -m "feat: GraphWriter.upsert_js_includes for File->File INCLUDES edges

Creates INCLUDES edges between File nodes with include_type and
language properties to distinguish JS ERB render-chain from Ruby mixins."
```

---

## Task 6: Fix _extract_js_http_calls dynamic URL handling

The `_extract_js_http_calls()` function in `js_parser.py` skips `Container._sendRequest` calls when the URL argument is a function call (not a string literal). Fix: use `"__dynamic_url__"` placeholder. Also add `Container._collect` and `Container._collectImmediateWithType` as data exfiltration call patterns.

**Files:**
- Modify: `graph_builder/parsers/js_parser.py`
- Modify: `graph_builder/tests/test_js_iife_connection.py`

### Step 1: Write tests

- [ ] **1.1: Add HTTP call fix tests**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- HTTP call detection fix ---

from graph_builder.parsers.js_parser import parse_js_file


def test_send_request_with_dynamic_url_detected():
    """Container._sendRequest('xframe', getTriggerUrl(), ...) should be detected."""
    import tempfile, os

    code = '''
(function(){
  var Container = {};
  Container._sendRequest = function(type, url, params, cb, data, extra) {};

  function reportDone() {}
  function getTriggerUrl() { return "/api/trigger"; }
  function getTriggerParams() { return {}; }
  function getTriggerData() { return {}; }
  function getTriggerExtra() { return {}; }

  function sendData() {
    Container._sendRequest("xframe", getTriggerUrl(), getTriggerParams(), reportDone, getTriggerData(), getTriggerExtra());
  }
})();
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(code)
        f.flush()
        try:
            ast = parse_js_file(f.name)
            # Should detect the _sendRequest call with dynamic URL
            assert len(ast.http_calls) >= 1
            call = ast.http_calls[0]
            assert call.url_or_path == "__dynamic_url__"
            assert call.method == "XFRAME"
            assert call.function == "sendData"
        finally:
            os.unlink(f.name)


def test_send_request_with_string_url_still_works():
    """Container._sendRequest('post', '/api/data', ...) still captures the string URL."""
    import tempfile, os

    code = '''
(function(){
  function submit() {
    Container._sendRequest("post", "/api/data", {}, function(){});
  }
})();
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(code)
        f.flush()
        try:
            ast = parse_js_file(f.name)
            assert len(ast.http_calls) >= 1
            call = ast.http_calls[0]
            assert call.url_or_path == "/api/data"
            assert call.method == "POST"
        finally:
            os.unlink(f.name)


def test_container_collect_detected():
    """Container._collect() should be detected as a data exfiltration call."""
    import tempfile, os

    code = '''
(function(){
  function gatherData() {
    Container._collect("device_data", getDeviceInfo());
  }

  function gatherImmediate() {
    Container._collectImmediateWithType("urgent", getData(), "high");
  }
})();
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(code)
        f.flush()
        try:
            ast = parse_js_file(f.name)
            assert len(ast.http_calls) >= 2
            callees = {c.function for c in ast.http_calls}
            assert "gatherData" in callees
            assert "gatherImmediate" in callees
        finally:
            os.unlink(f.name)
```

- [ ] **1.2: Run tests to see them fail**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "send_request or container_collect"`
Expected: `test_send_request_with_dynamic_url_detected` fails (0 http_calls), `test_container_collect_detected` fails (0 http_calls)

### Step 2: Implement the fix

- [ ] **2.1: Modify _SEND_REQUEST_CALLEES and add _COLLECT_CALLEES**

In `graph_builder/parsers/js_parser.py`, update line 27:

Replace:
```python
_SEND_REQUEST_CALLEES = {"sendRequest", "Container._sendRequest", "backwardCommunicator._sendRequest"}
```

With:
```python
_SEND_REQUEST_CALLEES = {"sendRequest", "Container._sendRequest", "backwardCommunicator._sendRequest"}

_COLLECT_CALLEES = {"Container._collect", "Container._collectImmediateWithType"}
```

- [ ] **2.2: Fix the dynamic URL handling in _extract_js_http_calls**

In `graph_builder/parsers/js_parser.py`, in the `_extract_js_http_calls` function, find the sendRequest block (lines 527-539):

Replace:
```python
        if callee in _SEND_REQUEST_CALLEES and args and args.named_child_count >= 2:
            method_arg = args.named_children[0]
            url_arg = args.named_children[1]
            method = _try_get_string(method_arg, source)
            url = _try_get_string(url_arg, source)
            if url:
                enclosing = _find_enclosing(call_node, source)
                ast.http_calls.append(HttpCallRef(
                    url_or_path=url,
                    method=(method or "unknown").upper(),
                    function=enclosing,
                    line=call_node.start_point[0] + 1,
                ))
```

With:
```python
        if callee in _SEND_REQUEST_CALLEES and args and args.named_child_count >= 2:
            method_arg = args.named_children[0]
            url_arg = args.named_children[1]
            method = _try_get_string(method_arg, source)
            url = _try_get_string(url_arg, source)
            # Use placeholder when URL is dynamic (function call, variable, etc.)
            if not url:
                url = "__dynamic_url__"
            enclosing = _find_enclosing(call_node, source)
            ast.http_calls.append(HttpCallRef(
                url_or_path=url,
                method=(method or "unknown").upper(),
                function=enclosing,
                line=call_node.start_point[0] + 1,
            ))
```

- [ ] **2.3: Add Container._collect* detection block**

In the same function, after the `Net._request` block (after line 554), add:

```python
        # Container._collect / Container._collectImmediateWithType — data exfiltration
        elif callee in _COLLECT_CALLEES and args:
            enclosing = _find_enclosing(call_node, source)
            # First arg is typically a data type string
            data_type = None
            if args.named_child_count >= 1:
                data_type = _try_get_string(args.named_children[0], source)
            ast.http_calls.append(HttpCallRef(
                url_or_path=data_type or "__collect__",
                method="COLLECT",
                function=enclosing,
                line=call_node.start_point[0] + 1,
            ))
```

- [ ] **2.4: Run tests**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v -k "send_request or container_collect"`
Expected: All 3 HTTP call tests pass

- [ ] **2.5: Run existing JS parser tests to check for regressions**

Run: `python -m pytest graph_builder/tests/test_all_parsers.py -v -k "js"`
Expected: All existing tests still pass

- [ ] **2.6: Commit**

```bash
git add graph_builder/parsers/js_parser.py graph_builder/tests/test_js_iife_connection.py
git commit -m "fix: JS HTTP call detection for dynamic URLs and _collect calls

- _sendRequest with non-string URL now uses '__dynamic_url__' placeholder
  instead of being silently skipped. Detects 5-8 previously missed calls.
- Container._collect and Container._collectImmediateWithType detected as
  data exfiltration calls with method='COLLECT'."
```

---

## Task 7: Integration test

End-to-end test that validates the full flow: fixture files parsed, ERB resolver runs, edges produced, and HTTP calls detected correctly.

**Files:**
- Modify: `graph_builder/tests/test_js_iife_connection.py`

### Step 1: Write integration test

- [ ] **1.1: Add full integration test**

Add to `graph_builder/tests/test_js_iife_connection.py`:

```python
# --- Full integration ---

def test_full_integration_parse_resolve_edges():
    """End-to-end: parse fixtures, run ERB resolver, verify edges and HTTP calls."""
    from graph_builder.parsers.js_parser import parse_js_file
    from graph_builder.resolvers.js_erb_resolver import JsErbResolver

    container_path = str(FIXTURES / "container.js.erb")
    net_path = str(FIXTURES / "net.js.erb")
    utils_path = str(FIXTURES / "utils.js")

    # Step 1: Parse all fixtures
    all_asts = {}
    for fpath in [container_path, net_path, utils_path]:
        ast = parse_js_file(fpath)
        all_asts[fpath] = ast

    # Step 2: Verify parsing worked
    assert all_asts[container_path].language == "javascript"
    assert all_asts[net_path].language == "javascript"
    assert all_asts[utils_path].language == "javascript"

    # Step 3: Run ERB resolver
    resolver = JsErbResolver(str(FIXTURES))
    edges = resolver.resolve_all(all_asts)

    # Step 4: Verify edges
    edge_pairs = [(e["source_file"], Path(e["target_file"]).name) for e in edges]

    # container.js.erb -> utils.js
    assert (container_path, "utils.js") in edge_pairs
    # container.js.erb -> net.js.erb
    assert (container_path, "net.js.erb") in edge_pairs

    # Step 5: Verify all edges have required fields
    for edge in edges:
        assert "source_file" in edge
        assert "target_file" in edge
        assert "type" in edge


def test_no_js_files_produces_no_edges():
    """When there are no JS files, ERB resolver produces no edges."""
    from graph_builder.parsers.base import FileAST
    from graph_builder.resolvers.js_erb_resolver import JsErbResolver

    resolver = JsErbResolver(str(FIXTURES))
    all_asts = {
        "foo.lua": FileAST(file_path="foo.lua", language="lua"),
        "bar.py": FileAST(file_path="bar.py", language="python"),
    }

    edges = resolver.resolve_all(all_asts)
    assert edges == []
```

- [ ] **1.2: Run full test suite**

Run: `python -m pytest graph_builder/tests/test_js_iife_connection.py -v`
Expected: All tests pass

- [ ] **1.3: Run full project test suite to check for regressions**

Run: `python -m pytest graph_builder/tests/ -v`
Expected: No regressions

- [ ] **1.4: Final commit**

```bash
git add graph_builder/tests/test_js_iife_connection.py
git commit -m "test: full integration test for JS IIFE connection model

End-to-end: parse .js.erb fixtures, run ERB resolver, verify INCLUDES
edges and HTTP call detection. Covers the complete data flow."
```

---

## Integration Verification

After all 7 tasks:

- [ ] **Run full test suite**

```bash
python -m pytest graph_builder/tests/ -v
```

- [ ] **Run on product codebase** (on Mac)

```bash
code-graph health -c config.yml
```

Expected improvements:
- JS orphan files: 94 -> ~10-15
- New INCLUDES edges: ~60-70 (ERB render-chain)
- New HTTP_CALLS edges: 0 -> 5-8 (dynamic URL fix)
- New COLLECT edges: 0 -> 3-5 (Container._collect*)

---

## Summary

| Task | Expected Impact | Method |
|------|----------------|--------|
| 1. ERB render detection | Core regex + extraction from raw .js.erb | `ERB_RENDER_PATTERN` regex on file content |
| 2. Filename resolution | Same-dir priority, global fallback | `resolve_filename()` with `_file_index` |
| 3. Collector loop | Container -> all templates/*.js.erb | `COLLECTOR_LOOP_PATTERN` + `find_collector_entry_points()` |
| 4. Pipeline wiring | Step 4g in build command | `JsErbResolver.resolve_all()` in `main.py` |
| 5. Writer method | File->File INCLUDES edges | `upsert_js_includes()` with include_type property |
| 6. HTTP call fix | 0 -> 5-8 sendRequest + 3-5 _collect | `__dynamic_url__` placeholder, `_COLLECT_CALLEES` |
| 7. Integration test | End-to-end validation | Parse fixtures, resolve, verify edges |
