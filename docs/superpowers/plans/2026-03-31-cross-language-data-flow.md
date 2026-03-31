# Cross-Language Data Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect 3 shared data structures (SessionInfo, ModelPredictionResult, Event) and 2 shared constants (MODEL_TYPES, RISK_LEVELS) defined across Lua/Go/Python/Ruby, creating ~28 cross-language structural edges.

**Architecture:** New cross_language_resolver.py with static configuration maps (same approach as shared Redis patterns in cross_service_resolver.py). File path matching via suffix index. Writer additions for SharedDataStructure and SharedConstant nodes + DEFINES_SHARED_STRUCTURE and DEFINES_CONSTANT edges.

**Tech Stack:** Python, existing resolver/writer infrastructure, static config maps from BOB investigation

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `graph_builder/ingestion/schema.py` | Modify | Add indexes for SharedDataStructure and SharedConstant nodes |
| `graph_builder/resolvers/cross_language_resolver.py` | Create | Static config maps for shared structures/constants, resolve functions |
| `graph_builder/ingestion/writer.py` | Modify | Add upsert methods for SharedDataStructure, SharedConstant nodes and DEFINES_SHARED_STRUCTURE, DEFINES_CONSTANT edges |
| `graph_builder/main.py` | Modify | Wire cross_language_resolver into build pipeline (Step 4i) |
| `graph_builder/tests/test_cross_language.py` | Create | Tests for all components |

---

## Task 1: Schema and Data Models (schema.py)

Add Memgraph indexes for the two new node types. No base.py changes needed — shared structures and constants are resolver-level concepts, not per-file AST fields.

**Files:**
- Modify: `graph_builder/ingestion/schema.py`

### Step 1: Write tests

- [ ] **1.1: Add schema tests to test_cross_language.py**

Create `graph_builder/tests/test_cross_language.py`:

```python
"""Tests for cross-language data flow detection.

Covers: SharedDataStructure nodes, SharedConstant nodes,
DEFINES_SHARED_STRUCTURE edges, DEFINES_CONSTANT edges.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# --- Schema tests ---

from graph_builder.ingestion.schema import INDEX_STATEMENTS, NODE_TYPES, EDGE_TYPES


def test_schema_has_shared_data_structure_index():
    """SharedDataStructure index exists in INDEX_STATEMENTS."""
    joined = " ".join(INDEX_STATEMENTS)
    assert "SharedDataStructure" in joined


def test_schema_has_shared_constant_index():
    """SharedConstant index exists in INDEX_STATEMENTS."""
    joined = " ".join(INDEX_STATEMENTS)
    assert "SharedConstant" in joined


def test_node_types_has_shared_data_structure():
    """NODE_TYPES registry includes SharedDataStructure."""
    assert "SharedDataStructure" in NODE_TYPES
    assert "name" in NODE_TYPES["SharedDataStructure"]


def test_node_types_has_shared_constant():
    """NODE_TYPES registry includes SharedConstant."""
    assert "SharedConstant" in NODE_TYPES
    assert "name" in NODE_TYPES["SharedConstant"]


def test_edge_types_has_defines_shared_structure():
    """EDGE_TYPES registry includes DEFINES_SHARED_STRUCTURE."""
    assert "DEFINES_SHARED_STRUCTURE" in EDGE_TYPES


def test_edge_types_has_defines_constant():
    """EDGE_TYPES registry includes DEFINES_CONSTANT."""
    assert "DEFINES_CONSTANT" in EDGE_TYPES
```

- [ ] **1.2: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "schema or node_types or edge_types"`
Expected: AssertionError — "SharedDataStructure" not found

### Step 2: Implement schema additions

- [ ] **2.1: Add indexes and type registrations to schema.py**

In `graph_builder/ingestion/schema.py`, add to `INDEX_STATEMENTS`:

```python
    "CREATE INDEX ON :SharedDataStructure(name);",
    "CREATE INDEX ON :SharedConstant(name);",
```

Add to `NODE_TYPES`:

```python
    "SharedDataStructure": ["name", "fields", "serialization_format"],
    "SharedConstant": ["name", "values"],
```

Add to `EDGE_TYPES`:

```python
    "DEFINES_SHARED_STRUCTURE": ["language", "field_count"],
    "DEFINES_CONSTANT": ["language"],
