# Slice 1 — Industry Systems

## Sources consulted

- https://aider.chat/2023/10/22/repomap.html — Aider's own blog post on repo map via tree-sitter; primary source, high signal.
- https://aider.chat/docs/repomap.html — Aider docs on repo map (graph ranking stated, few internals). Medium signal.
- https://deepwiki.com/Aider-AI/aider/4.1-repository-mapping — DeepWiki walkthrough of Aider source code; spells out PageRank personalization and edge construction. Medium-high signal (third-party but code-derived).
- https://cursor.com/docs/context/codebase-indexing — Cursor's official docs; describes chunking + embeddings pipeline, no graph. High signal for what Cursor *does*.
- https://cursor.com/blog/secure-codebase-indexing — Cursor blog on privacy/indexing; confirms embedding-only pipeline, Turbopuffer vector DB, Merkle tree for sync. High signal.
- https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast — Third-party teardown consistent with Cursor docs. Medium signal (corroborating).
- https://vadim.blog/claude-code-no-indexing — Third-party article with Boris Cherny quotes on agentic search vs RAG. Medium-high signal (quotes attributed to Anthropic leads, but second-hand).
- https://milvus.io/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens.md — Critique of grep-only retrieval (negative evidence). Failed to load directly but summarized via search.
- https://code.claude.com/docs/en/tools-reference — Primary source: full Claude Code built-in tool list, including the LSP tool (call hierarchy, go-to-def, find-references). High signal.
- https://claude.com/blog/building-agents-with-the-claude-agent-sdk — Anthropic engineering post; rationale for agentic search first, semantic search as optional. High signal.
- https://www.augmentcode.com/context-engine — Augment marketing page; describes "real-time knowledge graph," semantic index, compression. Medium signal (marketing, not architecture).
- https://www.augmentcode.com/learn/cod-model-5-phase-guide-to-codebase-dependency-mapping — Augment's COD dependency-mapping explanation; references AST + imports + calls graph. Medium signal.
- https://docs.windsurf.com/context-awareness/overview — Windsurf docs; confirms RAG + M-Query; no graph mentioned. Medium signal.
- https://windsurf.com/context — 404 at fetch time; discarded.
- https://code.visualstudio.com/docs/copilot/reference/workspace-context — Official VS Code/Copilot docs enumerating the agent tool surface (semantic search, grep, usages, file search, etc.). High signal.
- https://docs.github.com/en/copilot/tutorials/explore-a-codebase — GitHub Copilot tutorial; confirms semantic index and symbol querying but no graph claim. Medium signal.
- https://deepwiki.com/continuedev/continue/3.4-codebase-indexing — DeepWiki on Continue's indexing pipeline (tree-sitter + LanceDB + SQLite FTS). Medium-high signal.
- https://docs.continue.dev/guides/codebase-documentation-awareness — Continue docs; @Codebase provider deprecated in favor of MCP/tools. Medium signal.
- https://sourcegraph.com/blog/how-cody-understands-your-codebase — Sourcegraph's own blog; announced moving away from embeddings toward Sourcegraph-native search. High signal.
- https://sourcegraph.com/blog/announcing-scip — Sourcegraph blog introducing SCIP indexing protocol (compiler-accurate symbols). High signal.
- https://www.latent.space/p/sourcegraph — Latent Space podcast transcript with Beyang Liu + Steve Yegge on "Normsky" graph + embeddings hybrid. High signal (primary-source quotes from Sourcegraph leadership).
- https://ampcode.com/manual — Amp Owner's Manual; surface enumerates built-in permissioned commands but does not list graph tools. Medium signal.
- https://ampcode.com/ — Amp landing page; mostly testimonials, no architecture. Low signal.

## Key findings

