"""Improved Lua parser for OpenResty codebases.

Key improvements over the original plan:
  1. Generic return-table detection (not hardcoded to _M)
  2. Require-to-variable tracking (local redis = require "resty.redis")
  3. pcall/xpcall unwrapping
  4. ngx.ctx field tracking (reads and writes)
  5. ngx.shared.DICT tracking
  6. Dynamic require detection and flagging
  7. Method syntax (:) detection

Uses AST-walking approach where tree-sitter-lua grammar structure
makes pure queries fragile.
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_lua as tslua

from .base import (
    FileAST, FunctionDef, ImportRef, CallRef, ModuleInfo,
    ModulePatternType, ContextAccess, SharedDictAccess,
    InternalRedirect, RedisKeyAccess, HttpCallRef,
)

LUA = Language(tslua.language())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _first_child_of_type(node, type_name: str):
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _has_child_type(node, type_name: str) -> bool:
    return any(c.type == type_name for c in node.children)


def _get_string_value(string_node, source: bytes) -> str:
    """Extract string content from a Lua string node (strips quotes)."""
    content = _first_child_of_type(string_node, "string_content")
    if content:
        return _text(content, source)
    raw = _text(string_node, source)
    return raw.strip("\"'[]")


def _walk_all(root, type_name: str):
    """Yield all descendant nodes of a given type (depth-first)."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == type_name:
            yield node
        stack.extend(reversed(node.children))


def _find_enclosing_function(node, source: bytes) -> str:
    """Walk up the tree to find the enclosing function name."""
    current = node.parent
    while current:
        if current.type == "function_declaration":
            name_node = current.child_by_field_name("name")
            if name_node:
                return _text(name_node, source)
        if current.type == "assignment_statement":
            vl = _first_child_of_type(current, "variable_list")
            el = _first_child_of_type(current, "expression_list")
            if vl and el and any(c.type == "function_definition" for c in el.named_children):
                if vl.named_child_count > 0:
                    return _text(vl.named_children[0], source)
        current = current.parent
    return "<module>"


# ---------------------------------------------------------------------------
# Module pattern detection
# ---------------------------------------------------------------------------

def _detect_module_pattern(root, source: bytes) -> ModuleInfo:
    """Detect module pattern by analyzing the file's top-level return."""
    top_returns = [c for c in root.children if c.type == "return_statement"]
    if not top_returns:
        return ModuleInfo(pattern_type=ModulePatternType.SIDE_EFFECT)

    ret = top_returns[-1]
    expr_list = _first_child_of_type(ret, "expression_list")
    if not expr_list or expr_list.named_child_count == 0:
        return ModuleInfo(pattern_type=ModulePatternType.SIDE_EFFECT)

    returned = expr_list.named_children[0]
    returned_text = _text(returned, source)

    if returned.type == "identifier":
        pattern = _classify_var_name(returned_text)
        return ModuleInfo(pattern_type=pattern, table_var_name=returned_text,
                          returned_identifier=returned_text)

    if returned.type == "table_constructor":
        return ModuleInfo(pattern_type=ModulePatternType.DIRECT_RETURN,
                          returned_identifier=returned_text)

    if returned.type == "function_call":
        callee = returned.child_by_field_name("name")
        if callee and _text(callee, source) == "setmetatable":
            return ModuleInfo(pattern_type=ModulePatternType.METATABLE_CLASS,
                              returned_identifier=returned_text)

    return ModuleInfo(pattern_type=ModulePatternType.UNKNOWN,
                      returned_identifier=returned_text)


def _classify_var_name(name: str) -> ModulePatternType:
    if name == "_M":
        return ModulePatternType.UNDERSCORE_M
    if name == "M":
        return ModulePatternType.UPPERCASE_M
    if name == "m":
        return ModulePatternType.LOWERCASE_M
    return ModulePatternType.NAMED_TABLE


# ---------------------------------------------------------------------------
# Require extraction
# ---------------------------------------------------------------------------

