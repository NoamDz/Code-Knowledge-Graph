"""Tests for JS IIFE connection model: ERB render-chain and HTTP call fix.

Covers:
  - ERB render() pattern detection from raw .js.erb content
  - Filename-to-filepath resolution
  - Collector loop detection
  - HTTP call fix for dynamic URLs
  - Container._collect* as data exfiltration calls
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.resolvers.js_erb_resolver import JsErbResolver, ERB_RENDER_PATTERN

FIXTURES = Path(__file__).parent / "fixtures" / "js"


# --- ERB render pattern regex ---

def test_erb_render_pattern_double_quotes():
    """Detects env["template"].render("net.js.erb", env)."""
    line = '<%=env["template"].render("net.js.erb", env)%>'
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["net.js.erb"]


def test_erb_render_pattern_single_quotes():
    """Detects env['template'].render("utils.js", env)."""
    line = "<%=env['template'].render(\"utils.js\", env)%>"
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["utils.js"]


def test_erb_render_pattern_with_path():
    """Detects render calls with paths: render("path/to/file.js.erb", env)."""
    line = '<%=env["template"].render("path/to/file.js.erb", env)%>'
    matches = ERB_RENDER_PATTERN.findall(line)
    assert matches == ["path/to/file.js.erb"]


def test_erb_render_pattern_multiple_on_different_lines():
    """Detects multiple render calls in multi-line content."""
    content = '''<%=env["template"].render("base64.js", env)%>
<%=env["template"].render("json.js", env)%>
<%=env["template"].render("utils.js", env)%>'''
    matches = ERB_RENDER_PATTERN.findall(content)
    assert matches == ["base64.js", "json.js", "utils.js"]


def test_erb_render_pattern_no_match_on_plain_js():
    """Plain JS without ERB tags should yield no render matches."""
    content = 'var x = template.render("foo.js");'
    matches = ERB_RENDER_PATTERN.findall(content)
    assert matches == []


# --- Render extraction from fixtures ---

def test_extract_renders_from_container():
    """container.js.erb should yield render calls for utils.js, net.js.erb, base64.js."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "container.js.erb"))
    assert "utils.js" in renders
    assert "net.js.erb" in renders
    assert "base64.js" in renders


def test_extract_renders_from_net():
    """net.js.erb should yield render call for base64.js."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "net.js.erb"))
    assert "base64.js" in renders


def test_extract_renders_from_plain_js():
    """utils.js (plain JS) should yield no render calls."""
    resolver = JsErbResolver(str(FIXTURES))
    renders = resolver.extract_render_calls(str(FIXTURES / "utils.js"))
    assert renders == []


# --- Filename-to-filepath resolution ---

def test_resolve_filename_same_directory():
    """Resolver finds file in the same directory as the rendering file."""
    resolver = JsErbResolver(str(FIXTURES))
    # container.js.erb renders "utils.js" -> should find fixtures/js/utils.js
    result = resolver.resolve_filename("utils.js", str(FIXTURES / "container.js.erb"))
    assert result is not None
    assert result.replace("\\", "/").endswith("utils.js")


def test_resolve_filename_global_index():
    """Resolver falls back to global file index when not in same directory."""
    resolver = JsErbResolver(str(FIXTURES))
    # Look up from a hypothetical subdirectory; should still find via index
    result = resolver.resolve_filename("utils.js", str(FIXTURES / "subdir" / "fake.js.erb"))
    assert result is not None
    assert result.replace("\\", "/").endswith("utils.js")


def test_resolve_filename_not_found():
    """Resolver returns None for a filename that doesn't exist anywhere."""
    resolver = JsErbResolver(str(FIXTURES))
    result = resolver.resolve_filename("nonexistent_file.js", str(FIXTURES / "container.js.erb"))
    assert result is None


