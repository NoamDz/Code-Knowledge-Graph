"""Coverage report: scan a codebase and produce quality metrics.

Usage:
    python -m graph_builder.validate.coverage_report <repo_root> [--nginx-conf path]

Runs all parsers against every source file and produces aggregate
statistics about what was captured.

Works standalone (no Memgraph required) — useful for validating
parser quality before ingestion.
"""

from __future__ import annotations

import sys
import time
import json
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.parsers.js_parser import parse_js_file
from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.parsers.nginx_parser import parse_nginx_conf, parse_nginx_conf_recursive
from graph_builder.parsers.base import FileAST, ModulePatternType
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions


PARSERS = {
    ".lua": parse_lua_file,
    ".py": parse_python_file,
    ".rb": parse_ruby_file,
    ".js": parse_js_file,
    ".go": parse_go_file,
}

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".mypy_cache",
    "vendor", "venv", ".venv", "dist", "build",
}


@dataclass
class LanguageStats:
    """Statistics for one language."""
    total_files: int = 0
    parsed_ok: int = 0
    parse_errors: int = 0
    total_functions: int = 0
    public_functions: int = 0
    total_classes: int = 0
    total_imports: int = 0
    dynamic_imports: int = 0
    total_calls: int = 0
    pcall_calls: int = 0
    total_exports: int = 0
    files_with_exports: int = 0
    files_without_exports: int = 0
    ctx_accesses: int = 0
    shared_dict_accesses: int = 0
    internal_redirects: int = 0
    redis_accesses: int = 0
    http_calls: int = 0
    warnings: list[str] = field(default_factory=list)
    error_files: list[str] = field(default_factory=list)
    orphan_files: list[str] = field(default_factory=list)  # files with no imports in or out


def scan_files(repo_root: str) -> dict[str, list[str]]:
    """Scan repository for source files, grouped by extension."""
    root = Path(repo_root)
    files: dict[str, list[str]] = {ext: [] for ext in PARSERS}

    for ext in PARSERS:
        pattern = f"*{ext}"
        for f in root.rglob(pattern):
            # Skip excluded directories
            if any(skip in f.parts for skip in SKIP_DIRS):
                continue
            files[ext].append(str(f))

    # Also scan for .js.erb files (compound extension)
    for f in root.rglob("*.js.erb"):
        if any(skip in f.parts for skip in SKIP_DIRS):
            continue
        # Parse as JavaScript
        files.setdefault(".js", [])
        files[".js"].append(str(f))

    return files