def _extract_requires(root, source: bytes, ast: FileAST) -> dict[str, str]:
    """Extract all require() calls. Returns local_var → module binding map."""
    binding_map: dict[str, str] = {}

    for call_node in _walk_all(root, "function_call"):
        name_node = call_node.child_by_field_name("name")
        if not name_node or name_node.type != "identifier":
            continue
        if _text(name_node, source) != "require":
            continue

        args = _first_child_of_type(call_node, "arguments")
        if not args or args.named_child_count == 0:
            continue

        first_arg = args.named_children[0]

        # Dynamic require
        if first_arg.type != "string":
            static_prefix = _extract_concat_prefix(first_arg, source)
            ast.imports.append(ImportRef(
                module_string=_text(first_arg, source),
                line=first_arg.start_point[0] + 1,
                import_type="require",
                is_dynamic=True,
                static_prefix=static_prefix,
            ))
            ast.warnings.append(
                f"Dynamic require at line {first_arg.start_point[0] + 1}: "
                f"require({_text(first_arg, source)})"
            )
            continue

        # Static require
        mod_str = _get_string_value(first_arg, source)
        local_binding = _find_require_binding(call_node, source)

        if local_binding:
            binding_map[local_binding] = mod_str

        ast.imports.append(ImportRef(
            module_string=mod_str,
            line=call_node.start_point[0] + 1,
            import_type="require",
            local_binding=local_binding,
        ))

    return binding_map


def _find_require_binding(call_node, source: bytes) -> str | None:
    """Find the local variable a require call is assigned to.

    AST path: variable_declaration > assignment_statement > expression_list > function_call
    """
    parent = call_node.parent  # expression_list
    if not parent or parent.type != "expression_list":
        return None
    grandparent = parent.parent  # assignment_statement
    if not grandparent or grandparent.type != "assignment_statement":
        return None
    great_gp = grandparent.parent
    if not great_gp or great_gp.type != "variable_declaration":
        return None

    vl = _first_child_of_type(grandparent, "variable_list")
    if vl and vl.named_child_count > 0:
        first_var = vl.named_children[0]
        if first_var.type == "identifier":
            return _text(first_var, source)
    return None


def _extract_concat_prefix(node, source: bytes) -> str | None:
    """Extract static prefix from concatenation: "handlers." .. x."""
    if node.type == "binary_expression":
        left = node.child_by_field_name("left")
        op = node.child_by_field_name("operator")
        if op and _text(op, source) == ".." and left and left.type == "string":
            return _get_string_value(left, source)
    return None


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------

def _extract_functions(root, source: bytes, ast: FileAST, module_info: ModuleInfo):
    """Extract all function definitions."""
    table_var = module_info.table_var_name

    # function_declaration covers both `local function f()` and `function t.f()`
    for func_node in _walk_all(root, "function_declaration"):
        name_node = func_node.child_by_field_name("name")
        if not name_node:
            continue
        name_text = _text(name_node, source)
        is_local = _has_child_type(func_node, "local")
        is_method = name_node.type == "method_index_expression"

        visibility = "local"
        if not is_local and name_node.type in ("dot_index_expression", "method_index_expression"):
            if table_var:
                tbl = name_node.child_by_field_name("table")
                if tbl and _text(tbl, source) == table_var:
                    visibility = "public"

        ast.functions.append(FunctionDef(
            name=name_text,
            line=func_node.start_point[0] + 1,
            line_end=func_node.end_point[0] + 1,
            visibility=visibility,
            params=_extract_params(func_node, source),
            is_method=is_method,
        ))

    # Assignment-style: table.method = function(...) or table["method"] = function(...)
    for assign_node in _walk_all(root, "assignment_statement"):
        # Skip local assignments (inside variable_declaration)
        if assign_node.parent and assign_node.parent.type == "variable_declaration":
            continue

        vl = _first_child_of_type(assign_node, "variable_list")
        el = _first_child_of_type(assign_node, "expression_list")
        if not (vl and el):
            continue

        func_node = None
        for child in el.named_children:
            if child.type == "function_definition":
                func_node = child
                break
        if not func_node or vl.named_child_count == 0:
            continue

        name_node = vl.named_children[0]

        # Dot notation: table.method = function(...)
        if name_node.type == "dot_index_expression":
            name_text = _text(name_node, source)
            if any(f.name == name_text for f in ast.functions):
                continue

            visibility = "local"
            if table_var:
                tbl = name_node.child_by_field_name("table")
                if tbl and _text(tbl, source) == table_var:
                    visibility = "public"

            ast.functions.append(FunctionDef(
                name=name_text,
                line=func_node.start_point[0] + 1,
                line_end=func_node.end_point[0] + 1,
                visibility=visibility,
                params=_extract_params(func_node, source),
            ))

        # Bracket notation: table["method"] = function(...)
        elif name_node.type == "bracket_index_expression":
            tbl = name_node.child_by_field_name("table")
            field = name_node.child_by_field_name("field")
            if not (tbl and field and field.type == "string"):
                continue
            field_name = _get_string_value(field, source)
            name_text = f"{_text(tbl, source)}[\"{field_name}\"]"
            if any(f.name == name_text for f in ast.functions):
                continue

            visibility = "local"
            if table_var and _text(tbl, source) == table_var:
                visibility = "public"

            ast.functions.append(FunctionDef(
                name=name_text,
                line=func_node.start_point[0] + 1,
                line_end=func_node.end_point[0] + 1,
                visibility=visibility,
                params=_extract_params(func_node, source),
            ))


