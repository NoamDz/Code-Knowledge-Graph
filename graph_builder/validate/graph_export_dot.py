"""DOT export: generate Graphviz DOT from parsed ASTs without Memgraph.

Produces a directed graph with:
  - Nodes colored by language (Lua=green, Python=blue, Ruby=red, JS=yellow, Go=cyan)
  - Subgraph clusters grouped by top-level directory
  - Import edges as thin arrows
  - Cross-service edges (Redis, HTTP) as bold colored arrows
  - nginx endpoints as diamond nodes
  - Limited to top N most-connected files for readability

Usage:
    code-graph export-dot -c config.yml -o graph.dot --max-nodes 200
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from graph_builder.config import Config
from graph_builder.scanner import FileScanner
from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.parsers.js_parser import parse_js_file
from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.parsers.base import FileAST
from graph_builder.parsers.nginx_parser import parse_nginx_conf_recursive
from graph_builder.resolvers.lua_resolver import LuaResolver
from graph_builder.resolvers.python_resolver import PythonResolver
from graph_builder.resolvers.call_resolver import CallResolver
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions


PARSERS = {
    "lua": parse_lua_file,
    "python": parse_python_file,
    "ruby": parse_ruby_file,
    "javascript": parse_js_file,
    "go": parse_go_file,
}

# Node fill colors per language
LANG_COLORS = {
    "lua": "#90EE90",         # light green
    "python": "#87CEEB",      # light blue
    "ruby": "#FFB6B6",        # light red
    "javascript": "#FFFF99",  # light yellow
    "go": "#B0E0E6",          # light cyan
}

LANG_BORDER_COLORS = {
    "lua": "#228B22",
    "python": "#4169E1",
    "ruby": "#DC143C",
    "javascript": "#DAA520",
    "go": "#008B8B",
}


def _escape_dot(s: str) -> str:
    """Escape a string for use in DOT labels/IDs."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _node_id(file_path: str) -> str:
    """Generate a stable DOT node ID from a file path."""
    # Use a hash-like mangling to make valid DOT identifiers
    return "f_" + str(abs(hash(file_path)))


def _short_name(file_path: str, repo_root: str) -> str:
    """Get just the basename of a file (for label readability)."""
    try:
        return Path(file_path).relative_to(repo_root).name
    except (ValueError, TypeError):
        return Path(file_path).name


def _top_dir(file_path: str, repo_root: str) -> str:
    """Get the top-level directory relative to repo root for clustering."""
    try:
        rel = Path(file_path).relative_to(repo_root)
        parts = rel.parts
        if len(parts) > 1:
            return parts[0]
        return "(root)"
    except (ValueError, TypeError):
        return "(external)"


def _parse_all_files(config: Config) -> tuple[dict[str, FileAST], list[tuple[str, str]]]:
    """Parse all source files. Returns (asts, errors)."""
    scanner = FileScanner(config)
    all_files = scanner.scan()
    all_asts: dict[str, FileAST] = {}
    errors: list[tuple[str, str]] = []

    for file_path, language in all_files:
        parser_fn = PARSERS.get(language)
        if not parser_fn:
            continue
        try:
            ast = parser_fn(file_path)
            all_asts[file_path] = ast
        except Exception as e:
            errors.append((file_path, str(e)))

    return all_asts, errors


def _build_resolvers(config: Config) -> dict:
    """Build language-specific resolvers."""
    resolvers = {}
    package_paths = list(config.lua_package_paths)
    if config.nginx_conf and Path(config.nginx_conf).exists():
        try:
            nginx_config = parse_nginx_conf_recursive(
                config.nginx_conf, config.nginx_base_path,
            )
            for p in nginx_config.lua_package_path:
                if p not in package_paths:
                    package_paths.append(p)
        except Exception:
            pass

    resolvers["lua"] = LuaResolver(package_paths, config.repo_root)
    resolvers["python"] = PythonResolver(config.repo_root)
    return resolvers


