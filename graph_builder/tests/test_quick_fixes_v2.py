"""Tests for the quick-fixes-v2 bundle (Tasks 1-7).

Run with: python -m pytest graph_builder/tests/test_quick_fixes_v2.py -v
"""
from __future__ import annotations

import sys
import inspect
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import (
    FileAST, FunctionDef, ImportRef, CallRef, ContextAccess, ClassDef, ModuleInfo, ModulePatternType,
)
from graph_builder.ingestion.writer import GraphWriter

LUA_FIXTURES = Path(__file__).parent / "fixtures" / "lua"
PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"
GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"
RUBY_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"


# ───────────────────────────────────────────────────────────────
# Task 1: Missing edge properties
# ───────────────────────────────────────────────────────────────

class TestEdgeProperties:
    """Test that extracted-but-not-written properties are now written."""

    def _make_writer(self):
        """Create a GraphWriter with mocked driver (no Memgraph needed)."""
        with patch("graph_builder.ingestion.writer.GraphDatabase"):
            writer = GraphWriter(uri="bolt://fake:7687")
            writer._run = MagicMock()
            # Track buffered items directly
            return writer

    def test_1a_resolved_call_has_classification_and_confidence(self):
        """Resolved CALLS edges should include classification and resolution_confidence."""
        writer = self._make_writer()

        ast = FileAST(
            file_path="/repo/handler.lua", language="lua",
            calls=[
                CallRef(
                    caller_function="M:process",
                    callee_string="redis.get",
                    line=10,
                    resolved_module="resty.redis",
                    resolved_function="get",
                    resolved_file_path="/repo/lib/redis.lua",
                    resolution_confidence="binding",
                    classification=None,
                ),
            ],
        )
        resolved_imports = {"resty.redis": "/repo/lib/redis.lua"}
        writer.ingest_file_ast(ast, resolved_imports)
        writer.flush_all()

        # Check that CALLS_resolved buffer included confidence and classification
        # The edge template must have resolution_confidence and classification fields
        query = writer._edge_queries["CALLS_resolved"]
        assert "resolution_confidence" in query, \
            "CALLS_resolved query template missing resolution_confidence"
        assert "classification" in query, \
            "CALLS_resolved query template missing classification"

    def test_1b_imports_edge_has_local_binding(self):
        """IMPORTS edges should include local_binding property."""
        writer = self._make_writer()
        query = writer._edge_queries["IMPORTS"]
        assert "local_binding" in query, \
            "IMPORTS query template missing local_binding"

    def test_1c_function_node_has_decorators(self):
        """Function nodes should include decorators list property."""
        writer = self._make_writer()
        query = writer._node_queries["Function"]
        assert "decorators" in query, \
            "Function node query template missing decorators"

    def test_1d_class_node_has_is_interface(self):
        """Class nodes should include is_interface boolean property."""
        writer = self._make_writer()
        query = writer._node_queries["Class"]
        assert "is_interface" in query, \
            "Class node query template missing is_interface"

    def test_1e_metatable_inheritance_method_exists(self):
        """GraphWriter should have upsert_metatable_inheritance method."""
        writer = self._make_writer()
        assert hasattr(writer, "upsert_metatable_inheritance"), \
            "GraphWriter missing upsert_metatable_inheritance method"

    def test_1f_ctx_access_has_scope(self):
        """CTX_READS/CTX_WRITES edges should include scope property."""
        writer = self._make_writer()
        # upsert_ctx_access should accept scope parameter
        sig = inspect.signature(writer.upsert_ctx_access)
        assert "scope" in sig.parameters, \
            "upsert_ctx_access missing scope parameter"

    def test_1g_metatable_ingestion_creates_edge(self):
        """ingest_file_ast should create INHERITS_VIA_METATABLE edges from metatable_parents."""
        writer = self._make_writer()

        ast = FileAST(
            file_path="/repo/child.lua", language="lua",
            module_name="handlers.child",
            metatable_parents={"_M": "common.base.lua.handler"},
        )
        writer.ingest_file_ast(ast, {})
        writer.flush_all()

        # Check that _run was called with a query containing INHERITS_VIA_METATABLE
        calls = writer._run.call_args_list
        meta_calls = [c for c in calls if "INHERITS_VIA_METATABLE" in str(c)]
        assert len(meta_calls) >= 1, (
            f"Expected INHERITS_VIA_METATABLE edge creation, got calls: "
            f"{[str(c)[:80] for c in calls]}"
        )


