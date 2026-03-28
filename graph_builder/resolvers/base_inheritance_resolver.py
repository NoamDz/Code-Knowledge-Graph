"""Base class inheritance resolver for Lua handler/assessor/collector patterns.

Lua handlers/assessors/collectors inherit from base modules via:
    local base = require_version("common.base.lua.handler")
    local M = base:new()

When `self:validate_input()` is called in a handler file but `validate_input`
is NOT defined in that file, it's inherited from the base module. The
CallResolver incorrectly resolves these to the current file (confidence="self")
because the module has a table_var_name. This resolver corrects those.

Inheritance is ALWAYS single-level (child -> base, never child -> middle -> grandparent).
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


# Known base modules and their inheritable methods.
# Updated 2026-03-28 from BOB investigation of actual base module source files.
BASE_MODULE_METHODS: dict[str, set[str]] = {
    "common.base.lua.handler": {
        "validate", "response_map", "add_handler_error",
        "check_mark_store_save_async", "user_error", "parse_postdata",
        "dispatch", "handle_web_request", "handle_ep_request",
        "handle_pmc", "handle_tma", "handle_internal_request",
        "add_error_metrics", "parse_api_version_data",
        "verify_store_size_limit", "add_general_handler_error",
        "create_handler", "sanitize_error_output", "user_error_format",
        "create_handler_event",
    },
    "common.base.lua.assessor": {
        "assess",
    },
    "common.base.lua.collector": {
        "trigger", "collect", "get_trigger_collector",
        "trigger_web_request", "get_collect_collector",
        "decrypt_collect_data", "collect_web_request",
        "fake_collect_web_request", "get_store",
    },
    "common.base.lua.actor": {
        "act",
    },
}


def resolve_base_inheritance(all_asts: dict[str, FileAST]) -> int:
    """Resolve self:method() calls that are inherited from a known base module.

    For each Lua file:
      1. Check if it imports a known base module (common.base.lua.handler, etc.)
      2. Get the set of methods defined in the current file
      3. For each self:method() call where the method is NOT in the current
         file's methods but IS in the base module's known methods, re-resolve
         the call to the base module

    Args:
        all_asts: file_path -> FileAST for all parsed files

    Returns:
        Count of newly resolved (re-resolved) calls
    """
    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        # Step 1: Find which base module (if any) this file imports
        base_module = _find_base_module(ast)
        if not base_module:
            continue

        base_methods = BASE_MODULE_METHODS[base_module]

        # Step 2: Get the set of methods defined locally in this file
        local_methods = _get_local_methods(ast)

        # Step 3: Re-resolve self:method() calls targeting inherited methods
        for call in ast.calls:
            if not call.callee_string.startswith("self:"):
                continue

            method_name = call.callee_string.split(":", 1)[1]

            # Only re-resolve if: method NOT defined locally AND method IS in base
            if method_name not in local_methods and method_name in base_methods:
                call.resolved_module = base_module
                call.resolved_function = method_name
                call.resolution_confidence = "base_inherited"
                resolved_count += 1

    return resolved_count


def _find_base_module(ast: FileAST) -> str | None:
    """Check if the file imports a known base module."""
    for imp in ast.imports:
        if imp.module_string in BASE_MODULE_METHODS:
            return imp.module_string
    return None


def _get_local_methods(ast: FileAST) -> set[str]:
    """Get the set of method names defined in the file."""
    methods: set[str] = set()
    for func in ast.functions:
        # Strip table prefix: "M:apply" -> "apply", "M.process" -> "process"
        base_name = func.name.split(".")[-1].split(":")[-1]
        methods.add(base_name)
    return methods
