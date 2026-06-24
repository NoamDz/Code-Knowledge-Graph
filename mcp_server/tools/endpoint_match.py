"""Pure helpers for endpoint resolution and call-chain extraction.

Kept free of any Memgraph dependency so they can be unit-tested directly.

  * nginx_pattern_to_regex / resolve_endpoint — match a concrete request URL
    against the nginx location strings stored as Endpoint.path. nginx regex
    locations (e.g. ``~ ^/(?<module>.+)/controllers/...``) are stored verbatim,
    so an exact-string lookup never hits them; we fall back to regex matching.

  * extract_chain — turn a ``nodes(path)`` row into (names, files). Replaces the
    Cypher list comprehension ``[n in nodes(path) | n.name]``, which some
    Memgraph builds reject ("Not yet implemented: atom expression").
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

# nginx/PCRE named captures use (?<name>...); Python's re wants (?P<name>...).
_NGINX_NAMED_GROUP = re.compile(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>")

# A stored Endpoint.path is a regex location (not a literal URL) when it carries
# a regex metacharacter. Literal nginx prefixes look like "/wisp". '.' is left
# out on purpose — it appears in plenty of literal paths (e.g. /api/v1.0).
_REGEX_METACHARS = frozenset("^$()[]+*?|\\")


def nginx_pattern_to_regex(path: str) -> Optional[re.Pattern]:
    """Compile an nginx regex-location string to a Python regex.

    Returns None when ``path`` is a literal location (no regex metacharacters)
    or when the translated pattern fails to compile.
    """
    if not path or not any(ch in _REGEX_METACHARS for ch in path):
        return None
    translated = _NGINX_NAMED_GROUP.sub(r"(?P<\1>", path)
    try:
        return re.compile(translated)
    except re.error:
        return None


def resolve_endpoint(target: str, candidates: Iterable[str]) -> Optional[str]:
    """Resolve a concrete request URL to one of the stored Endpoint paths.

    Exact string match wins. Otherwise the most specific (longest) nginx regex
    location that matches the URL is returned. None if nothing matches.
    """
    candidate_list = list(candidates)
    if target in candidate_list:
        return target

    best: Optional[str] = None
    for path in candidate_list:
        pattern = nginx_pattern_to_regex(path)
        if pattern is not None and pattern.search(target):
            if best is None or len(path) > len(best):
                best = path
    return best


def extract_chain(nodes: Iterable[Mapping]) -> tuple[list, list]:
    """Split a path's nodes into parallel (names, files) lists.

    Accepts anything that supports ``.get()`` — neo4j Node objects or plain
    dicts — so it can replace the Memgraph-unsupported list comprehension.
    """
    names: list = []
    files: list = []
    for n in nodes:
        names.append(n.get("name"))
        files.append(n.get("file"))
    return names, files
