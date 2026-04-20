# Phase 1 Synthesis — Code Graph Agent Usage

**Date:** 2026-04-20
**Charter:** [`00_charter.md`](00_charter.md)
**Briefs:** [`01_industry.md`](01_industry.md), [`02_academic.md`](02_academic.md), [`03_tool_surface.md`](03_tool_surface.md)

This synthesis answers the charter's two questions (Q1 task fit, Q2 composition) and takes a defended position on tool-surface design (secondary question). Every claim cites a brief-level finding and the underlying source URL. Nothing here repeats training memory — if a claim has no citation, it belongs in "Open questions," not here.

---

## 1. Task-fit matrix

Nine recurring agent coding tasks, graded by how much the graph actually moves the needle vs grep / embeddings / LLM-memory alone. "Load-bearing" means published evidence shows the graph is the primary driver of the lift; "helpful" means measurable lift but the agent loop or another retriever contributes at least as much; "marginal" means the graph is within noise of cheaper retrieval; "unhelpful" means evidence shows either no lift or active regression.

| # | Task type | Graph role | Composition | Evidence |
|---|---|---|---|---|
| 1 | **Impact / blast-radius analysis** (who calls this, what breaks if I change it) | **Load-bearing** | Graph-as-verb (`find_callers` / `usages`) | Industry: Copilot's `usages` tool, Claude Code's `LSP` call-hierarchy, Aider PageRank edge from `referencing_file → defining_file` ([01 §1, §6, §10](01_industry.md)). Academic: LLM4FL ablation — removing CodeNav drops Top-1 fault-localization by 16.51% ([02 §16](02_academic.md)). |
| 2 | **Fault / bug localization** (find the right file/function for a symptom) | **Load-bearing** | Graph-as-ranker or graph-as-verb | Academic: LocAgent+Claude-3.5 hits 94.16% file-level Acc@5 on SWE-Bench-Lite vs BM25 61.68% / CodeRankEmbed 84.67%; removing the TraverseGraph tool drops module-level from 82.85%→78.47% ([02 §4, §5](02_academic.md)). LLM4FL's CodeNav-removed ablation −16.51% Top-1 ([02 §16](02_academic.md)). |
| 3 | **Cross-service / cross-language data-flow tracing** (HTTP → Lua → Redis → Python, endpoint-to-endpoint) | **Load-bearing** | Graph-as-verb with specialized traversals | Academic: CodeCompass "hidden-dependency" (G3) tasks — graph tool gives +23.2 points ACS (99.4% vs 76.2% vanilla, 78.2% BM25) ([02 §11](02_academic.md)). Industry: no non-graph system demonstrates an equivalent capability — Cursor, Windsurf, Continue.dev all stop at per-file embeddings / text search ([01 §3, §11, §13](01_industry.md)). |
| 4 | **Onboarding / repo Q&A** ("what does this codebase do," "where does auth live") | **Helpful** | Graph-as-ranker feeding a summary | Industry: Aider's repo map ranks symbols into a `--map-tokens` budget via PageRank ([01 §1, §2](01_industry.md)). Augment's "real-time knowledge graph" markets exactly this use case ([01 §12](01_industry.md)). Academic: Codebase-Memory (tree-sitter KG over MCP) reaches 83% answer-quality vs file-exploration 92% at 10x fewer tokens and 2.1x fewer tool calls ([02 §14](02_academic.md)) — cheap, slightly worse. |
| 5 | **Refactoring / rename / API migration** (touch every call site of X) | **Helpful** | Graph-as-verb via references / callers | Industry: this is the canonical use case for LSP `find-references` and Copilot `usages` ([01 §6, §10](01_industry.md)). The graph is reliable when *parser coverage* is — Codebase-Memory failure mode "macros are not represented in the AST" (C at 0.58 vs 1.00) ([02 §14](02_academic.md)). Lift is vs hand-grep, not vs LSP — if an IDE LSP is already available, the graph is redundant for mono-language tasks. |
| 6 | **Feature implementation / patch authoring** (write new code that fits in) | **Marginal** | Graph for localization, LLM memory for style | Academic: RepoGraph adds only +2.0 to +2.66 points on SWE-bench Lite despite graph access; dominant failure is "contextual misalignment" (patch doesn't integrate), not bad localization ([02 §1, §3](02_academic.md)). LocAgent 94% file-level → only +12 points Pass@10 downstream ([02 §6](02_academic.md)). CodeRAG-Bench: SWE-bench-Lite "remained 'too complex' with near-zero pass rates even with perfect retrieval" ([02 §13](02_academic.md)). |
| 7 | **Code review / security review** (reason about what this change affects) | **Helpful** | Graph-as-verb (callers + implicit deps) layered with grep for literals | Industry: no published system reports code-review-specific graph ablations, but Sourcegraph's "Normsky" hybrid is explicitly positioned for this task — graph for structural, search for recall ([01 §9](01_industry.md)). Academic: CodeCompass Navigation Paradox suggests the graph helps *when the reviewer knows to invoke it* — 42% overall adoption ([02 §11, §12](02_academic.md)). |
| 8 | **Test authoring** (write a test that exercises X) | **Marginal** | Embeddings / grep on test files, graph optional | No published evidence in any of the three briefs attributes test-authoring lift to graph access. Claude Code explicitly picks agentic search over indexed retrieval for this class of task ([01 §5, §15](01_industry.md)). Negative evidence: CodeRAG-Bench "no improvement or degradation with retrieved documents on basic programming" ([02 §13](02_academic.md)). |
| 9 | **Algorithmic / contest-style coding** (LeetCode, LiveCodeBench) | **Unhelpful** | None — LLM memory suffices | LiveCodeBench is "algorithmic/contest-style, not repo-graph-oriented… I found no paper using LiveCodeBench to evaluate graph-based retrieval" ([02 §25, open questions](02_academic.md)). No cross-file context to traverse. |

**Matrix summary.** The load-bearing cases (1–3) share one property: **they require multi-hop, symbol-precise traversal across files or languages**, which is exactly what grep and embeddings cannot reliably deliver. The helpful cases (4–5, 7) are ones where the graph is faster or cheaper than alternatives but not uniquely capable. Cases 6, 8, 9 are where retrieval stops being the bottleneck — generation quality dominates — and here the literature shows either tiny or zero lift from adding a graph.

---

## 2. Composition patterns

Five distinct patterns emerge from industry and academic evidence. Each has at least one concrete deployed example and published rationale.

### Pattern A — Graph-as-ranker (offline, inline)

**Shape.** The graph is built and traversed *before* the agent runs; output is a pruned, token-bounded summary injected into the prompt. The agent never issues graph queries.

**Canonical example.** Aider's repo map: tree-sitter extracts defs/refs → build edge `referencing_file → defining_file` → run personalized PageRank (files in chat = 100/n, others = 1/n) → emit a summary fitting `--map-tokens` (default 1k) ([01 §1, §2](01_industry.md)).

**When to use.** Small-to-mid codebases where a single token-bounded map is enough orientation; agents without strong tool-calling; or cases where you need deterministic, reproducible context.

**Trade-off.** Low agent complexity, no risk of the agent *failing to invoke* the graph (CodeCompass's failure mode — see Pattern B), but the ranker must guess what's relevant without seeing the current task. Aider mitigates with `--map-tokens` and personalization on in-chat files.

### Pattern B — Graph-as-verb (on-demand, typed tools)

**Shape.** The graph is persisted as an index; the agent calls *named verbs* — `find_references`, `call_hierarchy`, `go_to_definition`, `usages` — not graph queries. Tools return text, not triples.

**Canonical examples.** Claude Code's `LSP` tool with seven sub-verbs (definition, references, type-info, symbols, implementations, call-hierarchy) ([01 §6](01_industry.md)). GitHub Copilot Workspace's `usages` tool, backed by LSP Find-All-References/Find-Implementation/Go-to-Definition ([01 §10](01_industry.md)). Our Pinpoint MCP server is this pattern.

**When to use.** When the agent is strong enough to pick tools correctly; when tasks are heterogeneous (you don't know in advance which hop is needed); when you want lazy evaluation (only traverse what's asked).

**Trade-off.** Highest agent composability, but exposed to CodeCompass's Navigation Paradox — 42% overall adoption and 0% on G2 structural tasks because the agent "rationally" judges a simpler tool (grep) already reaches ~80% ([02 §11, §12](02_academic.md)). Mitigation: tool descriptions and prompt-level "checklist-at-END" moved G3 adoption 85.7%→100% in CodeCompass ([02 handoff to §3](02_academic.md)).

### Pattern C — Graph + embeddings hybrid ("Normsky")

**Shape.** Two retrievers in parallel: a graph for structural/deterministic queries, embeddings for fuzzy/NL recall, then a re-ranker over both. Sourcegraph's published architecture.

**Canonical example.** Sourcegraph Cody — Steve Yegge explicitly calls graphs "our Chomsky side"; Beyang Liu describes "layer one to have high recall… layer two re-ranking mechanism" with SCIP as the precise-navigation backbone ([01 §9](01_industry.md)). Sourcegraph then *removed* embeddings from Cody Enterprise (privacy + scaling), keeping graph + keyword ([01 §8](01_industry.md)).

**When to use.** Large codebases where neither retriever alone has enough recall; products serving heterogeneous user intents ("find code that does X" ≈ embedding; "who calls X" ≈ graph).

**Trade-off.** Engineering complexity of maintaining two indexes and a re-ranker. Published data is positive but doesn't isolate the graph's contribution from the embedding's contribution.

### Pattern D — No-index agentic (grep + LSP on demand)

**Shape.** No persistent retrieval index at all. The agent uses filesystem primitives (Grep, Glob, Read) plus an LSP tool for symbol-precise queries, composed at inference time.

**Canonical example.** Claude Code. Boris Cherny: "Early versions of Claude Code used RAG + a local vector db, but we found pretty quickly that agentic search generally works better" ([01 §5](01_industry.md)). Stated reasons: precision, simplicity, freshness (no index drift during editing), privacy ([01 §15](01_industry.md)).

**When to use.** When agents are powerful enough to plan multi-step retrieval; when index-staleness or privacy is a binding constraint; when codebase size is moderate enough that grep is fast.

**Trade-off.** Public counter-evidence: Milvus blog — grep-only "just burns too many tokens" ([01 §15](01_industry.md)). Scales poorly to cross-repo or multi-language tasks where grep has no symbol semantics.

### Pattern E — Natural language → query DSL

**Shape.** The agent emits *generated queries* in a graph DSL (Cypher, SCIP queries, custom). A translation sub-agent converts NL intent into the DSL.

**Canonical example.** CodexGraph. Academic evidence: on SWE-bench Lite it matches AutoCodeRover exactly (22.96% = 22.96% Pass@1); the entire value is concentrated in the translation agent — removing it drops CrossCodeEval EM from 27.90% to 8.30% ([02 §7, §8](02_academic.md)).

**When to use.** Rarely. The translation agent is worth ~20 points on strong models but collapses on weaker ones (GPT-4o 27.90% EM → Qwen2 5.00% EM), and "sometimes encounters loops where it fails to generate executable graph queries" ([02 §9](02_academic.md)).

**Trade-off.** The most expressive interface, but the published evidence says typed verbs beat NL→DSL unless you can afford a translation agent AND your model is strong. Text-to-SQL is "moving away from pure 'escape hatch' natural language generation toward more structured, validated tool-based approaches" ([03 §12](03_tool_surface.md)).

---

## 3. Tool-surface design — defended positions

Three charter-critical questions on surface design. Each answer is a position, not a hedge.

### Q — Is 16 tools too many?

**No. 16 is well inside the green band.** Anthropic's own published threshold is "tool-selection accuracy degrades significantly once you exceed 30–50 available tools" ([03 §1](03_tool_surface.md), https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool). OpenAI's o3/o4-mini guide calls "fewer than ~100 tools and fewer than ~20 arguments per tool" in-distribution; Anthropic's tool-search docs recommend traditional tool calling when you have *fewer than* 10 ([03 §2](03_tool_surface.md)). A 16-tool surface sits in the 10–30 band, which is uncontroversial across every source we consulted.

**But count is the wrong primary metric.** Context bloat moves more than selection entropy at this scale: a GitHub-only MCP eats ~42k tokens just for definitions ([03 §5](03_tool_surface.md)). The binding constraint for Pinpoint isn't "too many tools" — it's (a) *non-overlap* between tools, (b) *return-payload density*, and (c) *tool descriptions that make the agent invoke the right one* (CodeCompass: 42% adoption despite being designed for the task — [02 §12](02_academic.md)).

### Q — Bundle into workflow tools, or ship orthogonal primitives?

**Ship orthogonal primitives with non-overlap, not workflow wrappers.** Anthropic's *written* guidance favors bundling (`schedule_event` over `list_users + list_events + create_event`) ([03 §6](03_tool_surface.md)), but Claude Code's *shipped* design uses the opposite pattern — Read, Grep, Glob, Edit, Bash are deliberately primitive and compositional ([03 §7](03_tool_surface.md)). Both work. The lesson is **"few, non-overlapping, composable"** rather than "always high-level."

**Pinpoint's fit.** Our 16 tools already lean primitive (navigation / tracing / impact / search / snippets / diagnostic). The right refactor target is overlap between primitives, not aggregation into workflow verbs. Specifically, `get_dependents` and `find_impacted_files` are near-synonyms — a 1-hop reverse dep call and an N-hop reverse dep call respectively — and should be merged into one parameterized tool. Keeping both trains the agent to be unsure which to pick, which is exactly the Modexa "similar-name collisions" failure mode ([03 §10](03_tool_surface.md)).

### Q — One NL→Cypher escape hatch, or only typed tools?

**Typed tools only in phase 1; no NL→Cypher escape hatch.** CodexGraph's evidence is unambiguous: raw-DSL exposure without a translation agent collapses on weaker models (27.9%→5.0% on Qwen2) and loops on query-generation failures ([02 §9](02_academic.md)). Text-to-SQL's trajectory is away from NL-escape-hatches toward validated typed tools ([03 §12](03_tool_surface.md)). A graph-query escape hatch adds one tool that is maximally likely to misfire and maximally expensive when it does.

**When to revisit.** If phase-2 dogfooding reveals concrete structural queries the agent *attempts* but the 16 typed tools can't express, then add a restricted traversal tool (e.g., `graph_traverse(start, edge_type, max_hops)`) — not a full Cypher shell. This matches the Aider pattern of pre-bounded depth ([02 §2](02_academic.md): "1-hop + flatten beats 2-hop").

### Q — Structured JSON, plain text, or hybrid returns?

**Plain text returns, optimized for agent reading.** Anthropic's published guidance is to return "only high signal information" and "prioritize contextual relevance over flexibility" — a Slack example cut response tokens 206→72 (~⅔) when switching from raw API dump to curated text ([03 §8](03_tool_surface.md)). The MCP community remains split on `structuredContent` vs text; one practitioner reports structured→text swap gave a "notable performance improvement" on gemma3-27b ([03 §9](03_tool_surface.md)). Default to text; expose structured output only if a deterministic downstream consumer needs it.

---

## 4. Implications for Pinpoint — specific keep / merge / cut

Against our 16 MCP tools ([mcp_server/server.py](../../mcp_server/server.py)), tied to the matrix rows and patterns above.

### Keep as-is (load-bearing, no overlap, no alternative)

- **`trace_endpoint`** (row 3, Pattern B) — cross-language HTTP→Lua→Python data-flow is the Pinpoint feature that no other pattern reproduces; no published industry tool does endpoint-to-endpoint tracing. [01 §3, §11, §13]
- **`trace_cross_service_flow`** (row 3) — ngx.exec / ngx.location.capture reroutes are invisible to grep and to LSPs. Unique value.
- **`get_redis_coupling`** (row 3) — Redis key as implicit shared-memory channel is exactly CodeCompass's "hidden-dependency" (G3) category where graphs gave +23.2 points ([02 §11](02_academic.md)).
- **`get_implicit_dependencies`** (row 3, 7) — ngx.ctx / ngx.shared / Redis coupling is the Pinpoint-specific equivalent of CodeCompass G3.
- **`find_all_callers`** (row 1) — direct analogue of Copilot `usages` and Claude Code `LSP.findReferences`. Published lift (LLM4FL −16.51% when CodeNav removed, [02 §16](02_academic.md)).
- **`get_repo_overview`** (row 4, Pattern A) — Aider-style PageRank'd entry point. Highest-value tool for the onboarding use case.
- **`get_file_outline`** (row 5, 7) — cheap, bounded, read-shaped. Near-zero misfire risk.
- **`get_code_snippet`** (row 5, 6) — a snippet by name is a common grep-pattern-replacement and stays cheap even when the agent is confused.

### Merge — reduce overlap / ambiguity

- **`get_dependents` + `find_impacted_files` → one tool `find_dependents(file, max_depth)`.** Currently `get_dependents` is 1-hop, `find_impacted_files` is N-hop. Same operation, different depth. Two near-synonymous tools is the Modexa router-misfire pattern ([03 §10](03_tool_surface.md)). Default `max_depth=1` preserves cheap-call behavior.
- **`find_symbol` + `get_module_exports` → one tool `find_symbol(name, scope=None)`.** `get_module_exports` is `find_symbol` with `scope=module`. Fold in.

### Cut or gate (marginal, redundant, or diagnostic-only)

- **`find_unresolved`** — operator tool, not agent tool. Move out of the MCP surface into a CLI command. Agents don't need it; engineers do.
- **`get_graph_stats`** — same. Operator diagnostics.
- **`diagnose_file`** — same. `spot_check` is useful for parser-coverage debugging, not agent workflows.

Cutting these three non-agent tools from the agent surface takes 16 → 13; merging the two pairs takes 13 → 11. **Final recommended surface: 11 agent-facing tools**, all with non-overlapping verbs, all in the green band.

### Prioritize in phase-2 dogfooding

1. **Blast-radius on Lua → Go / Redis changes** — the highest-value load-bearing case; zero competitors.
2. **Cross-service endpoint tracing** — same.
3. **Repo onboarding** (get_repo_overview + get_file_outline flow) — highest coverage per token.

De-prioritize evaluating the graph on: feature-implementation quality, test authoring, and anything algorithmic. Academic evidence is unambiguous that retrieval quality is not the bottleneck there ([02 §6, §13](02_academic.md)).

---

## 5. Open questions and phase-2 candidates

Questions the phase-1 evidence cannot answer, ranked by whether they block a phase-2 build decision.

### Blocking (must answer before ripping tools or building new ones)

- **Empirical adoption on our codebase.** CodeCompass says 42% overall, 0% on G2 structural. Does our Opus/Sonnet-tier agent *actually* invoke `trace_cross_service_flow` and `get_redis_coupling` on real Pinpoint issues, or does it default to grep? No published data fits our shape. **Phase-2 candidate: instrumented dogfood on Pinpoint with 10–20 representative tasks; measure tool-adoption rate and end-to-end resolution delta.**
- **Return-format density.** Anthropic's 206→72 token cut was a 3× density improvement on one tool. How tight are our current returns? No source gives empirical data for code-navigation tools specifically ([03 open questions](03_tool_surface.md)). **Phase-2 candidate: audit 3–5 highest-use tools for payload density; target 2× reduction.**
- **Which graph edges drive which lift.** No published ablation decomposes CALLS vs IMPORTS vs INHERITS vs CTX_READS contributions ([02 open questions](02_academic.md)). Our schema has seven+ edge types and we don't know which carry weight.

### Non-blocking (interesting but deferred)

- **Does `trace_endpoint` hit the "too-deep-graph" failure mode?** RepoGraph: 1-hop + flatten 29.67% vs 2-hop + flatten 26.00% ([02 §2](02_academic.md)). Our endpoint traces go many hops by design; is depth hurting us?
- **Argument-complexity vs tool-count.** OpenAI pairs 100-tool / 20-arg thresholds but doesn't decompose them ([03 open questions](03_tool_surface.md)). Some of our tools take many args; no published data says whether that matters.
- **SWE-bench contamination.** SWE-Bench Illusion raises concerns for all the academic numbers above ([02 §?, open questions](02_academic.md)). Not actionable for us but tempers how much we weight absolute SWE-bench percentages.

### Phase-2 candidate set (for `research-next-phase-proposal`)

Three distinct phase-2 shapes are viable. Ordered by expected value:

1. **Empirical dogfood on Pinpoint** — 10–20 representative tasks (blast radius, cross-service tracing, onboarding, localization, refactor). Instrument tool-adoption rate, end-to-end resolution, token cost. Answers the Blocking questions 1 and 3 simultaneously. **Highest-value, highest-cost.**
2. **Surface refactor + return-format audit** — implement the merge/cut listed in §4 and measure density reduction. Answers Blocking question 2. **Lowest-cost, moderate-value.**
3. **Edge-type ablation** — rebuild graph with subsets of edge types, re-run fixed agent tasks, measure deltas. Answers Blocking question 3 directly. **Moderate cost, narrow value** — defer unless #1 reveals edge-specific failure modes.

The phase-decision skill (`research-phase-decision`, next step) should choose between CONCLUDE (go build on current evidence) and CONTINUE (run option 1 before committing to the §4 refactor).