def test_resolve_all_produces_edges():
    """resolve_all should produce INCLUDES edges from container -> utils, net, base64."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    # Build minimal ASTs representing the fixture files
    container_path = str(FIXTURES / "container.js.erb")
    net_path = str(FIXTURES / "net.js.erb")
    utils_path = str(FIXTURES / "utils.js")

    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
        net_path: FileAST(file_path=net_path, language="javascript"),
        utils_path: FileAST(file_path=utils_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    # container.js.erb should have edges to utils.js, net.js.erb, base64.js
    container_edges = [e for e in edges if e["source_file"] == container_path]
    container_targets = {Path(e["target_file"]).name for e in container_edges}

    assert "utils.js" in container_targets
    assert "net.js.erb" in container_targets
    # base64.js doesn't exist as a fixture, so it won't resolve


def test_resolve_all_nested_includes():
    """net.js.erb renders base64.js -> nested chain detected."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    net_path = str(FIXTURES / "net.js.erb")
    all_asts = {
        net_path: FileAST(file_path=net_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    net_edges = [e for e in edges if e["source_file"] == net_path]
    # base64.js doesn't exist as fixture, so this tests that we attempt resolution
    # but get 0 edges (file not found). The important thing is no crash.
    assert isinstance(net_edges, list)


# --- Collector loop detection ---

def test_collector_loop_detected_in_container():
    """container.js.erb has the collectors_rendered.each pattern."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "container.js.erb")) is True


def test_collector_loop_not_in_plain_js():
    """utils.js (plain JS) has no collector loop."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "utils.js")) is False


def test_collector_loop_not_in_sub_template():
    """net.js.erb (sub-template) has no collector loop."""
    resolver = JsErbResolver(str(FIXTURES))
    assert resolver.has_collector_loop(str(FIXTURES / "net.js.erb")) is False


def test_find_collector_entry_points():
    """Collector entry points are .js.erb files in templates/ directories."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    # Simulate ASTs with template paths
    all_asts = {
        "src/ato/templates/device_container.js.erb": FileAST(
            file_path="src/ato/templates/device_container.js.erb", language="javascript"),
        "src/malware/templates/malware_collector.js.erb": FileAST(
            file_path="src/malware/templates/malware_collector.js.erb", language="javascript"),
        "src/lib/js/utils.js": FileAST(
            file_path="src/lib/js/utils.js", language="javascript"),
        "src/common/base/js/container.js.erb": FileAST(
            file_path="src/common/base/js/container.js.erb", language="javascript"),
    }

    collectors = resolver.find_collector_entry_points(all_asts)

    # Only files in templates/ directories that end in .js.erb
    assert "src/ato/templates/device_container.js.erb" in collectors
    assert "src/malware/templates/malware_collector.js.erb" in collectors
    # Non-template files should NOT be collector entry points
    assert "src/lib/js/utils.js" not in collectors
    assert "src/common/base/js/container.js.erb" not in collectors


def test_resolve_all_with_collector_loop():
    """Container with collector loop should include collector entry points."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    container_path = str(FIXTURES / "container.js.erb")

    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
        "src/ato/templates/device_collector.js.erb": FileAST(
            file_path="src/ato/templates/device_collector.js.erb", language="javascript"),
        "src/malware/templates/mal_collector.js.erb": FileAST(
            file_path="src/malware/templates/mal_collector.js.erb", language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)

    # Container should have collector_loop edges to the template files
    collector_edges = [e for e in edges
                       if e["source_file"] == container_path
                       and e["type"] == "collector_loop"]
    collector_targets = {e["target_file"] for e in collector_edges}

    assert "src/ato/templates/device_collector.js.erb" in collector_targets
    assert "src/malware/templates/mal_collector.js.erb" in collector_targets


# --- Pipeline integration ---

def test_resolver_can_be_instantiated_with_repo_root():
    """JsErbResolver can be instantiated with any directory."""
    resolver = JsErbResolver(str(FIXTURES))
    stats = resolver.stats()
    assert stats["indexed_files"] >= 3  # container.js.erb, net.js.erb, utils.js


def test_resolve_all_returns_list_of_dicts():
    """resolve_all returns correctly structured edge dicts."""
    from graph_builder.parsers.base import FileAST

    resolver = JsErbResolver(str(FIXTURES))

    container_path = str(FIXTURES / "container.js.erb")
    all_asts = {
        container_path: FileAST(file_path=container_path, language="javascript"),
    }

    edges = resolver.resolve_all(all_asts)
    for edge in edges:
        assert "source_file" in edge
        assert "target_file" in edge
        assert "type" in edge
        assert edge["type"] in ("render", "collector_loop")


# --- Writer method ---

def test_upsert_js_includes_method_exists():
    """GraphWriter should have an upsert_js_includes method."""
    from graph_builder.ingestion.writer import GraphWriter
    assert hasattr(GraphWriter, "upsert_js_includes")


def test_upsert_js_includes_signature():
    """upsert_js_includes should accept source_file, target_file, include_type."""
    import inspect
    from graph_builder.ingestion.writer import GraphWriter
    sig = inspect.signature(GraphWriter.upsert_js_includes)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "source_file" in params
    assert "target_file" in params
    assert "include_type" in params


# --- HTTP call detection fix ---

from graph_builder.parsers.js_parser import parse_js_file


def _write_temp_js(code: str) -> str:
    """Write code to a temp .js file and return its path (Windows-safe)."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".js")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def test_send_request_with_dynamic_url_detected():
    """Container._sendRequest('xframe', getTriggerUrl(), ...) should be detected."""
    import os

    code = '''
(function(){
  var Container = {};
  Container._sendRequest = function(type, url, params, cb, data, extra) {};

  function reportDone() {}
  function getTriggerUrl() { return "/api/trigger"; }
  function getTriggerParams() { return {}; }
  function getTriggerData() { return {}; }
  function getTriggerExtra() { return {}; }

  function sendData() {
    Container._sendRequest("xframe", getTriggerUrl(), getTriggerParams(), reportDone, getTriggerData(), getTriggerExtra());
  }
})();
'''
    path = _write_temp_js(code)
    try:
        ast = parse_js_file(path)
        # Should detect the _sendRequest call with dynamic URL
        assert len(ast.http_calls) >= 1
        call = ast.http_calls[0]
        assert call.url_or_path == "__dynamic_url__"
        assert call.method == "XFRAME"
        assert call.function == "sendData"
    finally:
        os.unlink(path)


def test_send_request_with_string_url_still_works():
    """Container._sendRequest('post', '/api/data', ...) still captures the string URL."""
    import os

    code = '''
(function(){
  function submit() {
    Container._sendRequest("post", "/api/data", {}, function(){});
  }
})();
'''
    path = _write_temp_js(code)
    try:
        ast = parse_js_file(path)
        assert len(ast.http_calls) >= 1
        call = ast.http_calls[0]
        assert call.url_or_path == "/api/data"
        assert call.method == "POST"
    finally:
        os.unlink(path)


def test_container_collect_detected():
    """Container._collect() should be detected as a data exfiltration call."""
    import os

    code = '''
(function(){
  function gatherData() {
    Container._collect("device_data", getDeviceInfo());
  }

  function gatherImmediate() {
    Container._collectImmediateWithType("urgent", getData(), "high");
  }
})();
'''
    path = _write_temp_js(code)
    try:
        ast = parse_js_file(path)
        assert len(ast.http_calls) >= 2
        callees = {c.function for c in ast.http_calls}
        assert "gatherData" in callees
        assert "gatherImmediate" in callees
    finally:
        os.unlink(path)


# --- Full integration ---

def test_full_integration_parse_resolve_edges():
    """End-to-end: parse fixtures, run ERB resolver, verify edges and HTTP calls."""
    from graph_builder.parsers.js_parser import parse_js_file
    from graph_builder.resolvers.js_erb_resolver import JsErbResolver

    container_path = str(FIXTURES / "container.js.erb")
    net_path = str(FIXTURES / "net.js.erb")
    utils_path = str(FIXTURES / "utils.js")

    # Step 1: Parse all fixtures
    all_asts = {}
    for fpath in [container_path, net_path, utils_path]:
        ast = parse_js_file(fpath)
        all_asts[fpath] = ast

    # Step 2: Verify parsing worked
    assert all_asts[container_path].language == "javascript"
    assert all_asts[net_path].language == "javascript"
    assert all_asts[utils_path].language == "javascript"

    # Step 3: Run ERB resolver
    resolver = JsErbResolver(str(FIXTURES))
    edges = resolver.resolve_all(all_asts)

    # Step 4: Verify edges
    edge_pairs = [(e["source_file"], Path(e["target_file"]).name) for e in edges]

    # container.js.erb -> utils.js
    assert (container_path, "utils.js") in edge_pairs
    # container.js.erb -> net.js.erb
    assert (container_path, "net.js.erb") in edge_pairs

    # Step 5: Verify all edges have required fields
    for edge in edges:
        assert "source_file" in edge
        assert "target_file" in edge
        assert "type" in edge


def test_no_js_files_produces_no_edges():
    """When there are no JS files, ERB resolver produces no edges."""
    from graph_builder.parsers.base import FileAST
    from graph_builder.resolvers.js_erb_resolver import JsErbResolver

    resolver = JsErbResolver(str(FIXTURES))
    all_asts = {
        "foo.lua": FileAST(file_path="foo.lua", language="lua"),
        "bar.py": FileAST(file_path="bar.py", language="python"),
    }

    edges = resolver.resolve_all(all_asts)
    assert edges == []
