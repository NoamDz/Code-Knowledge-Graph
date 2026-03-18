"""Go parser for the code knowledge graph.

Extracts:
  - Package declaration
  - Imports (single and grouped)
  - Function definitions (including receivers)
  - Struct/interface definitions → ClassDef
  - Function calls
  - Exports (Go rule: uppercase first letter)
  - HTTP handlers: http.HandleFunc, mux patterns
  - Unix socket listeners: net.Listen("unix", path)
"""

from __future__ import annotations

import re
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_go as tsgo

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef, HttpCallRef

GO = Language(tsgo.language())


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
    """Walk up the tree to find the enclosing function name."""
    current = node.parent
    while current:
        if current.type in ("function_declaration", "method_declaration"):
            name_node = current.child_by_field_name("name")
            if name_node:
                # For methods, include receiver type
                if current.type == "method_declaration":
                    receiver = current.child_by_field_name("receiver")
                    if receiver:
                        # Extract type from receiver parameter list
                        for child in receiver.named_children:
                            type_node = child.child_by_field_name("type")
                            if type_node:
                                type_text = _text(type_node, source).lstrip("*")
                                return f"{type_text}.{_text(name_node, source)}"
                return _text(name_node, source)
        current = current.parent
    return "<module>"


def _extract_params(node, source: bytes) -> list[str]:
    """Extract parameter names from a function's parameter list."""
    params = []
    pnode = node.child_by_field_name("parameters")
    if pnode:
        for child in pnode.named_children:
            if child.type == "parameter_declaration":
                # May have multiple names: func foo(a, b int)
                for name_child in child.children:
                    if name_child.type == "identifier":
                        params.append(_text(name_child, source))
    return params


def _is_exported(name: str) -> bool:
    """Go rule: exported names start with an uppercase letter."""
    return bool(name) and name[0].isupper()


