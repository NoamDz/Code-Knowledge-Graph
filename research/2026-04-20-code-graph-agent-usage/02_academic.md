# Slice 2 — Academic / Benchmarks

## Sources consulted

- https://arxiv.org/abs/2410.14684 — RepoGraph (ICLR 2025) abstract page; high-signal for headline claim, light on quantitative detail alone.
- https://arxiv.org/html/2410.14684v1 — RepoGraph HTML; extracted full Table 2 resolve rates and ablation.
- https://openreview.net/forum?id=dw9VUsSHGB — RepoGraph OpenReview page; fetch blocked (403), no reviewer quotes.
- https://arxiv.org/abs/2503.09089 — LocAgent (ACL 2025) abstract; high-level headline numbers.
- https://arxiv.org/html/2503.09089 — LocAgent HTML; extracted per-benchmark accuracy table and the TraverseGraph ablation.
- https://aclanthology.org/2025.acl-long.426/ — LocAgent ACL anthology landing page; confirms publication venue.
- https://arxiv.org/html/arXiv:2408.03910 — CodexGraph (NAACL 2025) HTML; got full Table 1 numbers, translation-agent ablation, and loop-failure discussion.
- https://aclanthology.org/2025.naacl-long.7/ — CodexGraph ACL anthology landing page; confirms venue.
- https://arxiv.org/html/2504.10046v1 — CodeRAG (GraphCodeAgent) on DevEval; precise per-tool ablation deltas.
- https://arxiv.org/html/2406.14497v1 — CodeRAG-Bench (9k problems, 25M docs); strong negative-result source on retrieval limits.
- https://arxiv.org/html/2507.19942v1 — Prometheus multilingual KG; headline SWE-bench Lite and multilingual numbers; weak on ablation.
- https://arxiv.org/html/2409.13642v2 — LLM4FL (fault localization via call graph); explicit CodeNav-removed ablation.
- https://arxiv.org/html/2602.20048v1 — CodeCompass "Navigation Paradox"; best-in-class source for task-type breakdown (G1/G2/G3) and tool-adoption failure mode.
- https://arxiv.org/html/2603.27277v1 — Codebase-Memory (tree-sitter KG over MCP); answer-quality vs token/tool-call tradeoff numbers.
- https://arxiv.org/pdf/2310.06770 — SWE-bench original paper; baseline BM25 pass rates (Claude 2 at 1.96%).
- https://arxiv.org/html/2506.12286v3 — "SWE-Bench Illusion"; contamination/memorization caveat for all SWE-bench numbers.
- https://www.swebench.com/lite.html — SWE-bench Lite leaderboard for comparing resolve rates.
- https://eu.36kr.com/en/p/3354378250711941 — Ant CGM/SWE-Effi summary on Agentless vs AutoCodeRover resource cost; secondary reporting but useful framing.
- https://arxiv.org/html/2509.09853 — SWE-Effi paper (API-call / inference-time comparison of scaffolds).
- https://arxiv.org/html/2410.20285v1 — SWE-Search MCTS paper; references moatless as baseline.
- https://livecodebench.github.io/ — LiveCodeBench project page; confirms LiveCodeBench is algorithmic/contest-style, not repo-graph-oriented (relevant as a null source).
- https://aclanthology.org/2025.findings-naacl.176.pdf — CodeRAG-Bench anthology mirror; PDF binary not parseable in fetch.

## Key findings

1. RepoGraph delivers modest but consistent absolute lift on SWE-bench Lite (+2.0 to +2.66 points) across four very different scaffolds, which aggregates to the headline "32.8% average relative improvement" because one procedural baseline starts near zero — Evidence: https://arxiv.org/html/2410.14684v1 reports RAG 2.67%→5.33%, Agentless 27.33%→29.67%, AutoCodeRover 19.00%→21.33%, SWE-agent 18.33%→20.33%. Confidence: high.

2. RepoGraph's ablation shows 1-hop flattened graphs beat deeper 2-hop variants — more graph is not better — Evidence: https://arxiv.org/html/2410.14684v1 "1-hop + flatten: 29.67% … 2-hop + flatten: 26.00% (worst)". Confidence: high.

3. RepoGraph's dominant failure mode is not bad localization but "contextual misalignment" — the agent finds the right region but writes a patch that doesn't integrate with the rest of the repo — Evidence: https://arxiv.org/html/2410.14684v1 "contextual misalignment is the most prevalent error type, followed by incorrect localization and regressive fixes." Confidence: high. Implication: graphs help find code, not write compatible code.

4. LocAgent shows the largest reported lift from graph access on localization: on SWE-Bench-Lite file-level Acc@5, LocAgent+Claude-3.5 hits 94.16% vs BM25 61.68% and CodeRankEmbed 84.67% — Evidence: https://arxiv.org/html/2503.09089 Table of localization results. Confidence: high.