# ───────────────────────────────────────────────────────────────
# Task 2: Dynamic prefix boundary matching
# ───────────────────────────────────────────────────────────────

try:
    from graph_builder.resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes, _is_prefix_match
except ImportError:
    resolve_dynamic_prefixes = None
    _is_prefix_match = None


class TestDynamicPrefixBoundary:
    """Test that prefix matching respects namespace boundaries."""

    def test_exact_prefix_match(self):
        """'handlers.' should match 'ato.handlers.auth'."""
        assert _is_prefix_match("handlers.", "ato.handlers.auth") is True

    def test_prefix_at_start(self):
        """'handlers.' should match 'handlers.auth'."""
        assert _is_prefix_match("handlers.", "handlers.auth") is True

    def test_substring_false_positive_rejected(self):
        """'handler.' should NOT match 'my_handler_utils'."""
        assert _is_prefix_match("handler.", "my_handler_utils") is False

    def test_tasks_prefix_match(self):
        """'tasks.' should match 'ato.tasks.pts_run'."""
        assert _is_prefix_match("tasks.", "ato.tasks.pts_run") is True

    def test_tasks_prefix_no_false_positive(self):
        """'tasks.' should NOT match 'multitask_runner'."""
        assert _is_prefix_match("tasks.", "multitask_runner") is False

    def test_multi_segment_prefix(self):
        """'common.base.' should match 'ato.common.base.handler'."""
        assert _is_prefix_match("common.base.", "ato.common.base.handler") is True

    def test_multi_segment_no_match(self):
        """'common.base.' should NOT match 'uncommon.base.handler'."""
        assert _is_prefix_match("common.base.", "uncommon.base.handler") is False

    def test_single_segment_prefix(self):
        """'redis' should match 'redis' exactly."""
        assert _is_prefix_match("redis", "redis") is True

    def test_prefix_without_trailing_dot(self):
        """'handlers' (no trailing dot) should match 'handlers.auth'."""
        assert _is_prefix_match("handlers", "ato.handlers.auth") is True

    def test_full_integration_no_false_positives(self):
        """End-to-end: dynamic import with prefix should not produce false positives."""
        from graph_builder.parsers.base import FileAST, ImportRef

        source_ast = FileAST(
            file_path="/repo/dispatcher.lua", language="lua",
            imports=[ImportRef(
                module_string="handlers.*",
                line=5,
                import_type="require",
                is_dynamic=True,
                static_prefix="handlers.",
            )],
        )
        # True match: module name contains "handlers" as a full segment
        good_target = FileAST(
            file_path="/repo/handlers/auth.lua", language="lua",
            module_name="ato.handlers.auth",
        )
        # False positive: "handler" is a substring, not a segment
        bad_target = FileAST(
            file_path="/repo/my_handler_utils.lua", language="lua",
            module_name="my_handler_utils",
        )

        all_asts = {
            "/repo/dispatcher.lua": source_ast,
            "/repo/handlers/auth.lua": good_target,
            "/repo/my_handler_utils.lua": bad_target,
        }
        edges, stats = resolve_dynamic_prefixes(all_asts)

        targets = {e["target_file"] for e in edges}
        assert "/repo/handlers/auth.lua" in targets, "Should match ato.handlers.auth"
        assert "/repo/my_handler_utils.lua" not in targets, \
            "Should NOT match my_handler_utils (false positive)"

    def test_resolve_returns_stats(self):
        """resolve_dynamic_prefixes should return (edges, stats) tuple."""
        all_asts = {}
        result = resolve_dynamic_prefixes(all_asts)
        # After change, should be (edges, stats) tuple
        assert isinstance(result, tuple), "Should return (edges, stats) tuple"
        edges, stats = result
        assert isinstance(edges, list)
        assert isinstance(stats, dict)


