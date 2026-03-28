"""Parameter name → module resolver.

Post-parse pass that resolves calls on function parameters whose types are
known by convention.  In the target OpenResty codebase, handler methods like
``M:apply(input, bundle, web)`` always receive the same module types:

* ``bundle`` → ``lib.lua.bundle``  (Bundle module)
* ``web``    → ``lib.lua.store``   (Store module, accessed as web.store)
* ``store``  → ``lib.lua.store``   (Store module passed directly)
* ``store_object`` → ``lib.lua.store``  (Store module passed as store_object)

``input`` is a plain table with no methods, so it is intentionally excluded.

The resolver iterates every Lua AST, finds unresolved calls whose receiver
matches a known parameter name (or a chained access like ``web.store``),
and fills in ``resolved_module``, ``resolved_function``, and
``resolution_confidence = "parameter"``.

Also handles store vector chains: ``store.assess_vector:get()`` resolves
to ``common.base.lua.store_vector`` via FIELD_TYPE_MAP.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


# Maps parameter names to their known module string.
# "input" is deliberately absent — it's a plain table with no methods.
PARAMETER_TYPE_MAP: dict[str, str] = {
    "bundle": "lib.lua.bundle",
    "web": "lib.lua.store",
    "store": "lib.lua.store",
    "store_object": "lib.lua.store",
}

# Maps a resolved module to its typed field names and their sub-module types.
# Used for chained field access: store.assess_vector:get() → resolve "get" on store_vector.
FIELD_TYPE_MAP: dict[str, dict[str, str]] = {
    "lib.lua.store": {
        "assess_vector": "common.base.lua.store_vector",
        "collect_vector": "common.base.lua.store_vector",
    },
}


def resolve_parameter_calls(all_asts: dict[str, FileAST]) -> int:
    """Resolve calls on known parameter names across all Lua ASTs.

    For every unresolved call whose receiver matches a key in
    ``PARAMETER_TYPE_MAP`` (or a chained access like ``web.store``),
    the call's ``resolved_module`` and ``resolved_function`` are set.

    Also handles store vector chains: ``store.assess_vector:get()``
    resolves to ``common.base.lua.store_vector`` via FIELD_TYPE_MAP.

    Args:
        all_asts: file_path → FileAST mapping for all parsed files.

    Returns:
        Number of newly resolved calls.
    """
    resolved_count = 0

    for file_path, ast in all_asts.items():
        if ast.language != "lua":
            continue

        for call in ast.calls:
            # Skip calls that are already resolved
            if call.resolved_module is not None:
                continue

            callee = call.callee_string

            # ----------------------------------------------------------
            # Pattern 1: receiver:method()  or  receiver.method()
            # e.g. bundle:get, store:hget, store:set
            # ----------------------------------------------------------
            for sep in (":", "."):
                if sep not in callee:
                    continue

                parts = callee.split(sep, 1)
                receiver, method_name = parts[0], parts[1]

                # Direct parameter match: "bundle:get" → receiver="bundle"
                if receiver in PARAMETER_TYPE_MAP:
                    call.resolved_module = PARAMETER_TYPE_MAP[receiver]
                    call.resolved_function = method_name
                    call.resolution_confidence = "parameter"
                    resolved_count += 1
                    break

                # Chained access: "web.store:method" or "store.assess_vector:method"
                if "." in receiver:
                    chain_parts = receiver.split(".")
                    prefix = chain_parts[0]

                    if prefix in PARAMETER_TYPE_MAP:
                        prefix_module = PARAMETER_TYPE_MAP[prefix]

                        # Check if the chain resolves to a sub-module via FIELD_TYPE_MAP.
                        # For "store.assess_vector:get":
                        #   prefix="store" → prefix_module="lib.lua.store"
                        #   remaining="assess_vector" → FIELD_TYPE_MAP check
                        # For "web.store.assess_vector:get":
                        #   prefix="web" → prefix_module="lib.lua.store"
                        #   remaining chain = ["store", "assess_vector"]
                        #   Walk the chain: "store" is in PARAMETER_TYPE_MAP → intermediate_module
                        #   then "assess_vector" is in FIELD_TYPE_MAP → sub_module
                        resolved_module = _resolve_chain(
                            chain_parts[1:], prefix_module, method_name
                        )
                        if resolved_module:
                            call.resolved_module = resolved_module
                            call.resolved_function = method_name
                            call.resolution_confidence = "parameter"
                            resolved_count += 1
                            break

                        # Fall back: resolve to the prefix's module if no sub-module matched
                        suffix = chain_parts[-1]
                        suffix_module = PARAMETER_TYPE_MAP.get(suffix)
                        if suffix_module:
                            call.resolved_module = suffix_module
                        else:
                            call.resolved_module = prefix_module
                        call.resolved_function = method_name
                        call.resolution_confidence = "parameter"
                        resolved_count += 1
                        break

    return resolved_count


def _resolve_chain(
    remaining_parts: list[str], current_module: str, method_name: str
) -> str | None:
    """Walk a chain of field accesses resolving through FIELD_TYPE_MAP.

    For ["assess_vector"] with current_module="lib.lua.store":
        → checks FIELD_TYPE_MAP["lib.lua.store"]["assess_vector"]
        → returns "common.base.lua.store_vector"

    For ["store", "assess_vector"] with current_module="lib.lua.store":
        → "store" is in PARAMETER_TYPE_MAP → intermediate = "lib.lua.store"
        → "assess_vector" is in FIELD_TYPE_MAP["lib.lua.store"]
        → returns "common.base.lua.store_vector"

    Returns the resolved sub-module string, or None if chain does not match.
    """
    module = current_module

    for i, part in enumerate(remaining_parts):
        # Check if this part is a typed field on the current module
        field_map = FIELD_TYPE_MAP.get(module)
        if field_map and part in field_map:
            module = field_map[part]
            # If this is the last part before the method, we found our target
            if i == len(remaining_parts) - 1:
                return module
            continue

        # Check if this part redirects to another known module
        part_module = PARAMETER_TYPE_MAP.get(part)
        if part_module:
            module = part_module
            continue

        # Unknown part in chain — cannot resolve further
        return None

    # If we walked all parts and ended up at a different module than we started,
    # check if the final module has the field map entry
    if module != current_module:
        return module

    return None
