"""Tests for the new cross-service analysis features.

Covers:
  - Config loading (lua_package_paths)
  - nginx include following
  - Internal redirect detection (ngx.exec, ngx.location.capture)
  - Redis key tracking (Lua + Python)
  - HTTP call tracking (Lua + Python)
  - Python import resolver
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.parsers.js_parser import parse_js_file
from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.parsers.nginx_parser import parse_nginx_conf, parse_nginx_conf_recursive
from graph_builder.config import Config
from graph_builder.resolvers.python_resolver import PythonResolver
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions

FIXTURES = Path(__file__).parent / "fixtures"
LUA_FIXTURES = FIXTURES / "lua"
PY_FIXTURES = FIXTURES / "python"
JS_FIXTURES = FIXTURES / "js"
RB_FIXTURES = FIXTURES / "ruby"
GO_FIXTURES = FIXTURES / "go"
NGINX_FIXTURES = FIXTURES / "nginx_includes"


# --- Config loading ---

def test_config_lua_package_paths():
    """lua_package_paths from config.yml should be loaded."""
    config_path = Path(__file__).parent.parent.parent / "config_example.yml"
    if not config_path.exists():
        print("  SKIP: config_example.yml not found")
        return

    config = Config.from_yaml(str(config_path))
    assert hasattr(config, "lua_package_paths"), "Config missing lua_package_paths attribute"
    assert len(config.lua_package_paths) > 0, f"Expected lua_package_paths, got {config.lua_package_paths}"
    assert any("?.lua" in p for p in config.lua_package_paths), \
        f"Expected ?.lua patterns in {config.lua_package_paths}"
    print(f"  PASS: config loaded {len(config.lua_package_paths)} lua_package_paths")


def test_config_defaults():
    """Default config should have empty lua_package_paths."""
    config = Config.default()
    assert config.lua_package_paths == [], f"Expected empty, got {config.lua_package_paths}"
    assert config.nginx_base_path is None
    print("  PASS: config defaults correct")


# --- nginx include following ---

def test_nginx_includes():
    """Recursive nginx parser should follow include directives."""
    main_conf = NGINX_FIXTURES / "main.conf"
    if not main_conf.exists():
        print("  SKIP: nginx include fixture not found")
        return

    config = parse_nginx_conf_recursive(str(main_conf))

    # Should have locations from both included files
    location_paths = {loc.path for loc in config.locations}
    assert "/health" in location_paths, f"Missing /health in {location_paths}"
    assert "/api/users" in location_paths, f"Missing /api/users in {location_paths}"
    assert "/api/orders" in location_paths, f"Missing /api/orders in {location_paths}"
    assert "/internal/process" in location_paths, f"Missing /internal/process in {location_paths}"
    assert "/internal/fetch_data" in location_paths, f"Missing /internal/fetch_data in {location_paths}"

    # Should have shared dicts from both main and included
    dict_names = {d.name for d in config.shared_dicts}
    assert "main_cache" in dict_names, f"Missing main_cache in {dict_names}"
    assert "api_cache" in dict_names, f"Missing api_cache in {dict_names}"

    # Should have package path from main config
    assert len(config.lua_package_path) > 0, "Missing lua_package_path"

    print(f"  PASS: nginx includes — {len(config.locations)} locations, "
          f"{len(config.shared_dicts)} shared dicts")


def test_nginx_single_file_unchanged():
    """Single-file parser should still work as before."""
    conf = FIXTURES / "nginx.conf"
    if not conf.exists():
        print("  SKIP: nginx.conf fixture not found")
        return

    config = parse_nginx_conf(str(conf))
    assert len(config.locations) >= 4, f"Expected >= 4 locations, got {len(config.locations)}"
    print(f"  PASS: single-file nginx parse — {len(config.locations)} locations")


# --- Internal redirects ---

def test_internal_redirects():
    """Parser should detect ngx.exec and ngx.location.capture calls."""
    ast = parse_lua_file(str(LUA_FIXTURES / "internal_redirect.lua"))

    assert len(ast.internal_redirects) >= 3, \
        f"Expected >= 3 redirects, got {len(ast.internal_redirects)}: " \
        f"{[(r.target_path, r.redirect_type) for r in ast.internal_redirects]}"

    targets = {r.target_path for r in ast.internal_redirects}
    assert "/internal/process" in targets, f"Missing /internal/process in {targets}"
    assert "/internal/fetch_data" in targets, f"Missing /internal/fetch_data in {targets}"

    # capture_multi should produce multiple redirects
    types = {r.redirect_type for r in ast.internal_redirects}
    assert "exec" in types, f"Missing exec type in {types}"
    assert "capture" in types, f"Missing capture type in {types}"
    assert "capture_multi" in types, f"Missing capture_multi type in {types}"

    # Should be assigned to correct functions
    exec_redirect = [r for r in ast.internal_redirects if r.redirect_type == "exec"][0]
    assert exec_redirect.function == "_M.process_request", \
        f"Expected _M.process_request, got {exec_redirect.function}"

    print(f"  PASS: internal redirects — {len(ast.internal_redirects)} detected")


# --- Redis key tracking ---

def test_redis_lua():
    """Lua parser should detect Redis operations."""
    ast = parse_lua_file(str(LUA_FIXTURES / "redis_usage.lua"))

    assert len(ast.redis_accesses) >= 3, \
        f"Expected >= 3 Redis accesses, got {len(ast.redis_accesses)}: " \
        f"{[(r.key_name, r.operation) for r in ast.redis_accesses]}"

    ops = {r.operation for r in ast.redis_accesses}
    assert "get" in ops, f"Missing get in {ops}"
    assert "set" in ops, f"Missing set in {ops}"

    # Check read/write classification
    reads = [r for r in ast.redis_accesses if r.access_type == "read"]
    writes = [r for r in ast.redis_accesses if r.access_type == "write"]
    assert len(reads) >= 1, f"Expected >= 1 read, got {len(reads)}"
    assert len(writes) >= 1, f"Expected >= 1 write, got {len(writes)}"

    print(f"  PASS: Redis Lua — {len(ast.redis_accesses)} accesses "
          f"({len(reads)} reads, {len(writes)} writes)")


def test_redis_python():
    """Python parser should detect Redis operations."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_service.py"))

    assert len(ast.redis_accesses) >= 3, \
        f"Expected >= 3 Redis accesses, got {len(ast.redis_accesses)}: " \
        f"{[(r.key_name, r.operation) for r in ast.redis_accesses]}"

    ops = {r.operation for r in ast.redis_accesses}
    assert "get" in ops, f"Missing get in {ops}"
    assert "set" in ops, f"Missing set in {ops}"

    reads = [r for r in ast.redis_accesses if r.access_type == "read"]
    writes = [r for r in ast.redis_accesses if r.access_type == "write"]
    assert len(reads) >= 1, f"Expected reads, got {len(reads)}"
    assert len(writes) >= 1, f"Expected writes, got {len(writes)}"

    print(f"  PASS: Redis Python — {len(ast.redis_accesses)} accesses "
          f"({len(reads)} reads, {len(writes)} writes)")


