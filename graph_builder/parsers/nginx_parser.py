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
class NginxProxyPass:
    """A proxy_pass directive in a location block."""
    target: str             # e.g., "http://go_backend" or "http://unix:/tmp/svc.sock:/path"
    line: int


@dataclass
class NginxLocation:
    """A location block with its Lua phases."""
    path: str               # e.g., "/api/auth/login"
    modifier: str | None    # e.g., "~", "=", "~*"
    line: int
    phases: list[NginxLuaPhase] = field(default_factory=list)
    proxy_pass: NginxProxyPass | None = None


@dataclass
class NginxSharedDict:
    """A lua_shared_dict declaration."""
    name: str
    size: str
    line: int


@dataclass
class NginxUpstream:
    """An upstream block definition."""
    name: str               # e.g., "go_backend"
    servers: list[str] = field(default_factory=list)  # e.g., ["127.0.0.1:8081", "unix:/tmp/svc.sock"]
    line: int = 0


@dataclass
class NginxConfig:
    """Complete parsed nginx config."""
    lua_package_path: list[str] = field(default_factory=list)
    lua_package_cpath: list[str] = field(default_factory=list)
    shared_dicts: list[NginxSharedDict] = field(default_factory=list)
    locations: list[NginxLocation] = field(default_factory=list)
    global_phases: list[NginxLuaPhase] = field(default_factory=list)
    include_files: list[str] = field(default_factory=list)
    upstreams: list[NginxUpstream] = field(default_factory=list)
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
RE_UPSTREAM = re.compile(r'upstream\s+(\w+)\s*\{')
RE_PROXY_PASS = re.compile(r'proxy_pass\s+(\S+?)\s*;')
RE_UPSTREAM_SERVER = re.compile(r'server\s+(\S+)')


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

    _parse_single_file(content, config)

    return config


def _parse_single_file(content: str, config: NginxConfig):
    """Parse a single nginx config file's content into the config object."""
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

    # upstream blocks
    for m in RE_UPSTREAM.finditer(content):
        upstream_name = m.group(1)
        block_content, _ = _extract_block(content, m.start() + len(m.group(0)) - 1)
        servers = []
        for srv_match in RE_UPSTREAM_SERVER.finditer(block_content):
            server_addr = srv_match.group(1).rstrip(";")
            servers.append(server_addr)
        config.upstreams.append(NginxUpstream(
            name=upstream_name,
            servers=servers,
            line=_line_number(content, m.start()),
        ))

    # Process location blocks and their Lua directives
    _parse_locations_and_phases(content, config)


def parse_nginx_conf_recursive(conf_path: str, base_path: str | None = None) -> NginxConfig:
    """Parse an nginx.conf and recursively follow all include directives.

    Args:
        conf_path: Path to the main nginx.conf file.
        base_path: Optional prefix for resolving container-absolute include paths.
                   E.g., if includes say '/data/app/conf.d/*.conf' and the files
                   are at '<repo_root>/conf.d/*.conf', set base_path to the repo root
                   so '/data/app/' is stripped and resolved relative to base_path.
    """
    conf_path = str(Path(conf_path).resolve())
    config = NginxConfig()
    visited: set[str] = set()

    def _resolve_include_path(include_pattern: str, parent_dir: str) -> list[Path]:
        """Resolve an include pattern to actual file paths."""
        p = Path(include_pattern)

        # If absolute path, try as-is first, then try relative to base_path
        if p.is_absolute():
            # Try the literal path (works when running inside the container)
            matches = list(Path("/").glob(str(p).lstrip("/")))
            if matches:
                return sorted(matches)

            # Try remapping: strip the container prefix and search under base_path or parent_dir
            if base_path:
                # Try progressively shorter prefixes of the absolute path
                parts = p.parts[1:]  # strip root
                for i in range(len(parts)):
                    candidate = Path(base_path) / Path(*parts[i:])
                    if "*" in str(candidate) or "?" in str(candidate):
                        matches = list(candidate.parent.glob(candidate.name))
                        if matches:
                            return sorted(matches)
                    elif candidate.exists():
                        return [candidate]

            # Last resort: try relative to parent dir
            relative = Path(parent_dir) / p.name
            if relative.exists():
                return [relative]
            return []

        # Relative path — resolve relative to the including file's directory
        resolved = Path(parent_dir) / include_pattern
        if "*" in include_pattern or "?" in include_pattern:
            return sorted(resolved.parent.glob(resolved.name))
        elif resolved.exists():
            return [resolved]
        return []

    def _parse_recursive(file_path: str):
        resolved = str(Path(file_path).resolve())
        if resolved in visited:
            return
        visited.add(resolved)

        try:
            content = Path(resolved).read_text()
        except (OSError, IOError) as e:
            config.warnings.append(f"Could not read included file {file_path}: {e}")
            return

        # Parse this file into the shared config
        _parse_single_file(content, config)

        # Follow includes found in this file — they were appended to config.include_files
        # Snapshot includes so far to process only new ones
        parent_dir = str(Path(resolved).parent)
        includes_to_follow = list(config.include_files)  # copy current list

        for inc_pattern in includes_to_follow:
            inc_files = _resolve_include_path(inc_pattern, parent_dir)
            for inc_file in inc_files:
                _parse_recursive(str(inc_file))

    _parse_recursive(conf_path)
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

            # Extract proxy_pass within this location block
            pp_match = RE_PROXY_PASS.search(block_content)
            if pp_match:
                loc.proxy_pass = NginxProxyPass(
                    target=pp_match.group(1),
                    line=line + block_content[:pp_match.start()].count('\n'),
                )

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
