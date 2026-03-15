"""File watcher: triggers incremental re-indexing when source files change.

Usage:
    python -m watcher.file_watcher /path/to/repo [--memgraph-uri bolt://localhost:7687]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph_builder.ingestion.writer import GraphWriter
from graph_builder.ingestion.incremental import reingest_file, EXTENSION_MAP


class CodeChangeHandler(FileSystemEventHandler):
    """Handles file change events and triggers re-indexing."""

    def __init__(self, writer: GraphWriter):
        self.writer = writer
        self._debounce: dict[str, float] = {}
        self._debounce_seconds = 1.0

    def _should_process(self, path: str) -> bool:
        """Check if the file is a tracked source file."""
        ext = Path(path).suffix
        return ext in EXTENSION_MAP

    def _debounced(self, path: str) -> bool:
        """Simple debounce to avoid processing rapid successive changes."""
        now = time.time()
        last = self._debounce.get(path, 0)
        if now - last < self._debounce_seconds:
            return False
        self._debounce[path] = now
        return True

    def on_modified(self, event):
        if event.is_directory:
            return
        if self._should_process(event.src_path) and self._debounced(event.src_path):
            print(f"[watcher] Modified: {event.src_path}")
            try:
                reingest_file(event.src_path, self.writer)
                print(f"[watcher] Re-indexed: {event.src_path}")
            except Exception as e:
                print(f"[watcher] Error re-indexing {event.src_path}: {e}")

    def on_created(self, event):
        if event.is_directory:
            return
        if self._should_process(event.src_path) and self._debounced(event.src_path):
            print(f"[watcher] Created: {event.src_path}")
            try:
                reingest_file(event.src_path, self.writer)
                print(f"[watcher] Indexed: {event.src_path}")
            except Exception as e:
                print(f"[watcher] Error indexing {event.src_path}: {e}")

    def on_deleted(self, event):
        if event.is_directory:
            return
        if self._should_process(event.src_path):
            print(f"[watcher] Deleted: {event.src_path}")
            try:
                self.writer.clear_file(event.src_path)
                print(f"[watcher] Cleared: {event.src_path}")
            except Exception as e:
                print(f"[watcher] Error clearing {event.src_path}: {e}")


def start_watcher(repo_root: str, memgraph_uri: str = "bolt://localhost:7687"):
    """Start the file watcher."""
    writer = GraphWriter(uri=memgraph_uri)
    handler = CodeChangeHandler(writer)
    observer = Observer()
    observer.schedule(handler, repo_root, recursive=True)

    print(f"[watcher] Watching {repo_root} for changes...")
    print(f"[watcher] Connected to Memgraph at {memgraph_uri}")
    print("[watcher] Press Ctrl+C to stop")

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[watcher] Stopping...")
        observer.stop()
    observer.join()
    writer.close()


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    uri = "bolt://localhost:7687"
    if "--memgraph-uri" in sys.argv:
        idx = sys.argv.index("--memgraph-uri")
        uri = sys.argv[idx + 1]
    start_watcher(repo, uri)
