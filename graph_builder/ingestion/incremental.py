"""Incremental ingestion: re-parse and re-ingest a single changed file."""

from __future__ import annotations

from pathlib import Path

from .writer import GraphWriter
from ..parsers.lua_parser import parse_lua_file
from ..parsers.python_parser import parse_python_file
from ..parsers.ruby_parser import parse_ruby_file
from ..parsers.js_parser import parse_js_file


PARSERS = {
    "lua": parse_lua_file,
    "python": parse_python_file,
    "ruby": parse_ruby_file,
    "javascript": parse_js_file,
}

EXTENSION_MAP = {
    ".lua": "lua",
    ".py": "python",
    ".rb": "ruby",
    ".js": "javascript",
}


def detect_language(file_path: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(file_path).suffix
    return EXTENSION_MAP.get(ext)


def reingest_file(file_path: str, writer: GraphWriter,
                  resolved_imports: dict[str, str | None] | None = None) -> bool:
    """Re-parse and re-ingest a single file.

    Steps:
      1. Delete all nodes/edges originating from this file
      2. Re-parse with the appropriate language parser
      3. Re-ingest the new AST

    Returns True if successful, False if file type unsupported or parse error.
    """
    language = detect_language(file_path)
    if not language:
        return False

    parser_fn = PARSERS.get(language)
    if not parser_fn:
        return False

    # Step 1: Clear old data
    writer.clear_file(file_path)

    # Step 2: Re-parse
    if not Path(file_path).exists():
        # File was deleted — clearing was enough
        return True

    try:
        ast = parser_fn(file_path)
    except Exception as e:
        print(f"[incremental] Parse error for {file_path}: {e}")
        return False

    # Step 3: Re-ingest
    writer.ingest_file_ast(ast, resolved_imports)
    return True