def run_coverage_report(repo_root: str, nginx_conf: str | None = None,
                        nginx_base_path: str | None = None) -> str:
    """Run the full coverage report and return formatted output."""
    start = time.time()
    root = Path(repo_root)

    if not root.is_dir():
        return f"ERROR: {repo_root} is not a directory"

    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  Graph Coverage Report")
    lines.append(f"  Repository: {repo_root}")
    lines.append(f"{'='*60}")

    # Scan files
    file_groups = scan_files(repo_root)
    total_files = sum(len(files) for files in file_groups.values())
    lines.append(f"\n  Total source files found: {total_files}")

    # Parse all files
    all_asts: dict[str, FileAST] = {}
    lang_stats: dict[str, LanguageStats] = {}

    for ext, files in file_groups.items():
        lang = ext.lstrip(".")
        stats = LanguageStats(total_files=len(files))
        parser_fn = PARSERS[ext]

        for file_path in files:
            try:
                ast = parser_fn(file_path)
                all_asts[file_path] = ast
                stats.parsed_ok += 1
                stats.total_functions += len(ast.functions)
                stats.public_functions += len([f for f in ast.functions if f.visibility == "public"])
                stats.total_classes += len(ast.classes)
                stats.total_imports += len(ast.imports)
                stats.dynamic_imports += len([i for i in ast.imports if i.is_dynamic])
                stats.total_calls += len(ast.calls)
                stats.pcall_calls += len([c for c in ast.calls if c.is_pcall_wrapped])
                stats.total_exports += len(ast.exports)
                if ast.exports:
                    stats.files_with_exports += 1
                else:
                    stats.files_without_exports += 1
                stats.ctx_accesses += len(ast.ctx_accesses)
                stats.shared_dict_accesses += len(ast.shared_dict_accesses)
                stats.internal_redirects += len(ast.internal_redirects)
                stats.redis_accesses += len(ast.redis_accesses)
                stats.http_calls += len(ast.http_calls)
                stats.warnings.extend(ast.warnings)
            except Exception as e:
                stats.parse_errors += 1
                stats.error_files.append(f"{file_path}: {e}")

        lang_stats[lang] = stats

    # --- Redis abstraction resolution ---
    redis_before = sum(s.redis_accesses for s in lang_stats.values())
    resolve_redis_abstractions(all_asts)
    # Re-count redis accesses after abstraction resolution
    for ext, files in file_groups.items():
        lang = ext.lstrip(".")
        if lang in lang_stats:
            lang_stats[lang].redis_accesses = sum(
                len(all_asts[fp].redis_accesses) for fp in files
                if fp in all_asts
            )
    redis_after = sum(s.redis_accesses for s in lang_stats.values())

    # --- Format report ---

    lines.append(f"\n--- FILES ---")
    for lang, stats in lang_stats.items():
        pct = (stats.parsed_ok / stats.total_files * 100) if stats.total_files > 0 else 0
        lines.append(f"  {lang:>4}: {stats.parsed_ok:>4} / {stats.total_files:>4} parsed ({pct:.1f}%)"
                      f"  [errors: {stats.parse_errors}]")

    lines.append(f"\n--- ENTITIES ---")
    total_funcs = sum(s.total_functions for s in lang_stats.values())
    total_pub = sum(s.public_functions for s in lang_stats.values())
    total_classes = sum(s.total_classes for s in lang_stats.values())
    lines.append(f"  Functions:    {total_funcs:>6} ({total_pub} public)")
    lines.append(f"  Classes:      {total_classes:>6}")

    for lang, stats in lang_stats.items():
        if stats.total_functions > 0:
            lines.append(f"    {lang}: {stats.total_functions} functions ({stats.public_functions} public), "
                          f"{stats.total_classes} classes")

    lines.append(f"\n--- IMPORTS ---")
    total_imports = sum(s.total_imports for s in lang_stats.values())
    total_dynamic = sum(s.dynamic_imports for s in lang_stats.values())
    lines.append(f"  Total import refs:  {total_imports}")
    lines.append(f"  Dynamic imports:    {total_dynamic}")

    # Cross-reference imports: how many resolve to files in the repo?
    all_import_mods = []
    resolved_count = 0
    unresolved_internal = []
    for fp, ast in all_asts.items():
        for imp in ast.imports:
            all_import_mods.append(imp.module_string)
            if imp.is_dynamic:
                continue
            # Simple check: does the module string correspond to any file?
            if _import_likely_internal(imp.module_string, all_asts):
                resolved_count += 1
            elif _looks_internal(imp.module_string):
                unresolved_internal.append((fp, imp.module_string))

    lines.append(f"  Likely resolved:    {resolved_count} / {total_imports - total_dynamic}")
    if unresolved_internal:
        lines.append(f"  Likely internal but unresolved: {len(unresolved_internal)}")
        for fp, mod in unresolved_internal[:10]:
            lines.append(f"    {mod} (from {Path(fp).name})")
        if len(unresolved_internal) > 10:
            lines.append(f"    ... and {len(unresolved_internal) - 10} more")

    lines.append(f"\n--- EXPORTS ---")
    total_exports = sum(s.total_exports for s in lang_stats.values())
    files_with = sum(s.files_with_exports for s in lang_stats.values())
    files_without = sum(s.files_without_exports for s in lang_stats.values())
    lines.append(f"  Total exports:     {total_exports}")
    lines.append(f"  Files with exports:    {files_with}")
    lines.append(f"  Files without exports: {files_without}")

    for lang, stats in lang_stats.items():
        if stats.total_files > 0:
            pct = stats.files_with_exports / stats.total_files * 100 if stats.total_files else 0
            lines.append(f"    {lang}: {stats.files_with_exports} / {stats.total_files} ({pct:.1f}%)")
            if pct < 80:
                lines.append(f"      ⚠ LOW: Consider auditing {lang} parser export detection")

    lines.append(f"\n--- CALLS ---")
    total_calls = sum(s.total_calls for s in lang_stats.values())
    total_pcall = sum(s.pcall_calls for s in lang_stats.values())
    resolved_calls = sum(
        1 for ast in all_asts.values() for c in ast.calls if c.resolved_module
    )
    lines.append(f"  Total calls:         {total_calls}")
    lines.append(f"  Resolved to module:  {resolved_calls} ({resolved_calls/total_calls*100:.1f}%)" if total_calls else "  Total calls: 0")
    lines.append(f"  pcall-wrapped:       {total_pcall}")

    calls_per_func = total_calls / total_funcs if total_funcs else 0
    lines.append(f"  Calls per function:  {calls_per_func:.1f}")
    if calls_per_func < 0.3:
        lines.append(f"  ⚠ LOW call density — call resolution may need improvement")

    # OpenResty-specific
    total_ctx = sum(s.ctx_accesses for s in lang_stats.values())
    total_shared = sum(s.shared_dict_accesses for s in lang_stats.values())
    total_redirects = sum(s.internal_redirects for s in lang_stats.values())
    lines.append(f"\n--- OPENRESTY ---")
    lines.append(f"  ngx.ctx accesses:     {total_ctx}")
    lines.append(f"  ngx.shared accesses:  {total_shared}")
    lines.append(f"  Internal redirects:   {total_redirects}")

    # Cross-service communication
    total_redis = sum(s.redis_accesses for s in lang_stats.values())
    total_http = sum(s.http_calls for s in lang_stats.values())
    if total_redis or total_http:
        lines.append(f"\n--- CROSS-SERVICE ---")
        lines.append(f"  Redis key accesses:   {total_redis}")
        if redis_before < total_redis:
            lines.append(f"    (direct: {redis_before}, via abstractions: +{total_redis - redis_before})")
        if total_redis:
            redis_by_lang = {lang: s.redis_accesses for lang, s in lang_stats.items() if s.redis_accesses}
            for lang, count in redis_by_lang.items():
                lines.append(f"    {lang}: {count}")
        lines.append(f"  HTTP client calls:    {total_http}")
        if total_http:
            http_by_lang = {lang: s.http_calls for lang, s in lang_stats.items() if s.http_calls}
            for lang, count in http_by_lang.items():
                lines.append(f"    {lang}: {count}")

    # Lua module patterns
    if "lua" in lang_stats:
        lines.append(f"\n--- LUA MODULE PATTERNS ---")
        pattern_counts: dict[str, int] = {}
        for fp, ast in all_asts.items():
            if ast.language == "lua" and ast.module_info:
                key = ast.module_info.pattern_type.value
                pattern_counts[key] = pattern_counts.get(key, 0) + 1
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {pattern:>20}: {count}")

    # nginx.conf
    if nginx_conf:
        try:
            config = parse_nginx_conf_recursive(nginx_conf, nginx_base_path)
            lines.append(f"\n--- NGINX CONFIG ---")
            lines.append(f"  lua_package_path entries: {len(config.lua_package_path)}")
            lines.append(f"  Shared dicts: {len(config.shared_dicts)}")
            lines.append(f"  Locations: {len(config.locations)}")
            lines.append(f"  Global Lua phases: {len(config.global_phases)}")
            total_phases = sum(len(loc.phases) for loc in config.locations)
            lines.append(f"  Location Lua phases: {total_phases}")
            lines.append(f"  Include files: {len(config.include_files)}")
            lines.append(f"  Upstreams: {len(config.upstreams)}")
            proxy_count = sum(1 for loc in config.locations if loc.proxy_pass)
            lines.append(f"  Proxy_pass locations: {proxy_count}")
            if config.upstreams:
                for up in config.upstreams:
                    lines.append(f"    upstream {up.name}: {', '.join(up.servers)}")
        except Exception as e:
            lines.append(f"\n--- NGINX CONFIG ERROR ---")
            lines.append(f"  {e}")

    # Warnings
    all_warnings = []
    for s in lang_stats.values():
        all_warnings.extend(s.warnings)
    if all_warnings:
        lines.append(f"\n--- WARNINGS ({len(all_warnings)}) ---")
        for w in all_warnings[:20]:
            lines.append(f"  ⚠ {w}")
        if len(all_warnings) > 20:
            lines.append(f"  ... and {len(all_warnings) - 20} more")

    # Parse errors
    all_errors = []
    for s in lang_stats.values():
        all_errors.extend(s.error_files)
    if all_errors:
        lines.append(f"\n--- PARSE ERRORS ({len(all_errors)}) ---")
        for e in all_errors[:20]:
            lines.append(f"  ✗ {e}")
        if len(all_errors) > 20:
            lines.append(f"  ... and {len(all_errors) - 20} more")

    elapsed = time.time() - start
    lines.append(f"\n  Report generated in {elapsed:.2f}s")
    lines.append("")

    return "\n".join(lines)


