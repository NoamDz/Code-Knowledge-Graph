"""Tests for the BuiltinClassifier.

Run with: python -m pytest graph_builder/tests/test_builtin_classifier.py -v
"""

from __future__ import annotations

import pytest

from graph_builder.parsers.base import FileAST, CallRef
from graph_builder.resolvers.builtin_classifier import BuiltinClassifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ast(language: str, calls: list[CallRef], file_path: str = "/test/file") -> FileAST:
    """Build a minimal FileAST with the given calls."""
    return FileAST(file_path=file_path, language=language, calls=calls)


def _make_call(callee: str, resolved_module: str | None = None) -> CallRef:
    """Build a minimal CallRef."""
    return CallRef(
        caller_function="<module>",
        callee_string=callee,
        line=1,
        resolved_module=resolved_module,
    )


# ---------------------------------------------------------------------------
# Lua
# ---------------------------------------------------------------------------

class TestLuaBuiltins:
    def test_print(self):
        c = BuiltinClassifier()
        assert c.classify_call("print", "lua") == "builtin"

    def test_pairs(self):
        c = BuiltinClassifier()
        assert c.classify_call("pairs", "lua") == "builtin"

    def test_tonumber(self):
        c = BuiltinClassifier()
        assert c.classify_call("tonumber", "lua") == "builtin"

    def test_pcall(self):
        c = BuiltinClassifier()
        assert c.classify_call("pcall", "lua") == "builtin"

    def test_setmetatable(self):
        c = BuiltinClassifier()
        assert c.classify_call("setmetatable", "lua") == "builtin"

    def test_ipairs(self):
        c = BuiltinClassifier()
        assert c.classify_call("ipairs", "lua") == "builtin"

    def test_require(self):
        c = BuiltinClassifier()
        assert c.classify_call("require", "lua") == "builtin"


class TestLuaStdlib:
    def test_string_format(self):
        c = BuiltinClassifier()
        assert c.classify_call("string.format", "lua") == "builtin"

    def test_table_insert(self):
        c = BuiltinClassifier()
        assert c.classify_call("table.insert", "lua") == "builtin"

    def test_math_floor(self):
        c = BuiltinClassifier()
        assert c.classify_call("math.floor", "lua") == "builtin"

    def test_os_time(self):
        c = BuiltinClassifier()
        assert c.classify_call("os.time", "lua") == "builtin"


class TestLuaOpenResty:
    def test_ngx_log(self):
        c = BuiltinClassifier()
        assert c.classify_call("ngx.log", "lua") == "builtin"

    def test_ngx_say(self):
        c = BuiltinClassifier()
        assert c.classify_call("ngx.say", "lua") == "builtin"

    def test_ngx_exit(self):
        c = BuiltinClassifier()
        assert c.classify_call("ngx.exit", "lua") == "builtin"

    def test_ngx_req_get_uri_args(self):
        c = BuiltinClassifier()
        assert c.classify_call("ngx.req.get_uri_args", "lua") == "builtin"

    def test_ndk_set_var(self):
        c = BuiltinClassifier()
        assert c.classify_call("ndk.set_var", "lua") == "builtin"


class TestLuaExternal:
    def test_cjson_encode(self):
        c = BuiltinClassifier()
        assert c.classify_call("cjson.encode", "lua") == "external"

    def test_cjson_decode(self):
        c = BuiltinClassifier()
        assert c.classify_call("cjson.decode", "lua") == "external"

    def test_resty_redis(self):
        c = BuiltinClassifier()
        assert c.classify_call("resty.redis", "lua") == "external"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

class TestPythonBuiltins:
    def test_print(self):
        c = BuiltinClassifier()
        assert c.classify_call("print", "python") == "builtin"

    def test_len(self):
        c = BuiltinClassifier()
        assert c.classify_call("len", "python") == "builtin"

    def test_isinstance(self):
        c = BuiltinClassifier()
        assert c.classify_call("isinstance", "python") == "builtin"

    def test_str(self):
        c = BuiltinClassifier()
        assert c.classify_call("str", "python") == "builtin"

    def test_os_path_join(self):
        c = BuiltinClassifier()
        assert c.classify_call("os.path.join", "python") == "builtin"


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

class TestGoBuiltins:
    def test_make(self):
        c = BuiltinClassifier()
        assert c.classify_call("make", "go") == "builtin"

    def test_len(self):
        c = BuiltinClassifier()
        assert c.classify_call("len", "go") == "builtin"

    def test_append(self):
        c = BuiltinClassifier()
        assert c.classify_call("append", "go") == "builtin"

    def test_fmt_println(self):
        c = BuiltinClassifier()
        assert c.classify_call("fmt.Println", "go") == "builtin"

    def test_http_listenandserve(self):
        c = BuiltinClassifier()
        assert c.classify_call("http.ListenAndServe", "go") == "builtin"


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

