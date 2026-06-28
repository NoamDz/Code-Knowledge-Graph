"""CLI entry point for the code knowledge graph.

Commands:
    code-graph build           Full graph build
    code-graph update          Incremental update (changed files only)
    code-graph validate        Run validation / coverage report
    code-graph health          Graph health diagnostic (no Memgraph needed)
    code-graph export-dot      Export graph as Graphviz DOT (no Memgraph needed)
    code-graph spot-check      Inspect a single file's parse results
    code-graph audit           Run Lua codebase audit
    code-graph schema          Create Memgraph indexes
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from .config import Config
from .scanner import FileScanner
from .parsers.lua_parser import parse_lua_file
from .parsers.python_parser import parse_python_file
from .parsers.ruby_parser import parse_ruby_file
from .parsers.js_parser import parse_js_file
from .parsers.go_parser import parse_go_file
from .parsers.nginx_parser import parse_nginx_conf, parse_nginx_conf_recursive
from .parsers.base import FileAST
from .resolvers.lua_resolver import LuaResolver
from .resolvers.call_resolver import CallResolver
from .resolvers.redis_abstraction_resolver import resolve_redis_abstractions, resolve_go_redis_abstractions
from .resolvers.builtin_classifier import BuiltinClassifier
from .validate.spot_check import spot_check
from .validate.coverage_report import run_coverage_report
from .validate.graph_health import run_health_report
from .validate.graph_export_dot import generate_dot


PARSERS = {
    "lua": parse_lua_file,
    "python": parse_python_file,
    "ruby": parse_ruby_file,
    "javascript": parse_js_file,
    "go": parse_go_file,
}


def _load_config(config_path: str | None) -> Config:
    """Load config from YAML file or return defaults."""
    if config_path and Path(config_path).exists():
        return Config.from_yaml(config_path)
    return Config.default()


def _parse_all_files(config: Config) -> dict[str, FileAST]:
    """Parse all source files in the repository."""
    scanner = FileScanner(config)
    all_files = scanner.scan()
    all_asts: dict[str, FileAST] = {}
    errors: list[tuple[str, str]] = []

    click.echo(f"Scanning {len(all_files)} files...")

    for file_path, language in all_files:
        parser_fn = PARSERS.get(language)
        if not parser_fn:
            continue
        try:
            ast = parser_fn(file_path)
            all_asts[file_path] = ast
        except Exception as e:
            errors.append((file_path, str(e)))

    click.echo(f"Parsed {len(all_asts)} files ({len(errors)} errors)")
    for fp, err in errors[:10]:
        click.echo(f"  ERROR: {fp}: {err}", err=True)

    return all_asts


def _build_resolvers(config: Config) -> dict:
    """Build language-specific resolvers."""
    resolvers = {}

    # Collect Lua package paths from all sources
    package_paths = list(config.lua_package_paths)  # from config.yml

    # Also parse nginx.conf for lua_package_path
    if config.nginx_conf and Path(config.nginx_conf).exists():
        try:
            nginx_config = parse_nginx_conf_recursive(
                config.nginx_conf, config.nginx_base_path,
            )
            for p in nginx_config.lua_package_path:
                if p not in package_paths:
                    package_paths.append(p)
        except Exception as e:
            click.echo(f"Warning: Failed to parse nginx.conf: {e}", err=True)

    if package_paths:
        click.echo(f"  Lua package paths: {len(package_paths)} templates")

    resolvers["lua"] = LuaResolver(package_paths, config.repo_root)

    # Python resolver
    from .resolvers.python_resolver import PythonResolver
    resolvers["python"] = PythonResolver(config.repo_root)

    # Go resolver
    from .resolvers.go_resolver import GoResolver
    resolvers["go"] = GoResolver(config.repo_root)

    # JS resolver
    from .resolvers.js_resolver import JsResolver
    resolvers["js"] = JsResolver(config.repo_root)

    # Ruby resolver
    from .resolvers.ruby_resolver import RubyResolver
    resolvers["ruby"] = RubyResolver(config.repo_root)

    return resolvers


@click.group()
@click.option("-c", "--config", "config_path", default=None,
              help="Path to config YAML file")
@click.pass_context
def cli(ctx, config_path):
    """Code Knowledge Graph — build, query, and maintain a semantic map of your codebase."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = _load_config(config_path)


