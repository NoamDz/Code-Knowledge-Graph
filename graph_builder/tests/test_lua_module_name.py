"""Tests for Lua file -> require_version module-name derivation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.resolvers.lua_resolver import LuaResolver
from graph_builder.main import _assign_lua_module_names
from graph_builder.parsers.base import FileAST


def _resolver(tmp_path):
    return LuaResolver([], repo_root=str(tmp_path), source_roots=("src",))


def test_module_name_for_init_file(tmp_path):
    r = _resolver(tmp_path)
    p = str(tmp_path / "src" / "ato" / "collectors" / "ipp" / "init.lua")
    assert r.module_name_for_file(p) == "ato.collectors.ipp"


def test_module_name_for_plain_file(tmp_path):
    r = _resolver(tmp_path)
    p = str(tmp_path / "src" / "common" / "base" / "lua" / "store.lua")
    assert r.module_name_for_file(p) == "common.base.lua.store"


def test_module_name_strips_only_leading_source_root(tmp_path):
    # A 'src' segment deeper in the path must NOT be stripped; only the root one.
    r = _resolver(tmp_path)
    p = str(tmp_path / "src" / "lib" / "lua" / "context.lua")
    assert r.module_name_for_file(p) == "lib.lua.context"


def test_assign_lua_module_names_sets_on_ast(tmp_path):
    r = _resolver(tmp_path)
    fp = str(tmp_path / "src" / "ato" / "tasks" / "ipp.lua")
    ast = FileAST(file_path=fp, language="lua")
    _assign_lua_module_names({fp: ast}, r)
    assert ast.module_name == "ato.tasks.ipp"
