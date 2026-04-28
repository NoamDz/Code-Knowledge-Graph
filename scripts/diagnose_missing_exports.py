"""Diagnostic script: investigate files that should have exports but don't.

Usage:
    python3 diagnose_missing_exports.py /path/to/repo

Reads the files listed as having no exports in the audit and shows:
  - What the return statement looks like
  - What the AST structure is around the return
  - Suggested fixes
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from graph_builder.parsers.lua_parser import parse_lua_file, _detect_module_pattern, _find_exports
from tree_sitter import Language, Parser
import tree_sitter_lua as tslua

LUA = Language(tslua.language())

# Files that the audit flagged as having exports=0 but pattern != side_effect
# Update this list with your actual files
SUSPECT_FILES = [
    "common/orm_models/app_insights.lua",
    "common/orm_models/attribute_to_hashed_user_id.lua",
    "common/orm_models/calculated_attributes.lua",
    "common/orm_models/deleted_devices.lua",
    "common/orm_models/global_device_attributes.lua",
    "common/orm_models/hashed_user_id_to_attribute.lua",
    "common/orm_models/internal_event_mapping.lua",
    "common/orm_models/metastrokes_results.lua",
    "common/orm_models/policy_invocation_stat.lua",
    "common/orm_models/policy_result.lua",
    "common/orm_models/rulegen_models.lua",
    "common/orm_models/rulesets.lua",
    "common/orm_models/session_mobile_category.lua",
    "common/orm_models/session_mobile_data.lua",
    "common/orm_models/session_mobile_sim_data.lua",
    "common/orm_models/staged_rulesets.lua",
    "common/rules_engine/api/methods/math.lua",
    "common/actors/init.lua",
    "core/deferrer/client.lua",
]


def diagnose_file(file_path: str):
    """Show detailed diagnostic info about why a file has no exports."""
    path = Path(file_path)
    if not path.exists():
        print(f"  File not found: {file_path}")
        return

    source = path.read_bytes()
    parser = Parser(LUA)
    tree = parser.parse(source)
    root = tree.root_node

    print(f"\n{'='*60}")
    print(f"Diagnosing: {file_path}")
    print(f"{'='*60}")

    # Show the return statement
    for child in root.children:
        if child.type == "return_statement":
            line = child.start_point[0] + 1
            text = source[child.start_byte:child.end_byte].decode()
            print(f"\nReturn statement (line {line}):")
            # Show first 200 chars
            print(f"  {text[:200]}")
            if len(text) > 200:
                print(f"  ... ({len(text)} chars total)")

            # Show AST of the return expression
            from tree_sitter import Language
            expr_list = None
            for c in child.children:
                if c.type == "expression_list":
                    expr_list = c
                    break
            if expr_list and expr_list.named_child_count > 0:
                returned = expr_list.named_children[0]
                print(f"\nReturned expression type: {returned.type}")
                _print_ast(returned, source, depth=0, max_depth=3)

    # Try parsing with our parser
    try:
        ast = parse_lua_file(file_path)
        print(f"\nParser result:")
        print(f"  Pattern: {ast.module_info.pattern_type.value}")
        print(f"  Table var: {ast.module_info.table_var_name}")
        print(f"  Functions: {len(ast.functions)}")
        print(f"  Exports: {len(ast.exports)}: {ast.exports[:10]}")
        if not ast.exports and ast.module_info.table_var_name:
            print(f"\n  ⚠ Table var '{ast.module_info.table_var_name}' detected but no exports found.")
            print(f"  Check: are functions/values assigned to this table?")
    except Exception as e:
        print(f"\n  Parse error: {e}")

    # Show the first 30 lines for manual inspection
    lines = source.decode(errors='replace').split('\n')
    print(f"\nFirst 30 lines:")
    for i, line in enumerate(lines[:30], 1):
        print(f"  {i:3d} | {line}")
    if len(lines) > 30:
        print(f"  ... ({len(lines)} lines total)")
    print()


def _print_ast(node, source, depth=0, max_depth=3):
    """Print AST tree up to max_depth."""
    if depth > max_depth:
        return
    text = source[node.start_byte:node.end_byte].decode()[:50]
    if node.child_count == 0:
        print(f"  {'  ' * depth}{node.type} = \"{text}\"")
    else:
        print(f"  {'  ' * depth}{node.type}")
    for child in node.children:
        _print_ast(child, source, depth + 1, max_depth)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 diagnose_missing_exports.py /path/to/repo")
        print("\nThis script investigates files that should have exports but don't.")
        print("Edit the SUSPECT_FILES list at the top to match your actual files.")
        sys.exit(1)

    repo_root = Path(sys.argv[1])

    found = 0
    for rel_path in SUSPECT_FILES:
        full_path = repo_root / rel_path
        if full_path.exists():
            diagnose_file(str(full_path))
            found += 1

    if found == 0:
        print(f"No suspect files found in {repo_root}")
        print("Update SUSPECT_FILES in this script with your actual file paths.")
        print(f"\nTrying first 5 .lua files in {repo_root} as a demo...")
        for f in sorted(repo_root.rglob("*.lua"))[:5]:
            diagnose_file(str(f))


if __name__ == "__main__":
    main()