def _import_likely_internal(mod_string: str, all_asts: dict[str, FileAST]) -> bool:
    """Heuristic: does this import string likely refer to a file in the repo?"""
    # Relative imports are always internal
    if mod_string.startswith("."):
        return True
    # Convert module dots to path separators and check
    as_path = mod_string.replace(".", "/")
    for fp in all_asts:
        if as_path in fp:
            return True
    return False


def _looks_internal(mod_string: str) -> bool:
    """Heuristic: does this import string look like it might be internal?"""
    # Relative paths
    if mod_string.startswith(".") or mod_string.startswith(".."):
        return True
    # Multi-part names starting with project-like prefixes
    parts = mod_string.split(".")
    if len(parts) >= 2 and parts[0] in ("app", "lib", "src", "resty", "handlers", "services", "models"):
        return True
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m graph_builder.validate.coverage_report <repo_root> [--nginx-conf path]")
        sys.exit(1)

    repo_root = sys.argv[1]
    nginx_conf = None
    if "--nginx-conf" in sys.argv:
        idx = sys.argv.index("--nginx-conf")
        if idx + 1 < len(sys.argv):
            nginx_conf = sys.argv[idx + 1]

    print(run_coverage_report(repo_root, nginx_conf))


if __name__ == "__main__":
    main()
