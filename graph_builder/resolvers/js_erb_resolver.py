"""JS ERB render-chain resolver.

Detects the inclusion hierarchy in .js.erb files by parsing ERB template
render() calls. These files are assembled at build time by a Ruby generator
that uses env["template"].render("filename.js.erb", env) to concatenate
JavaScript files into a single IIFE bundle.

This resolver:
  1. Reads raw .js.erb file content (BEFORE ERB stripping)
  2. Extracts all render("filename", env) calls via regex
  3. Resolves each filename to a file path
  4. Detects the collector loop pattern in container.js.erb
  5. Returns INCLUDES edges (source_file -> included_file)

Usage:
    resolver = JsErbResolver("/path/to/repo")
    edges = resolver.resolve_all(all_asts)
"""

from __future__ import annotations

import re
from pathlib import Path

from ..parsers.base import FileAST

# Matches: env["template"].render("filename.js.erb", env)
# Handles both single and double quotes around "template" and the filename.
ERB_RENDER_PATTERN = re.compile(
    r'''env\[['"]template['"]\]\.render\(\s*['"]([^'"]+)['"]\s*,'''
)

# Matches the collector loop: env['collectors_rendered'].each
COLLECTOR_LOOP_PATTERN = re.compile(
    r'''env\[['"]collectors_rendered['"]\]\.each'''
)


class JsErbResolver:
    """Resolves ERB render-chain inclusions in .js.erb files."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._file_index: dict[str, str] = {}  # filename -> full path
        self._build_file_index()

    def _build_file_index(self):
        """Index all .js and .js.erb files by their basename for resolution."""
        skip = {"node_modules", ".git", "vendor", "dist", "build"}
        for ext in ("*.js", "*.js.erb"):
            for js_file in self.repo_root.rglob(ext):
                if any(s in js_file.parts for s in skip):
                    continue
                # Index by filename (basename)
                name = js_file.name
                full_path = str(js_file)
                # First occurrence wins; collisions handled in resolve_filename
                if name not in self._file_index:
                    self._file_index[name] = full_path

    def extract_render_calls(self, file_path: str) -> list[str]:
        """Extract all rendered filenames from a .js.erb file's raw content.

        Args:
            file_path: Path to the .js.erb file

        Returns:
            List of rendered filenames (e.g., ["net.js.erb", "utils.js"])
        """
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, IOError):
            return []

        return ERB_RENDER_PATTERN.findall(content)

    def has_collector_loop(self, file_path: str) -> bool:
        """Check if the file contains the collectors_rendered.each loop."""
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, IOError):
            return False

        return bool(COLLECTOR_LOOP_PATTERN.search(content))

    def resolve_filename(self, filename: str, from_file: str) -> str | None:
        """Resolve a rendered filename to a full file path.

        Search order:
          1. Same directory as the rendering file
          2. Global file index (all known JS/JS.ERB files)

        Args:
            filename: The filename from the render() call (e.g., "net.js.erb")
            from_file: The file containing the render() call

        Returns:
            Full file path, or None if not found.
        """
        from_dir = Path(from_file).parent

        # 1. Check same directory
        candidate = from_dir / filename
        if candidate.exists():
            return str(candidate.resolve())

        # 2. If filename contains a path separator, try relative to repo root
        if "/" in filename:
            candidate = self.repo_root / filename
            if candidate.exists():
                return str(candidate.resolve())

        # 3. Search the global file index by basename
        basename = Path(filename).name
        if basename in self._file_index:
            return self._file_index[basename]

        return None

    def find_collector_entry_points(self, all_asts: dict[str, FileAST]) -> list[str]:
        """Find collector entry-point files for the collectors_rendered loop.

        Collector entry points are .js.erb files inside */templates/ directories
        that define collector behavior. These are the top-level files loaded by
        the Ruby generator's snippet['collectors'].each loop.

        Returns:
            List of file paths for collector entry-point templates.
        """
        collectors = []
        for file_path, ast in all_asts.items():
            if ast.language != "javascript":
                continue
            # Collector entry points live in templates/ directories
            # and are .js.erb files
            normalized = file_path.replace("\\", "/")
            if "/templates/" in normalized and file_path.endswith(".js.erb"):
                collectors.append(file_path)
        return collectors

    def resolve_all(self, all_asts: dict[str, FileAST]) -> list[dict]:
        """Resolve all ERB render-chain inclusions across all JS files.

        Returns list of edge dicts:
            [{"source_file": "...", "target_file": "...", "type": "render"}]
        """
        edges = []
        container_file = None

        for file_path, ast in all_asts.items():
            if ast.language != "javascript":
                continue
            if not file_path.endswith(".erb"):
                continue

            # Extract render calls from raw file content
            rendered_filenames = self.extract_render_calls(file_path)

            for filename in rendered_filenames:
                target = self.resolve_filename(filename, file_path)
                if target:
                    edges.append({
                        "source_file": file_path,
                        "target_file": target,
                        "type": "render",
                    })

            # Detect the collector loop container
            if self.has_collector_loop(file_path):
                container_file = file_path

        # If we found a container with collectors_rendered.each,
        # create INCLUDES edges to all collector entry points
        if container_file:
            collector_files = self.find_collector_entry_points(all_asts)
            for coll_path in collector_files:
                # Don't include the container itself
                if coll_path == container_file:
                    continue
                # Don't duplicate edges already created by explicit render() calls
                existing_targets = {e["target_file"] for e in edges
                                    if e["source_file"] == container_file}
                if coll_path not in existing_targets:
                    edges.append({
                        "source_file": container_file,
                        "target_file": coll_path,
                        "type": "collector_loop",
                    })

        return edges

    def stats(self) -> dict:
        return {"indexed_files": len(self._file_index)}
