"""Unit tests for nginx fallback + file-backed route linking (explain_flow B1/B2/B3)."""

from graph_builder.parsers.nginx_parser import (
    _clean_lua_path,
    resolve_file_phase_handles,
    extract_try_files_target,
    NginxLocation,
    NginxLuaPhase,
)


def test_clean_lua_path_strips_quotes_and_semicolon():
    assert _clean_lua_path('"/data/kashmir/pinpoint/core/router/main.lua"') == \
        "/data/kashmir/pinpoint/core/router/main.lua"
    assert _clean_lua_path("'/a/b.lua';") == "/a/b.lua"
    assert _clean_lua_path("core/controllers/x.lua") == "core/controllers/x.lua"
    assert _clean_lua_path('  "/a/b.lua" ;  ') == "/a/b.lua"


def test_resolves_file_phase_by_longest_suffix():
    phase = NginxLuaPhase(
        directive="rewrite_by_lua_file", phase="rewrite", is_inline=False,
        lua_file="/data/kashmir/pinpoint/core/router/main.lua", inline_code=None, line=1,
    )
    loc = NginxLocation(path="@router", modifier=None, line=1, phases=[phase])
    files = [
        "/Users/dev/pinpoint/src/core/router/main.lua",
        "/Users/dev/pinpoint/src/other/main.lua",
    ]
    assert resolve_file_phase_handles([loc], files) == [
        ("@router", "rewrite", "/Users/dev/pinpoint/src/core/router/main.lua")
    ]


def test_skips_inline_and_unresolvable_file_phases():
    inline = NginxLuaPhase(
        directive="content_by_lua_block", phase="content", is_inline=True,
        lua_file=None, inline_code='require("x")', line=1,
    )
    missing = NginxLuaPhase(
        directive="rewrite_by_lua_file", phase="rewrite", is_inline=False,
        lua_file="/nope/ghost.lua", inline_code=None, line=2,
    )
    loc = NginxLocation(path="/a", modifier=None, line=1, phases=[inline, missing])
    assert resolve_file_phase_handles([loc], ["/repo/src/real.lua"]) == []


def test_ambiguous_basename_is_skipped():
    phase = NginxLuaPhase(
        directive="content_by_lua_file", phase="content", is_inline=False,
        lua_file="/deploy/x.lua", inline_code=None, line=1,
    )
    loc = NginxLocation(path="/a", modifier=None, line=1, phases=[phase])
    # Two indexed files share the basename and tie on suffix length → no match.
    assert resolve_file_phase_handles([loc], ["/r/one/x.lua", "/r/two/x.lua"]) == []
