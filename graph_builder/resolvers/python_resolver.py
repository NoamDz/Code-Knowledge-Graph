"""Python import resolver.

Resolves Python import strings to actual file paths in the repo.

Handles:
  - Absolute imports: 'mypackage.module' → '<repo>/mypackage/module.py'
  - Relative imports: '.utils' from file 'pkg/sub/main.py' → 'pkg/sub/utils.py'
  - Package imports: 'mypackage' → '<repo>/mypackage/__init__.py'

Usage:
    resolver = PythonResolver("/path/to/repo")
    file_path = resolver.resolve("mypackage.utils", "/path/to/repo/caller.py")
"""

from __future__ import annotations

from pathlib import Path


class PythonResolver:
    """Resolves Python import strings to file paths."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        self._index: dict[str, str] | None = None

    def _build_index(self) -> dict[str, str]:
        """Build module_string → file_path index for all Python files."""
        if self._index is not None:
            return self._index

        self._index = {}
        skip = {"node_modules", ".git", "__pycache__", ".mypy_cache",
                "vendor", "venv", ".venv", "dist", "build", ".tox", ".eggs"}

        for py_file in self.repo_root.rglob("*.py"):
            if any(s in py_file.parts for s in skip):
                continue

            try:
                rel = py_file.relative_to(self.repo_root)
            except ValueError:
                continue

            rel_str = str(rel).replace("\\", "/")
            file_path_str = str(py_file)

            # foo/bar/baz.py → foo.bar.baz
            module_name = rel_str.removesuffix(".py").replace("/", ".")

            # foo/bar/__init__.py → foo.bar
            if module_name.endswith(".__init__"):
                pkg_name = module_name.removesuffix(".__init__")
                self._index[pkg_name] = file_path_str

            self._index[module_name] = file_path_str

        return self._index

    def resolve(self, module_string: str, from_file: str | None = None) -> str | None:
        """Resolve a Python import string to a file path.

        Args:
            module_string: The import string (e.g., 'os.path', '.utils', '..models')
            from_file: The file containing the import (needed for relative imports)

        Returns:
            The resolved file path, or None if not found in the repo.
        """
        # Handle relative imports
        if module_string.startswith(".") and from_file:
            return self._resolve_relative(module_string, from_file)

        return self._resolve_absolute(module_string)

    def _resolve_relative(self, module_string: str, from_file: str) -> str | None:
        """Resolve a relative import like '.utils' or '..models'."""
        # Count leading dots
        dots = 0
        for ch in module_string:
            if ch == ".":
                dots += 1
            else:
                break

        remainder = module_string[dots:]

        try:
            from_path = Path(from_file)
            from_rel = from_path.relative_to(self.repo_root)
        except ValueError:
            return None

        # Go up `dots` levels from the importing file's directory
        # 1 dot = same package, 2 dots = parent package, etc.
        current = from_rel.parent
        for _ in range(dots - 1):
            current = current.parent

        if remainder:
            target = current / remainder.replace(".", "/")
        else:
            target = current

        # Try as a module file
        candidates = [
            self.repo_root / f"{target}.py",
            self.repo_root / target / "__init__.py",
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def _resolve_absolute(self, module_string: str) -> str | None:
        """Resolve an absolute import like 'mypackage.utils'."""
        index = self._build_index()

        # Direct lookup
        if module_string in index:
            return index[module_string]

        # Try as a path
        as_path = module_string.replace(".", "/")
        candidates = [
            self.repo_root / f"{as_path}.py",
            self.repo_root / as_path / "__init__.py",
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def stats(self) -> dict:
        index = self._build_index()
        return {
            "indexed_modules": len(index),
            "repo_root": str(self.repo_root),
        }
