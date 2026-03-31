"""Dynamic prefix resolver: expands dynamic require prefixes to potential imports.

Many Lua files use dynamic requires like:
    require(string.format("handlers.%s", handler_name))

The parser extracts the static_prefix (e.g., "handlers.") from these patterns.
This resolver finds all modules whose name matches that prefix at a namespace
boundary, creating POTENTIAL_IMPORT edges so the graph captures the possible
runtime targets.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def _is_prefix_match(prefix: str, module_name: str) -> bool:
    """Check if prefix matches at a namespace boundary.

    "tasks." should match "ato.tasks.pts_run" but NOT "multitask_runner".
    Splits both on "." and checks for contiguous subsequence match.
    """
    prefix_clean = prefix.rstrip(".")
    prefix_parts = prefix_clean.split(".")
    module_parts = module_name.split(".")

    # Check if prefix_parts appears as a contiguous subsequence in module_parts
    for i in range(len(module_parts) - len(prefix_parts) + 1):
        if module_parts[i:i + len(prefix_parts)] == prefix_parts:
            return True
    return False


def resolve_dynamic_prefixes(all_asts: dict[str, FileAST]) -> tuple[list[dict], dict]:
    """Expand dynamic require prefixes to all matching module targets.

    For each dynamic import with a static_prefix, finds all modules in the
    codebase whose module_name matches that prefix at a namespace boundary
    and creates an edge.

    Args:
        all_asts: Mapping of file_path -> FileAST for all parsed files.

    Returns:
        Tuple of (edges, stats):
        - edges: List of dicts with keys: source_file, target_file, prefix, line.
          Does not include self-references.
        - stats: Dict with counts of prefixes_processed, matches_found, files_scanned.
    """
    # Step 1: Build module_name -> file_path index
    module_index: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.module_name:
            module_index[ast.module_name] = file_path

    # Step 2: Collect all dynamic imports with static_prefix
    edges: list[dict] = []
    prefixes_processed = 0
    for file_path, ast in all_asts.items():
        for imp in ast.imports:
            if not imp.is_dynamic or not imp.static_prefix:
                continue

            prefix = imp.static_prefix
            prefixes_processed += 1

            # Step 3: Find all modules whose name matches the prefix at a boundary
            for module_name, target_file in module_index.items():
                if _is_prefix_match(prefix, module_name) and target_file != file_path:
                    edges.append({
                        "source_file": file_path,
                        "target_file": target_file,
                        "prefix": prefix,
                        "line": imp.line,
                    })

    stats = {
        "prefixes_processed": prefixes_processed,
        "matches_found": len(edges),
        "files_scanned": len(all_asts),
    }
    return edges, stats
