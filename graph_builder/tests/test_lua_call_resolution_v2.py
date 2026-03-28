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