def _extract_params(func_node, source: bytes) -> list[str]:
    params = []
    pnode = func_node.child_by_field_name("parameters")
    if pnode:
        for p in pnode.named_children:
            if p.type == "identifier":
                params.append(_text(p, source))
            elif p.type == "spread":
                params.append("...")
    return params


# ---------------------------------------------------------------------------
# Export detection
# ---------------------------------------------------------------------------

def _find_exports(root, source: bytes, module_info: ModuleInfo) -> list[str]:
    """Find exported names based on module pattern."""
    if module_info.pattern_type == ModulePatternType.DIRECT_RETURN:
        for child in root.children:
            if child.type == "return_statement":
                el = _first_child_of_type(child, "expression_list")
                if el and el.named_child_count > 0:
                    table = el.named_children[0]
                    if table.type == "table_constructor":
                        return _extract_table_keys(table, source)
        return []

    table_var = module_info.table_var_name
    if not table_var:
        return []

    exports = set()

    for func_node in _walk_all(root, "function_declaration"):
        name_node = func_node.child_by_field_name("name")
        if not name_node or name_node.type not in ("dot_index_expression", "method_index_expression"):
            continue
        tbl = name_node.child_by_field_name("table")
        if not tbl or _text(tbl, source) != table_var:
            continue
        field = name_node.child_by_field_name("field") or name_node.child_by_field_name("method")
        if field:
            exports.add(_text(field, source))

    # Assignment-style exports: table_var.x = value
    for assign_node in _walk_all(root, "assignment_statement"):
        if assign_node.parent and assign_node.parent.type == "variable_declaration":
            continue
        vl = _first_child_of_type(assign_node, "variable_list")
        if not vl or vl.named_child_count == 0:
            continue
        name_node = vl.named_children[0]

        # Dot notation: table_var.field = value
        if name_node.type == "dot_index_expression":
            tbl = name_node.child_by_field_name("table")
            if not tbl or _text(tbl, source) != table_var:
                continue
            field = name_node.child_by_field_name("field")
            if field:
                exports.add(_text(field, source))

        # Bracket notation: table_var["field"] = value
        elif name_node.type == "bracket_index_expression":
            tbl = name_node.child_by_field_name("table")
            if not tbl or _text(tbl, source) != table_var:
                continue
            field = name_node.child_by_field_name("field")
            if field and field.type == "string":
                exports.add(_get_string_value(field, source))

    return list(exports)


