"""Cross-service IPC resolver: Unix sockets, databases, AWS services, shared config.

Combines static configuration maps (from BOB investigation) with AST-based
detection to create cross-service edges. Static maps are used where dynamic
path construction makes AST scanning unreliable (e.g., Lua socket connections).
AST scanning is used where patterns are reliably detectable (e.g., Python
boto3 calls, Go mysql client methods).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from graph_builder.parsers.base import FileAST, DatabaseAccess, AwsServiceAccess


# =============================================================================
# Section 1: Unix Socket Connection Mapping
# =============================================================================

KNOWN_SOCKET_CONNECTIONS = [
    {
        "socket": "glider.sock",
        "protocol": "redis",
        "listener_lang": "external",  # Redis Glider is external
        "listener_files": [],
        "connector_files": ["lib/lua/redis/redisglider.lua"],
    },
    {
        "socket": "missioner.sock",
        "protocol": "http",
        "listener_files": ["deferrer/missioner/missioner.py"],
        "connector_files": ["core/deferrer/missioner/client.lua",
                            "deferrer/missioner/client.lua"],
    },
    {
        "socket": "prediction_tcp_router.sock",
        "protocol": "custom_json",
        "listener_files": ["core/model_prediction/server/router.go"],
        "connector_files": ["core/model_prediction/client/unix_socket_client.lua"],
    },
    {
        "socket": "global_data.sock",
        "protocol": "http",
        "listener_files": ["deferrer/global_data/global_data.py",
                           "global_data/global_data.py"],
        "connector_files": ["lib/lua/global_data_client.lua"],
    },
    {
        "socket": "atlas.sock",
        "protocol": "http",
        "listener_files": ["deferrer/atlas/atlas.py", "atlas/atlas.py"],
        "connector_files": ["lib/lua/atlas_client.lua"],
    },
    {
        "socket": "cassandra_communicator.sock",
        "protocol": "custom",
        "listener_files": ["lib/lua/cassandra/communicator.lua",
                           "cassandra/communicator.lua"],
        "connector_files": ["lib/lua/cassandra/client.lua"],
    },
]


def resolve_unix_sockets(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create Unix socket edges from the static configuration map.

    For each known socket, checks if listener/connector file paths match
    any parsed file. Uses suffix matching to handle different repo_root prefixes.

    Returns list of edge dicts:
        [{"socket", "protocol", "file", "role"}]
        role is "listener" or "connector"
    """
    edges: list[dict] = []
    # Build a suffix index for fast matching
    file_suffix_index = _build_suffix_index(all_asts)

    for sock_cfg in KNOWN_SOCKET_CONNECTIONS:
        socket_path = sock_cfg["socket"]
        protocol = sock_cfg["protocol"]

        for listener_path in sock_cfg.get("listener_files", []):
            matched = _match_file_suffix(listener_path, file_suffix_index)
            if matched:
                edges.append({
                    "socket": socket_path,
                    "protocol": protocol,
                    "file": matched,
                    "role": "listener",
                })

        for connector_path in sock_cfg["connector_files"]:
            matched = _match_file_suffix(connector_path, file_suffix_index)
            if matched:
                edges.append({
                    "socket": socket_path,
                    "protocol": protocol,
                    "file": matched,
                    "role": "connector",
                })

    return edges


def _build_suffix_index(all_asts: dict[str, FileAST]) -> dict[str, str]:
    """Build a mapping from normalized path suffixes to full file paths.

    This allows matching 'lib/lua/store.lua' against
    '/repo/src/lib/lua/store.lua'.
    """
    index: dict[str, str] = {}
    for file_path in all_asts:
        normalized = file_path.replace("\\", "/")
        # Store progressively shorter suffixes
        parts = normalized.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if suffix not in index:  # first match wins (longest path)
                index[suffix] = file_path
    return index


def _match_file_suffix(pattern: str, suffix_index: dict[str, str]) -> str | None:
    """Find a full file path matching the given suffix pattern."""
    pattern_normalized = pattern.replace("\\", "/")
    # Try exact suffix match
    if pattern_normalized in suffix_index:
        return suffix_index[pattern_normalized]
    # Try with src/ prefix stripped
    if pattern_normalized.startswith("src/"):
        stripped = pattern_normalized[4:]
        if stripped in suffix_index:
            return suffix_index[stripped]
    return None