5. LocAgent's TraverseGraph-removal ablation quantifies pure graph contribution at roughly +4.4 points module-level, far smaller than the gap to BM25 — Evidence: https://arxiv.org/html/2503.09089 "Removing the TraverseGraph tool reduced module-level performance from 82.85% to 78.47%". Confidence: high. Implication: much of LocAgent's lift is the agent loop, not the graph itself.

6. LocAgent translates to only +12 points Pass@10 on downstream issue resolution despite 90%+ file-level localization — the "find the file" → "fix the bug" conversion is lossy — Evidence: https://arxiv.org/abs/2503.09089 "improving downstream GitHub issue resolution success rates by 12% for multiple attempts (Pass@10)." Confidence: high. (This is the clearest single data point on the construction-vs-consumption gap.)

7. CodexGraph is competitive but not dominant: on SWE-bench Lite it matches AutoCodeRover (22.96% vs 22.96% Pass@1) while crushing BM25 (3.11%), i.e., against a good AST-based baseline the graph interface adds nothing — Evidence: https://arxiv.org/html/arXiv:2408.03910 Table 1. Confidence: high.

8. CodexGraph's value is concentrated in the "write then translate" query-construction agent, not the graph itself: removing the translation agent drops CrossCodeEval EM from 27.90% to 8.30% — Evidence: https://arxiv.org/html/arXiv:2408.03910 ablation Table 3. Confidence: high. Implication: the graph is only useful if the agent can formulate Cypher-ish queries; the interface dominates the structure.

9. CodexGraph scales poorly with weaker models (GPT-4o 27.90% EM → Qwen2 5.00% EM on CrossCodeEval) and "sometimes encounters loops where it fails to generate executable graph queries" — Evidence: https://arxiv.org/html/arXiv:2408.03910. Confidence: high. This is the construction-vs-consumption gap quantified: the graph is built once, but only a strong enough consumer can use it.

10. CodeRAG (GraphCodeAgent, DevEval) isolates graph contribution by component-ablation: removing the graph-reasoning tool drops Pass@1 by 6.31 points — the largest single-component effect, ~3x code-testing tool and ~22x web search — Evidence: https://arxiv.org/html/2504.10046v1 "Graph reasoning tool removal: Caused 6.31 point decrease, the largest component impact." Confidence: high.

11. CodeCompass' "Navigation Paradox" is the cleanest negative/positive split in the literature: the same graph tool gives +23.2 points on hidden-dependency tasks (99.4% vs 76.2% vanilla, 78.2% BM25) but underperforms both baselines on structural tasks (76.4% vs 79.7% / 85.1%) because the agent refused to call it — Evidence: https://arxiv.org/html/2602.20048v1 Table of G1/G2/G3 ACS. Confidence: high. This is the strongest evidence that "graph built" ≠ "graph used."

12. The CodeCompass tool-adoption data is the specific bottleneck number: overall 42.0% trial-level adoption, 0% on structural (G2) tasks despite being designed for them; mean ACS 99.5% when invoked vs 80.2% when skipped — Evidence: https://arxiv.org/html/2602.20048v1 "the model appears to apply a rational heuristic … the overhead of calling the graph tool is not justified" when simpler tools reach ~80%. Confidence: high.

13. CodeRAG-Bench reports broad negative results for retrieval on hard repo tasks: SWE-bench-Lite "remained 'too complex' with near-zero pass rates even with perfect retrieval," and strong models showed "no improvement or degradation with retrieved documents on basic programming" — Evidence: https://arxiv.org/html/2406.14497v1. Confidence: high. Implication: for the hardest SWE tasks, better retrieval (graph or otherwise) does not move the needle — the bottleneck is generation, not context.

14. Codebase-Memory quantifies the "cheap but slightly worse" tradeoff of graphs vs live file exploration: 83% answer-quality vs 92% for a file-exploration agent, at 10x fewer tokens and 2.1x fewer tool calls — Evidence: https://arxiv.org/html/2603.27277v1. Confidence: high. Failure mode: "macros are not represented in the AST" (C at 0.58 vs 1.00) — parser coverage directly bounds graph utility.

15. Prometheus (tree-sitter multilingual KG) reaches 28.67% on SWE-bench Lite vs Agentless+GPT-4o's 27.00% and is the first system on SWE-bench Multilingual (13.7%, 34.9% on Java), but the paper runs no graph-removal ablation — Evidence: https://arxiv.org/html/2507.19942v1. Confidence: medium (numbers high, attribution to graph low).

