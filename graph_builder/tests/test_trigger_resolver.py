"""Tests for trigger pub/sub edge resolution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.trigger_resolver import (
    resolve_trigger_events, resolve_trigger_edges,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_trigger_events_detected():
    pub = parse_lua_file(str(FIXTURES / "trigger_publisher.lua"))
    sub = parse_lua_file(str(FIXTURES / "trigger_subscriber.lua"))
    all_asts = {pub.file_path: pub, sub.file_path: sub}
    resolve_trigger_events(all_asts)
    pub_names = {(e.name, e.role) for e in pub.trigger_events}
    sub_names = {(e.name, e.role) for e in sub.trigger_events}
    assert ("new_policy_result", "publisher") in pub_names
    assert ("update_user_profile", "publisher") in pub_names
    assert ("new_policy_result", "subscriber") in sub_names


def test_trigger_edges_join_on_name():
    pub = parse_lua_file(str(FIXTURES / "trigger_publisher.lua"))
    sub = parse_lua_file(str(FIXTURES / "trigger_subscriber.lua"))
    all_asts = {pub.file_path: pub, sub.file_path: sub}
    resolve_trigger_events(all_asts)
    edges = resolve_trigger_edges(all_asts)
    pairs = {(e["source_file"], e["target_file"], e["name"]) for e in edges}
    assert (pub.file_path, sub.file_path, "new_policy_result") in pairs
