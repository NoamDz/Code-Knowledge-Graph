"""Tests for the quick-fixes bundle (4A-4H).

Run with: python -m pytest graph_builder/tests/test_quick_fixes.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_go_redis_abstractions

GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"

# ───────────────────────────────────────────────────────────────
# 4A: Go Redis r.client pattern + wrapper methods
# ───────────────────────────────────────────────────────────────

def test_4a_r_client_internal_redis_detected():
    """r.client.HGet inside redis wrapper should produce Redis accesses."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    internal_ops = [a for a in ast.redis_accesses if "r.client" in a.key_name]
    assert len(internal_ops) >= 3, (
        f"Expected >=3 internal r.client Redis ops, got {len(internal_ops)}: "
        f"{[(a.operation, a.key_name) for a in internal_ops]}"
    )
    internal_op_names = {a.operation for a in internal_ops}
    assert "HGet" in internal_op_names
    assert "Get" in internal_op_names
    assert "Del" in internal_op_names


def test_4a_wrapper_methods_detected():
    """s.redis.HGetAsString wrapper calls should be detected as Redis ops."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    wrapper_ops = [a for a in ast.redis_accesses
                   if a.operation in ("HGetAsString", "GetAsInt", "HSetWithExpire")]
    assert len(wrapper_ops) >= 3, (
        f"Expected >=3 wrapper Redis ops, got {len(wrapper_ops)}: "
        f"{[(a.operation, a.access_type) for a in wrapper_ops]}"
    )


def test_4a_read_write_classification():
    """Read/write classification should be correct for all detected ops."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    ops = {a.operation: a.access_type for a in ast.redis_accesses}
    # Reads
    for read_op in ("HGet", "Get", "HGetAsString", "GetAsInt"):
        if read_op in ops:
            assert ops[read_op] == "read", f"{read_op} should be read, got {ops[read_op]}"
    # Writes
    for write_op in ("Del", "HSet", "Expire", "HSetWithExpire"):
        if write_op in ops:
            assert ops[write_op] == "write", f"{write_op} should be write, got {ops[write_op]}"
