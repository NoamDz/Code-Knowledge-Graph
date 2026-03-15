"""Graph writer: translates FileAST objects into Memgraph nodes and edges.

Uses the neo4j Python driver (compatible with Memgraph via Bolt protocol).
All writes use MERGE to be idempotent.
"""

from __future__ import annotations

import time
from typing import Any

from neo4j import GraphDatabase

from ..parsers.base import FileAST, FunctionDef, ClassDef, ImportRef, CallRef


class GraphWriter:
    """Writes parsed code entities to Memgraph as nodes and edges."""

    def __init__(self, uri: str = "bolt://localhost:7687",
                 username: str = "", password: str = ""):
        auth = (username, password) if username else None
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self._write_count = 0

    def close(self):
        self.driver.close()

    def _run(self, query: str, **params):
        """Execute a Cypher query."""
        with self.driver.session() as session:
            session.run(query, **params)
            self._write_count += 1

    # --- Node upserts ---

    def upsert_file(self, file_path: str, language: str, module_name: str | None = None,
                    pattern_type: str | None = None):
        self._run("""
            MERGE (f:File {path: $path})
            SET f.language = $language,
                f.module_name = $module_name,
                f.pattern_type = $pattern_type,
                f.last_indexed = timestamp()
        """, path=file_path, language=language,
             module_name=module_name, pattern_type=pattern_type)

    def upsert_function(self, file_path: str, func: FunctionDef):
        self._run("""
            MERGE (fn:Function {name: $name, file: $file})
            SET fn.line = $line,
                fn.line_end = $line_end,
                fn.visibility = $visibility,
                fn.is_method = $is_method,
                fn.params = $params
            WITH fn
            MATCH (f:File {path: $file})
            MERGE (f)-[:DEFINES]->(fn)
        """, name=func.name, file=file_path, line=func.line,
             line_end=func.line_end, visibility=func.visibility,
             is_method=func.is_method, params=func.params)

    def upsert_class(self, file_path: str, cls: ClassDef):
        self._run("""
            MERGE (c:Class {name: $name, file: $file})
            SET c.line = $line,
                c.line_end = $line_end,
                c.parent_class = $parent_class,
                c.mixins = $mixins,
                c.methods = $methods
            WITH c
            MATCH (f:File {path: $file})
            MERGE (f)-[:DEFINES]->(c)
        """, name=cls.name, file=file_path, line=cls.line,
             line_end=cls.line_end, parent_class=cls.parent_class,
             mixins=cls.mixins, methods=cls.methods)

        # Create EXTENDS edge if there's a parent class
        if cls.parent_class:
            self._run("""
                MATCH (c:Class {name: $name, file: $file})
                MERGE (parent:Class {name: $parent_name})
                MERGE (c)-[:EXTENDS]->(parent)
            """, name=cls.name, file=file_path, parent_name=cls.parent_class)

        # Create INCLUDES edges for mixins
        for mixin in cls.mixins:
            self._run("""
                MATCH (c:Class {name: $name, file: $file})
                MERGE (m:Module {name: $mixin})
                MERGE (c)-[:INCLUDES]->(m)
            """, name=cls.name, file=file_path, mixin=mixin)

    # --- Edge upserts ---

    def upsert_import(self, from_file: str, to_file: str, module_string: str):
        self._run("""
            MATCH (a:File {path: $from_file})
            MATCH (b:File {path: $to_file})
            MERGE (a)-[r:IMPORTS {module: $module}]->(b)
        """, from_file=from_file, to_file=to_file, module=module_string)

    def upsert_unresolved_import(self, from_file: str, module_string: str, is_dynamic: bool = False):
        """Record an import that couldn't be resolved to a file."""
        self._run("""
            MATCH (f:File {path: $from_file})
            MERGE (m:Module {name: $module})
            SET m.is_external = true, m.is_dynamic = $is_dynamic
            MERGE (f)-[:REQUIRES {module: $module}]->(m)
        """, from_file=from_file, module=module_string, is_dynamic=is_dynamic)

    def upsert_call(self, from_func: str, from_file: str,
                    to_func: str, to_file: str | None = None,
                    line: int = 0, is_pcall: bool = False):
        if to_file:
            self._run("""
                MERGE (a:Function {name: $from_func, file: $from_file})
                MERGE (b:Function {name: $to_func, file: $to_file})
                MERGE (a)-[:CALLS {line: $line, is_pcall: $is_pcall}]->(b)
            """, from_func=from_func, from_file=from_file,
                 to_func=to_func, to_file=to_file,
                 line=line, is_pcall=is_pcall)
        else:
            # Unresolved call — create edge to a placeholder
            self._run("""
                MERGE (a:Function {name: $from_func, file: $from_file})
                MERGE (b:Function {name: $to_func})
                MERGE (a)-[:CALLS {line: $line, is_pcall: $is_pcall}]->(b)
            """, from_func=from_func, from_file=from_file,
                 to_func=to_func, line=line, is_pcall=is_pcall)

    # --- OpenResty-specific ---

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

    def upsert_ctx_access(self, field_name: str, access_type: str,
                           function: str, file_path: str, line: int):
        edge_type = "CTX_WRITES" if access_type == "write" else "CTX_READS"
        self._run(f"""
            MERGE (k:ContextKey {{name: $field}})
            MERGE (fn:Function {{name: $func, file: $file}})
            MERGE (fn)-[:{edge_type} {{line: $line}}]->(k)
        """, field=field_name, func=function, file=file_path, line=line)

    def upsert_shared_dict_access(self, dict_name: str, operation: str,
                                   function: str, file_path: str, line: int):
        self._run("""
            MERGE (d:SharedDict {name: $dict})
            MERGE (fn:Function {name: $func, file: $file})
            MERGE (fn)-[:USES_SHARED {operation: $op, line: $line}]->(d)
        """, dict=dict_name, op=operation, func=function,
             file=file_path, line=line)

    # --- Bulk operations ---

    def ingest_file_ast(self, ast: FileAST, resolved_imports: dict[str, str | None] | None = None):
        """Ingest a complete FileAST into the graph.

        Args:
            ast: The parsed file AST
            resolved_imports: module_string → file_path mapping from resolver
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
            if resolved_path:
                self.upsert_import(ast.file_path, resolved_path, imp.module_string)
            else:
                self.upsert_unresolved_import(ast.file_path, imp.module_string, imp.is_dynamic)

        # Calls
        for call in ast.calls:
            to_file = None
            to_func = call.callee_string
            if call.resolved_module and call.resolved_function:
                # Try to find the resolved module's file
                to_file = resolved_imports.get(call.resolved_module)
                to_func = call.resolved_function
            self.upsert_call(
                call.caller_function, ast.file_path,
                to_func, to_file,
                call.line, call.is_pcall_wrapped,
            )

        # ngx.ctx accesses
        for ctx in ast.ctx_accesses:
            self.upsert_ctx_access(
                ctx.field_name, ctx.access_type,
                ctx.function, ast.file_path, ctx.line,
            )

        # ngx.shared accesses
        for sd in ast.shared_dict_accesses:
            self.upsert_shared_dict_access(
                sd.dict_name, sd.operation,
                sd.function, ast.file_path, sd.line,
            )

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
