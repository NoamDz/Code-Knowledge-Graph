"""Tests for Go Redis abstraction detection."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_go_redis_abstractions

FIXTURES = Path(__file__).parent / "fixtures" / "go"

def test_go_parser_detects_redis_calls():
    """Go parser should detect redisClient.Method() calls."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))
    redis_calls = [c for c in ast.calls if "redisClient" in c.callee_string]
    assert len(redis_calls) >= 3, f"Expected 3+ Redis calls, got {len(redis_calls)}: {[c.callee_string for c in ast.calls]}"

def test_go_redis_resolver():
    """Go Redis resolver should create RedisKeyAccess entries."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))
    all_asts = {str(FIXTURES / "redis_client.go"): ast}
    before = len(ast.redis_accesses)
    resolve_go_redis_abstractions(all_asts)
    after = len(ast.redis_accesses)
    assert after > before, f"Expected Redis accesses to increase, got {before} -> {after}"
    assert after >= 3, f"Expected at least 3 Redis accesses, got {after}"
    reads = [a for a in ast.redis_accesses if a.access_type == "read"]
    writes = [a for a in ast.redis_accesses if a.access_type == "write"]
    assert len(reads) >= 2, "GetAsString and HGet should be reads"
    assert len(writes) >= 1, "Set should be a write"

def test_go_redis_method_classification():
    """Verify correct read/write classification of Go Redis methods."""
    ast = parse_go_file(str(FIXTURES / "redis_client.go"))
    all_asts = {"test.go": ast}
    resolve_go_redis_abstractions(all_asts)
    ops = {a.operation: a.access_type for a in ast.redis_accesses}
    assert ops.get("GetAsString") == "read"
    assert ops.get("Set") == "write"
    assert ops.get("HGet") == "read"
