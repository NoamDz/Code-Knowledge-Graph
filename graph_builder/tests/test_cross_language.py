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
