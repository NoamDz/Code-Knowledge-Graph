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
