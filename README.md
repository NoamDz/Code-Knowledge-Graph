# Code Knowledge Graph

A polyglot code indexer that parses Lua/OpenResty, Python, Ruby, JavaScript, and Go with Tree-sitter, builds a semantic graph in Memgraph, and exposes it to coding agents through a small MCP tool surface.

Built for IBM BOB; the MCP server is transport-standard (stdio + JSON-RPC) and works with any MCP-compatible agent.

## What the agent gets

Seven tools, designed around task shapes rather than graph primitives. See `DESIGN.md` for the rationale.

**Composites — task-shaped answers:**
- `explain_flow(endpoint)` — phase chain, call graph, reroutes, cross-service HTTP calls for an endpoint. Middleware collapsed by default; `escape_hatch=true` to expand.
- `find_impact(symbol_or_file)` — blast radius: direct callers, transitive dependents, plus implicit couplings (`ngx.ctx`, `ngx.shared`, Redis keys, HTTP calls).
- `onboard_to(area)` — ramp-up pack for a subsystem: central files, public exports, entry endpoints, Redis keys touched.
- `locate(description)` — natural-language localization. v1 ranks grep hits by graph centrality (no embeddings).

**Read primitives — kept for direct access:**
- `get_code_snippet(name)` — source text for a symbol.
- `get_file_outline(file_path)` — functions, classes, exports, imports.
- `find_symbol(name, scope=None)` — symbol lookup; with `scope` acts as module-exports.

Operator tools (`code-graph validate`, `code-graph stats`, `code-graph spot-check`) live on the CLI and are not exposed to the agent.

## Quick start

Prereqs: Docker (with compose v2), Python ≥ 3.10, `make`.

```bash
# 1. Clone and install the CLI
git clone <repo-url> code-graph && cd code-graph
pip install -e .

# 2. Configure
cp .env.example .env      # edit REPO_ROOT to point at the codebase to index
cp config_example.yml config.yml   # if one is provided; otherwise see below

# 3. Start Memgraph, create indexes, build the graph
make rebuild CONFIG=config.yml

# 4. Run the MCP server (stdio)
make mcp
```

The first `make rebuild` starts Memgraph on `localhost:7687`, runs `code-graph schema`, then `code-graph build`. Re-run `make rebuild` after editing the target codebase — `build` wipes the graph and rebuilds it from scratch.

## Make targets

| Target | What it does |
|---|---|
| `make up` | Start Memgraph in the background |
| `make down` | Stop all services |
| `make logs` | Tail Memgraph logs |
| `make schema` | Create Memgraph indexes |
| `make build-graph` | Full graph build from `CONFIG` (default `config.yml`) |
| `make rebuild` | `down` → `up` → `schema` → `build-graph` |
| `make build-image` | Build the MCP server Docker image |
| `make mcp` | Run the MCP server locally over stdio |
| `make clean` | Stop services and delete the Memgraph volume |

## Configuration

`config.yml` (copy from `config_example.yml` if present; otherwise minimal):

```yaml
repo_root: /path/to/your/codebase
nginx_conf: /path/to/nginx.conf       # optional (OpenResty endpoint tracing)
memgraph:
  uri: bolt://localhost:7687
ignore_patterns:
  - node_modules
  - .git
  - dist
```

Environment variables (see `.env.example`):

| Var | Default | Purpose |
|---|---|---|
| `MEMGRAPH_URI` | `bolt://localhost:7687` | Bolt endpoint for the graph DB |
| `REPO_ROOT` | `.` | Repo mounted read-only into the MCP container |
| `CODE_GRAPH_MIDDLEWARE_FILES` | built-in | Comma-separated file substrings treated as middleware in `explain_flow` |
| `CODE_GRAPH_MIDDLEWARE_FUNCTIONS` | built-in | Comma-separated function-name substrings treated as middleware |

## Registering with an MCP client

Stdio transport — run the server directly:

```json
{
  "mcpServers": {
    "code-graph": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": { "MEMGRAPH_URI": "bolt://localhost:7687" }
    }
  }
}
```

Or via Docker. Two forms — pick based on whether your MCP client lets you set a working directory.

**With `cwd` support** (Claude Desktop, most modern clients) — uses the compose `mcp` service so it inherits networking and volume mounts:

```json
{
  "mcpServers": {
    "code-graph": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "-T", "mcp"],
      "cwd": "/abs/path/to/code-graph",
      "env": { "REPO_ROOT": "/abs/path/to/your/codebase" }
    }
  }
}
```

**Without `cwd` support** — call `docker run` directly. You must build the image first (`make build-image`) and know the compose-network name (`<project-dir>_default`):

```json
{
  "mcpServers": {
    "code-graph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--network", "code-graph_default",
        "-e", "MEMGRAPH_URI=bolt://memgraph:7687",
        "-v", "/abs/path/to/your/codebase:/repo:ro",
        "code-graph-mcp:local"
      ]
    }
  }
}
```

## Keeping the graph fresh

```bash
code-graph build -c config.yml         # Wipe and rebuild — the only way to index
```

There is no incremental path. Cross-file edges (calls, requires, trigger pub/sub,
dirty-flag signalling) are resolved against the whole corpus, so a single changed
file can add or remove edges anywhere in the graph. Re-indexing that file alone
cannot know which. Rebuilding is cheap enough to make the alternative not worth
its correctness cost.

## Language support

| Language | What's parsed |
|---|---|
| **Lua / OpenResty** | `_M` exports, `require`, `ngx.*` APIs, `pcall` wrappers, `ngx.ctx` read/write coupling, `ngx.shared` dict usage, nginx.conf phases + endpoints |
| **Python** | absolute + relative imports, classes + inheritance, functions + methods, calls |
| **Ruby** | `require` / `require_relative`, classes, modules, mixins, Sinatra routes |
| **JavaScript** | CommonJS `require`, ESM `import`, classes, functions + arrows, Express routes, exports |
| **Go** | packages, imports, structs, methods |

## Graph schema (summary)

Nodes: `File`, `Module`, `Function`, `Class`, `Endpoint`, `NginxPhase`, `ContextKey`, `SharedDict`, `RedisKey`.

Edges: `IMPORTS`, `REQUIRES`, `DEFINES`, `CALLS`, `HANDLES`, `HAS_PHASE`, `EXTENDS`, `INCLUDES`, `CTX_READS`, `CTX_WRITES`, `USES_SHARED`, `REDIS_READS`, `REDIS_WRITES`, `HTTP_CALLS`, `REROUTES_TO`.

## Testing

```bash
python -m pytest graph_builder/tests -v
```

## Project layout

```
.
├── DESIGN.md                 # agent-surface design decisions
├── Dockerfile                # MCP server image
├── docker-compose.yml        # Memgraph + mcp profile
├── Makefile
├── pyproject.toml
├── config_example.yml
├── graph_builder/            # scanner, parsers, resolvers, ingestion
├── mcp_server/
│   ├── server.py             # FastMCP, 7-tool surface
│   ├── query_engine.py
│   └── tools/
│       ├── composites.py     # explain_flow, find_impact, onboard_to, locate
│       ├── navigation.py
│       ├── tracing.py
│       ├── impact.py
│       ├── search.py
│       └── snippets.py
```

## License

TBD.
