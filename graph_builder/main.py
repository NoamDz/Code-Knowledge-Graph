"""CLI entry point for the code knowledge graph.

Commands:
    code-graph build           Full graph build
    code-graph update          Incremental update (changed files only)
    code-graph validate        Run validation / coverage report
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
from .parsers.nginx_parser import parse_nginx_conf, parse_nginx_conf_recursive
from .parsers.base import FileAST
from .resolvers.lua_resolver import LuaResolver
from .resolvers.call_resolver import CallResolver
from .validate.spot_check import spot_check
from .validate.coverage_report import run_coverage_report


PARSERS = {
    "lua": parse_lua_file,
    "python": parse_python_file,
    "ruby": parse_ruby_file,
    "javascript": parse_js_file,
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
    lua_resolver = resolvers.get("lua")
    resolved_imports: dict[str, dict[str, str | None]] = {}

    python_resolver = resolvers.get("python")

    for file_path, ast in all_asts.items():
        file_resolved = {}
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

    # Step 4: Run cross-file call resolution
    click.echo("Resolving cross-file calls...")
    call_resolver = CallResolver(all_asts, resolvers)
    call_resolver.resolve_all()
    call_stats = call_resolver.stats()
    click.echo(f"  Calls: {call_stats['total_calls']} total, "
               f"{call_stats['already_resolved'] + call_stats['newly_resolved']} resolved "
               f"({call_stats['resolution_rate']:.1f}%)")

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

        # Ingest nginx endpoints
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
            click.echo(f"  Ingested {len(nginx_config.locations)} nginx locations")

        # Ingest all files
        for file_path, ast in all_asts.items():
            writer.ingest_file_ast(ast, resolved_imports.get(file_path, {}))

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
    report = run_coverage_report(config.repo_root, config.nginx_conf)
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
        writer.close()

    except Exception as e:
        click.echo(f"Memgraph connection failed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