# =============================================================================
# Section 3: Shared Redis Key Cross-Language Linking
# =============================================================================

CROSS_LANGUAGE_REDIS_PATTERNS = [
    {
        "pattern": "store:{session_id}",
        "description": "Session store data (Lua writes, Go reads for model prediction)",
        "writer_files": ["lib/lua/store.lua", "lib/lua/redis_helper.lua"],
        "reader_files": ["helpers/store.go"],
    },
    {
        "pattern": "bundles",
        "description": "Bundle configs (Ruby writes, Lua reads)",
        "writer_files": ["generator/clients/redis.rb"],
        "reader_files": ["lib/lua/bundles.lua"],
    },
    {
        "pattern": "bundle:{business}:{app}",
        "description": "Per-app bundle configs (Ruby writes, Lua reads)",
        "writer_files": ["generator/clients/redis.rb"],
        "reader_files": ["lib/lua/bundles.lua"],
    },
    {
        "pattern": "model_prediction:{session_id}",
        "description": "Model prediction results (Go writes, Lua reads)",
        "writer_files": ["tasks/model_prediction.go"],
        "reader_files": ["ato/assessors/model_prediction/init.lua"],
    },
    {
        "pattern": "model_prediction_tasks:{session_id}",
        "description": "Model prediction task queue (Lua writes, Go reads)",
        "writer_files": ["core/model_prediction/client/unix_socket_client.lua"],
        "reader_files": ["core/model_prediction/server/router.go"],
    },
]


