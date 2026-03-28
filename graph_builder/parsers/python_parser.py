"""Python parser for the code knowledge graph.

Extracts:
  - Import statements (import, from...import, relative imports)
  - Class definitions with inheritance
  - Function/method definitions with decorators
  - Function calls with module resolution
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_python as tspython

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef, RedisKeyAccess, HttpCallRef

PY = Language(tspython.language())


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _first_child_of_type(node, type_name: str):
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _walk_all(root, type_name: str):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == type_name:
            yield node
        stack.extend(reversed(node.children))


def _find_enclosing(node, source: bytes) -> str:
    """Find enclosing function or class.method name."""
    current = node.parent
    func_name = None
    class_name = None
    while current:
        if current.type == "function_definition" and func_name is None:
            name = current.child_by_field_name("name")
            if name:
                func_name = _text(name, source)
        if current.type == "class_definition" and class_name is None:
            name = current.child_by_field_name("name")
            if name:
                class_name = _text(name, source)
        current = current.parent
    if class_name and func_name:
        return f"{class_name}.{func_name}"
    return func_name or "<module>"


def _file_path_to_module(file_path: str) -> str | None:
    """Convert a file path to a Python module path.

    E.g., 'graph_builder/parsers/js_parser.py' -> 'graph_builder.parsers.js_parser'
    """
    p = Path(file_path)
    # Strip .py extension
    if p.suffix != ".py":
        return None
    # Convert path separators to dots, strip leading dots
    parts = list(p.with_suffix("").parts)
    if not parts:
        return None
    return ".".join(parts)


def parse_python_file(file_path: str) -> FileAST:
    """Parse a Python file and extract all code entities."""
    parser = Parser(PY)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="python")
    binding_map: dict[str, str] = {}
    _module_path = _file_path_to_module(file_path)

    # --- Imports ---
    for node in _walk_all(root, "import_statement"):
        name = node.child_by_field_name("name")
        if name:
            mod = _text(name, source)
            # For `import redis`, the top-level name is the binding
            top_level = mod.split(".")[0]
            binding_map[top_level] = mod
            ast.imports.append(ImportRef(
                module_string=mod, line=node.start_point[0] + 1,
                import_type="import",
                local_binding=top_level,
            ))

    for node in _walk_all(root, "import_from_statement"):
        mod_node = node.child_by_field_name("module_name")
        # module_name includes the relative_import prefix (dots) already
        full_mod = _text(mod_node, source).replace(" ", "") if mod_node else ""

        # Track imported names for binding
        imported_names = []
        for child in node.children:
            if child.type == "dotted_name" and child != mod_node:
                imported_names.append(_text(child, source))
            if child.type == "aliased_import":
                alias = child.child_by_field_name("alias")
                name = child.child_by_field_name("name")
                if alias:
                    binding_map[_text(alias, source)] = full_mod
                    imported_names.append(_text(alias, source))
                elif name:
                    imported_names.append(_text(name, source))

        for name in imported_names:
            binding_map[name] = full_mod

        ast.imports.append(ImportRef(
            module_string=full_mod, line=node.start_point[0] + 1,
            import_type="from_import",
            local_binding=", ".join(imported_names) if imported_names else None,
        ))

    # --- Classes ---
    for node in _walk_all(root, "class_definition"):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        class_name = _text(name_node, source)

        parent_class = None
        superclasses = node.child_by_field_name("superclasses")
        if superclasses:
            args = [_text(c, source) for c in superclasses.named_children
                    if c.type in ("identifier", "attribute")]
            if args:
                parent_class = args[0]

        methods = []
        body = node.child_by_field_name("body")
        if body:
            for method in _walk_all(body, "function_definition"):
                mn = method.child_by_field_name("name")
                if mn:
                    methods.append(_text(mn, source))

        # Build qualified name for class
        cls_qn = None
        if _module_path:
            cls_qn = f"{_module_path}.{class_name}"

        ast.classes.append(ClassDef(
            name=class_name,
            line=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_class=parent_class,
            methods=methods,
            qualified_name=cls_qn,
        ))

    # --- Functions ---
    for node in _walk_all(root, "function_definition"):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        func_name = _text(name_node, source)

        # Determine visibility
        visibility = "public"
        if func_name.startswith("_") and not func_name.startswith("__"):
            visibility = "private"

        # Check if it's a method (inside a class)
        is_method = False
        parent = node.parent
        while parent:
            if parent.type == "class_definition":
                is_method = True
                break
            if parent.type == "function_definition":
                break
            parent = parent.parent

        # Extract decorators
        decorators = []
        if node.parent and node.parent.type == "decorated_definition":
            for child in node.parent.children:
                if child.type == "decorator":
                    decorators.append(_text(child, source))

        # Extract params
        params = []
        param_node = node.child_by_field_name("parameters")
        if param_node:
            for p in param_node.named_children:
                if p.type == "identifier":
                    params.append(_text(p, source))
                elif p.type in ("typed_parameter", "default_parameter", "typed_default_parameter"):
                    pname = p.child_by_field_name("name") or p.named_children[0] if p.named_child_count > 0 else None
                    if pname:
                        params.append(_text(pname, source))

        # Build qualified name for function
        func_qn = None
        if _module_path:
            # Find enclosing class name for methods
            enclosing_class = None
            p = node.parent
            while p:
                if p.type == "class_definition":
                    cn = p.child_by_field_name("name")
                    if cn:
                        enclosing_class = _text(cn, source)
                    break
                p = p.parent
            if enclosing_class:
                func_qn = f"{_module_path}.{enclosing_class}.{func_name}"
            else:
                func_qn = f"{_module_path}.{func_name}"

        ast.functions.append(FunctionDef(
            name=func_name,
            line=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            visibility=visibility,
            params=params,
            is_method=is_method,
            decorators=decorators,
            qualified_name=func_qn,
        ))

    # --- Calls ---
    for node in _walk_all(root, "call"):
        func = node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        enclosing = _find_enclosing(node, source)

        rm, rf = None, None
        if "." in callee:
            parts = callee.split(".", 1)
            if parts[0] in binding_map:
                rm = binding_map[parts[0]]
                rf = parts[1]

        ast.calls.append(CallRef(
            caller_function=enclosing,
            callee_string=callee,
            line=node.start_point[0] + 1,
            resolved_module=rm,
            resolved_function=rf,
        ))

    # --- Exports (top-level public functions and classes) ---
    for func in ast.functions:
        if func.visibility == "public" and not func.is_method:
            ast.exports.append(func.name)
    for cls in ast.classes:
        ast.exports.append(cls.name)

    # --- Redis accesses ---
    _extract_redis_accesses_python(root, source, ast, binding_map)

    # --- HTTP calls ---
    _extract_http_calls_python(root, source, ast, binding_map)

    return ast


# --- Redis access detection ---

_PY_REDIS_READ_OPS = {"get", "hget", "hgetall", "hmget", "lrange", "smembers",
                      "sismember", "zrange", "zrangebyscore", "exists", "ttl",
                      "type", "keys", "mget", "llen", "scard", "zcard"}
_PY_REDIS_WRITE_OPS = {"set", "hset", "hmset", "delete", "lpush", "rpush",
                       "sadd", "srem", "zadd", "zrem", "incr", "decr", "incrby",
                       "decrby", "setex", "expire", "mset", "append"}
_PY_REDIS_PUBSUB_READ = {"subscribe", "psubscribe"}
_PY_REDIS_PUBSUB_WRITE = {"publish"}

_PY_ALL_REDIS_OPS = _PY_REDIS_READ_OPS | _PY_REDIS_WRITE_OPS | _PY_REDIS_PUBSUB_READ | _PY_REDIS_PUBSUB_WRITE


def _classify_redis_op_py(operation: str) -> str:
    op = operation.lower()
    if op in _PY_REDIS_READ_OPS or op in _PY_REDIS_PUBSUB_READ:
        return "read"
    return "write"


def _extract_redis_accesses_python(root, source: bytes, ast: FileAST, binding_map: dict[str, str]):
    """Detect Redis operations in Python code.

    Patterns: redis.get("key"), redis_client.set("key", val), r.hget("hash", "field")
    """
    redis_modules = {"redis", "redis.client", "aioredis"}
    redis_vars = set()
    for var, mod in binding_map.items():
        if mod in redis_modules or "redis" in mod.lower():
            redis_vars.add(var)

    # Also find variables created by redis.Redis(), redis.StrictRedis(), redis.from_url()
    # Pattern: redis_client = redis.Redis(...)
    redis_factories = {"Redis", "StrictRedis", "from_url", "RedisCluster", "StrictRedisCluster"}
    for node in _walk_all(root, "assignment"):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if not (left and right and right.type == "call"):
            continue
        func = right.child_by_field_name("function")
        if not func:
            continue

        is_redis_factory = False

        if func.type == "attribute":
            # Pattern: redis.Redis(...), redis.StrictRedis(...)
            obj = func.child_by_field_name("object")
            attr = func.child_by_field_name("attribute")
            if obj and attr and _text(obj, source) in redis_vars and _text(attr, source) in redis_factories:
                is_redis_factory = True
        elif func.type == "identifier":
            # Pattern: RedisCluster(...) — direct call after from-import
            if _text(func, source) in redis_factories:
                is_redis_factory = True

        if is_redis_factory:
            if left.type == "identifier":
                redis_vars.add(_text(left, source))
            elif left.type == "attribute":
                # Pattern: self.connection = RedisCluster(...)
                redis_vars.add(_text(left, source))

    for node in _walk_all(root, "call"):
        func = node.child_by_field_name("function")
        if not func or func.type != "attribute":
            continue

        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if not (obj and attr):
            continue

        obj_text = _text(obj, source)
        method_text = _text(attr, source)

        if obj_text not in redis_vars:
            continue

        if method_text.lower() not in _PY_ALL_REDIS_OPS:
            continue

        # Extract key name from first argument
        args = node.child_by_field_name("arguments")
        key_name = "<dynamic>"
        if args:
            for child in args.named_children:
                if child.type == "string":
                    # Strip quotes
                    raw = _text(child, source)
                    key_name = raw.strip("\"'")
                    break
                if child.type != "comment":
                    break

        line = node.start_point[0] + 1
        enclosing = _find_enclosing(node, source)

        ast.redis_accesses.append(RedisKeyAccess(
            key_name=key_name,
            operation=method_text,
            access_type=_classify_redis_op_py(method_text),
            function=enclosing,
            line=line,
        ))


# --- HTTP call detection ---

_HTTP_METHOD_MAP = {
    "get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE",
    "patch": "PATCH", "head": "HEAD", "options": "OPTIONS",
}


def _extract_http_calls_python(root, source: bytes, ast: FileAST, binding_map: dict[str, str]):
    """Detect HTTP client calls in Python code.

    Patterns: requests.get(url), requests.post(url), urllib.request.urlopen(url),
              httpx.get(url), session.get(url)
    """
    http_modules = {"requests", "httpx", "urllib", "urllib.request", "aiohttp"}
    http_vars = set()
    for var, mod in binding_map.items():
        if mod in http_modules or "requests" in mod.lower() or "httpx" in mod.lower():
            http_vars.add(var)

    # Also add direct module names
    http_vars.update({"requests", "httpx"})

    for node in _walk_all(root, "call"):
        func = node.child_by_field_name("function")
        if not func or func.type != "attribute":
            continue

        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if not (obj and attr):
            continue

        obj_text = _text(obj, source)
        method_text = _text(attr, source)

        method_upper = _HTTP_METHOD_MAP.get(method_text.lower())
        if not method_upper:
            # Also handle request_uri, urlopen
            if method_text == "urlopen":
                method_upper = "GET"
            elif method_text == "request":
                method_upper = "unknown"
            else:
                continue

        if obj_text not in http_vars:
            continue

        # Extract URL from first argument
        args = node.child_by_field_name("arguments")
        url = None
        if args:
            for child in args.named_children:
                if child.type == "string":
                    raw = _text(child, source)
                    url = raw.strip("\"'")
                    break
                if child.type != "comment":
                    break

        if url:
            line = node.start_point[0] + 1
            enclosing = _find_enclosing(node, source)
            ast.http_calls.append(HttpCallRef(
                url_or_path=url,
                method=method_upper,
                function=enclosing,
                line=line,
            ))
