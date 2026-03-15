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

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef

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


def parse_python_file(file_path: str) -> FileAST:
    """Parse a Python file and extract all code entities."""
    parser = Parser(PY)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="python")
    binding_map: dict[str, str] = {}

    # --- Imports ---
    for node in _walk_all(root, "import_statement"):
        name = node.child_by_field_name("name")
        if name:
            mod = _text(name, source)
            ast.imports.append(ImportRef(
                module_string=mod, line=node.start_point[0] + 1,
                import_type="import",
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

        ast.classes.append(ClassDef(
            name=class_name,
            line=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_class=parent_class,
            methods=methods,
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

        ast.functions.append(FunctionDef(
            name=func_name,
            line=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            visibility=visibility,
            params=params,
            is_method=is_method,
            decorators=decorators,
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

    return ast
