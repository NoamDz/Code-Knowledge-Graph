"""Graph writer: translates FileAST objects into Memgraph nodes and edges.

Uses the neo4j Python driver (compatible with Memgraph via Bolt protocol).
All writes use MERGE to be idempotent.

High-volume writes (File, Function, Class nodes; DEFINES, IMPORTS, CALLS edges)
are buffered and flushed in batches using UNWIND for performance.
Low-volume writes with complex conditional logic remain as direct _run() calls.
"""

from __future__ import annotations

import time
from typing import Any

from neo4j import GraphDatabase

from ..parsers.base import FileAST, FunctionDef, ClassDef, ImportRef, CallRef


class GraphWriter:
    """Writes parsed code entities to Memgraph as nodes and edges."""

    def __init__(self, uri: str = "bolt://localhost:7687",
                 username: str = "", password: str = "",
                 flush_threshold: int = 500):
        auth = (username, password) if username else None
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self._write_count = 0
        self._flush_threshold = flush_threshold

        # Buffers for batched writes
        # Node buffers: label -> list of param dicts
        self._node_buffers: dict[str, list[dict]] = {}
        # Edge buffers: edge_key -> list of param dicts
        # edge_key encodes the UNWIND query pattern (e.g. "CALLS_resolved", "CALLS_unresolved")
        self._edge_buffers: dict[str, list[dict]] = {}

    def close(self):
        self.flush_all()
        self.driver.close()

    def _run(self, query: str, **params):
        """Execute a single Cypher query (used for low-volume writes)."""
        with self.driver.session() as session:
            session.run(query, **params)
            self._write_count += 1

    # --- Buffering infrastructure ---

    def _buffer_node(self, label: str, params: dict):
        """Accumulate a node upsert. Auto-flushes when threshold is reached."""
        buf = self._node_buffers.setdefault(label, [])
        buf.append(params)
        if len(buf) >= self._flush_threshold:
            self._flush_nodes(label)

    def _buffer_edge(self, edge_type: str, params: dict):
        """Accumulate an edge upsert. Auto-flushes when threshold is reached."""
        buf = self._edge_buffers.setdefault(edge_type, [])
        buf.append(params)
        if len(buf) >= self._flush_threshold:
            self._flush_edges(edge_type)

    def _flush_nodes(self, label: str):
        """Flush a single node buffer using UNWIND for batch MERGE."""
        batch = self._node_buffers.pop(label, [])
        if not batch:
            return

        query = self._node_queries.get(label)
        if not query:
            # Fallback: should not happen if all labels are registered
            return

        with self.driver.session() as session:
            session.run(query, batch=batch)
        self._write_count += len(batch)

    def _flush_edges(self, edge_type: str):
        """Flush a single edge buffer using UNWIND for batch MERGE."""
        batch = self._edge_buffers.pop(edge_type, [])
        if not batch:
            return

        query = self._edge_queries.get(edge_type)
        if not query:
            return

        with self.driver.session() as session:
            session.run(query, batch=batch)
        self._write_count += len(batch)

    def flush_all(self):
        """Flush all remaining node and edge buffers.

        Must be called after all items are buffered to ensure nothing is left
        un-written. The close() method calls this automatically.
        """
        # Flush nodes first (edges may reference them)
        for label in list(self._node_buffers.keys()):
            self._flush_nodes(label)
        # Then flush edges
        for edge_type in list(self._edge_buffers.keys()):
            self._flush_edges(edge_type)

    # --- UNWIND query templates ---
    # These are the batched equivalents of the individual MERGE statements.

    _node_queries: dict[str, str] = {
        "File": """
            UNWIND $batch AS row
            MERGE (f:File {path: row.path})
            SET f.language = row.language,
                f.module_name = row.module_name,
                f.pattern_type = row.pattern_type,
                f.last_indexed = timestamp()
        """,
        "Function": """
            UNWIND $batch AS row
            MERGE (fn:Function {name: row.name, file: row.file})
            SET fn.line = row.line,
                fn.line_end = row.line_end,
                fn.visibility = row.visibility,
                fn.is_method = row.is_method,
                fn.params = row.params,
                fn.qualified_name = row.qualified_name,
                fn.decorators = row.decorators,
                fn.is_coroutine = row.is_coroutine
        """,
        "Class": """
            UNWIND $batch AS row
            MERGE (c:Class {name: row.name, file: row.file})
            SET c.line = row.line,
                c.line_end = row.line_end,
                c.parent_class = row.parent_class,
                c.mixins = row.mixins,
                c.methods = row.methods,
                c.qualified_name = row.qualified_name,
                c.is_interface = row.is_interface
        """,
    }

    _edge_queries: dict[str, str] = {
        # NOTE: these MERGE their endpoint nodes rather than MATCH them. File
        # nodes are buffered and may not be flushed yet when an edge batch
        # auto-flushes mid-stream; a MATCH would silently find nothing and drop
        # the edge (this caused DEFINES/IMPORTS to lose ~90% of edges). MERGE is
        # idempotent — upsert_file/upsert_function SET the real props on the same
        # key whenever their buffers flush.
        "DEFINES_Function": """
            UNWIND $batch AS row
            MERGE (f:File {path: row.file})
            MERGE (fn:Function {name: row.name, file: row.file})
            MERGE (f)-[:DEFINES]->(fn)
        """,
        "DEFINES_Class": """
            UNWIND $batch AS row
            MERGE (f:File {path: row.file})
            MERGE (c:Class {name: row.name, file: row.file})
            MERGE (f)-[:DEFINES]->(c)
        """,
        "IMPORTS": """
            UNWIND $batch AS row
            MERGE (a:File {path: row.from_file})
            MERGE (b:File {path: row.to_file})
            MERGE (a)-[r:IMPORTS {module: row.module}]->(b)
            SET r.local_binding = row.local_binding
        """,
        "CALLS_resolved": """
            UNWIND $batch AS row
            MERGE (a:Function {name: row.from_func, file: row.from_file})
            MERGE (b:Function {name: row.to_func, file: row.to_file})
            MERGE (a)-[:CALLS {line: row.line, is_pcall: row.is_pcall,
                               resolution_confidence: row.resolution_confidence,
                               classification: row.classification,
                               is_goroutine: row.is_goroutine,
                               is_deferred: row.is_deferred}]->(b)
        """,
        "CALLS_unresolved": """
            UNWIND $batch AS row
            MERGE (a:Function {name: row.from_func, file: row.from_file})
            MERGE (b:Function {name: row.to_func})
            MERGE (a)-[:CALLS {line: row.line, is_pcall: row.is_pcall, classification: row.classification,
                               is_goroutine: row.is_goroutine, is_deferred: row.is_deferred}]->(b)
        """,
    }

    # --- Node upserts (buffered) ---

    def upsert_file(self, file_path: str, language: str, module_name: str | None = None,
                    pattern_type: str | None = None):
        self._buffer_node("File", {
            "path": file_path,
            "language": language,
            "module_name": module_name,
            "pattern_type": pattern_type,
        })

    def upsert_function(self, file_path: str, func: FunctionDef):
        params = {
            "name": func.name,
            "file": file_path,
            "line": func.line,
            "line_end": func.line_end,
            "visibility": func.visibility,
            "is_method": func.is_method,
            "params": func.params,
            "qualified_name": func.qualified_name,
            "decorators": func.decorators,
            "is_coroutine": func.is_coroutine,
        }
        # Buffer the Function node
        self._buffer_node("Function", params)
        # Buffer the DEFINES edge (File -> Function)
        self._buffer_edge("DEFINES_Function", {
            "file": file_path,
            "name": func.name,
        })

    def upsert_class(self, file_path: str, cls: ClassDef):
        params = {
            "name": cls.name,
            "file": file_path,
            "line": cls.line,
            "line_end": cls.line_end,
            "parent_class": cls.parent_class,
            "mixins": cls.mixins,
            "methods": cls.methods,
            "qualified_name": cls.qualified_name,
            "is_interface": cls.is_interface,
        }
        # Buffer the Class node
        self._buffer_node("Class", params)
        # Buffer the DEFINES edge (File -> Class)
        self._buffer_edge("DEFINES_Class", {
            "file": file_path,
            "name": cls.name,
        })

        # EXTENDS and INCLUDES edges stay as direct _run() calls
        # because they are conditional and low-volume
        if cls.parent_class:
            self._run("""
                MATCH (c:Class {name: $name, file: $file})
                MERGE (parent:Class {name: $parent_name})
                MERGE (c)-[:EXTENDS]->(parent)
            """, name=cls.name, file=file_path, parent_name=cls.parent_class)

        for mixin in cls.mixins:
            self._run("""
                MATCH (c:Class {name: $name, file: $file})
                MERGE (m:Module {name: $mixin})
                MERGE (c)-[:INCLUDES]->(m)
            """, name=cls.name, file=file_path, mixin=mixin)

    # --- Edge upserts (buffered) ---

    def upsert_import(self, from_file: str, to_file: str, module_string: str,
                      local_binding: str | None = None):
        self._buffer_edge("IMPORTS", {
            "from_file": from_file,
            "to_file": to_file,
            "module": module_string,
            "local_binding": local_binding,
        })

    def upsert_unresolved_import(self, from_file: str, module_string: str, is_dynamic: bool = False):
        """Record an import that couldn't be resolved to a file.

        Kept as direct _run() because it involves conditional SET on the Module node.
        """
        self._run("""
            MERGE (f:File {path: $from_file})
            MERGE (m:Module {name: $module})
            SET m.is_external = true, m.is_dynamic = $is_dynamic
            MERGE (f)-[:REQUIRES {module: $module}]->(m)
        """, from_file=from_file, module=module_string, is_dynamic=is_dynamic)

    def upsert_call(self, from_func: str, from_file: str,
                    to_func: str, to_file: str | None = None,
                    line: int = 0, is_pcall: bool = False,
                    classification: str | None = None,
                    resolution_confidence: str | None = None,
                    is_goroutine: bool = False,
                    is_deferred: bool = False):
        if to_file:
            self._buffer_edge("CALLS_resolved", {
                "from_func": from_func,
                "from_file": from_file,
                "to_func": to_func,
                "to_file": to_file,
                "line": line,
                "is_pcall": is_pcall,
                "resolution_confidence": resolution_confidence,
                "classification": classification,
                "is_goroutine": is_goroutine,
                "is_deferred": is_deferred,
            })
        else:
            self._buffer_edge("CALLS_unresolved", {
                "from_func": from_func,
                "from_file": from_file,
                "to_func": to_func,
                "line": line,
                "is_pcall": is_pcall,
                "classification": classification,
                "is_goroutine": is_goroutine,
                "is_deferred": is_deferred,
            })

    # --- OpenResty-specific (kept as direct _run() — low volume, complex logic) ---

    def upsert_nginx_endpoint(self, location: str, phase: str,
                               lua_file: str | None, is_inline: bool):
        self._run("""
            MERGE (e:Endpoint {path: $location})
            MERGE (p:NginxPhase {phase_type: $phase, endpoint: $location})
            MERGE (e)-[:HAS_PHASE]->(p)
            SET p.lua_file = $lua_file, p.is_inline = $is_inline
        """, location=location, phase=phase,
             lua_file=lua_file, is_inline=is_inline)

        if lua_file:
            self._run("""
                MATCH (p:NginxPhase {phase_type: $phase, endpoint: $location})
                MATCH (f:File {path: $lua_file})
                MERGE (p)-[:HANDLES]->(f)
            """, phase=phase, location=location, lua_file=lua_file)

    def upsert_phase_handles_file(self, location: str, phase: str, file_path: str):
        """Link an nginx phase to a File it dispatches into (inline require target).

        Mirrors the HANDLES edge that upsert_nginx_endpoint creates for *_by_lua_file
        directives, but for require() targets found inside inline *_by_lua_block code.
        Silently no-ops if the File node does not exist (MATCH fails).
        """
        self._run("""
            MATCH (p:NginxPhase {phase_type: $phase, endpoint: $location})
            MATCH (f:File {path: $file_path})
            MERGE (p)-[:HANDLES]->(f)
        """, phase=phase, location=location, file_path=file_path)

    def upsert_endpoint_delegation(self, source_path: str, target_path: str):
        """Link an endpoint to a named location it delegates to via try_files.

        MERGEs the source Endpoint so a phaseless fallback (`location /` with only
        `try_files $uri @router`) becomes a real node, then connects it to the
        named location (`@router`) that actually holds the Lua phase.
        """
        self._run("""
            MERGE (s:Endpoint {path: $source})
            MERGE (t:Endpoint {path: $target})
            MERGE (s)-[:DELEGATES_TO]->(t)
        """, source=source_path, target=target_path)

    def upsert_ctx_access(self, field_name: str, access_type: str,
                           function: str, file_path: str, line: int,
                           scope: str | None = None):
        edge_type = "CTX_WRITES" if access_type == "write" else "CTX_READS"
        self._run(f"""
            MERGE (k:ContextKey {{name: $field}})
            MERGE (fn:Function {{name: $func, file: $file}})
            MERGE (fn)-[:{edge_type} {{line: $line, scope: $scope}}]->(k)
        """, field=field_name, func=function, file=file_path, line=line, scope=scope)

    def upsert_shared_dict_access(self, dict_name: str, operation: str,
                                   function: str, file_path: str, line: int):
        self._run("""
            MERGE (d:SharedDict {name: $dict})
            MERGE (fn:Function {name: $func, file: $file})
            MERGE (fn)-[:USES_SHARED {operation: $op, line: $line}]->(d)
        """, dict=dict_name, op=operation, func=function,
             file=file_path, line=line)

    def upsert_channel_access(self, channel_name: str, operation: str,
                               function: str, file_path: str, line: int,
                               element_type: str | None = None):
        """Create a Channel node and CHAN_SENDS or CHAN_RECEIVES edge."""
        edge_type = "CHAN_SENDS" if operation in ("send", "create", "close") else "CHAN_RECEIVES"
        self._run(f"""
            MERGE (ch:Channel {{name: $channel_name}})
            ON CREATE SET ch.element_type = $element_type
            WITH ch
            MERGE (fn:Function {{name: $function, file: $file_path}})
            MERGE (fn)-[:{edge_type} {{line: $line}}]->(ch)
        """, channel_name=channel_name, element_type=element_type,
            file_path=file_path, function=function, line=line)

    def upsert_metatable_inheritance(self, child_file: str, parent_module: str,
                                      table_var: str):
        """Create an INHERITS_VIA_METATABLE edge from child File to parent Module."""
        self._run("""
            MERGE (child:File {path: $child_file})
            MERGE (parent:Module {name: $parent_module})
            MERGE (child)-[:INHERITS_VIA_METATABLE {table_var: $table_var}]->(parent)
        """, child_file=child_file, parent_module=parent_module, table_var=table_var)

    def upsert_internal_redirect(self, source_function: str, source_file: str,
                                  target_path: str, redirect_type: str, line: int):
        """Create a REROUTES_TO edge from a function to an Endpoint."""
        self._run("""
            MERGE (fn:Function {name: $func, file: $file})
            MERGE (e:Endpoint {path: $target})
            MERGE (fn)-[:REROUTES_TO {redirect_type: $rtype, line: $line}]->(e)
        """, func=source_function, file=source_file,
             target=target_path, rtype=redirect_type, line=line)

    def upsert_redis_access(self, key_name: str, operation: str,
                             access_type: str, function: str,
                             file_path: str, line: int):
        """Create a RedisKey node and REDIS_READS/REDIS_WRITES edge."""
        edge_type = "REDIS_WRITES" if access_type == "write" else "REDIS_READS"
        self._run(f"""
            MERGE (k:RedisKey {{name: $key}})
            MERGE (fn:Function {{name: $func, file: $file}})
            MERGE (fn)-[:{edge_type} {{operation: $op, line: $line}}]->(k)
        """, key=key_name, func=function, file=file_path,
             op=operation, line=line)

    def upsert_http_call(self, url_or_path: str, method: str,
                          function: str, file_path: str, line: int):
        """Create an HTTP_CALLS edge from a function to an Endpoint (if path matches)."""
        if url_or_path.startswith("/"):
            self._run("""
                MERGE (fn:Function {name: $func, file: $file})
                MERGE (e:Endpoint {path: $path})
                MERGE (fn)-[:HTTP_CALLS {method: $method, line: $line}]->(e)
            """, func=function, file=file_path,
                 path=url_or_path, method=method, line=line)
        else:
            self._run("""
                MERGE (fn:Function {name: $func, file: $file})
                MERGE (e:Endpoint {path: $url})
                SET e.is_external = true
                MERGE (fn)-[:HTTP_CALLS {method: $method, line: $line}]->(e)
            """, func=function, file=file_path,
                 url=url_or_path, method=method, line=line)

    def upsert_proxy_pass(self, location_path: str, target: str,
                           upstream_name: str | None = None):
        """Create a PROXIES_TO edge from an Endpoint to a Service."""
        service_name = upstream_name or target
        self._run("""
            MERGE (e:Endpoint {path: $location})
            MERGE (s:Service {name: $service_name})
            MERGE (e)-[:PROXIES_TO {upstream_name: $upstream}]->(s)
            SET s.target = $target
        """, location=location_path, service_name=service_name,
             upstream=upstream_name or "", target=target)

    def upsert_upstream(self, name: str, servers: list[str]):
        """Create or update a Service node from an upstream block."""
        socket_path = None
        for srv in servers:
            if "unix:" in srv:
                socket_path = srv.split("unix:", 1)[1].split(";")[0].strip()
                break

        self._run("""
            MERGE (s:Service {name: $name})
            SET s.servers = $servers,
                s.socket_path = $socket_path,
                s.type = "upstream"
        """, name=name, servers=servers, socket_path=socket_path)

    # --- Bulk operations ---

    def ingest_file_ast(self, ast: FileAST, resolved_imports: dict[str, str | None] | None = None):
        """Ingest a complete FileAST into the graph.

        Args:
            ast: The parsed file AST
            resolved_imports: module_string -> file_path mapping from resolver
        """
        resolved_imports = resolved_imports or {}

        # File node
        module_name = ast.module_name
        pattern_type = ast.module_info.pattern_type.value if ast.module_info else None
        self.upsert_file(ast.file_path, ast.language, module_name, pattern_type)

        # Functions
        for func in ast.functions:
            self.upsert_function(ast.file_path, func)

        # Classes
        for cls in ast.classes:
            self.upsert_class(ast.file_path, cls)

        # Imports
        for imp in ast.imports:
            resolved_path = resolved_imports.get(imp.module_string)
            # Markers like "__go_stdlib__" / "__python_stdlib__" / "__go_external__"
            # are classifications, not real file paths — treat them as external
            # (REQUIRES -> Module) rather than IMPORTS to a junk File node.
            if resolved_path and not resolved_path.startswith("__"):
                self.upsert_import(ast.file_path, resolved_path, imp.module_string,
                                   local_binding=imp.local_binding)
            else:
                self.upsert_unresolved_import(ast.file_path, imp.module_string, imp.is_dynamic)

        # Metatable inheritance (Lua-specific)
        for table_var, parent_module in ast.metatable_parents.items():
            self.upsert_metatable_inheritance(ast.file_path, parent_module, table_var)

        # Calls
        for call in ast.calls:
            to_file = None
            to_func = call.callee_string
            if call.resolved_module and call.resolved_function:
                to_file = resolved_imports.get(call.resolved_module)
                to_func = call.resolved_function
            self.upsert_call(
                call.caller_function, ast.file_path,
                to_func, to_file,
                call.line, call.is_pcall_wrapped,
                call.classification,
                call.resolution_confidence,
                call.is_goroutine,
                call.is_deferred,
            )

        # ngx.ctx accesses
        for ctx in ast.ctx_accesses:
            self.upsert_ctx_access(
                ctx.field_name, ctx.access_type,
                ctx.function, ast.file_path, ctx.line,
                scope=ctx.scope,
            )

        # ngx.shared accesses
        for sd in ast.shared_dict_accesses:
            self.upsert_shared_dict_access(
                sd.dict_name, sd.operation,
                sd.function, ast.file_path, sd.line,
            )

        # Internal redirects
        for redir in ast.internal_redirects:
            self.upsert_internal_redirect(
                redir.function, ast.file_path,
                redir.target_path, redir.redirect_type, redir.line,
            )

        # Redis accesses
        for ra in ast.redis_accesses:
            self.upsert_redis_access(
                ra.key_name, ra.operation, ra.access_type,
                ra.function, ast.file_path, ra.line,
            )

        # HTTP calls
        for hc in ast.http_calls:
            self.upsert_http_call(
                hc.url_or_path, hc.method,
                hc.function, ast.file_path, hc.line,
            )

        # Database accesses
        for da in ast.db_accesses:
            if da.db_type == "cassandra":
                self.upsert_cassandra_access(
                    da.function, ast.file_path,
                    da.operation, da.line,
                )
            else:
                self.upsert_db_access(
                    da.function, ast.file_path,
                    da.db_type, da.operation, da.table, da.line,
                )

        # AWS service accesses
        for sa in ast.aws_accesses:
            if sa.service == "sqs":
                access_type = "produce" if sa.operation in (
                    "send_message", "send_message_batch"
                ) else "consume"
                self.upsert_sqs_access(
                    ast.file_path, sa.resource_id or "<unknown>",
                    sa.operation, access_type,
                )
            elif sa.service == "kinesis":
                self.upsert_kinesis_access(
                    ast.file_path, sa.resource_id or "<unknown>",
                    sa.operation,
                )
            elif sa.service == "s3":
                self.upsert_s3_access(
                    ast.file_path, sa.resource_id or "<unknown>",
                    sa.operation,
                )

        # Channel accesses (Go)
        for ca in ast.channel_accesses:
            self.upsert_channel_access(
                ca.channel_name, ca.operation,
                ca.function, ast.file_path, ca.line,
                ca.element_type,
            )

    def upsert_mission_dispatch(self, source_file: str, task_name: str,
                                 target_file: str | None, line: int):
        """Create a DISPATCHES edge from a file to a task handler file."""
        if target_file:
            self._run("""
                MERGE (src:File {path: $source})
                MERGE (tgt:File {path: $target})
                MERGE (src)-[:DISPATCHES {task: $task, line: $line}]->(tgt)
            """, source=source_file, target=target_file, task=task_name, line=line)

    def upsert_signals_assessor(self, source_file: str, target_file: str,
                                flag: str, line: int):
        """Create a SIGNALS_ASSESSOR edge (collector/handler -> assessor)."""
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:SIGNALS_ASSESSOR {flag: $flag, line: $line}]->(tgt)
        """, source=source_file, target=target_file, flag=flag, line=line)

    def upsert_trigger_edge(self, source_file: str, target_file: str,
                            name: str, line: int):
        """Create a TRIGGERS edge (publisher -> subscriber), joined on trigger name."""
        # PUBLISHES/SUBSCRIBES make the TriggerEvent node reachable; TRIGGERS
        # stays as the direct pub->sub edge (denormalized for one-hop queries).
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (t:TriggerEvent {name: $name})
            MERGE (src)-[:TRIGGERS {name: $name, line: $line}]->(tgt)
            MERGE (src)-[:PUBLISHES {line: $line}]->(t)
            MERGE (tgt)-[:SUBSCRIBES]->(t)
        """, source=source_file, target=target_file, name=name, line=line)

    def upsert_same_package(self, file_a: str, file_b: str, package_name: str):
        """Create a SAME_PACKAGE edge between two files in the same Go package."""
        self._run("""
            MERGE (a:File {path: $file_a})
            MERGE (b:File {path: $file_b})
            MERGE (a)-[:SAME_PACKAGE {package: $pkg}]->(b)
        """, file_a=file_a, file_b=file_b, pkg=package_name)

    def upsert_endpoint_link(self, source_file: str, source_function: str,
                             endpoint_path: str, method: str, line: int):
        """HTTP_CALLS edge from caller to endpoint (cross-language)."""
        self._run("""
            MERGE (fn:Function {name: $func, file: $src_file})
            MERGE (e:Endpoint {path: $endpoint})
            MERGE (fn)-[:HTTP_CALLS {method: $method, line: $line, cross_language: true}]->(e)
        """, func=source_function, src_file=source_file,
             endpoint=endpoint_path, method=method, line=line)

    def upsert_go_socket_endpoint(self, socket_path: str, handler_path: str,
                                   go_file: str):
        """Endpoint + SERVES edge for Go unix socket handler."""
        self._run("""
            MERGE (e:Endpoint {path: $handler_path})
            SET e.socket = $socket, e.is_go_handler = true
            MERGE (f:File {path: $go_file})
            MERGE (e)-[:SERVES]->(f)
        """, handler_path=handler_path, socket=socket_path, go_file=go_file)

    def upsert_dynamic_load(self, source_file: str, target_file: str,
                            load_type: str):
        """Create a LOADS_DYNAMICALLY edge from source to target file."""
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:LOADS_DYNAMICALLY {load_type: $load_type}]->(tgt)
        """, source=source_file, target=target_file, load_type=load_type)

    def upsert_implements(self, struct_name: str, interface_name: str,
                          struct_file: str):
        """Create an IMPLEMENTS edge from a struct to an interface."""
        self._run("""
            MERGE (s:Class {name: $struct_name, file: $struct_file})
            MERGE (i:Class {name: $iface_name})
            MERGE (s)-[:IMPLEMENTS]->(i)
        """, struct_name=struct_name, iface_name=interface_name,
             struct_file=struct_file)

    def upsert_potential_import(self, source_file: str, target_file: str,
                                prefix: str, line: int):
        """Create a POTENTIAL_IMPORT edge from dynamic require prefix expansion."""
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:POTENTIAL_IMPORT {prefix: $prefix, line: $line, dynamic: true}]->(tgt)
        """, source=source_file, target=target_file, prefix=prefix, line=line)

    def upsert_js_includes(self, source_file: str, target_file: str,
                            include_type: str = "render"):
        """Create an INCLUDES edge between two File nodes (JS ERB render-chain).

        Args:
            source_file: The .js.erb file that contains the render() call
            target_file: The file being rendered/included
            include_type: "render" for explicit render() calls,
                          "collector_loop" for collectors_rendered.each
        """
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:INCLUDES {include_type: $include_type, language: "javascript"}]->(tgt)
        """, source=source_file, target=target_file, include_type=include_type)

    # --- Cross-service IPC upserts ---

    def upsert_unix_socket(self, socket_path: str, protocol: str):
        """Create a UnixSocket node."""
        self._run("""
            MERGE (s:UnixSocket {path: $path})
            SET s.protocol = $protocol
        """, path=socket_path, protocol=protocol)

    def upsert_socket_listens(self, file_path: str, socket_path: str):
        """Create a SOCKET_LISTENS edge from File to UnixSocket."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (s:UnixSocket {path: $socket})
            MERGE (f)-[:SOCKET_LISTENS]->(s)
        """, file=file_path, socket=socket_path)

    def upsert_socket_connects(self, file_path: str, socket_path: str):
        """Create a SOCKET_CONNECTS edge from File to UnixSocket."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (s:UnixSocket {path: $socket})
            MERGE (f)-[:SOCKET_CONNECTS]->(s)
        """, file=file_path, socket=socket_path)

    def upsert_shared_redis_pattern(self, pattern: str, file_path: str,
                                     access_type: str):
        """Create SharedRedisPattern node and WRITES/READS_REDIS_PATTERN edge."""
        edge_type = "WRITES_REDIS_PATTERN" if access_type == "write" else "READS_REDIS_PATTERN"
        self._run(f"""
            MERGE (p:SharedRedisPattern {{pattern: $pattern}})
            MERGE (f:File {{path: $file}})
            MERGE (f)-[:{edge_type}]->(p)
        """, pattern=pattern, file=file_path)

    def upsert_db_access(self, function: str, file_path: str,
                          db_type: str, operation: str,
                          table: str | None, line: int):
        """Create a QUERIES_DB edge from Function to a database label."""
        label = table or f"<{db_type}>"
        self._run("""
            MERGE (fn:Function {name: $func, file: $file})
            MERGE (fn)-[:QUERIES_DB {db_type: $db_type, operation: $op,
                                      table: $table, line: $line}]->(:DatabaseTable {name: $label})
        """, func=function, file=file_path, db_type=db_type,
             op=operation, table=table or "", label=label, line=line)

    def upsert_cassandra_access(self, function: str, file_path: str,
                                 operation: str, line: int):
        """Create a QUERIES_CASSANDRA edge."""
        self._run("""
            MERGE (fn:Function {name: $func, file: $file})
            MERGE (fn)-[:QUERIES_CASSANDRA {operation: $op, line: $line}]->(:DatabaseTable {name: 'cassandra'})
        """, func=function, file=file_path, op=operation, line=line)

    def upsert_sqs_access(self, file_path: str, queue_name: str,
                           operation: str, access_type: str):
        """Create SQSQueue node and PRODUCES_TO/CONSUMES_FROM edge."""
        edge_type = "PRODUCES_TO" if access_type == "produce" else "CONSUMES_FROM"
        self._run(f"""
            MERGE (q:SQSQueue {{name: $queue}})
            MERGE (f:File {{path: $file}})
            MERGE (f)-[:{edge_type} {{operation: $op}}]->(q)
        """, queue=queue_name, file=file_path, op=operation)

    def upsert_kinesis_access(self, file_path: str, stream_name: str,
                               operation: str):
        """Create KinesisStream node and STREAMS_TO edge."""
        self._run("""
            MERGE (k:KinesisStream {name: $stream})
            MERGE (f:File {path: $file})
            MERGE (f)-[:STREAMS_TO {operation: $op}]->(k)
        """, stream=stream_name, file=file_path, op=operation)

    def upsert_s3_access(self, file_path: str, bucket: str, operation: str):
        """Create ACCESSES_S3 edge from File to S3 bucket identifier."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (f)-[:ACCESSES_S3 {operation: $op, bucket: $bucket}]->(:Service {name: $bucket_svc})
        """, file=file_path, op=operation, bucket=bucket,
             bucket_svc=f"s3:{bucket}")

    def upsert_config_reads(self, file_path: str, config_name: str):
        """Create ConfigFile node and READS_CONFIG edge."""
        self._run("""
            MERGE (c:ConfigFile {name: $config})
            MERGE (f:File {path: $file})
            MERGE (f)-[:READS_CONFIG]->(c)
        """, config=config_name, file=file_path)

    # --- Cross-language data flow upserts ---

    def upsert_shared_data_structure(self, name: str, fields: list[str],
                                      serialization_format: str):
        """Create or update a SharedDataStructure node."""
        self._run("""
            MERGE (s:SharedDataStructure {name: $name})
            SET s.fields = $fields,
                s.serialization_format = $fmt
        """, name=name, fields=fields, fmt=serialization_format)

    def upsert_defines_structure(self, file_path: str, structure_name: str,
                                  language: str, field_count: int):
        """Create a DEFINES_SHARED_STRUCTURE edge from File to SharedDataStructure."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (s:SharedDataStructure {name: $struct})
            MERGE (f)-[:DEFINES_SHARED_STRUCTURE {language: $lang, field_count: $fc}]->(s)
        """, file=file_path, struct=structure_name,
             lang=language, fc=field_count)

    def upsert_shared_constant(self, name: str, values: list[str]):
        """Create or update a SharedConstant node."""
        self._run("""
            MERGE (c:SharedConstant {name: $name})
            SET c.values = $values
        """, name=name, values=values)

    def upsert_defines_constant(self, file_path: str, constant_name: str,
                                 language: str):
        """Create a DEFINES_CONSTANT edge from File to SharedConstant."""
        self._run("""
            MERGE (f:File {path: $file})
            MERGE (c:SharedConstant {name: $const})
            MERGE (f)-[:DEFINES_CONSTANT {language: $lang}]->(c)
        """, file=file_path, const=constant_name, lang=language)

    def clear_file(self, file_path: str):
        """Remove all nodes and edges originating from a file."""
        self._run("""
            MATCH (f:File {path: $path})
            OPTIONAL MATCH (f)-[:DEFINES]->(node)
            DETACH DELETE node
        """, path=file_path)
        self._run("""
            MATCH (f:File {path: $path})-[r]->()
            DELETE r
        """, path=file_path)

    @property
    def write_count(self) -> int:
        return self._write_count
