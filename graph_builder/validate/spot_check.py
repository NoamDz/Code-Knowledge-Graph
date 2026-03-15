"""Spot-check tool: inspect what the parser extracted from a single file.

Usage:
    python -m graph_builder.validate.spot_check <file_path>

Shows a detailed report of all entities found, useful for comparing
against what you see when reading the file manually.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.parsers.js_parser import parse_js_file


PARSERS = {
    ".lua": parse_lua_file,
    ".py": parse_python_file,
    ".rb": parse_ruby_file,
    ".js": parse_js_file,
}


def spot_check(file_path: str) -> str:
    """Run a spot check on a file and return a formatted report."""
    path = Path(file_path)
    if not path.exists():
        return f"ERROR: File not found: {file_path}"

    ext = path.suffix
    if ext not in PARSERS:
        return f"ERROR: Unsupported file type: {ext} (supported: {list(PARSERS.keys())})"

    parser_fn = PARSERS[ext]
    ast = parser_fn(str(path))

    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"Spot Check: {file_path}")
    lines.append(f"{'='*60}")

    # File info
    source_lines = path.read_text().count('\n') + 1
    lines.append(f"\nSOURCE: {source_lines} lines, language: {ast.language}")

    # Module info (Lua-specific)
    if ast.module_info:
        mi = ast.module_info
        lines.append(f"\nMODULE PATTERN: {mi.pattern_type.value}")
        if mi.table_var_name:
            lines.append(f"  Table variable: {mi.table_var_name}")
        if mi.returned_identifier:
            lines.append(f"  Returns: {mi.returned_identifier}")

    # Classes
    if ast.classes:
        lines.append(f"\nCLASSES ({len(ast.classes)}):")
        for cls in ast.classes:
            parent = f" < {cls.parent_class}" if cls.parent_class else ""
            mixins = f" [mixins: {', '.join(cls.mixins)}]" if cls.mixins else ""
            lines.append(f"  {cls.name}{parent}{mixins}  (lines {cls.line}-{cls.line_end})")
            if cls.methods:
                lines.append(f"    methods: {', '.join(cls.methods)}")

    # Functions
    lines.append(f"\nFUNCTIONS ({len(ast.functions)}):")
    for func in ast.functions:
        method_tag = " [method]" if func.is_method else ""
        deco_tag = f" {func.decorators}" if func.decorators else ""
        params_str = f"({', '.join(func.params)})" if func.params else "()"
        lines.append(
            f"  {'✓' if func.visibility == 'public' else '○'} {func.name}{params_str}"
            f"  lines {func.line}-{func.line_end}  vis={func.visibility}"
            f"{method_tag}{deco_tag}"
        )

    # Exports
    lines.append(f"\nEXPORTS ({len(ast.exports)}): {', '.join(ast.exports) if ast.exports else '(none)'}")

    # Imports
    lines.append(f"\nIMPORTS ({len(ast.imports)}):")
    for imp in ast.imports:
        binding = f" as {imp.local_binding}" if imp.local_binding else ""
        dynamic = " [DYNAMIC]" if imp.is_dynamic else ""
        prefix = f" (prefix: {imp.static_prefix})" if imp.static_prefix else ""
        lines.append(f"  {imp.import_type}: \"{imp.module_string}\"{binding}{dynamic}{prefix}  (line {imp.line})")

    # Calls
    lines.append(f"\nCALLS ({len(ast.calls)}):")
    for call in ast.calls:
        pcall = " [pcall]" if call.is_pcall_wrapped else ""
        resolved = ""
        if call.resolved_module:
            resolved = f" → {call.resolved_module}.{call.resolved_function}"
        lines.append(f"  {call.caller_function} → {call.callee_string}{pcall}{resolved}  (line {call.line})")

    # OpenResty-specific
    if ast.ctx_accesses:
        lines.append(f"\nngx.ctx ACCESSES ({len(ast.ctx_accesses)}):")
        for ca in ast.ctx_accesses:
            lines.append(f"  {ca.access_type}: ngx.ctx.{ca.field_name} in {ca.function}  (line {ca.line})")

    if ast.shared_dict_accesses:
        lines.append(f"\nngx.shared ACCESSES ({len(ast.shared_dict_accesses)}):")
        for sd in ast.shared_dict_accesses:
            lines.append(f"  {sd.operation}: ngx.shared.{sd.dict_name} in {sd.function}  (line {sd.line})")

    # Warnings
    if ast.warnings:
        lines.append(f"\nWARNINGS ({len(ast.warnings)}):")
        for w in ast.warnings:
            lines.append(f"  ⚠ {w}")

    lines.append("")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m graph_builder.validate.spot_check <file_path> [file_path2 ...]")
        sys.exit(1)

    for file_path in sys.argv[1:]:
        print(spot_check(file_path))


if __name__ == "__main__":
    main()
