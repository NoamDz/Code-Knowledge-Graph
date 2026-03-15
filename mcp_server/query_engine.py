"""Cypher query runner and result formatter for the MCP server."""

from __future__ import annotations

import os
from typing import Any

from neo4j import GraphDatabase


class QueryEngine:
    """Runs Cypher queries against Memgraph and formats results."""

    def __init__(self, uri: str | None = None):
        self.uri = uri or os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
        self.driver = GraphDatabase.driver(self.uri, auth=None)

    def query(self, cypher: str, **params) -> list[dict[str, Any]]:
        """Execute a Cypher query and return list of result dicts."""
        with self.driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(record) for record in result]

    def close(self):
        self.driver.close()


def format_file_list(title: str, results: list[dict]) -> str:
    """Format a list of files as human-readable text."""
    if not results:
        return f"{title}: (none found)"
    lines = [f"{title} ({len(results)} files):"]
    for r in results:
        path = r.get("path", "?")
        lang = r.get("language", "")
        extra = f" [{lang}]" if lang else ""
        lines.append(f"  {path}{extra}")
    return "\n".join(lines)


def format_call_chain(entry: str, results: list[dict]) -> str:
    """Format a call chain trace as human-readable text."""
    if not results:
        return f"No call chain found from {entry}"
    lines = [f"Call chain from {entry}:"]
    for r in results:
        phase = r.get("phase", "")
        entry_file = r.get("entry_file", "")
        chain = r.get("call_chain", [])
        lines.append(f"  [{phase}] {entry_file}")
        if chain:
            lines.append(f"    → " + " → ".join(chain))
    return "\n".join(lines)


def format_symbol_results(name: str, results: list[dict]) -> str:
    """Format symbol search results."""
    if not results:
        return f"Symbol '{name}' not found"
    lines = [f"Symbol '{name}' found in {len(results)} locations:"]
    for r in results:
        stype = r.get("type", "?")
        sname = r.get("name", "?")
        sfile = r.get("file", "?")
        sline = r.get("line", "?")
        lines.append(f"  [{stype}] {sname} in {sfile}:{sline}")
    return "\n".join(lines)
