"""File scanner: discovers source files in a repository, grouped by language."""

from __future__ import annotations

from pathlib import Path

from .config import Config


class FileScanner:
    """Walks the repository tree and yields (file_path, language) pairs."""

    def __init__(self, config: Config):
        self.root = Path(config.repo_root).resolve()
        self.extensions = config.extensions
        self.skip_dirs = config.skip_dirs

    def scan(self) -> list[tuple[str, str]]:
        """Return list of (absolute_file_path, language) for all source files."""
        results = []
        for ext, language in self.extensions.items():
            for f in self.root.rglob(f"*{ext}"):
                if self._should_skip(f):
                    continue
                results.append((str(f), language))
        return sorted(results)

    def scan_by_language(self) -> dict[str, list[str]]:
        """Return files grouped by language."""
        groups: dict[str, list[str]] = {}
        for file_path, language in self.scan():
            groups.setdefault(language, []).append(file_path)
        return groups

    def _should_skip(self, path: Path) -> bool:
        """Check if a file should be skipped based on directory rules."""
        parts = path.relative_to(self.root).parts
        for part in parts:
            if part in self.skip_dirs:
                return True
            # Wildcard patterns like *.egg-info
            for pattern in self.skip_dirs:
                if "*" in pattern and path.match(pattern):
                    return True
        return False

    def count(self) -> dict[str, int]:
        """Return file counts per language."""
        groups = self.scan_by_language()
        return {lang: len(files) for lang, files in groups.items()}
