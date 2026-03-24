# Graph-Based Code Retrieval: A Technical Deep Dive

## How Code Knowledge Graphs Work, How They're Built, and How They Handle Polyglot Enterprise Codebases

---

## 1. What Graph-Based Retrieval Actually Is

Graph-based code retrieval replaces the "code as flat text" paradigm with a **directed property graph** where nodes represent code entities (files, classes, functions, variables, imports) and edges represent typed relationships between them (defines, calls, imports, inherits, contains). The fundamental insight — validated by RepoGraph (ICLR 2025), LocAgent (ACL 2025), and KGCompass (2025) — is that code has **inherent graph structure** that flat embedding-based search destroys.

When you embed a function into a 768-dimensional vector and store it in a vector DB, you lose the fact that `validate_token()` is called by `auth_middleware()`, which is invoked by `nginx access_by_lua_block` for the `/api/*` location. Vector similarity might tell you `validate_token` is *related* to `auth_middleware` (they share semantic space), but it cannot trace the **directed dependency chain** — and that chain is exactly what matters when you ask "what breaks if I change `validate_token`'s signature?"

Graph-based retrieval answers these structural questions through **graph traversal** (BFS, DFS, ego-graph extraction, multi-hop neighbor queries) rather than approximate nearest-neighbor search.

---

## 2. Anatomy of a Code Knowledge Graph

### 2.1 The Node Types

Every code graph system converges on a similar set of node types, regardless of implementation:

```
Node Types (universal across systems):
├── File         — a source file, with path, language, modification time
├── Module       — a named grouping (Python module, Lua _M table, JS/TS module, Ruby module)
├── Class        — a class or struct definition
├── Function     — a function, method, or callable
├── Variable     — a constant, global, or significant variable
├── Endpoint     — an HTTP route or API entry point (framework-specific)
└── Import       — an import statement (sometimes inlined as an edge property)
```

The granularity varies significantly between systems:

| System | Node Granularity | What Each Node Represents |
|--------|-----------------|--------------------------|
| **RepoGraph** | Code line | Each node = one line of code (def or ref) |
| **LocAgent** | Code entity | Each node = a file, class, or function |
| **Code-Graph-RAG** | Code entity | Each node = function, class, module |
| **Aider repo-map** | Symbol | Each node = a named identifier (function/class name) |
| **Your bob-code-graph** | Code entity + OpenResty | Each node = function, class, module, endpoint, nginx phase |

### 2.2 The Edge Types

Edges encode how entities relate. These are directed and typed:

```
Edge Types:
├── DEFINES      — File → Function/Class ("this file defines this function")
├── IMPORTS      — File → File ("this file imports/requires that file")
├── CALLS        — Function → Function ("this function calls that function")
├── CONTAINS     — Class → Method ("this class contains this method")
├── INHERITS     — Class → Class ("this class extends that class")
├── IMPLEMENTS   — Class → Interface
├── INVOKES      — Function → Function (cross-file, resolved)
└── [domain-specific edges]:
    ├── HANDLES      — Endpoint → Function (OpenResty: nginx phase → Lua handler)
    ├── CTX_READS    — Function → ContextKey (ngx.ctx implicit coupling)
    └── EXPORTS      — Module → Function (public API)
```

The critical distinction is between **within-file** edges (deterministic, from AST parsing) and **cross-file** edges (require resolution logic to match an import string like `require "resty.auth"` to an actual file path).

### 2.3 The Properties

Nodes and edges carry metadata that makes them useful for retrieval:

```python
# Example node properties (from RepoGraph's Tag namedtuple):
Tag = namedtuple("Tag", [
    "rel_fname",   # relative file path
    "fname",       # absolute file path
    "line",        # [start_line, end_line]
    "name",        # symbol name ("validate_token", "AuthService")
    "kind",        # "def" or "ref"
    "category",    # "class" or "function"
    "info",        # for def: full function text; for class: list of method names
])
```

---

## 3. RepoGraph: The Actual Implementation Dissected

I cloned and analyzed the RepoGraph repository (`github.com/ozyyshr/RepoGraph`). The codebase is surprisingly compact — the core is three files:

```
repograph/
├── construct_graph.py   (592 lines — graph construction)
├── graph_searcher.py    (45 lines  — BFS/DFS retrieval)
└── utils.py             (101 lines — Python AST parsing utilities)
```

### 3.1 Step 1: Repository Structure Extraction (`utils.py`)

