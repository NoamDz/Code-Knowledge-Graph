"""Parser-level check that the Go parser extracts functions and methods.

Runs anywhere (no graph). Resolves the Phase-0 question of whether missing Go
functions are a parser gap or an ingestion gap: if this passes, the parser is
fine and any missing Go Function nodes in the graph are an ingestion issue.
"""
from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_go")

from graph_builder.parsers.go_parser import parse_go_file  # noqa: E402

GO_SAMPLE = '''package router

import "fmt"

func StandardHandler(w int) error {
    fmt.Println("hi")
    return nil
}

type StandardRouter struct {
    name string
}

func (r *StandardRouter) ReadTasks(data []byte) error {
    return nil
}
'''


def test_go_parser_extracts_functions_and_methods(tmp_path):
    f = tmp_path / "router.go"
    f.write_text(GO_SAMPLE, encoding="utf-8")
    ast = parse_go_file(str(f))

    names = {fn.name for fn in ast.functions}
    assert "StandardHandler" in names, f"plain function missing; got {names}"
    # methods are stored with their receiver type, e.g. "StandardRouter.ReadTasks"
    assert any(n.endswith("ReadTasks") for n in names), f"method missing; got {names}"
    # the struct is captured as a class
    assert any(c.name == "StandardRouter" for c in ast.classes)
    # every function carries real line info (relevant to get_code_snippet)
    assert all(fn.line and fn.line_end for fn in ast.functions)
