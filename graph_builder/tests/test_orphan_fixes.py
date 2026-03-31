"""Tests for orphan-file / import-resolution fixes.

Run with: python -m pytest graph_builder/tests/test_orphan_fixes.py -v
"""
from __future__ import annotations

from pathlib import Path

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.go_resolver import GoResolver
from graph_builder.resolvers.python_resolver import PythonResolver
from graph_builder.resolvers.ruby_resolver import RubyResolver

GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"
LUA_FIXTURES = Path(__file__).parent / "fixtures" / "lua"
PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"
RB_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"


# ---------------------------------------------------------------------------
# Ruby stdlib recognition
# ---------------------------------------------------------------------------

def test_ruby_stdlib_classified():
    """Ruby stdlib imports like 'erb' and 'fileutils' should resolve."""
    resolver = RubyResolver(str(RB_FIXTURES))
    assert resolver.resolve("erb") == "__ruby_stdlib__"
    assert resolver.resolve("fileutils") == "__ruby_stdlib__"
    assert resolver.resolve("json") == "__ruby_stdlib__"
    assert resolver.resolve("yaml") == "__ruby_stdlib__"
    assert resolver.resolve("net/http") == "__ruby_stdlib__"


def test_ruby_stdlib_method():
    """is_stdlib should identify Ruby stdlib modules."""
    resolver = RubyResolver(str(RB_FIXTURES))
    assert resolver.is_stdlib("erb")
    assert resolver.is_stdlib("json")
    assert resolver.is_stdlib("net/http")
    assert not resolver.is_stdlib("rails")
    assert not resolver.is_stdlib("nokogiri")


def test_ruby_gem_returns_none():
    """Unknown gems should return None (not stdlib sentinel).

    Note: gems listed in fixtures/ruby/Gemfile now return '__ruby_gem__'
    instead of None. Only truly unknown gems return None.
    """
    resolver = RubyResolver(str(RB_FIXTURES))
    assert resolver.resolve("rails") is None  # not in Gemfile
    assert resolver.resolve("nokogiri") is None  # not in Gemfile
    # rspec IS in the Gemfile fixture, so it returns __ruby_gem__
    assert resolver.resolve("rspec") == "__ruby_gem__"


# ---------------------------------------------------------------------------
# Ruby require_relative
# ---------------------------------------------------------------------------

def test_ruby_require_relative():
    """require_relative should resolve relative paths to .rb files."""
    resolver = RubyResolver(str(RB_FIXTURES))
    main_file = str(RB_FIXTURES / "require_resolve" / "main.rb")
    result = resolver.resolve("./helper", from_file=main_file,
                              import_type="require_relative")
    assert result is not None
    assert result.endswith("helper.rb")


def test_ruby_require_relative_no_from_file():
    """require_relative without from_file should return None."""
    resolver = RubyResolver(str(RB_FIXTURES))
    result = resolver.resolve("./helper", from_file=None,
                              import_type="require_relative")
    assert result is None


# ---------------------------------------------------------------------------
# Go same-package linking
# ---------------------------------------------------------------------------

def test_go_same_package_files():
    """Files in the same Go package directory should be linked."""
    resolver = GoResolver(str(GO_FIXTURES))
    siblings = resolver.get_package_siblings(str(GO_FIXTURES / "same_package" / "main.go"))
    sibling_names = [Path(s).name for s in siblings]
    assert "handler.go" in sibling_names
    assert "main.go" not in sibling_names


def test_go_stdlib_classification():
    """Go stdlib imports should be classified."""
    resolver = GoResolver(str(GO_FIXTURES))
    assert resolver.is_stdlib("fmt")
    assert resolver.is_stdlib("context")
    assert resolver.is_stdlib("net/http")
    assert resolver.is_stdlib("encoding/json")
    assert not resolver.is_stdlib("github.com/go-redis/redis/v8")


# ---------------------------------------------------------------------------
# Lua mission dispatch detection
# ---------------------------------------------------------------------------

def test_mission_dispatch_detected():
    """missioner.add_mission('task_name') should be detected in warnings."""
    ast = parse_lua_file(str(LUA_FIXTURES / "mission_caller.lua"))
    mission_warnings = [w for w in ast.warnings if w.startswith("mission:")]
    assert len(mission_warnings) >= 2

    task_names = [w.split(":")[1] for w in mission_warnings]
    assert "pts_run" in task_names
    assert "model_prediction" in task_names


def test_mission_resolver():
    """resolve_missions should populate ast.mission_dispatches from call scanning."""
    from graph_builder.resolvers.mission_resolver import resolve_missions, resolve_mission_targets

    fixture_path = str(LUA_FIXTURES / "mission_caller.lua")
    ast = parse_lua_file(fixture_path)
    resolve_missions({fixture_path: ast})

    assert len(ast.mission_dispatches) >= 2
    task_names = [m.task_name for m in ast.mission_dispatches]
    assert "pts_run" in task_names
    assert "model_prediction" in task_names

    # Also test Phase 2: target resolution
    results = resolve_mission_targets({fixture_path: ast})
    assert len(results) >= 2
    assert all(r["target_pattern"].startswith("tasks/") for r in results)


# ---------------------------------------------------------------------------
# Python bare import (same-directory) resolution
# ---------------------------------------------------------------------------

def test_python_bare_import_same_directory():
    """Bare imports like 'from config import Config' should resolve to same directory."""
    resolver = PythonResolver(str(PY_FIXTURES / "flat_service"))
    runner_path = str(PY_FIXTURES / "flat_service" / "runner.py")

    result = resolver.resolve("config", runner_path)
    assert result is not None
    assert "config.py" in result

    result = resolver.resolve("record_handler", runner_path)
    assert result is not None
    assert "record_handler.py" in result


def test_python_bare_import_prefers_local():
    """Same-directory file should be found for bare imports."""
    resolver = PythonResolver(str(PY_FIXTURES / "flat_service"))
    runner_path = str(PY_FIXTURES / "flat_service" / "runner.py")

    result = resolver.resolve("error_handler", runner_path)
    assert result is not None
    assert "error_handler.py" in result
