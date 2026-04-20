# Phase 1 Research Charter — Code Graph Agent Usage

**Date:** 2026-04-20
**Cycle:** Phase 1 (of a phased research project)
**Spec:** docs/superpowers/specs/2026-04-20-code-graph-agent-usage-research-design.md

## Research questions

**Q1 — Task fit.** For which agent coding tasks does a code knowledge graph actually help an agent, vs where is grep / embeddings / LLM-memory alone equivalent or better?

**Q2 — Composition.** How do expert systems (Sourcegraph, Cursor, Aider, Amp, Claude Code, etc.) compose the graph with other retrieval? When do they use which?

Secondary: evidence-informed view on tool-surface design (is 16 tools too many for an agent to navigate?).

## In scope

- Literature synthesis from industry blogs, product docs, engineering talks, academic papers, and practitioner writing.
- Explicit search for negative evidence (tasks where graphs don't help; systems that deliberately chose not to use graphs).

## Out of scope (phase 1)

- Empirical benchmarking on the Pinpoint codebase.
- Code changes to the graph builder or MCP server.
- Decisions on semantic augmentation (embeddings, PageRank).

## Slice assignments

- **Slice 1 — Industry systems:** what experts ship (Sourcegraph / Amp / Cord, Cursor, Aider, Windsurf, Augment, Claude Code, GitHub Copilot Workspace, Continue, + others the agent finds). → `01_industry.md`
- **Slice 2 — Academic / benchmarks:** what the evidence says (RepoGraph, LocAgent, code-graph-RAG, SWE-bench findings, published ablations). → `02_academic.md`
- **Slice 3 — Tool-surface design:** what makes agent-facing tools usable (tool count, abstraction, MCP patterns, postmortems). → `03_tool_surface.md`

## Success criteria (phase 1 done when)

- Task-fit matrix covers ≥6 task types with ≥2 evidence cells each
- Composition-patterns section identifies ≥3 distinct patterns, ≥1 concrete example each
- Tool-surface recommendations take an explicit defended position on tool count and abstraction — not "it depends"
- Every synthesis claim cites a source URL; zero un-cited assertions
- "Implications for Pinpoint" names specific tools to keep / merge / cut and specific use cases to prioritize

## Hard rules (apply to every brief)

- Every claim must include a clickable source URL.
- No answering from training memory. Use WebFetch / WebSearch for every claim.
- Findings without a source URL go in "Open Questions," not "Key Findings."
- Explicit search for negative evidence. A slice returning zero skepticism is a red flag.
- Each brief ends with a "Handoffs" section listing observations belonging to other slices.

## Expected phase-1 outcomes

- **CONTINUE deeper** — one finding is high-impact but under-evidenced; go deeper (possibly empirical on our own codebase).
- **CONCLUDE and build** — synthesis gives enough to invoke `writing-plans` on focused consumption-side work.
- **PIVOT** — phase 1 reveals the real question is elsewhere; recharter.