# ───────────────────────────────────────────────────────────────
# Task 3: Auto-detect base module methods
# ───────────────────────────────────────────────────────────────

try:
    from graph_builder.resolvers.base_inheritance_resolver import (
        resolve_base_inheritance, BASE_MODULE_METHODS,
    )
    from graph_builder.parsers.lua_parser import parse_lua_file
except ImportError:
    resolve_base_inheritance = None
    BASE_MODULE_METHODS = None
    parse_lua_file = None


class TestBaseModuleAutoDetection:
    """Test auto-detection of base module methods from ASTs."""

    def test_auto_detect_finds_base_handler_methods(self):
        """_auto_detect_base_modules should extract public methods from base module ASTs."""
        from graph_builder.resolvers.base_inheritance_resolver import _auto_detect_base_modules

        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        # Simulate the module_name that would be assigned during full build
        base_ast.module_name = "common.base.lua.handler"

        all_asts = {str(LUA_FIXTURES / "base_handler.lua"): base_ast}
        detected = _auto_detect_base_modules(all_asts)

        assert "common.base.lua.handler" in detected, \
            f"Should detect common.base.lua.handler, got: {list(detected.keys())}"
        methods = detected["common.base.lua.handler"]
        assert "validate" in methods, f"Should detect 'validate', got: {methods}"
        assert "dispatch" in methods, f"Should detect 'dispatch', got: {methods}"
        assert "handle_web_request" in methods
        assert "add_handler_error" in methods
        assert "parse_postdata" in methods

    def test_auto_detect_excludes_private_helpers(self):
        """Private/local functions should not appear in auto-detected methods."""
        from graph_builder.resolvers.base_inheritance_resolver import _auto_detect_base_modules

        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        base_ast.module_name = "common.base.lua.handler"

        all_asts = {str(LUA_FIXTURES / "base_handler.lua"): base_ast}
        detected = _auto_detect_base_modules(all_asts)
        methods = detected.get("common.base.lua.handler", set())
        assert "_internal_helper" not in methods, \
            "Private helper should not be in detected methods"

    def test_auto_detect_used_in_resolution(self):
        """resolve_base_inheritance should use auto-detected methods for resolution."""
        base_ast = parse_lua_file(str(LUA_FIXTURES / "base_handler.lua"))
        base_ast.module_name = "common.base.lua.handler"

        child_ast = parse_lua_file(str(LUA_FIXTURES / "child_handler.lua"))
        child_ast.module_name = "handlers.child"

        all_asts = {
            str(LUA_FIXTURES / "base_handler.lua"): base_ast,
            str(LUA_FIXTURES / "child_handler.lua"): child_ast,
        }
        resolved = resolve_base_inheritance(all_asts)
        assert resolved > 0, "Should resolve at least one base-inherited call"

        # Check that self:validate was resolved to base
        validate_calls = [c for c in child_ast.calls
                         if "validate" in c.callee_string
                         and c.resolved_module == "common.base.lua.handler"]
        assert len(validate_calls) >= 1, \
            f"self:validate should resolve to base handler, got: {[(c.callee_string, c.resolved_module) for c in child_ast.calls]}"

    def test_hardcoded_fallback_used_when_no_ast(self):
        """When base module ASTs are not in all_asts, hardcoded fallback should work."""
        child_ast = parse_lua_file(str(LUA_FIXTURES / "child_handler.lua"))
        child_ast.module_name = "handlers.child"

        # Only child AST, no base AST -- should fall back to hardcoded
        all_asts = {str(LUA_FIXTURES / "child_handler.lua"): child_ast}
        resolved = resolve_base_inheritance(all_asts)
        assert resolved > 0, "Hardcoded fallback should resolve base-inherited calls"


from graph_builder.resolvers.python_resolver import PythonResolver


