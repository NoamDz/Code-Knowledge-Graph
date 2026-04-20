# Code Knowledge Graph — Agent Usage Research (Phase 1)

**Date:** 2026-04-20
**Type:** Research project (not a build)
**Audience:** user only — terse, internal notes quality
**Status:** spec approved, awaiting phase-1 execution

---

## Motivation

The graph-construction side of the project is mature: 100% parse across 5 languages, ~85% import resolution, 46% call resolution (63% effective), 17+ edge types, 1,234 files, 1,125 Redis edges. The natural next phase is the consumption layer — making the graph useful to an agent.

Before building more consumption-side tooling, two questions are load-bearing and unresolved:

- **Q1 — Task fit.** For which agent coding tasks does a code knowledge graph actually help, vs where is grep / embeddings / LLM-memory alone equivalent or better?
- **Q2 — Composition.** How do expert systems (Sourcegraph, Cursor, Aider, Amp, Claude Code, etc.) compose the graph with other retrieval? When do they use which?

Secondary concern: the existing MCP server already exposes 16 tools. An agent facing too-large a tool surface may not use it well. Any consumption-side build should be informed by evidence on tool-surface design, not guessed.

Without evidence on Q1 and Q2, consumption-side work risks building more tools for use cases that don't benefit, and in a shape agents can't navigate.

---

## Non-goals (phase 1)

- No code changes to the graph builder or MCP server.
- No empirical benchmarking on the Pinpoint codebase. Pure literature / practitioner synthesis. Empirical work, if warranted, is a phase-2 candidate.
- No decision on specific semantic-augmentation work (embeddings, PageRank). Phase 1 may surface evidence that informs this later.
- Not a public artifact. Audience is the user only.

---

## Approach

A single research cycle, anchored by a charter, executed in parallel across three slices, synthesized into a unified deliverable, and terminated by a phase-decision checkpoint.

Uses the existing research-skill stack:
- `research-charter-anchor` — anchors the cycle
- `dispatching-researcher-team` — fans out the three parallel slices
- `research-results-analysis` — drives synthesis
- `research-findings-qa` — confirms user understanding before the decision
- `research-phase-decision` — CONTINUE / CONCLUDE / PIVOT
- `research-next-phase-proposal` — scopes phase 2 if continuing

---

## Workflow

```
1. Write research charter           (me → 00_charter.md)
2. User approves charter             (gate)
3. Dispatch 3 parallel research agents (dispatching-researcher-team)
4. Agents return structured briefs   (01/02/03_*.md)
5. Synthesize into unified deliverable (me → 04_synthesis.md)
6. research-findings-qa              (user confirms understanding)
7. research-phase-decision           (→ 05_phase_decision.md)
8. If CONTINUE/PIVOT: research-next-phase-proposal scopes phase 2
```

The charter is the load-bearing artifact — it fixes scope per slice, brief format, success criteria. Once approved, execution is largely mechanical.

---

## The three slices

Parallelism only works if slice boundaries are sharp enough to prevent duplicate work.

### Slice 1 — Industry systems (what experts *ship*)

**In scope:** Sourcegraph / Amp / Cord, Cursor, Aider, Windsurf, Augment, Claude Code, GitHub Copilot Workspace, Continue, plus 2-3 additional credible systems the agent surfaces. For each: what does their code intelligence actually do, what role does a graph play vs grep / embeddings / LLM memory, how are these composed, what does their tool surface look like.

**Sources:** product docs, engineering blogs, talks, changelogs, OSS repos.

**Out of scope:** academic benchmarks (→ slice 2), abstract tool-surface design principles (→ slice 3).

### Slice 2 — Academic / benchmarks (what the *evidence* says)

**In scope:** RepoGraph (ICLR 2025), LocAgent (ACL 2025), code-graph-RAG papers, SWE-bench / LiveCodeBench findings on code graphs, published ablations. Which task types show measured lift from graph access, what are the failure modes, what's the gap between "graph built" and "agent benefits."

**Sources:** papers, preprints, lab blogs.

**Out of scope:** industry product descriptions, tool-count opinions unsupported by data.

### Slice 3 — Tool-surface design (what makes *agent-facing tools* usable)

**In scope:** Anthropic's writing on tool use, MCP ecosystem patterns, postmortems / retrospectives on tool-surface failures, evidence on tool-count and abstraction level across agent systems. Key question: is "16 tools" too many? Under what conditions? What abstractions work? Low-level primitives vs high-level workflows vs an NL→Cypher escape hatch?

**Sources:** Anthropic / OpenAI blog posts, MCP docs, practitioner writing, relevant academic work on tool selection by LLMs.

