"""Go import resolver.

Go imports are package paths like "github.com/org/repo/internal/pkg".
Resolution: find directories containing .go files with matching package declarations.

Also handles:
- Same-package linking: Go files in the same directory share a package scope.
- Stdlib classification: identifies Go standard library imports.
"""

from __future__ import annotations

from pathlib import Path

from graph_builder.parsers.base import FileAST


# Go standard library top-level packages (Go 1.22+)
GO_STDLIB_PACKAGES = frozenset({
    "archive", "bufio", "bytes", "cmp", "compress", "container", "context",
    "crypto", "database", "debug", "embed", "encoding", "errors", "expvar",
    "flag", "fmt", "go", "hash", "html", "image", "index", "io", "iter",
    "log", "maps", "math", "mime", "net", "os", "path", "plugin", "reflect",
    "regexp", "runtime", "slices", "sort", "strconv", "strings", "sync",
    "syscall", "testing", "text", "time", "unicode", "unsafe", "internal",
})


class GoResolver:
    """Resolves Go import paths to file paths within the repository."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        # Map of package_path_suffix -> directory containing .go files
        self._index: dict[str, str] = {}
        # Map of directory -> list of .go file paths (for same-package linking)
        self._dir_files: dict[str, list[str]] = {}
        self._build_index()

    def _build_index(self):
        """Build an index of Go package directories and per-directory file lists."""
        for go_file in self.repo_root.rglob("*.go"):
            # Skip vendor / node_modules / .git
            parts = go_file.relative_to(self.repo_root).parts
            if any(p in ("vendor", "node_modules", ".git") for p in parts):
                continue

            dir_path = str(go_file.parent)
            # Use the relative directory path as potential import suffix
            rel_dir = str(go_file.parent.relative_to(self.repo_root)).replace("\\", "/")

            # Register this directory for suffix-based import resolution
            if rel_dir not in self._index:
                self._index[rel_dir] = dir_path

            # Track all .go files per directory for same-package linking
            self._dir_files.setdefault(dir_path, []).append(str(go_file))

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

    def get_package_siblings(self, file_path: str) -> list[str]:
        """Return all other .go files in the same directory (same Go package).

        Excludes the file itself and test files (*_test.go).

        Args:
            file_path: absolute path to a .go file

        Returns:
            List of absolute paths to sibling .go files.
        """
        fp = Path(file_path).resolve()
        dir_path = str(fp.parent)
        all_files = self._dir_files.get(dir_path, [])
        siblings = []
        for f in all_files:
            f_path = Path(f)
            if f_path.resolve() == fp:
                continue
            if f_path.name.endswith("_test.go"):
                continue
            siblings.append(str(f_path))
        return siblings

    def is_stdlib(self, import_path: str) -> bool:
        """Check if an import path is a Go standard library package.

        The check looks at the first path segment of the import.
        E.g., "net/http" -> first segment is "net" which is in the stdlib set.

        Args:
            import_path: e.g., "fmt", "net/http", "encoding/json"

        Returns:
            True if the import is a Go stdlib package.
        """
        first_segment = import_path.split("/")[0]
        return first_segment in GO_STDLIB_PACKAGES

    def stats(self) -> dict:
        return {
            "indexed_packages": len(self._index),
            "indexed_directories": len(self._dir_files),
        }


def resolve_go_interfaces(all_asts: dict) -> list[tuple[str, str]]:
    """Match Go structs to interfaces using structural typing.

    Compares interface method sets against struct method sets.
    A struct implements an interface if the interface's method set
    is a subset of the struct's method set.

    Args:
        all_asts: file_path -> FileAST mapping

    Returns:
        List of (struct_name, interface_name) tuples.
    """
    interfaces: dict[str, set[str]] = {}   # name -> method names
    structs: dict[str, set[str]] = {}       # name -> method names

    for file_path, ast in all_asts.items():
        if ast.language != "go":
            continue
        for cls in ast.classes:
            if cls.is_interface:
                interfaces[cls.name] = set(cls.methods)
            else:
                structs[cls.name] = set(cls.methods)

    implements: list[tuple[str, str]] = []
    for iface_name, iface_methods in interfaces.items():
        if not iface_methods:
            continue  # Skip empty interfaces
        for struct_name, struct_methods in structs.items():
            if iface_methods.issubset(struct_methods):
                implements.append((struct_name, iface_name))

    return implements
