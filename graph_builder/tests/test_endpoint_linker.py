"""Tests for the cross-language endpoint linker.

Covers:
  - Exact nginx location match
  - Prefix match (URL longer than location path)
  - Longest prefix wins
  - Unix socket to Go handler match
  - No match for external URLs
  - build_go_handler_registry from AST warnings
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import FileAST, HttpCallRef, FunctionDef
from graph_builder.parsers.nginx_parser import NginxConfig, NginxLocation, NginxLuaPhase
from graph_builder.resolvers.endpoint_linker import EndpointLinker


def _make_nginx_config(locations):
    """Build a NginxConfig from a simple list of location dicts."""
    locs = []
    for loc in locations:
        phases = [NginxLuaPhase(
            directive="content_by_lua_block", phase=loc.get("phase", "content"),
            is_inline=False, lua_file=loc["lua_file"], inline_code=None, line=1,
        )]
        locs.append(NginxLocation(
            path=loc["path"], modifier=loc.get("modifier"), line=1, phases=phases,
        ))
    return NginxConfig(locations=locs, upstreams=[])


def _make_ast(file_path, language, http_calls=None, warnings=None, functions=None):
    """Build a minimal FileAST for testing."""
    return FileAST(
        file_path=file_path,
        language=language,
        http_calls=http_calls or [],
        warnings=warnings or [],
        functions=functions or [],
    )


# --- Exact match ---

def test_exact_location_match():
    """JS /api/assess -> nginx location /api/assess -> Lua handler."""
    nginx_cfg = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "/srv/lua/assess.lua"},
        {"path": "/api/other", "lua_file": "/srv/lua/other.lua"},
    ])
    linker = EndpointLinker(nginx_cfg)

    all_asts = {
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="/api/assess", method="POST",
                        function="submitAssessment", line=42),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 1
    link = links[0]
    assert link["source_file"] == "app.js"
    assert link["source_function"] == "submitAssessment"
    assert link["source_line"] == 42
    assert link["method"] == "POST"
    assert link["endpoint"] == "/api/assess"
    assert link["target_lua_file"] == "/srv/lua/assess.lua"


# --- Prefix match ---

def test_prefix_match():
    """/api/assess/result should match /api/assess (prefix)."""
    nginx_cfg = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "/srv/lua/assess.lua"},
    ])
    linker = EndpointLinker(nginx_cfg)

    all_asts = {
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="/api/assess/result", method="GET",
                        function="getResult", line=55),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 1
    assert links[0]["endpoint"] == "/api/assess/result"
    assert links[0]["target_lua_file"] == "/srv/lua/assess.lua"


# --- Longest prefix wins ---

def test_longest_prefix_wins():
    """/api/assess should match /api/assess, not /api."""
    nginx_cfg = _make_nginx_config([
        {"path": "/api", "lua_file": "/srv/lua/api_root.lua"},
        {"path": "/api/assess", "lua_file": "/srv/lua/assess.lua"},
    ])
    linker = EndpointLinker(nginx_cfg)

    all_asts = {
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="/api/assess", method="POST",
                        function="callAssess", line=10),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 1
    assert links[0]["target_lua_file"] == "/srv/lua/assess.lua"


# --- Unix socket to Go handler ---

def test_unix_socket_to_go():
    """unix:/tmp/model_prediction.sock -> Go handler file."""
    linker = EndpointLinker()  # no nginx config needed
    linker.register_go_handlers({
        "/tmp/model_prediction.sock": {
            "/predict": "/srv/go/predictor/main.go",
        },
    })

    all_asts = {
        "caller.lua": _make_ast("caller.lua", "lua", http_calls=[
            HttpCallRef(url_or_path="unix:/tmp/model_prediction.sock:/predict",
                        method="POST", function="call_prediction", line=20),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 1
    link = links[0]
    assert link["target_go_file"] == "/srv/go/predictor/main.go"
    assert link["socket"] == "/tmp/model_prediction.sock"
    assert link["endpoint"] == "/predict"


# --- No match for external URLs ---

def test_external_url_no_match():
    """External URLs (https://api.external.com/...) should not match."""
    nginx_cfg = _make_nginx_config([
        {"path": "/api/assess", "lua_file": "/srv/lua/assess.lua"},
    ])
    linker = EndpointLinker(nginx_cfg)

    all_asts = {
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="https://api.external.com/v1/data",
                        method="GET", function="fetchExternal", line=99),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 0


# --- build_go_handler_registry ---

def test_build_go_handler_registry():
    """Discovers Go unix socket handlers from AST warnings and http_calls."""
    linker = EndpointLinker()

    all_asts = {
        "/srv/go/predictor/main.go": _make_ast(
            "/srv/go/predictor/main.go", "go",
            warnings=["unix_socket:/tmp/model_prediction.sock"],
            http_calls=[
                HttpCallRef(url_or_path="/predict", method="POST",
                            function="handlePredict", line=30),
                HttpCallRef(url_or_path="/health", method="GET",
                            function="handleHealth", line=45),
            ],
        ),
        # Non-Go file should be ignored
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="/api/foo", method="GET",
                        function="callFoo", line=5),
        ]),
        # Go file without unix_socket warning should be ignored
        "/srv/go/utils/helper.go": _make_ast(
            "/srv/go/utils/helper.go", "go",
            http_calls=[
                HttpCallRef(url_or_path="/debug", method="GET",
                            function="handleDebug", line=10),
            ],
        ),
    }

    registry = linker.build_go_handler_registry(all_asts)

    assert "/tmp/model_prediction.sock" in registry
    handlers = registry["/tmp/model_prediction.sock"]
    assert handlers["/predict"] == "/srv/go/predictor/main.go"
    assert handlers["/health"] == "/srv/go/predictor/main.go"
    assert len(registry) == 1  # only one socket


# --- No nginx config (empty linker) ---

def test_no_nginx_config():
    """Linker with no nginx config should still work for socket matching."""
    linker = EndpointLinker()

    all_asts = {
        "app.js": _make_ast("app.js", "javascript", http_calls=[
            HttpCallRef(url_or_path="/api/assess", method="POST",
                        function="callAssess", line=10),
        ]),
    }

    links = linker.link_all(all_asts)
    assert len(links) == 0


# --- Full integration: build_go_handler_registry + link ---

def test_full_go_integration():
    """Build registry from ASTs, register, then link calls."""
    linker = EndpointLinker()

    go_ast = _make_ast(
        "/srv/go/svc/main.go", "go",
        warnings=["unix_socket:/tmp/svc.sock"],
        http_calls=[
            HttpCallRef(url_or_path="/process", method="POST",
                        function="handleProcess", line=15),
        ],
    )

    caller_ast = _make_ast(
        "worker.lua", "lua",
        http_calls=[
            HttpCallRef(url_or_path="unix:/tmp/svc.sock:/process",
                        method="POST", function="do_work", line=42),
        ],
    )

    all_asts = {
        "/srv/go/svc/main.go": go_ast,
        "worker.lua": caller_ast,
    }

    # Build and register
    registry = linker.build_go_handler_registry(all_asts)
    linker.register_go_handlers(registry)

    # Link
    links = linker.link_all(all_asts)
    assert len(links) == 1
    assert links[0]["source_file"] == "worker.lua"
    assert links[0]["target_go_file"] == "/srv/go/svc/main.go"
    assert links[0]["socket"] == "/tmp/svc.sock"
