"""Redis abstraction resolver.

Post-parse pass that recognizes calls to known Redis wrapper modules
(like redis_helper, store, store_vector) and creates RedisKeyAccess entries
on the caller's AST.

This makes Redis usage visible through abstraction layers:
  caller.lua → store:get(key)       →  REDIS_READS edge on caller
  caller.lua → vector:add(data)     →  REDIS_WRITES edge on caller
  caller.lua → redis_helper:get(k)  →  REDIS_READS edge on caller
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST, RedisKeyAccess


# Store methods classified as read or write.
# Used for both "lib.lua.store" and "common.base.lua.store" paths.
_STORE_READ = {
    "get", "hget", "hmget", "hgetall", "exists",
    "smembers", "sismember",
}
_STORE_WRITE = {
    "set", "delete", "expire", "incr", "decr",
    "hset", "hmset", "hdel",
    "sadd", "srem",
    "lock", "unlock",
    "begin_transaction", "commit_transaction",
    "cache_stores_start", "cache_stores_commit",
}

# StoreVector actual methods (from store_vector.lua):
# new, set, set_sparse_safe, setall, get, getall, incr
# "new" is a constructor and excluded from Redis classification.
_STORE_VECTOR_READ = {
    "get", "getall",
}
_STORE_VECTOR_WRITE = {
    "set", "set_sparse_safe", "setall", "incr",
}

# Hardcoded abstraction defaults for known Redis wrapper modules.
# Keys are module strings (as they appear in require() calls).
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
    # Both paths used in different parts of the codebase
    "lib.lua.store": {"read": _STORE_READ, "write": _STORE_WRITE},
    "common.base.lua.store": {"read": _STORE_READ, "write": _STORE_WRITE},
    "lib.lua.store_vector": {"read": _STORE_VECTOR_READ, "write": _STORE_VECTOR_WRITE},
}

# Factory methods on store modules that return store_vector instances.
STORE_VECTOR_FACTORIES: dict[str, set[str]] = {
    "lib.lua.store": {"collect_vector", "assess_vector"},
    "common.base.lua.store": {"collect_vector", "assess_vector"},
}

# All store module strings (for prefix matching in chained calls)
_ALL_STORE_MODULES = {"lib.lua.store", "common.base.lua.store"}


def resolve_redis_abstractions(all_asts: dict[str, FileAST],
                                abstraction_map: dict | None = None):
    """Scan all ASTs for calls to Redis abstraction modules and create RedisKeyAccess entries.

    Handles three patterns:
    1. Direct: store:get(key), redis_helper:set(key, val)
    2. Chained: store.assess_vector:set(val) — factory.method:operation
    3. Deep chain: runtime.web.store:get(key) — nested property access
    """
    abstractions = abstraction_map or REDIS_ABSTRACTION_DEFAULTS

    for file_path, ast in all_asts.items():
        # Build binding map: local_var → module_string
        binding_to_module: dict[str, str] = {}
        for imp in ast.imports:
            if imp.local_binding and not imp.is_dynamic:
                for binding in imp.local_binding.split(", "):
                    binding = binding.strip()
                    if binding:
                        binding_to_module[binding] = imp.module_string

        # Build case-insensitive binding lookup for property chain matching
        # e.g., "Store" → "common.base.lua.store" also matches "store" in runtime.web.store
        binding_lower: dict[str, str] = {
            k.lower(): v for k, v in binding_to_module.items()
        }

        # Check if this file imports any store module
        has_store_import = any(
            mod_str in _ALL_STORE_MODULES for mod_str in binding_to_module.values()
        )

        already_matched: set[int] = set()

        # --- Pass 1: Direct abstraction calls ---
        # Matches: store:get, Store.get, redis_helper:hget
        for call in ast.calls:
            callee = call.callee_string
            for sep in (":", "."):
                if sep not in callee:
                    continue
                parts = callee.split(sep, 1)
                table_name, method_name = parts[0], parts[1]

                module_str = call.resolved_module or binding_to_module.get(table_name)
                if not module_str or module_str not in abstractions:
                    continue

                config = abstractions[module_str]
                if method_name in config.get("read", set()):
                    ast.redis_accesses.append(RedisKeyAccess(
                        key_name=f"<via {module_str}>",
                        operation=method_name, access_type="read",
                        function=call.caller_function, line=call.line,
                    ))
                    already_matched.add(call.line)
                    break
                elif method_name in config.get("write", set()):
                    ast.redis_accesses.append(RedisKeyAccess(
                        key_name=f"<via {module_str}>",
                        operation=method_name, access_type="write",
                        function=call.caller_function, line=call.line,
                    ))
                    already_matched.add(call.line)
                    break

        # --- Pass 2: Chained vector calls ---
        # Matches: store.assess_vector:set, store.collect_vector:add
        # Pattern: binding.factory_method:vector_operation
        # The callee "store.assess_vector:set" splits on ":" as
        #   table_name="store.assess_vector", method_name="set"
        # We need to check if the prefix "store" is a store binding
        # and "assess_vector" is a factory method
        for call in ast.calls:
            if call.line in already_matched:
                continue
            callee = call.callee_string

            # Try splitting on ":" first (method call syntax)
            if ":" in callee:
                parts = callee.split(":", 1)
                chain, method_name = parts[0], parts[1]

                # Check if chain contains a store binding as prefix
                # e.g., "store.assess_vector" → "store" is binding, "assess_vector" is factory
                # e.g., "runtime.web.store.assess_vector" → look for any binding in the chain
                if "." in chain:
                    chain_parts = chain.split(".")
                    for i, part in enumerate(chain_parts):
                        # Try exact binding, then case-insensitive
                        mod_str = binding_to_module.get(part) or binding_lower.get(part.lower())
                        # Also match by name: "store" in a chain likely IS a store
                        if not mod_str and has_store_import and part.lower() == "store":
                            mod_str = next(
                                (v for v in binding_to_module.values() if v in _ALL_STORE_MODULES), None
                            )
                        if not mod_str or mod_str not in _ALL_STORE_MODULES:
                            continue
                        # Check if next part is a factory method
                        remaining = chain_parts[i+1:]
                        if remaining and remaining[-1] in STORE_VECTOR_FACTORIES.get(mod_str, set()):
                            # This is a vector operation
                            if method_name in _STORE_VECTOR_READ:
                                ast.redis_accesses.append(RedisKeyAccess(
                                    key_name=f"<via store_vector>",
                                    operation=method_name, access_type="read",
                                    function=call.caller_function, line=call.line,
                                ))
                                already_matched.add(call.line)
                                break
                            elif method_name in _STORE_VECTOR_WRITE:
                                ast.redis_accesses.append(RedisKeyAccess(
                                    key_name=f"<via store_vector>",
                                    operation=method_name, access_type="write",
                                    function=call.caller_function, line=call.line,
                                ))
                                already_matched.add(call.line)
                                break

        # --- Pass 3: Deep chain store calls ---
        # Matches: runtime.web.store:get, runtime.web.store:begin_transaction
        # Pattern: any.chain.STORE_NAME:method — match by binding OR by property name "store"
        for call in ast.calls:
            if call.line in already_matched:
                continue
            callee = call.callee_string

            if ":" in callee:
                parts = callee.split(":", 1)
                chain, method_name = parts[0], parts[1]

                if "." in chain:
                    chain_parts = chain.split(".")
                    last_part = chain_parts[-1]
                    # Try exact binding, case-insensitive, or name-based "store" match
                    mod_str = binding_to_module.get(last_part) or binding_lower.get(last_part.lower())
                    if not mod_str and has_store_import and last_part.lower() == "store":
                        mod_str = next(
                            (v for v in binding_to_module.values() if v in _ALL_STORE_MODULES), None
                        )
                    if mod_str and mod_str in abstractions:
                        config = abstractions[mod_str]
                        if method_name in config.get("read", set()):
                            ast.redis_accesses.append(RedisKeyAccess(
                                key_name=f"<via {mod_str}>",
                                operation=method_name, access_type="read",
                                function=call.caller_function, line=call.line,
                            ))
                            already_matched.add(call.line)
                        elif method_name in config.get("write", set()):
                            ast.redis_accesses.append(RedisKeyAccess(
                                key_name=f"<via {mod_str}>",
                                operation=method_name, access_type="write",
                                function=call.caller_function, line=call.line,
                            ))
                            already_matched.add(call.line)

        # --- Pass 4: Unbound vector variable calls ---
        # Matches: vector:add, collect_vector:set
        # Heuristic: if the file imports a store module, any call to
        # an unbound variable with a store_vector method name is likely Redis
        if has_store_import:
            for call in ast.calls:
                if call.line in already_matched:
                    continue
                callee = call.callee_string
                for sep in (":", "."):
                    if sep not in callee:
                        continue
                    parts = callee.split(sep, 1)
                    var_name, method_name = parts[0], parts[1]

                    # Skip if already bound to a module
                    if var_name in binding_to_module:
                        continue

                    if method_name in _STORE_VECTOR_READ:
                        ast.redis_accesses.append(RedisKeyAccess(
                            key_name="<via store_vector>",
                            operation=method_name, access_type="read",
                            function=call.caller_function, line=call.line,
                        ))
                        already_matched.add(call.line)
                        break
                    elif method_name in _STORE_VECTOR_WRITE:
                        ast.redis_accesses.append(RedisKeyAccess(
                            key_name="<via store_vector>",
                            operation=method_name, access_type="write",
                            function=call.caller_function, line=call.line,
                        ))
                        already_matched.add(call.line)
                        break


# Go Redis client methods
_GO_REDIS_READ = {
    "Get", "GetAsString", "GetAsInt", "GetAsFloat",
    "GetRange", "GetSet", "GetEx", "GetDel",
    "Strlen", "Exists", "Type", "TTL", "PTTL", "Keys", "Scan",
    "HGet", "HGetAsString", "HGetAsInt", "HGetAsFloat",
    "HGetAll", "HMGet", "HExists", "HKeys", "HVals", "HLen",
    "SMembers", "SIsMember", "SCard", "SRandMember",
    "ZRange", "ZRangeByScore", "ZRank", "ZScore", "ZCard",
    "LRange", "LLen", "LIndex",
    "Ping",
}

_GO_REDIS_WRITE = {
    "Set", "SetEX", "SetNX", "Append", "Incr", "IncrBy", "Decr", "DecrBy",
    "Del", "Expire", "ExpireAt", "PExpire", "Persist",
    "HSet", "HSetWithExpire", "HMSet", "HDel", "HIncrBy",
    "SAdd", "SRem", "SPop",
    "ZAdd", "ZRem", "ZIncrBy",
    "LPush", "RPush", "LPop", "RPop", "LSet", "LTrim",
    "Publish",
    "Close",
}

_GO_REDIS_INDICATORS = {"redisClient", "RedisClient", "redis.Client", "rdb", "redisConn"}


def resolve_go_redis_abstractions(all_asts):
    """Detect Redis calls in Go code through client wrapper patterns."""
    from graph_builder.parsers.base import RedisKeyAccess

    for file_path, ast in all_asts.items():
        if ast.language != "go":
            continue
        for call in ast.calls:
            callee = call.callee_string
            parts = callee.rsplit(".", 1)
            if len(parts) != 2:
                continue
            receiver, method = parts
            is_redis = any(ind in receiver for ind in _GO_REDIS_INDICATORS)
            if not is_redis:
                receiver_tail = receiver.rsplit(".", 1)[-1]
                is_redis = receiver_tail.lower() in {"redisclient", "redis", "rdb", "redisconn", "rclient", "client"}
            if not is_redis:
                continue
            if method in _GO_REDIS_READ:
                access_type = "read"
            elif method in _GO_REDIS_WRITE:
                access_type = "write"
            else:
                continue
            ast.redis_accesses.append(RedisKeyAccess(
                key_name=f"<via go:{receiver}>",
                operation=method,
                access_type=access_type,
                function=call.caller_function,
                line=call.line,
            ))