@cli.command()
@click.pass_context
def build(ctx):
    """Full graph build: scan → parse → resolve → ingest."""
    config = ctx.obj["config"]
    start = time.time()

    click.echo(f"Building code graph for: {config.repo_root}")

    # Step 1: Parse all files
    all_asts = _parse_all_files(config)
    if not all_asts:
        click.echo("No files parsed. Check repo_root in config.", err=True)
        sys.exit(1)

    # Step 2: Build resolvers
    resolvers = _build_resolvers(config)

    # Step 3: Resolve imports
    click.echo("Resolving cross-file imports...")
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
        file_resolved = {}
        for imp in ast.imports:
            if imp.is_dynamic:
                continue
            # Go stdlib/external classification: mark before normal resolution
            if ast.language == "go":
                go_res = resolvers.get("go")
                if go_res and hasattr(go_res, 'is_stdlib') and go_res.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "__go_stdlib__"
                    continue
                if go_res and hasattr(go_res, 'is_external') and go_res.is_external(imp.module_string):
                    file_resolved[imp.module_string] = "__go_external__"
                    continue
            # Python stdlib classification
            if ast.language == "python":
                py_res = resolvers.get("python")
                if py_res and hasattr(py_res, 'is_stdlib') and py_res.is_stdlib(imp.module_string):
                    file_resolved[imp.module_string] = "__python_stdlib__"
                    continue
            resolver_key = lang_to_resolver.get(ast.language)
            resolver = resolvers.get(resolver_key) if resolver_key else None
            if resolver:
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

    # Step 4: Run cross-file call resolution
    click.echo("Resolving cross-file calls...")
    call_resolver = CallResolver(all_asts, resolvers)
    call_resolver.resolve_all()
    call_stats = call_resolver.stats()
    click.echo(f"  Calls: {call_stats['total_calls']} total, "
               f"{call_stats['already_resolved'] + call_stats['newly_resolved']} resolved "
               f"({call_stats['resolution_rate']:.1f}%)")

    # Step 4b: Resolve Redis abstractions
    click.echo("Resolving Redis abstraction layers...")
    redis_before = sum(len(ast.redis_accesses) for ast in all_asts.values())
    resolve_redis_abstractions(all_asts)
    resolve_go_redis_abstractions(all_asts)
    redis_after = sum(len(ast.redis_accesses) for ast in all_asts.values())
    redis_added = redis_after - redis_before
    if redis_added > 0:
        click.echo(f"  Redis accesses via abstractions: +{redis_added} (total: {redis_after})")

    # Step 4b1: Resolve Ruby dynamic loading (Dir.glob, class_eval)
    ruby_resolver = resolvers.get("ruby")
    ruby_dynamic_edges: list[dict] = []
    if ruby_resolver and hasattr(ruby_resolver, "resolve_dynamic_loading"):
        ruby_dynamic_edges = ruby_resolver.resolve_dynamic_loading(all_asts)
        if ruby_dynamic_edges:
            click.echo(f"  Ruby dynamic loading: {len(ruby_dynamic_edges)} edges")

    # Step 4b2: Resolve parameter name calls
    click.echo("Resolving parameter-name calls...")
    from .resolvers.parameter_resolver import resolve_parameter_calls
    param_resolved = resolve_parameter_calls(all_asts)
    if param_resolved:
        click.echo(f"  Parameter calls resolved: {param_resolved}")

    # Step 4b3: Resolve base-inherited calls
    from .resolvers.base_inheritance_resolver import resolve_base_inheritance
    base_resolved = resolve_base_inheritance(all_asts)
    if base_resolved:
        click.echo(f"  Base-inherited calls resolved: {base_resolved}")

    # Step 4c: Classify unresolved calls
    click.echo("Classifying unresolved calls...")
    classifier = BuiltinClassifier()
    classifier.classify_all(all_asts)
    class_stats = classifier.stats()
    click.echo(f"  Builtins: {class_stats['builtin']}, External: {class_stats['external']}, "
               f"Truly unresolved: {class_stats['truly_unresolved']}")

    # Step 4d: Cross-language endpoint linking
    click.echo("Linking cross-language endpoints...")
    from .resolvers.endpoint_linker import EndpointLinker
    nginx_config_obj = None
    if config.nginx_conf and Path(config.nginx_conf).exists():
        nginx_config_obj = parse_nginx_conf_recursive(
            config.nginx_conf, config.nginx_base_path,
        )
    linker = EndpointLinker(nginx_config_obj)
    linker.register_internal_endpoints()
    go_registry = linker.build_go_handler_registry(all_asts)
    linker.register_go_handlers(go_registry)

    # Auto-discover controller routes from parsed Lua controller files
    controller_routes = {}
    for fp in all_asts:
        fp_norm = fp.replace("\\", "/")
        if "/controllers/" in fp_norm and fp_norm.endswith(".lua"):
            parts = fp_norm.split("/controllers/", 1)
            if len(parts) == 2:
                ctrl_name = parts[1].replace(".lua", "")
                route = f"/controllers/{ctrl_name}"
                controller_routes[route] = fp
    if controller_routes:
        linker.register_controller_routes(controller_routes)
        click.echo(f"  Controller routes: {len(controller_routes)}")

    endpoint_links = linker.link_all(all_asts)
    if endpoint_links:
        click.echo(f"  Linked {len(endpoint_links)} cross-language HTTP calls to endpoints")

    # Step 4e: Mission dispatch resolution (two-phase)
    from .resolvers.mission_resolver import resolve_missions, resolve_mission_targets
    resolve_missions(all_asts)  # Phase 1: populate ast.mission_dispatches
    missions = resolve_mission_targets(all_asts)  # Phase 2: match to task files
    total_dispatches = sum(len(ast.mission_dispatches) for ast in all_asts.values())
    if missions:
        resolved_count = sum(1 for m in missions if m["target_file"])
        click.echo(f"  Missions: {total_dispatches} dispatches, {resolved_count} resolved to files")

    # Step 4f: Dynamic prefix expansion
    from .resolvers.dynamic_prefix_resolver import resolve_dynamic_prefixes
    dynamic_edges, dynamic_stats = resolve_dynamic_prefixes(all_asts)
    if dynamic_edges:
        click.echo(f"  Dynamic prefix expansion: {len(dynamic_edges)} potential imports "
                   f"({dynamic_stats['prefixes_processed']} prefixes processed)")

    # Step 4g: Resolve JS ERB render-chain inclusions
    click.echo("Resolving JS ERB render-chain inclusions...")
    from .resolvers.js_erb_resolver import JsErbResolver
    js_erb_resolver = JsErbResolver(config.repo_root)
    js_erb_edges = js_erb_resolver.resolve_all(all_asts)
    if js_erb_edges:
        render_edges = [e for e in js_erb_edges if e["type"] == "render"]
        collector_edges = [e for e in js_erb_edges if e["type"] == "collector_loop"]
        click.echo(f"  ERB render includes: {len(render_edges)}, "
                   f"collector loop includes: {len(collector_edges)}")

    # Step 4h: Cross-service IPC detection
    click.echo("Detecting cross-service IPC patterns...")
    from .resolvers.cross_service_resolver import (
        resolve_unix_sockets,
        resolve_shared_redis_patterns,
        resolve_database_accesses,
        resolve_aws_service_accesses,
        resolve_shared_configs,
    )
    socket_edges = resolve_unix_sockets(all_asts)
    redis_pattern_edges = resolve_shared_redis_patterns(all_asts)
    resolve_database_accesses(all_asts)
    resolve_aws_service_accesses(all_asts)
    config_edges = resolve_shared_configs(all_asts)

    total_db = sum(len(ast.db_accesses) for ast in all_asts.values())
    total_aws = sum(len(ast.aws_accesses) for ast in all_asts.values())
    click.echo(f"  Unix sockets: {len(socket_edges)}, "
               f"Redis patterns: {len(redis_pattern_edges)}, "
               f"DB accesses: {total_db}, AWS accesses: {total_aws}, "
               f"Config edges: {len(config_edges)}")

    # Step 4i: Cross-language data flow detection
    click.echo("Detecting cross-language shared structures and constants...")
    from .resolvers.cross_language_resolver import (
        resolve_shared_structures,
        resolve_shared_constants,
    )
    structure_edges = resolve_shared_structures(all_asts)
    constant_edges = resolve_shared_constants(all_asts)
    if structure_edges or constant_edges:
        click.echo(f"  Shared structures: {len(structure_edges)} edges, "
                   f"shared constants: {len(constant_edges)} edges")

    # Step 5: Ingest into Memgraph
    click.echo("Ingesting into Memgraph...")
    try:
        from .ingestion.writer import GraphWriter
        from .ingestion.schema import create_indexes

        writer = GraphWriter(
            uri=config.memgraph.uri,
            username=config.memgraph.username,
            password=config.memgraph.password,
        )

        # Create indexes
        with writer.driver.session() as session:
            create_indexes(session)

        # Ingest all files FIRST and flush, so the File nodes exist before any
        # linking step matches against them. nginx HANDLES edges (below) and the
        # Go/socket/structure linkers (further down) all MATCH (f:File {...}); on
        # a fresh `build` graph those matches silently no-op if files aren't yet
        # flushed. (`update` re-ingests into an already-populated graph, so it
        # never hit this — but `build` must work from empty.)
        for file_path, ast in all_asts.items():
            writer.ingest_file_ast(ast, resolved_imports.get(file_path, {}))

        writer.flush_all()

        # Ingest nginx endpoints (after the File flush above so HANDLES matches).
        if config.nginx_conf and Path(config.nginx_conf).exists():
            nginx_config = parse_nginx_conf_recursive(
                config.nginx_conf, config.nginx_base_path,
            )
            for loc in nginx_config.locations:
                for phase in loc.phases:
                    writer.upsert_nginx_endpoint(
                        loc.path, phase.phase,
                        phase.lua_file, phase.is_inline,
                    )
                # Ingest proxy_pass → Service edges
                if loc.proxy_pass:
                    # Try to find upstream name from target
                    upstream_name = None
                    target = loc.proxy_pass.target
                    for upstream in nginx_config.upstreams:
                        if upstream.name in target:
                            upstream_name = upstream.name
                            break
                    writer.upsert_proxy_pass(loc.path, target, upstream_name)

            # Ingest upstream definitions
            for upstream in nginx_config.upstreams:
                writer.upsert_upstream(upstream.name, upstream.servers)

            proxy_count = sum(1 for loc in nginx_config.locations if loc.proxy_pass)
            click.echo(f"  Ingested {len(nginx_config.locations)} nginx locations, "
                       f"{proxy_count} proxy_pass, {len(nginx_config.upstreams)} upstreams")

            # Link inline content_by_lua_block require() targets into the call
            # graph so explain_flow can traverse past [content] (inline).
            from .parsers.nginx_parser import resolve_inline_phase_handles
            lua_resolver = resolvers.get("lua")
            if lua_resolver:
                inline_edges = resolve_inline_phase_handles(
                    nginx_config.locations, lua_resolver,
                )
                for loc_path, phase_name, resolved_file in inline_edges:
                    writer.upsert_phase_handles_file(loc_path, phase_name, resolved_file)
                if inline_edges:
                    click.echo(f"  Inline-block HANDLES edges: {len(inline_edges)}")

            # B3: link *_by_lua_file phases to their real File nodes. nginx
            # declares deploy paths (/data/kashmir/pinpoint/...) but the graph
            # indexes build paths (.../src/...); resolve by longest suffix.
            from .parsers.nginx_parser import resolve_file_phase_handles
            file_edges = resolve_file_phase_handles(
                nginx_config.locations, all_asts.keys(),
            )
            for loc_path, phase_name, resolved_file in file_edges:
                writer.upsert_phase_handles_file(loc_path, phase_name, resolved_file)
            if file_edges:
                click.echo(f"  File-phase HANDLES edges: {len(file_edges)}")

            # B1: link fallback locations (try_files -> @named) so explain_flow
            # can follow the delegation chain (e.g. / -> @router -> main.lua).
            delegation_count = 0
            for loc in nginx_config.locations:
                if loc.try_files_target:
                    writer.upsert_endpoint_delegation(loc.path, loc.try_files_target)
                    delegation_count += 1
            if delegation_count:
                click.echo(f"  Endpoint delegations (try_files): {delegation_count}")

        # Go same-package linking
        go_resolver = resolvers.get("go")
        if go_resolver and hasattr(go_resolver, "get_package_siblings"):
            pkg_edges = 0
            seen = set()
            for file_path, ast in all_asts.items():
                if ast.language == "go":
                    siblings = go_resolver.get_package_siblings(file_path)
                    for sibling in siblings:
                        edge_key = tuple(sorted([file_path, sibling]))
                        if edge_key not in seen:
                            writer.upsert_same_package(file_path, sibling, "server")
                            seen.add(edge_key)
                            pkg_edges += 1
            if pkg_edges:
                click.echo(f"  Go same-package edges: {pkg_edges}")

        # Ingest dynamic prefix edges
        if dynamic_edges:
            for edge in dynamic_edges:
                writer.upsert_potential_import(
                    edge["source_file"], edge["target_file"],
                    edge["prefix"], edge["line"],
                )

        # Ingest mission dispatch edges
        if missions:
            for m in missions:
                if m.get("target_file"):
                    writer.upsert_mission_dispatch(
                        m["source_file"], m["task_name"],
                        m["target_file"], m["line"],
                    )

        # Ingest JS ERB render-chain edges
        if js_erb_edges:
            for edge in js_erb_edges:
                writer.upsert_js_includes(
                    edge["source_file"], edge["target_file"], edge["type"],
                )

        # Ingest cross-service IPC edges
        for edge in socket_edges:
            writer.upsert_unix_socket(edge["socket"], edge["protocol"])
            if edge["role"] == "listener":
                writer.upsert_socket_listens(edge["file"], edge["socket"])
            else:
                writer.upsert_socket_connects(edge["file"], edge["socket"])

        for edge in redis_pattern_edges:
            writer.upsert_shared_redis_pattern(
                edge["pattern"], edge["file"], edge["access_type"],
            )

        for edge in config_edges:
            writer.upsert_config_reads(edge["file"], edge["config"])

        # Ingest Ruby dynamic loading edges
        if ruby_dynamic_edges:
            for edge in ruby_dynamic_edges:
                writer.upsert_dynamic_load(
                    edge["source"], edge["target"], edge["load_type"],
                )

        # Ingest cross-language shared structure edges
        seen_structures: set[str] = set()
        for edge in structure_edges:
            struct_name = edge["structure_name"]
            if struct_name not in seen_structures:
                writer.upsert_shared_data_structure(
                    struct_name, edge["fields"], edge["serialization"],
                )
                seen_structures.add(struct_name)
            writer.upsert_defines_structure(
                edge["file"], struct_name,
                edge["language"], edge["field_count"],
            )

        # Ingest cross-language shared constant edges
        seen_constants: set[str] = set()
        for edge in constant_edges:
            const_name = edge["constant_name"]
            if const_name not in seen_constants:
                writer.upsert_shared_constant(const_name, edge["values"])
                seen_constants.add(const_name)
            writer.upsert_defines_constant(
                edge["file"], const_name, edge["language"],
            )

        click.echo(f"  {writer.write_count} graph writes")
        writer.close()

    except Exception as e:
        click.echo(f"\nMemgraph ingestion failed: {e}", err=True)
        click.echo("Graph was parsed and resolved but not ingested.")
        click.echo("Is Memgraph running? (docker compose up -d)")
        click.echo(f"\nParsed {len(all_asts)} files successfully.")

    elapsed = time.time() - start
    click.echo(f"\nBuild completed in {elapsed:.1f}s")


