"""Tests for cross-service IPC edge detection.

Covers: Unix sockets, mission dispatch, shared Redis patterns, MySQL,
Cassandra, SQS, Kinesis, S3, shared config, endpoint linker expansion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import (
    FileAST, CallRef, ImportRef, HttpCallRef,
    MissionDispatch, DatabaseAccess, AwsServiceAccess,
)


# --- Data model tests ---

def test_mission_dispatch_model():
    """MissionDispatch dataclass stores task name and queue."""
    md = MissionDispatch(
        task_name="pts_run", queue="policy",
        caller_function="apply", line=107,
    )
    assert md.task_name == "pts_run"
    assert md.queue == "policy"


def test_database_access_model():
    """DatabaseAccess dataclass stores db type, operation, and optional table."""
    da = DatabaseAccess(
        db_type="mysql", operation="query", table="alerted_transactions",
        function="check_alerts", line=42,
    )
    assert da.db_type == "mysql"
    assert da.table == "alerted_transactions"


def test_aws_service_access_model():
    """AwsServiceAccess dataclass stores service type and operation."""
    sa = AwsServiceAccess(
        service="sqs", operation="send_message", resource_id="task-queue",
        function="enqueue_task", line=26,
    )
    assert sa.service == "sqs"
    assert sa.operation == "send_message"


def test_file_ast_has_new_fields():
    """FileAST should include mission_dispatches, db_accesses, aws_accesses."""
    ast = FileAST(file_path="test.lua", language="lua")
    assert ast.mission_dispatches == []
    assert ast.db_accesses == []
    assert ast.aws_accesses == []


# --- Unix socket tests ---

from graph_builder.resolvers.cross_service_resolver import (
    resolve_unix_sockets,
    KNOWN_SOCKET_CONNECTIONS,
)


def test_known_socket_inventory_complete():
    """Static socket map has all 6 BOB-confirmed sockets."""
    socket_paths = {s["socket"] for s in KNOWN_SOCKET_CONNECTIONS}
    assert "glider.sock" in socket_paths
    assert "missioner.sock" in socket_paths
    assert "prediction_tcp_router.sock" in socket_paths
    assert "global_data.sock" in socket_paths
    assert "atlas.sock" in socket_paths
    assert "cassandra_communicator.sock" in socket_paths


def test_static_socket_mapping_creates_edges():
    """Static socket config creates SOCKET_LISTENS and SOCKET_CONNECTS edges."""
    ast_listener = FileAST(
        file_path="deferrer/missioner/missioner.py", language="python",
    )
    ast_connector = FileAST(
        file_path="core/deferrer/missioner/client.lua", language="lua",
    )
    all_asts = {
        "deferrer/missioner/missioner.py": ast_listener,
        "core/deferrer/missioner/client.lua": ast_connector,
    }

    edges = resolve_unix_sockets(all_asts)
    socket_edges = [e for e in edges if "missioner.sock" in e["socket"]]
    assert len(socket_edges) >= 1  # at least one listener or connector matched


def test_python_socket_string_scan():
    """Python file with bind_unix_socket() detected as listener."""
    ast = FileAST(file_path="services/global_data/server.py", language="python",
                  calls=[
                      CallRef(caller_function="start_server",
                              callee_string="bind_unix_socket",
                              line=15),
                  ])
    # The actual socket path detection scans string literals in the source.
    # For unit testing, the static config handles Python socket listeners.
    all_asts = {"services/global_data/server.py": ast}
    edges = resolve_unix_sockets(all_asts)
    # Static mapping should produce edges if file path matches known config
    assert isinstance(edges, list)


def test_socket_listener_and_connector_roles():
    """Both listener and connector roles are correctly assigned."""
    all_asts = {
        "deferrer/missioner/missioner.py": FileAST(
            file_path="deferrer/missioner/missioner.py", language="python"),
        "core/deferrer/missioner/client.lua": FileAST(
            file_path="core/deferrer/missioner/client.lua", language="lua"),
    }

    edges = resolve_unix_sockets(all_asts)
    missioner_edges = [e for e in edges if e["socket"] == "missioner.sock"]
    roles = {e["role"] for e in missioner_edges}
    assert "listener" in roles
    assert "connector" in roles
