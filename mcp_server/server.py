"""FastMCP server exposing graph tools to BOB.

Start with:
    python -m mcp_server.server

Or register in MCP config as:
    {"command": "python", "args": ["-m", "mcp_server.server"]}
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from .query_engine import QueryEngine
from .tools import navigation, tracing, impact, search

mcp = FastMCP("bob-code-graph")

# Initialize query engine (connects on first use)
_engine: QueryEngine | None = None


def _get_engine() -> QueryEngine:
    global _engine
    if _engine is None:
        uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
        _engine = QueryEngine(uri)
    return _engine


# --- Navigation tools ---

@mcp.tool()
def get_dependencies(file_path: str) -> str:
    """Returns all files that the given file imports or depends on.
    Use when you need to understand what a file relies on before modifying it.
    """
    return navigation.get_dependencies(_get_engine(), file_path)


@mcp.tool()
def get_dependents(file_path: str) -> str:
    """Returns all files that import or depend on the given file.
    Use for impact analysis — which files will be affected by changes here.
    """
    return navigation.get_dependents(_get_engine(), file_path)


@mcp.tool()
def get_repo_overview(limit: int = 40) -> str:
    """Returns a condensed map of the most important files in the codebase,
    ranked by how many other files import them.
    Use at the start of a new task to orient yourself.
    """
    return navigation.get_repo_overview(_get_engine(), limit)


# --- Tracing tools ---

@mcp.tool()
def trace_endpoint(endpoint_path: str, max_depth: int = 6) -> str:
    """Traces the complete code path for an HTTP endpoint through all
    Lua phases, function calls, and module dependencies.
    Essential for understanding how a feature works end-to-end.
    Example: trace_endpoint('/api/auth/login')
    """
    return tracing.trace_endpoint(_get_engine(), endpoint_path, max_depth)


@mcp.tool()
def find_all_callers(function_name: str) -> str:
    """Finds every function across the codebase that calls the given function.
    Use before modifying a function signature to understand the blast radius.
    """
    return tracing.find_all_callers(_get_engine(), function_name)


# --- Impact tools ---

@mcp.tool()
def find_impacted_files(file_path: str, max_depth: int = 5) -> str:
    """Find all files that could be affected by changes to the given file.
    Traces the reverse dependency graph to show the full blast radius.
    """
    return impact.find_impacted_files(_get_engine(), file_path, max_depth)


@mcp.tool()
def get_implicit_dependencies(file_path: str) -> str:
    """Returns implicit dependencies for a Lua file: ngx.ctx fields
    read/written, ngx.shared dicts accessed, and other files that
    touch the same ctx fields or shared dicts.
    These are dependencies that don't show up in require/import statements.
    """
    return impact.get_implicit_dependencies(_get_engine(), file_path)


# --- Search tools ---

@mcp.tool()
def find_symbol(symbol_name: str) -> str:
    """Finds where a function, class, or module is defined in the codebase.
    Returns file path and line number.
    """
    return search.find_symbol(_get_engine(), symbol_name)


@mcp.tool()
def get_module_exports(module_name: str) -> str:
    """Returns the public API (exported functions) of a module.
    Example: get_module_exports('resty.auth')
    """
    return search.get_module_exports(_get_engine(), module_name)


@mcp.tool()
def get_graph_stats() -> str:
    """Returns aggregate statistics about the code graph: file counts
    per language, node/edge counts by type, and overall graph health.
    """
    return search.get_graph_stats(_get_engine())


@mcp.tool()
def find_unresolved(language: str | None = None) -> str:
    """Returns imports and calls that the graph could not resolve to
    actual files. Useful for identifying external deps vs parser gaps.
    """
    return search.find_unresolved(_get_engine(), language)


# --- Diagnostic tools ---

@mcp.tool()
def diagnose_file(file_path: str) -> str:
    """Returns diagnostic info about how well a file was captured
    in the code graph. Use when queries return unexpected results.
    """
    from graph_builder.validate.spot_check import spot_check
    return spot_check(file_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