```

### Step 3: Verify tests pass

- [ ] **3.1: Run schema tests**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "schema or node_types or edge_types"`
Expected: All 6 tests pass

- [ ] **3.2: Commit**

```bash
git add graph_builder/ingestion/schema.py graph_builder/tests/test_cross_language.py
git commit -m "feat: add SharedDataStructure and SharedConstant schema (indexes, node types, edge types)"
```

---

## Task 2: Create cross_language_resolver.py with Static Configs

New resolver module with static configuration maps for shared data structures and shared constants. Uses the same `_build_suffix_index` / `_match_file_suffix` pattern from `cross_service_resolver.py`.

**Files:**
- Create: `graph_builder/resolvers/cross_language_resolver.py`

### Step 1: Write tests

- [ ] **1.1: Add resolver tests to test_cross_language.py**

Append to `graph_builder/tests/test_cross_language.py`:

```python
from graph_builder.parsers.base import FileAST


# --- Static config inventory tests ---

from graph_builder.resolvers.cross_language_resolver import (
    SHARED_DATA_STRUCTURES,
    SHARED_CONSTANTS,
    resolve_shared_structures,
    resolve_shared_constants,
)


def test_shared_structures_inventory_complete():
    """Static config has all 3 BOB-confirmed shared structures."""
    names = {s["name"] for s in SHARED_DATA_STRUCTURES}
    assert "SessionInfo" in names
    assert "ModelPredictionResult" in names
    assert "Event" in names


def test_shared_constants_inventory_complete():
    """Static config has all 2 BOB-confirmed shared constants."""
    names = {c["name"] for c in SHARED_CONSTANTS}
    assert "MODEL_TYPES" in names
    assert "RISK_LEVELS" in names


def test_session_info_has_correct_languages():
    """SessionInfo is defined in Lua, Go, and Python."""
    session_info = [s for s in SHARED_DATA_STRUCTURES if s["name"] == "SessionInfo"][0]
    assert set(session_info["definitions"].keys()) == {"lua", "go", "python"}


def test_event_has_correct_languages():
    """Event is defined in Ruby and Lua."""
    event = [s for s in SHARED_DATA_STRUCTURES if s["name"] == "Event"][0]
    assert set(event["definitions"].keys()) == {"ruby", "lua"}


def test_model_types_has_correct_languages():
    """MODEL_TYPES constant is defined in Lua, Go, and Python."""
    model_types = [c for c in SHARED_CONSTANTS if c["name"] == "MODEL_TYPES"][0]
    assert set(model_types["files"].keys()) == {"lua", "go", "python"}


# --- resolve_shared_structures tests ---

def test_resolve_shared_structures_matches_files():
    """resolve_shared_structures creates edges when definition files are present."""
    all_asts = {
        "ato/models/session_info.lua": FileAST(
            file_path="ato/models/session_info.lua", language="lua"),
        "core/model_prediction/server/models/session.go": FileAST(
            file_path="core/model_prediction/server/models/session.go", language="go"),
        "deferrer/poller/poller/models/session.py": FileAST(
            file_path="deferrer/poller/poller/models/session.py", language="python"),
    }
    edges = resolve_shared_structures(all_asts)

    # SessionInfo has 3 definition files, all present -> 3 DEFINES_SHARED_STRUCTURE edges
    session_edges = [e for e in edges if e["structure_name"] == "SessionInfo"]
    assert len(session_edges) == 3

    languages = {e["language"] for e in session_edges}
    assert languages == {"lua", "go", "python"}


def test_resolve_shared_structures_with_repo_prefix():
    """Suffix matching works with repo_root prefix on file paths."""
    all_asts = {
        "repo/src/ato/models/session_info.lua": FileAST(
            file_path="repo/src/ato/models/session_info.lua", language="lua"),
        "repo/src/core/model_prediction/server/models/session.go": FileAST(
            file_path="repo/src/core/model_prediction/server/models/session.go",
            language="go"),
    }
    edges = resolve_shared_structures(all_asts)
    session_edges = [e for e in edges if e["structure_name"] == "SessionInfo"]
    assert len(session_edges) == 2


def test_resolve_shared_structures_unmatched_files_skipped():
    """Files not in the repo produce no edges."""
    all_asts = {
        "totally/different/path.lua": FileAST(
            file_path="totally/different/path.lua", language="lua"),
    }
    edges = resolve_shared_structures(all_asts)
    assert len(edges) == 0


def test_resolve_shared_structures_partial_match():
    """Only matched files produce edges; unmatched are skipped."""
    all_asts = {
        "ato/models/session_info.lua": FileAST(
            file_path="ato/models/session_info.lua", language="lua"),
        # Go file NOT present -> only 1 edge for SessionInfo
    }
    edges = resolve_shared_structures(all_asts)
    session_edges = [e for e in edges if e["structure_name"] == "SessionInfo"]
    assert len(session_edges) == 1
    assert session_edges[0]["language"] == "lua"


def test_resolve_shared_structures_edge_shape():
    """Each edge has correct keys: structure_name, fields, serialization, file, language, field_count."""
    all_asts = {
        "ato/events/init.lua": FileAST(
            file_path="ato/events/init.lua", language="lua"),
    }
    edges = resolve_shared_structures(all_asts)
    event_edges = [e for e in edges if e["structure_name"] == "Event"]
    assert len(event_edges) == 1
    edge = event_edges[0]
    assert "structure_name" in edge
    assert "fields" in edge
    assert "serialization" in edge
    assert "file" in edge
    assert "language" in edge
    assert "field_count" in edge
    assert edge["field_count"] == len(edge["fields"])


# --- resolve_shared_constants tests ---

def test_resolve_shared_constants_matches_files():
    """resolve_shared_constants creates edges when constant files are present."""
    all_asts = {
        "ato/config/init.lua": FileAST(
            file_path="ato/config/init.lua", language="lua"),
        "core/model_prediction/server/common/constants/constants.go": FileAST(
            file_path="core/model_prediction/server/common/constants/constants.go",
            language="go"),
        "deferrer/poller/poller/constants.py": FileAST(
            file_path="deferrer/poller/poller/constants.py", language="python"),
    }
    edges = resolve_shared_constants(all_asts)

    # MODEL_TYPES: 3 files * 1 edge each = 3 edges
    model_edges = [e for e in edges if e["constant_name"] == "MODEL_TYPES"]
    assert len(model_edges) == 3

    # RISK_LEVELS: same 3 files = 3 edges
    risk_edges = [e for e in edges if e["constant_name"] == "RISK_LEVELS"]
    assert len(risk_edges) == 3

    # Total: 6 edges
    assert len(edges) == 6


def test_resolve_shared_constants_with_repo_prefix():
    """Suffix matching works with repo_root prefix on file paths."""
    all_asts = {
        "repo/src/ato/config/init.lua": FileAST(
            file_path="repo/src/ato/config/init.lua", language="lua"),
    }
    edges = resolve_shared_constants(all_asts)
    # Both MODEL_TYPES and RISK_LEVELS reference ato/config/init.lua
    lua_edges = [e for e in edges if e["language"] == "lua"]
    assert len(lua_edges) == 2


def test_resolve_shared_constants_unmatched_files_skipped():
    """Files not in the repo produce no edges."""
    all_asts = {
        "totally/different/path.lua": FileAST(
            file_path="totally/different/path.lua", language="lua"),
    }
    edges = resolve_shared_constants(all_asts)
    assert len(edges) == 0


def test_resolve_shared_constants_edge_shape():
    """Each edge has correct keys: constant_name, values, file, language."""
    all_asts = {
        "ato/config/init.lua": FileAST(
            file_path="ato/config/init.lua", language="lua"),
    }
    edges = resolve_shared_constants(all_asts)
    assert len(edges) >= 1
    edge = edges[0]
    assert "constant_name" in edge
    assert "values" in edge
    assert "file" in edge
    assert "language" in edge
```