def _resolve_imports(all_asts: dict[str, FileAST], resolvers: dict) -> dict[str, dict[str, str | None]]:
    """Resolve imports across all files."""
    lua_resolver = resolvers.get("lua")
    python_resolver = resolvers.get("python")
    resolved_imports: dict[str, dict[str, str | None]] = {}

    for file_path, ast in all_asts.items():
        file_resolved: dict[str, str | None] = {}
        for imp in ast.imports:
            if imp.is_dynamic:
                continue
            if ast.language == "lua" and lua_resolver:
                file_resolved[imp.module_string] = lua_resolver.resolve(imp.module_string)
            elif ast.language == "python" and python_resolver:
                file_resolved[imp.module_string] = python_resolver.resolve(
                    imp.module_string, file_path,
                )
            else:
                file_resolved[imp.module_string] = None
        resolved_imports[file_path] = file_resolved

    return resolved_imports


def generate_dot(config: Config, max_nodes: int = 200) -> str:
    """Run the full pipeline and generate DOT output.

    Returns the DOT string.
    """
    repo_root = config.repo_root

    # --- Run full pipeline ---
    all_asts, _errors = _parse_all_files(config)
    if not all_asts:
        return "// No files parsed. Check repo_root.\ndigraph G {}"

    resolvers = _build_resolvers(config)
    resolved_imports = _resolve_imports(all_asts, resolvers)

    call_resolver = CallResolver(all_asts, resolvers)
    call_resolver.resolve_all()

    resolve_redis_abstractions(all_asts)

    # --- Compute connectivity for each file ---
    # Connectivity = number of import edges (in + out) + redis + http
    connectivity: dict[str, int] = defaultdict(int)

    # Import edges: file -> set of resolved target files
    import_edges: list[tuple[str, str]] = []
    for file_path, file_resolved in resolved_imports.items():
        for _mod_string, target_path in file_resolved.items():
            if target_path and target_path in all_asts:
                import_edges.append((file_path, target_path))
                connectivity[file_path] += 1
                connectivity[target_path] += 1

    # Redis/HTTP add to connectivity
    for file_path, ast in all_asts.items():
        connectivity[file_path] += len(ast.redis_accesses)
        connectivity[file_path] += len(ast.http_calls)

    # Select top N by connectivity
    ranked = sorted(all_asts.keys(), key=lambda fp: connectivity.get(fp, 0), reverse=True)
    selected_files = set(ranked[:max_nodes])

    # --- Collect nginx endpoints ---
    nginx_endpoints: list[tuple[str, str, str]] = []  # (path, phase, lua_file)
    if config.nginx_conf and Path(config.nginx_conf).exists():
        try:
            nginx_config = parse_nginx_conf_recursive(
                config.nginx_conf, config.nginx_base_path,
            )
            for loc in nginx_config.locations:
                for phase in loc.phases:
                    nginx_endpoints.append((loc.path, phase.phase, phase.lua_file or ""))
        except Exception:
            pass

    # --- Build DOT ---
    dot_lines: list[str] = []
    dot_lines.append("digraph CodeGraph {")
    dot_lines.append('  rankdir=LR;')
    dot_lines.append('  node [style=filled, fontsize=10, fontname="Helvetica"];')
    dot_lines.append('  edge [fontsize=8, fontname="Helvetica"];')
    dot_lines.append("")

    # Group nodes by top-level directory
    dir_groups: dict[str, list[str]] = defaultdict(list)
    for fp in selected_files:
        top = _top_dir(fp, repo_root)
        dir_groups[top].append(fp)

    cluster_idx = 0
    for dir_name, files in sorted(dir_groups.items()):
        dot_lines.append(f"  subgraph cluster_{cluster_idx} {{")
        dot_lines.append(f'    label="{_escape_dot(dir_name)}";')
        dot_lines.append('    style=dashed;')
        dot_lines.append('    color="#666666";')

        for fp in sorted(files):
            ast = all_asts[fp]
            lang = ast.language
            fill = LANG_COLORS.get(lang, "#DDDDDD")
            border = LANG_BORDER_COLORS.get(lang, "#333333")
            label = _short_name(fp, repo_root)
            nid = _node_id(fp)
            func_count = len(ast.functions)
            tooltip = f"{lang} | {func_count} funcs"
            dot_lines.append(
                f'    {nid} [label="{_escape_dot(label)}", '
                f'fillcolor="{fill}", color="{border}", '
                f'tooltip="{_escape_dot(tooltip)}"];'
            )

        dot_lines.append("  }")
        cluster_idx += 1

    # nginx endpoints as diamond nodes
    for path, phase, lua_file in nginx_endpoints:
        nid = "nginx_" + str(abs(hash(path + phase)))
        label = f"{path}\\n({phase})"
        dot_lines.append(
            f'  {nid} [label="{_escape_dot(label)}", '
            f'shape=diamond, fillcolor="#FFA07A", color="#8B0000", '
            f'fontsize=9];'
        )
        # Connect to lua file if it exists in our selected set
        if lua_file:
            for fp in selected_files:
                if lua_file in fp:
                    dot_lines.append(
                        f'  {nid} -> {_node_id(fp)} '
                        f'[style=dashed, color="#8B0000", label="phase"];'
                    )
                    break

    dot_lines.append("")

    # Import edges (thin arrows)
    seen_edges: set[tuple[str, str]] = set()
    for src, dst in import_edges:
        if src in selected_files and dst in selected_files:
            edge_key = (src, dst)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                dot_lines.append(
                    f'  {_node_id(src)} -> {_node_id(dst)} '
                    f'[color="#666666", arrowsize=0.7];'
                )

    # Cross-service edges: Redis
    redis_files = {
        fp for fp, ast in all_asts.items()
        if fp in selected_files and ast.redis_accesses
    }
    for fp in sorted(redis_files):
        nid = "redis_" + str(abs(hash(fp)))
        # Create a shared Redis node per file (or one global)
        # Use one global Redis node for simplicity
        pass  # handled below

    if redis_files:
        dot_lines.append("")
        dot_lines.append('  redis_hub [label="Redis", shape=cylinder, '
                         'fillcolor="#FF6347", color="#8B0000", fontcolor="white"];')
        for fp in sorted(redis_files):
            ast = all_asts[fp]
            reads = sum(1 for r in ast.redis_accesses if r.access_type == "read")
            writes = sum(1 for r in ast.redis_accesses if r.access_type == "write")
            label_parts = []
            if reads:
                label_parts.append(f"R:{reads}")
            if writes:
                label_parts.append(f"W:{writes}")
            edge_label = " ".join(label_parts) if label_parts else ""
            dot_lines.append(
                f'  {_node_id(fp)} -> redis_hub '
                f'[style=bold, color="#FF6347", penwidth=2.0, '
                f'label="{edge_label}"];'
            )

    # Cross-service edges: HTTP
    http_files = {
        fp for fp, ast in all_asts.items()
        if fp in selected_files and ast.http_calls
    }
    if http_files:
        dot_lines.append("")
        dot_lines.append('  http_hub [label="HTTP\\n(external)", shape=octagon, '
                         'fillcolor="#9370DB", color="#4B0082", fontcolor="white"];')
        for fp in sorted(http_files):
            ast = all_asts[fp]
            count = len(ast.http_calls)
            dot_lines.append(
                f'  {_node_id(fp)} -> http_hub '
                f'[style=bold, color="#9370DB", penwidth=2.0, '
                f'label="{count}"];'
            )

    # Legend
    dot_lines.append("")
    dot_lines.append("  subgraph cluster_legend {")
    dot_lines.append('    label="Legend";')
    dot_lines.append('    style=solid;')
    dot_lines.append('    color="#333333";')
    dot_lines.append('    fontsize=10;')
    for lang, fill in sorted(LANG_COLORS.items()):
        border = LANG_BORDER_COLORS.get(lang, "#333")
        dot_lines.append(
            f'    legend_{lang} [label="{lang}", fillcolor="{fill}", '
            f'color="{border}", shape=box, fontsize=9];'
        )
    dot_lines.append('    legend_nginx [label="nginx endpoint", shape=diamond, '
                     'fillcolor="#FFA07A", color="#8B0000", fontsize=9];')
    dot_lines.append("  }")

    dot_lines.append("}")
    dot_lines.append("")

    return "\n".join(dot_lines)
