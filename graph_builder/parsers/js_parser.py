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

import re
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjs

from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef, HttpCallRef

JS = Language(tsjs.language())

# ERB tag pattern: replaces <%= ... %>, <% ... %>, <%- ... %>, <%# ... %>
RE_ERB_TAG = re.compile(rb'<%[=\-#]?.*?%>', re.DOTALL)


def _strip_erb(source: bytes) -> bytes:
    """Strip ERB tags from source, replacing with empty string literals."""
    return RE_ERB_TAG.sub(b'""', source)


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
    """Parse a JavaScript file and extract all code entities.

    Supports .js.erb files by stripping ERB tags before parsing.
    """
    parser = Parser(JS)
    source = Path(file_path).read_bytes()

    # Strip ERB tags for .js.erb files (or any file containing ERB)
    if file_path.endswith(".erb"):
        source = _strip_erb(source)

    tree = parser.parse(source)
    root = tree.root_node

    ast = FileAST(file_path=file_path, language="javascript")
    binding_map: dict[str, str] = {}
    _stem = Path(file_path).stem  # filename without extension (e.g., "user_controller")
    # For .js.erb, strip both extensions
    if _stem.endswith(".js"):
        _stem = _stem[:-3]

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
                        method_qn = f"{_stem}.{class_name}.{mname}"
                        ast.functions.append(FunctionDef(
                            name=mname,
                            line=member.start_point[0] + 1,
                            line_end=member.end_point[0] + 1,
                            visibility="private" if mname.startswith("_") else "public",
                            params=params,
                            is_method=True,
                            qualified_name=method_qn,
                        ))

        cls_qn = f"{_stem}.{class_name}"
        ast.classes.append(ClassDef(
            name=class_name,
            line=cls_node.start_point[0] + 1,
            line_end=cls_node.end_point[0] + 1,
            parent_class=parent_class,
            methods=methods,
            qualified_name=cls_qn,
        ))

    # --- Top-level functions ---
    for func_node in _walk_all(root, "function_declaration"):
        name_node = func_node.child_by_field_name("name")
        if not name_node:
            continue
        fname = _text(name_node, source)
        ast.functions.append(FunctionDef(
            name=fname,
            line=func_node.start_point[0] + 1,
            line_end=func_node.end_point[0] + 1,
            visibility="public",
            params=_extract_params(func_node, source),
            qualified_name=f"{_stem}.{fname}",
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
            qualified_name=f"{_stem}.{fname}",
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
    for assign in _walk_all(root, "assignment_expression"):
        left = assign.child_by_field_name("left")
        if not left:
            continue
        left_text = _text(left, source)

        # module.exports = ...
        if left_text == "module.exports":
            right = assign.child_by_field_name("right")
            if not right:
                continue
            if right.type == "object":
                # module.exports = { key: val, shorthand }
                for child in right.named_children:
                    if child.type == "shorthand_property_identifier":
                        ast.exports.append(_text(child, source))
                    elif child.type == "pair":
                        key = child.child_by_field_name("key")
                        if key:
                            ast.exports.append(_text(key, source))
            elif right.type == "identifier":
                # module.exports = ClassName
                ast.exports.append(_text(right, source))
            elif right.type in ("function_expression", "arrow_function", "class"):
                # module.exports = function(){} or class
                name = right.child_by_field_name("name")
                if name:
                    ast.exports.append(_text(name, source))
                else:
                    ast.exports.append("<default>")
            elif right.type == "call_expression":
                # module.exports = require("./x") — re-export
                func = right.child_by_field_name("function")
                if func and _text(func, source) == "require":
                    ast.exports.append("<reexport>")

        # module.exports.Foo = value
        elif left_text.startswith("module.exports."):
            prop_name = left_text.split("module.exports.", 1)[1]
            if prop_name:
                ast.exports.append(prop_name)

        # exports.foo = value
        elif left.type == "member_expression":
            obj = left.child_by_field_name("object")
            prop = left.child_by_field_name("property")
            if obj and prop and _text(obj, source) == "exports":
                ast.exports.append(_text(prop, source))

    # export default / export { ... }
    for exp in _walk_all(root, "export_statement"):
        decl = exp.child_by_field_name("declaration")
        if decl:
            name = decl.child_by_field_name("name")
            if name:
                ast.exports.append(_text(name, source))
        # export { a, b }
        for child in exp.children:
            if child.type == "export_clause":
                for spec in child.named_children:
                    if spec.type == "export_specifier":
                        name_node = spec.child_by_field_name("name")
                        if name_node:
                            ast.exports.append(_text(name_node, source))

    # --- IIFE / revealing module pattern exports ---
    # Detect: return { key: fn, ... } inside function expressions
    # This catches browser-style modules like: var X = (function(){ ... return { a: a }; })();
    if not ast.exports:
        _extract_iife_exports(root, source, ast)

    # --- Global variable assignment exports ---
    # Detect: window.X = ..., global.X = ...
    if not ast.exports:
        _extract_global_exports(root, source, ast)

    # --- HTTP call detection (browser → backend) ---
    _extract_js_http_calls(root, source, ast)

    return ast


def _extract_iife_exports(root, source: bytes, ast: FileAST):
    """Detect exports from IIFE / revealing module pattern.

    Catches: var X = (function(){ ... return { a: a, b: b }; })();
    Also: (function(){ ... window.X = { a: a }; })();
    """
    for return_stmt in _walk_all(root, "return_statement"):
        # Only care about returns that are inside a function expression (IIFE body)
        parent = return_stmt.parent
        while parent:
            if parent.type in ("function_expression", "arrow_function"):
                break
            if parent.type in ("function_declaration",):
                # Named function declaration — not an IIFE
                parent = None
                break
            parent = parent.parent

        if not parent:
            continue

        # Check if the return value is an object literal
        for child in return_stmt.children:
            if child.type == "object":
                for prop in child.named_children:
                    if prop.type == "shorthand_property_identifier":
                        name = _text(prop, source)
                        if name not in ast.exports:
                            ast.exports.append(name)
                    elif prop.type == "pair":
                        key = prop.child_by_field_name("key")
                        if key:
                            name = _text(key, source)
                            if name not in ast.exports:
                                ast.exports.append(name)
                    elif prop.type == "method_definition":
                        name_node = prop.child_by_field_name("name")
                        if name_node:
                            name = _text(name_node, source)
                            if name not in ast.exports:
                                ast.exports.append(name)


def _extract_global_exports(root, source: bytes, ast: FileAST):
    """Detect exports via global assignment: window.X = ..., global.X = ..."""
    for assign in _walk_all(root, "assignment_expression"):
        left = assign.child_by_field_name("left")
        if not left or left.type != "member_expression":
            continue
        obj = left.child_by_field_name("object")
        prop = left.child_by_field_name("property")
        if not obj or not prop:
            continue
        obj_text = _text(obj, source)
        if obj_text in ("window", "global", "self", "globalThis"):
            name = _text(prop, source)
            if name not in ast.exports:
                ast.exports.append(name)


def _extract_js_http_calls(root, source: bytes, ast: FileAST):
    """Detect HTTP calls in JS: fetch(), $.ajax(), XMLHttpRequest."""
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        enclosing = _find_enclosing(call_node, source)
        args = call_node.child_by_field_name("arguments")

        # fetch("/api/endpoint", { method: "POST" })
        if callee == "fetch" and args and args.named_child_count >= 1:
            first_arg = args.named_children[0]
            url = _try_get_string(first_arg, source)
            if url:
                method = "GET"
                # Check for method in options object
                if args.named_child_count >= 2:
                    opts = args.named_children[1]
                    method = _extract_method_from_object(opts, source) or "GET"
                ast.http_calls.append(HttpCallRef(
                    url_or_path=url, method=method,
                    function=enclosing, line=call_node.start_point[0] + 1,
                ))

        # $.ajax({ url: "/api", method: "POST" })
        elif callee in ("$.ajax", "jQuery.ajax") and args and args.named_child_count >= 1:
            opts = args.named_children[0]
            if opts.type == "object":
                url = _extract_prop_string(opts, source, "url")
                if url:
                    method = _extract_method_from_object(opts, source) or "GET"
                    ast.http_calls.append(HttpCallRef(
                        url_or_path=url, method=method,
                        function=enclosing, line=call_node.start_point[0] + 1,
                    ))

    # XMLHttpRequest.open("METHOD", "/url")
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        if callee.endswith(".open"):
            args = call_node.child_by_field_name("arguments")
            if args and args.named_child_count >= 2:
                method_arg = args.named_children[0]
                url_arg = args.named_children[1]
                method = _try_get_string(method_arg, source)
                url = _try_get_string(url_arg, source)
                if method and url and method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    enclosing = _find_enclosing(call_node, source)
                    ast.http_calls.append(HttpCallRef(
                        url_or_path=url, method=method.upper(),
                        function=enclosing, line=call_node.start_point[0] + 1,
                    ))

    # sendRequest(type, url, ...) — custom HTTP wrapper
    for call_node in _walk_all(root, "call_expression"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        args = call_node.child_by_field_name("arguments")

        if callee == "sendRequest" and args and args.named_child_count >= 2:
            method_arg = args.named_children[0]
            url_arg = args.named_children[1]
            method = _try_get_string(method_arg, source)
            url = _try_get_string(url_arg, source)
            if url:
                enclosing = _find_enclosing(call_node, source)
                ast.http_calls.append(HttpCallRef(
                    url_or_path=url,
                    method=(method or "unknown").upper(),
                    function=enclosing,
                    line=call_node.start_point[0] + 1,
                ))

        # Net._request({ type: "POST", url: "/api/assess" }, ...) — custom HTTP wrapper
        elif callee == "Net._request" and args and args.named_child_count >= 1:
            config_arg = args.named_children[0]
            if config_arg.type == "object":
                url = _extract_prop_string(config_arg, source, "url")
                method = _extract_method_from_object(config_arg, source)
                if url:
                    enclosing = _find_enclosing(call_node, source)
                    ast.http_calls.append(HttpCallRef(
                        url_or_path=url,
                        method=(method or "unknown").upper(),
                        function=enclosing,
                        line=call_node.start_point[0] + 1,
                    ))


def _try_get_string(node, source: bytes) -> str | None:
    """Try to extract a string value from a node."""
    if not node:
        return None
    if node.type == "string":
        return _get_string_value(node, source)
    if node.type == "identifier":
        # Can't resolve variable values at parse time
        return None
    if node.type == "template_string":
        # Template literals — extract the static part
        frags = []
        for child in node.children:
            if child.type == "string_fragment" or child.type == "template_fragment":
                frags.append(_text(child, source))
        return "".join(frags) if frags else None
    return None


def _extract_method_from_object(node, source: bytes) -> str | None:
    """Extract method property from an object literal like { method: "POST" }."""
    if node.type != "object":
        return None
    for child in node.named_children:
        if child.type == "pair":
            key = child.child_by_field_name("key")
            val = child.child_by_field_name("value")
            if key and val:
                key_text = _text(key, source)
                if key_text in ("method", "type"):
                    return _try_get_string(val, source)
    return None


def _extract_prop_string(node, source: bytes, prop_name: str) -> str | None:
    """Extract a string property value from an object literal."""
    if node.type != "object":
        return None
    for child in node.named_children:
        if child.type == "pair":
            key = child.child_by_field_name("key")
            val = child.child_by_field_name("value")
            if key and val and _text(key, source) == prop_name:
                return _try_get_string(val, source)
    return None