# --- HTTP call tracking ---

def test_http_calls_lua():
    """Lua parser should detect HTTP client calls."""
    ast = parse_lua_file(str(LUA_FIXTURES / "http_calls.lua"))

    assert len(ast.http_calls) >= 2, \
        f"Expected >= 2 HTTP calls, got {len(ast.http_calls)}: " \
        f"{[(h.url_or_path, h.method) for h in ast.http_calls]}"

    urls = {h.url_or_path for h in ast.http_calls}
    assert any("python-svc" in u for u in urls), f"Missing python-svc call in {urls}"
    assert any("config-svc" in u for u in urls), f"Missing config-svc call in {urls}"

    print(f"  PASS: HTTP Lua — {len(ast.http_calls)} calls detected")


def test_http_calls_python():
    """Python parser should detect HTTP client calls."""
    ast = parse_python_file(str(PY_FIXTURES / "http_service.py"))

    assert len(ast.http_calls) >= 2, \
        f"Expected >= 2 HTTP calls, got {len(ast.http_calls)}: " \
        f"{[(h.url_or_path, h.method) for h in ast.http_calls]}"

    methods = {h.method for h in ast.http_calls}
    assert "POST" in methods, f"Missing POST in {methods}"
    assert "GET" in methods, f"Missing GET in {methods}"

    print(f"  PASS: HTTP Python — {len(ast.http_calls)} calls detected")


