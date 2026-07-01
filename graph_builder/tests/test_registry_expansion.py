"""Tests for registry-style dynamic require_version(format(...)) expansion."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_format_prefix_extracted():
    ast = parse_lua_file(str(FIXTURES / "collectors_registry.lua"))
    dyn = [i for i in ast.imports if i.is_dynamic]
    assert dyn, "registry require should be flagged dynamic"
    assert any(i.static_prefix == "ato.collectors" for i in dyn)


def test_registry_expands_to_known_modules():
    reg = parse_lua_file(str(FIXTURES / "collectors_registry.lua"))
    # Two fake target modules under the ato.collectors namespace.
    from graph_builder.parsers.base import FileAST
    ipp = FileAST(file_path="/r/src/ato/collectors/ipp/init.lua", language="lua",
                  module_name="ato.collectors.ipp")
    dev = FileAST(file_path="/r/src/ato/collectors/device/init.lua", language="lua",
                  module_name="ato.collectors.device")
    all_asts = {reg.file_path: reg, ipp.file_path: ipp, dev.file_path: dev}
    edges, _ = resolve_dynamic_prefixes(all_asts)
    targets = {e["target_file"] for e in edges if e["source_file"] == reg.file_path}
    assert ipp.file_path in targets
    assert dev.file_path in targets
