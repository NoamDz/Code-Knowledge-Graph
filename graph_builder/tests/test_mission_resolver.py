"""Tests for expanded mission dispatch detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.base import FileAST, CallRef, ImportRef, MissionDispatch
from graph_builder.resolvers.mission_resolver import resolve_missions, resolve_mission_targets

FIXTURES = Path(__file__).parent / "fixtures" / "lua" / "mission"


def _make_ast(file_path, calls=None, imports=None):
    return FileAST(
        file_path=file_path, language="lua",
        calls=calls or [], imports=imports or [],
    )


def test_add_mission_direct_call():
    """missioner.add_mission('pts_run', ...) detected from CallRef."""
    fixture = str(FIXTURES / "pts_controller.lua")
    ast = _make_ast(fixture, calls=[
        CallRef(caller_function="apply", callee_string="missioner.add_mission",
                line=8),  # line 8 in fixture has add_mission("pts_run", ...)
    ])
    all_asts = {fixture: ast}
    resolve_missions(all_asts)
    assert len(ast.mission_dispatches) >= 1
    assert ast.mission_dispatches[0].task_name == "pts_run"


def test_missioner_timer_post():
    """missioner_timer.post() variant is also detected."""
    fixture = str(FIXTURES / "analyzer.lua")
    ast = _make_ast(fixture, calls=[
        CallRef(caller_function="analyze", callee_string="missioner_timer.post",
                line=6),  # line 6 in fixture has post("analyze_batch", ...)
    ])
    all_asts = {fixture: ast}
    resolve_missions(all_asts)
    assert len(ast.mission_dispatches) >= 1
    assert ast.mission_dispatches[0].task_name == "analyze_batch"


def test_binding_based_detection():
    """Local variable bound to missioner module is detected."""
    fixture = str(FIXTURES / "rulegen.lua")
    ast = _make_ast(fixture,
        imports=[
            ImportRef(module_string="deferrer.missioner.client",
                      line=1, import_type="require",
                      local_binding="missioner"),
        ],
        calls=[
            CallRef(caller_function="run_check",
                    callee_string="missioner.add_mission", line=6),
        ],
    )
    all_asts = {fixture: ast}
    resolve_missions(all_asts)
    assert len(ast.mission_dispatches) >= 1
    assert ast.mission_dispatches[0].task_name == "rulegen_check"


def test_task_target_resolution():
    """Task name resolves to task file via pattern matching."""
    task_ast = _make_ast("src/ato/tasks/pts_run.lua")
    caller_ast = _make_ast("src/ato/controllers/pts.lua")
    caller_ast.mission_dispatches.append(
        MissionDispatch(task_name="pts_run", queue="policy",
                        caller_function="apply", line=107)
    )

    all_asts = {
        "src/ato/tasks/pts_run.lua": task_ast,
        "src/ato/controllers/pts.lua": caller_ast,
    }

    results = resolve_mission_targets(all_asts)
    assert len(results) >= 1
    assert results[0]["target_file"] == "src/ato/tasks/pts_run.lua"


def test_unresolved_task_logged():
    """Task name not matching any file produces entry with target_file=None."""
    caller_ast = _make_ast("src/caller.lua")
    caller_ast.mission_dispatches.append(
        MissionDispatch(task_name="nonexistent_task", caller_function="run", line=10)
    )

    all_asts = {"src/caller.lua": caller_ast}
    results = resolve_mission_targets(all_asts)
    assert len(results) == 1
    assert results[0]["target_file"] is None


def test_legacy_warning_detection():
    """Legacy warning-based detection still works as fallback."""
    ast = _make_ast("src/caller.lua")
    ast.warnings.append("mission:some_task:42")
    all_asts = {"src/caller.lua": ast}
    resolve_missions(all_asts)
    assert len(ast.mission_dispatches) == 1
    assert ast.mission_dispatches[0].task_name == "some_task"
    assert ast.mission_dispatches[0].line == 42


def test_no_duplicate_from_warning_and_call():
    """If warning and call both detect the same dispatch, no duplicate."""
    fixture = str(FIXTURES / "pts_controller.lua")
    ast = _make_ast(fixture, calls=[
        CallRef(caller_function="apply", callee_string="missioner.add_mission",
                line=8),
    ])
    ast.warnings.append("mission:pts_run:8")
    all_asts = {fixture: ast}
    resolve_missions(all_asts)
    # Should have exactly 1, not 2
    pts_dispatches = [d for d in ast.mission_dispatches if d.task_name == "pts_run" and d.line == 8]
    assert len(pts_dispatches) == 1
