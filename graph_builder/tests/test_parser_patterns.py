"""Tests for parser pattern extraction (13 language-specific patterns).

Covers: Lua coroutines/table dispatch, Python yield/getattr/decorators,
Go goroutines/defer/channels, Ruby blocks/send/metaprogramming, JS events/timers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import (
    FileAST, FunctionDef, CallRef, ChannelAccess,
)


# --- Data model tests ---

def test_function_def_is_coroutine():
    """FunctionDef should have is_coroutine field."""
    func = FunctionDef(name="process", line=1, line_end=10, is_coroutine=True)
    assert func.is_coroutine is True

    func2 = FunctionDef(name="normal", line=1, line_end=5)
    assert func2.is_coroutine is False


def test_call_ref_is_goroutine():
    """CallRef should have is_goroutine field."""
    call = CallRef(
        caller_function="main", callee_string="handler.Process",
        line=10, is_goroutine=True,
    )
    assert call.is_goroutine is True

    call2 = CallRef(caller_function="main", callee_string="fmt.Println", line=5)
    assert call2.is_goroutine is False


def test_call_ref_is_deferred():
    """CallRef should have is_deferred field."""
    call = CallRef(
        caller_function="main", callee_string="conn.Close",
        line=15, is_deferred=True,
    )
    assert call.is_deferred is True


def test_channel_access_model():
    """ChannelAccess dataclass stores channel name, operation, function, line."""
    ca = ChannelAccess(
        channel_name="taskQueue", operation="send",
        function="worker.Process", line=42,
    )
    assert ca.channel_name == "taskQueue"
    assert ca.operation == "send"
    assert ca.element_type is None


def test_channel_access_with_type():
    """ChannelAccess can store element type."""
    ca = ChannelAccess(
        channel_name="resultChan", operation="create",
        function="main", line=10, element_type="*Task",
    )
    assert ca.element_type == "*Task"


def test_file_ast_has_channel_accesses():
    """FileAST should include channel_accesses field."""
    ast = FileAST(file_path="test.go", language="go")
    assert ast.channel_accesses == []


# --- Lua pattern tests ---

from graph_builder.parsers.lua_parser import parse_lua_file
from graph_builder.resolvers.builtin_classifier import BuiltinClassifier

FIXTURES = Path(__file__).parent / "fixtures"
LUA = FIXTURES / "lua"
PY = FIXTURES / "python"
GO = FIXTURES / "go"
RB = FIXTURES / "ruby"
JS = FIXTURES / "js"


def test_lua_coroutine_calls_detected():
    """Coroutine.* calls should be detected as regular calls."""
    ast = parse_lua_file(str(LUA / "coroutine_patterns.lua"))
    coroutine_calls = [c for c in ast.calls if c.callee_string.startswith("coroutine.")]
    assert len(coroutine_calls) >= 5, (
        f"Expected 5+ coroutine calls (create, resume, yield, wrap, running), "
        f"got {len(coroutine_calls)}: {[c.callee_string for c in coroutine_calls]}"
    )
    callee_names = {c.callee_string for c in coroutine_calls}
    assert "coroutine.create" in callee_names
    assert "coroutine.resume" in callee_names
    assert "coroutine.yield" in callee_names
    assert "coroutine.wrap" in callee_names
    assert "coroutine.running" in callee_names


def test_lua_coroutine_classification():
    """Coroutine.* calls should be classified as 'coroutine' by BuiltinClassifier."""
    classifier = BuiltinClassifier()
    assert classifier.classify_call("coroutine.create", "lua") == "coroutine"
    assert classifier.classify_call("coroutine.resume", "lua") == "coroutine"
    assert classifier.classify_call("coroutine.yield", "lua") == "coroutine"
    assert classifier.classify_call("coroutine.wrap", "lua") == "coroutine"
    assert classifier.classify_call("coroutine.running", "lua") == "coroutine"
    # Other stdlib should still be "builtin"
    assert classifier.classify_call("string.format", "lua") == "builtin"
    assert classifier.classify_call("table.insert", "lua") == "builtin"


def test_lua_table_dispatch_imports():
    """Table dispatch with require() values should create import entries."""
    ast = parse_lua_file(str(LUA / "table_dispatch.lua"))
    module_strings = {imp.module_string for imp in ast.imports}
    assert "events.event_type_a" in module_strings
    assert "events.event_type_b" in module_strings
    assert "events.event_type_c" in module_strings
    assert "handlers.get_handler" in module_strings
    assert "handlers.post_handler" in module_strings


# --- Python pattern tests ---

from graph_builder.parsers.python_parser import parse_python_file


def test_python_tornado_coroutine_flagged():
    """Functions with @tornado.gen.coroutine should have is_coroutine=True."""
    ast = parse_python_file(str(PY / "tornado_coroutines.py"))
    func_map = {f.name: f for f in ast.functions}

    assert "process" in func_map
    assert func_map["process"].is_coroutine is True, "process should be is_coroutine=True"

    assert "fetch_data" in func_map
    assert func_map["fetch_data"].is_coroutine is True, "fetch_data should be is_coroutine=True"

    assert "normal_method" in func_map
    assert func_map["normal_method"].is_coroutine is False, "normal_method should be is_coroutine=False"


def test_python_getattr_dynamic_dispatch():
    """getattr() calls should create CallRef entries with dynamic confidence."""
    ast = parse_python_file(str(PY / "dynamic_dispatch.py"))
    getattr_calls = [c for c in ast.calls if c.callee_string == "getattr"]
    assert len(getattr_calls) >= 2, f"Expected 2+ getattr calls, got {len(getattr_calls)}"

    # Check that a potential call to "handle_get" is created from the string literal arg
    dynamic_calls = [c for c in ast.calls if c.resolution_confidence == "dynamic_getattr"]
    assert len(dynamic_calls) >= 1, (
        f"Expected 1+ dynamic_getattr calls for literal string arg, got {len(dynamic_calls)}"
    )
    dynamic_targets = {c.callee_string for c in dynamic_calls}
    assert "self.handle_get" in dynamic_targets, (
        f"Expected 'self.handle_get' in dynamic targets, got {dynamic_targets}"
    )


def test_python_decorator_factory_detection():
    """Functions that return wrapper functions should be flagged."""
    ast = parse_python_file(str(PY / "dynamic_dispatch.py"))
    func_map = {f.name: f for f in ast.functions}

    # timing_decorator is a decorator factory (takes func, returns wrapper)
    assert "timing_decorator" in func_map
    # We detect this via a functools.wraps call inside the function
    wraps_calls = [c for c in ast.calls
                   if c.callee_string in ("functools.wraps", "wraps")
                   and c.caller_function in ("wrapper", "timing_decorator")]
    assert len(wraps_calls) >= 1, "Should detect functools.wraps usage in decorator"


# --- Go pattern tests ---

from graph_builder.parsers.go_parser import parse_go_file


def test_go_goroutine_detection():
    """Calls inside `go` statements should have is_goroutine=True."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    goroutine_calls = [c for c in ast.calls if c.is_goroutine]
    assert len(goroutine_calls) >= 1, (
        f"Expected 1+ goroutine calls, got {len(goroutine_calls)}"
    )
    # w.processLoop() is called via `go w.processLoop()`
    goroutine_targets = {c.callee_string for c in goroutine_calls}
    assert "w.processLoop" in goroutine_targets, (
        f"Expected 'w.processLoop' in goroutine targets, got {goroutine_targets}"
    )