# --- Context module abstraction ---

def test_context_module():
    """Parser should detect context.get() abstraction over ngx.ctx."""
    ast = parse_lua_file(str(LUA_FIXTURES / "context_module.lua"))

    assert len(ast.ctx_accesses) >= 5, \
        f"Expected >= 5 context accesses, got {len(ast.ctx_accesses)}: " \
        f"{[(a.field_name, a.access_type, a.scope) for a in ast.ctx_accesses]}"

    # Check scoped field names
    field_names = {a.field_name for a in ast.ctx_accesses}
    assert any("tree" in f for f in field_names), f"Missing tree field in {field_names}"
    assert any("component" in f for f in field_names), f"Missing component field in {field_names}"
    assert any("is_deferrer" in f for f in field_names), f"Missing is_deferrer field in {field_names}"

    # Check scopes
    scopes = {a.scope for a in ast.ctx_accesses if a.scope}
    assert "global_config" in scopes, f"Missing global_config scope in {scopes}"

    # Check read/write detection
    writes = [a for a in ast.ctx_accesses if a.access_type == "write"]
    reads = [a for a in ast.ctx_accesses if a.access_type == "read"]
    assert len(writes) >= 3, f"Expected >= 3 writes, got {len(writes)}"
    assert len(reads) >= 2, f"Expected >= 2 reads, got {len(reads)}"

    print(f"  PASS: context module — {len(ast.ctx_accesses)} accesses "
          f"({len(writes)} writes, {len(reads)} reads), scopes: {scopes}")


# --- Python resolver ---

def test_python_resolver():
    """Python resolver should resolve imports to file paths."""
    resolver = PythonResolver(str(PY_FIXTURES.parent.parent.parent))

    # Should be able to resolve a module that exists in the repo
    # Test with the fixtures themselves
    resolved = resolver._resolve_absolute("graph_builder.parsers.base")
    if resolved:
        assert "base.py" in resolved, f"Expected base.py in {resolved}"
        print(f"  PASS: Python resolver — resolved graph_builder.parsers.base → {Path(resolved).name}")
    else:
        print("  SKIP: Python resolver — could not resolve in this directory structure")


# --- JS export patterns ---

def test_js_iife_exports():
    """JS parser should detect exports from IIFE / revealing module pattern."""
    ast = parse_js_file(str(JS_FIXTURES / "iife_module.js"))

    # Should detect exports from return { key: fn, ... }
    assert len(ast.exports) >= 3, \
        f"Expected >= 3 IIFE exports, got {len(ast.exports)}: {ast.exports}"

    assert "publicMethod" in ast.exports, f"Missing publicMethod in exports: {ast.exports}"
    assert "anotherPublic" in ast.exports, f"Missing anotherPublic in exports: {ast.exports}"
    assert "collect" in ast.exports, f"Missing collect in exports: {ast.exports}"

    # _helperPrivate should NOT be exported (not in the return object)
    assert "_helperPrivate" not in ast.exports, \
        f"_helperPrivate should not be exported: {ast.exports}"

    # Should detect HTTP call inside the IIFE
    assert len(ast.http_calls) >= 1, \
        f"Expected HTTP calls in IIFE, got {len(ast.http_calls)}"

    print(f"  PASS: JS IIFE exports — {len(ast.exports)} exports: {ast.exports}")