def _extract_table_keys(table_node, source: bytes) -> list[str]:
    keys = []
    for child in table_node.named_children:
        if child.type == "field":
            name = child.child_by_field_name("name")
            if name:
                keys.append(_text(name, source))
    return keys


# ---------------------------------------------------------------------------
# Call extraction
# ---------------------------------------------------------------------------

def _extract_calls(root, source: bytes, ast: FileAST, binding_map: dict[str, str]):
    """Extract function calls with pcall unwrapping and module resolution."""
    seen = set()

    for call_node in _walk_all(root, "function_call"):
        name_node = call_node.child_by_field_name("name")
        if not name_node:
            continue
        callee_text = _text(name_node, source)
        line = call_node.start_point[0] + 1

        if callee_text == "require":
            continue

        # pcall/xpcall handling
        if callee_text in ("pcall", "xpcall"):
            args = _first_child_of_type(call_node, "arguments")
            if args and args.named_child_count > 0:
                actual = args.named_children[0]
                actual_text = _text(actual, source)
                enclosing = _find_enclosing_function(call_node, source)
                key = (enclosing, actual_text, line)
                if key not in seen:
                    seen.add(key)
                    rm, rf = _resolve_call(actual_text, binding_map)
                    ast.calls.append(CallRef(
                        caller_function=enclosing,
                        callee_string=actual_text,
                        line=line,
                        is_pcall_wrapped=True,
                        resolved_module=rm,
                        resolved_function=rf,
                    ))
            continue

        enclosing = _find_enclosing_function(call_node, source)
        key = (enclosing, callee_text, line)
        if key in seen:
            continue
        seen.add(key)

        rm, rf = _resolve_call(callee_text, binding_map)
        ast.calls.append(CallRef(
            caller_function=enclosing, callee_string=callee_text,
            line=line, resolved_module=rm, resolved_function=rf,
        ))


def _resolve_call(callee: str, binding_map: dict[str, str]) -> tuple[str | None, str | None]:
    for sep in (".", ":"):
        if sep in callee:
            parts = callee.split(sep, 1)
            if parts[0] in binding_map:
                return binding_map[parts[0]], parts[1]
    return None, None


# ---------------------------------------------------------------------------
# ngx.ctx tracking
# ---------------------------------------------------------------------------

def _extract_ctx_accesses(root, source: bytes, ast: FileAST):
    """Extract ngx.ctx.field reads and writes."""
    written_locs = set()

    for dot_node in _walk_all(root, "dot_index_expression"):
        table = dot_node.child_by_field_name("table")
        field = dot_node.child_by_field_name("field")
        if not (table and field and table.type == "dot_index_expression"):
            continue
        inner_t = table.child_by_field_name("table")
        inner_f = table.child_by_field_name("field")
        if not (inner_t and inner_f):
            continue
        if _text(inner_t, source) != "ngx" or _text(inner_f, source) != "ctx":
            continue

        field_name = _text(field, source)
        line = field.start_point[0] + 1
        enclosing = _find_enclosing_function(dot_node, source)

        # Determine read vs write: check if this dot_node is inside a variable_list
        # on the LHS of an assignment
        is_write = _is_lhs_of_assignment(dot_node)

        access_type = "write" if is_write else "read"
        loc = (field_name, line)
        if access_type == "write":
            written_locs.add(loc)
        elif loc in written_locs:
            continue

        ast.ctx_accesses.append(ContextAccess(
            field_name=field_name, access_type=access_type,
            function=enclosing, line=line,
        ))


def _is_lhs_of_assignment(node) -> bool:
    """Check if a node is on the left-hand side of an assignment."""
    current = node
    while current.parent:
        if current.parent.type == "variable_list":
            # Check the variable_list's parent is an assignment
            gp = current.parent.parent
            if gp and gp.type == "assignment_statement":
                return True
        if current.parent.type in ("expression_list", "arguments", "return_statement"):
            return False
        current = current.parent
    return False


# ---------------------------------------------------------------------------
# ngx.shared tracking
# ---------------------------------------------------------------------------

