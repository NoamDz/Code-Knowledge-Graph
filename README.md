# BOB Code Knowledge Graph

A polyglot Code Knowledge Graph builder for IBM BOB, designed to index Lua/OpenResty, Python, Ruby, and JavaScript codebases into a queryable graph database (Memgraph), exposed as MCP tools.

## Architecture

```
Your codebase (Lua/Python/Ruby/JS)
        ↓  Tree-sitter parsers (per language)
    Graph Builder (Python)
        ↓  Cypher ingestion
    Memgraph (Docker, in-memory graph DB)
        ↓  Query API
    MCP Server (Python, FastMCP)
        ↓  MCP protocol
    IBM BOB agent
```

## Quick Start

### 1. Start Memgraph
```bash
docker compose up -d
```

### 2. Install dependencies
```bash
pip install -e .
```

### 3. Configure
Create `config.yml` or use environment variables:
```yaml
repo_root: /path/to/your/codebase
nginx_conf: /path/to/nginx.conf  # optional, for OpenResty
memgraph:
  uri: bolt://localhost:7687
```

Or set environment variables:
```bash
export REPO_ROOT=/path/to/your/codebase
export NGINX_CONF=/path/to/nginx.conf
export MEMGRAPH_URI=bolt://localhost:7687
```

### 4. Build the graph
```bash
bob-graph build                    # Full build
bob-graph build -c config.yml      # With config file
bob-graph update                   # Incremental update
bob-graph validate                 # Run validation queries
bob-graph stats                    # Print graph stats
```

### 5. Start the MCP server
```bash
python -m mcp_server.server
```

Register in BOB's MCP config:
```json
{
  "mcpServers": {
    "code-graph": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "MEMGRAPH_URI": "bolt://localhost:7687"
      }
    }
  }
}
```

### 6. Start the file watcher (optional)
```bash
python -m watcher.file_watcher /path/to/your/codebase
```

## MCP Tools Available to BOB

### Navigation
- **get_dependencies** — What does this file import?
- **get_dependents** — What imports this file?
- **get_repo_overview** — Condensed map of most central files
- **get_file_info** — Detailed info about a single file

### Tracing
- **trace_endpoint** — Full code path for an HTTP endpoint
- **trace_call_chain** — Follow calls outgoing/incoming from a function

### Impact Analysis
- **find_impacted_files** — Blast radius of changes to a file
- **find_all_callers** — Every function that calls a given function
- **find_implementors** — All subclasses/implementors of a class
- **find_context_coupling** — Implicit coupling via ngx.ctx/ngx.shared

### Search
- **find_symbol** — Where is a function/class defined?
- **get_module_exports** — Public API of a module
- **get_lua_ngx_usage** — ngx.* APIs used in a Lua file
- **search_files** — Find files by path pattern

## Language Support

| Language | Features Parsed |
|---|---|
| **Lua/OpenResty** | `_M` exports, `require`, `ngx.*` APIs, `pcall` wrappers, `ngx.ctx` coupling, nginx.conf phases |
| **Python** | imports (absolute + relative), classes with inheritance, functions/methods, calls |
| **Ruby** | `require`/`require_relative`, classes, modules, mixins (`include`/`extend`), Sinatra routes |
| **JavaScript** | CommonJS `require`, ESM `import`, classes, functions/arrows, Express routes, exports |

## Testing
```bash
python -m pytest graph_builder/tests/test_parsers.py -v
```

## Project Structure
```
bob-code-graph/
├── docker-compose.yml
├── pyproject.toml
├── graph_builder/
│   ├── main.py              ← CLI: build, update, validate, stats
│   ├── config.py
│   ├── scanner.py
│   ├── change_tracker.py
│   ├── parsers/
│   │   ├── base.py          ← Data models + abstract parser
│   │   ├── lua_parser.py    ← Lua + OpenResty
│   │   ├── python_parser.py
│   │   ├── ruby_parser.py
│   │   ├── js_parser.py
│   │   └── nginx_parser.py  ← nginx.conf entry points
│   ├── resolvers/
│   │   ├── lua_resolver.py
│   │   ├── python_resolver.py
│   │   ├── ruby_resolver.py
│   │   └── js_resolver.py
│   ├── ingestion/
│   │   ├── schema.py        ← Memgraph indexes
│   │   ├── writer.py        ← Batched Cypher writes
│   │   └── incremental.py   ← Single-file re-indexing
│   └── tests/
├── mcp_server/
│   ├── server.py            ← FastMCP server
│   ├── query_engine.py
│   └── tools/
│       ├── navigation.py
│       ├── tracing.py
│       ├── impact.py
│       └── search.py
└── watcher/
    └── file_watcher.py      ← Live incremental updates
```
