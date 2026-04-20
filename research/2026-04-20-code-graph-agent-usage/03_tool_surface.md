# Slice 3 — Tool-Surface Design

## Sources consulted

- https://www.anthropic.com/engineering/writing-tools-for-agents — Anthropic engineering, primary source on tool design principles (consolidation, namespacing, return format). High signal.
- https://www.anthropic.com/engineering/code-execution-with-mcp — Anthropic engineering, contains the 150k→2k token (98.7%) reduction figure for progressive disclosure. High signal.
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool — Anthropic official docs; contains the explicit "30–50 tools" degradation threshold and tool-search accuracy numbers. High signal, authoritative.
- https://blog.arcade.dev/anthropic-tool-search-4000-tools-test (redirected to https://arcade.dev/blog/anthropic-tool-search-4000-tools-test) — Independent 4,027-tool benchmark of Anthropic's tool search; 56% regex / 64% BM25 retrieval. High signal, independent empirical test.
- https://eclipsesource.com/blogs/2026/01/22/mcp-context-overload/ — Practitioner blog quantifying context bloat (>20% pre-work, >40% rule-of-thumb). Medium signal.
- https://dev.to/nebulagg/mcp-tool-overload-why-more-tools-make-your-agent-worse-5a49 — Practitioner post reporting 95%→71% accuracy drop with full GitHub MCP vs focused set, 42k tokens just for GitHub MCP definitions. Medium signal (single-practitioner data).
- https://jentic.com/blog/the-mcp-tool-trap — Analysis of MCP's low-level protocol tradeoffs; cites "Less is More" paper. Medium signal.
- https://arxiv.org/abs/2411.15399 — "Less is More: Optimizing Function Calling for LLM Execution on Edge Devices"; shows up to 70% exec-time and 40% power reduction from dynamic tool selection. Medium signal (edge-device framing).
- https://developers.openai.com/cookbook/examples/o-series/o3o4-mini_prompting_guide — OpenAI cookbook; states ~100 tools / ~20 args per tool is "in-distribution" for o3/o4-mini; 6% accuracy bump from front-loaded descriptions. High signal.
- https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/1121 — Active MCP protocol debate on structuredContent vs text; contains a practitioner report that swapping structured→text improved gemma3-27b. Medium signal.
- https://medium.com/@Modexa/when-agents-pick-the-wrong-tool-f0fceb237bb6 — Practitioner piece on tool-router failure modes (similar-name collisions). Low-medium signal.
- https://cookbook.openai.com/examples/o-series/o3o4-mini_prompting_guide — Duplicate mirror of the OpenAI cookbook (for citation redundancy).
- https://demiliani.com/2025/09/04/model-context-protocol-and-the-too-many-tools-problem/ — Practitioner discussion of MCP tool-count problem, cites Cursor's 40-tool cap. Medium signal.

## Key findings

1. Anthropic states explicitly that Claude's tool-selection accuracy "degrades significantly once you exceed 30–50 available tools" — this is the single most concrete vendor-published threshold on tool count. Confidence: high. Evidence: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool ("Claude's ability to correctly pick the right tool degrades significantly once you exceed 30–50 available tools").

2. A 16-tool surface sits well inside the green zone for current frontier models: OpenAI's o3/o4-mini guide calls "fewer than ~100 tools and fewer than ~20 arguments per tool" in-distribution, and Anthropic's tool-search docs recommend traditional tool calling when you have <10 tools, implying the 10–30 band is uncontroversial. Confidence: high. Evidence: https://developers.openai.com/cookbook/examples/o-series/o3o4-mini_prompting_guide and https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool ("When traditional tool calling might be better: Less than 10 tools total").

3. Accuracy collapse at scale is real and steep, not gradual: with Anthropic's tool-search enabled, Opus 4 went from 49% → 74% and Opus 4.5 from 79.5% → 88.1% on MCP evals, quantifying the penalty the model pays when forced to reason over many loaded definitions. Confidence: high. Evidence: WebSearch summary of https://www.anthropic.com/engineering/writing-tools-for-agents and https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool.

4. Independent testing of Anthropic's tool-search at scale is still mediocre (56% regex / 64% BM25 across 4,027 tools), so "just add search" is not a free pass above ~50 tools. Confidence: high. Evidence: https://arcade.dev/blog/anthropic-tool-search-4000-tools-test ("~60% retrieval accuracy isn't ready for prime time").

5. Context bloat, not just selection entropy, is the main cost: a typical multi-server setup (GitHub, Slack, Sentry, Grafana, Splunk) consumes "~55k tokens in definitions before Claude does any actual work"; a GitHub-only MCP eats ~42k. Confidence: high. Evidence: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool and https://dev.to/nebulagg/mcp-tool-overload-why-more-tools-make-your-agent-worse-5a49.

6. Anthropic's consolidation guidance favors high-level, workflow-shaped tools over thin CRUD primitives: replace `list_users` + `list_events` + `create_event` with a single `schedule_event` that "finds availability and schedules an event"; prefer `search_contacts` over `list_contacts`. Confidence: high. Evidence: https://www.anthropic.com/engineering/writing-tools-for-agents ("consider implementing a schedule_event tool which finds availability and schedules an event").