**Out of scope:** specific company products (unless citing their tool-surface rationale), graph-specific academic work.

### Anti-overlap rule

Each agent's brief must include a "handoffs" section listing things they saw that belong to a different slice. During synthesis I cross-check and de-dupe, picking the strongest treatment.

---

## Deliverables

### Per-slice brief (each ~2-3 pages)

- **Sources consulted** — every URL, one-line note on signal quality
- **Key findings** — ~8-12 numbered claims. Each: claim in one sentence + evidence (source link + quote or summary) + confidence (high / medium / low)
- **Themes** — 2-4 sentences identifying patterns
- **Open questions** — unanswered items, sources needed
- **Handoffs** — cross-slice observations

**Hard rule:** no un-cited claims. Findings without a source URL go in "open questions," not "key findings."

### Unified synthesis (~5-10 pages, me)

- **Task-fit matrix** — rows = agent coding tasks (impact analysis, onboarding, debugging, refactoring, code review, feature implementation, codebase Q&A, test authoring, + any that surface). Columns = graph role (load-bearing / helpful / marginal / unhelpful), typical composition pattern (graph-only / graph+grep / graph+embeddings / graph+LLM-memory), source evidence. Each cell cites slices 1 and 2.
- **Composition patterns** — 3-5 distinct patterns experts use to combine graph + other retrieval, with concrete examples.
- **Tool-surface recommendations** — defended position on tool count, abstraction level, return formats. Cites slice 3.
- **Implications for Pinpoint** — which existing 16 tools to keep / merge / cut, which use cases to prioritize, what's missing.
- **Open questions and phase-2 candidates** — what didn't resolve, what deserves deeper investigation.

---

## Filesystem layout

```
research/2026-04-20-code-graph-agent-usage/
├── 00_charter.md
├── 01_industry.md
├── 02_academic.md
├── 03_tool_surface.md
├── 04_synthesis.md
└── 05_phase_decision.md
```

---

## Success criteria (phase 1 done when)

- Task-fit matrix covers ≥6 task types, ≥2 evidence cells each
- Composition-patterns section identifies ≥3 distinct patterns, ≥1 concrete example each
- Tool-surface recommendations take an explicit defended position on tool count and abstraction — not "it depends"
- Every synthesis claim cites a source URL; zero un-cited assertions
- "Implications for Pinpoint" names specific tools to keep / merge / cut and specific use cases to prioritize
- Synthesis is readable end-to-end in one sitting and supports a go/no-go decision on named phase-2 options

If briefs come back too thin to meet these, I flag it at synthesis time and either re-dispatch a slice with a tighter prompt or lower the bar explicitly in the phase-decision doc. Not silently.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated citations | Every claim includes a clickable URL. During synthesis I spot-check ~20% of citations. Fabricated sources kill the finding and lower the slice's confidence bar. |
| Training-data recall instead of actual research | Charter explicitly instructs agents to use WebFetch / WebSearch for every claim, and to cite specific URLs. Briefs without URLs are rejected at review. |
| Thin findings from a slice | Brief honestly flags it; I re-dispatch with a tighter prompt or downgrade that slice's weight in synthesis with a note in open questions. Never paper over gaps. |
| Slice overlap drift | "Handoffs" section in each brief makes overlap visible. I de-dupe during synthesis. |
| Confirmation bias (filtering for "graph is useful") | Charter explicitly asks for tasks where graphs *don't* help, and for expert skepticism. Zero negative evidence from a slice is a red flag. |
| Phase-2 scope creep | `research-next-phase-proposal` commits to a narrow next phase. User approves the scope before any phase-2 work. |

---

## Phase-decision mechanics

After synthesis is written:

1. **research-findings-qa** — user reads `04_synthesis.md`; I walk through it; user confirms understanding and framing, or pushes back (we revise before deciding).
2. **research-phase-decision** — structured CONTINUE / CONCLUDE / PIVOT choice written into `05_phase_decision.md` with reasoning.
3. **research-next-phase-proposal** — only on CONTINUE or PIVOT. Scopes a specific phase-2 cycle.

Expected outcomes:

- **CONTINUE deeper** — one high-impact, under-evidenced finding deserves follow-up (e.g., "no published tool-surface ablation" → empirical on our own codebase).
- **CONCLUDE and build** — synthesis gives enough to redesign the tool surface and pick consumption work with confidence. Invoke `writing-plans` on a focused build.
- **PIVOT** — phase 1 surfaces the real question is elsewhere (e.g., "graph is fine, the problem is system prompting"); we recharter.

The decision artifact is short — one page — but captures the *reasoning*, so future-you can reconstruct why phase 2 was scoped as it was.
