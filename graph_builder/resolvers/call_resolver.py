"""Cross-file call resolution engine.

After all files are parsed, this engine:
  1. Builds a global symbol table (module_name.function → file_path)
  2. Resolves CALLS edges using require-to-variable bindings
  3. Produces resolution statistics

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

        # Resolution stats
        self._total_calls = 0
        self._already_resolved = 0
        self._newly_resolved = 0
        self._unresolved = 0

    def build_symbol_table(self):
        """Build the global symbol table from all parsed ASTs."""
        for file_path, ast in self.all_asts.items():
            if not ast.module_name:
                continue
            for func in ast.functions:
                if func.visibility == "public":
                    # Use the base function name (strip table prefix)
                    func_base = func.name.split(".")[-1].split(":")[-1]
                    key = f"{ast.module_name}.{func_base}"
                    self.global_symbols[key] = file_path

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

            for call in ast.calls:
                self._total_calls += 1

                if call.resolved_module:
                    self._already_resolved += 1
                    continue

                # Try to resolve using binding map
                resolved = self._resolve_call(call, binding_map, ast)
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

    def _resolve_call(self, call: CallRef, binding_map: dict[str, str],
                      ast: FileAST) -> bool:
        """Try to resolve a single call. Returns True if resolved."""
        callee = call.callee_string

        # Try table.method or table:method pattern
        for sep in (".", ":"):
            if sep in callee:
                parts = callee.split(sep, 1)
                table_name, method_name = parts[0], parts[1]

                # Check binding map
                if table_name in binding_map:
                    module = binding_map[table_name]
                    call.resolved_module = module
                    call.resolved_function = method_name
                    return True

                # Check if it's a self-call on the module table
                if ast.module_info and table_name == ast.module_info.table_var_name:
                    call.resolved_module = ast.module_name or ast.file_path
                    call.resolved_function = method_name
                    return True

        # Try global symbol table for unqualified calls
        # This handles cases where a function is imported directly
        if callee in binding_map:
            call.resolved_module = binding_map[callee]
            call.resolved_function = callee
            return True

        # Try to find in global symbols
        for module_name, file_path in self.global_symbols.items():
            if module_name.endswith(f".{callee}"):
                call.resolved_module = module_name.rsplit(".", 1)[0]
                call.resolved_function = callee
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
            "resolution_rate": (
                (self._already_resolved + self._newly_resolved) / self._total_calls * 100
                if self._total_calls > 0 else 0
            ),
        }
