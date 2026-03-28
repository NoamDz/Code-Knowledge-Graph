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


from graph_builder.resolvers.parameter_resolver import (
    PARAMETER_TYPE_MAP,
    FIELD_TYPE_MAP,
    resolve_parameter_calls,
)


# ---------------------------------------------------------------------------
# Task 4: Parameter resolver — FIELD_TYPE_MAP and store_object
# ---------------------------------------------------------------------------

class TestFieldTypeMap:
    def test_field_type_map_has_assess_vector(self):
        """FIELD_TYPE_MAP should map assess_vector to store_vector module."""
        assert "lib.lua.store" in FIELD_TYPE_MAP
        assert "assess_vector" in FIELD_TYPE_MAP["lib.lua.store"]
        assert FIELD_TYPE_MAP["lib.lua.store"]["assess_vector"] == "common.base.lua.store_vector"

    def test_field_type_map_has_collect_vector(self):
        """FIELD_TYPE_MAP should map collect_vector to store_vector module."""
        assert "collect_vector" in FIELD_TYPE_MAP["lib.lua.store"]
        assert FIELD_TYPE_MAP["lib.lua.store"]["collect_vector"] == "common.base.lua.store_vector"


class TestStoreObjectParameter:
    def test_store_object_in_parameter_type_map(self):
        """store_object should be in PARAMETER_TYPE_MAP mapping to lib.lua.store."""
        assert "store_object" in PARAMETER_TYPE_MAP
        assert PARAMETER_TYPE_MAP["store_object"] == "lib.lua.store"


