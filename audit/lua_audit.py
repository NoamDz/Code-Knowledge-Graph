"""Lua codebase audit: classify module patterns across all Lua files.

Usage:
    python -m audit.lua_audit <repo_root>

Produces a report showing:
  - How many files use each module pattern (_M, m, named, direct, class, etc.)
  - Files grouped by pattern
  - Require patterns (standard, parenthesized, pcall-wrapped, dynamic)
  - Potential parser issues (files that failed to parse or have zero exports)
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.base import ModulePatternType

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "vendor", "venv"}


def audit_lua_files(repo_root: str) -> str:
    """Audit all Lua files in a repository."""
    root = Path(repo_root)
    lua_files = []
    for f in root.rglob("*.lua"):
        if not any(skip in f.parts for skip in SKIP_DIRS):
            lua_files.append(f)

    if not lua_files:
        return f"No .lua files found in {repo_root}"

    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  Lua Codebase Audit: {repo_root}")
    lines.append(f"  Files found: {len(lua_files)}")
    lines.append(f"{'='*60}")

    # Parse all files
    results = []
    errors = []
    for f in sorted(lua_files):
        try:
            ast = parse_lua_file(str(f))
            results.append((f, ast))
        except Exception as e:
            errors.append((f, str(e)))

    # --- Module pattern distribution ---
    pattern_counts = Counter()
    pattern_files: dict[str, list[str]] = {}
    table_var_counts = Counter()

    for f, ast in results:
        if ast.module_info:
            pattern = ast.module_info.pattern_type.value
            pattern_counts[pattern] += 1
            pattern_files.setdefault(pattern, []).append(str(f.relative_to(root)))
            if ast.module_info.table_var_name:
                table_var_counts[ast.module_info.table_var_name] += 1

    lines.append(f"\n--- MODULE PATTERNS ---")
    for pattern, count in pattern_counts.most_common():
        pct = count / len(results) * 100
        lines.append(f"  {pattern:>20}: {count:>4} ({pct:.1f}%)")

    lines.append(f"\n--- TABLE VARIABLE NAMES ---")
    for var, count in table_var_counts.most_common(20):
        lines.append(f"  {var:>20}: {count:>4}")

    # --- Export analysis ---
    files_with_exports = sum(1 for _, ast in results if ast.exports)
    files_without = sum(1 for _, ast in results if not ast.exports)
    total_exports = sum(len(ast.exports) for _, ast in results)

    lines.append(f"\n--- EXPORT ANALYSIS ---")
    lines.append(f"  Files with exports:    {files_with_exports}")
    lines.append(f"  Files without exports: {files_without}")
    lines.append(f"  Total exports:         {total_exports}")
    lines.append(f"  Avg exports/file:      {total_exports/len(results):.1f}" if results else "")

    if files_without > 0:
        lines.append(f"\n  Files with no exports (potential parser misses):")
        for f, ast in results:
            if not ast.exports:
                pattern = ast.module_info.pattern_type.value if ast.module_info else "?"
                lines.append(f"    {str(f.relative_to(root)):50s}  pattern: {pattern}")

    # --- Require patterns ---
    require_types = Counter()
    dynamic_requires = []
    for f, ast in results:
        for imp in ast.imports:
            if imp.is_dynamic:
                require_types["dynamic"] += 1
                dynamic_requires.append((str(f.relative_to(root)), imp.module_string))
            elif imp.local_binding:
                require_types["with_binding"] += 1
            else:
                require_types["standalone"] += 1

    lines.append(f"\n--- REQUIRE PATTERNS ---")
    for rtype, count in require_types.most_common():
        lines.append(f"  {rtype:>20}: {count:>4}")

    if dynamic_requires:
        lines.append(f"\n  Dynamic requires (need manual review):")
        for f, mod in dynamic_requires[:20]:
            lines.append(f"    {f}: require({mod})")

    # --- ngx.ctx usage ---
    ctx_fields = Counter()
    for _, ast in results:
        for ca in ast.ctx_accesses:
            ctx_fields[ca.field_name] += 1

    if ctx_fields:
        lines.append(f"\n--- ngx.ctx FIELDS USED ---")
        for field, count in ctx_fields.most_common(20):
            lines.append(f"  {field:>30}: {count:>4} accesses")

    # --- ngx.shared usage ---
    shared_dicts = Counter()
    for _, ast in results:
        for sd in ast.shared_dict_accesses:
            shared_dicts[sd.dict_name] += 1

    if shared_dicts:
        lines.append(f"\n--- ngx.shared DICTS USED ---")
        for name, count in shared_dicts.most_common():
            lines.append(f"  {name:>30}: {count:>4} accesses")

    # --- Errors ---
    if errors:
        lines.append(f"\n--- PARSE ERRORS ({len(errors)}) ---")
        for f, err in errors:
            lines.append(f"  {str(f.relative_to(root))}: {err}")

    # --- Warnings ---
    all_warnings = []
    for _, ast in results:
        all_warnings.extend(ast.warnings)
    if all_warnings:
        lines.append(f"\n--- WARNINGS ({len(all_warnings)}) ---")
        for w in all_warnings[:30]:
            lines.append(f"  {w}")

    lines.append("")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m audit.lua_audit <repo_root>")
        sys.exit(1)
    print(audit_lua_files(sys.argv[1]))


if __name__ == "__main__":
    main()