7. But low-level primitives are exactly what Claude Code ships with, and the design works because the primitives are compositional and orthogonal (Read, Grep, Glob, Edit, Bash) rather than overlapping CRUD wrappers — the lesson is "few, non-overlapping, composable" rather than "always high-level." Confidence: medium. Evidence: https://code.claude.com/docs/en/tools-reference and https://dev.to/klement_gunndu_e16216829c/why-claude-codes-unix-philosophy-beats-other-ai-assistants-3o3c.

8. Return format: Anthropic's own guidance is to return "only high signal information" and to "prioritize contextual relevance over flexibility"; a concrete Slack example cut response tokens from 206 → 72 (~⅔ reduction) when switching from raw API dump to a curated format. Confidence: high. Evidence: https://www.anthropic.com/engineering/writing-tools-for-agents.

9. Structured vs text content is genuinely contested in MCP: the protocol added `structuredContent` but practitioners report mixed results — one report cites a "notable performance improvement" after swapping structured output for plain text on gemma3-27b; the emerging compromise is "text for agent UX, structured for code-mode / deterministic consumers." Confidence: medium. Evidence: https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/1121.

10. Discovery mechanisms that demonstrably work: (a) namespacing by service and resource (`asana_projects_search`, `asana_users_search`) so related tools cluster lexically; (b) keeping the 3–5 hottest tools non-deferred while lazy-loading the rest; (c) system-prompt "tool categories" hints ("You can search for tools to interact with Slack, GitHub, and Jira"). Confidence: high. Evidence: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool and https://www.anthropic.com/engineering/writing-tools-for-agents.

11. Progressive disclosure via code execution is Anthropic's currently preferred pattern for large surfaces: presenting tools as files the model can read on demand reduced a Drive/Salesforce example from 150,000 → 2,000 tokens (98.7% savings). Confidence: high. Evidence: https://www.anthropic.com/engineering/code-execution-with-mcp ("token usage from 150,000 tokens to 2,000 tokens—a time and cost saving of 98.7%").

12. On the "one NL→Cypher escape hatch vs many typed tools" question, the literature does not settle it empirically, but two directional signals lean toward hybrid-with-typed-primary: (a) practitioner failure modes show routers misfire when tools have similar names or vague scope, which pure NL-escape-hatches avoid; (b) the text-to-SQL field is "moving away from pure 'escape hatch' natural language generation toward more structured, validated tool-based approaches while maintaining some flexibility for edge cases." Confidence: low-to-medium (inferred from adjacent domains, not a direct head-to-head study). Evidence: https://medium.com/@Modexa/when-agents-pick-the-wrong-tool-f0fceb237bb6 and WebSearch synthesis on text-to-SQL architectures.

## Themes

Across every source, the dominant pattern is "curate hard, then use infrastructure for the long tail": the first 10–30 tools are a design problem (naming, non-overlap, return-shape), everything above ~50 is an *infrastructure* problem solved by lazy loading, search, namespacing, or code-execution wrappers rather than by prompt engineering. A second pattern is that the quality of tool *descriptions and return payloads* moves accuracy more than the number of tools in the 10–50 band — front-loaded descriptions gave a 6% bump at OpenAI and token-frugal returns cut context cost ~⅔ at Anthropic. Third, there is genuine live disagreement on structured-vs-text returns, which suggests the right answer is task-dependent rather than universal. Finally, every credible source argues against thin CRUD mirrors of the underlying API — the disagreement is between "bundle into workflow tools" (Anthropic guidance) and "ship orthogonal primitives the agent composes" (Claude Code's own design), and both work so long as the tools don't overlap.

## Open questions

- No published study directly measures the failure-mode spectrum for *exactly* a 16-tool code-graph surface — all evidence is either below (<10) or far above (100s–1000s). The 30–50 cliff is stated but not graphed.
- No source gives head-to-head numbers for "one NL→Cypher tool" vs "N typed graph tools" on comparable tasks; the text-to-SQL literature is suggestive but not transferable given graph-query idiosyncrasies.
- Whether tool *argument* complexity (nested schemas, enums) hurts selection more or less than tool *count* is unresolved — OpenAI pairs the two thresholds (100 tools / 20 args) but doesn't decompose the contribution.
- Empirical data on return-format (structured JSON vs text vs hybrid) for code-navigation tools specifically is absent; the MCP discussion thread is a proxy at best.
- The "Less is More" arXiv paper headlines exec-time/power numbers for edge devices but its abstract does not expose the accuracy delta; would need full-text read to cite rigorously.

## Handoffs

- To slice 1 (industry): How do real codebase-indexing products (Sourcegraph Cody, GitHub Copilot Workspace, Cursor, Sourcegraph Amp) partition their tool surface? Do they expose fine-grained graph tools, or funnel through one or two broad search/navigation tools? Specifically worth checking Cursor's 40-MCP-tool hard cap (https://demiliani.com/2025/09/04/model-context-protocol-and-the-too-many-tools-problem/) as a real product rationale.
- To slice 2 (academic): Whether any graph-specific benchmark (code property graph, CodeQL-style, Joern-like) has measured LLM accuracy as a function of typed-tool count vs a single query-language escape hatch. Also whether the "Less is More" paper (arXiv 2411.15399) or ACEBench / MCP-Bench (https://github.com/Accenture/mcp-bench) contain tool-count ablations applicable to code-navigation surfaces.
