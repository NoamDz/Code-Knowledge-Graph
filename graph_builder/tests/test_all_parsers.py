"""Comprehensive test suite for all parsers, nginx parser, and validation tools.

Run with: python graph_builder/tests/test_all_parsers.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.parsers.js_parser import parse_js_file
from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.parsers.nginx_parser import parse_nginx_conf
from graph_builder.parsers.base import ModulePatternType
from graph_builder.validate.spot_check import spot_check
from graph_builder.validate.coverage_report import run_coverage_report

FIXTURES = Path(__file__).parent / "fixtures"
LUA = FIXTURES / "lua"

passed = 0
failed = 0
errors = []


def check(condition, msg):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        errors.append(msg)
        print(f"    FAIL: {msg}")


def test_lua_M():
    ast = parse_lua_file(str(LUA / "module_M.lua"))
    check(ast.module_info.pattern_type == ModulePatternType.UNDERSCORE_M, "M: pattern should be _M")
    check(ast.module_info.table_var_name == "_M", "M: table var should be _M")
    check(len(ast.functions) == 3, f"M: expected 3 functions, got {len(ast.functions)}")
    check("validate_token" in ast.exports, "M: validate_token should be exported")
    check("refresh_session" in ast.exports, "M: refresh_session should be exported")
    check(len(ast.imports) == 2, f"M: expected 2 imports, got {len(ast.imports)}")
    redis_imp = [i for i in ast.imports if i.module_string == "resty.redis"]
    check(len(redis_imp) == 1 and redis_imp[0].local_binding == "redis",
          "M: require binding should be redis → resty.redis")
    resolved = [c for c in ast.calls if c.resolved_module == "resty.redis"]
    check(len(resolved) >= 1, "M: should resolve redis:new → resty.redis")


def test_lua_m():
    ast = parse_lua_file(str(LUA / "module_m.lua"))
    check(ast.module_info.pattern_type == ModulePatternType.LOWERCASE_M, "m: pattern should be m")
    check(set(ast.exports) >= {"handle_request", "process", "validate"}, f"m: exports wrong: {ast.exports}")
    check("internal_helper" not in ast.exports, "m: internal_helper should not be exported")
    pcall = [c for c in ast.calls if c.is_pcall_wrapped]
    check(len(pcall) >= 1, "m: should detect pcall-wrapped call")
    ctx_w = [c for c in ast.ctx_accesses if c.access_type == "write"]
    check(any(c.field_name == "request_data" for c in ctx_w), "m: should detect ngx.ctx.request_data write")


def test_lua_named():
    ast = parse_lua_file(str(LUA / "module_named.lua"))
    check(ast.module_info.pattern_type == ModulePatternType.NAMED_TABLE, "named: pattern should be named")
    check(ast.module_info.table_var_name == "auth", "named: table var should be auth")
    check("verify" in ast.exports, "named: verify should be exported")
    check("hash_token" not in ast.exports, "named: hash_token should not be exported")
    ctx_w = [c for c in ast.ctx_accesses if c.access_type == "write" and c.field_name == "user_id"]
    check(len(ctx_w) >= 1, "named: should detect ngx.ctx.user_id write")
    ctx_r = [c for c in ast.ctx_accesses if c.access_type == "read" and c.field_name == "user_id"]
    check(len(ctx_r) >= 1, "named: should detect ngx.ctx.user_id read")


def test_lua_direct_return():
    ast = parse_lua_file(str(LUA / "module_direct_return.lua"))
    check(ast.module_info.pattern_type == ModulePatternType.DIRECT_RETURN, "direct: pattern should be direct")
    check(set(ast.exports) >= {"fetch_url", "post_json"}, f"direct: exports wrong: {ast.exports}")
    check(len(ast.functions) == 2, f"direct: expected 2 functions, got {len(ast.functions)}")


def test_lua_class():
    ast = parse_lua_file(str(LUA / "module_class.lua"))
    check(ast.module_info.pattern_type in (ModulePatternType.NAMED_TABLE, ModulePatternType.METATABLE_CLASS),
          f"class: unexpected pattern {ast.module_info.pattern_type}")
    methods = [f for f in ast.functions if f.is_method]
    check(len(methods) >= 3, f"class: expected >= 3 methods, got {len(methods)}")
    check(len(ast.ctx_accesses) >= 2, "class: should detect ngx.ctx accesses")


def test_lua_complex():
    ast = parse_lua_file(str(LUA / "module_complex.lua"))
    check(len(ast.exports) == 5, f"complex: expected 5 exports, got {len(ast.exports)}")
    check(len(ast.shared_dict_accesses) >= 2, f"complex: expected shared dict accesses")
    dynamic = [i for i in ast.imports if i.is_dynamic]
    check(len(dynamic) >= 1, "complex: should detect dynamic require")
    check(len(ast.warnings) >= 1, "complex: should have warnings about dynamic require")
    ctx_fields = {c.field_name for c in ast.ctx_accesses}
    check("rate_limited" in ctx_fields, "complex: should detect ngx.ctx.rate_limited")
    check("user_id" in ctx_fields, "complex: should detect ngx.ctx.user_id")
    check("last_error" in ctx_fields, "complex: should detect ngx.ctx.last_error")


def test_python():
    ast = parse_python_file(str(FIXTURES / "python" / "payment_processor.py"))
    check(len(ast.classes) == 1, f"py: expected 1 class, got {len(ast.classes)}")
    check(ast.classes[0].name == "PaymentProcessor", "py: class name should be PaymentProcessor")
    check(ast.classes[0].parent_class == "BaseService", "py: parent should be BaseService")
    check(len(ast.imports) == 5, f"py: expected 5 imports, got {len(ast.imports)}")
    # Check relative import handling
    rel_imports = [i for i in ast.imports if i.module_string.startswith(".")]
    check(len(rel_imports) == 3, f"py: expected 3 relative imports, got {len(rel_imports)}")
    # No doubled paths
    for i in ast.imports:
        check(".." not in i.module_string.replace("..", "DOTDOT", 1).replace(".", ""),
              f"py: import path looks doubled: {i.module_string}")
    private = [f for f in ast.functions if f.visibility == "private"]
    check(len(private) == 2, f"py: expected 2 private methods, got {len(private)}")
    deco = [f for f in ast.functions if f.decorators]
    check(len(deco) == 1, f"py: expected 1 decorated function, got {len(deco)}")
    check(len(deco[0].decorators) == 1, f"py: decorator should not be duplicated")


def test_ruby():
    ast = parse_ruby_file(str(FIXTURES / "ruby" / "user_service.rb"))
    check(len(ast.classes) == 1, f"rb: expected 1 class, got {len(ast.classes)}")
    check(ast.classes[0].name == "UserService", "rb: class name")
    check(set(ast.classes[0].mixins) == {"AuthHelper", "Logging"}, f"rb: mixins = {ast.classes[0].mixins}")
    check(len(ast.imports) == 3, f"rb: expected 3 imports, got {len(ast.imports)}")
    req_rel = [i for i in ast.imports if i.import_type == "require_relative"]
    check(len(req_rel) == 2, f"rb: expected 2 require_relative")
    private = [f for f in ast.functions if f.visibility == "private"]
    check(len(private) == 2, f"rb: expected 2 private methods, got {len(private)}")
    # attr_reader creates implicit methods
    check(any(f.name == "repo" for f in ast.functions), "rb: attr_reader :repo should create method")
    check(any(f.name == "cache" for f in ast.functions), "rb: attr_reader :cache should create method")


def test_js():
    ast = parse_js_file(str(FIXTURES / "js" / "user_controller.js"))
    check(len(ast.classes) == 1, f"js: expected 1 class, got {len(ast.classes)}")
    check(ast.classes[0].name == "UserController", "js: class name")
    check(len(ast.imports) == 4, f"js: expected 4 imports, got {len(ast.imports)}")
    # Destructured import
    auth_imp = [i for i in ast.imports if i.module_string == "./auth"]
    check(len(auth_imp) == 1, "js: should have ./auth import")
    check("validateToken" in (auth_imp[0].local_binding or ""), "js: destructured import binding")
    # Arrow function
    check(any(f.name == "createRouter" for f in ast.functions), "js: createRouter arrow fn")
    # Exports
    check("UserController" in ast.exports, f"js: exports should include UserController: {ast.exports}")
    check("createRouter" in ast.exports, f"js: exports should include createRouter: {ast.exports}")
    # _bindRoutes should be private
    check(any(f.name == "_bindRoutes" and f.visibility == "private" for f in ast.functions),
          "js: _bindRoutes should be private")


def test_go():
    ast = parse_go_file(str(FIXTURES / "go" / "http_handler.go"))
    check(ast.module_name == "main", f"go: package should be main, got {ast.module_name}")
    check(len(ast.imports) >= 5, f"go: expected >= 5 imports, got {len(ast.imports)}")
    # Struct definitions
    struct_names = {c.name for c in ast.classes}
    check("Config" in struct_names, f"go: missing Config struct in {struct_names}")
    check("Server" in struct_names, f"go: missing Server struct in {struct_names}")
    # Functions
    func_names = {f.name for f in ast.functions}
    check("NewServer" in func_names, f"go: missing NewServer in {func_names}")
    check("main" in func_names, f"go: missing main in {func_names}")
    check("handleMetrics" in func_names, f"go: missing handleMetrics in {func_names}")
    # Methods with receivers
    check("Server.registerRoutes" in func_names or any("registerRoutes" in n for n in func_names),
          f"go: missing Server.registerRoutes in {func_names}")
    # Exports (uppercase)
    check("NewServer" in ast.exports, f"go: NewServer should be exported: {ast.exports}")
    check("Config" in ast.exports, f"go: Config should be exported: {ast.exports}")
    # HTTP handlers
    check(len(ast.http_calls) >= 1, f"go: expected HTTP handlers, got {len(ast.http_calls)}")
    handler_paths = {h.url_or_path for h in ast.http_calls}
    check("/api/health" in handler_paths or "/metrics" in handler_paths,
          f"go: missing handler paths in {handler_paths}")
    # Unix socket detection
    check(any("unix_socket:" in w for w in ast.warnings),
          f"go: should detect unix socket listener: {ast.warnings}")


def test_nginx():
    config = parse_nginx_conf(str(FIXTURES / "nginx.conf"))
    check(len(config.lua_package_path) == 2, f"nginx: expected 2 package paths, got {len(config.lua_package_path)}")
    check(any("?.lua" in p for p in config.lua_package_path), "nginx: should have ?.lua pattern")
    check(len(config.shared_dicts) == 3, f"nginx: expected 3 shared dicts, got {len(config.shared_dicts)}")
    dict_names = {sd.name for sd in config.shared_dicts}
    check(dict_names == {"rate_limit", "app_cache", "locks"}, f"nginx: shared dicts = {dict_names}")
    check(len(config.locations) >= 5, f"nginx: expected >= 5 locations, got {len(config.locations)}")
    check(len(config.global_phases) >= 2, f"nginx: expected >= 2 global phases, got {len(config.global_phases)}")
    # Check a specific location
    login_locs = [l for l in config.locations if "login" in l.path]
    check(len(login_locs) == 1, "nginx: should have /api/auth/login location")
    if login_locs:
        check(len(login_locs[0].phases) >= 2, "nginx: login should have access + content phases")


def test_spot_check_tool():
    result = spot_check(str(LUA / "module_named.lua"))
    check("auth" in result, "spot_check: should mention auth table")
    check("verify" in result, "spot_check: should mention verify export")
    check("ngx.ctx.user_id" in result, "spot_check: should mention ctx access")
    check("NAMED_TABLE" in result or "named" in result, "spot_check: should mention module pattern")


def test_coverage_report_tool():
    result = run_coverage_report(str(FIXTURES), nginx_conf=str(FIXTURES / "nginx.conf"))
    check("100.0%" in result, "coverage: all files should parse successfully")
    check("Functions:" in result, "coverage: should have function count")
    check("lua_package_path" in result, "coverage: should have nginx config info")
    check("LUA MODULE PATTERNS" in result, "coverage: should show pattern distribution")


def main():
    global passed, failed, errors

    tests = [
        ("Lua _M pattern", test_lua_M),
        ("Lua m pattern", test_lua_m),
        ("Lua named pattern", test_lua_named),
        ("Lua direct return", test_lua_direct_return),
        ("Lua class pattern", test_lua_class),
        ("Lua complex patterns", test_lua_complex),
        ("Python parser", test_python),
        ("Ruby parser", test_ruby),
        ("JavaScript parser", test_js),
        ("Go parser", test_go),
        ("nginx.conf parser", test_nginx),
        ("Spot-check tool", test_spot_check_tool),
        ("Coverage report tool", test_coverage_report_tool),
    ]

    print(f"\n{'='*60}")
    print(f"  Comprehensive Parser Test Suite")
    print(f"{'='*60}\n")

    for name, test_fn in tests:
        before = failed
        try:
            test_fn()
            if failed == before:
                print(f"  ✓ {name}")
            else:
                print(f"  ✗ {name} ({failed - before} checks failed)")
        except Exception as e:
            failed += 1
            errors.append(f"{name}: EXCEPTION: {e}")
            print(f"  ✗ {name}: EXCEPTION: {e}")

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print(f"\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