Before any tree-sitter parsing happens, `create_structure()` walks the entire repository and builds a nested dictionary mirroring the file system. For every `.py` file, it uses Python's built-in `ast` module (not tree-sitter) to extract:

```python
def parse_python_file(file_path):
    parsed_data = ast.parse(file_content)
    class_info = []      # {name, start_line, end_line, text, methods[]}
    function_names = []   # {name, start_line, end_line, text}
    
    for node in ast.walk(parsed_data):
        if isinstance(node, ast.ClassDef):
            methods = [...]  # extract each FunctionDef in class body
            class_info.append({
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "text": file_content.splitlines()[node.lineno-1 : node.end_lineno],
                "methods": methods,
            })
```

This pre-pass gives the system **authoritative line ranges** for every class and function. This is important — tree-sitter's tag queries give you the AST node positions, but RepoGraph cross-references them with Python `ast` for exact line numbers.

**Key limitation**: `utils.py` only handles `.py` files (`if file_name.endswith(".py")`). Similarly, `find_files()` in `construct_graph.py` filters to `.py` only. **RepoGraph as published is Python-only**, despite the paper's broader claims about language support.

### 3.2 Step 2: Tree-sitter Tag Extraction (`construct_graph.py`)

The core of RepoGraph is `get_tags_raw()`, which uses tree-sitter to find **definitions** and **references** at the code-line level. Here's the actual tree-sitter query used (hardcoded in the source):

```scheme
;; Tree-sitter query for Python
(class_definition
  name: (identifier) @name.definition.class) @definition.class

(function_definition
  name: (identifier) @name.definition.function) @definition.function

(call
  function: [
    (identifier) @name.reference.call
    (attribute
      attribute: (identifier) @name.reference.call)
  ]) @reference.call
```

This query captures three things:
1. **Class definitions** — `class Foo:` produces a `def` tag for `Foo`
2. **Function definitions** — `def bar():` produces a `def` tag for `bar`
3. **Function calls** — `bar()` or `obj.bar()` produces a `ref` tag for `bar`

For each match, the code determines if it's a `def` or `ref`:

```python
for node, tag in captures:
    if tag.startswith("name.definition."):
        kind = "def"
    elif tag.startswith("name.reference."):
        kind = "ref"
    
    tag_name = node.text.decode("utf-8")
    
    # Filter out standard library and third-party functions
    if tag_name in std_funcs:    # from import analysis
        continue
    elif tag_name in builtins_funs:  # len, print, list, dict, etc.
        continue
```

### 3.3 Step 3: Filtering Out Non-Project References

This is the most underappreciated step. RepoGraph's `std_proj_funcs()` method analyzes every import statement in each file using Python's `ast` module, then **actually executes the import** to discover what functions the third-party library provides:

```python
def std_proj_funcs(self, code, fname):
    """Identify functions from standard/third-party libraries."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_statement = codelines[node.lineno-1].strip()
            try:
                exec(import_statement)  # Actually runs the import!
            except:
                continue
            eval_name = alias.name if alias.asname is None else alias.asname
            std_funcs.extend([
                name for name, member 
                in inspect.getmembers(eval(eval_name)) 
                if callable(member)
            ])
```

This is bold — it literally runs `exec(import_statement)` on every import to enumerate callable members. The result: when tree-sitter finds a call to `json.dumps()`, it knows `dumps` comes from the `json` standard library and **excludes it** from the graph. Only project-internal references become graph nodes.

For builtins, it additionally collects all members of `builtins`, `list`, `dict`, `set`, `str`, and `tuple` to filter out calls like `len()`, `append()`, `keys()`, etc.

### 3.4 Step 4: Graph Assembly (`tag_to_graph()`)

The filtered tags become a NetworkX `MultiDiGraph`:

```python
def tag_to_graph(self, tags):
    G = nx.MultiDiGraph()
    
    # Add all tags as nodes
    for tag in tags:
        G.add_node(tag['name'], 
                   category=tag['category'],
                   info=tag['info'],      # function body text or class methods
                   fname=tag['fname'],     # file path
                   line=tag['line'],       # [start, end] line numbers
                   kind=tag['kind'])       # "def" or "ref"
    
    # Edge type 1: class CONTAINS method
    for tag in tags:
        if tag['category'] == 'class':
            class_funcs = tag['info'].split('\t')
            for f in class_funcs:
                G.add_edge(tag['name'], f.strip())
    
    # Edge type 2: ref INVOKES def (name matching)
    tags_ref = [tag for tag in tags if tag['kind'] == 'ref']
    tags_def = [tag for tag in tags if tag['kind'] == 'def']
    for tag in tags_ref:
        for tag_def in tags_def:
            if tag['name'] == tag_def['name']:
                G.add_edge(tag['name'], tag_def['name'])
    
    return G
```