@cli.command()
@click.pass_context
def validate(ctx):
    """Run the coverage report against the codebase."""
    config = ctx.obj["config"]
    report = run_coverage_report(
        config.repo_root, config.nginx_conf, config.nginx_base_path,
        config=config,
    )
    click.echo(report)


@cli.command("spot-check")
@click.argument("file_path")
def spot_check_cmd(file_path):
    """Inspect what the parser extracted from a single file."""
    result = spot_check(file_path)
    click.echo(result)


@cli.command()
@click.pass_context
def audit(ctx):
    """Run the Lua codebase audit."""
    config = ctx.obj["config"]
    import importlib
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from audit.lua_audit import audit_lua_files
    result = audit_lua_files(config.repo_root)
    click.echo(result)


@cli.command()
@click.pass_context
def schema(ctx):
    """Create Memgraph indexes and schema."""
    config = ctx.obj["config"]
    from .ingestion.writer import GraphWriter
    from .ingestion.schema import create_indexes

    try:
        writer = GraphWriter(
            uri=config.memgraph.uri,
            username=config.memgraph.username,
            password=config.memgraph.password,
        )
        with writer.driver.session() as session:
            results = create_indexes(session)
            for r in results:
                click.echo(f"  {r}")
        writer.close()
        click.echo("Schema created successfully.")
    except Exception as e:
        click.echo(f"Failed to connect to Memgraph: {e}", err=True)
        click.echo("Is Memgraph running? (docker compose up -d)")
        sys.exit(1)


