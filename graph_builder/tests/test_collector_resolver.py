"""Tests for collector registration detection and resolution."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.collector_resolver import resolve_collectors

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_parse_collector_init():
    """Parse the collector init fixture and verify CollectorInfo is populated."""
    ast = parse_lua_file(str(FIXTURES / "collector_init.lua"))

    assert ast.collector_info is not None, "collector_info should not be None"
    assert ast.collector_info.name == "device", (
        f"Expected name='device', got '{ast.collector_info.name}'"
    )
    assert ast.collector_info.endpoint == "/api/device_id", (
        f"Expected endpoint='/api/device_id', got '{ast.collector_info.endpoint}'"
    )
    assert len(ast.collector_info.js_files) == 4, (
        f"Expected 4 js_files, got {len(ast.collector_info.js_files)}: {ast.collector_info.js_files}"
    )
    expected_js = [
        "device_utils.js.erb",
        "device_id.js.erb",
        "sensor.js.erb",
        "device_container.js.erb",
    ]
    assert ast.collector_info.js_files == expected_js, (
        f"Expected js_files={expected_js}, got {ast.collector_info.js_files}"
    )
    print("  PASS: test_parse_collector_init")


def test_resolve_collectors():
    """Parse fixture and run resolve_collectors, verify mapping output."""
    ast = parse_lua_file(str(FIXTURES / "collector_init.lua"))
    all_asts = {str(FIXTURES / "collector_init.lua"): ast}

    mappings = resolve_collectors(all_asts)

    assert len(mappings) == 1, f"Expected 1 mapping, got {len(mappings)}"
    m = mappings[0]
    assert m["collector_name"] == "device"
    assert m["endpoint"] == "/api/device_id"
    assert len(m["js_files"]) == 4
    assert m["init_file"] == str(FIXTURES / "collector_init.lua")
    print("  PASS: test_resolve_collectors")


def test_no_collector_in_normal_file():
    """Parse a normal Lua file and verify collector_info is None."""
    ast = parse_lua_file(str(FIXTURES / "module_M.lua"))

    assert ast.collector_info is None, (
        f"Expected collector_info=None for normal Lua file, got {ast.collector_info}"
    )
    print("  PASS: test_no_collector_in_normal_file")