**This is the key insight**: cross-file edges are created by **name matching** — if a `ref` tag named `validate_token` exists in `middleware.py` and a `def` tag named `validate_token` exists in `auth.py`, an edge connects them. No import resolution, no type analysis, no LSP — just name matching.

This is both the strength and weakness of the approach:
- **Strength**: Dead simple, no language-specific import resolution logic needed
- **Weakness**: Name collisions create false edges (if two different files each define a function called `process()`, all references to `process` get edges to both definitions)

### 3.5 Step 5: Retrieval via Ego-Graph Extraction (`graph_searcher.py`)

At query time, the agent provides a keyword (e.g., `"validate_token"`). The searcher extracts a local subgraph:

```python
class RepoSearcher:
    def one_hop_neighbors(self, query):
        return list(self.graph.neighbors(query))
    
    def two_hop_neighbors(self, query):
        one_hop = self.one_hop_neighbors(query)
        two_hop = []
        for node in one_hop:
            two_hop.extend(self.one_hop_neighbors(node))
        return list(set(two_hop))
    
    def bfs(self, query, depth):
        visited = []
        queue = [(query, 0)]
        while queue:
            node, level = queue.pop(0)
            if node not in visited:
                visited.append(node)
                if level < depth:
                    queue.extend(
                        [(n, level + 1) for n in self.one_hop_neighbors(node)]
                    )
        return visited
```

The retrieved ego-graph (all nodes within N hops of the query) is then serialized as text context for the LLM. For each node, the `info` field contains the actual function body (for `def` nodes) or the code line (for `ref` nodes), so the LLM gets real source code, not just names.

### 3.6 Integration: How RepoGraph Feeds an Agent

For **procedural frameworks** (like Agentless), RepoGraph context is injected at each pipeline step — localization, repair generation, verification. The function `construct_code_graph_context()` takes the localized files/functions, queries the graph for their ego-graphs, and appends the result to the LLM prompt.

For **agent frameworks** (like SWE-agent), RepoGraph adds a new action `search_repo` to the agent's action space:

```
search_repo <search_term>
→ Returns def and ref relations for the search term
```

The agent can call this action at any point during its exploration, getting back the subgraph context alongside file reads, grep results, etc.

---

## 4. LocAgent: The Heterogeneous Graph Approach

LocAgent (ACL 2025, from Yale/Stanford/All Hands AI) takes a more structured approach with a **directed heterogeneous graph**. Where RepoGraph is flat (all nodes are "tags"), LocAgent explicitly types its graph:

```
Node types V: {File, Class, Function}
Edge types R: {contain, import, invoke, inherit}
```

### 4.1 Graph Construction

LocAgent parses each Python file to extract:
- **Structural containment**: File → Class → Method hierarchy via `contain` edges
- **Import relationships**: `import` edges from resolved import statements
- **Invocations**: `invoke` edges from function calls (cross-file, resolved)
- **Inheritance**: `inherit` edges from class declarations

The key difference from RepoGraph: LocAgent **resolves imports** to actual file paths, creating precise cross-file edges rather than relying on name matching. This eliminates the false-positive problem of name collisions.

### 4.2 Sparse Hierarchical Entity Indexing

LocAgent builds two index layers:
1. **Upper index**: Maps entity names to qualified identifiers (`auth.py:AuthService.validate_token`)
2. **Lower index**: BM25 sparse index over entity names for fuzzy matching

When the agent searches for a keyword, it first does exact lookup in the upper index, then falls back to fuzzy BM25 search in the lower index.

### 4.3 Agent Tools

LocAgent exposes graph operations as tools the LLM agent can call:

- **SearchEntity**: Find code entities by name (exact or fuzzy)
- **GetEntityCode**: Retrieve source code for a specific entity at configurable detail levels (full, preview/skeleton, or folded)
- **TraverseGraph**: Walk the graph from a given entity, returning neighbors by edge type

The output format adapts to result size: full code for ≤3 matched entities, module skeleton for larger files, folded output (just signatures) for very large result sets.

