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
