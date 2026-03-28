# JS IIFE Connection Model — Design Spec

**Date:** 2026-03-26
**Goal:** Connect 94 orphaned JavaScript files by modeling the ERB render-chain inclusion hierarchy that assembles them into bundles.

**Context:** BOB's Round 5 investigation revealed the JS architecture is fundamentally different from what we assumed. There are no `window.*` globals — everything runs inside one giant IIFE. The connection mechanism is Ruby ERB template rendering: `container.js.erb` includes `net.js.erb` via `<%=env["template"].render("net.js.erb", env)%>`.

---

## Architecture Insight

The JS bundle is assembled at build time by the Ruby generator:

```
(function(){                           ← container.js.erb line 3
  <%=env["template"].render("base64.js", env)%>     ← Layer 1: Utilities
  <%=env["template"].render("json.js", env)%>
  <%=env["template"].render("utils.js", env)%>
  <%=env["template"].render("net.js.erb", env)%>    ← Layer 2: Network

  var Container = (function(){...})();              ← Layer 3: Container

  <% env['collectors_rendered'].each { |code| %>    ← Layer 4: Collectors
    <%=code%>
  <% } %>

  Container._setup();
})();
```

**File categories (94 total):**
- Core infrastructure: 28 files (`src/lib/js/`)
- Container framework: 3 files (`src/common/base/js/`)
- ATO collectors: 19 files
- Malware collectors: 14 files
- Common collectors: 15 files
- Intelligent snippet/loader: 10 files
- Obfuscation: 2 files
- Other: 3 files

---

## 1. ERB Render-Chain Edge Detection

### Problem

JS files are connected through Ruby ERB `render()` calls, not JavaScript `require()` or `import`. The existing `JsResolver` only handles CommonJS/ESM patterns, finding zero connections.

### Solution

Create a new resolver that parses `.js.erb` files for ERB render calls BEFORE the ERB tags are stripped.

**Pattern to detect:**
```ruby
env["template"].render("filename.js.erb", env)
env['template'].render("filename.js", env)
env["template"].render("path/to/file.js.erb", env)
```

**Regex:**
```python
ERB_RENDER_PATTERN = re.compile(
    r'''env\[['"]template['"]\]\.render\(\s*['"]([^'"]+)['"]\s*,'''
)
```

**Algorithm:**
1. For each `.js.erb` file, read the raw content (before ERB stripping)
2. Extract all `render("filename", env)` calls
3. Resolve each filename to a file path:
   - Search in the same directory as the rendering file
   - Search in `src/lib/js/` (shared utilities)
   - Search in `src/common/base/js/`
   - Search across all known JS directories
4. Create `INCLUDES` edges from the rendering file to the included file

**Collector rendering pattern:**
`container.js.erb` includes collectors via a loop:
```ruby
<% env['collectors_rendered'].each { |code| %> <%=code%> <% } %>
```

This is populated by `tasks.rb`:
```ruby
snippet['collectors'].each { |collector_path|
  content = template.render(collector_path, env)
  generated << content
}
```

For the collector loop, we can't resolve specific files from the ERB (it's runtime data). Instead, create `INCLUDES` edges from `container.js.erb` to all collector entry-point templates (files in `*/templates/*.js.erb` that are top-level collectors, not sub-templates). The sub-templates are included by their parent collector via explicit `render()` calls which we DO detect.

**Handling nested includes:**
Sub-templates include other sub-templates:
- `device_container.js.erb` renders `device_id.js.erb`, `global_device_id.js.erb`, `device_utils.js.erb`, `sensor.js.erb`
- `behave.js.erb` renders `mouse_movements.js.erb`, `keystrokes.js.erb`, `metastrokes.js.erb`

These are direct `render()` calls and will be detected by the regex.

### Expected Result