- [ ] **1.2: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "resolve_shared or inventory"`
Expected: ImportError — `cross_language_resolver` not found

### Step 2: Implement cross_language_resolver.py

- [ ] **2.1: Create graph_builder/resolvers/cross_language_resolver.py**

```python
"""Cross-language data flow resolver: shared structures and constants.

Uses static configuration maps (from BOB investigation) to create edges
linking files that define the same data structures or constants across
languages. Same approach as shared Redis patterns in cross_service_resolver.py.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST
from graph_builder.resolvers.cross_service_resolver import (
    _build_suffix_index,
    _match_file_suffix,
)


# =============================================================================
# Section 1: Shared Data Structures
# =============================================================================

SHARED_DATA_STRUCTURES = [
    {
        "name": "SessionInfo",
        "fields": ["session_id", "user_id", "device_id", "ip_address",
                   "user_agent", "timestamp", "risk_score", "attributes"],
        "definitions": {
            "lua": ["ato/models/session_info.lua"],
            "go": ["core/model_prediction/server/models/session.go"],
            "python": ["deferrer/poller/poller/models/session.py"],
        },
        "serialization": "json",
    },
    {
        "name": "ModelPredictionResult",
        "fields": ["model_type", "score", "features", "model_version",
                   "timestamp"],
        "definitions": {
            "go": ["core/model_prediction/server/models/model_prediction.go"],
            "lua": ["core/model_prediction/client/models/task.lua"],
            "python": ["deferrer/poller/poller/models/prediction.py"],
        },
        "serialization": "json",
    },
    {
        "name": "Event",
        "fields": ["event_type", "session_id", "user_id", "timestamp",
                   "data"],
        "definitions": {
            "ruby": ["common/generator/lib/models/event.rb"],
            "lua": ["ato/events/init.lua"],
        },
        "serialization": "json",
    },
]


# =============================================================================
# Section 2: Shared Constants
# =============================================================================

SHARED_CONSTANTS = [
    {
        "name": "MODEL_TYPES",
        "values": ["fraud_detection", "ato_detection", "behavior_analysis"],
        "files": {
            "lua": ["ato/config/init.lua"],
            "go": ["core/model_prediction/server/common/constants/constants.go"],
            "python": ["deferrer/poller/poller/constants.py"],
        },
    },
    {
        "name": "RISK_LEVELS",
        "values": ["low", "medium", "high", "critical"],
        "files": {
            "lua": ["ato/config/init.lua"],
            "go": ["core/model_prediction/server/common/constants/constants.go"],
            "python": ["deferrer/poller/poller/constants.py"],
        },
    },
]


# =============================================================================
# Section 3: Resolver Functions
# =============================================================================

def resolve_shared_structures(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create DEFINES_SHARED_STRUCTURE edges from the static config map.

    For each known shared structure, checks if definition file paths match
    any parsed file. Uses suffix matching to handle different repo_root prefixes.

    Returns list of edge dicts:
        [{"structure_name", "fields", "serialization", "file", "language", "field_count"}]
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for struct_cfg in SHARED_DATA_STRUCTURES:
        name = struct_cfg["name"]
        fields = struct_cfg["fields"]
        serialization = struct_cfg["serialization"]

        for language, file_patterns in struct_cfg["definitions"].items():
            for pattern in file_patterns:
                matched = _match_file_suffix(pattern, suffix_index)
                if matched:
                    edges.append({
                        "structure_name": name,
                        "fields": fields,
                        "serialization": serialization,
                        "file": matched,
                        "language": language,
                        "field_count": len(fields),
                    })

    return edges


def resolve_shared_constants(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create DEFINES_CONSTANT edges from the static config map.

    For each known shared constant set, checks if definition file paths match
    any parsed file. Uses suffix matching to handle different repo_root prefixes.

    Returns list of edge dicts:
        [{"constant_name", "values", "file", "language"}]
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for const_cfg in SHARED_CONSTANTS:
        name = const_cfg["name"]
        values = const_cfg["values"]

        for language, file_patterns in const_cfg["files"].items():
            for pattern in file_patterns:
                matched = _match_file_suffix(pattern, suffix_index)
                if matched:
                    edges.append({
                        "constant_name": name,
                        "values": values,
                        "file": matched,
                        "language": language,
                    })

    return edges
```

### Step 3: Verify tests pass

- [ ] **3.1: Run resolver tests**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "resolve_shared or inventory"`
Expected: All 15 tests pass

- [ ] **3.2: Commit**

```bash
git add graph_builder/resolvers/cross_language_resolver.py graph_builder/tests/test_cross_language.py
git commit -m "feat: add cross_language_resolver with static config maps for shared structures and constants"
```

---

## Task 3: GraphWriter Upsert Methods (writer.py)

Add 4 new methods to GraphWriter for upserting SharedDataStructure/SharedConstant nodes and DEFINES_SHARED_STRUCTURE/DEFINES_CONSTANT edges. These are low-volume writes (at most ~28 edges) so direct `_run()` calls are appropriate — no buffering needed.

**Files:**
- Modify: `graph_builder/ingestion/writer.py`

### Step 1: Write tests

- [ ] **1.1: Add writer tests to test_cross_language.py**

Append to `graph_builder/tests/test_cross_language.py`:

```python
# --- Writer method existence tests ---
# (Actual Cypher execution requires Memgraph; here we test method signatures exist)

from graph_builder.ingestion.writer import GraphWriter


def test_writer_has_upsert_shared_data_structure():
    """GraphWriter has upsert_shared_data_structure method."""
    assert hasattr(GraphWriter, "upsert_shared_data_structure")
    import inspect
    sig = inspect.signature(GraphWriter.upsert_shared_data_structure)
    params = list(sig.parameters.keys())
    assert "name" in params
    assert "fields" in params
    assert "serialization_format" in params


def test_writer_has_upsert_defines_structure():
    """GraphWriter has upsert_defines_structure method."""
    assert hasattr(GraphWriter, "upsert_defines_structure")
    import inspect
    sig = inspect.signature(GraphWriter.upsert_defines_structure)
    params = list(sig.parameters.keys())
    assert "file_path" in params
    assert "structure_name" in params
    assert "language" in params
    assert "field_count" in params


def test_writer_has_upsert_shared_constant():
    """GraphWriter has upsert_shared_constant method."""
    assert hasattr(GraphWriter, "upsert_shared_constant")
    import inspect
    sig = inspect.signature(GraphWriter.upsert_shared_constant)
    params = list(sig.parameters.keys())
    assert "name" in params
    assert "values" in params


def test_writer_has_upsert_defines_constant():
    """GraphWriter has upsert_defines_constant method."""
    assert hasattr(GraphWriter, "upsert_defines_constant")
    import inspect
    sig = inspect.signature(GraphWriter.upsert_defines_constant)
    params = list(sig.parameters.keys())
    assert "file_path" in params
    assert "constant_name" in params
    assert "language" in params
```

- [ ] **1.2: Run tests to verify they fail**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "writer_has"`
Expected: AssertionError — methods not found on GraphWriter

### Step 2: Implement writer methods

- [ ] **2.1: Add upsert methods to writer.py**

Add after the `upsert_config_reads` method (around line 673) in `graph_builder/ingestion/writer.py`:

```python
    # --- Cross-language data flow upserts ---

    def upsert_shared_data_structure(self, name: str, fields: list[str],
                                      serialization_format: str):
        """Create or update a SharedDataStructure node."""
        self._run("""
            MERGE (s:SharedDataStructure {name: $name})
            SET s.fields = $fields,
                s.serialization_format = $fmt
        """, name=name, fields=fields, fmt=serialization_format)

    def upsert_defines_structure(self, file_path: str, structure_name: str,
                                  language: str, field_count: int):
        """Create a DEFINES_SHARED_STRUCTURE edge from File to SharedDataStructure."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (s:SharedDataStructure {name: $struct})
            MERGE (f)-[:DEFINES_SHARED_STRUCTURE {language: $lang, field_count: $fc}]->(s)
        """, file=file_path, struct=structure_name,
             lang=language, fc=field_count)

    def upsert_shared_constant(self, name: str, values: list[str]):
        """Create or update a SharedConstant node."""
        self._run("""
            MERGE (c:SharedConstant {name: $name})
            SET c.values = $values
        """, name=name, values=values)

    def upsert_defines_constant(self, file_path: str, constant_name: str,
                                 language: str):
        """Create a DEFINES_CONSTANT edge from File to SharedConstant."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (c:SharedConstant {name: $const})
            MERGE (f)-[:DEFINES_CONSTANT {language: $lang}]->(c)
        """, file=file_path, const=constant_name, lang=language)
```

### Step 3: Verify tests pass

- [ ] **3.1: Run writer tests**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "writer_has"`
Expected: All 4 tests pass

- [ ] **3.2: Commit**

```bash
git add graph_builder/ingestion/writer.py graph_builder/tests/test_cross_language.py
git commit -m "feat: add GraphWriter upsert methods for SharedDataStructure and SharedConstant"
```

---

## Task 4: Wire into main.py Build Pipeline

Add Step 4i in the build command to run the cross-language resolver, then ingest the resulting edges in Step 5.

**Files:**
- Modify: `graph_builder/main.py`

### Step 1: Write tests

- [ ] **1.1: Add pipeline wiring tests to test_cross_language.py**

Append to `graph_builder/tests/test_cross_language.py`:

```python
# --- Pipeline wiring tests ---

def test_main_imports_cross_language_resolver():
    """main.py can import the cross_language_resolver functions."""
    from graph_builder.resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )
    assert callable(resolve_shared_structures)
    assert callable(resolve_shared_constants)


def test_resolve_shared_structures_returns_list():
    """resolve_shared_structures returns a list even with empty input."""
    from graph_builder.resolvers.cross_language_resolver import resolve_shared_structures
    result = resolve_shared_structures({})
    assert isinstance(result, list)
    assert len(result) == 0


def test_resolve_shared_constants_returns_list():
    """resolve_shared_constants returns a list even with empty input."""
    from graph_builder.resolvers.cross_language_resolver import resolve_shared_constants
    result = resolve_shared_constants({})
    assert isinstance(result, list)
    assert len(result) == 0
```

- [ ] **1.2: Run tests to verify they pass** (these test existing code)

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "main_imports or returns_list"`
Expected: All 3 tests pass (resolver was created in Task 2)

### Step 2: Wire into build command

- [ ] **2.1: Add cross-language resolution step to main.py**

In `graph_builder/main.py`, add Step 4i after Step 4h (the cross-service IPC detection block, around line 311). Insert before the `# Step 5: Ingest into Memgraph` comment:

```python
    # Step 4i: Cross-language data flow detection
    click.echo("Detecting cross-language shared structures and constants...")
    from .resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )
    structure_edges = resolve_shared_structures(all_asts)
    constant_edges = resolve_shared_constants(all_asts)
    if structure_edges or constant_edges:
        click.echo(f"  Shared structures: {len(structure_edges)} edges, "
                   f"shared constants: {len(constant_edges)} edges")
```

- [ ] **2.2: Add ingestion of cross-language edges in Step 5**

In `graph_builder/main.py`, add after the config_edges ingestion loop (around line 421, after `writer.upsert_config_reads(edge["file"], edge["config"])`):

```python
        # Ingest cross-language shared structure edges
        seen_structures: set[str] = set()
        for edge in structure_edges:
            struct_name = edge["structure_name"]
            if struct_name not in seen_structures:
                writer.upsert_shared_data_structure(
                    struct_name, edge["fields"], edge["serialization"],
                )
                seen_structures.add(struct_name)
            writer.upsert_defines_structure(
                edge["file"], struct_name,
                edge["language"], edge["field_count"],
            )

        # Ingest cross-language shared constant edges
        seen_constants: set[str] = set()
        for edge in constant_edges:
            const_name = edge["constant_name"]
            if const_name not in seen_constants:
                writer.upsert_shared_constant(const_name, edge["values"])
                seen_constants.add(const_name)
            writer.upsert_defines_constant(
                edge["file"], const_name, edge["language"],
            )
```

### Step 3: Verify tests pass

- [ ] **3.1: Run all pipeline tests**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v -k "main_imports or returns_list"`
Expected: All 3 tests pass

- [ ] **3.2: Commit**

```bash
git add graph_builder/main.py graph_builder/tests/test_cross_language.py
git commit -m "feat: wire cross-language resolver into build pipeline (Step 4i + ingestion)"
```

---

## Task 5: Integration Test

End-to-end test: build a multi-language AST set with matching file paths, run both resolvers, and verify the complete edge set.

**Files:**
- Modify: `graph_builder/tests/test_cross_language.py`

### Step 1: Write and run integration test

- [ ] **1.1: Add integration test**

Append to `graph_builder/tests/test_cross_language.py`:

```python
# --- Integration: full pipeline test ---

def test_full_cross_language_pipeline():
    """End-to-end: multi-language ASTs produce correct shared structure + constant edges."""
    from graph_builder.resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )

    # Build a multi-language AST set matching all known shared structures
    all_asts = {
        # SessionInfo definitions (Lua, Go, Python)
        "ato/models/session_info.lua": FileAST(
            file_path="ato/models/session_info.lua", language="lua"),
        "core/model_prediction/server/models/session.go": FileAST(
            file_path="core/model_prediction/server/models/session.go",
            language="go"),
        "deferrer/poller/poller/models/session.py": FileAST(
            file_path="deferrer/poller/poller/models/session.py",
            language="python"),

        # ModelPredictionResult definitions (Go, Lua, Python)
        "core/model_prediction/server/models/model_prediction.go": FileAST(
            file_path="core/model_prediction/server/models/model_prediction.go",
            language="go"),
        "core/model_prediction/client/models/task.lua": FileAST(
            file_path="core/model_prediction/client/models/task.lua",
            language="lua"),
        "deferrer/poller/poller/models/prediction.py": FileAST(
            file_path="deferrer/poller/poller/models/prediction.py",
            language="python"),

        # Event definitions (Ruby, Lua)
        "common/generator/lib/models/event.rb": FileAST(
            file_path="common/generator/lib/models/event.rb", language="ruby"),
        "ato/events/init.lua": FileAST(
            file_path="ato/events/init.lua", language="lua"),

        # Constants definitions (Lua, Go, Python)
        "ato/config/init.lua": FileAST(
            file_path="ato/config/init.lua", language="lua"),
        "core/model_prediction/server/common/constants/constants.go": FileAST(
            file_path="core/model_prediction/server/common/constants/constants.go",
            language="go"),
        "deferrer/poller/poller/constants.py": FileAST(
            file_path="deferrer/poller/poller/constants.py", language="python"),
    }

    # Run resolvers
    structure_edges = resolve_shared_structures(all_asts)
    constant_edges = resolve_shared_constants(all_asts)

    # --- Verify shared structures ---

    # SessionInfo: 3 languages = 3 edges
    session_edges = [e for e in structure_edges if e["structure_name"] == "SessionInfo"]
    assert len(session_edges) == 3
    session_langs = {e["language"] for e in session_edges}
    assert session_langs == {"lua", "go", "python"}

    # ModelPredictionResult: 3 languages = 3 edges
    mpr_edges = [e for e in structure_edges if e["structure_name"] == "ModelPredictionResult"]
    assert len(mpr_edges) == 3
    mpr_langs = {e["language"] for e in mpr_edges}
    assert mpr_langs == {"go", "lua", "python"}

    # Event: 2 languages = 2 edges
    event_edges = [e for e in structure_edges if e["structure_name"] == "Event"]
    assert len(event_edges) == 2
    event_langs = {e["language"] for e in event_edges}
    assert event_langs == {"ruby", "lua"}

    # Total structure edges: 3 + 3 + 2 = 8
    assert len(structure_edges) == 8

    # --- Verify shared constants ---

    # MODEL_TYPES: 3 languages = 3 edges
    model_type_edges = [e for e in constant_edges if e["constant_name"] == "MODEL_TYPES"]
    assert len(model_type_edges) == 3

    # RISK_LEVELS: 3 languages = 3 edges
    risk_edges = [e for e in constant_edges if e["constant_name"] == "RISK_LEVELS"]
    assert len(risk_edges) == 3

    # Total constant edges: 3 + 3 = 6
    assert len(constant_edges) == 6

    # --- Verify total ---
    # 8 structure edges + 6 constant edges = 14 DEFINES edges
    # Plus 3 SharedDataStructure nodes + 2 SharedConstant nodes = 5 node upserts
    # Total graph writes: ~14 edges + 5 nodes = 19 minimum
    # (Spec says ~28 because it counts both node creation and edge creation per file)
    total_edges = len(structure_edges) + len(constant_edges)
    assert total_edges == 14

    # Verify all edges have required fields
    for edge in structure_edges:
        assert "structure_name" in edge
        assert "file" in edge
        assert "language" in edge
        assert "fields" in edge
        assert "serialization" in edge
        assert "field_count" in edge
        assert edge["field_count"] > 0

    for edge in constant_edges:
        assert "constant_name" in edge
        assert "file" in edge
        assert "language" in edge
        assert "values" in edge
        assert len(edge["values"]) > 0


def test_full_pipeline_with_repo_prefix():
    """End-to-end with repo_root prefix: suffix matching works correctly."""
    from graph_builder.resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )

    prefix = "/home/user/repos/pinpoint/src"
    all_asts = {
        f"{prefix}/ato/models/session_info.lua": FileAST(
            file_path=f"{prefix}/ato/models/session_info.lua", language="lua"),
        f"{prefix}/core/model_prediction/server/models/session.go": FileAST(
            file_path=f"{prefix}/core/model_prediction/server/models/session.go",
            language="go"),
        f"{prefix}/ato/config/init.lua": FileAST(
            file_path=f"{prefix}/ato/config/init.lua", language="lua"),
        f"{prefix}/core/model_prediction/server/common/constants/constants.go": FileAST(
            file_path=f"{prefix}/core/model_prediction/server/common/constants/constants.go",
            language="go"),
    }

    structure_edges = resolve_shared_structures(all_asts)
    constant_edges = resolve_shared_constants(all_asts)

    # SessionInfo: Lua + Go = 2 edges (Python file not present)
    session_edges = [e for e in structure_edges if e["structure_name"] == "SessionInfo"]
    assert len(session_edges) == 2

    # MODEL_TYPES: Lua + Go = 2 edges (Python file not present)
    model_edges = [e for e in constant_edges if e["constant_name"] == "MODEL_TYPES"]
    assert len(model_edges) == 2

    # Verify file paths are the full prefixed paths, not the suffix patterns
    for edge in structure_edges:
        assert edge["file"].startswith(prefix)


def test_full_pipeline_empty_asts():
    """End-to-end with no matching files: returns empty lists."""
    from graph_builder.resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )

    all_asts = {}
    assert resolve_shared_structures(all_asts) == []
    assert resolve_shared_constants(all_asts) == []


def test_structure_node_deduplication():
    """Multiple definition files for the same structure share the same structure_name."""
    from graph_builder.resolvers.cross_language_resolver import resolve_shared_structures

    all_asts = {
        "ato/models/session_info.lua": FileAST(
            file_path="ato/models/session_info.lua", language="lua"),
        "core/model_prediction/server/models/session.go": FileAST(
            file_path="core/model_prediction/server/models/session.go",
            language="go"),
    }
    edges = resolve_shared_structures(all_asts)
    session_edges = [e for e in edges if e["structure_name"] == "SessionInfo"]

    # Both edges reference the same structure_name
    assert len(session_edges) == 2
    assert session_edges[0]["structure_name"] == session_edges[1]["structure_name"]
    # But different files and languages
    assert session_edges[0]["file"] != session_edges[1]["file"]
    assert session_edges[0]["language"] != session_edges[1]["language"]
```

- [ ] **1.2: Run all tests**

Run: `python -m pytest graph_builder/tests/test_cross_language.py -v`
Expected: All tests pass (schema, resolver, writer signatures, pipeline wiring, integration)

- [ ] **1.3: Run with verbose output to confirm edge counts**

Run: `python -m pytest graph_builder/tests/test_cross_language.py::test_full_cross_language_pipeline -v -s`
Expected: 8 structure edges + 6 constant edges = 14 total definition edges

- [ ] **1.4: Run existing test suites to verify no regressions**

Run: `python -m pytest graph_builder/tests/test_cross_service.py -v`
Expected: All existing tests still pass

Run: `python -m pytest graph_builder/tests/ -v --timeout=60`
Expected: Full test suite passes

- [ ] **1.5: Commit**

```bash
git add graph_builder/tests/test_cross_language.py
git commit -m "test: add integration tests for cross-language data flow (structures + constants)"
```

---

## Verification Checklist

After all 5 tasks are complete, verify:

| Check | Command | Expected |
|-------|---------|----------|
| All tests pass | `python -m pytest graph_builder/tests/test_cross_language.py -v` | 30+ tests green |
| No regressions | `python -m pytest graph_builder/tests/ -v --timeout=60` | All tests green |
| Schema has new indexes | Check `INDEX_STATEMENTS` has `SharedDataStructure` and `SharedConstant` | 2 new index statements |
| Resolver creates correct edges | `test_full_cross_language_pipeline` | 8 structure + 6 constant = 14 edges |
| Writer has 4 new methods | `test_writer_has_*` | 4 method signature tests pass |
| Pipeline wired | `grep "cross_language_resolver" graph_builder/main.py` | Import + resolve + ingest blocks present |

## Files Modified (Summary)

| File | Lines Changed | What |
|------|--------------|------|
| `graph_builder/ingestion/schema.py` | +6 | 2 indexes, 2 NODE_TYPES entries, 2 EDGE_TYPES entries |
| `graph_builder/resolvers/cross_language_resolver.py` | ~130 (new) | Static configs + 2 resolve functions |
| `graph_builder/ingestion/writer.py` | ~40 | 4 new upsert methods |
| `graph_builder/main.py` | ~30 | Step 4i resolution + Step 5 ingestion |
| `graph_builder/tests/test_cross_language.py` | ~350 (new) | 30+ tests covering all components |