def test_js_export_patterns():
    """JS parser should detect exports.foo, module.exports.Foo patterns."""
    ast = parse_js_file(str(JS_FIXTURES / "export_patterns.js"))

    assert "processData" in ast.exports, f"Missing processData in exports: {ast.exports}"
    assert "formatOutput" in ast.exports, f"Missing formatOutput in exports: {ast.exports}"
    assert "DataCollector" in ast.exports, f"Missing DataCollector in exports: {ast.exports}"

    print(f"  PASS: JS export patterns — {len(ast.exports)} exports: {ast.exports}")


def test_js_erb():
    """JS parser should handle .js.erb files with ERB tags stripped."""
    ast = parse_js_file(str(JS_FIXTURES / "erb_template.js.erb"))

    # Should parse successfully despite ERB tags
    assert len(ast.functions) >= 1, \
        f"Expected >= 1 function, got {len(ast.functions)}: {[f.name for f in ast.functions]}"

    # Should detect module.exports = ClassName
    assert len(ast.exports) >= 1, f"Expected exports, got {ast.exports}"

    # Should detect HTTP calls (fetch, $.ajax, XMLHttpRequest.open)
    assert len(ast.http_calls) >= 1, \
        f"Expected >= 1 HTTP call, got {len(ast.http_calls)}: " \
        f"{[(h.url_or_path, h.method) for h in ast.http_calls]}"

    http_urls = {h.url_or_path for h in ast.http_calls}
    assert any("/api/" in u for u in http_urls), \
        f"Missing /api/ in HTTP call URLs: {http_urls}"

    print(f"  PASS: JS ERB — {len(ast.functions)} functions, {len(ast.exports)} exports, "
          f"{len(ast.http_calls)} HTTP calls")


# --- Ruby export patterns ---

def test_ruby_nested_modules():
    """Ruby parser should detect classes in deeply nested modules."""
    ast = parse_ruby_file(str(RB_FIXTURES / "nested_modules.rb"))

    # Should export full module paths
    assert "Malware::Generator::Preprocess::Active" in ast.exports, \
        f"Missing nested class export: {ast.exports}"
    assert "Malware::Generator::Preprocess::Passive" in ast.exports, \
        f"Missing nested class export: {ast.exports}"

    # Should export singleton methods with full path
    assert any("Active.process" in e for e in ast.exports), \
        f"Missing singleton method export: {ast.exports}"
    assert any("Active.validate" in e for e in ast.exports), \
        f"Missing singleton method export: {ast.exports}"

    print(f"  PASS: Ruby nested modules — exports: {ast.exports}")


def test_ruby_export_patterns():
    """Ruby parser should export class names, module names, and singleton methods."""
    ast = parse_ruby_file(str(RB_FIXTURES / "export_patterns.rb"))

    # Module name should be exported
    assert "Exportable" in ast.exports, f"Missing Exportable in exports: {ast.exports}"

    # Class names should be exported
    assert "BaseProcessor" in ast.exports, f"Missing BaseProcessor in exports: {ast.exports}"
    assert "SpecialProcessor" in ast.exports, f"Missing SpecialProcessor in exports: {ast.exports}"

    # Singleton methods (def self.method) should be exported
    singleton_exports = [e for e in ast.exports if "." in e]
    assert any("create" in e for e in singleton_exports), \
        f"Missing self.create in exports: {ast.exports}"

    # Private methods should NOT be exported
    assert "validate" not in ast.exports, f"validate should not be exported: {ast.exports}"
    assert "transform" not in ast.exports, f"transform should not be exported: {ast.exports}"

    print(f"  PASS: Ruby export patterns — {len(ast.exports)} exports: {ast.exports}")


# --- nginx proxy_pass ---

