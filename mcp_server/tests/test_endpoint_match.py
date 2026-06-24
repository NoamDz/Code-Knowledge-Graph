"""Unit tests for endpoint matching + path-chain extraction.

These are pure-function tests — no Memgraph required. They cover the two
server-side explain_flow fixes:
  - resolve_endpoint: concrete URL -> stored nginx location (exact OR regex)
  - extract_chain:    nodes(path) rows -> (names, files) without the
                      Memgraph-unsupported `[n in nodes(path) | n.name]` list comp.
"""

from __future__ import annotations

import re

from mcp_server.tools.endpoint_match import (
    nginx_pattern_to_regex,
    resolve_endpoint,
    extract_chain,
)


# --- nginx_pattern_to_regex -------------------------------------------------

def test_literal_path_is_not_a_regex():
    assert nginx_pattern_to_regex("/wisp") is None
    assert nginx_pattern_to_regex("/monitor") is None


def test_named_capture_pattern_compiles_and_matches_concrete_url():
    pat = nginx_pattern_to_regex(
        "^/(?<module>.+)/controllers/(?<controller>.+)/(?<rest>.+)$"
    )
    assert pat is not None
    m = pat.search("/ato/controllers/index/session_info")
    assert m is not None
    # nginx (?<name>) was translated to a usable Python named group.
    assert m.group("module") == "ato"
    assert m.group("controller") == "index"
    assert m.group("rest") == "session_info"


def test_non_matching_url_returns_no_match():
    pat = nginx_pattern_to_regex("^/(?<module>.+)/controllers/(?<controller>.+)$")
    assert pat is not None
    assert pat.search("/wisp") is None


# --- resolve_endpoint -------------------------------------------------------

_CANDIDATES = [
    "/wisp",
    "/monitor",
    "^/(?<module>.+)/controllers/(?<controller>.+)/(?<rest>.+)$",
]


def test_exact_match_wins():
    assert resolve_endpoint("/wisp", _CANDIDATES) == "/wisp"


def test_regex_fallback_for_dynamic_route():
    assert (
        resolve_endpoint("/ato/controllers/index/session_info", _CANDIDATES)
        == "^/(?<module>.+)/controllers/(?<controller>.+)/(?<rest>.+)$"
    )


def test_no_match_returns_none():
    assert resolve_endpoint("/nope/not/here", ["/wisp", "/monitor"]) is None


def test_exact_preferred_over_regex_when_both_apply():
    # A literal that also satisfies a broad regex must still resolve to itself.
    candidates = ["/ato/controllers/index/session_info",
                  "^/(?<m>.+)/controllers/(?<c>.+)/(?<r>.+)$"]
    assert (
        resolve_endpoint("/ato/controllers/index/session_info", candidates)
        == "/ato/controllers/index/session_info"
    )


def test_most_specific_regex_wins_when_several_match():
    candidates = [
        "^/(?<a>.+)$",                                  # broad
        "^/(?<module>.+)/controllers/(?<rest>.+)$",     # specific
    ]
    assert (
        resolve_endpoint("/ato/controllers/session_info", candidates)
        == "^/(?<module>.+)/controllers/(?<rest>.+)$"
    )


# --- extract_chain ----------------------------------------------------------

def test_extract_chain_maps_names_and_files():
    # neo4j Node objects support .get(); dicts are a faithful stand-in.
    nodes = [
        {"name": "run", "file": "/repo/wisp.lua"},
        {"name": "apply", "file": "/repo/handler.lua"},
    ]
    names, files = extract_chain(nodes)
    assert names == ["run", "apply"]
    assert files == ["/repo/wisp.lua", "/repo/handler.lua"]


def test_extract_chain_handles_missing_keys():
    names, files = extract_chain([{"name": "run"}, {}])
    assert names == ["run", None]
    assert files == [None, None]


def test_extract_chain_empty():
    assert extract_chain([]) == ([], [])
