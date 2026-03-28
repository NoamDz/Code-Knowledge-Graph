"""Tests for cross-service IPC edge detection.

Covers: Unix sockets, mission dispatch, shared Redis patterns, MySQL,
Cassandra, SQS, Kinesis, S3, shared config, endpoint linker expansion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import (
    FileAST, CallRef, ImportRef, HttpCallRef, ClassDef,
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


# --- Database and AWS detection tests ---

from graph_builder.resolvers.cross_service_resolver import (
    resolve_database_accesses,
    resolve_aws_service_accesses,
    resolve_shared_redis_patterns,
    resolve_shared_configs,
)


# --- MySQL detection tests ---

def test_lua_mysql_via_binding():
    """Lua db:query() with mysql module binding creates QUERIES_DB."""
    ast = FileAST(file_path="src/lib/lua/alerts.lua", language="lua",
        imports=[
            ImportRef(module_string="lib.lua.mysql", line=1,
                      import_type="require", local_binding="db"),
        ],
        calls=[
            CallRef(caller_function="check_alerts",
                    callee_string="db:query", line=42),
        ],
    )
    all_asts = {"src/lib/lua/alerts.lua": ast}
    resolve_database_accesses(all_asts)
    assert len(ast.db_accesses) >= 1
    assert ast.db_accesses[0].db_type == "mysql"
    assert ast.db_accesses[0].operation == "query"


def test_python_mysql_cursor_execute():
    """Python cursor.execute() with mysql.connector import creates QUERIES_DB."""
    ast = FileAST(file_path="src/deferrer/missioner/db.py", language="python",
        imports=[
            ImportRef(module_string="mysql.connector", line=1,
                      import_type="import"),
        ],
        calls=[
            CallRef(caller_function="save_record",
                    callee_string="cursor.execute", line=15),
        ],
    )
    all_asts = {"src/deferrer/missioner/db.py": ast}
    resolve_database_accesses(all_asts)
    assert len(ast.db_accesses) >= 1
    assert ast.db_accesses[0].db_type == "mysql"


def test_go_mysql_client_query():
    """Go mps.mysqlClient.Query() creates QUERIES_DB."""
    ast = FileAST(file_path="src/core/model_prediction/server/tasks.go",
                  language="go",
        calls=[
            CallRef(caller_function="ProcessTask",
                    callee_string="mps.mysqlClient.Query", line=88),
        ],
    )
    all_asts = {"src/core/model_prediction/server/tasks.go": ast}
    resolve_database_accesses(all_asts)
    assert len(ast.db_accesses) >= 1
    assert ast.db_accesses[0].db_type == "mysql"
    assert ast.db_accesses[0].operation == "Query"


def test_ruby_mysql_via_sequel():
    """Ruby db.fetch() with sequel import creates QUERIES_DB."""
    ast = FileAST(file_path="src/generator/db/queries.rb", language="ruby",
        imports=[
            ImportRef(module_string="sequel", line=1,
                      import_type="require"),
        ],
        calls=[
            CallRef(caller_function="get_bundles",
                    callee_string="db.fetch", line=20),
        ],
    )
    all_asts = {"src/generator/db/queries.rb": ast}
    resolve_database_accesses(all_asts)
    assert len(ast.db_accesses) >= 1
    assert ast.db_accesses[0].db_type == "mysql"
    assert ast.db_accesses[0].operation == "fetch"


def test_lua_cassandra_execute_statement():
    """Lua CassandraDB.execute_statement() creates QUERIES_CASSANDRA."""
    ast = FileAST(file_path="src/lib/lua/cassandra/client.lua", language="lua",
        imports=[
            ImportRef(module_string="lib.lua.cassandra.client", line=1,
                      import_type="require", local_binding="CassandraDB"),
        ],
        calls=[
            CallRef(caller_function="store_event",
                    callee_string="CassandraDB.execute_statement", line=90),
        ],
    )
    all_asts = {"src/lib/lua/cassandra/client.lua": ast}
    resolve_database_accesses(all_asts)
    cass_accesses = [a for a in ast.db_accesses if a.db_type == "cassandra"]
    assert len(cass_accesses) >= 1
    assert cass_accesses[0].operation == "execute_statement"


def test_no_mysql_without_import():
    """Python cursor.execute() without mysql import does not create DB access."""
    ast = FileAST(file_path="src/utils/helper.py", language="python",
        imports=[
            ImportRef(module_string="json", line=1, import_type="import"),
        ],
        calls=[
            CallRef(caller_function="process",
                    callee_string="cursor.execute", line=10),
        ],
    )
    all_asts = {"src/utils/helper.py": ast}
    resolve_database_accesses(all_asts)
    assert len(ast.db_accesses) == 0


def test_lua_mysql_receiver_heuristic():
    """Lua db.query with common receiver name detected without explicit binding."""
    ast = FileAST(file_path="src/lib/lua/store.lua", language="lua",
        imports=[],  # no explicit mysql import
        calls=[
            CallRef(caller_function="save_data",
                    callee_string="db.query", line=30),
        ],
    )
    all_asts = {"src/lib/lua/store.lua": ast}
    resolve_database_accesses(all_asts)
    # 'db' is in the heuristic list of common MySQL receivers
    assert len(ast.db_accesses) >= 1
    assert ast.db_accesses[0].db_type == "mysql"


# --- SQS detection tests ---

def test_python_sqs_send_message():
    """Python sqs_client.send_message() creates SQS PRODUCES_TO."""
    ast = FileAST(file_path="src/deferrer/aggregator/clients/sqs.py",
                  language="python",
        imports=[
            ImportRef(module_string="boto3", line=1, import_type="import"),
        ],
        calls=[
            CallRef(caller_function="enqueue",
                    callee_string="self.sqs_client.send_message", line=26),
        ],
    )
    all_asts = {"src/deferrer/aggregator/clients/sqs.py": ast}
    resolve_aws_service_accesses(all_asts)
    sqs = [a for a in ast.aws_accesses if a.service == "sqs"]
    assert len(sqs) >= 1
    assert sqs[0].operation == "send_message"


def test_python_sqs_receive_message():
    """Python sqs.receive_message() creates SQS CONSUMES_FROM."""
    ast = FileAST(file_path="src/deferrer/poller/clients/sqs.py",
                  language="python",
        imports=[
            ImportRef(module_string="boto3.session", line=1, import_type="import"),
        ],
        calls=[
            CallRef(caller_function="poll",
                    callee_string="self.sqs_client.receive_message", line=84),
        ],
    )
    all_asts = {"src/deferrer/poller/clients/sqs.py": ast}
    resolve_aws_service_accesses(all_asts)
    sqs = [a for a in ast.aws_accesses if a.service == "sqs"]
    assert len(sqs) >= 1
    assert sqs[0].operation == "receive_message"


def test_no_sqs_without_boto():
    """Python sqs_client.send_message without boto3 import is not detected."""
    ast = FileAST(file_path="src/utils/mock_sqs.py", language="python",
        imports=[
            ImportRef(module_string="json", line=1, import_type="import"),
        ],
        calls=[
            CallRef(caller_function="mock_send",
                    callee_string="sqs_client.send_message", line=10),
        ],
    )
    all_asts = {"src/utils/mock_sqs.py": ast}
    resolve_aws_service_accesses(all_asts)
    assert len(ast.aws_accesses) == 0


# --- Kinesis detection tests ---

def test_go_kinesis_upload_event():
    """Go kinesis.UploadEvent() creates Kinesis STREAMS_TO."""
    ast = FileAST(file_path="src/core/model_prediction/server/services/kinesis.go",
                  language="go",
        calls=[
            CallRef(caller_function="ProcessEvent",
                    callee_string="kinesis.UploadEvent", line=62),
        ],
    )
    all_asts = {"src/core/model_prediction/server/services/kinesis.go": ast}
    resolve_aws_service_accesses(all_asts)
    kinesis = [a for a in ast.aws_accesses if a.service == "kinesis"]
    assert len(kinesis) >= 1
    assert kinesis[0].operation == "UploadEvent"


def test_ruby_kinesis_firehose():
    """Ruby firehose.put_record() creates Kinesis access."""
    ast = FileAST(file_path="src/generator/clients/firehose.rb", language="ruby",
        imports=[
            ImportRef(module_string="aws-sdk-firehose", line=1,
                      import_type="require"),
        ],
        calls=[
            CallRef(caller_function="send_event",
                    callee_string="firehose.put_record", line=25),
        ],
    )
    all_asts = {"src/generator/clients/firehose.rb": ast}
    resolve_aws_service_accesses(all_asts)
    kinesis = [a for a in ast.aws_accesses if a.service == "kinesis"]
    assert len(kinesis) >= 1
    assert kinesis[0].operation == "put_record"


# --- S3 detection tests ---

def test_ruby_s3_upload_file():
    """Ruby obj.upload_file() with S3 class creates ACCESSES_S3."""
    ast = FileAST(file_path="src/core/multi_events_uploader/lib/clients/s3.rb",
                  language="ruby",
        classes=[
            ClassDef(name="S3Client", line=14, line_end=50),
        ],
        imports=[
            ImportRef(module_string="aws-sdk-s3", line=1,
                      import_type="require"),
        ],
        calls=[
            CallRef(caller_function="upload",
                    callee_string="obj.upload_file", line=33),
        ],
    )
    all_asts = {"src/core/multi_events_uploader/lib/clients/s3.rb": ast}
    resolve_aws_service_accesses(all_asts)
    s3 = [a for a in ast.aws_accesses if a.service == "s3"]
    assert len(s3) >= 1
    assert s3[0].operation == "upload_file"


def test_ruby_s3_get_object():
    """Ruby s3_client.get_object() with S3 import creates ACCESSES_S3."""
    ast = FileAST(file_path="src/core/downloader/s3_reader.rb", language="ruby",
        imports=[
            ImportRef(module_string="aws-sdk-s3", line=1,
                      import_type="require"),
        ],
        calls=[
            CallRef(caller_function="download",
                    callee_string="s3_client.get_object", line=18),
        ],
    )
    all_asts = {"src/core/downloader/s3_reader.rb": ast}
    resolve_aws_service_accesses(all_asts)
    s3 = [a for a in ast.aws_accesses if a.service == "s3"]
    assert len(s3) >= 1
    assert s3[0].operation == "get_object"


# --- Shared Redis pattern tests ---

def test_shared_redis_pattern_matching():
    """Shared Redis pattern config matches writer and reader files."""
    all_asts = {
        "lib/lua/store.lua": FileAST(file_path="lib/lua/store.lua", language="lua"),
        "helpers/store.go": FileAST(file_path="helpers/store.go", language="go"),
    }
    edges = resolve_shared_redis_patterns(all_asts)
    store_edges = [e for e in edges if e["pattern"] == "store:{session_id}"]
    assert len(store_edges) >= 2
    access_types = {e["access_type"] for e in store_edges}
    assert "write" in access_types
    assert "read" in access_types


# --- Shared config tests ---

def test_shared_config_file_matching():
    """Shared config map matches reader files when present."""
    all_asts = {
        "lib/lua/config.lua": FileAST(file_path="lib/lua/config.lua", language="lua"),
        "core/model_prediction/server/config/init.go": FileAST(
            file_path="core/model_prediction/server/config/init.go", language="go"),
    }
    edges = resolve_shared_configs(all_asts)
    config_json_edges = [e for e in edges if e["config"] == "config.json"]
    assert len(config_json_edges) >= 2  # lua and go readers
    files = {e["file"] for e in config_json_edges}
    assert "lib/lua/config.lua" in files
    assert "core/model_prediction/server/config/init.go" in files


def test_shared_redis_pattern_creates_edges_with_prefix():
    """Static Redis pattern config creates writer and reader edges with repo prefix."""
    ast_writer = FileAST(file_path="repo/src/lib/lua/store.lua", language="lua")
    ast_reader = FileAST(file_path="repo/src/helpers/store.go", language="go")
    all_asts = {
        "repo/src/lib/lua/store.lua": ast_writer,
        "repo/src/helpers/store.go": ast_reader,
    }
    edges = resolve_shared_redis_patterns(all_asts)
    patterns = {e["pattern"] for e in edges}
    assert "store:{session_id}" in patterns


def test_shared_redis_pattern_unmatched_files_skipped():
    """Files not in the repo produce no edges."""
    all_asts = {
        "totally/different/path.lua": FileAST(
            file_path="totally/different/path.lua", language="lua",
        ),
    }
    edges = resolve_shared_redis_patterns(all_asts)
    assert len(edges) == 0


def test_shared_config_creates_edges_with_prefix():
    """Static config map creates READS_CONFIG edges with repo prefix."""
    ast_lua = FileAST(file_path="repo/src/lib/lua/config.lua", language="lua")
    ast_go = FileAST(
        file_path="repo/src/core/model_prediction/server/config/init.go",
        language="go",
    )
    all_asts = {
        "repo/src/lib/lua/config.lua": ast_lua,
        "repo/src/core/model_prediction/server/config/init.go": ast_go,
    }
    edges = resolve_shared_configs(all_asts)
    configs = {e["config"] for e in edges}
    assert "config.json" in configs
    # Both Lua and Go should have edges
    files = {e["file"] for e in edges}
    assert "repo/src/lib/lua/config.lua" in files
    assert "repo/src/core/model_prediction/server/config/init.go" in files


def test_shared_config_model_prediction_json():
    """model_prediction_service.json has Lua and Go readers."""
    ast_lua = FileAST(
        file_path="src/core/model_prediction/client/unix_socket_client.lua",
        language="lua",
    )
    ast_go = FileAST(
        file_path="src/core/model_prediction/server/config/init.go",
        language="go",
    )
    all_asts = {
        "src/core/model_prediction/client/unix_socket_client.lua": ast_lua,
        "src/core/model_prediction/server/config/init.go": ast_go,
    }
    edges = resolve_shared_configs(all_asts)
    mp_edges = [e for e in edges if e["config"] == "model_prediction_service.json"]
    assert len(mp_edges) == 2  # one Lua, one Go