def test_nginx_proxy_pass():
    """nginx parser should detect proxy_pass and upstream blocks."""
    main_conf = NGINX_FIXTURES / "main.conf"
    if not main_conf.exists():
        print("  SKIP: nginx include fixture not found")
        return

    config = parse_nginx_conf_recursive(str(main_conf))

    # Should detect upstreams
    upstream_names = {u.name for u in config.upstreams}
    assert "go_backend" in upstream_names, f"Missing go_backend in upstreams: {upstream_names}"
    assert "python_backend" in upstream_names, f"Missing python_backend in upstreams: {upstream_names}"

    # go_backend should have unix socket server
    go_up = [u for u in config.upstreams if u.name == "go_backend"][0]
    assert any("unix:" in s for s in go_up.servers), \
        f"Expected unix socket in go_backend servers: {go_up.servers}"

    # Should detect proxy_pass in locations
    proxy_locs = [loc for loc in config.locations if loc.proxy_pass]
    assert len(proxy_locs) >= 2, \
        f"Expected >= 2 proxy_pass locations, got {len(proxy_locs)}"

    proxy_targets = {loc.proxy_pass.target for loc in proxy_locs}
    assert any("go_backend" in t for t in proxy_targets), \
        f"Missing go_backend proxy_pass: {proxy_targets}"

    print(f"  PASS: nginx proxy_pass — {len(config.upstreams)} upstreams, "
          f"{len(proxy_locs)} proxy_pass locations")


# --- Redis abstraction ---

def test_redis_abstraction():
    """Redis abstraction resolver should create RedisKeyAccess from store calls."""
    # Parse the fixture (now uses store instead of redis_helper)
    ast = parse_lua_file(str(LUA_FIXTURES / "redis_helper_caller.lua"))

    # Before resolution, this file has no direct redis accesses
    assert len(ast.redis_accesses) == 0, \
        f"Expected 0 direct redis accesses, got {len(ast.redis_accesses)}"

    # Run the abstraction resolver
    all_asts = {ast.file_path: ast}
    resolve_redis_abstractions(all_asts)

    # After resolution, should have redis accesses via abstraction:
    # store.get (read), store.set (write), store.exists (read),
    # store.hset (write), vector:add (write via store_vector)
    assert len(ast.redis_accesses) >= 4, \
        f"Expected >= 4 redis accesses via abstraction, got {len(ast.redis_accesses)}: " \
        f"{[(r.operation, r.access_type) for r in ast.redis_accesses]}"

    # Check read/write classification
    reads = [r for r in ast.redis_accesses if r.access_type == "read"]
    writes = [r for r in ast.redis_accesses if r.access_type == "write"]
    assert len(reads) >= 2, f"Expected >= 2 reads, got {len(reads)}"
    assert len(writes) >= 2, f"Expected >= 2 writes, got {len(writes)}"

    # Check specific operations are detected
    ops = {r.operation for r in ast.redis_accesses}
    assert "get" in ops, f"Missing get in operations: {ops}"
    assert "set" in ops, f"Missing set in operations: {ops}"
    assert "exists" in ops, f"Missing exists in operations: {ops}"
    assert "hset" in ops, f"Missing hset in operations: {ops}"

    # Keys should indicate abstraction
    assert all("<via " in r.key_name for r in ast.redis_accesses), \
        f"Expected <via ...> in key names"

    # Check that store_vector method (vector:add) is also detected
    vector_accesses = [r for r in ast.redis_accesses if "store_vector" in r.key_name]
    assert len(vector_accesses) >= 1, \
        f"Expected >= 1 store_vector access, got {len(vector_accesses)}: " \
        f"{[(r.operation, r.access_type) for r in ast.redis_accesses]}"

    print(f"  PASS: Redis abstraction — {len(ast.redis_accesses)} accesses "
          f"({len(reads)} reads, {len(writes)} writes), "
          f"including {len(vector_accesses)} store_vector accesses")


