"""Tests that store-vector / dirty-flag keys carry real identity."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def _accesses(name):
    ast = parse_lua_file(str(FIXTURES / name))
    resolve_redis_abstractions({ast.file_path: ast})
    return ast.redis_accesses


def test_assess_vector_key_is_namespaced():
    keys = {a.key_name for a in _accesses("assessor_keys.lua")}
    assert "assess:session_info" in keys
    assert "<via store_vector>" not in keys


def test_producer_and_consumer_share_key():
    accesses = _accesses("assessor_keys.lua")
    producers = [a for a in accesses if a.key_name == "assess:session_info" and a.access_type == "write"]
    consumers = [a for a in accesses if a.key_name == "assess:session_info" and a.access_type == "read"]
    assert producers and consumers


def test_dirty_flag_key_recorded():
    keys = {a.key_name for a in _accesses("assessor_keys.lua")}
    assert "dirty:ato:device_id" in keys
