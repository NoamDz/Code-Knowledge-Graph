"""Cross-file call resolution engine.

After all files are parsed, this engine:
  1. Builds a global symbol table (module_name.function → file_path)
  2. Builds a class hierarchy and method map for inheritance-aware resolution
  3. Builds a basic type map for constructor/factory patterns
  4. Resolves CALLS edges using:
     a. require-to-variable bindings
     b. self-calls on module table
     c. same-file resolution (functions calling other functions in the same file)
     d. inheritance-aware resolution (BFS through parent classes)
     e. type-inferred resolution (constructor return types)
     f. global symbol table lookup
  5. Produces resolution statistics

Usage:
    engine = CallResolver(all_asts, resolvers)
    engine.resolve_all()
    # Now all CallRef objects in the ASTs have resolved_module/resolved_function
    stats = engine.stats()
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST, CallRef


class CallResolver:
    """Resolves cross-file function calls using import bindings and a global symbol table."""

    def __init__(self, all_asts: dict[str, FileAST], resolvers: dict):
        """
        Args:
            all_asts: file_path → FileAST for all parsed files
            resolvers: language → resolver instance (e.g., {"lua": LuaResolver(...)})
        """
        self.all_asts = all_asts
        self.resolvers = resolvers

        # Global symbol table: "module.function" → file_path
        self.global_symbols: dict[str, str] = {}

        # Qualified name symbol table: qualified_name → file_path
        self.qualified_symbols: dict[str, str] = {}

        # Class hierarchy: child_class → parent_class
        self.class_hierarchy: dict[str, str] = {}

        # Class methods: class_name → {method_names}
        self.class_methods: dict[str, set[str]] = {}

        # Class-to-file map: class_name → file_path
        self.class_files: dict[str, str] = {}

        # Resolution stats
        self._total_calls = 0
        self._already_resolved = 0
        self._newly_resolved = 0
        self._unresolved = 0

    def build_symbol_table(self):
        """Build the global symbol table, class hierarchy, and type maps from all parsed ASTs."""
        for file_path, ast in self.all_asts.items():
            # Build class hierarchy and method map (Item 8)
            for cls in ast.classes:
                if cls.parent_class:
                    self.class_hierarchy[cls.name] = cls.parent_class
                self.class_methods[cls.name] = set(cls.methods)
                self.class_files[cls.name] = file_path

            # Build global symbol table
            if not ast.module_name:
                continue

            for func in ast.functions:
                if func.visibility == "public":
                    # Use the base function name (strip table prefix)
                    func_base = func.name.split(".")[-1].split(":")[-1]
                    key = f"{ast.module_name}.{func_base}"
                    self.global_symbols[key] = file_path

                # Also index by qualified name if available (Item 3)
                if func.qualified_name:
                    self.qualified_symbols[func.qualified_name] = file_path

            for export_name in ast.exports:
                key = f"{ast.module_name}.{export_name}"
                if key not in self.global_symbols:
                    self.global_symbols[key] = file_path

    def resolve_all(self):
        """Resolve all unresolved calls across all ASTs."""
        self.build_symbol_table()

        for file_path, ast in self.all_asts.items():
            # Build file-level binding map from imports
            binding_map = self._build_binding_map(ast)

            # Build type map for this file (Item 9)
            type_map = self._build_type_map(ast)

            for call in ast.calls:
                self._total_calls += 1

                if call.resolved_module:
                    self._already_resolved += 1
                    continue

                # Try to resolve using binding map
                resolved = self._resolve_call(call, binding_map, ast, type_map)
                if resolved:
                    self._newly_resolved += 1
                else:
                    self._unresolved += 1

    def _build_binding_map(self, ast: FileAST) -> dict[str, str]:
        """Build local_var → module_string map from imports."""
        binding_map = {}
        for imp in ast.imports:
            if imp.local_binding and not imp.is_dynamic:
                # Handle comma-separated bindings (from Python/JS destructured imports)
                for binding in imp.local_binding.split(", "):
                    binding = binding.strip()
                    if binding:
                        binding_map[binding] = imp.module_string
        return binding_map

    def _build_type_map(self, ast: FileAST) -> dict[str, str]:
        """Infer variable types from constructor calls and known patterns (Item 9).

        Returns a mapping of callee_string → class_name for calls that are
        constructor/factory invocations.
        """
        type_map: dict[str, str] = {}  # callee_string → class_name

        # Build a set of known class names across all files
        all_class_names: set[str] = set()
        for file_ast in self.all_asts.values():
            for cls in file_ast.classes:
                all_class_names.add(cls.name)

        for call in ast.calls:
            callee = call.callee_string
            # Pattern: ClassName() (Python), ClassName.new (Ruby), new ClassName (JS)
            for cls_name in all_class_names:
                if (callee == cls_name
                        or callee == f"{cls_name}.new"
                        or callee == f"new {cls_name}"):
                    type_map[callee] = cls_name
                    break

        return type_map

    def _resolve_via_inheritance(self, class_name: str, method_name: str) -> str | None:
        """BFS through class hierarchy to find which class defines a method (Item 8)."""
        visited: set[str] = set()
        queue = [class_name]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if current in self.class_methods and method_name in self.class_methods[current]:
                return current
            parent = self.class_hierarchy.get(current)
            if parent:
                queue.append(parent)
        return None

    def _resolve_call(self, call: CallRef, binding_map: dict[str, str],
                      ast: FileAST, type_map: dict[str, str]) -> bool:
        """Try to resolve a single call. Returns True if resolved."""
        callee = call.callee_string

        # Strategy 1: Try table.method or table:method pattern (binding map + self-calls)
        for sep in (".", ":"):
            if sep in callee:
                parts = callee.split(sep, 1)
                table_name, method_name = parts[0], parts[1]

                # Check binding map
                if table_name in binding_map:
                    module = binding_map[table_name]
                    call.resolved_module = module
                    call.resolved_function = method_name
                    call.resolution_confidence = "binding"

                    # Item 8: If we resolved to a module but the method might be inherited,
                    # try to find the actual defining class
                    if table_name in type_map:
                        defining_class = self._resolve_via_inheritance(
                            type_map[table_name], method_name)
                        if defining_class and defining_class != type_map.get(table_name):
                            call.resolution_confidence = "inherited"
                    return True

                # Check if it's a self-call on the module table
                if ast.module_info and table_name == ast.module_info.table_var_name:
                    call.resolved_module = ast.module_name or ast.file_path
                    call.resolved_function = method_name
                    call.resolution_confidence = "self"
                    return True

                # Item 9: Type-inferred resolution — if table_name was assigned from
                # a constructor, resolve method on that class
                if table_name in type_map:
                    cls_name = type_map[table_name]
                    # Try to find the method via inheritance
                    defining_class = self._resolve_via_inheritance(cls_name, method_name)
                    if defining_class and defining_class in self.class_files:
                        call.resolved_module = defining_class
                        call.resolved_function = method_name
                        call.resolved_file_path = self.class_files[defining_class]
                        call.resolution_confidence = "type_inferred"
                        return True

                # Item 8: If table_name is a known class, try inheritance resolution
                if table_name in self.class_methods:
                    defining_class = self._resolve_via_inheritance(table_name, method_name)
                    if defining_class and defining_class in self.class_files:
                        call.resolved_module = defining_class
                        call.resolved_function = method_name
                        call.resolved_file_path = self.class_files[defining_class]
                        call.resolution_confidence = "inherited"
                        return True

        # Strategy 2: Direct binding map lookup for unqualified calls
        if callee in binding_map:
            call.resolved_module = binding_map[callee]
            call.resolved_function = callee
            call.resolution_confidence = "binding"
            return True

        # Strategy 3 (Item 2): Same-file resolution — if the callee matches a function
        # defined in the same file, resolve it there
        bare_name = callee.split(".")[-1].split(":")[-1]
        for func in ast.functions:
            func_base = func.name.split(".")[-1].split(":")[-1]
            if func_base == bare_name:
                call.resolved_module = ast.module_name or ast.file_path
                call.resolved_function = bare_name
                call.resolution_confidence = "same_file"
                return True

        # Strategy 4: Global symbol table lookup
        for module_name, file_path in self.global_symbols.items():
            if module_name.endswith(f".{callee}"):
                call.resolved_module = module_name.rsplit(".", 1)[0]
                call.resolved_function = callee
                call.resolution_confidence = "global_unique"
                return True

        # Strategy 5 (Item 3): Qualified name lookup
        for qn, file_path in self.qualified_symbols.items():
            if qn.endswith(f".{callee}"):
                call.resolved_module = qn.rsplit(".", 1)[0]
                call.resolved_function = callee
                call.resolved_file_path = file_path
                call.resolution_confidence = "qualified"
                return True

        return False

    def stats(self) -> dict:
        """Return resolution statistics."""
        return {
            "total_calls": self._total_calls,
            "already_resolved": self._already_resolved,
            "newly_resolved": self._newly_resolved,
            "unresolved": self._unresolved,
            "global_symbols": len(self.global_symbols),
            "qualified_symbols": len(self.qualified_symbols),
            "class_hierarchy_entries": len(self.class_hierarchy),
            "resolution_rate": (
                (self._already_resolved + self._newly_resolved) / self._total_calls * 100
                if self._total_calls > 0 else 0
            ),
        }
