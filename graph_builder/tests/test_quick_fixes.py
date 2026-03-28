"""Tests for the quick-fixes bundle (4A-4H).

Run with: python -m pytest graph_builder/tests/test_quick_fixes.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_go_redis_abstractions
from graph_builder.resolvers.call_resolver import CallResolver
from graph_builder.resolvers.ruby_resolver import RubyResolver

GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"
PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"
RB_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"

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


# ───────────────────────────────────────────────────────────────
# 4B: Python self.method() resolution
# ───────────────────────────────────────────────────────────────

def test_4b_self_method_resolved():
    """self._validate_record() should resolve to the same-file function."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    self_calls = [c for c in ast.calls
                  if c.callee_string.startswith("self.")
                  and c.resolved_module is not None]
    resolved_names = {c.resolved_function for c in self_calls}
    assert "_validate_record" in resolved_names, (
        f"self._validate_record not resolved. Resolved: {resolved_names}"
    )
    assert "_add_to_batch" in resolved_names, (
        f"self._add_to_batch not resolved. Resolved: {resolved_names}"
    )
    assert "_flush_batch" in resolved_names, (
        f"self._flush_batch not resolved. Resolved: {resolved_names}"
    )


def test_4b_self_attribute_chain_not_resolved():
    """self.logger.warning() should NOT be resolved (attribute chain, not method)."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    # self.logger.warning → callee_string is "self.logger.warning"
    # The first "." split gives table_name="self", method_name="logger.warning"
    # "logger.warning" won't match any function name, so it should NOT resolve
    # via the self-python path
    logger_calls = [c for c in ast.calls
                    if "logger" in c.callee_string
                    and c.resolution_confidence == "self_python"]
    assert len(logger_calls) == 0, (
        f"self.logger.X calls should not resolve as self_python: {logger_calls}"
    )


def test_4b_self_resolution_confidence():
    """Self-resolved calls should have confidence 'self_python'."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    self_resolved = [c for c in ast.calls
                     if c.resolution_confidence == "self_python"]
    assert len(self_resolved) >= 3, (
        f"Expected >=3 self_python resolutions, got {len(self_resolved)}"
    )