# --- IPC / pub-sub / HTTP socket / custom wrappers ---

def test_lua_ipc_detection():
    """Lua parser should detect file-based IPC and pub/sub patterns."""
    ast = parse_lua_file(str(LUA_FIXTURES / "ipc_patterns.lua"))

    # Should detect file IPC (io.open to /tmp/pinpoint_missions/)
    # Should detect HTTP client calls (resty.http connect + request)
    http_calls = ast.http_calls
    redis_accesses = ast.redis_accesses

    assert len(http_calls) >= 1, f"Expected HTTP calls, got {http_calls}"

    # Check for FILE_IPC detection
    ipc_calls = [h for h in http_calls if h.method == "FILE_IPC"]
    assert len(ipc_calls) >= 1, \
        f"Expected FILE_IPC calls, got {[(h.url_or_path, h.method) for h in http_calls]}"
    assert any("/tmp/pinpoint_missions/" in h.url_or_path for h in ipc_calls), \
        f"Expected /tmp/pinpoint_missions/ in IPC calls: {[(h.url_or_path, h.method) for h in ipc_calls]}"

    # Check for Unix socket connect detection
    unix_calls = [h for h in http_calls if h.method == "UNIX_CONNECT"]
    assert len(unix_calls) >= 1, \
        f"Expected UNIX_CONNECT calls, got {[(h.url_or_path, h.method) for h in http_calls]}"
    assert any("unix:" in h.url_or_path for h in unix_calls), \
        f"Expected unix: in socket calls: {[(h.url_or_path, h.method) for h in unix_calls]}"

    # Check for httpc:request({path=..., method=...}) detection
    request_calls = [h for h in http_calls if h.url_or_path == "/predict"]
    assert len(request_calls) >= 1, \
        f"Expected /predict request call, got {[(h.url_or_path, h.method) for h in http_calls]}"
    assert request_calls[0].method == "POST", \
        f"Expected POST method for /predict, got {request_calls[0].method}"

    print(f"  PASS: Lua IPC detection — {len(http_calls)} HTTP calls, "
          f"{len(redis_accesses)} Redis accesses")


def test_js_http_wrappers():
    """JS parser should detect sendRequest() and Net._request() as HTTP calls."""
    ast = parse_js_file(str(JS_FIXTURES / "http_wrappers.js"))

    assert len(ast.http_calls) >= 2, f"Expected >= 2 HTTP calls, got {len(ast.http_calls)}"
    urls = {h.url_or_path for h in ast.http_calls}
    assert "/api/collect" in urls, f"Missing /api/collect: {urls}"
    assert "/api/assess" in urls, f"Missing /api/assess: {urls}"

    # Check methods are correctly extracted
    methods_by_url = {h.url_or_path: h.method for h in ast.http_calls}
    assert methods_by_url.get("/api/collect") == "POST", \
        f"Expected POST for /api/collect, got {methods_by_url.get('/api/collect')}"
    assert methods_by_url.get("/api/assess") == "POST", \
        f"Expected POST for /api/assess, got {methods_by_url.get('/api/assess')}"

    print(f"  PASS: JS HTTP wrappers — {len(ast.http_calls)} calls detected: {urls}")


# --- Go parser ---