class TestJsBuiltins:
    def test_console_log(self):
        c = BuiltinClassifier()
        assert c.classify_call("console.log", "javascript") == "builtin"

    def test_json_parse(self):
        c = BuiltinClassifier()
        assert c.classify_call("JSON.parse", "javascript") == "builtin"

    def test_parseint(self):
        c = BuiltinClassifier()
        assert c.classify_call("parseInt", "javascript") == "builtin"

    def test_settimeout(self):
        c = BuiltinClassifier()
        assert c.classify_call("setTimeout", "javascript") == "builtin"

    def test_document_queryselector(self):
        c = BuiltinClassifier()
        assert c.classify_call("document.querySelector", "javascript") == "builtin"


# ---------------------------------------------------------------------------
# Ruby
# ---------------------------------------------------------------------------

class TestRubyBuiltins:
    def test_puts(self):
        c = BuiltinClassifier()
        assert c.classify_call("puts", "ruby") == "builtin"

    def test_raise(self):
        c = BuiltinClassifier()
        assert c.classify_call("raise", "ruby") == "builtin"

    def test_require(self):
        c = BuiltinClassifier()
        assert c.classify_call("require", "ruby") == "builtin"

    def test_file_read(self):
        c = BuiltinClassifier()
        assert c.classify_call("File.read", "ruby") == "builtin"


# ---------------------------------------------------------------------------
# Resolved calls should not be classified
# ---------------------------------------------------------------------------

class TestResolvedCallsSkipped:
    def test_resolved_call_stays_none(self):
        """Calls with resolved_module should not be classified."""
        call = _make_call("some_func", resolved_module="my_module")
        ast = _make_ast("lua", [call])
        c = BuiltinClassifier()
        c.classify_all({"/test/file": ast})
        assert call.classification is None

    def test_resolved_call_counted(self):
        """Resolved calls should appear in already_resolved count."""
        call = _make_call("some_func", resolved_module="my_module")
        ast = _make_ast("lua", [call])
        c = BuiltinClassifier()
        c.classify_all({"/test/file": ast})
        assert c.stats()["already_resolved"] == 1


# ---------------------------------------------------------------------------
# Truly unresolved
# ---------------------------------------------------------------------------

class TestTrulyUnresolved:
    def test_unknown_lua_call(self):
        c = BuiltinClassifier()
        assert c.classify_call("my_custom_func", "lua") == "truly_unresolved"

    def test_unknown_python_call(self):
        c = BuiltinClassifier()
        assert c.classify_call("some_random_function", "python") == "truly_unresolved"

    def test_unknown_language(self):
        c = BuiltinClassifier()
        assert c.classify_call("anything", "cobol") == "truly_unresolved"


# ---------------------------------------------------------------------------
# stats() method
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_returns_counts(self):
        calls = [
            _make_call("print"),                              # builtin
            _make_call("cjson.encode"),                       # external
            _make_call("my_func"),                            # truly_unresolved
            _make_call("string.format"),                      # builtin
            _make_call("redis_helper", resolved_module="m"),  # already_resolved
        ]
        ast = _make_ast("lua", calls)
        c = BuiltinClassifier()
        c.classify_all({"/test/file": ast})
        s = c.stats()
        assert s["builtin"] == 2
        assert s["external"] == 1
        assert s["truly_unresolved"] == 1
        assert s["already_resolved"] == 1

    def test_stats_empty(self):
        c = BuiltinClassifier()
        c.classify_all({})
        s = c.stats()
        assert s["builtin"] == 0
        assert s["external"] == 0
        assert s["truly_unresolved"] == 0
        assert s["already_resolved"] == 0

    def test_classify_all_modifies_in_place(self):
        call_print = _make_call("print")
        call_cjson = _make_call("cjson.encode")
        call_unknown = _make_call("my_func")
        ast = _make_ast("lua", [call_print, call_cjson, call_unknown])
        c = BuiltinClassifier()
        c.classify_all({"/test/file": ast})
        assert call_print.classification == "builtin"
        assert call_cjson.classification == "external"
        assert call_unknown.classification == "truly_unresolved"

    def test_multi_language(self):
        """Test classification across multiple languages in one pass."""
        lua_calls = [_make_call("print"), _make_call("ngx.say")]
        py_calls = [_make_call("len"), _make_call("os.path.join")]
        go_calls = [_make_call("fmt.Println"), _make_call("make")]
        js_calls = [_make_call("console.log"), _make_call("parseInt")]

        asts = {
            "/test/lua_file": _make_ast("lua", lua_calls, "/test/lua_file"),
            "/test/py_file": _make_ast("python", py_calls, "/test/py_file"),
            "/test/go_file": _make_ast("go", go_calls, "/test/go_file"),
            "/test/js_file": _make_ast("javascript", js_calls, "/test/js_file"),
        }
        c = BuiltinClassifier()
        c.classify_all(asts)
        s = c.stats()
        assert s["builtin"] == 8
        assert s["external"] == 0
        assert s["truly_unresolved"] == 0