### 4.4 Results

On SWE-Bench Lite, LocAgent with a fine-tuned Qwen-2.5-32B achieved **92.7% file-level localization accuracy** — comparable to Claude 3.5 Sonnet at ~86% cost reduction. The ablation study showed that removing graph guidance dropped accuracy significantly, confirming the graph structure provides genuine signal beyond what text search alone delivers.

---

## 5. Making Graphs Language-Agnostic: The Tree-sitter Strategy

The common thread across all systems is **tree-sitter** as the parsing layer. Here's exactly how language-agnostic graph construction works:

### 5.1 The Core Abstraction

Tree-sitter provides a **uniform API** across all languages: parse source code → get an AST → run structured queries against it. The language-specific part is the **grammar** (which defines the AST node types) and the **tag queries** (which map language-specific AST patterns to universal concepts).

```
For each language, you need:
1. A tree-sitter grammar     → defines AST node types for the language
2. A set of tag queries       → maps AST patterns to "def" and "ref" tags
3. An import resolver          → maps import strings to file paths
4. A filtering list            → identifies builtins/stdlib to exclude
```

### 5.2 Tag Query Patterns Per Language

Here's what the tree-sitter queries look like for each language in a polyglot system:

**Python:**
```scheme
(class_definition name: (identifier) @name.definition.class)
(function_definition name: (identifier) @name.definition.function)
(call function: [(identifier) @name.reference.call
                  (attribute attribute: (identifier) @name.reference.call)])
(import_from_statement module_name: (dotted_name) @name.reference.import)
```

**JavaScript/TypeScript:**
```scheme
(class_declaration name: (identifier) @name.definition.class)
(function_declaration name: (identifier) @name.definition.function)
(arrow_function) @definition.function  ; needs parent context for name
(call_expression function: [(identifier) @name.reference.call
                             (member_expression property: (property_identifier) @name.reference.call)])
(import_statement source: (string) @name.reference.import)
```

**Ruby:**
```scheme
(class name: (constant) @name.definition.class)
(method name: (identifier) @name.definition.function)
(call method: (identifier) @name.reference.call)
(call receiver: (constant) @name.reference.call method: (identifier) @name.reference.call)
```

**Lua (OpenResty):**
```scheme
(function_declaration name: (_) @name.definition.function)
(local_function name: (identifier) @name.definition.function)
(assignment_statement
  (variable_list (dot_index_expression) @name)
  (expression_list (function_definition) @func))  ; _M.func = function()
(function_call name: (identifier) @func_name
  arguments: (arguments (string) @name.reference.import))  ; require "x"
```

### 5.3 The Unified Graph Schema

Code-Graph-RAG demonstrates the cleanest version of this pattern. Their `language_config.py` maps each language to a specification:

```python
# Simplified from Code-Graph-RAG's approach
class LanguageSpec:
    function_node_types: tuple  # e.g., ("function_definition",) for Python
    class_node_types: tuple     # e.g., ("class_definition",) for Python
    import_node_types: tuple    # e.g., ("import_statement", "import_from_statement")
    call_node_types: tuple      # e.g., ("call",) for Python
    module_node_types: tuple    # e.g., ("module",) for Python
```

