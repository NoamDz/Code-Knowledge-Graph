"""Parameter name → module resolver.

Post-parse pass that resolves calls on function parameters whose types are
known by convention.  In the target OpenResty codebase, handler methods like
``M:apply(input, bundle, web)`` always receive the same module types:

* ``bundle`` → ``lib.lua.bundle``  (Bundle module)
* ``web``    → ``lib.lua.store``   (Store module, accessed as web.store)
* ``store``  → ``lib.lua.store``   (Store module passed directly)

``input`` is a plain table with no methods, so it is intentionally excluded.

The resolver iterates every Lua AST, finds unresolved calls whose receiver
matches a known parameter name (or a chained access like ``web.store``),
and fills in ``resolved_module``, ``resolved_function``, and
``resolution_confidence = "parameter"``.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


# Maps parameter names to their known module string.
# "input" is deliberately absent — it's a plain table with no methods.
PARAMETER_TYPE_MAP: dict[str, str] = {
    "bundle": "lib.lua.bundle",
    "web": "lib.lua.store",
    "store": "lib.lua.store",
}


def resolve_parameter_calls(all_asts: dict[str, FileAST]) -> int:
    """Resolve calls on known parameter names across all Lua ASTs.

    For every unresolved call whose receiver matches a key in
    ``PARAMETER_TYPE_MAP`` (or a chained access like ``web.store``),
    the call's ``resolved_module`` and ``resolved_function`` are set.

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

                # Chained access: "web.store:method" → receiver="web.store"
                # Split receiver on "." and check if any prefix maps to a
                # known parameter AND the chain ends at the target module.
                if "." in receiver:
                    chain_parts = receiver.split(".")
                    prefix = chain_parts[0]
                    # For "web.store:method", prefix is "web" and suffix
                    # is "store".  We resolve to the store module.
                    if prefix in PARAMETER_TYPE_MAP:
                        # The chained property indicates the actual module.
                        # "web.store" → lib.lua.store
                        suffix = chain_parts[-1]
                        # Map known suffixes to modules
                        suffix_module = PARAMETER_TYPE_MAP.get(suffix)
                        if suffix_module:
                            call.resolved_module = suffix_module
                        else:
                            # Fall back to the prefix's module
                            call.resolved_module = PARAMETER_TYPE_MAP[prefix]
                        call.resolved_function = method_name
                        call.resolution_confidence = "parameter"
                        resolved_count += 1
                        break

    return resolved_count
