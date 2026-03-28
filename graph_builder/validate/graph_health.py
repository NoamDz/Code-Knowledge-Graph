"""Graph health diagnostic: full-pipeline analysis without Memgraph.

Runs the complete pipeline (parse -> resolve imports -> CallResolver -> redis abstractions)
and produces a per-language health report with technique coverage matrix.

Usage:
    code-graph health -c config.yml
"""

from __future__ import annotations

import time
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
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions, resolve_go_redis_abstractions


PARSERS = {
    "lua": parse_lua_file,
    "python": parse_python_file,
    "ruby": parse_ruby_file,
    "javascript": parse_js_file,
    "go": parse_go_file,
}

# Which languages have dedicated resolvers
RESOLVER_LANGUAGES = {"lua", "python", "go", "javascript", "ruby"}


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
    """Build language-specific resolvers (mirrors main.py logic)."""
    resolvers = {}

    # Lua resolver
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

    # Python resolver
    resolvers["python"] = PythonResolver(config.repo_root)

    # Go resolver
    from graph_builder.resolvers.go_resolver import GoResolver
    resolvers["go"] = GoResolver(config.repo_root)

    # JS resolver
    from graph_builder.resolvers.js_resolver import JsResolver
    resolvers["js"] = JsResolver(config.repo_root)

    # Ruby resolver
    from graph_builder.resolvers.ruby_resolver import RubyResolver
    resolvers["ruby"] = RubyResolver(config.repo_root)

    return resolvers


def _resolve_imports(all_asts: dict[str, FileAST], resolvers: dict) -> dict[str, dict[str, str | None]]:
    """Resolve imports across all files. Returns file_path -> {module_string -> resolved_path}."""
    resolved_imports: dict[str, dict[str, str | None]] = {}

    # Map language names to resolver keys
    lang_to_resolver = {
        "lua": "lua",
        "python": "python",
        "go": "go",
        "javascript": "js",
        "ruby": "ruby",
    }

    for file_path, ast in all_asts.items():
        file_resolved: dict[str, str | None] = {}
        for imp in ast.imports:
            if imp.is_dynamic:
                continue
            resolver_key = lang_to_resolver.get(ast.language)
            resolver = resolvers.get(resolver_key) if resolver_key else None
            if resolver:
                # Go stdlib imports (fmt, net/http, etc.) won't resolve to
                # repo files — classify them as resolved before trying.
                if ast.language == "go" and hasattr(resolver, "is_stdlib") and resolver.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "<go-stdlib>"
                    continue
                if ast.language == "ruby":
                    file_resolved[imp.module_string] = resolver.resolve(
                        imp.module_string, file_path, import_type=imp.import_type,
                    )
                else:
                    file_resolved[imp.module_string] = resolver.resolve(
                        imp.module_string, file_path,
                    )
            else:
                file_resolved[imp.module_string] = None
        resolved_imports[file_path] = file_resolved

    return resolved_imports


