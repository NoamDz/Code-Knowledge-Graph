"""Unit tests for inline nginx Lua block -> call graph linking (explain_flow #1)."""

from graph_builder.parsers.nginx_parser import (
    extract_requires,
    resolve_inline_phase_handles,
    NginxLocation,
    NginxLuaPhase,
)


def test_extracts_dotted_require():
    assert extract_requires('require("core.openresty.global_controller").run()') == [
        "core.openresty.global_controller"
    ]


def test_extracts_single_quotes_and_no_parens():
    assert extract_requires("local x = require 'a.b'") == ["a.b"]


def test_extracts_multiple_and_dedupes_preserving_order():
    code = 'local a = require("x.y")\nrequire("x.y")\nrequire("z")'
    assert extract_requires(code) == ["x.y", "z"]


def test_empty_or_none():
    assert extract_requires("") == []
    assert extract_requires(None) == []


class _FakeResolver:
    """Stands in for LuaResolver — resolve(module_string) -> file path or None."""
    def __init__(self, mapping):
        self.mapping = mapping
    def resolve(self, module_string, from_file=None):
        return self.mapping.get(module_string)


def test_maps_inline_require_to_handles_edge():
    phase = NginxLuaPhase(
        directive="content_by_lua_block", phase="content", is_inline=True,
        lua_file=None, inline_code='require("core.global_controller").run()', line=1,
    )
    loc = NginxLocation(path="/wisp", modifier=None, line=1, phases=[phase])
    resolver = _FakeResolver({"core.global_controller": "/repo/core/global_controller.lua"})
    assert resolve_inline_phase_handles([loc], resolver) == [
        ("/wisp", "content", "/repo/core/global_controller.lua")
    ]


def test_skips_file_phases_and_unresolved_requires():
    file_phase = NginxLuaPhase(
        directive="content_by_lua_file", phase="content", is_inline=False,
        lua_file="x.lua", inline_code=None, line=1,
    )
    inline_unresolved = NginxLuaPhase(
        directive="content_by_lua_block", phase="content", is_inline=True,
        lua_file=None, inline_code='require("does.not.exist")', line=2,
    )
    loc = NginxLocation(path="/a", modifier=None, line=1,
                        phases=[file_phase, inline_unresolved])
    assert resolve_inline_phase_handles([loc], _FakeResolver({})) == []
