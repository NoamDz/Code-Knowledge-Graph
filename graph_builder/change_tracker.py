"""Change tracking for incremental graph updates.

Supports two modes:
  - Git-based: uses `git diff` to find changed files since a ref
  - Hash-based: compares file content hashes against a state file
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


class GitChangeTracker:
    """Uses git to detect changed files since a given ref."""

    def __init__(self, repo_root: str):
        self.repo_root = repo_root

    def get_changed_files(self, since_ref: str = "HEAD~1") -> list[str]:
        """Return files changed since the given git ref."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_ref, "HEAD"],
                capture_output=True, text=True, cwd=self.repo_root,
            )
            if result.returncode != 0:
                return []
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            return [str(Path(self.repo_root) / f) for f in files]
        except FileNotFoundError:
            return []

    def get_uncommitted_changes(self) -> list[str]:
        """Return files with uncommitted changes."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True, text=True, cwd=self.repo_root,
            )
            staged = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True, text=True, cwd=self.repo_root,
            )
            files = set()
            for output in (result.stdout, staged.stdout):
                for f in output.strip().split("\n"):
                    if f.strip():
                        files.add(str(Path(self.repo_root) / f.strip()))
            return sorted(files)
        except FileNotFoundError:
            return []


class HashChangeTracker:
    """Fallback: compare file content hashes against saved state."""

    def __init__(self, state_file: str = ".graph_state.json"):
        self.state_file = Path(state_file)
        self.state: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def get_changed_files(self, file_paths: list[str]) -> list[str]:
        """Return files whose content has changed since last check."""
        changed = []
        for f in file_paths:
            path = Path(f)
            if not path.exists():
                if f in self.state:
                    changed.append(f)  # deleted file
                continue
            h = hashlib.md5(path.read_bytes()).hexdigest()
            if self.state.get(f) != h:
                changed.append(f)
                self.state[f] = h
        self._save()
        return changed

    def mark_current(self, file_paths: list[str]):
        """Update state for the given files without reporting changes."""
        for f in file_paths:
            path = Path(f)
            if path.exists():
                self.state[f] = hashlib.md5(path.read_bytes()).hexdigest()
        self._save()