def test_go_parser():
    """Go parser should extract functions, structs, HTTP handlers, and unix sockets."""
    ast = parse_go_file(str(GO_FIXTURES / "http_handler.go"))

    # Package
    assert ast.module_name == "main", f"Expected package main, got {ast.module_name}"

    # Imports
    assert len(ast.imports) >= 5, f"Expected >= 5 imports, got {len(ast.imports)}"
    import_mods = {imp.module_string for imp in ast.imports}
    assert "net/http" in import_mods, f"Missing net/http in imports"
    assert "encoding/json" in import_mods, f"Missing encoding/json in imports"

    # Functions
    func_names = {f.name for f in ast.functions}
    assert "NewServer" in func_names, f"Missing NewServer: {func_names}"
    assert "main" in func_names, f"Missing main: {func_names}"

    # Methods with receiver types
    assert any("Server." in f.name for f in ast.functions), \
        f"Missing Server methods: {func_names}"

    # Structs
    class_names = {c.name for c in ast.classes}
    assert "Config" in class_names, f"Missing Config struct: {class_names}"
    assert "Server" in class_names, f"Missing Server struct: {class_names}"

    # Exports (uppercase)
    assert "NewServer" in ast.exports, f"NewServer should be exported"
    assert "Config" in ast.exports, f"Config should be exported"
    assert "main" not in ast.exports, f"main should not be exported"

    # HTTP handlers
    assert len(ast.http_calls) >= 1, f"Expected HTTP handlers: {ast.http_calls}"

    # Unix socket
    assert any("unix_socket:" in w for w in ast.warnings), \
        f"Expected unix socket warning: {ast.warnings}"

    print(f"  PASS: Go parser — {len(ast.functions)} functions, {len(ast.classes)} structs, "
          f"{len(ast.imports)} imports, {len(ast.http_calls)} HTTP handlers")


# --- Metatable inheritance ---

def test_lua_metatable_inheritance():
    """Lua parser should detect setmetatable-based inheritance from required modules."""
    ast = parse_lua_file(str(LUA_FIXTURES / "metatable_inheritance.lua"))

    # Should detect metatable parents for global_device, session_device, special_device
    assert len(ast.metatable_parents) >= 3, \
        f"Expected >= 3 metatable parents, got {len(ast.metatable_parents)}: {ast.metatable_parents}"

    # global_device inherits from base_model (via {__index = base_model})
    assert "global_device" in ast.metatable_parents, \
        f"Missing global_device in metatable_parents: {ast.metatable_parents}"
    assert ast.metatable_parents["global_device"] == "ato.models.base_model", \
        f"Expected ato.models.base_model, got {ast.metatable_parents['global_device']}"

    # session_device also inherits from base_model
    assert "session_device" in ast.metatable_parents, \
        f"Missing session_device in metatable_parents: {ast.metatable_parents}"
    assert ast.metatable_parents["session_device"] == "ato.models.base_model", \
        f"Expected ato.models.base_model, got {ast.metatable_parents['session_device']}"

    # special_device inherits from base_model (direct metatable pattern)
    assert "special_device" in ast.metatable_parents, \
        f"Missing special_device in metatable_parents: {ast.metatable_parents}"
    assert ast.metatable_parents["special_device"] == "ato.models.base_model", \
        f"Expected ato.models.base_model, got {ast.metatable_parents['special_device']}"

    # standalone should NOT be in metatable_parents (self-referential)
    assert "standalone" not in ast.metatable_parents, \
        f"standalone should not be in metatable_parents (self-referential): {ast.metatable_parents}"

    print(f"  PASS: metatable inheritance — {len(ast.metatable_parents)} parents detected: "
          f"{ast.metatable_parents}")


# --- Runner ---

def run_all():
    tests = [
        test_config_lua_package_paths,
        test_config_defaults,
        test_nginx_includes,
        test_nginx_single_file_unchanged,
        test_internal_redirects,
        test_redis_lua,
        test_redis_python,
        test_http_calls_lua,
        test_http_calls_python,
        test_context_module,
        test_python_resolver,
        test_js_iife_exports,
        test_js_export_patterns,
        test_js_erb,
        test_ruby_nested_modules,
        test_ruby_export_patterns,
        test_nginx_proxy_pass,
        test_redis_abstraction,
        test_go_parser,
        test_lua_ipc_detection,
        test_js_http_wrappers,
        test_lua_metatable_inheritance,
    ]

    passed = 0
    failed = 0
    skipped = 0
    errors = []

    print("\n=== New Feature Tests ===\n")
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
