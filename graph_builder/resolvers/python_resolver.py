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


# Python standard library top-level packages (Python 3.10+)
# Used for classification (not resolution -- stdlib imports are always "external")
PYTHON_STDLIB_TOP = frozenset({
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
    "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
    "binhex", "bisect", "builtins", "bz2",
    "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
    "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "cProfile", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest",
    "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
    "fractions", "ftplib", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "grp", "gzip",
    "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect",
    "io", "ipaddress", "itertools",
    "json",
    "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma",
    "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
    "modulefinder", "multiprocessing",
    "netrc", "nis", "nntplib", "numbers",
    "operator", "optparse", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
    "pydoc",
    "queue", "quopri",
    "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy",
    "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "sunau", "symtable",
    "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing",
    "unicodedata", "unittest", "urllib", "uu", "uuid",
    "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref",
    "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    # Also common aliases/sub-packages that appear as top-level
    "_thread", "__future__",
})


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

        # Try absolute resolution first
        result = self._resolve_absolute(module_string)
        if result:
            return result

        # For bare-name imports (no dots), try same-directory resolution
        if "." not in module_string and from_file:
            return self._resolve_same_directory(module_string, from_file)

        return None

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

        # Suffix match: find any indexed module that ends with this string.
        # This handles cases where repo_root includes parent dirs and actual
        # imports are relative to a sub-package root (e.g., import
        # "aggregator.models.task" matching "deferrer.aggregator.aggregator.models.task").
        suffix_dot = f".{module_string}"
        for indexed_module, file_path in index.items():
            if indexed_module.endswith(suffix_dot) or indexed_module == module_string:
                return file_path

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

    def _resolve_same_directory(self, module_string: str, from_file: str) -> str | None:
        """Resolve a bare import by looking in the same directory.

        Handles flat Python services that use:
            from config import Config  (config.py in same dir)
        """
        from_dir = Path(from_file).parent
        candidate = from_dir / f"{module_string}.py"
        if candidate.exists():
            return str(candidate)
        candidate_pkg = from_dir / module_string / "__init__.py"
        if candidate_pkg.exists():
            return str(candidate_pkg)
        return None

    def is_stdlib(self, module_string: str) -> bool:
        """Check if a module string is a Python standard library module.

        Args:
            module_string: e.g., "os", "os.path", "collections.abc"

        Returns:
            True if the top-level package is in the Python stdlib.
        """
        top = module_string.split(".")[0]
        return top in PYTHON_STDLIB_TOP

    def _find_package_roots(self) -> dict[str, Path]:
        """Find the topmost __init__.py for each package tree.

        Walks upward from each .py file to find the highest directory
        that still contains __init__.py. This identifies package roots
        for resolving absolute imports.

        Returns:
            Dict mapping .py file path string -> topmost package root Path.
        """
        skip = {"node_modules", ".git", "__pycache__", ".mypy_cache",
                "vendor", "venv", ".venv", "dist", "build", ".tox", ".eggs"}
        roots: dict[str, Path] = {}
        for py_file in self.repo_root.rglob("*.py"):
            if any(s in py_file.parts for s in skip):
                continue
            current = py_file.parent
            topmost = None
            while current != self.repo_root and current != current.parent:
                if (current / "__init__.py").exists():
                    topmost = current
                else:
                    break
                current = current.parent
            if topmost:
                roots[str(py_file)] = topmost
        return roots

    def stats(self) -> dict:
        index = self._build_index()
        roots = self._find_package_roots()
        return {
            "indexed_modules": len(index),
            "repo_root": str(self.repo_root),
            "package_roots": len(set(str(v) for v in roots.values())),
        }
