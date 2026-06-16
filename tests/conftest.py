# tests/conftest.py
"""Shared fixtures for the eval suite."""
import os

import pytest

# smoke_test.py is a standalone script (not a pytest test file) that opens a
# live Memgraph connection at import time.  Exclude it from collection so that
# running `pytest tests/` on a machine without Memgraph never produces a
# collection error.
collect_ignore = ["smoke_test.py"]


@pytest.fixture(scope="session")
def engine():
    """Yield a QueryEngine connected to Memgraph, or skip the whole eval suite.

    Skips (never fails) when the driver is missing or no graph is reachable, so
    the graph-hitting tests are inert on machines without a built graph.
    """
    try:
        from mcp_server.query_engine import QueryEngine
    except Exception as exc:  # neo4j driver not installed, etc.
        pytest.skip(f"QueryEngine import failed: {exc}")

    uri = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
    eng = QueryEngine(uri)
    try:
        eng.query("RETURN 1 AS ok")  # forces a real connection
    except Exception as exc:
        eng.close()
        pytest.skip(f"no graph reachable at {uri}: {exc}")
    yield eng
    eng.close()
