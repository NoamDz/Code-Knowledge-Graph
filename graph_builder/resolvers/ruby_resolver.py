"""Ruby import resolver.

Resolves require/require_relative statements to file paths.

Handles:
  - require_relative "../lib/auth" -- relative to current file + .rb
  - require "json" -- stdlib, returns "__ruby_stdlib__"
  - require "my_app/models/user" -- search index for matching path
  - require "rails" -- external gem, returns None

Usage:
    resolver = RubyResolver("/path/to/repo")
    file_path = resolver.resolve("./helper", "/path/to/repo/lib/main.rb",
                                  import_type="require_relative")
"""

from __future__ import annotations

import re
from pathlib import Path

# Known Ruby stdlib modules (ships with Ruby, no gem install needed)
_RUBY_STDLIB = {
    "erb", "fileutils", "json", "yaml", "csv", "set", "ostruct",
    "pathname", "uri", "net/http", "net/https", "net/smtp",
    "socket", "openssl", "digest", "base64", "securerandom",
    "logger", "tempfile", "stringio", "pp", "optparse", "getoptlong",
    "find", "benchmark", "date", "time", "bigdecimal", "cgi",
    "drb", "fiddle", "monitor", "mutex_m", "observer", "open3",
    "open-uri", "rake", "rdoc", "readline", "shellwords",
    "singleton", "strscan", "timeout", "tmpdir", "webrick",
    "zlib", "forwardable", "abbrev", "English", "fiber",
    "io/console", "io/wait", "ipaddr", "resolv", "tsort",
    "weakref", "delegate", "mkmf", "racc", "psych",
}

# Common aliases for gems where the require name differs from gem name.
# Maps normalized (lowercase, underscored) require base -> True
_KNOWN_GEM_ALIASES: dict[str, str] = {
    "active_support": "activesupport",
    "rest_client": "rest-client",
    "restclient": "rest-client",
    "statsd": "statsd-instrument",
    "concurrent": "concurrent-ruby",
    "aws": "aws-sdk-s3",
}


class RubyResolver:
    """Resolves Ruby require/require_relative strings to file paths."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self._index: dict[str, str] = {}
        self._parsed_gems: set[str] = set()
        self._build_index()
        self._parse_gemfiles()

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

    def _parse_gemfiles(self):
        """Find all Gemfiles in the repo and extract gem names."""
        for gemfile in self.repo_root.rglob("Gemfile"):
            # Skip vendor directories
            if "vendor" in gemfile.parts or ".bundle" in gemfile.parts:
                continue
            try:
                with open(gemfile, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        match = re.match(r"^\s*gem\s+['\"]([^'\"]+)['\"]", line)
                        if match:
                            self._parsed_gems.add(match.group(1))
            except OSError:
                pass

    def is_gem(self, module_string: str) -> bool:
        """Check if a require string is a known gem (from Gemfile or aliases).

        Normalizes the base name (lowercase, replace '-' with '_') and checks
        against parsed Gemfile gems and known aliases.

        Args:
            module_string: e.g., "redis", "active_support/core_ext"

        Returns:
            True if the import is a known gem.
        """
        base = module_string.split("/")[0].split("::")[0]
        normalized = base.lower().replace("-", "_")

        # Check direct match in parsed gems (also normalized)
        normalized_gems = {g.lower().replace("-", "_") for g in self._parsed_gems}
        if normalized in normalized_gems:
            return True

        # Check known aliases
        if normalized in _KNOWN_GEM_ALIASES:
            return True

        return False

    def is_stdlib(self, module_string: str) -> bool:
        """Check if a require string is a Ruby stdlib module."""
        return module_string in _RUBY_STDLIB or module_string.split("/")[0] in _RUBY_STDLIB

    def resolve(self, module_string: str, from_file: str | None = None,
                import_type: str = "require") -> str | None:
        """Resolve a Ruby require/require_relative to a file path.

        Args:
            module_string: The require string (e.g., "../lib/auth", "json")
            from_file: The file containing the require (needed for require_relative)
            import_type: "require" or "require_relative"

        Returns:
            The resolved file path, "__ruby_stdlib__" for stdlib, or None
            if not found (external gem).
        """
        if import_type == "require_relative" and from_file:
            try:
                from_dir = Path(from_file).resolve().parent
                target = (from_dir / module_string).resolve()
                candidate = target.with_suffix(".rb") if not target.suffix else target
                if candidate.exists():
                    return str(candidate)
                if target.exists() and target.is_file():
                    return str(target)
            except (OSError, ValueError):
                pass
            return None

        # Check if it's a known stdlib module
        if self.is_stdlib(module_string):
            return "__ruby_stdlib__"

        # require "name" -- try index lookup (exact match)
        if module_string in self._index:
            return self._index[module_string]

        # Suffix match: require "models/user" should match "app/models/user"
        for key, path in self._index.items():
            if key.endswith(f"/{module_string}") or key == module_string:
                return path

        # Check if it's a known gem before returning None
        if self.is_gem(module_string):
            return "__ruby_gem__"

        return None  # truly unresolved

    def resolve_dynamic_loading(self, all_asts: dict) -> list[dict]:
        """Detect Dir.glob/Dir.entries/class_eval loading patterns and return edges.

        Returns a list of dicts: {"source": file_path, "target": file_path, "load_type": str}
        """
        edges: list[dict] = []

        for file_path, ast in all_asts.items():
            if ast.language != "ruby":
                continue

            has_dir_glob = False
            has_class_eval = False

            for call in ast.calls:
                callee = call.callee_string.lower()
                # Dir.glob, Dir.entries, Dir["pattern"]
                if "dir.glob" in callee or "dir.entries" in callee:
                    has_dir_glob = True
                # scan_for_* method definitions containing Dir.glob
                if "scan_for_" in callee:
                    has_dir_glob = True
                # class_eval(IO.read(...))
                if "class_eval" in callee:
                    has_class_eval = True

            if has_dir_glob:
                # Find all .rb files in subdirectories relative to this file
                source_dir = Path(file_path).parent
                for rb_file in source_dir.rglob("*.rb"):
                    rb_str = str(rb_file)
                    if rb_str == file_path:
                        continue
                    edges.append({
                        "source": file_path,
                        "target": rb_str,
                        "load_type": "dir_glob",
                    })

            if has_class_eval:
                # class_eval(IO.read(entry)) — loading .rb files dynamically
                # Mark as dynamic loader; specific targets resolved at integration time
                edges.append({
                    "source": file_path,
                    "target": file_path,  # self-reference as marker
                    "load_type": "class_eval",
                })

        return edges

    def stats(self) -> dict:
        return {
            "indexed_files": len(self._index),
            "parsed_gems": len(self._parsed_gems),
        }