A tree structure:
```
container.js.erb
├── base64.js
├── json.js
├── utils.js
├── rc4.js.erb
├── sha256.js.erb
├── net.js.erb
├── DOMLoadedHelper.js.erb
├── task_queue.js
├── ...  (28 core utility includes)
├── device_container.js.erb (collector)
│   ├── device_id.js.erb
│   ├── global_device_id.js.erb
│   ├── device_utils.js.erb
│   └── sensor.js.erb
├── behave.js.erb (collector)
│   ├── mouse_movements.js.erb
│   ├── keystrokes.js.erb
│   └── metastrokes.js.erb
└── ... (other collectors)
```

**Expected edges:** ~60-70 INCLUDES edges
**Expected orphan reduction:** 94 → ~10-15 (remaining orphans would be files only included conditionally or by the intelligent snippet system)

---

## 2. JS HTTP Call Detection Fix

### Problem

`Container._sendRequest` pattern was added to the JS parser but detects 0 calls. BOB showed the actual call sites use transport type strings like `"xframe"` as the first argument, not a URL:

```javascript
Container._sendRequest("xframe", getTriggerUrl(), getTriggerParams(), reportDone, getTriggerData(), getTriggerExtra());
```

The first argument is the transport method, the second is the URL (often a function call, not a string literal).

### Solution

Update the JS parser's HTTP call detection in `_extract_js_http_calls()` (line 462 of `js_parser.py`).

The existing code already reads `args.named_children[0]` as `method_arg` and `args.named_children[1]` as `url_arg`. The problem is NOT argument order — it's that the URL argument is typically a function call (`getTriggerUrl()`), not a string literal, so `_try_get_string()` returns `None`, and the `if url:` check causes the detection to be skipped entirely.

**Fix:**
1. When `url` is `None` (non-string URL argument), use `"__dynamic_url__"` placeholder instead of skipping
2. Also detect `Container._collect()` and `Container._collectImmediateWithType()` as data exfiltration calls (they eventually call `Net._request`)

**Implementation file:** `graph_builder/parsers/js_parser.py` — update `_extract_js_http_calls()` method.

**Expected impact:** 5-8 HTTP_CALLS edges detected in malware collector files.

---

## Testing Strategy

### Unit Tests

1. **ERB render detection:**
   - File with `env["template"].render("net.js.erb", env)` → INCLUDES edge to net.js.erb
   - File with `env['template'].render("utils.js", env)` → INCLUDES edge to utils.js
   - File with multiple render calls → multiple INCLUDES edges
   - File with no render calls (plain .js) → no INCLUDES edges
   - Nested: device_container renders device_id → transitive chain detected

2. **Collector loop detection:**
   - container.js.erb with `collectors_rendered.each` → INCLUDES edges to collector entry points

3. **HTTP call fix:**
   - `Container._sendRequest("xframe", url, ...)` → HTTP_CALLS edge with dynamic URL
   - `Container._sendRequest(null, hashRequestPath, ...)` → HTTP_CALLS edge

### Integration Verification

After implementation, run `code-graph health` and verify:
- JS orphan files drop from 94 to ~10-15
- JS import resolution shows new INCLUDES edges
- HTTP calls for JS increase from 0 to 5-8

---

## Expected Impact Summary

| Component | Impact |
|-----------|--------|
| ERB render-chain edges | 94 → ~10-15 orphans, ~60-70 INCLUDES edges |
| HTTP call detection fix | 0 → 5-8 HTTP_CALLS edges |

---

## Files Modified/Created

| File | Change |
|------|--------|
| `graph_builder/resolvers/js_erb_resolver.py` | **New** — ERB render-chain parser and resolver |
| `graph_builder/parsers/js_parser.py` | Fix `_sendRequest` HTTP detection argument order |
| `graph_builder/ingestion/writer.py` | Add `upsert_js_includes()` for INCLUDES edges (note: INCLUDES edge type already exists in schema per CLAUDE.md) |
| `graph_builder/main.py` | Wire `JsErbResolver` into build pipeline |
| `graph_builder/tests/test_js_iife_connection.py` | New test file |
