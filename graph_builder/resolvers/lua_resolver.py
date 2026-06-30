"""Lua module resolver.

Resolves require("resty.auth") to an actual file path using:
  1. lua_package_path from nginx.conf (converted to glob patterns)
  2. A module_name → file_path index built at startup
  3. Fallback heuristics for common patterns

Usage:
    resolver = LuaResolver(
        package_paths=["/srv/app/lua/?.lua", "/srv/app/lua/?/init.lua"],
        repo_root="/srv/app"
    )
    file_path = resolver.resolve("resty.auth")  # → "/srv/app/lua/resty/auth.lua"
"""

from __future__ import annotations

from pathlib import Path


class LuaResolver:
    """Resolves Lua require() strings to file paths."""

    def __init__(self, package_paths: list[str], repo_root: str,
                 source_roots: tuple[str, ...] = ("src",)):
        self.repo_root = Path(repo_root)
        self.package_paths = package_paths
        self.source_roots = tuple(source_roots)
        self.module_index: dict[str, str] = {}
        self._build_index()
        self.file_to_module: dict[str, str] = {}
        self.path_suffix_index: dict[str, str] = {}

    def _build_index(self):
        """Build module_name → file_path lookup for all Lua files in the repo."""
        for lua_file in self.repo_root.rglob("*.lua"):
            # Skip common vendor/dependency directories
            parts = lua_file.parts
            if any(skip in parts for skip in ("node_modules", ".git", "vendor")):
                continue

            # Try each package_path template to derive a module name
            for template in self.package_paths:
                module_name = self._file_to_module(lua_file, template)
                if module_name:
                    self.module_index[module_name] = str(lua_file)

            # Also index by simple relative path conversion
            try:
                rel = lua_file.relative_to(self.repo_root)
                simple_name = str(rel).removesuffix(".lua").removesuffix("/init").replace("/", ".")
                if simple_name not in self.module_index:
                    self.module_index[simple_name] = str(lua_file)
            except ValueError:
                pass

    def _file_to_module(self, file_path: Path, template: str) -> str | None:
        """Convert a file path to a module name using a package_path template.

        Template example: "/srv/app/lua/?.lua"
        File: "/srv/app/lua/resty/auth.lua"
        Result: "resty.auth"
        """
        # Clean up template
        template = template.strip()
        if not template or template == ";;":
            return None

        # Replace ? with a capture pattern
        # e.g., "/srv/app/lua/?.lua" → we need to match the ? part
        if "?" not in template:
            return None

        prefix, suffix = template.split("?", 1)
        file_str = str(file_path)

        if not file_str.startswith(prefix) or not file_str.endswith(suffix):
            return None

        # Extract the ? part
        captured = file_str[len(prefix):-len(suffix)] if suffix else file_str[len(prefix):]

        # Convert path separators to dots
        module_name = captured.replace("/", ".").replace("\\", ".")
        return module_name

    def module_name_for_file(self, file_path: str) -> str | None:
        """Derive the require_version dotted module name for a Lua file.

        Inverse of require_version path mapping: drop the leading source-root
        segment (e.g. "src"), drop "/init.lua" or ".lua", join with dots.
            <repo>/src/ato/collectors/ipp/init.lua -> "ato.collectors.ipp"
            <repo>/src/common/base/lua/store.lua   -> "common.base.lua.store"
        """
        parts = list(Path(file_path).parts)
        # Take everything after the LAST leading-style source-root segment.
        cut = None
        for i, p in enumerate(parts):
            if p in self.source_roots:
                cut = i
        if cut is not None:
            parts = parts[cut + 1:]
        else:
            try:
                parts = list(Path(file_path).relative_to(self.repo_root).parts)
            except ValueError:
                pass
        if not parts:
            return None
        last = parts[-1]
        if last == "init.lua":
            parts = parts[:-1]
        elif last.endswith(".lua"):
            parts[-1] = last[:-4]
        parts = [p for p in parts if p]
        return ".".join(parts) if parts else None

    def resolve(self, module_string: str, from_file: str | None = None) -> str | None:
        """Resolve a require() string to a file path.

        Args:
            module_string: The require() string (e.g., "resty.redis")
            from_file: (unused) the file containing the import, for API consistency

        Returns the file path if found in the repo, None if external.
        """
        # Direct lookup
        if module_string in self.module_index:
            return self.module_index[module_string]

        # Try with dots → slashes and search
        as_path = module_string.replace(".", "/")
        for lua_file in self.repo_root.rglob("*.lua"):
            if str(lua_file).endswith(as_path + ".lua"):
                return str(lua_file)
            if str(lua_file).endswith(as_path + "/init.lua"):
                return str(lua_file)

        return None

    def resolve_all(self, module_strings: list[str]) -> dict[str, str | None]:
        """Resolve multiple module strings at once."""
        return {mod: self.resolve(mod) for mod in module_strings}

    def get_index(self) -> dict[str, str]:
        """Return the complete module name → file path index."""
        return dict(self.module_index)

    def stats(self) -> dict:
        """Return resolver statistics."""
        return {
            "indexed_modules": len(self.module_index),
            "package_paths": len(self.package_paths),
            "repo_root": str(self.repo_root),
        }