@cli.command()
@click.pass_context
def update(ctx):
    """Incremental update: re-ingest only changed files."""
    config = ctx.obj["config"]

    from .change_tracker import GitChangeTracker
    from .ingestion.writer import GraphWriter
    from .ingestion.incremental import reingest_file

    tracker = GitChangeTracker(config.repo_root)
    changed = tracker.get_changed_files()
    uncommitted = tracker.get_uncommitted_changes()
    all_changed = sorted(set(changed + uncommitted))

    if not all_changed:
        click.echo("No changed files detected.")
        return

    click.echo(f"Found {len(all_changed)} changed files")

    try:
        writer = GraphWriter(
            uri=config.memgraph.uri,
            username=config.memgraph.username,
            password=config.memgraph.password,
        )

        success = 0
        for fp in all_changed:
            if reingest_file(fp, writer):
                click.echo(f"  ✓ {fp}")
                success += 1
            else:
                click.echo(f"  ✗ {fp} (skipped)")

        click.echo(f"\nUpdated {success}/{len(all_changed)} files")
        writer.flush_all()
        writer.close()

    except Exception as e:
        click.echo(f"Memgraph connection failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-o", "--output", default="graph_export.json", help="Output JSON file path")
@click.pass_context
def export(ctx, output):
    """Export the full graph as JSON for offline analysis."""
    import json
    from datetime import datetime

    config = ctx.obj["config"]

    try:
        from .ingestion.writer import GraphWriter
        writer = GraphWriter(
            uri=config.memgraph.uri,
            username=config.memgraph.username,
            password=config.memgraph.password,
        )

        nodes = []
        edges = []

        with writer.driver.session() as session:
            # Export all nodes
            result = session.run("MATCH (n) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
            for record in result:
                nodes.append({
                    "id": record["id"],
                    "labels": record["labels"],
                    "properties": dict(record["props"]),
                })

            # Export all edges
            result = session.run(
                "MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS dst, "
                "type(r) AS type, properties(r) AS props"
            )
            for record in result:
                edges.append({
                    "source": record["src"],
                    "target": record["dst"],
                    "type": record["type"],
                    "properties": dict(record["props"]),
                })

        writer.close()

        export_data = {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        }

        with open(output, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        click.echo(f"Exported {len(nodes)} nodes, {len(edges)} edges to {output}")

    except Exception as e:
        click.echo(f"Export failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def health(ctx):
    """Graph health diagnostic: full pipeline analysis without Memgraph."""
    config = ctx.obj["config"]
    report = run_health_report(config)
    click.echo(report)


@cli.command("export-dot")
@click.option("-o", "--output", default="graph.dot", help="Output DOT file path")
@click.option("--max-nodes", default=200, type=int,
              help="Maximum number of file nodes to include (default: 200)")
@click.pass_context
def export_dot(ctx, output, max_nodes):
    """Export graph as Graphviz DOT for visualization (no Memgraph needed)."""
    config = ctx.obj["config"]
    dot_content = generate_dot(config, max_nodes=max_nodes)

    with open(output, "w") as f:
        f.write(dot_content)

    # Count nodes and edges for summary
    node_count = dot_content.count("[label=")
    edge_count = dot_content.count("->")
    click.echo(f"Exported DOT graph to {output}")
    click.echo(f"  ~{node_count} nodes, ~{edge_count} edges")
    click.echo(f"  Max nodes: {max_nodes}")
    click.echo(f"  Render: dot -Tpng {output} -o graph.png")


if __name__ == "__main__":
    cli()
