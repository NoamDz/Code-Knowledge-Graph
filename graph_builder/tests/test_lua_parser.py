"""Tests for the improved Lua parser against all fixture patterns."""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.base import ModulePatternType

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_module_M():
    """Test canonical _M module pattern."""
    ast = parse_lua_file(str(FIXTURES / "module_M.lua"))

    assert ast.module_info is not None
    assert ast.module_info.pattern_type == ModulePatternType.UNDERSCORE_M
    assert ast.module_info.table_var_name == "_M"

    # Should find 3 functions: validate_token, refresh_session, _check_expiry
    assert len(ast.functions) == 3, f"Expected 3 functions, got {len(ast.functions)}: {[f.name for f in ast.functions]}"

    # Exports should be validate_token and refresh_session
    assert "validate_token" in ast.exports, f"Missing validate_token in exports: {ast.exports}"
    assert "refresh_session" in ast.exports, f"Missing refresh_session in exports: {ast.exports}"
    assert "_check_expiry" not in ast.exports, "_check_expiry should not be exported"

    # Public vs local visibility
    pub_funcs = [f for f in ast.functions if f.visibility == "public"]
    local_funcs = [f for f in ast.functions if f.visibility == "local"]
    assert len(pub_funcs) == 2, f"Expected 2 public functions, got {len(pub_funcs)}"
    assert len(local_funcs) == 1, f"Expected 1 local function, got {len(local_funcs)}"

    # Imports
    assert len(ast.imports) == 2, f"Expected 2 imports, got {len(ast.imports)}"
    import_mods = {i.module_string for i in ast.imports}
    assert "resty.redis" in import_mods
    assert "cjson" in import_mods

    # Require-to-variable binding
    redis_import = [i for i in ast.imports if i.module_string == "resty.redis"][0]
    assert redis_import.local_binding == "redis", f"Expected binding 'redis', got '{redis_import.local_binding}'"

    print("  PASS: module_M.lua")


def test_module_m():
    """Test lowercase m module pattern."""
    ast = parse_lua_file(str(FIXTURES / "module_m.lua"))

    assert ast.module_info.pattern_type == ModulePatternType.LOWERCASE_M
    assert ast.module_info.table_var_name == "m"

    # Exports: handle_request, process, validate
    assert "handle_request" in ast.exports, f"Missing handle_request in exports: {ast.exports}"
    assert "process" in ast.exports, f"Missing process in exports: {ast.exports}"
    assert "validate" in ast.exports, f"Missing validate in exports: {ast.exports}"

    # internal_helper should NOT be exported
    assert "internal_helper" not in ast.exports

    # Check public/local
    pub_funcs = [f for f in ast.functions if f.visibility == "public"]
    assert len(pub_funcs) == 3, f"Expected 3 public, got {len(pub_funcs)}: {[f.name for f in pub_funcs]}"

    # Imports with bindings
    utils_imp = [i for i in ast.imports if i.module_string == "lib.utils"]
    assert len(utils_imp) == 1
    assert utils_imp[0].local_binding == "utils"

    # Should detect ngx.ctx write
    ctx_writes = [c for c in ast.ctx_accesses if c.access_type == "write"]
    assert len(ctx_writes) >= 1, f"Expected ctx writes, got {len(ctx_writes)}"
    assert any(c.field_name == "request_data" for c in ctx_writes), \
        f"Missing ngx.ctx.request_data write: {[(c.field_name, c.access_type) for c in ast.ctx_accesses]}"

    # Should detect pcall-wrapped call
    pcall_calls = [c for c in ast.calls if c.is_pcall_wrapped]
    assert len(pcall_calls) >= 1, f"Expected pcall-wrapped calls, got {len(pcall_calls)}"

    print("  PASS: module_m.lua")


def test_module_named():
    """Test named module table pattern (local auth = {})."""
    ast = parse_lua_file(str(FIXTURES / "module_named.lua"))

    assert ast.module_info.pattern_type == ModulePatternType.NAMED_TABLE
    assert ast.module_info.table_var_name == "auth"

    # Exports: verify, get_current_user, logout
    assert "verify" in ast.exports, f"Missing verify: {ast.exports}"
    assert "get_current_user" in ast.exports, f"Missing get_current_user: {ast.exports}"
    assert "logout" in ast.exports, f"Missing logout: {ast.exports}"

    # hash_token is local, should NOT be exported
    assert "hash_token" not in ast.exports

    # ngx.ctx accesses
    ctx_writes = [c for c in ast.ctx_accesses if c.access_type == "write"]
    ctx_reads = [c for c in ast.ctx_accesses if c.access_type == "read"]
    assert any(c.field_name == "user_id" for c in ctx_writes), \
        f"Missing ngx.ctx.user_id write: {[(c.field_name, c.access_type) for c in ast.ctx_accesses]}"
    assert any(c.field_name == "user_id" for c in ctx_reads), \
        f"Missing ngx.ctx.user_id read: {[(c.field_name, c.access_type) for c in ast.ctx_accesses]}"

    print("  PASS: module_named.lua")


