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
