"""Tests for Lua call resolution v2 improvements.

Covers: local alias classification, store vector chains, store_object parameter,
base inheritance updates, and CallResolver self: guard fix.

Run with: python -m pytest graph_builder/tests/test_lua_call_resolution_v2.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from graph_builder.parsers.base import FileAST, CallRef, ImportRef, ModuleInfo, ModulePatternType, FunctionDef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ast(
    language: str = "lua",
    calls: list[CallRef] | None = None,
    file_path: str = "/test/file.lua",
    imports: list[ImportRef] | None = None,
    functions: list[FunctionDef] | None = None,
    module_info: ModuleInfo | None = None,
    local_aliases: list[tuple[str, str]] | None = None,
) -> FileAST:
    """Build a minimal FileAST with the given fields."""
    ast = FileAST(
        file_path=file_path,
        language=language,
        calls=calls or [],
        imports=imports or [],
        functions=functions or [],
        module_info=module_info,
    )
    if local_aliases is not None:
        ast.local_aliases = local_aliases
    return ast


def _make_call(callee: str, resolved_module: str | None = None) -> CallRef:
    """Build a minimal CallRef."""
    return CallRef(
        caller_function="<module>",
        callee_string=callee,
        line=1,
        resolved_module=resolved_module,
    )


# ---------------------------------------------------------------------------
# Task 1: FileAST.local_aliases field
# ---------------------------------------------------------------------------

class TestFileASTLocalAliases:
    def test_local_aliases_defaults_to_empty_list(self):
        """FileAST should have a local_aliases field defaulting to []."""
        ast = FileAST(file_path="/test.lua", language="lua")
        assert ast.local_aliases == []

    def test_local_aliases_stores_tuples(self):
        """local_aliases should accept a list of (name, rhs) tuples."""
        ast = FileAST(
            file_path="/test.lua",
            language="lua",
            local_aliases=[("format", "string.format"), ("encode", "cjson.encode")],
        )
        assert len(ast.local_aliases) == 2
        assert ast.local_aliases[0] == ("format", "string.format")
        assert ast.local_aliases[1] == ("encode", "cjson.encode")


from graph_builder.parsers.lua_parser import parse_lua_file

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


# ---------------------------------------------------------------------------
# Task 2: Lua parser populates local_aliases
# ---------------------------------------------------------------------------

class TestLuaParserLocalAliases:
    def test_single_alias(self):
        """local format = string.format should produce ('format', 'string.format')."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert "format" in alias_dict
        assert alias_dict["format"] == "string.format"

    def test_multi_assignment(self):
        """local gsub, match = string.gsub, string.match should produce both aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("gsub") == "string.gsub"
        assert alias_dict.get("match") == "string.match"

    def test_cjson_aliases(self):
        """local encode, decode = cjson.encode, cjson.decode should produce both aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("encode") == "cjson.encode"
        assert alias_dict.get("decode") == "cjson.decode"

    def test_non_field_access_excluded(self):
        """local x = func_call() should NOT appear in local_aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_names = [name for name, _ in ast.local_aliases]
        # M should not appear (it's assigned from base:new(), not a field access)
        assert "M" not in alias_names

    def test_custom_module_alias_included(self):
        """local my_func = some_module.do_thing should appear in local_aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        alias_dict = dict(ast.local_aliases)
        assert alias_dict.get("my_func") == "some_module.do_thing"

    def test_total_alias_count(self):
        """The fixture should produce exactly 8 aliases."""
        ast = parse_lua_file(str(FIXTURES / "alias_builtins.lua"))
        assert len(ast.local_aliases) == 8


from graph_builder.resolvers.builtin_classifier import BuiltinClassifier


# ---------------------------------------------------------------------------
# Task 3: BuiltinClassifier alias map support
# ---------------------------------------------------------------------------

class TestBuiltinClassifierAliases:
    def test_format_alias_classified_as_builtin(self):
        """format aliased from string.format should be classified as builtin."""
        call = _make_call("format")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "builtin"

    def test_encode_alias_classified_as_external(self):
        """encode aliased from cjson.encode should be classified as external."""
        call = _make_call("encode")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("encode", "cjson.encode")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "external"

    def test_multi_alias_all_classified(self):
        """Multiple aliases should all be classified correctly."""
        call_format = _make_call("format")
        call_insert = _make_call("insert")
        call_encode = _make_call("encode")
        ast = _make_ast(
            calls=[call_format, call_insert, call_encode],
            local_aliases=[
                ("format", "string.format"),
                ("insert", "table.insert"),
                ("encode", "cjson.encode"),
            ],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call_format.classification == "builtin"
        assert call_insert.classification == "builtin"
        assert call_encode.classification == "external"

    def test_custom_module_alias_stays_unresolved(self):
        """Alias from unknown module (not stdlib/external) stays truly_unresolved."""
        call = _make_call("my_func")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("my_func", "some_module.do_thing")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification == "truly_unresolved"

    def test_no_aliases_no_change(self):
        """Files without local_aliases should classify normally."""
        call = _make_call("format")
        ast = _make_ast(calls=[call])
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        # "format" is not in LUA_BUILTINS (it's a table method, not a global),
        # so without alias info it should be truly_unresolved
        assert call.classification == "truly_unresolved"

    def test_resolved_call_not_reclassified(self):
        """Calls already resolved should not be touched by alias classification."""
        call = _make_call("format", resolved_module="my.module")
        ast = _make_ast(
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        assert call.classification is None
        assert call.resolved_module == "my.module"

    def test_alias_stats_counted(self):
        """Alias-classified calls should appear in the correct stats buckets."""
        call_format = _make_call("format")
        call_encode = _make_call("encode")
        call_unknown = _make_call("mystery_func")
        ast = _make_ast(
            calls=[call_format, call_encode, call_unknown],
            local_aliases=[
                ("format", "string.format"),
                ("encode", "cjson.encode"),
            ],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.lua": ast})
        s = c.stats()
        assert s["builtin"] == 1
        assert s["external"] == 1
        assert s["truly_unresolved"] == 1

    def test_non_lua_files_ignore_aliases(self):
        """Python files should not use Lua local_aliases."""
        call = _make_call("format")
        ast = _make_ast(
            language="python",
            calls=[call],
            local_aliases=[("format", "string.format")],
        )
        c = BuiltinClassifier()
        c.classify_all({"/test/file.py": ast})
        # Python's "format" is a builtin, so it should be classified as builtin
        # regardless of local_aliases (which are Lua-only)
        assert call.classification == "builtin"