When adding a new language (say, C#), the auto-detection looks at the tree-sitter grammar's `node-types.json` and maps:

```
Auto-detected for C#:
  Functions: ['destructor_declaration', 'method_declaration', 'constructor_declaration']
  Classes:   ['struct_declaration', 'enum_declaration', 'interface_declaration', 'class_declaration']
  Modules:   ['compilation_unit', 'file_scoped_namespace_declaration', 'namespace_declaration']
  Calls:     ['invocation_expression']
```

All of these map into the **same graph schema** — a `Function` node, a `Class` node, a `CALLS` edge — regardless of source language. This is how polyglot graphs work: the parsing is language-specific, but the graph representation is universal.

### 5.4 Cross-Language Communication

This is where it gets harder. Three distinct patterns exist in enterprise codebases:

**Pattern 1: Shared module imports (same runtime)**

Lua `require "auth"` → `auth.lua`, Python `from auth import validate` → `auth.py`.

These are handled by **language-specific resolvers** that understand each language's module resolution algorithm. For your OpenResty stack, this means replicating `lua_package_path` logic; for Python, understanding `sys.path`; for Ruby, `$LOAD_PATH` and `require_relative`.

**Pattern 2: Cross-language calls via FFI or bindings**

Python calling C extensions, Ruby calling native extensions, Lua calling C via FFI. These generally can't be statically traced — the graph should mark them as **external** or **unresolved** rather than silently ignoring them.

**Pattern 3: Service-to-service communication (HTTP, RPC, message queues)**

This is the hardest case. When your Ruby service calls your Python service over HTTP, no static analysis will find that connection. The approaches being used in production:

- **API contract matching**: Parse OpenAPI/Swagger specs, Protobuf definitions, or GraphQL schemas. Match client call URLs/method names to server endpoint definitions. This creates `CALLS_SERVICE` edges across language boundaries.

- **Configuration-driven**: Parse `nginx.conf` (which you're already doing), Docker Compose, Kubernetes manifests, or service mesh configurations to discover which services communicate.

- **ngx.ctx / shared state**: Your OpenResty-specific pattern where Lua modules communicate implicitly through `ngx.ctx.field_name`. This requires custom detection of read/write patterns (as you've already planned in your implementation).

- **Multi-repo graph merging**: Code-Graph-RAG supports indexing multiple repositories into a single graph. If repo A exports an HTTP endpoint `/api/users` and repo B's code contains a request to `/api/users`, the graph can create a cross-repo edge. This requires parsing HTTP client calls (requests, fetch, etc.) and matching them to endpoint definitions.

Sourcegraph's SCIP protocol handles this at the index level — their cross-repo navigation works because SCIP symbols use a globally-unique naming scheme:

```
scip-python python package-name 1.0.0 module/path/ClassName#method_name()
```

When the same symbol appears in two different SCIP indexes (one as a definition, one as a reference), Sourcegraph's backend joins them.

---

## 6. The Resolution Problem: From "Name" to "Actual Entity"

This is the technical crux that separates toy implementations from production-grade systems.

### 6.1 Name Matching (RepoGraph's Approach)

```
ref "validate_token" in file A  ←→  def "validate_token" in file B
```

**Pros**: Zero configuration, works across languages, no import analysis needed.

**Cons**: False positives from name collisions. If `utils.py` and `helpers.py` both define `process()`, every reference to `process` anywhere gets edges to both. In a 1000-file codebase, common names like `get`, `process`, `handle`, `init` create noise.

### 6.2 Import-Based Resolution (Your bob-code-graph Approach)

```
File A: require "resty.auth"  → resolver → /path/to/resty/auth.lua
File B: from auth.service import validate  → resolver → /path/to/auth/service.py
```

Each language gets a resolver that understands module path conventions:

```python
class LuaResolver:
    def resolve(self, module_string: str) -> str | None:
        # "resty.auth" → resty/auth.lua via lua_package_path
        for template in self.package_paths:
            candidate = template.replace("?", module_string.replace(".", "/"))
            if os.path.exists(candidate):
                return candidate
        return None  # External library
```

**Pros**: Precise cross-file edges, no false positives from name collisions.

**Cons**: Must implement per-language resolution logic, handle edge cases (dynamic requires, conditional imports, re-exports).

### 6.3 LSP-Based Resolution (Highest Fidelity)

Use the actual language server to resolve symbols:

```
textDocument/definition("validate_token", file_A, line_42, col_8)
→ {uri: "file:///path/to/auth.py", range: {start: {line: 15, character: 4}}}
```

**Pros**: Compiler-accurate, handles polymorphism, dynamic dispatch, type inference.

**Cons**: Requires running a language server per language, initial indexing time (30-90s per language for medium codebases), doesn't work for inline code (e.g., Lua in nginx.conf).

### 6.4 SCIP-Based Resolution (Sourcegraph's Approach)

SCIP indexers run during the build process and produce a Protobuf-encoded index of every symbol occurrence with a globally-unique identifier:

```protobuf
message Occurrence {
  repeated int32 range = 1;         // [startLine, startCol, endLine, endCol]
  string symbol = 2;                // e.g., "scip-python python django 4.2 db/models/fields#DurationField#"
  int32 symbol_roles = 3;           // Definition, Reference, Import, etc.
}
```

**Pros**: Compiler-accurate (uses the actual build system), cross-repo by design, cross-language via shared symbols (Protobuf → Java/Go).

**Cons**: Requires build system integration, language-specific indexers (currently Go, TypeScript, Java, Python, Ruby, Rust, C++), not real-time (runs in CI/CD).

---

## 7. Graph Storage: In-Memory vs. Database

### 7.1 NetworkX (In-Memory, Python)

Used by RepoGraph and Aider. The graph is a Python object serialized with pickle.

```python
import networkx as nx
G = nx.MultiDiGraph()
G.add_node("validate_token", kind="def", file="auth.py", line=[15, 30])
G.add_edge("middleware.check_auth", "validate_token", type="CALLS")

# Retrieval: simple graph traversal
neighbors = list(G.neighbors("validate_token"))
# Or ego-graph:
subgraph = nx.ego_graph(G, "validate_token", radius=2)
```

**When to use**: Codebases < ~50K files, single-machine use, no need for persistence across processes.

### 7.2 Memgraph (In-Memory Graph DB, Cypher)

Used by Code-Graph-RAG and your bob-code-graph. Runs as a Docker container, queried via Bolt protocol using Cypher.

```cypher
-- Find all callers of a function, 2 hops deep
MATCH path = (caller:Function)-[:CALLS*1..2]->(fn:Function {name: "validate_token"})
RETURN caller.name, caller.file, length(path) as depth
ORDER BY depth;

-- Impact analysis: what files are affected by a change?
MATCH (f:File {path: "auth.py"})<-[:DEFINES]-(fn:Function)
MATCH (caller:Function)-[:CALLS]->(fn)
MATCH (caller_file:File)-[:DEFINES]->(caller)
RETURN DISTINCT caller_file.path AS affected_file;
```

**When to use**: Medium to large codebases, need for Cypher query expressiveness, multi-process access (MCP server + watcher + CLI), real-time incremental updates.

### 7.3 SQLite + Vector Extensions

Used by er77/code-graph-rag-mcp and CodeGraph CLI. Stores the graph as an adjacency list alongside vector embeddings.

```sql
-- entities table
CREATE TABLE entities (id, name, type, filePath, code, embedding BLOB);
-- relationships table  
CREATE TABLE relationships (sourceId, targetId, type);
-- type can be: "calls", "imports", "extends", "contains"
```

**When to use**: Single-file deployment, no external services, combined structural + semantic search.

---

## 8. Retrieval Strategies: How Agents Actually Query the Graph

### 8.1 Ego-Graph Extraction (RepoGraph)

Given a keyword, extract all nodes within N hops:

```
Input: "DurationField"
→ Find node "DurationField" (def, django/db/models/fields/__init__.py:1234)
→ 1-hop neighbors: all refs to DurationField across the repo
→ 2-hop neighbors: functions that call those referencing functions
→ Return: formatted text with file paths, line numbers, and code snippets
```

### 8.2 Typed Traversal (LocAgent)

The agent explicitly chooses edge types to traverse:

```
Step 1: SearchEntity("DurationField") 
  → Found: django/db/models/fields/__init__.py:DurationField (class)
Step 2: TraverseGraph("DurationField", edge_types=["inherit"])
  → Found: subclasses in other modules
Step 3: TraverseGraph("DurationField", edge_types=["invoke"]) 
  → Found: all callers across the repo
Step 4: GetEntityCode("DurationField", detail="full")
  → Returns: complete class source code
```

### 8.3 Cypher Queries (Code-Graph-RAG / bob-code-graph)

The MCP server translates natural language or structured queries into Cypher:

```cypher
-- "What functions call validate_token and what files are they in?"
MATCH (caller:Function)-[:CALLS]->(fn:Function {name: "validate_token"})
MATCH (f:File)-[:DEFINES]->(caller)
RETURN caller.name, f.path, caller.line
ORDER BY f.path;

-- "Trace the full call chain from the /api/auth endpoint"
MATCH (e:Endpoint {path: "/api/auth"})-[:HAS_PHASE]->(p:NginxPhase)
MATCH path = (entry:Function {file: p.lua_file})-[:CALLS*1..5]->(deep:Function)
RETURN [n in nodes(path) | n.name] AS call_chain, 
       [n in nodes(path) | n.file] AS files;

-- "Repo overview: most imported files (PageRank proxy)"
MATCH (f:File)<-[:IMPORTS]-(caller:File)
RETURN f.path, count(caller) AS import_count
ORDER BY import_count DESC
LIMIT 20;
```

### 8.4 PageRank Ranking (Aider)

Aider doesn't use a graph DB — it uses NetworkX's PageRank on a definition-reference graph to rank symbols by importance, then generates a condensed "repo-map" that fits within a token budget:

```python
# Simplified from Aider's approach:
personalization = {}
for fname in mentioned_fnames:
    personalization[fname] = 10 / len(all_fnames)

ranked = nx.pagerank(G, personalization=personalization)
# Top-ranked symbols get included in the context
```

This produces output like:
```
src/auth/service.py:
  class AuthService
    def validate_token(self, token)
    def refresh_token(self, refresh)
src/middleware/auth.py:
  def check_auth(request)
src/routes/api.py:
  def login_handler(request)
```

The repo-map is compact (fits in ~2000 tokens) and gives the LLM a structural overview without full file contents.

---

## 9. Practical Considerations for Your Stack

Given that you're building bob-code-graph for a Lua/OpenResty + Python + Ruby + JS codebase:

### 9.1 What RepoGraph Gets Right (and What It Doesn't)

**Right**: Line-level granularity is excellent for LLM context — when you retrieve a `def` node, you get the actual function body text, not just a name. This is directly usable by the agent.

**Doesn't**: RepoGraph's name-matching approach for cross-file edges would create too much noise in a polyglot codebase. A function called `init()` exists in Lua, Python, and Ruby — name matching would create false edges across language boundaries. Your import-based resolution approach is the correct choice.

**Doesn't**: RepoGraph is Python-only. The actual implementation filters for `.py` files and uses `ast.parse()` (Python's built-in AST) for structure extraction. The tree-sitter queries are only for Python tag extraction. To support Lua/Ruby/JS, you need language-specific tag queries and resolvers — which is exactly what you've built.

### 9.2 What Code-Graph-RAG Gets Right

**Right**: Unified graph schema across languages via `language_config.py`. Each language's parser produces the same node/edge types, so Cypher queries work identically regardless of source language. Your approach should follow this pattern.

**Right**: Memgraph as the storage layer with incremental updates via file watcher. The two-pass ingestion strategy (definitions first, then cross-file edges) avoids referencing nodes that don't exist yet.

**Right**: MCP server as the query interface. This decouples the graph infrastructure from the agent, letting BOB call graph tools like any other MCP server.

### 9.3 OpenResty-Specific Advantages You Have

Your codebase has a structure that graph-based retrieval is uniquely suited for:

1. **nginx.conf as the entry point graph**: No other system parses nginx.conf to create endpoint → lua handler edges. This is your highest-value unique feature — it answers "what handles `/api/auth`?" which no LSP or embedding search can answer.

2. **ngx.ctx implicit coupling**: Two Lua modules that both touch `ngx.ctx.user_id` are functionally coupled with zero import relationship. Graph edges for `CTX_READS`/`CTX_WRITES` to a shared `ContextKey` node make this coupling visible and queryable.

3. **`local M = {}` module pattern**: The 72% prevalence you found of uppercase `M` (not `_M`) means your parser's handling of this pattern directly affects the majority of module exports. This is domain-specific knowledge that no generic tool has.

---

## 10. Key Takeaways

1. **Graph-based retrieval works because code IS a graph.** The definition-reference structure of code is inherently a directed graph. Flattening it into embedding vectors destroys the structural information that matters most for navigation and impact analysis.

2. **RepoGraph's actual implementation is simpler than expected** — tree-sitter tag queries + name matching + NetworkX ego-graph extraction. The power comes from the line-level granularity (each tag carries its full code text) and the filtering of standard library noise.

3. **Language-agnostic graphs are achieved through language-specific parsers producing a universal schema.** The tag queries are per-language, the resolvers are per-language, but the graph nodes and edges are universal.

4. **Cross-language communication edges require domain-specific work** — nginx.conf parsing, API contract matching, shared state detection. No generic tool handles this; it's where custom implementations like bob-code-graph provide unique value.

5. **The resolution precision spectrum** (name matching → import resolution → LSP → SCIP) trades implementation complexity for accuracy. For a medium codebase with distinct naming conventions, import-based resolution hits the sweet spot. LSP/SCIP are worth adding incrementally for high-value queries.

6. **Retrieval strategy matters as much as graph construction.** Ego-graph extraction (RepoGraph), typed traversal with agent tools (LocAgent), Cypher queries (Code-Graph-RAG), and PageRank ranking (Aider) are all valid — the right choice depends on how your agent thinks and what questions it needs to answer.
