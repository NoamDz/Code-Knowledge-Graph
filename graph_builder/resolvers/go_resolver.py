"""Go import resolver.

Go imports are package paths like "github.com/org/repo/internal/pkg".
Resolution: find directories containing .go files with matching package declarations.
"""

from __future__ import annotations

from pathlib import Path

from graph_builder.parsers.base import FileAST


class GoResolver:
    """Resolves Go import paths to file paths within the repository."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        # Map of package_path_suffix → directory containing .go files
        self._index: dict[str, str] = {}
        self._build_index()

    def _build_index(self):
        """Build an index of Go package directories."""
        for go_file in self.repo_root.rglob("*.go"):
            # Skip test files and vendor
            parts = go_file.relative_to(self.repo_root).parts
            if any(p in ("vendor", "node_modules", ".git") for p in parts):
                continue

            dir_path = str(go_file.parent)
            # Use the relative directory path as potential import suffix
            rel_dir = str(go_file.parent.relative_to(self.repo_root)).replace("\\", "/")

            # Register this directory — any import path ending with this relative path
            # could resolve here
            if rel_dir not in self._index:
                self._index[rel_dir] = dir_path

    def resolve(self, import_path: str, from_file: str | None = None) -> str | None:
        """Resolve a Go import path to a .go file path.

        Args:
            import_path: e.g., "github.com/org/repo/internal/auth"
            from_file: (unused) the file containing the import, for API consistency

        Returns:
            Absolute path to a representative .go file, or None if not found.
        """
        # Try progressively shorter suffixes of the import path
        parts = import_path.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if suffix in self._index:
                dir_path = Path(self._index[suffix])
                # Return the first non-test .go file in this directory
                go_files = sorted(dir_path.glob("*.go"))
                for gf in go_files:
                    if not gf.name.endswith("_test.go"):
                        return str(gf)
                # If only test files, return the first one
                if go_files:
                    return str(go_files[0])
                return self._index[suffix]

        return None

    def stats(self) -> dict:
        return {
            "indexed_packages": len(self._index),
        }