def test_module_direct_return():
    """Test direct table return pattern."""
    ast = parse_lua_file(str(FIXTURES / "module_direct_return.lua"))

    assert ast.module_info.pattern_type == ModulePatternType.DIRECT_RETURN

    # Exports from the return table
    assert "fetch_url" in ast.exports, f"Missing fetch_url: {ast.exports}"
    assert "post_json" in ast.exports, f"Missing post_json: {ast.exports}"

    # Functions should exist
    func_names = [f.name for f in ast.functions]
    assert "fetch_url" in func_names, f"Missing fetch_url function: {func_names}"
    assert "post_json" in func_names, f"Missing post_json function: {func_names}"

    # Imports
    import_mods = {i.module_string for i in ast.imports}
    assert "resty.http" in import_mods

    print("  PASS: module_direct_return.lua")


def test_module_class():
    """Test metatable class pattern."""
    ast = parse_lua_file(str(FIXTURES / "module_class.lua"))

    # Should detect the return of the class table
    assert ast.module_info.pattern_type in (
        ModulePatternType.NAMED_TABLE,
        ModulePatternType.METATABLE_CLASS,
    ), f"Expected named/class pattern, got {ast.module_info.pattern_type}"

    # Functions: new, connect, send, close
    func_names = [f.name for f in ast.functions]
    assert any("new" in n for n in func_names), f"Missing 'new' in: {func_names}"
    assert any("connect" in n for n in func_names), f"Missing 'connect' in: {func_names}"
    assert any("send" in n for n in func_names), f"Missing 'send' in: {func_names}"
    assert any("close" in n for n in func_names), f"Missing 'close' in: {func_names}"

    # Method syntax detection
    method_funcs = [f for f in ast.functions if f.is_method]
    assert len(method_funcs) >= 3, f"Expected >= 3 methods (: syntax), got {len(method_funcs)}: {[(f.name, f.is_method) for f in ast.functions]}"

    # ngx.ctx access
    assert len(ast.ctx_accesses) >= 2, f"Expected ctx accesses, got {len(ast.ctx_accesses)}"

    print("  PASS: module_class.lua")


def test_module_complex():
    """Test complex OpenResty patterns: ngx.ctx, ngx.shared, pcall, dynamic require."""
    ast = parse_lua_file(str(FIXTURES / "module_complex.lua"))

    assert ast.module_info.pattern_type == ModulePatternType.LOWERCASE_M
    assert ast.module_info.table_var_name == "m"

    # Exports
    for name in ["check_rate_limit", "get_cached", "set_cached", "safe_process", "get_request_context"]:
        assert name in ast.exports, f"Missing export '{name}': {ast.exports}"

    # ngx.shared accesses
    assert len(ast.shared_dict_accesses) >= 1, \
        f"Expected shared dict accesses, got {len(ast.shared_dict_accesses)}"
    dict_names = {a.dict_name for a in ast.shared_dict_accesses}
    assert "rate_limit" in dict_names or "rate_limiter" in dict_names, \
        f"Missing rate_limit shared dict: {dict_names}"

    # ngx.ctx accesses
    ctx_fields = {a.field_name for a in ast.ctx_accesses}
    assert "rate_limited" in ctx_fields, f"Missing rate_limited ctx field: {ctx_fields}"
    assert "last_error" in ctx_fields, f"Missing last_error ctx field: {ctx_fields}"
    assert "user_id" in ctx_fields, f"Missing user_id ctx field: {ctx_fields}"

    # Dynamic require
    dynamic_imports = [i for i in ast.imports if i.is_dynamic]
    assert len(dynamic_imports) >= 1, f"Expected dynamic imports, got {len(dynamic_imports)}"
    assert len(ast.warnings) >= 1, f"Expected warnings about dynamic require"

    # pcall-wrapped calls
    pcall_calls = [c for c in ast.calls if c.is_pcall_wrapped]
    assert len(pcall_calls) >= 1, f"Expected pcall calls, got {len(pcall_calls)}"

    print("  PASS: module_complex.lua")


def run_all():
    tests = [
        test_module_M,
        test_module_m,
        test_module_named,
        test_module_direct_return,
        test_module_class,
        test_module_complex,
    ]

    passed = 0
    failed = 0
    errors = []

    print("\n=== Lua Parser Tests ===\n")
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"  FAIL: {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            errors.append((test.__name__, f"ERROR: {e}"))
            print(f"  ERROR: {test.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if errors:
        print(f"\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")
    print()
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