def _extract_shared_dict_accesses(root, source: bytes, ast: FileAST):
    """Extract ngx.shared.DICT accesses."""
    for dot_node in _walk_all(root, "dot_index_expression"):
        table = dot_node.child_by_field_name("table")
        field = dot_node.child_by_field_name("field")
        if not (table and field and table.type == "dot_index_expression"):
            continue
        inner_t = table.child_by_field_name("table")
        inner_f = table.child_by_field_name("field")
        if not (inner_t and inner_f):
            continue
        if _text(inner_t, source) != "ngx" or _text(inner_f, source) != "shared":
            continue

        dict_name = _text(field, source)
        line = field.start_point[0] + 1
        enclosing = _find_enclosing_function(dot_node, source)

        operation = "access"
        parent = dot_node.parent
        if parent and parent.type == "method_index_expression":
            method = parent.child_by_field_name("method")
            if method:
                operation = _text(method, source)

        ast.shared_dict_accesses.append(SharedDictAccess(
            dict_name=dict_name, operation=operation,
            function=enclosing, line=line,
        ))


# ---------------------------------------------------------------------------
# Internal redirect tracking (ngx.exec, ngx.location.capture)
# ---------------------------------------------------------------------------

_REDIRECT_PATTERNS = {
    "ngx.exec": "exec",
    "ngx.location.capture": "capture",
    "ngx.location.capture_multi": "capture_multi",
}


def _extract_internal_redirects(root, source: bytes, ast: FileAST):
    """Extract ngx.exec() and ngx.location.capture() calls as internal redirects."""
    for call_node in _walk_all(root, "function_call"):
        name_node = call_node.child_by_field_name("name")
        if not name_node:
            continue
        callee_text = _text(name_node, source)

        redirect_type = _REDIRECT_PATTERNS.get(callee_text)
        if not redirect_type:
            continue

        args = _first_child_of_type(call_node, "arguments")
        if not args or args.named_child_count == 0:
            continue

        line = call_node.start_point[0] + 1
        enclosing = _find_enclosing_function(call_node, source)

        if redirect_type == "capture_multi":
            # ngx.location.capture_multi({{"/a"}, {"/b"}})
            # First arg is a table of tables, each containing a path string
            # AST: table_constructor > field > table_constructor > field > string
            first_arg = args.named_children[0]
            if first_arg.type == "table_constructor":
                for entry in first_arg.named_children:
                    # Each entry may be a field wrapping a table_constructor
                    inner = entry
                    if inner.type == "field":
                        inner = _first_child_of_type(inner, "table_constructor")
                    if inner and inner.type == "table_constructor" and inner.named_child_count > 0:
                        # The first element of the inner table is the path
                        first_elem = inner.named_children[0]
                        # May be wrapped in a field node
                        if first_elem.type == "field":
                            first_elem = first_elem.named_children[0] if first_elem.named_child_count > 0 else first_elem
                        if first_elem.type == "string":
                            target = _get_string_value(first_elem, source)
                            ast.internal_redirects.append(InternalRedirect(
                                target_path=target,
                                redirect_type=redirect_type,
                                function=enclosing,
                                line=line,
                            ))
        else:
            # ngx.exec(path) or ngx.location.capture(path)
            first_arg = args.named_children[0]
            if first_arg.type == "string":
                target = _get_string_value(first_arg, source)
                ast.internal_redirects.append(InternalRedirect(
                    target_path=target,
                    redirect_type=redirect_type,
                    function=enclosing,
                    line=line,
                ))


# ---------------------------------------------------------------------------
# Redis key tracking
# ---------------------------------------------------------------------------

# Operations and their read/write classification
_REDIS_READ_OPS = {"get", "hget", "hgetall", "hmget", "lrange", "smembers",
                   "sismember", "zrange", "zrangebyscore", "exists", "ttl",
                   "type", "keys", "mget", "llen", "scard", "zcard"}
_REDIS_WRITE_OPS = {"set", "hset", "hmset", "del", "delete", "lpush", "rpush",
                    "sadd", "srem", "zadd", "zrem", "incr", "decr", "incrby",
                    "decrby", "setex", "expire", "mset", "append"}
