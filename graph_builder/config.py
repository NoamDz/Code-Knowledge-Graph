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

    # Path prefix for resolving nginx include directives.
    # In containers, nginx includes use absolute paths like /data/app/nginx/conf.d/*.conf
    # This maps the container prefix to the local repo_root.
    nginx_base_path: str | None = None

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
        if "nginx_base_path" in raw:
            config.nginx_base_path = raw["nginx_base_path"]

        return config

    @classmethod
    def default(cls) -> "Config":
        return cls()
