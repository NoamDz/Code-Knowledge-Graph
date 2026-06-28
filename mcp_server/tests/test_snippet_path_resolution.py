"""Unit tests for get_code_snippet's on-disk path resolution.

The graph stores absolute build-time paths (e.g. /Users/dev/pinpoint/src/x.lua),
but the MCP server often runs in a container where the repo is mounted at /repo.
_resolve_source_path must remap the stored path onto the mount root so the file
can actually be read. Pure tests — no Memgraph needed.
"""

from pathlib import Path

from mcp_server.tools.snippets import _resolve_source_path


def test_literal_path_is_returned_when_it_exists(tmp_path):
    f = tmp_path / "real.lua"
    f.write_text("-- hi")
    assert _resolve_source_path(str(f), mount_root="/nonexistent") == f


def test_remaps_absolute_build_path_onto_mount_root(tmp_path):
    # Simulate the container: repo mounted at <tmp>/repo, file under src/core.
    mount = tmp_path / "repo"
    target = mount / "src" / "core" / "openresty" / "global_controller.lua"
    target.parent.mkdir(parents=True)
    target.write_text("-- M.run")

    # Graph recorded a totally different absolute prefix (the Mac host build path).
    stored = "/Users/il021250/dev/pinpoint/src/core/openresty/global_controller.lua"
    resolved = _resolve_source_path(stored, mount_root=str(mount))
    assert resolved == target


def test_prefers_longest_suffix_match(tmp_path):
    # Two files share the basename; the longer, more-specific suffix must win.
    mount = tmp_path / "repo"
    right = mount / "src" / "core" / "util.lua"
    wrong = mount / "util.lua"
    right.parent.mkdir(parents=True)
    right.write_text("-- right")
    wrong.write_text("-- wrong")

    stored = "/build/somewhere/src/core/util.lua"
    assert _resolve_source_path(stored, mount_root=str(mount)) == right


def test_returns_none_when_unresolvable(tmp_path):
    mount = tmp_path / "repo"
    mount.mkdir()
    stored = "/Users/dev/pinpoint/src/missing.lua"
    assert _resolve_source_path(stored, mount_root=str(mount)) is None


def test_returns_none_when_mount_root_missing(tmp_path):
    stored = "/Users/dev/pinpoint/src/x.lua"
    assert _resolve_source_path(stored, mount_root=str(tmp_path / "does_not_exist")) is None