_REDIS_PUBSUB_READ = {"subscribe", "psubscribe"}
_REDIS_PUBSUB_WRITE = {"publish"}


def _classify_redis_op(operation: str) -> str:
    """Classify a Redis operation as read or write."""
    op_lower = operation.lower()
    if op_lower in _REDIS_READ_OPS or op_lower in _REDIS_PUBSUB_READ:
        return "read"
    if op_lower in _REDIS_WRITE_OPS or op_lower in _REDIS_PUBSUB_WRITE:
        return "write"
    return "write"  # default to write for unknown ops (safer for impact analysis)


def _extract_redis_accesses_lua(root, source: bytes, ast: FileAST, binding_map: dict[str, str]):
    """Extract Redis key accesses from Lua code.

    Detects patterns like:
        redis:get("key")
        redis:set("key", value)
        red:hget("hash", "field")
    where `redis`/`red` is bound to a `resty.redis` require, or
    `red` is created by `redis:new()`.
    """
    # Find variables bound to Redis modules
    redis_modules = {"resty.redis", "redis", "resty.redis.connector"}
    redis_vars = set()
    for var, mod in binding_map.items():
        if mod in redis_modules:
            redis_vars.add(var)

    if not redis_vars:
        return

    # Also find variables created by <redis_var>:new()
    # Pattern: local red = redis:new()
    for decl in _walk_all(root, "variable_declaration"):
        assign = _first_child_of_type(decl, "assignment_statement")
        if not assign:
            continue
        el = _first_child_of_type(assign, "expression_list")
        vl = _first_child_of_type(assign, "variable_list")
        if not (el and vl and vl.named_child_count > 0 and el.named_child_count > 0):
            continue
        call = el.named_children[0]
        if call.type != "function_call":
            continue
        name_node = call.child_by_field_name("name")
        if not name_node or name_node.type != "method_index_expression":
            continue
        table = name_node.child_by_field_name("table")
        method = name_node.child_by_field_name("method")
        if table and method and _text(table, source) in redis_vars and _text(method, source) == "new":
            var_node = vl.named_children[0]
            if var_node.type == "identifier":
                redis_vars.add(_text(var_node, source))

    all_redis_ops = _REDIS_READ_OPS | _REDIS_WRITE_OPS | _REDIS_PUBSUB_READ | _REDIS_PUBSUB_WRITE

    for call_node in _walk_all(root, "function_call"):
        name_node = call_node.child_by_field_name("name")
        if not name_node or name_node.type != "method_index_expression":
            continue

        table = name_node.child_by_field_name("table")
        method = name_node.child_by_field_name("method")
        if not (table and method):
            continue

        table_text = _text(table, source)
        method_text = _text(method, source)

        # Check if this is a call on a known Redis variable
        if table_text not in redis_vars:
            continue

        if method_text.lower() not in all_redis_ops:
            continue

        args = _first_child_of_type(call_node, "arguments")
        key_name = "<dynamic>"
        if args and args.named_child_count > 0:
            first_arg = args.named_children[0]
            if first_arg.type == "string":
                key_name = _get_string_value(first_arg, source)

        line = call_node.start_point[0] + 1
        enclosing = _find_enclosing_function(call_node, source)

        ast.redis_accesses.append(RedisKeyAccess(
            key_name=key_name,
            operation=method_text,
            access_type=_classify_redis_op(method_text),
            function=enclosing,
            line=line,
        ))


# ---------------------------------------------------------------------------
# HTTP call tracking (Lua)
# ---------------------------------------------------------------------------

