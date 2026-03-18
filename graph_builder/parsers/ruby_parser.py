"""Ruby parser for the code knowledge graph.

Extracts:
  - require / require_relative imports
  - Module and class definitions with inheritance
  - include / extend (mixins)
  - Method definitions with visibility (public/private)
  - attr_reader/attr_writer/attr_accessor as implicit methods
  - Method calls
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_ruby as tsruby

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef

RB = Language(tsruby.language())


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
    content = _first_child_of_type(node, "string_content")
    if content:
        return _text(content, source)
    return _text(node, source).strip("\"'")


def _find_enclosing(node, source: bytes) -> str:
    current = node.parent
    method_name = None
    class_name = None
    while current:
        if current.type == "method" and method_name is None:
            n = current.child_by_field_name("name")
            if n:
                method_name = _text(n, source)
        if current.type == "class" and class_name is None:
            n = current.child_by_field_name("name")
            if n:
                class_name = _text(n, source)
        if current.type == "module" and class_name is None:
            n = current.child_by_field_name("name")
            if n:
                class_name = _text(n, source)
        current = current.parent
    if class_name and method_name:
        return f"{class_name}#{method_name}"
    return method_name or "<module>"


def _find_enclosing_module_or_class(node, source: bytes) -> str | None:
    """Walk up the tree to find enclosing module/class name chain."""
    names = []
    current = node.parent
    while current:
        if current.type in ("class", "module"):
            n = current.child_by_field_name("name")
            if n:
                names.append(_text(n, source))
        current = current.parent
    if names:
        return "::".join(reversed(names))
    return None


def parse_ruby_file(file_path: str) -> FileAST:
    """Parse a Ruby file and extract all code entities."""
    parser = Parser(RB)
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="ruby")

    # --- Imports (require / require_relative) ---
    for call_node in _walk_all(root, "call"):
        method = call_node.child_by_field_name("method")
        if not method:
            continue
        method_name = _text(method, source)
        if method_name not in ("require", "require_relative"):
            continue

        args = call_node.child_by_field_name("arguments")
        if not args or args.named_child_count == 0:
            continue
        first_arg = args.named_children[0]
        if first_arg.type == "string":
            mod_str = _get_string_value(first_arg, source)
            ast.imports.append(ImportRef(
                module_string=mod_str,
                line=call_node.start_point[0] + 1,
                import_type=method_name,
            ))

    # --- Classes and modules ---
    for class_node in _walk_all(root, "class"):
        name_node = class_node.child_by_field_name("name")
        if not name_node:
            continue
        class_name = _text(name_node, source)

        # Superclass
        parent_class = None
        superclass = class_node.child_by_field_name("superclass")
        if superclass:
            parent_class = _text(superclass, source)

        # Collect methods, mixins, attr_* within this class body
        body = class_node.child_by_field_name("body")
        methods = []
        mixins = []
        visibility = "public"  # tracks current visibility state

        if body:
            for child in body.children:
                # Visibility modifiers: private, protected, public (as bare identifiers)
                if child.type == "identifier" and _text(child, source) in ("private", "protected", "public"):
                    visibility = _text(child, source)
                    continue

                # Method definitions
                if child.type == "method":
                    mn = child.child_by_field_name("name")
                    if mn:
                        mname = _text(mn, source)
                        methods.append(mname)
                        params = _extract_ruby_params(child, source)
                        # Build qualified name: Module::Class#method
                        enclosing = _find_enclosing_module_or_class(child, source)
                        method_qn = f"{enclosing}#{mname}" if enclosing else None
                        ast.functions.append(FunctionDef(
                            name=mname,
                            line=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            visibility=visibility,
                            params=params,
                            is_method=True,
                            qualified_name=method_qn,
                        ))

                # include/extend calls
                if child.type == "call":
                    cm = child.child_by_field_name("method")
                    if cm:
                        call_name = _text(cm, source)
                        if call_name in ("include", "extend"):
                            args = child.child_by_field_name("arguments")
                            if args:
                                for arg in args.named_children:
                                    if arg.type == "constant":
                                        mixins.append(_text(arg, source))

                        # attr_reader/writer/accessor → implicit methods
                        if call_name in ("attr_reader", "attr_writer", "attr_accessor"):
                            args = child.child_by_field_name("arguments")
                            if args:
                                for arg in args.named_children:
                                    if arg.type == "simple_symbol":
                                        sym = _text(arg, source).lstrip(":")
                                        methods.append(sym)
                                        attr_enclosing = _find_enclosing_module_or_class(child, source)
                                        attr_qn = f"{attr_enclosing}#{sym}" if attr_enclosing else None
                                        ast.functions.append(FunctionDef(
                                            name=sym,
                                            line=child.start_point[0] + 1,
                                            line_end=child.start_point[0] + 1,
                                            visibility="public",
                                            is_method=True,
                                            qualified_name=attr_qn,
                                        ))

        # Build qualified name for class including enclosing module
        cls_enclosing = _find_enclosing_module_or_class(class_node, source)
        if cls_enclosing:
            # cls_enclosing already includes this class, use it directly
            cls_qn = cls_enclosing
        else:
            cls_qn = class_name

        ast.classes.append(ClassDef(
            name=class_name,
            line=class_node.start_point[0] + 1,
            line_end=class_node.end_point[0] + 1,
            parent_class=parent_class,
            mixins=mixins,
            methods=methods,
            qualified_name=cls_qn,
        ))

    # --- Calls ---
    for call_node in _walk_all(root, "call"):
        method = call_node.child_by_field_name("method")
        if not method:
            continue
        method_name = _text(method, source)

        # Skip require/require_relative (already handled)
        if method_name in ("require", "require_relative"):
            continue
        # Skip meta-calls
        if method_name in ("include", "extend", "attr_reader", "attr_writer",
                           "attr_accessor", "private", "protected", "public"):
            continue

        receiver = call_node.child_by_field_name("receiver")
        if receiver:
            callee = f"{_text(receiver, source)}.{method_name}"
        else:
            callee = method_name

        enclosing = _find_enclosing(call_node, source)

        ast.calls.append(CallRef(
            caller_function=enclosing,
            callee_string=callee,
            line=call_node.start_point[0] + 1,
        ))

    # --- Module and nested class/module detection ---
    def _find_nested_types(node, source, ast, namespace):
        """Recursively find classes and modules, tracking full namespace."""
        for child in node.children:
            if child.type == "module":
                name_node = child.child_by_field_name("name")
                if name_node:
                    mod_name = _text(name_node, source)
                    new_ns = namespace + [mod_name]
                    full_name = "::".join(new_ns)
                    if full_name not in ast.exports:
                        ast.exports.append(full_name)
                    # Also export the bare module name for backward compat
                    if mod_name not in ast.exports:
                        ast.exports.append(mod_name)

                    body = child.child_by_field_name("body")
                    if body:
                        # Module-level singleton methods
                        for member in body.children:
                            if member.type == "singleton_method":
                                mn = member.child_by_field_name("name")
                                if mn:
                                    mname = _text(mn, source)
                                    func_full = f"{full_name}.{mname}"
                                    params = _extract_ruby_params(member, source)
                                    ast.functions.append(FunctionDef(
                                        name=func_full,
                                        line=member.start_point[0] + 1,
                                        line_end=member.end_point[0] + 1,
                                        visibility="public",
                                        params=params,
                                        is_method=True,
                                        qualified_name=func_full,
                                    ))
                                    if func_full not in ast.exports:
                                        ast.exports.append(func_full)

                            # Regular methods inside module (not class) are module functions
                            if member.type == "method":
                                mn = member.child_by_field_name("name")
                                if mn:
                                    mname = _text(mn, source)
                                    if not any(f.name == mname and f.is_method for f in ast.functions):
                                        params = _extract_ruby_params(member, source)
                                        mod_method_qn = f"{full_name}#{mname}"
                                        ast.functions.append(FunctionDef(
                                            name=mname,
                                            line=member.start_point[0] + 1,
                                            line_end=member.end_point[0] + 1,
                                            visibility="public",
                                            params=params,
                                            is_method=True,
                                            qualified_name=mod_method_qn,
                                        ))

                        # Recurse into body for nested modules/classes
                        _find_nested_types(body, source, ast, new_ns)

            elif child.type == "class":
                name_node = child.child_by_field_name("name")
                if name_node:
                    cls_name = _text(name_node, source)
                    if namespace:
                        full_name = "::".join(namespace + [cls_name])
                        # Update the ClassDef's qualified_name if not already set
                        for cls in ast.classes:
                            if cls.name == cls_name and (not cls.qualified_name or cls.qualified_name == cls_name):
                                cls.qualified_name = full_name
                        if full_name not in ast.exports:
                            ast.exports.append(full_name)

                    # Find singleton methods inside nested class
                    body = child.child_by_field_name("body")
                    if body:
                        cls_qn = "::".join(namespace + [cls_name]) if namespace else cls_name
                        for member in body.children:
                            if member.type == "singleton_method":
                                mn = member.child_by_field_name("name")
                                if mn:
                                    mname = _text(mn, source)
                                    func_full = f"{cls_qn}.{mname}"
                                    params = _extract_ruby_params(member, source)
                                    ast.functions.append(FunctionDef(
                                        name=func_full,
                                        line=member.start_point[0] + 1,
                                        line_end=member.end_point[0] + 1,
                                        visibility="public",
                                        params=params,
                                        is_method=True,
                                        qualified_name=func_full,
                                    ))
                                    if func_full not in ast.exports:
                                        ast.exports.append(func_full)
                                    # Also add to the class methods list
                                    for cls in ast.classes:
                                        if cls.name == cls_name:
                                            cls.methods.append(f"self.{mname}")

    _find_nested_types(root, source, ast, [])

    # --- Exports ---
    # Export: public methods
    for func in ast.functions:
        if func.visibility == "public" and func.name not in ast.exports:
            ast.exports.append(func.name)
    # Export: class names
    for cls in ast.classes:
        if cls.name not in ast.exports:
            ast.exports.append(cls.name)

    return ast


def _extract_ruby_params(method_node, source: bytes) -> list[str]:
    params = []
    pnode = method_node.child_by_field_name("parameters")
    if pnode:
        for p in pnode.named_children:
            if p.type == "identifier":
                params.append(_text(p, source))
            elif p.type == "keyword_parameter":
                name = p.child_by_field_name("name")
                if name:
                    params.append(_text(name, source) + ":")
            elif p.type == "optional_parameter":
                name = p.child_by_field_name("name")
                if name:
                    params.append(_text(name, source))
            elif p.type == "splat_parameter":
                name = p.child_by_field_name("name")
                if name:
                    params.append("*" + _text(name, source))
            elif p.type == "block_parameter":
                name = p.child_by_field_name("name")
                if name:
                    params.append("&" + _text(name, source))
    return params
