"""Tests for require_version() tracking in Lua parser."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_require_version_in_imports():
    """require_version() calls should appear in ast.imports."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))
    mod_strings = [imp.module_string for imp in ast.imports]
    assert "common.base.lua.handler" in mod_strings
    assert "ato.helpers" in mod_strings
    assert "lib.lua.context" in mod_strings
    assert "lib.lua.store" in mod_strings


def test_require_version_bindings():
    """require_version() calls should populate local bindings."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))
    bindings = {imp.module_string: imp.local_binding for imp in ast.imports}
    assert bindings.get("common.base.lua.handler") == "base"
    assert bindings.get("ato.helpers") == "helpers"
    assert bindings.get("lib.lua.context") == "context"
    assert bindings.get("lib.lua.store") == "store"


def test_require_version_calls_resolved():
    """Calls on require_version'd modules should be resolved via binding map."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))
    helpers_calls = [c for c in ast.calls if c.callee_string == "helpers.do_thing"]
    assert len(helpers_calls) >= 1
    assert helpers_calls[0].resolved_module == "ato.helpers"

    store_calls = [c for c in ast.calls if c.callee_string == "store:get" or c.callee_string == "store.get"]
    assert len(store_calls) >= 1
    assert store_calls[0].resolved_module == "lib.lua.store"


def test_require_version_import_type():
    """require_version imports should have import_type='require_version'."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))
    rv_imports = [imp for imp in ast.imports if imp.module_string == "common.base.lua.handler"]
    assert len(rv_imports) == 1
    assert rv_imports[0].import_type == "require_version"


def test_plain_require_still_works():
    """Plain require() should still work alongside require_version()."""
    ast = parse_lua_file(str(FIXTURES / "require_version.lua"))
    ctx_imports = [imp for imp in ast.imports if imp.module_string == "lib.lua.context"]
    assert len(ctx_imports) == 1
    assert ctx_imports[0].import_type == "require"
    assert ctx_imports[0].local_binding == "context"