def run_health_report(config: Config) -> str:
    """Run the full pipeline and produce a health diagnostic report."""
    start = time.time()
    lines: list[str] = []

    lines.append("")
    lines.append("=" * 70)
    lines.append("  GRAPH HEALTH DIAGNOSTIC")
    lines.append(f"  Repository: {config.repo_root}")
    lines.append("=" * 70)

    # --- Step 1: Parse ---
    all_asts, parse_errors = _parse_all_files(config)
    if not all_asts:
        lines.append("\n  ERROR: No files parsed. Check repo_root in config.")
        return "\n".join(lines)

    # --- Step 2: Build resolvers ---
    resolvers = _build_resolvers(config)

    # --- Step 3: Resolve imports ---
    resolved_imports = _resolve_imports(all_asts, resolvers)

    # --- Step 4: Call resolution ---
    call_resolver = CallResolver(all_asts, resolvers)
    call_resolver.resolve_all()
    call_stats = call_resolver.stats()

    # --- Step 4b: Parameter name resolution ---
    from graph_builder.resolvers.parameter_resolver import resolve_parameter_calls
    param_resolved = resolve_parameter_calls(all_asts)

    # --- Step 4c: Base class inheritance resolution ---
    from graph_builder.resolvers.base_inheritance_resolver import resolve_base_inheritance
    base_resolved = resolve_base_inheritance(all_asts)

    # --- Step 5: Redis abstraction resolution ---
    redis_before = sum(len(ast.redis_accesses) for ast in all_asts.values())
    resolve_redis_abstractions(all_asts)
    resolve_go_redis_abstractions(all_asts)  # 4A: Go Redis wrapper detection
    redis_after = sum(len(ast.redis_accesses) for ast in all_asts.values())

    # --- Step 6: Classify unresolved calls ---
    from graph_builder.resolvers.builtin_classifier import BuiltinClassifier
    classifier = BuiltinClassifier()
    classifier.classify_all(all_asts)
    class_stats = classifier.stats()

    # --- Step 7: Cross-service IPC resolution ---
    from graph_builder.resolvers.cross_service_resolver import (
        resolve_unix_sockets,
        resolve_shared_redis_patterns,
        resolve_database_accesses,
        resolve_aws_service_accesses,
        resolve_shared_configs,
        KNOWN_SOCKET_CONNECTIONS,
    )
    from graph_builder.resolvers.mission_resolver import resolve_missions, resolve_mission_targets

    resolve_database_accesses(all_asts)
    resolve_aws_service_accesses(all_asts)
    socket_edges = resolve_unix_sockets(all_asts)
    redis_pattern_edges = resolve_shared_redis_patterns(all_asts)
    config_edges = resolve_shared_configs(all_asts)
    resolve_missions(all_asts)
    mission_results = resolve_mission_targets(all_asts)

    # --- Collect per-language stats ---
    lang_data: dict[str, dict] = defaultdict(lambda: {
        "files": 0,
        "functions": 0,
        "public_functions": 0,
        "classes": 0,
        "imports_total": 0,
        "imports_resolved": 0,
        "imports_dynamic": 0,
        "calls_total": 0,
        "calls_resolved": 0,
        "exports_total": 0,
        "files_with_exports": 0,
        "redis_accesses": 0,
        "http_calls": 0,
        "funcs_with_outgoing_calls": 0,
        "orphan_functions": 0,
        "file_paths": [],
        "file_import_counts": {},
        "file_imported_by": defaultdict(int),
        "has_local_binding_tracking": False,
        "has_qualified_names": False,
        "has_class_detection": False,
    })

    # Track which files import which files (for orphan / connectivity)
    # file_path -> set of files it imports from
    file_imports_from: dict[str, set[str]] = defaultdict(set)
    # file_path -> set of files that import it
    file_imported_by: dict[str, set[str]] = defaultdict(set)

    for file_path, ast in all_asts.items():
        lang = ast.language
        d = lang_data[lang]
        d["files"] += 1
        d["functions"] += len(ast.functions)
        d["public_functions"] += sum(1 for f in ast.functions if f.visibility == "public")
        d["classes"] += len(ast.classes)
        d["exports_total"] += len(ast.exports)
        if ast.exports:
            d["files_with_exports"] += 1
        d["redis_accesses"] += len(ast.redis_accesses)
        d["http_calls"] += len(ast.http_calls)
        d["file_paths"].append(file_path)

        # Import stats
        file_resolved = resolved_imports.get(file_path, {})
        for imp in ast.imports:
            d["imports_total"] += 1
            if imp.is_dynamic:
                d["imports_dynamic"] += 1
                continue
            resolved_path = file_resolved.get(imp.module_string)
            if resolved_path:
                d["imports_resolved"] += 1
                file_imports_from[file_path].add(resolved_path)
                file_imported_by[resolved_path].add(file_path)

            # Track binding support
            if imp.local_binding:
                d["has_local_binding_tracking"] = True

        # Call stats
        callers_with_calls: set[str] = set()
        resolved_callers: set[str] = set()
        for call in ast.calls:
            d["calls_total"] += 1
            if call.resolved_module:
                d["calls_resolved"] += 1
                resolved_callers.add(call.caller_function)
            callers_with_calls.add(call.caller_function)

        # Qualified names
        for func in ast.functions:
            if func.qualified_name:
                d["has_qualified_names"] = True
                break

        # Class detection
        if ast.classes:
            d["has_class_detection"] = True

        # Connectivity: functions with outgoing calls vs orphans
        all_func_names = {f.name for f in ast.functions}
        # Normalize caller names: Ruby uses "ClassName#method" but
        # FunctionDef.name stores bare "method". Strip class prefix.
        normalized_callers = set()
        for caller in callers_with_calls:
            if "#" in caller:
                normalized_callers.add(caller.split("#")[-1])
            else:
                normalized_callers.add(caller)
        # Also normalize callers that made resolved calls (Python self-resolution
        # sets resolved_module/resolved_function but caller_function may use
        # "ClassName.method" form that doesn't match FunctionDef.name).
        normalized_resolved = set()
        for caller in resolved_callers:
            if "#" in caller:
                normalized_resolved.add(caller.split("#")[-1])
            elif "." in caller:
                normalized_resolved.add(caller.rsplit(".", 1)[-1])
            else:
                normalized_resolved.add(caller)
        funcs_that_call = (normalized_callers | normalized_resolved) & all_func_names
        d["funcs_with_outgoing_calls"] += len(funcs_that_call)
        d["orphan_functions"] += len(all_func_names - (normalized_callers | normalized_resolved))

        # Per-file import count
        d["file_import_counts"][file_path] = len(ast.imports)

    # --- Format the report ---

    # Per-language sections
    for lang in sorted(lang_data.keys()):
        d = lang_data[lang]
        lines.append("")
        lines.append(f"  {'─' * 66}")
        lines.append(f"  LANGUAGE: {lang.upper()}")
        lines.append(f"  {'─' * 66}")

        # Basic counts
        lines.append(f"  Files:           {d['files']}")
        lines.append(f"  Functions:       {d['functions']} ({d['public_functions']} public)")
        lines.append(f"  Classes:         {d['classes']}")

        # Export coverage
        if d["files"] > 0:
            export_pct = d["files_with_exports"] / d["files"] * 100
            lines.append(f"  Export coverage: {d['files_with_exports']}/{d['files']} files ({export_pct:.1f}%)")
        else:
            lines.append(f"  Export coverage: N/A")

        # Import resolution
        non_dynamic = d["imports_total"] - d["imports_dynamic"]
        if non_dynamic > 0:
            import_pct = d["imports_resolved"] / non_dynamic * 100
            lines.append(f"  Import resolution: {d['imports_resolved']}/{non_dynamic} ({import_pct:.1f}%)")
        else:
            lines.append(f"  Import resolution: no static imports")

        # Call resolution
        if d["calls_total"] > 0:
            call_pct = d["calls_resolved"] / d["calls_total"] * 100
            lines.append(f"  Call resolution:   {d['calls_resolved']}/{d['calls_total']} ({call_pct:.1f}%)")
        else:
            lines.append(f"  Call resolution:   no calls detected")

        # Redis / HTTP / IPC
        lines.append(f"  Redis accesses:  {d['redis_accesses']}")
        lines.append(f"  HTTP calls:      {d['http_calls']}")

        # Connectivity
        lines.append(f"  Functions w/ outgoing calls: {d['funcs_with_outgoing_calls']}")
        lines.append(f"  Orphan functions (0 calls):  {d['orphan_functions']}")

        # Top importers (files with most dependencies)
        if d["file_import_counts"]:
            sorted_importers = sorted(
                d["file_import_counts"].items(), key=lambda x: -x[1]
            )[:5]
            lines.append(f"  Top importers:")
            for fp, count in sorted_importers:
                lines.append(f"    {count:>3} imports  {Path(fp).name}")

        # Orphan files (no imports in AND no imports out)
        orphan_files = []
        for fp in d["file_paths"]:
            has_imports_out = bool(file_imports_from.get(fp))
            has_imports_in = bool(file_imported_by.get(fp))
            if not has_imports_out and not has_imports_in:
                orphan_files.append(fp)
        if orphan_files:
            lines.append(f"  Orphan files (no import edges): {len(orphan_files)}")
            for fp in orphan_files[:5]:
                lines.append(f"    {Path(fp).name}")
            if len(orphan_files) > 5:
                lines.append(f"    ... and {len(orphan_files) - 5} more")

    # --- Technique coverage matrix ---
    lines.append("")
    lines.append(f"  {'─' * 66}")
    lines.append(f"  TECHNIQUE COVERAGE MATRIX")
    lines.append(f"  {'─' * 66}")

    # Column headers
    techniques = [
        ("Import resolver", lambda lang, d: "YES" if lang in RESOLVER_LANGUAGES else "no"),
        ("Binding tracking", lambda lang, d: "YES" if d["has_local_binding_tracking"] else "no"),
        ("Call resolution",
         lambda lang, d: f"{d['calls_resolved'] / d['calls_total'] * 100:.0f}%"
         if d["calls_total"] > 0 else "N/A"),
        ("Redis detection", lambda lang, d: "YES" if d["redis_accesses"] > 0 else "no"),
        ("HTTP detection", lambda lang, d: "YES" if d["http_calls"] > 0 else "no"),
        ("Qualified names", lambda lang, d: "YES" if d["has_qualified_names"] else "no"),
        ("Class/inherit", lambda lang, d: "YES" if d["has_class_detection"] else "no"),
    ]

    # Build matrix
    langs_sorted = sorted(lang_data.keys())
    header = f"  {'Technique':<22}"
    for lang in langs_sorted:
        header += f" {lang:>12}"
    lines.append(header)
    lines.append(f"  {'─' * 22}" + "".join(f" {'─' * 12}" for _ in langs_sorted))

    for tech_name, tech_fn in techniques:
        row = f"  {tech_name:<22}"
        for lang in langs_sorted:
            val = tech_fn(lang, lang_data[lang])
            row += f" {val:>12}"
        lines.append(row)

    # --- Cross-service IPC section ---
    lines.append("")
    lines.append(f"  {'─' * 66}")
    lines.append(f"  CROSS-SERVICE IPC")
    lines.append(f"  {'─' * 66}")

    total_db = sum(len(ast.db_accesses) for ast in all_asts.values())
    total_aws = sum(len(ast.aws_accesses) for ast in all_asts.values())
    total_missions = sum(len(ast.mission_dispatches) for ast in all_asts.values())
    resolved_missions_count = len([m for m in mission_results if m["target_file"]])

    lines.append(f"  Unix sockets:        {len(socket_edges)} edges ({len(KNOWN_SOCKET_CONNECTIONS)} sockets)")
    lines.append(f"  Mission dispatches:  {total_missions} detected, {resolved_missions_count} resolved")
    lines.append(f"  Redis patterns:      {len(redis_pattern_edges)} cross-language edges")
    lines.append(f"  Database accesses:   {total_db} (MySQL + Cassandra)")
    lines.append(f"  AWS services:        {total_aws} (SQS + Kinesis + S3)")
    lines.append(f"  Shared configs:      {len(config_edges)} edges")

    # Breakdown by type
    db_by_type: dict[str, int] = defaultdict(int)
    for ast in all_asts.values():
        for da in ast.db_accesses:
            db_by_type[da.db_type] += 1
    if db_by_type:
        for db_type, count in sorted(db_by_type.items()):
            lines.append(f"    {db_type}: {count}")

    aws_by_type: dict[str, int] = defaultdict(int)
    for ast in all_asts.values():
        for sa in ast.aws_accesses:
            aws_by_type[sa.service] += 1
    if aws_by_type:
        for svc, count in sorted(aws_by_type.items()):
            lines.append(f"    {svc}: {count}")

    # --- Global summary ---
    lines.append("")
    lines.append(f"  {'─' * 66}")
    lines.append(f"  GLOBAL SUMMARY")
    lines.append(f"  {'─' * 66}")

    total_files = sum(d["files"] for d in lang_data.values())
    total_funcs = sum(d["functions"] for d in lang_data.values())
    total_classes = sum(d["classes"] for d in lang_data.values())
    total_imports = sum(d["imports_total"] for d in lang_data.values())
    total_imports_resolved = sum(d["imports_resolved"] for d in lang_data.values())
    total_imports_non_dynamic = sum(
        d["imports_total"] - d["imports_dynamic"] for d in lang_data.values()
    )

    lines.append(f"  Total files:     {total_files} ({len(parse_errors)} parse errors)")
    lines.append(f"  Total functions: {total_funcs}")
    lines.append(f"  Total classes:   {total_classes}")

    if total_imports_non_dynamic > 0:
        pct = total_imports_resolved / total_imports_non_dynamic * 100
        lines.append(f"  Import resolution: {total_imports_resolved}/{total_imports_non_dynamic} ({pct:.1f}%)")

    total_resolved = call_stats['already_resolved'] + call_stats['newly_resolved'] + param_resolved + base_resolved
    total_calls = call_stats['total_calls']
    total_pct = total_resolved / total_calls * 100 if total_calls else 0
    lines.append(f"  Call resolution:   {total_calls} total, "
                 f"{total_resolved} resolved ({total_pct:.1f}%)")
    if param_resolved or base_resolved:
        lines.append(f"    (CallResolver: {call_stats['already_resolved'] + call_stats['newly_resolved']}, "
                     f"parameter: +{param_resolved}, base-inherited: +{base_resolved})")

    lines.append(f"  Call classification:")
    lines.append(f"    Builtins:          {class_stats['builtin']}")
    lines.append(f"    External:          {class_stats['external']}")
    lines.append(f"    Truly unresolved:  {class_stats['truly_unresolved']}")

    lines.append(f"  Redis accesses:  {redis_after}"
                 + (f" (direct: {redis_before}, via abstractions: +{redis_after - redis_before})"
                    if redis_after > redis_before else ""))

    total_http = sum(d["http_calls"] for d in lang_data.values())
    lines.append(f"  HTTP calls:      {total_http}")

    # Parse errors
    if parse_errors:
        lines.append(f"\n  PARSE ERRORS ({len(parse_errors)}):")
        for fp, err in parse_errors[:10]:
            lines.append(f"    {Path(fp).name}: {err}")
        if len(parse_errors) > 10:
            lines.append(f"    ... and {len(parse_errors) - 10} more")

    elapsed = time.time() - start
    lines.append(f"\n  Report generated in {elapsed:.2f}s")
    lines.append("")

    return "\n".join(lines)
