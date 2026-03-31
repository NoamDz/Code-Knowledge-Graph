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
