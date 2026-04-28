"""FastMCP server exposing the code graph to an agent.

Agent-facing surface: 7 tools (see DESIGN.md at repo root).
  - 4 composites: explain_flow, find_impact, onboard_to, locate
  - 3 read primitives: get_code_snippet, get_file_outline, find_symbol

Operator-only tools (find_unresolved, get_graph_stats, diagnose_file) have
moved to the `code-graph` CLI — they are not exposed here.

Start with:
    python -m mcp_server.server
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from .query_engine import QueryEngine
from .telemetry import traced
from .tools import composites, search, snippets

mcp = FastMCP("bob-code-graph")

_engine: QueryEngine | None = None


def _get_engine() -> QueryEngine:
    global _engine
    if _engine is None:
        uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
        _engine = QueryEngine(uri)
    return _engine


# --- Composites (task-shaped) ---

@mcp.tool()
@traced("explain_flow")
def explain_flow(endpoint: str, escape_hatch: bool = False) -> str:
    """Explain how an HTTP endpoint works end-to-end: nginx phases, call graph,
    internal reroutes, and cross-service HTTP calls, with middleware collapsed.

    Pass escape_hatch=True to get the raw call-centric trace including middleware.
    Example: explain_flow('/api/auth/login')
    """
    return composites.explain_flow(_get_engine(), endpoint, escape_hatch)


@mcp.tool()
@traced("find_impact")
def find_impact(symbol_or_file: str, max_depth: int = 5, escape_hatch: bool = False) -> str:
    """Blast radius for a change. Accepts a file path OR a symbol name.

    Returns direct callers, transitive file-level dependents, and implicit
    couplings (ngx.ctx, ngx.shared, Redis keys, HTTP calls to other services).
    Use before modifying a function or file to understand what breaks.

    Pass escape_hatch=True to also dump raw primitive output (find_all_callers
    for symbols, find_impacted_files for paths) so you can see what the
    composite filtered or summarized.
    """
    return composites.find_impact(_get_engine(), symbol_or_file, max_depth, escape_hatch)


@mcp.tool()
@traced("onboard_to")
def onboard_to(area: str, escape_hatch: bool = False) -> str:
    """Ramp-up pack for a feature area. `area` is a path prefix, module name,
    or endpoint ('/api/...'). Returns central files, public exports, entry
    endpoints, and Redis keys touched by that area.

    Use at the start of a new task to orient yourself inside a subsystem.
    Pass escape_hatch=True to drop the centrality filter (no min import count)
    and include non-public exports.
    """
    return composites.onboard_to(_get_engine(), area, escape_hatch)


@mcp.tool()
@traced("locate")
def locate(description: str, limit: int = 10, escape_hatch: bool = False) -> str:
    """Natural-language symbol localization. Given a description of what
    you're looking for, returns the top-ranked matching symbols and files.

    Default: ranks by literal token hits reweighted by graph centrality
    (incoming edge count). Pass escape_hatch=True to skip the centrality
    rerank and see raw lexical matches — useful when the target is a leaf
    utility or entry endpoint with low in-degree.

    Use locate when you're describing behavior; use find_symbol when you know
    the exact name. Example: locate('endpoint that issues auth tokens').
    """
    return composites.locate(_get_engine(), description, limit, escape_hatch)


# --- Read primitives (kept) ---

@mcp.tool()
@traced("find_symbol")
def find_symbol(symbol_name: str, scope: str | None = None) -> str:
    """Finds where a function, class, or module is defined.

    If `scope` is provided (module name like 'resty.auth' or path substring
    like 'services/auth/'), results are filtered to that scope and public
    exports are preferred — i.e. acts as module-exports lookup.
    """
    return search.find_symbol(_get_engine(), symbol_name, scope)


@mcp.tool()
@traced("get_code_snippet")
def get_code_snippet(name: str, context_lines: int = 0) -> str:
    """Retrieves the source code of a function or class by name.
    Searches the graph for matching symbols and reads the actual source file.
    Example: get_code_snippet('parse_js_file')
    """
    return snippets.get_code_snippet(_get_engine(), name, context_lines)


@mcp.tool()
@traced("get_file_outline")
def get_file_outline(file_path: str) -> str:
    """Shows the structural outline of a file: all defined functions, classes,
    exports, and imports with line numbers.
    Example: get_file_outline('graph_builder/parsers/js_parser.py')
    """
    return snippets.get_file_outline(_get_engine(), file_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
