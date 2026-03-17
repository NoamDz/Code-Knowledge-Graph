"""Redis abstraction resolver.

Post-parse pass that recognizes calls to known Redis wrapper modules
(like redis_helper) and creates RedisKeyAccess entries on the caller's AST.

This makes Redis usage visible through abstraction layers:
  caller.lua → redis_helper:get(key)  →  REDIS_READS edge on caller
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST, RedisKeyAccess


# Hardcoded abstraction defaults for known Redis wrapper modules.
# Keys are module strings (as they appear in require() calls).
# Values classify each method as "read" or "write".
REDIS_ABSTRACTION_DEFAULTS: dict[str, dict[str, set[str]]] = {
    "lib.lua.redis_helper": {
        "read": {
            "get", "get_as_string", "get_json", "hget", "hgetall", "hkeys",
            "hmget", "hlen", "exists", "ttl", "right_pop", "get_time", "get_info",
        },
        "write": {
            "set", "set_json", "hset", "hsetall", "hdel", "hdel_many", "hmset",
            "delete", "setnx", "hsetnx", "incr", "hincr", "left_push", "lock",
            "unlock", "atomic_getset", "atomic_hgethset", "set_with_expire",
            "setex_with_expire", "setnx_with_expire", "incr_with_expire_once",
            "hset_with_expire", "hsetnx_with_expire", "set_with_expire_once",
            "hset_with_limit", "hset_with_limit_expire_once", "hset_update",
            "expire", "exists_and_hsetnx", "exists_and_hincr", "pipeline",
        },
    },
}


def resolve_redis_abstractions(all_asts: dict[str, FileAST],
                                abstraction_map: dict | None = None):
    """Scan all ASTs for calls to Redis abstraction modules and create RedisKeyAccess entries.

    Args:
        all_asts: file_path → FileAST for all parsed files.
        abstraction_map: Optional override for REDIS_ABSTRACTION_DEFAULTS.
    """
    abstractions = abstraction_map or REDIS_ABSTRACTION_DEFAULTS

    # Build a lookup: for each AST, check which local bindings map to abstraction modules
    for file_path, ast in all_asts.items():
        # Build binding map: local_var → module_string
        binding_to_module: dict[str, str] = {}
        for imp in ast.imports:
            if imp.local_binding and not imp.is_dynamic:
                for binding in imp.local_binding.split(", "):
                    binding = binding.strip()
                    if binding:
                        binding_to_module[binding] = imp.module_string

        # Check each call: does it target a known abstraction?
        for call in ast.calls:
            callee = call.callee_string
            # Match patterns like: redis_helper:get, redis_helper.get
            for sep in (":", "."):
                if sep not in callee:
                    continue
                parts = callee.split(sep, 1)
                table_name, method_name = parts[0], parts[1]

                # Look up what module this table_name is bound to
                module_str = call.resolved_module or binding_to_module.get(table_name)
                if not module_str:
                    continue

                # Check if this module is a known Redis abstraction
                if module_str not in abstractions:
                    continue

                config = abstractions[module_str]
                read_methods = config.get("read", set())
                write_methods = config.get("write", set())

                if method_name in read_methods:
                    ast.redis_accesses.append(RedisKeyAccess(
                        key_name=f"<via {module_str}>",
                        operation=method_name,
                        access_type="read",
                        function=call.caller_function,
                        line=call.line,
                    ))
                    break
                elif method_name in write_methods:
                    ast.redis_accesses.append(RedisKeyAccess(
                        key_name=f"<via {module_str}>",
                        operation=method_name,
                        access_type="write",
                        function=call.caller_function,
                        line=call.line,
                    ))
                    break
