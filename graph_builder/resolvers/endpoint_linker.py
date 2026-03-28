"""Cross-language endpoint linker: matches HTTP call URLs to target handlers.

Uses nginx config locations for URL-to-handler matching (longest-prefix),
and Go unix socket handler registries for socket-based routing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..parsers.base import FileAST
    from ..parsers.nginx_parser import NginxConfig


class EndpointLinker:
    """Links HTTP client calls to their target server handlers across languages.

    Flow:
        1. Index nginx locations (path -> lua_file/proxy_target)
        2. Register Go unix socket handlers (socket_path -> {http_path -> go_file})
        3. For each HTTP call in any AST, try to match:
           a. nginx location (longest-prefix match)
           b. unix socket handler (exact socket + path match)
    """

    # BOB-confirmed internal endpoints and their cross-language callers
    INTERNAL_ENDPOINTS = [
        {"path": "/tasks", "callers": ["python"],
         "description": "Poller -> Lua task dispatch"},
        {"path": "/missions", "callers": ["python"],
         "description": "Missioner -> Lua mission dispatch"},
        {"path": "/get_bundle", "callers": ["go"],
         "description": "Model Prediction -> Lua bundle fetch"},
        {"path": "/monitor", "callers": ["any"],
         "description": "Health check endpoint"},
        {"path": "/status", "callers": ["any"],
         "description": "Status endpoint"},
        {"path": "/events", "callers": ["any"],
         "description": "Event ingestion endpoint"},
    ]

    def __init__(self, nginx_config: NginxConfig | None = None):
        # location_path -> {lua_file, proxy_target, phases, ...}
        self._location_index: dict[str, dict] = {}
        # socket_path -> {http_path -> go_file_path}
        self._go_handlers: dict[str, dict[str, str]] = {}
        # controller route path -> lua_file_path
        self._controller_routes: dict[str, str] = {}

        if nginx_config is not None:
            self._index_nginx_locations(nginx_config)

    def _index_nginx_locations(self, nginx_config: NginxConfig) -> None:
        """Build a lookup index from nginx location paths."""
        for loc in nginx_config.locations:
            entry: dict = {
                "path": loc.path,
                "modifier": loc.modifier,
                "phases": [],
                "lua_file": None,
                "proxy_target": None,
            }

            for phase in loc.phases:
                entry["phases"].append({
                    "phase": phase.phase,
                    "lua_file": phase.lua_file,
                    "is_inline": phase.is_inline,
                })
                # Use the first non-None lua_file as the handler
                if phase.lua_file and entry["lua_file"] is None:
                    entry["lua_file"] = phase.lua_file

            if loc.proxy_pass:
                entry["proxy_target"] = loc.proxy_pass.target

            self._location_index[loc.path] = entry

    def register_go_handlers(self, handlers: dict[str, dict[str, str]]) -> None:
        """Register Go unix socket handlers.

        Args:
            handlers: {socket_path: {http_path: go_file_path}}
        """
        self._go_handlers.update(handlers)

    def register_internal_endpoints(self) -> None:
        """Register BOB-confirmed internal endpoints for cross-language linking.

        These endpoints are accessed internally (not from external clients)
        and represent known cross-language call paths.  The endpoints are
        already in the nginx location index if nginx config is loaded.
        This method is a no-op marker that enables internal endpoint
        awareness in link_all().
        """
        pass

    def register_controller_routes(self, routes: dict[str, str]) -> None:
        """Register controller routes from BOB's confirmed routing map.

        Args:
            routes: {url_path_pattern: lua_file_path}
        """
        self._controller_routes.update(routes)

    def _match_location(self, url_path: str) -> dict | None:
        """Find the best matching nginx location using longest-prefix match.

        This mimics nginx's location matching behavior for prefix locations.
        Exact matches (modifier '=') take priority. Otherwise, longest prefix wins.
        """
        # First check for exact match (= modifier)
        for path, entry in self._location_index.items():
            if entry.get("modifier") == "=" and url_path == path:
                return entry

        # Longest prefix match
        best_match: dict | None = None
        best_length = 0

        for path, entry in self._location_index.items():
            # Skip regex locations for prefix matching
            if entry.get("modifier") in ("~", "~*"):
                continue
            if url_path.startswith(path) and len(path) > best_length:
                best_match = entry
                best_length = len(path)

        return best_match

    def _match_unix_socket(self, url: str) -> dict | None:
        """Match a unix socket URL to a Go handler.

        Handles URL formats like:
            unix:/tmp/model_prediction.sock
            unix:/tmp/model_prediction.sock:/predict
            http://unix:/tmp/svc.sock:/path
        """
        # Extract socket path from various URL formats
        socket_match = re.search(r'unix:([^:\s]+\.sock)', url)
        if not socket_match:
            return None

        socket_path = socket_match.group(1)

        # Extract the HTTP path after the socket (if any)
        path_match = re.search(r'\.sock:(/[^\s]*)', url)
        http_path = path_match.group(1) if path_match else "/"

        if socket_path in self._go_handlers:
            handler_map = self._go_handlers[socket_path]
            # Try exact path match first
            if http_path in handler_map:
                return {
                    "socket": socket_path,
                    "http_path": http_path,
                    "go_file": handler_map[http_path],
                }
            # Try prefix match
            best_path = None
            best_len = 0
            for registered_path, go_file in handler_map.items():
                if http_path.startswith(registered_path) and len(registered_path) > best_len:
                    best_path = registered_path
                    best_len = len(registered_path)
            if best_path:
                return {
                    "socket": socket_path,
                    "http_path": best_path,
                    "go_file": handler_map[best_path],
                }

        return None

    def link_all(self, all_asts: dict[str, FileAST]) -> list[dict]:
        """Link all HTTP calls across all ASTs to their target handlers.

        Returns:
            List of link dicts, each containing:
                source_file, source_function, source_line, method, endpoint,
                and one of: target_lua_file, target_go_file+socket, proxy_target
        """
        links: list[dict] = []

        for file_path, ast in all_asts.items():
            for hc in ast.http_calls:
                url = hc.url_or_path
                link = self._resolve_single_call(
                    source_file=file_path,
                    source_function=hc.function,
                    source_line=hc.line,
                    method=hc.method,
                    url=url,
                )
                if link is not None:
                    links.append(link)

        return links

    def _resolve_single_call(
        self,
        source_file: str,
        source_function: str,
        source_line: int,
        method: str,
        url: str,
    ) -> dict | None:
        """Try to resolve a single HTTP call to a handler."""
        base = {
            "source_file": source_file,
            "source_function": source_function,
            "source_line": source_line,
            "method": method,
        }

        # 1. Try unix socket match
        socket_match = self._match_unix_socket(url)
        if socket_match:
            return {
                **base,
                "endpoint": socket_match["http_path"],
                "target_go_file": socket_match["go_file"],
                "socket": socket_match["socket"],
            }

        # 2. Try nginx location match (only for path-like URLs)
        url_path = self._extract_path(url)
        if url_path and url_path.startswith("/"):
            loc_match = self._match_location(url_path)
            if loc_match:
                result = {**base, "endpoint": url_path}
                if loc_match.get("lua_file"):
                    result["target_lua_file"] = loc_match["lua_file"]
                if loc_match.get("proxy_target"):
                    result["proxy_target"] = loc_match["proxy_target"]
                return result

            # 3. Try controller route match
            ctrl_match = self._match_controller_route(url_path)
            if ctrl_match:
                return {
                    **base,
                    "endpoint": url_path,
                    "target_lua_file": ctrl_match,
                }

        return None

    def _match_controller_route(self, url_path: str) -> str | None:
        """Match a URL path against registered controller routes."""
        # Exact match first
        if url_path in self._controller_routes:
            return self._controller_routes[url_path]
        # Prefix match
        best_match = None
        best_len = 0
        for route_path, lua_file in self._controller_routes.items():
            if url_path.startswith(route_path) and len(route_path) > best_len:
                best_match = lua_file
                best_len = len(route_path)
        return best_match

    @staticmethod
    def _extract_path(url: str) -> str | None:
        """Extract the path component from a URL or path string.

        Handles:
            /api/foo          -> /api/foo
            http://host/path  -> /path
            https://ext.com/  -> /
            unix:/tmp/x.sock  -> None (handled separately)
        """
        if "unix:" in url:
            return None

        if url.startswith("/"):
            # Strip query string
            return url.split("?")[0].split("#")[0]

        # Try to extract path from full URL
        match = re.match(r'https?://[^/]+(/.*)$', url)
        if match:
            path = match.group(1)
            return path.split("?")[0].split("#")[0]

        return None

    def build_go_handler_registry(self, all_asts: dict[str, FileAST]) -> dict[str, dict[str, str]]:
        """Scan Go ASTs for unix socket handler registrations.

        Discovers Go handlers by looking for:
            1. Warnings with format "unix_socket:/path/to/sock" (from Go parser)
            2. HTTP calls with HandleFunc pattern (registered as http_calls)

        Returns:
            {socket_path: {http_path: go_file_path}}
        """
        registry: dict[str, dict[str, str]] = {}

        for file_path, ast in all_asts.items():
            if ast.language != "go":
                continue

            # Look for unix_socket warnings from the Go parser
            socket_path = None
            for warning in ast.warnings:
                if warning.startswith("unix_socket:"):
                    socket_path = warning.split("unix_socket:", 1)[1].strip()
                    break

            if not socket_path:
                continue

            # Collect handler paths from http_calls (HandleFunc registrations)
            handler_map: dict[str, str] = {}
            for hc in ast.http_calls:
                # HandleFunc-style registrations have the path as url_or_path
                path = hc.url_or_path
                if path.startswith("/"):
                    handler_map[path] = file_path

            if handler_map:
                registry[socket_path] = handler_map

        return registry