1. **Aider builds an explicit symbol-reference graph and runs PageRank over it** — Evidence: "a graph where each source file is a node and edges connect files which have dependencies" (https://aider.chat/2023/10/22/repomap.html); DeepWiki source walkthrough confirms "for each identifier that appears in both defines and references… add edge referencing_file -> defining_file" and PageRank personalization "files in chat context receive 100 / len(fnames), while unrelated files get 1 / len(fnames)" (https://deepwiki.com/Aider-AI/aider/4.1-repository-mapping). Confidence: high.

2. **Aider's graph is load-bearing: it is the ranker that decides what fits in the `--map-tokens` budget** — Evidence: "Aider optimizes the repo map by selecting the most important parts of the codebase which will fit into the token budget assigned by the user (via the --map-tokens switch, which defaults to 1k tokens)" (https://aider.chat/2023/10/22/repomap.html). Confidence: high.

3. **Cursor's indexing is embeddings-only — no code graph, no symbol table on the server** — Evidence: the docs describe splitting files into "syntactic chunks" that are "converted into embeddings" and stored in Turbopuffer; no AST/graph mentioned (https://cursor.com/docs/context/codebase-indexing, https://cursor.com/blog/secure-codebase-indexing). Third-party teardown corroborates ("No evidence found. The article contains no mentions of Cursor building symbol tables, dependency graphs, or AST-based indexing structures" — https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast). Confidence: high.

4. **Cursor's agent tool surface for retrieval is small and heterogeneous: grep for exact symbols, semantic search for fuzzy, read + reference-following for exploration** — Evidence: "Agent uses grep automatically when you reference specific symbols… semantic search [when] you don't know the exact name… file reads and reference following for complex exploration" (https://cursor.com/docs/context/codebase-indexing). Confidence: high.

5. **Claude Code ships no pre-built code graph and explicitly chose agentic search (Grep/Glob/Read) over RAG** — Evidence: Boris Cherny: "Early versions of Claude Code used RAG + a local vector db, but we found pretty quickly that agentic search generally works better" (reported at https://vadim.blog/claude-code-no-indexing); Anthropic's SDK post states "we suggest starting with agentic search, and only adding semantic search if you need faster results or more variations" (https://claude.com/blog/building-agents-with-the-claude-agent-sdk). Confidence: high.

6. **But Claude Code DOES expose graph-adjacent primitives via the LSP tool: jump-to-definition, find-references, call-hierarchy** — Evidence: the official tools-reference table lists the `LSP` tool with capabilities "Jump to a symbol's definition / Find all references to a symbol / Get type information at a position / List symbols in a file or workspace / Find implementations of an interface / Trace call hierarchies" (https://code.claude.com/docs/en/tools-reference). This is graph-structured retrieval even though no graph is materialized as a standalone index. Confidence: high.

7. **Claude Code's full built-in tool surface is ~30 tools spanning filesystem, shell, editing, scheduling, task/worktree management — retrieval is only a small subset (Glob, Grep, Read, LSP, WebFetch, WebSearch, Agent)** — Evidence: complete table at https://code.claude.com/docs/en/tools-reference listing `Agent`, `AskUserQuestion`, `Bash`, `CronCreate/Delete/List`, `Edit`, `EnterPlanMode`, `EnterWorktree`, `ExitPlanMode`, `ExitWorktree`, `Glob`, `Grep`, `ListMcpResourcesTool`, `LSP`, `Monitor`, `NotebookEdit`, `PowerShell`, `Read`, `ReadMcpResourceTool`, `SendMessage`, `Skill`, `TaskCreate/Get/List/Stop/Update`, `TodoWrite`, `ToolSearch`, `WebFetch`, `WebSearch`, `Write`. Confidence: high.

8. **Sourcegraph explicitly moved AWAY from embeddings for Cody Enterprise, toward code-graph + keyword retrieval** — Evidence: "Embeddings have been at the backbone of Cody's retrieval stack since we launched the product in beta, and now that Cody Enterprise is generally available, we're leaving them behind (for now)" (https://sourcegraph.com/blog/how-cody-understands-your-codebase). Rationale stated: sending code to a third party (OpenAI) and scaling issues on massive codebases. Confidence: high.

9. **Sourcegraph's stated design philosophy ("Normsky") is graph + embeddings hybrid, with the graph providing deterministic structural context and search/embeddings providing recall** — Evidence: Steve Yegge: "the graph is definitely our Chomsky side"; Beyang Liu describes "layer one to have high recall and get all the potential things that could be relevant… layer two re-ranking mechanism" (https://www.latent.space/p/sourcegraph). SCIP is the backing protocol: "Precise code navigation relies on the open source SCIP Code Intelligence Protocol" (https://sourcegraph.com/blog/announcing-scip). Confidence: high.

10. **GitHub Copilot Workspace exposes a multi-tool retrieval surface (semantic search, text search, grep, file search, usages, list-directory, read file) and picks combinations automatically** — Evidence: official VS Code docs enumerate tools and state "Copilot analyzes what information it needs and automatically selects the right combination of search tools" (https://code.visualstudio.com/docs/copilot/reference/workspace-context). The `usages` tool uses "Find All References, Find Implementation, Go to Definition" — symbol-graph-adjacent but served via LSP/IDE, not a materialized graph index. Confidence: high.

11. **Continue.dev uses tree-sitter for AST-based chunk extraction plus LanceDB vector search plus SQLite FTS5 keyword search — but no explicit graph structure** — Evidence: DeepWiki: "CodeSnippetsCodebaseIndex uses Tree-sitter queries (.scm files) to extract meaningful code entities… The documentation makes no mention of building graph structures. The system uses vector databases (LanceDB), SQLite tables, and AST parsing—but describes no explicit knowledge graph or relational graph construction" (https://deepwiki.com/continuedev/continue/3.4-codebase-indexing). Their `@Codebase` provider is deprecated in favor of MCP tool-call style retrieval (https://docs.continue.dev/guides/codebase-documentation-awareness). Confidence: high.

12. **Augment Code markets a "real-time knowledge graph" / "semantic dependency graph" built from AST + imports + calls; specifics are thin, but this is the most graph-forward commercial positioning** — Evidence: "Augment semantically indexes and maps your code, understanding relationships between hundreds of thousands of files" and "Real-time Knowledge Graph" feature (https://www.augmentcode.com/context-engine); COD dependency model "parse source code, extract every import and call, then build an interactive map of how everything connects" (https://www.augmentcode.com/learn/cod-model-5-phase-guide-to-codebase-dependency-mapping). Confidence: medium (marketing + methodology page, no engineering blog exposing the schema).

13. **Windsurf's public architecture is embeddings/RAG with proprietary "M-Query" retrieval — no graph documented** — Evidence: "Windsurf uses LLMs to perform retrieval-augmented generation (RAG) on your codebase using our own M-Query techniques" (https://docs.windsurf.com/context-awareness/overview). The overview doc does not discuss graph structures, ASTs, or symbol-based indexing. Confidence: medium-high (absence-of-evidence, but from the primary doc).

14. **Amp (Sourcegraph's agent) inherits Sourcegraph's code-graph capabilities through MCP, not as first-class built-in tools** — Evidence: the Owner's Manual mentions the Librarian subagent and MCP tool integration; "You can see Amp's builtin tools by running `amp tools list`" and the manual "does not explain how Amp composes search, grep, embeddings, or code graphs" (https://ampcode.com/manual). Third-party summary confirms "Agents can leverage powerful code search and navigation tools available via the Sourcegraph MCP." Confidence: medium (primary source under-specifies).

15. **Negative evidence — Claude Code team publicly defended dropping embeddings on grounds of freshness, privacy, simplicity, and (per internal tests) precision; third parties push back on token cost** — Evidence: vadim.blog summary of Anthropic rationale: "Precision: Grep locates exact matches; embeddings introduce false positives / Simplicity: No index building or maintenance required / Freshness: Filesystem reads reflect current state; pre-built indexes drift during editing / Privacy: Code never leaves the machine for embedding computation" (https://vadim.blog/claude-code-no-indexing). Milvus blog counter-argues grep-only "just burns too many tokens" (title per https://milvus.io/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens.md). Confidence: medium-high.

## Themes

- **Two camps with a shrinking middle.** One camp (Aider, Augment, Sourcegraph/Amp) treats a symbol/call/dependency graph as load-bearing; the other (Cursor, Windsurf, Continue) stays in an embeddings + text-search lane; Claude Code sits off to one side with *no materialized index at all* plus a separate LSP tool for graph-like queries on demand.
- **Graph retrieval is rarely exposed as a single "graph" tool.** Even in Sourcegraph's stack the graph shows up *behind* tools named `search`, `usages`, `references`, `jump-to-def`. This is consistent with Copilot's `usages` and Claude Code's `LSP`: agents call verbs, not graph queries.
- **The published rationales converge on two axes: staleness/freshness vs recall/precision.** Anthropic's argument against embeddings is dominated by freshness + privacy + simplicity. Sourcegraph's argument *for* graphs is dominated by type-precision and avoiding LLM hallucination on symbols. Neither camp claims their retrieval is sufficient alone; both layer in the other's tools (Claude Code has LSP; Sourcegraph has BM25 ranking; Cursor has grep fallback).
- **Tool-surface sizes are modest (3–10 retrieval-shaped tools) and tool verbs tend to be search/read/navigate rather than structured graph queries.** The graph is upstream of the tool surface, not at it.

## Open questions

- What exactly does Augment's "knowledge graph" schema look like (node types, edge types, storage)? Marketing page does not say; no engineering blog found.
- Does Amp expose graph queries to the LLM as first-class tools, or only indirectly via the Sourcegraph MCP server? `amp tools list` output could not be retrieved.
- What does Windsurf's M-Query actually do beyond re-ranking? The referenced video was not fetchable in this pass.
- How much does Claude Code's LSP tool get used in practice vs Grep/Read? No telemetry surfaced.
- For Cursor, does any server-side re-ranking use symbol info, or is it purely vector NN? Not documented publicly.
- Is there public evidence of any agent exposing explicit call-graph traversal as a named tool (e.g., `find_callers`, `trace_path`)? Not found in this pass — strongest candidate is Copilot's `usages`, but it is LSP-backed, not a persisted graph.
- Negative evidence where a graph was *tried and dropped*: only Sourcegraph's inverse is documented (embeddings tried and dropped). No public case of a vendor trying a graph and dropping it — worth a follow-up pass.

## Handoffs

- To slice 2 (academic / benchmarks):
  - The OpenReview / arXiv paper "Context-Augmented Code Generation Using Programming Knowledge Graphs" (https://arxiv.org/abs/2410.18251, https://openreview.net/forum?id=EHfn5fbFHw) — directly relevant benchmark evidence on PKG retrieval.
  - "CodeGRAG: Extracting Composed Syntax Graphs for Retrieval Augmented Cross-Lingual Code Generation" (https://arxiv.org/html/2405.02355v1).
  - "Reliable Graph-RAG for Codebases: AST-Derived" (https://arxiv.org/pdf/2601.08773).
  - "Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP" (https://arxiv.org/html/2603.27277v1) — directly aligned with this project's architecture.
  - "An Exploratory Study of Code Retrieval Techniques in Coding Agents" (https://www.preprints.org/manuscript/202510.0924).
  - "Semantic Code Graph – an information model to facilitate software comprehension" (https://arxiv.org/html/2310.02128v2).

- To slice 3 (tool-surface design):
  - Claude Code's full 30-tool enumeration with permission model (https://code.claude.com/docs/en/tools-reference) — canonical reference on *shape* of an agent tool surface (including the pattern of LSP as one tool with seven sub-verbs).
  - Copilot's `#tool` prompt-referencing convention — "explicitly reference [tools] in your prompts by typing `#` followed by the tool name" (https://code.visualstudio.com/docs/copilot/reference/workspace-context).
  - Aider's `--map-tokens` budget pattern — graph pre-ranks *offline* and the agent sees only a pruned token-bounded summary, not a query API.
  - Augment's MCP-exposed Context Engine and Continue's pivot from `@Codebase` to MCP tools — suggests an industry convergence on MCP as the tool-surface layer between graph indexers and agents.
  - The general pattern across vendors: graph features are named as verbs (search, references, usages, go-to-def) not as graph queries (no `traverse`, `shortest_path`, `neighbors` tools surfaced).
