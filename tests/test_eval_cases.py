# tests/test_eval_cases.py
from tests.eval_cases import EvalCase, check_output


def test_missing_substring_is_reported():
    case = EvalCase("find_symbol", {"symbol_name": "foo"}, must_contain=["foo"], id="c1")
    failures = check_output("nothing here", case)
    assert failures and "foo" in failures[0]


def test_all_conditions_satisfied_returns_no_failures():
    case = EvalCase(
        "find_symbol", {"symbol_name": "foo"},
        must_contain=["foo", r"bar\.lua"], must_not_contain=["ERROR"], min_lines=2, id="c2",
    )
    output = "foo defined in\nbar.lua:10"
    assert check_output(output, case) == []


def test_must_not_contain_is_enforced():
    case = EvalCase("find_impact", {"symbol_or_file": "x"}, must_not_contain=["Traceback"], id="c3")
    failures = check_output("Traceback (most recent call last)", case)
    assert failures and "Traceback" in failures[0]


def test_none_output_is_a_failure():
    case = EvalCase("locate", {"description": "x"}, id="c4")
    assert check_output(None, case) == ["c4: tool returned None"]


def test_min_lines_counts_only_nonempty_lines():
    case = EvalCase("onboard_to", {"area": "x"}, min_lines=3, id="c5")
    failures = check_output("line1\n\nline2", case)  # only 2 non-empty lines
    assert failures and "min" in failures[0].lower() or ">=" in failures[0]
