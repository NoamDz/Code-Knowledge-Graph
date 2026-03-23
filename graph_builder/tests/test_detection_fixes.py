"""Tests for detection fixes based on product codebase investigation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.js_parser import parse_js_file
from graph_builder.parsers.lua_parser import parse_lua_file

JS_FIXTURES = Path(__file__).parent / "fixtures" / "js"
LUA_FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_container_send_request():
    """Container._sendRequest should be detected as HTTP call."""
    ast = parse_js_file(str(JS_FIXTURES / "container_send.js"))
    assert len(ast.http_calls) >= 3, f"Expected 3+ HTTP calls, got {len(ast.http_calls)}"

    urls = {h.url_or_path for h in ast.http_calls}
    assert "/api/assess" in urls
    assert "/api/get_devices" in urls
    assert "/api/backward" in urls

    methods = {h.method for h in ast.http_calls}
    assert "POST" in methods


def test_backward_communicator_alias():
    """backwardCommunicator._sendRequest should also be detected."""
    ast = parse_js_file(str(JS_FIXTURES / "container_send.js"))
    backward_calls = [h for h in ast.http_calls if h.url_or_path == "/api/backward"]
    assert len(backward_calls) >= 1


def test_lua_http_handler_post():
    """http_handler.post() should be detected as HTTP call."""
    ast = parse_lua_file(str(LUA_FIXTURES / "http_handler_caller.lua"))
    post_calls = [h for h in ast.http_calls if h.method == "POST"]
    assert len(post_calls) >= 1
    # Should capture unix socket path
    assert any("unix:" in h.url_or_path for h in post_calls)


def test_lua_http_handler_get():
    """http_handler.get() should be detected as HTTP call."""
    ast = parse_lua_file(str(LUA_FIXTURES / "http_handler_caller.lua"))
    get_calls = [h for h in ast.http_calls if h.method == "GET"]
    assert len(get_calls) >= 1


def test_lua_http_handler_total():
    """All http_handler calls should be detected."""
    ast = parse_lua_file(str(LUA_FIXTURES / "http_handler_caller.lua"))
    assert len(ast.http_calls) >= 3, f"Expected 3+ HTTP calls, got {len(ast.http_calls)}"