def _extract_http_calls_lua(root, source: bytes, ast: FileAST, binding_map: dict[str, str]):
    """Extract HTTP client calls from Lua code.

    Detects patterns like:
        httpc:request_uri("http://python-svc:8080/api/process", {...})
        ngx.location.capture("/internal/api")
    """
    http_modules = {"resty.http"}
    http_vars = set()
    for var, mod in binding_map.items():
        if mod in http_modules:
            http_vars.add(var)

    # Also find variables created by <http_var>.new()
    # Pattern: local httpc = http.new()
    for decl in _walk_all(root, "variable_declaration"):
        assign = _first_child_of_type(decl, "assignment_statement")
        if not assign:
            continue
        el = _first_child_of_type(assign, "expression_list")
        vl = _first_child_of_type(assign, "variable_list")
        if not (el and vl and vl.named_child_count > 0 and el.named_child_count > 0):
            continue
        call = el.named_children[0]
        if call.type != "function_call":
            continue
        name_node = call.child_by_field_name("name")
        if not name_node:
            continue
        callee = _text(name_node, source)
        # http.new() or http:new()
        for hvar in list(http_vars):
            if callee in (f"{hvar}.new", f"{hvar}:new"):
                var_node = vl.named_children[0]
                if var_node.type == "identifier":
                    http_vars.add(_text(var_node, source))
                break

    for call_node in _walk_all(root, "function_call"):
        name_node = call_node.child_by_field_name("name")
        if not name_node:
            continue

        callee_text = _text(name_node, source)
        args = _first_child_of_type(call_node, "arguments")
        if not args or args.named_child_count == 0:
            continue

        line = call_node.start_point[0] + 1
        enclosing = _find_enclosing_function(call_node, source)
        url_or_path = None
        method = "unknown"

        # httpc:request_uri(url, params) pattern
        if name_node.type == "method_index_expression":
            table = name_node.child_by_field_name("table")
            method_node = name_node.child_by_field_name("method")
            if table and method_node:
                table_text = _text(table, source)
                method_text = _text(method_node, source)
                if table_text in http_vars and method_text == "request_uri":
                    first_arg = args.named_children[0]
                    if first_arg.type == "string":
                        url_or_path = _get_string_value(first_arg, source)
                        # Try to detect method from params table
                        if args.named_child_count > 1:
                            params = args.named_children[1]
                            if params.type == "table_constructor":
                                for field_node in params.named_children:
                                    if field_node.type == "field":
                                        name = field_node.child_by_field_name("name")
                                        if name and _text(name, source) == "method":
                                            val = field_node.child_by_field_name("value")
                                            if val and val.type == "string":
                                                method = _get_string_value(val, source)

        # ngx.location.capture(path) — already tracked as redirect, but also as HTTP
        elif callee_text == "ngx.location.capture":
            first_arg = args.named_children[0]
            if first_arg.type == "string":
                url_or_path = _get_string_value(first_arg, source)
                method = "GET"

        if url_or_path:
            ast.http_calls.append(HttpCallRef(
                url_or_path=url_or_path,
                method=method,
                function=enclosing,
                line=line,
            ))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_lua_file(file_path: str) -> FileAST:
    """Parse a Lua file and extract all code entities."""
    parser = Parser(LUA)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="lua")

    # 1. Detect module pattern
    ast.module_info = _detect_module_pattern(root, source)

    # 2. Extract requires and build binding map
    binding_map = _extract_requires(root, source, ast)

    # 3. Extract function definitions
    _extract_functions(root, source, ast, ast.module_info)

    # 4. Find exports
    ast.exports = _find_exports(root, source, ast.module_info)

    # 5. Mark exported functions as public
    for func in ast.functions:
        func_base = func.name.split(".")[-1].split(":")[-1]
        if func_base in ast.exports:
            func.visibility = "public"

    # 6. Extract calls
    _extract_calls(root, source, ast, binding_map)

    # 7. ngx.ctx accesses
    _extract_ctx_accesses(root, source, ast)

    # 8. ngx.shared accesses
    _extract_shared_dict_accesses(root, source, ast)

    # 9. Internal redirects (ngx.exec, ngx.location.capture)
    _extract_internal_redirects(root, source, ast)

    # 10. Redis key accesses
    _extract_redis_accesses_lua(root, source, ast, binding_map)

    # 11. HTTP client calls
    _extract_http_calls_lua(root, source, ast, binding_map)

    return ast