class TestStoreVectorChainResolution:
    def test_store_assess_vector_get(self):
        """store.assess_vector:get() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        count = resolve_parameter_calls(all_asts)

        av_get_calls = [
            c for c in ast.calls
            if "assess_vector" in c.callee_string
            and c.callee_string.endswith("get")
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(av_get_calls) >= 1, (
            f"Expected at least 1 assess_vector:get resolution, got {len(av_get_calls)}. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_store_assess_vector_set(self):
        """store.assess_vector:set() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        av_set_calls = [
            c for c in ast.calls
            if "assess_vector" in c.callee_string
            and c.callee_string.endswith("set")
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(av_set_calls) >= 1

    def test_store_collect_vector_setall(self):
        """store.collect_vector:setall() should resolve to common.base.lua.store_vector."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        cv_calls = [
            c for c in ast.calls
            if "collect_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(cv_calls) >= 1

    def test_web_store_assess_vector_deep_chain(self):
        """web.store.assess_vector:get() should resolve via deep chain lookup."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        deep_calls = [
            c for c in ast.calls
            if "web.store.assess_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(deep_calls) >= 1, (
            f"Expected deep chain resolution. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_store_object_hget(self):
        """store_object:hget() should resolve to lib.lua.store."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        so_calls = [
            c for c in ast.calls
            if c.callee_string.startswith("store_object:")
            and c.resolved_module == "lib.lua.store"
        ]
        assert len(so_calls) >= 1

    def test_store_object_vector_chain(self):
        """store_object.assess_vector:get() should resolve to store_vector module."""
        ast = parse_lua_file(str(FIXTURES / "store_vector_chains.lua"))
        all_asts = {"store_vector_chains.lua": ast}
        resolve_parameter_calls(all_asts)

        so_av_calls = [
            c for c in ast.calls
            if "store_object.assess_vector" in c.callee_string
            and c.resolved_module == "common.base.lua.store_vector"
        ]
        assert len(so_av_calls) >= 1, (
            f"Expected store_object.assess_vector chain resolution. "
            f"All calls: {[(c.callee_string, c.resolved_module) for c in ast.calls]}"
        )

    def test_unknown_chain_not_resolved(self):
        """foo.bar:method() with unknown foo should NOT be resolved."""
        call = _make_call("foo.bar:baz")
        ast = _make_ast(calls=[call])
        all_asts = {"/test/file.lua": ast}
        resolve_parameter_calls(all_asts)
        assert call.resolved_module is None


from graph_builder.resolvers.base_inheritance_resolver import (
    BASE_MODULE_METHODS,
    resolve_base_inheritance,
)
from graph_builder.resolvers.call_resolver import CallResolver
from graph_builder.resolvers.redis_abstraction_resolver import (
    _STORE_VECTOR_READ,
    _STORE_VECTOR_WRITE,
)


# ---------------------------------------------------------------------------
# Task 5: Updated BASE_MODULE_METHODS
# ---------------------------------------------------------------------------

class TestBaseModuleMethodsUpdated:
    def test_handler_has_validate(self):
        """Handler base should have 'validate' (not 'validate_input')."""
        methods = BASE_MODULE_METHODS["common.base.lua.handler"]
        assert "validate" in methods

    def test_handler_has_response_map(self):
        """Handler base should have 'response_map'."""
        assert "response_map" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_add_handler_error(self):
        """Handler base should have 'add_handler_error'."""
        assert "add_handler_error" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_check_mark_store_save_async(self):
        """Handler base should have 'check_mark_store_save_async'."""
        assert "check_mark_store_save_async" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_user_error(self):
        """Handler base should have 'user_error'."""
        assert "user_error" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_dispatch(self):
        """Handler base should have 'dispatch'."""
        assert "dispatch" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_has_parse_postdata(self):
        """Handler base should have 'parse_postdata'."""
        assert "parse_postdata" in BASE_MODULE_METHODS["common.base.lua.handler"]

    def test_handler_no_old_methods(self):
        """Handler base should NOT have the old incorrect methods."""
        methods = BASE_MODULE_METHODS["common.base.lua.handler"]
        assert "validate_input" not in methods
        assert "handle_error" not in methods
        assert "log_error" not in methods
        assert "system_error" not in methods

    def test_collector_has_trigger(self):
        """Collector base should have 'trigger'."""
        assert "trigger" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_has_collect(self):
        """Collector base should have 'collect'."""
        assert "collect" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_has_get_store(self):
        """Collector base should have 'get_store'."""
        assert "get_store" in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_collector_no_old_methods(self):
        """Collector base should NOT have the old incorrect method 'store_data'."""
        assert "store_data" not in BASE_MODULE_METHODS["common.base.lua.collector"]

    def test_assessor_has_assess(self):
        """Assessor base should have 'assess'."""
        assert "assess" in BASE_MODULE_METHODS["common.base.lua.assessor"]

    def test_actor_exists(self):
        """Actor base module should be in BASE_MODULE_METHODS."""
        assert "common.base.lua.actor" in BASE_MODULE_METHODS

    def test_actor_has_act(self):
        """Actor base should have 'act'."""
        assert "act" in BASE_MODULE_METHODS["common.base.lua.actor"]


class TestBaseInheritanceWithUpdatedMethods:
    def test_handler_validate_input_no_longer_resolves(self):
        """self:validate_input() should no longer resolve via base inheritance."""
        ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
        all_asts = {"child_handler.lua": ast}
        resolve_base_inheritance(all_asts)

        vi_calls = [
            c for c in ast.calls
            if c.callee_string == "self:validate_input"
        ]
        if vi_calls:
            assert vi_calls[0].resolved_module != "common.base.lua.handler" or \
                   vi_calls[0].resolution_confidence != "base_inherited", \
                "validate_input should no longer resolve via base inheritance"

    def test_handler_user_error_still_resolves(self):
        """self:user_error() should still resolve to base handler (kept in updated set)."""
        ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
        all_asts = {"child_handler.lua": ast}
        resolve_base_inheritance(all_asts)

        ue_calls = [
            c for c in ast.calls
            if c.callee_string == "self:user_error"
            and c.resolved_module == "common.base.lua.handler"
            and c.resolution_confidence == "base_inherited"
        ]
        assert len(ue_calls) == 1, (
            f"Expected self:user_error to resolve to base handler. "
            f"Calls: {[(c.callee_string, c.resolved_module, c.resolution_confidence) for c in ast.calls]}"
        )


# ---------------------------------------------------------------------------
# Task 6: CallResolver self: branch guard
# ---------------------------------------------------------------------------

class TestCallResolverSelfGuard:
    def test_self_method_in_file_resolves(self):
        """self:process() where process is defined in the file should resolve to self."""
        call = _make_call("self:process")
        func = FunctionDef(name="M:process", line=10, line_end=20, visibility="public")
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )
        ast = _make_ast(
            calls=[call],
            functions=[func],
            module_info=module_info,
            file_path="/test/handler.lua",
        )
        ast.module_name = "test.handler"

        resolver = CallResolver(
            all_asts={"/test/handler.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        assert call.resolved_module == "test.handler"
        assert call.resolved_function == "process"
        assert call.resolution_confidence == "self"

    def test_self_method_not_in_file_does_not_resolve(self):
        """self:validate() where validate is NOT in the file should NOT resolve to self."""
        call = _make_call("self:validate")
        # Only define 'process' and 'apply' -- NOT 'validate'
        func_process = FunctionDef(name="M:process", line=10, line_end=20, visibility="public")
        func_apply = FunctionDef(name="M:apply", line=1, line_end=9, visibility="public")
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )
        ast = _make_ast(
            calls=[call],
            functions=[func_process, func_apply],
            module_info=module_info,
            file_path="/test/child_handler.lua",
        )
        ast.module_name = "test.child_handler"

        resolver = CallResolver(
            all_asts={"/test/child_handler.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        # The call should NOT be resolved to self -- it should fall through
        # so that the base_inheritance_resolver can pick it up later
        if call.resolved_module is not None:
            assert call.resolution_confidence != "self", (
                "self:validate() should not resolve to self when validate is not defined in the file"
            )

    def test_self_method_no_table_var_falls_through(self):
        """self:method() with no table_var_name should try function matching."""
        call = _make_call("self:apply")
        func = FunctionDef(name="apply", line=1, line_end=10, visibility="local")
        module_info = ModuleInfo(pattern_type=ModulePatternType.SIDE_EFFECT)
        ast = _make_ast(
            calls=[call],
            functions=[func],
            module_info=module_info,
            file_path="/test/script.lua",
        )
        ast.module_name = "test.script"

        resolver = CallResolver(
            all_asts={"/test/script.lua": ast},
            resolvers={},
        )
        resolver.resolve_all()

        # Option B in the self: branch should match by function name
        assert call.resolved_module == "test.script"
        assert call.resolved_function == "apply"


# ---------------------------------------------------------------------------
# Task 7: Updated StoreVector method sets
# ---------------------------------------------------------------------------

class TestStoreVectorMethodSets:
    def test_read_has_get(self):
        """StoreVector read set should contain 'get'."""
        assert "get" in _STORE_VECTOR_READ

    def test_read_has_getall(self):
        """StoreVector read set should contain 'getall'."""
        assert "getall" in _STORE_VECTOR_READ

    def test_write_has_set(self):
        """StoreVector write set should contain 'set'."""
        assert "set" in _STORE_VECTOR_WRITE

    def test_write_has_setall(self):
        """StoreVector write set should contain 'setall'."""
        assert "setall" in _STORE_VECTOR_WRITE

    def test_write_has_set_sparse_safe(self):
        """StoreVector write set should contain 'set_sparse_safe'."""
        assert "set_sparse_safe" in _STORE_VECTOR_WRITE

    def test_write_has_incr(self):
        """StoreVector write set should contain 'incr'."""
        assert "incr" in _STORE_VECTOR_WRITE

    def test_no_nonexistent_methods(self):
        """StoreVector sets should NOT contain methods that don't exist on StoreVector."""
        all_methods = _STORE_VECTOR_READ | _STORE_VECTOR_WRITE
        assert "add" not in all_methods
        assert "delete" not in all_methods
        assert "clear" not in all_methods
        assert "zadd" not in all_methods
        assert "zrem" not in all_methods
        assert "zrangebyscore" not in all_methods
        assert "get_all" not in all_methods
        assert "count" not in all_methods
        assert "exists" not in all_methods

    def test_new_excluded(self):
        """'new' is a constructor, not a Redis operation -- should not be in either set."""
        assert "new" not in _STORE_VECTOR_READ
        assert "new" not in _STORE_VECTOR_WRITE


# ---------------------------------------------------------------------------
# Task 8: Integration test -- all components together
# ---------------------------------------------------------------------------

class TestIntegrationAllResolvers:
    def test_call_resolver_then_inheritance(self):
        """CallResolver + base inheritance: self:validate falls through to base.

        Tests that when CallResolver self: guard skips a method not defined
        locally, the base_inheritance_resolver can then pick it up.
        """
        imports = [
            ImportRef(
                module_string="common.base.lua.handler",
                line=1,
                import_type="require_version",
                local_binding="base",
            ),
        ]
        functions = [
            FunctionDef(name="M:apply", line=5, line_end=20, visibility="public",
                        params=["self", "input", "bundle", "web"]),
            FunctionDef(name="M:process", line=22, line_end=30, visibility="public",
                        params=["self", "data"]),
        ]
        calls = [
            # self: inherited method (validate is NOT in this file)
            CallRef(caller_function="M:apply", callee_string="self:validate", line=10),
            # self: same-file method (process IS in this file)
            CallRef(caller_function="M:apply", callee_string="self:process", line=11),
            # Unknown call
            CallRef(caller_function="M:apply", callee_string="mystery_function", line=12),
        ]
        module_info = ModuleInfo(
            pattern_type=ModulePatternType.UPPERCASE_M,
            table_var_name="M",
        )

        ast = FileAST(
            file_path="/test/my_handler.lua",
            language="lua",
            module_name="test.my_handler",
            module_info=module_info,
            imports=imports,
            functions=functions,
            calls=calls,
        )

        all_asts = {"/test/my_handler.lua": ast}

        # Step 1: CallResolver
        resolver = CallResolver(all_asts=all_asts, resolvers={})
        resolver.resolve_all()

        # Step 2: Base inheritance resolver
        resolve_base_inheritance(all_asts)

        # --- Verify results ---

        # self:validate -> resolved to base handler (inherited)
        validate_call = next(c for c in calls if c.callee_string == "self:validate")
        assert validate_call.resolved_module == "common.base.lua.handler", (
            f"self:validate should resolve to base handler, got {validate_call.resolved_module}"
        )
        assert validate_call.resolution_confidence == "base_inherited"

        # self:process -> resolved to same file (self)
        process_call = next(c for c in calls if c.callee_string == "self:process")
        assert process_call.resolved_module == "test.my_handler", (
            f"self:process should resolve to same file, got {process_call.resolved_module}"
        )
        assert process_call.resolution_confidence == "self"

        # mystery_function -> should still be unresolved (no module)
        mystery_call = next(c for c in calls if c.callee_string == "mystery_function")
        assert mystery_call.resolved_module is None or \
            mystery_call.resolution_confidence not in ("self", "base_inherited")

    def test_store_vector_redis_classification(self):
        """Redis abstraction resolver should correctly classify updated StoreVector methods."""
        from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions

        calls = [
            CallRef(caller_function="M:apply", callee_string="vector:get", line=1),
            CallRef(caller_function="M:apply", callee_string="vector:setall", line=2),
            CallRef(caller_function="M:apply", callee_string="vector:set_sparse_safe", line=3),
            CallRef(caller_function="M:apply", callee_string="vector:incr", line=4),
            CallRef(caller_function="M:apply", callee_string="vector:getall", line=5),
        ]
        ast = FileAST(
            file_path="/test/handler.lua",
            language="lua",
            imports=[
                ImportRef(module_string="lib.lua.store", line=1,
                         import_type="require", local_binding="store"),
            ],
            calls=calls,
        )
        all_asts = {"/test/handler.lua": ast}
        resolve_redis_abstractions(all_asts)

        # vector:get -> read, vector:getall -> read
        read_ops = [r for r in ast.redis_accesses if r.access_type == "read"]
        read_op_names = {r.operation for r in read_ops}
        assert "get" in read_op_names
        assert "getall" in read_op_names

        # vector:setall -> write, vector:set_sparse_safe -> write, vector:incr -> write
        write_ops = [r for r in ast.redis_accesses if r.access_type == "write"]
        write_op_names = {r.operation for r in write_ops}
        assert "setall" in write_op_names
        assert "set_sparse_safe" in write_op_names
        assert "incr" in write_op_names

    def test_actor_inheritance_e2e(self):
        """Parsing child_actor.lua and resolving base inheritance for actor."""
        ast = parse_lua_file(str(FIXTURES / "child_actor.lua"))
        all_asts = {"child_actor.lua": ast}

        # Run CallResolver first
        resolver = CallResolver(all_asts=all_asts, resolvers={})
        resolver.resolve_all()

        # Then run base inheritance
        count = resolve_base_inheritance(all_asts)

        # act() is defined in the file, so should NOT resolve to base
        act_calls = [
            c for c in ast.calls
            if "act" in c.callee_string
            and c.resolution_confidence == "base_inherited"
        ]
        assert len(act_calls) == 0, \
            "act() is overridden locally, should not resolve to base"
