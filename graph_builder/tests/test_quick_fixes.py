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


# ───────────────────────────────────────────────────────────────
# 4C: Python RedisCluster factory
# ───────────────────────────────────────────────────────────────

def test_4c_redis_cluster_detected():
    """RedisCluster with self.connection should detect Redis ops."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    assert len(ast.redis_accesses) >= 2, (
        f"Expected >=2 Redis accesses, got {len(ast.redis_accesses)}: "
        f"{[(a.operation, a.access_type) for a in ast.redis_accesses]}"
    )


def test_4c_redis_cluster_read_write():
    """hget should be read, hset should be write."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    ops = {a.operation: a.access_type for a in ast.redis_accesses}
    assert ops.get("hget") == "read", f"hget should be read, got {ops.get('hget')}"
    assert ops.get("hset") == "write", f"hset should be write, got {ops.get('hset')}"


def test_4c_redis_cluster_import_detected():
    """RedisCluster should be registered via try/except import."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    import_modules = [imp.module_string for imp in ast.imports]
    assert any("redis" in m for m in import_modules), (
        f"Expected redis import, got: {import_modules}"
    )


# ───────────────────────────────────────────────────────────────
# 4D: Ruby preprocessor loading model
# ───────────────────────────────────────────────────────────────

def test_4d_dir_glob_loading_detected():
    """Dir.glob in preprocessor_loader.rb should produce LOADS_DYNAMICALLY targets."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    all_asts = {str(RB_FIXTURES / "preprocessor_loader.rb"): ast}
    resolver = RubyResolver(str(RB_FIXTURES))

    edges = resolver.resolve_dynamic_loading(all_asts)
    # Should find strip_whitespace.rb and normalize.rb in preprocess/
    target_names = {Path(e["target"]).name for e in edges}
    assert "strip_whitespace.rb" in target_names, (
        f"strip_whitespace.rb not in loading targets: {target_names}"
    )
    assert "normalize.rb" in target_names, (
        f"normalize.rb not in loading targets: {target_names}"
    )


def test_4d_class_eval_loading_detected():
    """class_eval(IO.read(...)) should be detected as dynamic loading."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    # Verify that the AST contains a call matching class_eval pattern
    class_eval_calls = [c for c in ast.calls if "class_eval" in c.callee_string]
    assert len(class_eval_calls) >= 1, (
        f"Expected class_eval call, got: {[c.callee_string for c in ast.calls]}"
    )


def test_4d_loading_edges_have_correct_structure():
    """Loading edges should have source, target, and load_type keys."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    all_asts = {str(RB_FIXTURES / "preprocessor_loader.rb"): ast}
    resolver = RubyResolver(str(RB_FIXTURES))

    edges = resolver.resolve_dynamic_loading(all_asts)
    for edge in edges:
        assert "source" in edge, f"Edge missing 'source': {edge}"
        assert "target" in edge, f"Edge missing 'target': {edge}"
        assert "load_type" in edge, f"Edge missing 'load_type': {edge}"
        assert edge["load_type"] in ("dir_glob", "class_eval"), (
            f"Unexpected load_type: {edge['load_type']}"
        )
