"""Configuration loader for the code knowledge graph.

Loads settings from a YAML config file and provides sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MemgraphConfig:
    uri: str = "bolt://localhost:7687"
    username: str = ""
    password: str = ""


@dataclass
class Config:
    """Top-level configuration."""
    repo_root: str = "."
    nginx_conf: str | None = None
    memgraph: MemgraphConfig = field(default_factory=MemgraphConfig)

    # Language extensions to scan
    extensions: dict[str, str] = field(default_factory=lambda: {
        ".lua": "lua",
        ".py": "python",
        ".rb": "ruby",
        ".js": "javascript",
        ".js.erb": "javascript",
        ".go": "go",
    })

    # Directories to skip during scanning
    skip_dirs: set[str] = field(default_factory=lambda: {
        "node_modules", ".git", "__pycache__", ".mypy_cache",
        "vendor", "venv", ".venv", "dist", "build", ".tox",
        ".eggs", "*.egg-info",
    })

    # Lua-specific
    lua_module_table_names: list[str] = field(default_factory=lambda: [
        "_M", "m", "M",
    ])
    lua_package_paths: list[str] = field(default_factory=list)
    # Path segment(s) that act as the Lua require_version root. A file at
    # <repo>/src/ato/collectors/ipp/init.lua resolves to module "ato.collectors.ipp".
    lua_source_roots: list[str] = field(default_factory=lambda: ["src"])

    # Path prefix for resolving nginx include directives.
    # In containers, nginx includes use absolute paths like /data/app/nginx/conf.d/*.conf
    # This maps the container prefix to the local repo_root.
    nginx_base_path: str | None = None

    # Middleware filtering for the explain_flow MCP composite. Files/functions
    # whose name contains any of these substrings are collapsed in the call
    # trace by default. Used in addition to the ngx.ctx state-key heuristic.
    middleware_files: list[str] = field(default_factory=list)
    middleware_functions: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load config from a YAML file."""
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        config = cls()
        config.repo_root = raw.get("repo_root", config.repo_root)
        config.nginx_conf = raw.get("nginx_conf", config.nginx_conf)

        mg = raw.get("memgraph", {})
        config.memgraph = MemgraphConfig(
            uri=mg.get("uri", config.memgraph.uri),
            username=mg.get("username", config.memgraph.username),
            password=mg.get("password", config.memgraph.password),
        )

        if "extensions" in raw:
            config.extensions = raw["extensions"]
        if "skip_dirs" in raw:
            config.skip_dirs = set(raw["skip_dirs"])
        if "lua_module_table_names" in raw:
            config.lua_module_table_names = raw["lua_module_table_names"]
        if "lua_package_paths" in raw:
            config.lua_package_paths = raw["lua_package_paths"]
        if "lua_source_roots" in raw:
            config.lua_source_roots = list(raw["lua_source_roots"])
        if "nginx_base_path" in raw:
            config.nginx_base_path = raw["nginx_base_path"]
        if "middleware_files" in raw:
            config.middleware_files = list(raw["middleware_files"])
        if "middleware_functions" in raw:
            config.middleware_functions = list(raw["middleware_functions"])

        return config

    @classmethod
    def default(cls) -> "Config":
        return cls()