def parse_go_file(file_path: str) -> FileAST:
    """Parse a Go file and extract all code entities."""
    parser = Parser(GO)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="go")
    binding_map: dict[str, str] = {}

    # --- Package declaration ---
    for pkg_node in _walk_all(root, "package_clause"):
        name_node = _first_child_of_type(pkg_node, "package_identifier")
        if name_node:
            ast.module_name = _text(name_node, source)
        break

    # --- Imports ---
    for imp_decl in _walk_all(root, "import_declaration"):
        # Single import: import "fmt"
        for spec in _walk_all(imp_decl, "import_spec"):
            path_node = spec.child_by_field_name("path")
            if path_node:
                mod_str = _text(path_node, source).strip('"')
                alias_node = spec.child_by_field_name("name")
                local_binding = None
                if alias_node:
                    local_binding = _text(alias_node, source)
                else:
                    # Default binding is the last path segment
                    local_binding = mod_str.rsplit("/", 1)[-1]

                binding_map[local_binding] = mod_str

                ast.imports.append(ImportRef(
                    module_string=mod_str,
                    line=spec.start_point[0] + 1,
                    import_type="import",
                    local_binding=local_binding,
                ))

        # Also handle interpreted_string_literal directly under import_declaration
        for child in imp_decl.children:
            if child.type == "interpreted_string_literal":
                mod_str = _text(child, source).strip('"')
                local_binding = mod_str.rsplit("/", 1)[-1]
                binding_map[local_binding] = mod_str
                ast.imports.append(ImportRef(
                    module_string=mod_str,
                    line=child.start_point[0] + 1,
                    import_type="import",
                    local_binding=local_binding,
                ))

    # --- Struct and interface definitions → ClassDef ---
    for type_decl in _walk_all(root, "type_declaration"):
        for type_spec in type_decl.children:
            if type_spec.type != "type_spec":
                continue
            name_node = type_spec.child_by_field_name("name")
            type_body = type_spec.child_by_field_name("type")
            if not name_node or not type_body:
                continue

            type_name = _text(name_node, source)
            if type_body.type in ("struct_type", "interface_type"):
                methods = []
                # For interfaces, collect method signatures
                if type_body.type == "interface_type":
                    for child in type_body.named_children:
                        if child.type == "method_spec":
                            mn = child.child_by_field_name("name")
                            if mn:
                                methods.append(_text(mn, source))

                type_qn = f"{ast.module_name}.{type_name}" if ast.module_name else type_name
                ast.classes.append(ClassDef(
                    name=type_name,
                    line=type_spec.start_point[0] + 1,
                    line_end=type_spec.end_point[0] + 1,
                    methods=methods,
                    qualified_name=type_qn,
                ))

                if _is_exported(type_name):
                    ast.exports.append(type_name)

    # --- Function declarations ---
    for func_node in _walk_all(root, "function_declaration"):
        name_node = func_node.child_by_field_name("name")
        if not name_node:
            continue
        func_name = _text(name_node, source)
        params = _extract_params(func_node, source)
        visibility = "public" if _is_exported(func_name) else "private"

        func_qn = f"{ast.module_name}.{func_name}" if ast.module_name else func_name
        ast.functions.append(FunctionDef(
            name=func_name,
            line=func_node.start_point[0] + 1,
            line_end=func_node.end_point[0] + 1,
            visibility=visibility,
            params=params,
            qualified_name=func_qn,
        ))

        if _is_exported(func_name):
            ast.exports.append(func_name)

    # --- Method declarations (with receivers) ---
    for method_node in _walk_all(root, "method_declaration"):
        name_node = method_node.child_by_field_name("name")
        if not name_node:
            continue
        method_name = _text(name_node, source)

        # Get receiver type
        receiver = method_node.child_by_field_name("receiver")
        receiver_type = None
        if receiver:
            for child in receiver.named_children:
                type_node = child.child_by_field_name("type")
                if type_node:
                    receiver_type = _text(type_node, source).lstrip("*")

        full_name = f"{receiver_type}.{method_name}" if receiver_type else method_name
        params = _extract_params(method_node, source)
        visibility = "public" if _is_exported(method_name) else "private"

        # Qualified name: package.Type.Method
        if ast.module_name and receiver_type:
            method_qn = f"{ast.module_name}.{receiver_type}.{method_name}"
        elif ast.module_name:
            method_qn = f"{ast.module_name}.{method_name}"
        else:
            method_qn = full_name

        ast.functions.append(FunctionDef(
            name=full_name,
            line=method_node.start_point[0] + 1,
            line_end=method_node.end_point[0] + 1,
            visibility=visibility,
            params=params,
            is_method=True,
            qualified_name=method_qn,
        ))

        # Add methods to their ClassDef
        if receiver_type:
            for cls in ast.classes:
                if cls.name == receiver_type:
                    cls.methods.append(method_name)
                    break

        if _is_exported(method_name):
            ast.exports.append(method_name)

    # --- Calls ---
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        enclosing = _find_enclosing(call_node, source)

        rm, rf = None, None
        if "." in callee:
            parts = callee.split(".", 1)
            if parts[0] in binding_map:
                rm = binding_map[parts[0]]
                rf = parts[1]

        ast.calls.append(CallRef(
            caller_function=enclosing,
            callee_string=callee,
            line=call_node.start_point[0] + 1,
            resolved_module=rm,
            resolved_function=rf,
        ))

        # --- HTTP handler detection ---
        # http.HandleFunc("/path", handler) or router.HandleFunc("/path", handler)
        if callee.endswith("HandleFunc") or callee.endswith("Handle"):
            args = call_node.child_by_field_name("arguments")
            if args and args.named_child_count >= 1:
                first_arg = args.named_children[0]
                if first_arg.type == "interpreted_string_literal":
                    path = _text(first_arg, source).strip('"')
                    # Determine HTTP method from chained .Methods("GET") call
                    method = _detect_http_method(call_node, source)
                    ast.http_calls.append(HttpCallRef(
                        url_or_path=path,
                        method=method,
                        function=enclosing,
                        line=call_node.start_point[0] + 1,
                    ))

        # --- Unix socket listener detection ---
        # net.Listen("unix", "/path/to/socket.sock")
        if callee in ("net.Listen", "Listen"):
            args = call_node.child_by_field_name("arguments")
            if args and args.named_child_count >= 2:
                first_arg = args.named_children[0]
                second_arg = args.named_children[1]
                if first_arg.type == "interpreted_string_literal":
                    network = _text(first_arg, source).strip('"')
                    if network == "unix":
                        socket_path = _text(second_arg, source).strip('"')
                        ast.warnings.append(f"unix_socket:{socket_path}")

    return ast


def _detect_http_method(call_node, source: bytes) -> str:
    """Try to detect HTTP method from a chained .Methods("GET") call."""
    # Check if parent is a call_expression with .Methods
    parent = call_node.parent
    while parent:
        if parent.type == "call_expression":
            func = parent.child_by_field_name("function")
            if func and _text(func, source).endswith(".Methods"):
                args = parent.child_by_field_name("arguments")
                if args and args.named_child_count >= 1:
                    method_arg = args.named_children[0]
                    if method_arg.type == "interpreted_string_literal":
                        return _text(method_arg, source).strip('"')
            break
        parent = parent.parent

    # Check sibling: .Methods("GET") called after HandleFunc
    # In gorilla/mux, it's chained: router.HandleFunc("/path", h).Methods("GET")
    parent = call_node.parent
    if parent and parent.type == "selector_expression":
        # The parent of the selector might be another call_expression
        grandparent = parent.parent
        if grandparent and grandparent.type == "call_expression":
            func = grandparent.child_by_field_name("function")
            if func:
                func_text = _text(func, source)
                if func_text.endswith("Methods"):
                    args = grandparent.child_by_field_name("arguments")
                    if args and args.named_child_count >= 1:
                        method_arg = args.named_children[0]
                        if method_arg.type == "interpreted_string_literal":
                            return _text(method_arg, source).strip('"')

    return "unknown"
