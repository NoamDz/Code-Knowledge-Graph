"""JavaScript parser for the code knowledge graph.

Extracts:
  - require() (CommonJS) and import (ESM) statements
  - Destructured imports: const { a, b } = require("mod")
  - Class definitions with inheritance
  - Function/method definitions (function, arrow, class methods)
  - module.exports / export declarations
  - Function calls
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjs

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef

JS = Language(tsjs.language())


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


def _get_string_value(node, source: bytes) -> str:
    frag = _first_child_of_type(node, "string_fragment")
    if frag:
        return _text(frag, source)
    return _text(node, source).strip("\"'`")


def _find_enclosing(node, source: bytes) -> str:
    current = node.parent
    func_name = None
    class_name = None
    while current:
        if current.type == "method_definition" and func_name is None:
            n = current.child_by_field_name("name")
            if n:
                func_name = _text(n, source)
        if current.type in ("function_declaration", "generator_function_declaration") and func_name is None:
            n = current.child_by_field_name("name")
            if n:
                func_name = _text(n, source)
        if current.type == "variable_declarator" and func_name is None:
            n = current.child_by_field_name("name")
            val = current.child_by_field_name("value")
            if n and val and val.type in ("arrow_function", "function_expression"):
                func_name = _text(n, source)
        if current.type == "class_declaration" and class_name is None:
            n = current.child_by_field_name("name")
            if n:
                class_name = _text(n, source)
        current = current.parent
    if class_name and func_name:
        return f"{class_name}.{func_name}"
    return func_name or "<module>"


def _extract_params(node, source: bytes) -> list[str]:
    params = []
    pnode = node.child_by_field_name("parameters")
    if pnode:
        for p in pnode.named_children:
            if p.type == "identifier":
                params.append(_text(p, source))
            elif p.type == "assignment_pattern":
                left = p.child_by_field_name("left")
                if left:
                    params.append(_text(left, source))
            elif p.type == "rest_pattern":
                params.append(_text(p, source))
            elif p.type == "object_pattern":
                params.append("{...}")
            elif p.type == "array_pattern":
                params.append("[...]")
    return params


def parse_js_file(file_path: str) -> FileAST:
    """Parse a JavaScript file and extract all code entities."""
    parser = Parser(JS)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="javascript")
    binding_map: dict[str, str] = {}

    # --- CommonJS require() ---
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func or func.type != "identifier" or _text(func, source) != "require":
            continue
        args = call_node.child_by_field_name("arguments")
        if not args or args.named_child_count == 0:
            continue
        first_arg = args.named_children[0]
        if first_arg.type != "string":
            continue
        mod_str = _get_string_value(first_arg, source)

        # Find binding: const x = require("mod") or const { a, b } = require("mod")
        local_binding = None
        parent = call_node.parent  # variable_declarator
        if parent and parent.type == "variable_declarator":
            name_node = parent.child_by_field_name("name")
            if name_node:
                if name_node.type == "identifier":
                    local_binding = _text(name_node, source)
                    binding_map[local_binding] = mod_str
                elif name_node.type == "object_pattern":
                    # Destructured: const { a, b } = require("mod")
                    names = []
                    for child in name_node.named_children:
                        if child.type == "shorthand_property_identifier_pattern":
                            n = _text(child, source)
                            names.append(n)
                            binding_map[n] = mod_str
                        elif child.type == "pair_pattern":
                            val = child.child_by_field_name("value")
                            if val:
                                n = _text(val, source)
                                names.append(n)
                                binding_map[n] = mod_str
                    local_binding = ", ".join(names) if names else None

        ast.imports.append(ImportRef(
            module_string=mod_str,
            line=call_node.start_point[0] + 1,
            import_type="require",
            local_binding=local_binding,
        ))

    # --- ESM import ---
    for imp in _walk_all(root, "import_statement"):
        source_node = imp.child_by_field_name("source")
        if not source_node:
            continue
        mod_str = _get_string_value(source_node, source)

        # Extract imported names
        names = []
        for child in imp.children:
            if child.type == "import_clause":
                for ic_child in child.children:
                    if ic_child.type == "identifier":
                        n = _text(ic_child, source)
                        names.append(n)
                        binding_map[n] = mod_str
                    if ic_child.type == "named_imports":
                        for spec in ic_child.named_children:
                            if spec.type == "import_specifier":
                                alias = spec.child_by_field_name("alias")
                                name = spec.child_by_field_name("name")
                                n = _text(alias or name, source) if (alias or name) else None
                                if n:
                                    names.append(n)
                                    binding_map[n] = mod_str

        ast.imports.append(ImportRef(
            module_string=mod_str,
            line=imp.start_point[0] + 1,
            import_type="import",
            local_binding=", ".join(names) if names else None,
        ))

    # --- Classes ---
    for cls_node in _walk_all(root, "class_declaration"):
        name_node = cls_node.child_by_field_name("name")
        if not name_node:
            continue
        class_name = _text(name_node, source)

        parent_class = None
        heritage = _first_child_of_type(cls_node, "class_heritage")
        if heritage and heritage.named_child_count > 0:
            parent_class = _text(heritage.named_children[0], source)

        methods = []
        body = cls_node.child_by_field_name("body")
        if body:
            for member in body.named_children:
                if member.type == "method_definition":
                    mn = member.child_by_field_name("name")
                    if mn:
                        mname = _text(mn, source)
                        methods.append(mname)
                        params = _extract_params(member, source)
                        ast.functions.append(FunctionDef(
                            name=mname,
                            line=member.start_point[0] + 1,
                            line_end=member.end_point[0] + 1,
                            visibility="private" if mname.startswith("_") else "public",
                            params=params,
                            is_method=True,
                        ))

        ast.classes.append(ClassDef(
            name=class_name,
            line=cls_node.start_point[0] + 1,
            line_end=cls_node.end_point[0] + 1,
            parent_class=parent_class,
            methods=methods,
        ))

    # --- Top-level functions ---
    for func_node in _walk_all(root, "function_declaration"):
        name_node = func_node.child_by_field_name("name")
        if not name_node:
            continue
        ast.functions.append(FunctionDef(
            name=_text(name_node, source),
            line=func_node.start_point[0] + 1,
            line_end=func_node.end_point[0] + 1,
            visibility="public",
            params=_extract_params(func_node, source),
        ))

    # --- Arrow functions assigned to const/let/var ---
    for decl in _walk_all(root, "variable_declarator"):
        name_node = decl.child_by_field_name("name")
        val_node = decl.child_by_field_name("value")
        if not (name_node and val_node):
            continue
        if name_node.type != "identifier":
            continue
        if val_node.type not in ("arrow_function", "function_expression"):
            continue
        fname = _text(name_node, source)
        # Skip if already captured (e.g., inside a class)
        if any(f.name == fname for f in ast.functions):
            continue
        ast.functions.append(FunctionDef(
            name=fname,
            line=val_node.start_point[0] + 1,
            line_end=val_node.end_point[0] + 1,
            visibility="public",
            params=_extract_params(val_node, source),
        ))

    # --- Calls ---
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)

        # Skip require calls (already handled)
        if callee == "require":
            continue

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

    # --- Exports ---
    # module.exports = { ... }
    for assign in _walk_all(root, "assignment_expression"):
        left = assign.child_by_field_name("left")
        if left and _text(left, source) == "module.exports":
            right = assign.child_by_field_name("right")
            if right and right.type == "object":
                for child in right.named_children:
                    if child.type == "shorthand_property_identifier":
                        ast.exports.append(_text(child, source))
                    elif child.type == "pair":
                        key = child.child_by_field_name("key")
                        if key:
                            ast.exports.append(_text(key, source))
    # export default / export { ... }
    for exp in _walk_all(root, "export_statement"):
        decl = exp.child_by_field_name("declaration")
        if decl:
            name = decl.child_by_field_name("name")
            if name:
                ast.exports.append(_text(name, source))

    return ast
