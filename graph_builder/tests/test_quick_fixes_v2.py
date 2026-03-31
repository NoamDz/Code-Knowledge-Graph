"""Tests for the quick-fixes-v2 bundle (Tasks 4-7).

Run with: python -m pytest graph_builder/tests/test_quick_fixes_v2.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"
GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"
RUBY_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"

from graph_builder.resolvers.python_resolver import PythonResolver


# ---------------------------------------------------------------
# Task 4: Python package root detection + stdlib classification
# ---------------------------------------------------------------

class TestPythonResolver:
    """Test Python package root detection and stdlib classification."""

    def test_is_stdlib_recognizes_common_modules(self):
        """is_stdlib should recognize os, sys, json, logging, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os") is True
        assert resolver.is_stdlib("sys") is True
        assert resolver.is_stdlib("json") is True
        assert resolver.is_stdlib("logging") is True
        assert resolver.is_stdlib("collections") is True
        assert resolver.is_stdlib("pathlib") is True
        assert resolver.is_stdlib("typing") is True
        assert resolver.is_stdlib("datetime") is True
        assert resolver.is_stdlib("re") is True
        assert resolver.is_stdlib("unittest") is True

    def test_is_stdlib_rejects_third_party(self):
        """is_stdlib should reject known third-party packages."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("flask") is False
        assert resolver.is_stdlib("django") is False
        assert resolver.is_stdlib("requests") is False
        assert resolver.is_stdlib("numpy") is False
        assert resolver.is_stdlib("boto3") is False

    def test_is_stdlib_handles_submodules(self):
        """is_stdlib should recognize os.path, collections.abc, etc."""
        resolver = PythonResolver(str(PY_FIXTURES))
        assert resolver.is_stdlib("os.path") is True
        assert resolver.is_stdlib("collections.abc") is True
        assert resolver.is_stdlib("http.server") is True
        assert resolver.is_stdlib("urllib.parse") is True
        assert resolver.is_stdlib("email.mime.text") is True

    def test_find_package_roots(self):
        """_find_package_roots should detect nested_pkg as a package root."""
        resolver = PythonResolver(str(PY_FIXTURES))
        roots = resolver._find_package_roots()
        # nested_pkg/ contains __init__.py, so it should be detected
        root_dirs = {str(v) for v in roots.values()}
        nested_pkg_dir = str((PY_FIXTURES / "nested_pkg").resolve())
        has_nested = any(nested_pkg_dir in d for d in root_dirs)
        assert has_nested, f"Should detect nested_pkg as package root, got: {root_dirs}"

    def test_package_root_resolution(self):
        """Absolute import 'services.models' should resolve relative to package root."""
        resolver = PythonResolver(str(PY_FIXTURES / "nested_pkg"))
        handler_file = str(PY_FIXTURES / "nested_pkg" / "services" / "handler.py")
        result = resolver.resolve("services.models", handler_file)
        assert result is not None, "services.models should resolve within nested_pkg"
        assert "models.py" in result

    def test_resolver_stats_include_package_roots(self):
        """stats() should include package_roots count."""
        resolver = PythonResolver(str(PY_FIXTURES))
        stats = resolver.stats()
        assert "package_roots" in stats, f"stats should include package_roots, got: {stats}"
