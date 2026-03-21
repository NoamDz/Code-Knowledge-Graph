"""Ruby import resolver.

Resolves require/require_relative statements to file paths.

Handles:
  - require_relative "../lib/auth" -- relative to current file + .rb
  - require "json" -- external gem, returns None
  - require "my_app/models/user" -- search index for matching path

Usage:
    resolver = RubyResolver("/path/to/repo")
    file_path = resolver.resolve("./helper", "/path/to/repo/lib/main.rb",
                                  import_type="require_relative")
"""

from __future__ import annotations

from pathlib import Path


class RubyResolver:
    """Resolves Ruby require/require_relative strings to file paths."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}
        self._build_index()

    def _build_index(self):
        """Index all .rb files by relative path (without .rb extension)."""
        skip = {"node_modules", ".git", "vendor", "dist", "build", ".bundle"}
        for rb_file in self.repo_root.rglob("*.rb"):
            if any(s in rb_file.parts for s in skip):
                continue
            rel = str(rb_file.relative_to(self.repo_root)).replace("\\", "/")
            # Index by relative path without .rb
            key = rel.removesuffix(".rb")
            self._index[key] = str(rb_file)

    def resolve(self, module_string: str, from_file: str | None = None,
                import_type: str = "require") -> str | None:
        """Resolve a Ruby require/require_relative to a file path.

        Args:
            module_string: The require string (e.g., "../lib/auth", "json")
            from_file: The file containing the require (needed for require_relative)
            import_type: "require" or "require_relative"

        Returns:
            The resolved file path, or None if not found (external gem).
        """
        if import_type == "require_relative" and from_file:
            from_dir = Path(from_file).parent
            target = (from_dir / module_string).resolve()
            candidate = target.with_suffix(".rb") if not target.suffix else target
            if candidate.exists():
                return str(candidate)
            # Also try without adding suffix if the path already ends in .rb
            if target.exists():
                return str(target)
            return None

        # require "name" -- try index lookup (exact match)
        if module_string in self._index:
            return self._index[module_string]

        # Suffix match: require "models/user" should match "app/models/user"
        for key, path in self._index.items():
            if key.endswith(f"/{module_string}") or key == module_string:
                return path

        return None  # external gem

    def stats(self) -> dict:
        return {"indexed_files": len(self._index)}
