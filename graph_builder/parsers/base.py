"""Base data models for parsed code entities.

These dataclasses represent the structured output from all language parsers.
The key improvements over the original plan:
  - ImportRef has local_binding field (for require-to-variable tracking)
  - ContextAccess and SharedDictAccess for ngx.ctx/ngx.shared coupling
  - ModuleInfo captures the detected module pattern type
  - CallRef tracks whether the call was inside pcall/xpcall
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModulePatternType(Enum):
    """How the file exports its module table."""
    UNDERSCORE_M = "_M"           # local _M = {} ... return _M
    UPPERCASE_M = "M"             # local M = {} ... return M
    LOWERCASE_M = "m"             # local m = {} ... return m
    NAMED_TABLE = "named"         # local auth = {} ... return auth
    DIRECT_RETURN = "direct"      # return { foo = foo, bar = bar }
    METATABLE_CLASS = "class"     # setmetatable({}, Class) pattern
    SIDE_EFFECT = "side_effect"   # no return (scripts, init code)
    UNKNOWN = "unknown"           # could not determine
    OPAQUE_FACTORY = "opaque_factory"
    REEXPORT = "reexport"


@dataclass
class FunctionDef:
    """A function or method definition."""
    name: str
    line: int
    line_end: int
    visibility: str = "local"     # "public", "private", "local"
    params: list[str] = field(default_factory=list)
    is_method: bool = False       # uses : syntax (self param)
    decorators: list[str] = field(default_factory=list)  # Python/@decorators
    qualified_name: str | None = None  # fully-qualified name (e.g., "module.Class.method")
    is_coroutine: bool = False    # Tornado @gen.coroutine, Lua coroutine.wrap target


@dataclass
class ImportRef:
    """An import/require statement."""
    module_string: str            # "resty.redis", "./utils", "json"
    line: int
    import_type: str              # "require", "import", "from_import", "require_relative"
    local_binding: str | None = None  # variable name: local redis = require "resty.redis" → "redis"
    is_dynamic: bool = False      # require("handlers." .. x) → True
    static_prefix: str | None = None  # for dynamic: "handlers."


@dataclass
class CallRef:
    """A function/method call."""
    caller_function: str          # function where the call happens (or "<module>" for top-level)
    callee_string: str            # what is being called: "redis.get", "validate", etc.
    line: int
    is_pcall_wrapped: bool = False  # call is inside pcall/xpcall
    resolved_module: str | None = None  # filled by resolver: "resty.redis"
    resolved_function: str | None = None  # filled by resolver: "get"
    resolved_file_path: str | None = None
    resolution_confidence: str | None = None   # "binding", "self", "global_unique"
    classification: str | None = None  # "builtin", "external", "dynamic", "truly_unresolved", or None (resolved)
    is_goroutine: bool = False    # Go: call is spawned via `go` keyword
    is_deferred: bool = False     # Go: call is deferred via `defer` keyword


@dataclass
class ContextAccess:
    """An ngx.ctx field read or write (Lua/OpenResty specific).

    Supports both raw ngx.ctx.field and abstracted context.get("scope").field patterns.
    When a scope is present, field_name is "scope.field" (e.g., "global_config.is_deferrer").
    """
    field_name: str               # e.g., "user_id" or "global_config.is_deferrer"
    access_type: str              # "read" or "write"
    function: str                 # which function does this
    line: int
    scope: str | None = None      # e.g., "global_config" from context.get("global_config")


@dataclass
class SharedDictAccess:
    """An ngx.shared.DICT access (Lua/OpenResty specific)."""
    dict_name: str                # e.g., "rate_limit" from ngx.shared.rate_limit
    operation: str                # "get", "set", "incr", "delete", "add", etc.
    function: str                 # which function does this
    line: int


@dataclass
class InternalRedirect:
    """An ngx.exec() or ngx.location.capture() call (OpenResty internal routing)."""
    target_path: str              # e.g., "/internal/process"
    redirect_type: str            # "exec", "capture", "capture_multi"
    function: str                 # which function does this
    line: int


@dataclass
class RedisKeyAccess:
    """A Redis key read or write."""
    key_name: str                 # e.g., "user:flags:active" (or pattern if not literal)
    operation: str                # "get", "set", "hget", "hset", "publish", "subscribe", etc.
    access_type: str              # "read" or "write"
    function: str                 # which function does this
    line: int


@dataclass
class HttpCallRef:
    """An HTTP client call to another service."""
    url_or_path: str              # the URL/path string (when it's a literal)
    method: str                   # "GET", "POST", etc. or "unknown"
    function: str                 # which function does this
    line: int


@dataclass
class ChannelAccess:
    """A Go channel operation (send, receive, create, close)."""
    channel_name: str
    operation: str         # "send", "receive", "create", "close"
    function: str
    line: int
    element_type: str | None = None   # e.g., "*Task", "error"


@dataclass
class MissionDispatch:
    """A missioner.add_mission() or missioner_timer.post() call."""
    task_name: str                # first string argument: "pts_run"
    queue: str | None = None      # queue name: "policy", "default"
    caller_function: str = "<module>"
    line: int = 0


@dataclass
class DatabaseAccess:
    """A database query call (MySQL, Cassandra)."""
    db_type: str                  # "mysql" or "cassandra"
    operation: str                # "query", "execute", "prepare_statement", etc.
    table: str | None = None      # extracted table name (best-effort)
    function: str = "<module>"
    line: int = 0


@dataclass
class AwsServiceAccess:
    """An AWS service call (SQS, Kinesis, S3)."""
    service: str                  # "sqs", "kinesis", "s3"
    operation: str                # "send_message", "put_record", "upload_file"
    resource_id: str | None = None  # queue URL, stream name, bucket (when extractable)
    function: str = "<module>"
    line: int = 0


@dataclass
class ClassDef:
    """A class definition."""
    name: str
    line: int
    line_end: int
    parent_class: str | None = None   # superclass name
    mixins: list[str] = field(default_factory=list)  # Ruby include/extend
    methods: list[str] = field(default_factory=list)  # method names defined in this class
    qualified_name: str | None = None  # fully-qualified name (e.g., "module::ClassName")
    is_interface: bool = False  # Go: interface vs struct


@dataclass
class ModuleInfo:
    pattern_type: ModulePatternType
    table_var_name: str | None = None
    returned_identifier: str | None = None

    returned_value_kind: str | None = None
    returned_value_callee: str | None = None
    has_public_module_value: bool = False
    exports_are_explicit: bool = False

@dataclass
class FileAST:
    """Complete parse result for a single source file."""
    file_path: str
    language: str
    module_name: str | None = None
    module_info: ModuleInfo | None = None

    classes: list[ClassDef] = field(default_factory=list)
    functions: list[FunctionDef] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    # OpenResty-specific
    ctx_accesses: list[ContextAccess] = field(default_factory=list)
    shared_dict_accesses: list[SharedDictAccess] = field(default_factory=list)
    internal_redirects: list[InternalRedirect] = field(default_factory=list)

    # Cross-service communication
    redis_accesses: list[RedisKeyAccess] = field(default_factory=list)
    http_calls: list[HttpCallRef] = field(default_factory=list)

    # Mission dispatch (Lua missioner system)
    mission_dispatches: list[MissionDispatch] = field(default_factory=list)

    # Database access (MySQL, Cassandra)
    db_accesses: list[DatabaseAccess] = field(default_factory=list)

    # AWS service access (SQS, Kinesis, S3)
    aws_accesses: list[AwsServiceAccess] = field(default_factory=list)

    # Go channel operations
    channel_accesses: list[ChannelAccess] = field(default_factory=list)

    # Metatable inheritance (Lua-specific)
    metatable_parents: dict[str, str] = field(default_factory=dict)  # child_table → parent_module_string

    # Local variable aliases (Lua-specific): (local_name, rhs_dotted_expression)
    # e.g., [("format", "string.format"), ("encode", "cjson.encode")]
    local_aliases: list[tuple[str, str]] = field(default_factory=list)

    # Module-level string constants: M.name = "device_id" -> {"name": "device_id"}
    module_constants: dict[str, str] = field(default_factory=dict)

    # Diagnostics
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        """Return a summary dict for validation reporting."""
        return {
            "file": self.file_path,
            "language": self.language,
            "module_name": self.module_name,
            "module_pattern": self.module_info.pattern_type.value if self.module_info else None,
            "table_var": self.module_info.table_var_name if self.module_info else None,
            "functions": len(self.functions),
            "public_functions": len([f for f in self.functions if f.visibility == "public"]),
            "imports": len(self.imports),
            "dynamic_imports": len([i for i in self.imports if i.is_dynamic]),
            "calls": len(self.calls),
            "pcall_wrapped": len([c for c in self.calls if c.is_pcall_wrapped]),
            "exports": len(self.exports),
            "ctx_accesses": len(self.ctx_accesses),
            "shared_dict_accesses": len(self.shared_dict_accesses),
            "internal_redirects": len(self.internal_redirects),
            "redis_accesses": len(self.redis_accesses),
            "http_calls": len(self.http_calls),
            "warnings": self.warnings,
            "returned_value_kind": self.module_info.returned_value_kind if self.module_info else None,
            "returned_value_callee": self.module_info.returned_value_callee if self.module_info else None,
            "has_public_module_value": self.module_info.has_public_module_value if self.module_info else False,
            "exports_are_explicit": self.module_info.exports_are_explicit if self.module_info else False,
            "resolved_calls": len([c for c in self.calls if c.resolved_file_path]),
        }
