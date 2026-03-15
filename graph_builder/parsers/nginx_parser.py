"""nginx.conf parser for OpenResty Lua entry points.

Extracts:
  - lua_package_path configuration
  - lua_shared_dict declarations
  - location blocks with their Lua phase directives
  - *_by_lua_block and *_by_lua_file directives
  - Inline Lua code within blocks (for require extraction)
  - Include directives (for following config includes)

This is a regex/state-machine parser, not tree-sitter, since nginx.conf
is not a programming language with a tree-sitter grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NginxLuaPhase:
    """A Lua phase directive in an nginx location."""
    directive: str          # e.g., "access_by_lua_block", "content_by_lua_file"
    phase: str              # e.g., "access", "content", "rewrite"
    is_inline: bool         # True for *_block, False for *_file
    lua_file: str | None    # path for *_file directives
    inline_code: str | None # code for *_block directives
    line: int


@dataclass
class NginxLocation:
    """A location block with its Lua phases."""
    path: str               # e.g., "/api/auth/login"
    modifier: str | None    # e.g., "~", "=", "~*"
    line: int
    phases: list[NginxLuaPhase] = field(default_factory=list)


@dataclass
class NginxSharedDict:
    """A lua_shared_dict declaration."""
    name: str
    size: str
    line: int


@dataclass
class NginxConfig:
    """Complete parsed nginx config."""
    lua_package_path: list[str] = field(default_factory=list)
    lua_package_cpath: list[str] = field(default_factory=list)
    shared_dicts: list[NginxSharedDict] = field(default_factory=list)
    locations: list[NginxLocation] = field(default_factory=list)
    global_phases: list[NginxLuaPhase] = field(default_factory=list)
    include_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Phase directive patterns
PHASE_MAP = {
    "init_by_lua_block": "init",
    "init_by_lua_file": "init",
    "init_worker_by_lua_block": "init_worker",
    "init_worker_by_lua_file": "init_worker",
    "rewrite_by_lua_block": "rewrite",
    "rewrite_by_lua_file": "rewrite",
    "access_by_lua_block": "access",
    "access_by_lua_file": "access",
    "content_by_lua_block": "content",
    "content_by_lua_file": "content",
    "header_filter_by_lua_block": "header_filter",
    "header_filter_by_lua_file": "header_filter",
    "body_filter_by_lua_block": "body_filter",
    "body_filter_by_lua_file": "body_filter",
    "log_by_lua_block": "log",
    "log_by_lua_file": "log",
    "ssl_certificate_by_lua_block": "ssl_certificate",
    "ssl_session_fetch_by_lua_block": "ssl_session_fetch",
    "ssl_session_store_by_lua_block": "ssl_session_store",
}

# Regexes
RE_LUA_PKG_PATH = re.compile(r'lua_package_path\s+"([^"]+)"')
RE_LUA_PKG_CPATH = re.compile(r'lua_package_cpath\s+"([^"]+)"')
RE_SHARED_DICT = re.compile(r'lua_shared_dict\s+(\w+)\s+(\S+?)\s*;')
RE_LOCATION = re.compile(r'location\s+(=|~\*?|~)?\s*(\S+)\s*\{')
RE_LUA_FILE = re.compile(r'(\w+_by_lua_file)\s+(\S+)\s*;')
RE_LUA_BLOCK_START = re.compile(r'(\w+_by_lua_block)\s*\{')
RE_INCLUDE = re.compile(r'include\s+(\S+)\s*;')


def _extract_block(content: str, start_pos: int) -> tuple[str, int]:
    """Extract content between matched braces starting at { position.

    Returns (block_content, end_position_after_closing_brace).
    """
    depth = 0
    i = start_pos
    block_start = None

    while i < len(content):
        if content[i] == '{':
            if depth == 0:
                block_start = i + 1
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[block_start:i], i + 1
        i += 1

    return content[block_start or start_pos:], len(content)


def _line_number(content: str, pos: int) -> int:
    """Get 1-indexed line number for a position in the content."""
    return content[:pos].count('\n') + 1


def parse_nginx_conf(conf_path: str) -> NginxConfig:
    """Parse an nginx.conf file and extract OpenResty Lua directives."""
    content = Path(conf_path).read_text()
    config = NginxConfig()

    # lua_package_path
    for m in RE_LUA_PKG_PATH.finditer(content):
        paths = [p.strip() for p in m.group(1).split(";") if p.strip() and p.strip() != ";"]
        config.lua_package_path.extend(paths)

    # lua_package_cpath
    for m in RE_LUA_PKG_CPATH.finditer(content):
        paths = [p.strip() for p in m.group(1).split(";") if p.strip() and p.strip() != ";"]
        config.lua_package_cpath.extend(paths)

    # lua_shared_dict
    for m in RE_SHARED_DICT.finditer(content):
        config.shared_dicts.append(NginxSharedDict(
            name=m.group(1), size=m.group(2),
            line=_line_number(content, m.start()),
        ))

    # include directives
    for m in RE_INCLUDE.finditer(content):
        config.include_files.append(m.group(1))

    # Process location blocks and their Lua directives
    _parse_locations_and_phases(content, config)

    return config


def _parse_locations_and_phases(content: str, config: NginxConfig):
    """Parse location blocks and extract Lua phase directives."""
    pos = 0
    current_location: NginxLocation | None = None

    while pos < len(content):
        # Check for location block start
        loc_match = RE_LOCATION.search(content, pos)
        block_match = RE_LUA_BLOCK_START.search(content, pos)
        file_match = RE_LUA_FILE.search(content, pos)

        # Find earliest match
        candidates = []
        if loc_match:
            candidates.append(('location', loc_match))
        if block_match:
            candidates.append(('block', block_match))
        if file_match:
            candidates.append(('file', file_match))

        if not candidates:
            break

        candidates.sort(key=lambda x: x[1].start())
        match_type, match = candidates[0]

        if match_type == 'location':
            modifier = match.group(1)
            path = match.group(2)
            line = _line_number(content, match.start())

            # Extract the location block content
            block_content, end_pos = _extract_block(content, match.start() + len(match.group(0)) - 1)

            loc = NginxLocation(path=path, modifier=modifier, line=line)

            # Find Lua directives within this location block
            _extract_phases_from_block(block_content, loc.phases, line, config)

            config.locations.append(loc)
            pos = end_pos

        elif match_type == 'block':
            directive = match.group(1)
            if directive not in PHASE_MAP:
                pos = match.end()
                continue

            # Extract the Lua block content
            block_content, end_pos = _extract_block(content, match.start() + len(match.group(0)) - 1)
            line = _line_number(content, match.start())

            phase = NginxLuaPhase(
                directive=directive,
                phase=PHASE_MAP[directive],
                is_inline=True,
                lua_file=None,
                inline_code=block_content.strip(),
                line=line,
            )

            # Determine if this is inside a location or global
            # (simplified: if no location has been started yet or if this
            #  was already captured in a location block, skip)
            if not any(p.line == line for loc in config.locations for p in loc.phases):
                config.global_phases.append(phase)

            pos = end_pos

        elif match_type == 'file':
            directive = match.group(1)
            lua_file = match.group(2).rstrip(';')
            if directive not in PHASE_MAP:
                pos = match.end()
                continue

            line = _line_number(content, match.start())
            phase = NginxLuaPhase(
                directive=directive,
                phase=PHASE_MAP[directive],
                is_inline=False,
                lua_file=lua_file,
                inline_code=None,
                line=line,
            )

            if not any(p.line == line for loc in config.locations for p in loc.phases):
                config.global_phases.append(phase)

            pos = match.end()


def _extract_phases_from_block(block_content: str, phases: list, base_line: int, config: NginxConfig):
    """Extract Lua phase directives from within a location block."""
    # File directives
    for m in RE_LUA_FILE.finditer(block_content):
        directive = m.group(1)
        if directive not in PHASE_MAP:
            continue
        phases.append(NginxLuaPhase(
            directive=directive,
            phase=PHASE_MAP[directive],
            is_inline=False,
            lua_file=m.group(2).rstrip(';'),
            inline_code=None,
            line=base_line + block_content[:m.start()].count('\n'),
        ))

    # Block directives
    for m in RE_LUA_BLOCK_START.finditer(block_content):
        directive = m.group(1)
        if directive not in PHASE_MAP:
            continue
        inner_content, _ = _extract_block(block_content, m.start() + len(m.group(0)) - 1)
        phases.append(NginxLuaPhase(
            directive=directive,
            phase=PHASE_MAP[directive],
            is_inline=True,
            lua_file=None,
            inline_code=inner_content.strip(),
            line=base_line + block_content[:m.start()].count('\n'),
        ))
