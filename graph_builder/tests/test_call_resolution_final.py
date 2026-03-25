"""Tests for parameter name → module resolver, dynamic prefix expansion, and base inheritance."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import FileAST, ImportRef
from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.base_inheritance_resolver import (
    BASE_MODULE_METHODS,
    resolve_base_inheritance,
)
from graph_builder.resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes
from graph_builder.resolvers.parameter_resolver import (
    PARAMETER_TYPE_MAP,
    resolve_parameter_calls,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lua"


def test_parameter_type_map_has_known_params():
    """bundle, web, store should be in the map; input should NOT."""
    assert "bundle" in PARAMETER_TYPE_MAP
    assert "web" in PARAMETER_TYPE_MAP
    assert "store" in PARAMETER_TYPE_MAP
    assert "input" not in PARAMETER_TYPE_MAP


def test_bundle_get_resolved():
    """bundle:get() calls should resolve to lib.lua.bundle."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    all_asts = {"param_handler.lua": ast}
    count = resolve_parameter_calls(all_asts)
    assert count > 0, "Expected at least one resolved call"

    bundle_calls = [
        c for c in ast.calls
        if c.resolved_module == "lib.lua.bundle" and c.resolved_function == "get"
    ]
    assert len(bundle_calls) >= 2, (
        f"Expected at least 2 bundle:get resolutions, got {len(bundle_calls)}"
    )
    for call in bundle_calls:
        assert call.resolution_confidence == "parameter"


def test_store_methods_resolved():
    """store:hget, store:set should resolve to lib.lua.store."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    all_asts = {"param_handler.lua": ast}
    resolve_parameter_calls(all_asts)

    store_calls = [
        c for c in ast.calls
        if c.resolved_module == "lib.lua.store"
    ]
    store_methods = {c.resolved_function for c in store_calls}
    assert "hget" in store_methods, f"hget not found in resolved store methods: {store_methods}"
    assert "set" in store_methods, f"set not found in resolved store methods: {store_methods}"


def test_web_store_chained_resolved():
    """web.store:get() and web.store:hget() should resolve to lib.lua.store."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))
    all_asts = {"param_handler.lua": ast}
    resolve_parameter_calls(all_asts)

    web_store_calls = [
        c for c in ast.calls
        if c.resolved_module == "lib.lua.store"
        and c.resolution_confidence == "parameter"
        and "web.store" in c.callee_string
    ]
    assert len(web_store_calls) >= 2, (
        f"Expected at least 2 web.store resolutions, got {len(web_store_calls)}: "
        f"{[c.callee_string for c in web_store_calls]}"
    )


def test_already_resolved_not_overwritten():
    """Calls that already have resolved_module should NOT be touched."""
    ast = parse_lua_file(str(FIXTURES / "param_handler.lua"))

    # Manually mark a bundle:get call as already resolved
    for call in ast.calls:
        if "bundle" in call.callee_string and "get" in call.callee_string:
            call.resolved_module = "my.custom.module"
            call.resolved_function = "custom_get"
            call.resolution_confidence = "binding"
            break

    all_asts = {"param_handler.lua": ast}
    resolve_parameter_calls(all_asts)

    # That call should still have the manually set module
    manually_set = [
        c for c in ast.calls
        if c.resolved_module == "my.custom.module"
    ]
    assert len(manually_set) == 1, (
        "The manually pre-resolved call should not be overwritten"
    )
    assert manually_set[0].resolved_function == "custom_get"
    assert manually_set[0].resolution_confidence == "binding"


# --- Dynamic prefix expansion tests ---


def test_dynamic_prefix_expansion():
    """Dynamic imports with static_prefix should expand to matching modules."""
    ast = FileAST(file_path="src/dispatcher.lua", language="lua")
    ast.imports.append(ImportRef(
        module_string='format("tasks.%s", task_name)',
        line=10, import_type="require",
        is_dynamic=True, static_prefix="tasks.",
    ))
    task1 = FileAST(file_path="src/ato/tasks/pts_run.lua", language="lua")
    task1.module_name = "ato.tasks.pts_run"
    task2 = FileAST(file_path="src/ato/tasks/assess.lua", language="lua")
    task2.module_name = "ato.tasks.assess"
    unrelated = FileAST(file_path="src/lib/store.lua", language="lua")
    unrelated.module_name = "lib.lua.store"

    all_asts = {
        "src/dispatcher.lua": ast,
        "src/ato/tasks/pts_run.lua": task1,
        "src/ato/tasks/assess.lua": task2,
        "src/lib/store.lua": unrelated,
    }
    edges = resolve_dynamic_prefixes(all_asts)
    assert len(edges) >= 2
    targets = [e["target_file"] for e in edges]
    assert "src/ato/tasks/pts_run.lua" in targets
    assert "src/ato/tasks/assess.lua" in targets
    assert "src/lib/store.lua" not in targets

    # Verify edge structure
    for edge in edges:
        assert edge["source_file"] == "src/dispatcher.lua"
        assert edge["prefix"] == "tasks."
        assert edge["line"] == 10


def test_no_dynamic_prefix_no_edges():
    """Files without dynamic imports produce no edges."""
    ast = FileAST(file_path="src/main.lua", language="lua")
    ast.imports.append(ImportRef(
        module_string="lib.utils",
        line=1, import_type="require",
        is_dynamic=False, static_prefix=None,
    ))

    other = FileAST(file_path="src/lib/utils.lua", language="lua")
    other.module_name = "lib.utils"

    all_asts = {
        "src/main.lua": ast,
        "src/lib/utils.lua": other,
    }
    edges = resolve_dynamic_prefixes(all_asts)
    assert len(edges) == 0


# --- Base class inheritance tests ---


def test_inherited_method_resolved():
    """self:validate_input() in child_handler should resolve to common.base.lua.handler."""
    ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
    all_asts = {"child_handler.lua": ast}
    count = resolve_base_inheritance(all_asts)
    assert count > 0, "Expected at least one base-inherited resolution"

    vi_calls = [
        c for c in ast.calls
        if c.callee_string == "self:validate_input"
    ]
    assert len(vi_calls) == 1
    assert vi_calls[0].resolved_module == "common.base.lua.handler"
    assert vi_calls[0].resolved_function == "validate_input"
    assert vi_calls[0].resolution_confidence == "base_inherited"


def test_same_file_method_not_overridden():
    """self:process() defined in same file should NOT resolve to base."""
    ast = parse_lua_file(str(FIXTURES / "child_handler.lua"))
    all_asts = {"child_handler.lua": ast}
    resolve_base_inheritance(all_asts)

    process_calls = [
        c for c in ast.calls
        if c.callee_string == "self:process"
    ]
    assert len(process_calls) == 1
    # process is defined locally in child_handler.lua, so it should NOT
    # be resolved to the base module
    assert process_calls[0].resolution_confidence != "base_inherited"
    assert process_calls[0].resolved_module != "common.base.lua.handler"
