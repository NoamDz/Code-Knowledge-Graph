"""`build` rebuilds the graph from scratch.

Every write in the ingestion layer is a `MERGE`, which creates but never
deletes. Without an explicit wipe the graph converges to the union of every
build ever run against it: a deleted function keeps its `Function` node, a
removed `bind` keeps the `TRIGGERS` edge pointing at it, and a deleted file
keeps everything. So `build` clears the graph before it ingests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from graph_builder.ingestion.writer import GraphWriter
from graph_builder.main import cli


def _mock_writer() -> GraphWriter:
    """A GraphWriter whose driver and _run are mocked (no Memgraph needed)."""
    with patch("graph_builder.ingestion.writer.GraphDatabase"):
        writer = GraphWriter(uri="bolt://fake:7687")
    writer._run = MagicMock()
    return writer


def test_clear_graph_detach_deletes_every_node():
    writer = _mock_writer()

    writer.clear_graph()

    query = writer._run.call_args[0][0]
    assert "MATCH (n)" in query
    assert "DETACH DELETE n" in query


def test_build_clears_the_graph_before_ingesting_anything(tmp_path):
    """The wipe must precede every write, not interleave with them.

    Clearing after a partial ingest would delete the nodes just written.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.lua").write_text("local M = {}\nreturn M\n")
    config = tmp_path / "config.yml"
    config.write_text(f"repo_root: {tmp_path.as_posix()}\n")

    writer = MagicMock()
    with patch("graph_builder.ingestion.writer.GraphWriter", return_value=writer), \
         patch("graph_builder.ingestion.schema.create_indexes"):
        result = CliRunner().invoke(cli, ["-c", str(config), "build"])

    assert result.exit_code == 0, result.output

    called = [name for name, _, _ in writer.mock_calls]
    assert "clear_graph" in called, f"build never wiped the graph; calls={called}"
    assert "ingest_file_ast" in called, f"build ingested nothing; calls={called}"
    assert called.index("clear_graph") < called.index("ingest_file_ast")


@pytest.fixture
def live_writer():
    """A GraphWriter against a real Memgraph, or skip.

    Mirrors tests/conftest.py: inert on machines without a database rather
    than failing.
    """
    uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
    try:
        writer = GraphWriter(uri=uri)
        writer._run("RETURN 1")
    except Exception as exc:
        pytest.skip(f"no Memgraph reachable at {uri}: {exc}")
    yield writer
    writer.close()


def test_clear_graph_removes_stale_edges_against_live_memgraph(live_writer):
    """The bug this whole change exists to fix, end to end."""
    live_writer._run("""
        MERGE (a:File {path: '/wipe-test/a.lua'})
        MERGE (b:File {path: '/wipe-test/b.lua'})
        MERGE (a)-[:TRIGGERS {name: 'stale_event', line: 1}]->(b)
    """)

    live_writer.clear_graph()

    with live_writer.driver.session() as session:
        remaining = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
        edges = session.run("MATCH ()-[r]->() RETURN count(r) AS r").single()["r"]
    assert remaining == 0
    assert edges == 0