def resolve_shared_redis_patterns(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create cross-language Redis pattern edges from static config.

    Returns list of edge dicts:
        [{"pattern", "file", "access_type"}]
        access_type is "write" or "read"
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for pattern_cfg in CROSS_LANGUAGE_REDIS_PATTERNS:
        pattern = pattern_cfg["pattern"]

        for writer_path in pattern_cfg["writer_files"]:
            matched = _match_file_suffix(writer_path, suffix_index)
            if matched:
                edges.append({
                    "pattern": pattern,
                    "file": matched,
                    "access_type": "write",
                })

        for reader_path in pattern_cfg["reader_files"]:
            matched = _match_file_suffix(reader_path, suffix_index)
            if matched:
                edges.append({
                    "pattern": pattern,
                    "file": matched,
                    "access_type": "read",
                })

    return edges


# =============================================================================
# Section 4 & 5: MySQL and Cassandra Detection
# =============================================================================

# Lua MySQL: modules whose methods indicate MySQL access
_LUA_MYSQL_MODULES = {
    "lib.lua.mysql",
    "common.base.lua.mysql",
}

_LUA_MYSQL_METHODS = {"query", "execute", "fetch", "prepare"}

# Lua Cassandra modules
_LUA_CASSANDRA_MODULES = {
    "lib.lua.cassandra.client",
    "cassandra.client",
}

_LUA_CASSANDRA_METHODS = {"execute_statement", "prepare_statement", "batch_execute"}

# Python MySQL indicators
_PYTHON_MYSQL_IMPORTS = {"mysql.connector", "MySQLdb", "pymysql"}
_PYTHON_MYSQL_CALL_PATTERNS = {"cursor.execute", "cursor.executemany", "cursor.fetchone",
                                "cursor.fetchall", "cursor.fetchmany"}

# Ruby MySQL indicators
_RUBY_MYSQL_IMPORTS = {"sequel"}
_RUBY_MYSQL_CALL_PATTERNS = {"Sequel.connect", "@db.fetch", "db.fetch", "db.run",
                              "db.execute", "dataset.insert", "dataset.update"}

# Go MySQL indicators (similar to Go Redis pattern)
_GO_MYSQL_INDICATORS = {"mysqlClient", "MysqlClient", "db.MysqlClient", "mysql"}
_GO_MYSQL_METHODS = {"Query", "Execute", "Prepare", "QueryRow", "Exec"}

# SQL table name extraction (best-effort)
_TABLE_REGEX = re.compile(
    r'\b(?:FROM|INTO|UPDATE|JOIN)\s+[`"]?(\w+)[`"]?',
    re.IGNORECASE,
)


def _extract_table_name(sql_hint: str) -> str | None:
    """Best-effort extraction of table name from SQL fragment."""
    match = _TABLE_REGEX.search(sql_hint)
    return match.group(1) if match else None


def resolve_database_accesses(all_asts: dict[str, FileAST]) -> None:
    """Scan ASTs for MySQL and Cassandra access patterns.

    Populates ast.db_accesses with DatabaseAccess entries.
    """
    for file_path, ast in all_asts.items():
        if ast.language == "lua":
            _detect_lua_mysql(ast)
            _detect_lua_cassandra(ast)
        elif ast.language == "python":
            _detect_python_mysql(ast)
        elif ast.language == "ruby":
            _detect_ruby_mysql(ast)
        elif ast.language == "go":
            _detect_go_mysql(ast)


def _detect_lua_mysql(ast: FileAST) -> None:
    """Detect MySQL access in Lua files via binding to mysql modules."""
    binding_to_module: dict[str, str] = {}
    for imp in ast.imports:
        if imp.local_binding and not imp.is_dynamic:
            binding_to_module[imp.local_binding] = imp.module_string

    mysql_bindings: set[str] = set()
    for binding, mod_str in binding_to_module.items():
        if mod_str in _LUA_MYSQL_MODULES:
            mysql_bindings.add(binding)

    for call in ast.calls:
        callee = call.callee_string
        for sep in (":", "."):
            if sep not in callee:
                continue
            parts = callee.split(sep, 1)
            receiver, method = parts[0], parts[1]

            is_mysql = (
                receiver in mysql_bindings
                or call.resolved_module in _LUA_MYSQL_MODULES
                or receiver.lower() in ("db", "mysql", "mysql_client")
            )
            if is_mysql and method.lower() in _LUA_MYSQL_METHODS:
                ast.db_accesses.append(DatabaseAccess(
                    db_type="mysql", operation=method,
                    table=None,  # table extraction needs SQL string -- not in CallRef
                    function=call.caller_function, line=call.line,
                ))
                break


def _detect_lua_cassandra(ast: FileAST) -> None:
    """Detect Cassandra access in Lua files."""
    binding_to_module: dict[str, str] = {}
    for imp in ast.imports:
        if imp.local_binding and not imp.is_dynamic:
            binding_to_module[imp.local_binding] = imp.module_string

    cassandra_bindings: set[str] = set()
    for binding, mod_str in binding_to_module.items():
        if mod_str in _LUA_CASSANDRA_MODULES:
            cassandra_bindings.add(binding)

    for call in ast.calls:
        callee = call.callee_string
        for sep in (":", "."):
            if sep not in callee:
                continue
            parts = callee.split(sep, 1)
            receiver, method = parts[0], parts[1]

            is_cassandra = (
                receiver in cassandra_bindings
                or call.resolved_module in _LUA_CASSANDRA_MODULES
                or receiver.lower() in ("cassandradb", "cassandra_client", "cass")
            )
            if is_cassandra and method in _LUA_CASSANDRA_METHODS:
                ast.db_accesses.append(DatabaseAccess(
                    db_type="cassandra", operation=method,
                    function=call.caller_function, line=call.line,
                ))
                break


def _detect_python_mysql(ast: FileAST) -> None:
    """Detect MySQL access in Python files via mysql.connector imports."""
    has_mysql_import = any(
        imp.module_string in _PYTHON_MYSQL_IMPORTS
        or imp.module_string.startswith("mysql.")
        for imp in ast.imports
    )
    if not has_mysql_import:
        return

    for call in ast.calls:
        callee = call.callee_string
        if any(pattern in callee for pattern in _PYTHON_MYSQL_CALL_PATTERNS):
            ast.db_accesses.append(DatabaseAccess(
                db_type="mysql", operation=callee.split(".")[-1],
                function=call.caller_function, line=call.line,
            ))


def _detect_ruby_mysql(ast: FileAST) -> None:
    """Detect MySQL access in Ruby files via sequel gem."""
    has_sequel = any(
        imp.module_string in _RUBY_MYSQL_IMPORTS
        or "sequel" in imp.module_string.lower()
        for imp in ast.imports
    )
    if not has_sequel:
        return

    for call in ast.calls:
        callee = call.callee_string
        if any(pattern in callee for pattern in _RUBY_MYSQL_CALL_PATTERNS):
            ast.db_accesses.append(DatabaseAccess(
                db_type="mysql", operation=callee.split(".")[-1],
                function=call.caller_function, line=call.line,
            ))


def _detect_go_mysql(ast: FileAST) -> None:
    """Detect MySQL access in Go files via mysqlClient patterns."""
    for call in ast.calls:
        callee = call.callee_string
        parts = callee.rsplit(".", 1)
        if len(parts) != 2:
            continue
        receiver, method = parts
        is_mysql = any(ind in receiver for ind in _GO_MYSQL_INDICATORS)
        if not is_mysql:
            receiver_tail = receiver.rsplit(".", 1)[-1]
            is_mysql = receiver_tail.lower() in {"mysqlclient", "mysql", "dbclient"}
        if is_mysql and method in _GO_MYSQL_METHODS:
            ast.db_accesses.append(DatabaseAccess(
                db_type="mysql", operation=method,
                function=call.caller_function, line=call.line,
            ))


# =============================================================================
# Section 6, 7, 8: SQS, Kinesis, S3 Detection
# =============================================================================

# Python SQS patterns
_SQS_PRODUCE_METHODS = {"send_message", "send_message_batch"}
_SQS_CONSUME_METHODS = {"receive_message", "delete_message", "delete_message_batch"}
_SQS_ALL_METHODS = _SQS_PRODUCE_METHODS | _SQS_CONSUME_METHODS
_SQS_INDICATORS = {"sqs_client", "sqs", "queue_client"}

# Go/Ruby Kinesis patterns
_KINESIS_METHODS = {"UploadEvent", "PutRecord", "put_record", "put_record_batch"}
_KINESIS_INDICATORS = {"kinesis", "Kinesis", "firehose", "Firehose"}

# Ruby S3 patterns
_S3_METHODS = {"put_object", "get_object", "upload_file", "download_file",
               "delete_object", "head_object"}
_S3_INDICATORS = {"s3", "S3", "s3_client", "bucket"}


def resolve_aws_service_accesses(all_asts: dict[str, FileAST]) -> None:
    """Scan ASTs for SQS, Kinesis, and S3 access patterns.

    Populates ast.aws_accesses with AwsServiceAccess entries.
    """
    for file_path, ast in all_asts.items():
        if ast.language == "python":
            _detect_python_sqs(ast)
        elif ast.language == "go":
            _detect_go_kinesis(ast)
        elif ast.language == "ruby":
            _detect_ruby_kinesis(ast)
            _detect_ruby_s3(ast)


def _detect_python_sqs(ast: FileAST) -> None:
    """Detect SQS operations in Python files (boto3-based)."""
    has_boto = any(
        "boto3" in imp.module_string or "sqs" in imp.module_string.lower()
        for imp in ast.imports
    )
    if not has_boto:
        return

    for call in ast.calls:
        callee = call.callee_string
        # Match: sqs_client.send_message, self.sqs_client.send_message, etc.
        parts = callee.rsplit(".", 1)
        if len(parts) != 2:
            continue
        receiver, method = parts
        receiver_tail = receiver.rsplit(".", 1)[-1] if "." in receiver else receiver
        is_sqs = receiver_tail.lower() in _SQS_INDICATORS
        if is_sqs and method in _SQS_ALL_METHODS:
            ast.aws_accesses.append(AwsServiceAccess(
                service="sqs", operation=method,
                resource_id=None,  # queue URL is runtime
                function=call.caller_function, line=call.line,
            ))


def _detect_go_kinesis(ast: FileAST) -> None:
    """Detect Kinesis operations in Go files."""
    for call in ast.calls:
        callee = call.callee_string
        parts = callee.rsplit(".", 1)
        if len(parts) != 2:
            continue
        receiver, method = parts
        is_kinesis = any(ind in receiver for ind in _KINESIS_INDICATORS)
        if is_kinesis and method in _KINESIS_METHODS:
            ast.aws_accesses.append(AwsServiceAccess(
                service="kinesis", operation=method,
                function=call.caller_function, line=call.line,
            ))


def _detect_ruby_kinesis(ast: FileAST) -> None:
    """Detect Kinesis Firehose operations in Ruby files."""
    has_kinesis = any(
        "kinesis" in imp.module_string.lower()
        or "firehose" in imp.module_string.lower()
        or "Aws::Firehose" in imp.module_string
        for imp in ast.imports
    )
    # Also check class definitions for Firehose client
    has_firehose_class = any(
        "firehose" in cls.name.lower() or "kinesis" in cls.name.lower()
        for cls in ast.classes
    )
    if not has_kinesis and not has_firehose_class:
        # Broader scan: check all calls for kinesis method patterns
        pass

    for call in ast.calls:
        callee = call.callee_string
        parts = callee.rsplit(".", 1)
        if len(parts) != 2:
            continue
        receiver, method = parts
        is_kinesis = any(ind.lower() in receiver.lower() for ind in _KINESIS_INDICATORS)
        if is_kinesis and method in _KINESIS_METHODS:
            ast.aws_accesses.append(AwsServiceAccess(
                service="kinesis", operation=method,
                function=call.caller_function, line=call.line,
            ))


def _detect_ruby_s3(ast: FileAST) -> None:
    """Detect S3 operations in Ruby files."""
    has_s3 = any(
        "s3" in imp.module_string.lower()
        or "Aws::S3" in imp.module_string
        for imp in ast.imports
    )
    has_s3_class = any(
        "s3" in cls.name.lower() for cls in ast.classes
    )
    if not has_s3 and not has_s3_class:
        return

    for call in ast.calls:
        callee = call.callee_string
        parts = callee.rsplit(".", 1)
        if len(parts) != 2:
            continue
        receiver, method = parts
        # When we have S3 imports/classes, any call using an S3 method is likely S3
        is_s3 = any(ind.lower() in receiver.lower() for ind in _S3_INDICATORS)
        if method in _S3_METHODS and (is_s3 or has_s3 or has_s3_class):
            ast.aws_accesses.append(AwsServiceAccess(
                service="s3", operation=method,
                function=call.caller_function, line=call.line,
            ))


# =============================================================================
# Section 9: Shared Configuration File Edges
# =============================================================================

SHARED_CONFIG_FILES = [
    {
        "config": "config.json",
        "description": "Main app configuration -- read by all languages",
        "readers": {
            "lua": ["lib/lua/config.lua"],
            "python": ["deferrer/missioner/lib/config.py",
                       "deferrer/aggregator/aggregator/lib/config.py",
                       "deferrer/poller/poller/lib/config.py",
                       "deferrer/global_data/lib/config.py",
                       "deferrer/atlas/lib/config.py"],
            "go": ["core/model_prediction/server/config/init.go"],
            "ruby": ["core/utils/ruby/utils.rb",
                     "core/generator/lib/config.rb"],
        },
    },
    {
        "config": "model_prediction_service.json",
        "description": "Model prediction service config -- Lua client and Go server",
        "readers": {
            "lua": ["core/model_prediction/client/unix_socket_client.lua"],
            "go": ["core/model_prediction/server/config/init.go"],
        },
    },
    {
        "config": "features.json",
        "description": "Feature flags -- read by Lua and Ruby",
        "readers": {
            "lua": ["lib/lua/features.lua"],
            "ruby": ["core/generator/lib/features.rb"],
        },
    },
]


def resolve_shared_configs(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create shared config file edges from static config.

    Returns list of edge dicts:
        [{"config", "file"}]
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for config_entry in SHARED_CONFIG_FILES:
        config_name = config_entry["config"]
        for lang, file_list in config_entry["readers"].items():
            for file_pattern in file_list:
                matched = _match_file_suffix(file_pattern, suffix_index)
                if matched:
                    edges.append({
                        "config": config_name,
                        "file": matched,
                    })

    return edges
