"""Tests for module-level string constant extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_module_constants_extracted():
    ast = parse_lua_file(str(FIXTURES / "assessor_device_id.lua"))
    assert ast.module_constants.get("name") == "device_id"
    assert ast.module_constants.get("assess_key") == "device_id"
    assert ast.module_constants.get("id") == "13"