def test_go_defer_detection():
    """Calls inside `defer` statements should have is_deferred=True."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    deferred_calls = [c for c in ast.calls if c.is_deferred]
    assert len(deferred_calls) >= 2, (
        f"Expected 2+ deferred calls (close, cleanup), got {len(deferred_calls)}"
    )
    deferred_targets = {c.callee_string for c in deferred_calls}
    assert "close" in deferred_targets or "w.cleanup" in deferred_targets, (
        f"Expected 'close' or 'w.cleanup' in deferred targets, got {deferred_targets}"
    )


def test_go_channel_send_detection():
    """Channel send operations (ch <- value) should be detected."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    sends = [ca for ca in ast.channel_accesses if ca.operation == "send"]
    assert len(sends) >= 1, f"Expected 1+ channel sends, got {len(sends)}"


def test_go_channel_receive_detection():
    """Channel receive operations (<-ch) should be detected."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    receives = [ca for ca in ast.channel_accesses if ca.operation == "receive"]
    assert len(receives) >= 1, f"Expected 1+ channel receives, got {len(receives)}"


def test_go_channel_create_detection():
    """make(chan Type) calls should be detected as channel creation."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    creates = [ca for ca in ast.channel_accesses if ca.operation == "create"]
    assert len(creates) >= 3, (
        f"Expected 3+ channel creates (taskQueue, resultChan, done), got {len(creates)}"
    )


def test_go_channel_close_detection():
    """close(ch) calls should be detected as channel close."""
    ast = parse_go_file(str(GO / "concurrency.go"))
    closes = [ca for ca in ast.channel_accesses if ca.operation == "close"]
    assert len(closes) >= 2, (
        f"Expected 2+ channel closes (resultChan, taskQueue), got {len(closes)}"
    )
