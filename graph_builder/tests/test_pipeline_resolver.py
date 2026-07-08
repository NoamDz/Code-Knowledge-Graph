"""Tests for dirty-flag -> assessor pipeline edge resolution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions
from graph_builder.resolvers.pipeline_resolver import resolve_pipeline_edges

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_dirty_flag_links_to_assessor():
    # producer fixture sets dirty flag "device_id"; assessor declares M.name="device_id"
    producer = parse_lua_file(str(FIXTURES / "assessor_keys.lua"))
    assessor = parse_lua_file(str(FIXTURES / "assessors/device_id_assessor.lua"))
    all_asts = {producer.file_path: producer, assessor.file_path: assessor}
    resolve_redis_abstractions(all_asts)  # populates dirty:* accesses
    edges = resolve_pipeline_edges(all_asts)
    pairs = {(e["source_file"], e["target_file"], e["flag"]) for e in edges}
    assert (producer.file_path, assessor.file_path, "device_id") in pairs