16. LLM4FL (call-graph fault localization on Defects4J) reports –16.51% Top-1 when CodeNav is removed, yet still loses to the supervised GNN baseline DepGraph at Top-1 (327 vs 359, –8.64%) — Evidence: https://arxiv.org/html/2409.13642v2. Confidence: high. Implication: a trained graph-aware specialist still beats an LLM-with-graph-tool on the narrowest task.

17. Aggregate SWE-bench Lite picture: graph-assisted open-source scaffolds cluster in the 28–30% range (RepoGraph+Agentless 29.67%, CodexGraph 22.96%, Prometheus 28.67%, LLM-only Agentless-Lite 32.3% with plain embeddings), i.e., no graph system currently beats a well-tuned embedding retriever by more than its noise band — Evidence: https://www.swebench.com/lite.html and https://arxiv.org/html/2410.14684v1. Confidence: medium.

## Themes

Two patterns recur across every paper. First, graphs reliably help localization (finding the right file/function) — every ablation that removes graph access shows a measurable drop — but the lift shrinks dramatically when the metric is end-to-end issue resolution (LocAgent: 94% file-level → +12% Pass@10; RepoGraph: +2 points resolve rate; CodeRAG-Bench: near-zero on hard SWE-bench regardless of retrieval quality). The bottleneck moves from "where is the code" to "how do I edit it correctly," where graphs contribute little. Second, the "graph built" vs "graph consumed" gap is real and measurable: CodexGraph's translation agent is worth 19.6 points (vs the graph proper), CodeCompass' tool-adoption rate (42%) bounds its max lift, and weaker models can't use the graph interface at all (Qwen2 5% vs GPT-4o 27.9% on the same graph). The graph is infrastructure; the agent's ability to query it is the actual independent variable. Third, negative-result signal is strongest when tasks are categorized by dependency structure: graphs dominate on hidden/multi-hop architectural dependencies, break even on keyword-discoverable tasks, and can be net-negative on merely structural tasks where BM25 is already ~80% effective. Uniform benchmarks hide this by averaging.

## Open questions

- No published ablation isolates *which graph edge types* (CALLS vs IMPORTS vs INHERITS vs CTX_READS) drive the measured lift — all sources treat "the graph" as monolithic.
- Whether any published system evaluates graph benefit under a production-agent budget (fixed token / tool-call budget) is unclear; CodeCompass tracks adoption rate but not unit economics.
- No direct head-to-head on the same benchmark between (a) graph-as-context (RepoGraph-style inline) and (b) graph-as-tool (LocAgent/CodexGraph-style queryable DB); the implied comparison is across different benchmarks.
- LiveCodeBench is algorithmic/contest-style and therefore genuinely not a code-graph benchmark; I found no paper using LiveCodeBench to evaluate graph-based retrieval, which is itself a finding — but I could not source a paper explicitly stating this.
- The SWE-Bench Illusion paper (https://arxiv.org/html/2506.12286v3) raises contamination concerns for all SWE-bench numbers above; the degree to which graph systems in particular benefit from memorization is unstudied.
- Reviewer critiques of RepoGraph in OpenReview were inaccessible (403) so any peer-review concerns about null results in that paper are unresolved.

## Handoffs

- To slice 1 (industry):
  - CodexGraph's "weaker model = much worse graph use" result (finding 9) predicts that industry graph-tool products will show Opus/Sonnet-tier-specific lift — worth checking whether Cursor, Claude Code, Sourcegraph report model-tier ablation.
  - Codebase-Memory's token/tool-call efficiency numbers (10x fewer tokens, 2.1x fewer tool calls at 83% vs 92% quality — finding 14) are the right framing for any industry cost-vs-quality claim.
  - Moatless, Aider, Agentless are all on SWE-bench leaderboards with and without graph components; slice 1 should capture their reported resolve-rate deltas as industry data points, not academic.

- To slice 3 (tool-surface design):
  - CodeCompass tool-adoption finding (finding 12) is the single most actionable design signal: the agent won't call the graph tool when a simpler tool reaches ~80%. Prompt surface and tool description matter more than graph fidelity. The authors' fix ("checklist-at-END formatting" moved G3 adoption 85.7%→100%) is a concrete design lever.
  - CodexGraph's translation-agent ablation (finding 8): exposing raw Cypher is unusable; a natural-language-to-query layer is worth ~20 points. The tool-surface question is whether the model sees a query DSL or a set of pre-defined traversals.
  - RepoGraph's 1-hop-beats-2-hop result (finding 2) suggests tool surfaces should default to shallow neighborhoods; deeper is not better and can be worse.
  - LLM4FL loses to a trained GNN (finding 16) — so a graph tool that only surfaces raw structure to a general LLM has a ceiling below specialized fine-tuned models. Tool design should consider whether to embed ranking / scoring into the tool surface rather than relying on LLM-side reasoning over raw graph output.
