"""Dynamic prefix resolver: expands dynamic require prefixes to potential imports.

Many Lua files use dynamic requires like:
    require(string.format("handlers.%s", handler_name))

The parser extracts the static_prefix (e.g., "handlers.") from these patterns.
This resolver finds all modules whose name contains that prefix, creating
POTENTIAL_IMPORT edges so the graph captures the possible runtime targets.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


def resolve_dynamic_prefixes(all_asts: dict[str, FileAST]) -> list[dict]:
    """Expand dynamic require prefixes to all matching module targets.

    For each dynamic import with a static_prefix, finds all modules in the
    codebase whose module_name contains that prefix and creates an edge.

    Args:
        all_asts: Mapping of file_path -> FileAST for all parsed files.

    Returns:
        List of dicts with keys: source_file, target_file, prefix, line.
        Does not include self-references.
    """
    # Step 1: Build module_name -> file_path index
    module_index: dict[str, str] = {}
    for file_path, ast in all_asts.items():
        if ast.module_name:
            module_index[ast.module_name] = file_path

    # Step 2: Collect all dynamic imports with static_prefix
    edges: list[dict] = []
    for file_path, ast in all_asts.items():
        for imp in ast.imports:
            if not imp.is_dynamic or not imp.static_prefix:
                continue

            prefix = imp.static_prefix

            # Step 3: Find all modules whose name contains the prefix
            for module_name, target_file in module_index.items():
                if prefix in module_name and target_file != file_path:
                    edges.append({
                        "source_file": file_path,
                        "target_file": target_file,
                        "prefix": prefix,
                        "line": imp.line,
                    })

    return edges
