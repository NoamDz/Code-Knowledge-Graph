"""JavaScript/Node.js import resolver.

Resolves require("./foo") and require("../utils") to actual file paths.
Bare module names (npm packages like "express") are left unresolved.

Handles:
  - Relative requires: require("./utils") → <dir>/utils.js
  - Parent requires: require("../models/user") → <parent>/models/user.js
  - Index files: require("./lib") → <dir>/lib/index.js
  - .js.erb files (Rails asset pipeline)

Usage:
    resolver = JsResolver("/path/to/repo")
    file_path = resolver.resolve("./utils", "/path/to/repo/src/main.js")
"""

from __future__ import annotations

from pathlib import Path


class JsResolver:
    """Resolves JavaScript require/import strings to file paths."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}
        self._build_index()

    def _build_index(self):
        """Index all .js and .js.erb files by relative path (without extension)."""
        skip = {"node_modules", ".git", "vendor", "dist", "build"}
        for ext in ("*.js", "*.js.erb"):
            for js_file in self.repo_root.rglob(ext):
                if any(s in js_file.parts for s in skip):
                    continue
                rel = str(js_file.relative_to(self.repo_root)).replace("\\", "/")
                # Index by relative path without extension
                key = rel
                if key.endswith(".js.erb"):
                    key = key[:-7]  # remove .js.erb
                elif key.endswith(".js"):
                    key = key[:-3]  # remove .js
                self._index[key] = str(js_file)

    def resolve(self, module_string: str, from_file: str | None = None) -> str | None:
        """Resolve a JS import/require to a file path.

        Args:
            module_string: The require/import string (e.g., "./utils", "express")
            from_file: The file containing the import (needed for relative resolution)

        Returns:
            The resolved file path, or None if not found (external package).
        """
        # Skip bare module names (npm packages)
        if not module_string.startswith("."):
            return None  # external package

        if not from_file:
            return None

        # Resolve relative to the importing file
        from_dir = Path(from_file).parent
        target = (from_dir / module_string).resolve()

        # Try extensions and index.js
        candidates = [
            target,
            target.with_suffix(".js"),
            target.parent / (target.name + ".js.erb"),
            target / "index.js",
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def stats(self) -> dict:
        return {"indexed_files": len(self._index)}