# ---------------------------------------------------------------
# Task 4: Python package root detection + stdlib classification
# ---------------------------------------------------------------

class TestPythonResolver:
    """Test Python package root detection and stdlib classification."""

    def test_is_stdlib_recognizes_common_modules(self):
        """is_stdlib should recognize os, sys, json, logging, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os") is True
        assert resolver.is_stdlib("sys") is True
        assert resolver.is_stdlib("json") is True
        assert resolver.is_stdlib("logging") is True
        assert resolver.is_stdlib("collections") is True
        assert resolver.is_stdlib("pathlib") is True
        assert resolver.is_stdlib("typing") is True
        assert resolver.is_stdlib("datetime") is True
        assert resolver.is_stdlib("re") is True
        assert resolver.is_stdlib("unittest") is True

    def test_is_stdlib_rejects_third_party(self):
        """is_stdlib should reject known third-party packages."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("flask") is False
        assert resolver.is_stdlib("django") is False
        assert resolver.is_stdlib("requests") is False
        assert resolver.is_stdlib("numpy") is False
        assert resolver.is_stdlib("boto3") is False

    def test_is_stdlib_handles_submodules(self):
        """is_stdlib should recognize os.path, collections.abc, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os.path") is True
        assert resolver.is_stdlib("collections.abc") is True
        assert resolver.is_stdlib("http.server") is True
        assert resolver.is_stdlib("urllib.parse") is True
        assert resolver.is_stdlib("email.mime.text") is True

    def test_find_package_roots(self):
        """_find_package_roots should detect nested_pkg as a package root."""
        resolver = PythonResolver(str(PY_FIXTURES))
        roots = resolver._find_package_roots()
        # nested_pkg/ contains __init__.py, so it should be detected
        root_dirs = {str(v) for v in roots.values()}
        nested_pkg_dir = str((PY_FIXTURES / "nested_pkg").resolve())
        has_nested = any(nested_pkg_dir in d for d in root_dirs)
        assert has_nested, f"Should detect nested_pkg as package root, got: {root_dirs}"

    def test_package_root_resolution(self):
        """Absolute import 'services.models' should resolve relative to package root."""
        resolver = PythonResolver(str(PY_FIXTURES / "nested_pkg"))
        handler_file = str(PY_FIXTURES / "nested_pkg" / "services" / "handler.py")
        result = resolver.resolve("services.models", handler_file)
        assert result is not None, "services.models should resolve within nested_pkg"
        assert "models.py" in result

    def test_resolver_stats_include_package_roots(self):
        """stats() should include package_roots count."""
        resolver = PythonResolver(str(PY_FIXTURES))
        stats = resolver.stats()
        assert "package_roots" in stats, f"stats should include package_roots, got: {stats}"


from graph_builder.resolvers.go_resolver import GoResolver


# ---------------------------------------------------------------
# Task 5: Go go.mod parsing
# ---------------------------------------------------------------

class TestGoModParsing:
    """Test go.mod parsing and module prefix stripping."""

    def test_parse_go_mod_extracts_module_name(self):
        """GoResolver should parse go.mod and extract 'pp-consumer' module name."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver._module_name == "pp-consumer", \
            f"Expected module name 'pp-consumer', got: {resolver._module_name}"

    def test_internal_import_resolves_with_module_prefix(self):
        """'pp-consumer/common' should resolve by stripping module prefix."""
        resolver = GoResolver(str(GO_FIXTURES))
        result = resolver.resolve("pp-consumer/common")
        assert result is not None, \
            "'pp-consumer/common' should resolve to common/utils.go"
        assert "common" in result

    def test_internal_import_without_module_prefix_still_works(self):
        """'common' should still resolve via suffix matching."""
        resolver = GoResolver(str(GO_FIXTURES))
        result = resolver.resolve("common")
        assert result is not None, "'common' should resolve via suffix matching"

    def test_external_dep_classified(self):
        """External dependencies from go.mod require block should be classified."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("github.com/aws/aws-sdk-go") is True
        assert resolver.is_external("github.com/redis/go-redis/v9") is True
        assert resolver.is_external("github.com/stretchr/testify") is True

    def test_internal_not_classified_as_external(self):
        """Internal imports should not be classified as external."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("pp-consumer/common") is False
        assert resolver.is_external("common") is False

    def test_stdlib_not_classified_as_external(self):
        """Stdlib imports should not be classified as external."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver.is_external("fmt") is False
        assert resolver.is_external("net/http") is False

    def test_go_mod_root_detected(self):
        """The Go project root should be the directory containing go.mod."""
        resolver = GoResolver(str(GO_FIXTURES))
        assert resolver._go_project_root is not None
        assert resolver._go_project_root == str(Path(GO_FIXTURES).resolve()), \
            f"Go project root should be fixtures dir, got: {resolver._go_project_root}"

    def test_stats_include_module_name(self):
        """stats() should include module_name and external_deps count."""
        resolver = GoResolver(str(GO_FIXTURES))
        stats = resolver.stats()
        assert "module_name" in stats, f"stats should include module_name, got: {stats}"
        assert "external_deps" in stats, f"stats should include external_deps, got: {stats}"
        assert stats["module_name"] == "pp-consumer"
        assert stats["external_deps"] >= 10  # 10 deps in go.mod


class TestGoResolverParentRepoRoot:
    """Test that GoResolver works when repo_root is a parent of go.mod directory.

    This reproduces the real-world scenario where the overall repository root
    (e.g. ``src/``) is an ancestor of the Go project subdirectory
    (e.g. ``src/core/model_prediction/server/``).  Before the fix, index keys
    were computed relative to repo_root and ended up as
    ``core/model_prediction/server/common/utils`` instead of ``common/utils``,
    so stripped import paths never matched.
    """

    def test_resolve_with_parent_repo_root(self, tmp_path):
        """Import resolution should work when repo_root is a parent of go.mod."""
        # Build a directory tree:  repo_root / subdir / go.mod + common/utils.go
        subdir = tmp_path / "core" / "server"
        common_dir = subdir / "common"
        common_dir.mkdir(parents=True)

        # go.mod lives in the subdir
        (subdir / "go.mod").write_text("module my-service\n\ngo 1.22\n")
        # A Go package under the module
        (common_dir / "utils.go").write_text("package common\n\nfunc DoStuff() {}\n")
        # A top-level Go file in subdir
        (subdir / "main.go").write_text("package main\n\nimport \"my-service/common\"\n")

        resolver = GoResolver(str(tmp_path))

        # go.mod should be found
        assert resolver._module_name == "my-service"
        assert resolver._go_project_root == str(subdir.resolve())

        # The critical assertion: "my-service/common" must resolve
        result = resolver.resolve("my-service/common")
        assert result is not None, (
            f"'my-service/common' should resolve when repo_root is a parent. "
            f"Index keys: {list(resolver._index.keys())}"
        )
        assert "common" in result

        # Also check bare suffix matching
        result_bare = resolver.resolve("common")
        assert result_bare is not None, (
            f"'common' should resolve via suffix matching. "
            f"Index keys: {list(resolver._index.keys())}"
        )

    def test_index_keys_relative_to_go_project_root(self, tmp_path):
        """Index keys should be relative to go_project_root, not repo_root."""
        subdir = tmp_path / "deep" / "nested" / "project"
        pkg_dir = subdir / "internal" / "auth"
        pkg_dir.mkdir(parents=True)

        (subdir / "go.mod").write_text("module example.com/myapp\n\ngo 1.22\n")
        (pkg_dir / "auth.go").write_text("package auth\n\nfunc Login() {}\n")

        resolver = GoResolver(str(tmp_path))

        # Index key should be "internal/auth", NOT "deep/nested/project/internal/auth"
        assert "internal/auth" in resolver._index, (
            f"Expected 'internal/auth' in index, got: {list(resolver._index.keys())}"
        )
        bad_key = "deep/nested/project/internal/auth"
        assert bad_key not in resolver._index, (
            f"Index should NOT contain repo_root-relative key '{bad_key}'"
        )

    def test_same_package_linking_with_parent_repo_root(self, tmp_path):
        """get_package_siblings should work when repo_root is a parent."""
        subdir = tmp_path / "services" / "api"
        handler_dir = subdir / "handlers"
        handler_dir.mkdir(parents=True)

        (subdir / "go.mod").write_text("module api-service\n\ngo 1.22\n")
        (handler_dir / "user.go").write_text("package handlers\n\nfunc GetUser() {}\n")
        (handler_dir / "order.go").write_text("package handlers\n\nfunc GetOrder() {}\n")

        resolver = GoResolver(str(tmp_path))
        siblings = resolver.get_package_siblings(str(handler_dir / "user.go"))
        sibling_names = [Path(s).name for s in siblings]
        assert "order.go" in sibling_names

    def test_fallback_without_go_mod(self, tmp_path):
        """When no go.mod exists, scanning should fall back to repo_root."""
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        (pkg_dir / "main.go").write_text("package main\n")

        resolver = GoResolver(str(tmp_path))

        assert resolver._go_project_root is None
        assert resolver._module_name is None
        # Index should still work, scanning from repo_root
        assert "mypkg" in resolver._index, (
            f"Expected 'mypkg' in index without go.mod, got: {list(resolver._index.keys())}"
        )


from graph_builder.resolvers.ruby_resolver import RubyResolver


# ---------------------------------------------------------------
# Task 6: Ruby Gemfile parsing
# ---------------------------------------------------------------

class TestRubyGemfileParsing:
    """Test Ruby Gemfile parsing and gem classification."""

    def test_parse_gemfiles_finds_gems(self):
        """_parse_gemfiles should extract gem names from Gemfile."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        gems = resolver._parsed_gems
        assert "activesupport" in gems, f"Should find activesupport, got: {gems}"
        assert "redis" in gems, f"Should find redis, got: {gems}"
        assert "aws-sdk-s3" in gems, f"Should find aws-sdk-s3, got: {gems}"
        assert "rest-client" in gems, f"Should find rest-client, got: {gems}"
        assert "pry" in gems, f"Should find pry (dev gem), got: {gems}"

    def test_is_gem_matches_known_gems(self):
        """is_gem should match gem names and common aliases."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("redis") is True
        assert resolver.is_gem("active_support") is True  # underscore variant
        assert resolver.is_gem("rest-client") is True
        assert resolver.is_gem("rest_client") is True  # underscore variant
        assert resolver.is_gem("oj") is True
        assert resolver.is_gem("dalli") is True

    def test_is_gem_rejects_unknown(self):
        """is_gem should reject unknown modules."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("my_custom_lib") is False
        assert resolver.is_gem("nonexistent_gem") is False

    def test_is_gem_handles_submodules(self):
        """is_gem should match 'active_support/core_ext' via base name."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        assert resolver.is_gem("active_support/core_ext") is True
        assert resolver.is_gem("aws-sdk-s3/resource") is True

    def test_resolve_returns_gem_sentinel(self):
        """Unresolved gem imports should return '__ruby_gem__' sentinel."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        result = resolver.resolve("redis")
        # redis is not in our test fixtures as a .rb file, so it should
        # resolve as a gem sentinel (not stdlib, not in index)
        assert result == "__ruby_gem__", \
            f"'redis' should resolve to '__ruby_gem__', got: {result}"

    def test_resolve_unknown_returns_none(self):
        """Truly unknown imports should return None."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        result = resolver.resolve("completely_unknown_thing")
        assert result is None, \
            f"Unknown module should return None, got: {result}"

    def test_stats_include_gems(self):
        """stats() should include parsed_gems count."""
        resolver = RubyResolver(str(RUBY_FIXTURES))
        stats = resolver.stats()
        assert "parsed_gems" in stats, f"stats should include parsed_gems, got: {stats}"
        assert stats["parsed_gems"] >= 10
