# Code Knowledge Graph — Agent Usage Research (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the phase-1 research cycle to answer (Q1) "for which agent coding tasks does a code knowledge graph actually help?" and (Q2) "how do expert systems compose the graph with other retrieval?", producing a synthesis that supports a go/no-go decision on consumption-side build work.

**Architecture:** Parallel-dispatched literature / practitioner research. Three research agents produce structured briefs; the orchestrator synthesizes them into a single decision-ready deliverable; a phase-decision checkpoint commits to CONTINUE / CONCLUDE / PIVOT.

**Tech Stack:** `Agent` tool (`subagent_type: "general-purpose"`) for parallel dispatch, WebFetch / WebSearch for sources, markdown deliverables, git for versioning. No code changes to the graph builder or MCP server.

**Spec:** `docs/superpowers/specs/2026-04-20-code-graph-agent-usage-research-design.md`

---

## File Structure

All research outputs live at the repo root under `research/2026-04-20-code-graph-agent-usage/`:

- Create: `research/2026-04-20-code-graph-agent-usage/00_charter.md` — research charter (Task 1)
- Create: `research/2026-04-20-code-graph-agent-usage/01_industry.md` — slice 1 brief (Task 4, written by dispatched agent)
- Create: `research/2026-04-20-code-graph-agent-usage/02_academic.md` — slice 2 brief (Task 4, written by dispatched agent)
- Create: `research/2026-04-20-code-graph-agent-usage/03_tool_surface.md` — slice 3 brief (Task 4, written by dispatched agent)
- Create: `research/2026-04-20-code-graph-agent-usage/04_synthesis.md` — unified synthesis (Task 6)
- Create: `research/2026-04-20-code-graph-agent-usage/05_phase_decision.md` — CONTINUE / CONCLUDE / PIVOT decision (Task 9)

No existing files are modified. `research/` is not in `.gitignore`, so these files commit normally.

---

## Task 1: Write the research charter

**Files:**
- Create: `research/2026-04-20-code-graph-agent-usage/00_charter.md`

- [ ] **Step 1: Create the directory and charter file with this exact content**

```markdown
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
```

- [ ] **Step 2: Verify the file exists and looks right**

Run: `ls research/2026-04-20-code-graph-agent-usage/`
Expected: `00_charter.md`

- [ ] **Step 3: Commit**

```bash
git add research/2026-04-20-code-graph-agent-usage/00_charter.md
git commit -m "research(phase-1): add charter for code graph agent usage"
```

---

## Task 2: User approves charter (gate)

- [ ] **Step 1: Present the charter for user approval**

Post to the user: "Charter committed to `research/2026-04-20-code-graph-agent-usage/00_charter.md`. Please review and approve (or request changes) before I dispatch the three research agents."

- [ ] **Step 2: Wait for explicit user approval**

Do not proceed to Task 3 until the user has explicitly approved the charter. If the user requests changes, edit `00_charter.md`, amend the commit, and re-present.

---

## Task 3: Dispatch three parallel research agents

This is the core execution step. All three agents run in parallel via a **single message with three `Agent` tool calls** (multiple tool_use blocks in the same message — that's what triggers parallelism). Each agent writes its brief directly to disk.

**Files:**
- Each dispatched agent creates one file under `research/2026-04-20-code-graph-agent-usage/`

- [ ] **Step 1: Dispatch all three agents in parallel**

Send one assistant message containing three `Agent` tool calls (no other content between them). Use `subagent_type: "general-purpose"` for each. The exact prompts:

**Agent 1 — Slice 1 (Industry systems):**

```
You are researching how industry agent-based coding systems use code knowledge graphs in their retrieval stack. Produce a structured brief.

TARGET SYSTEMS (expand to include others you find credible):
- Sourcegraph / Amp / Cord
- Cursor
- Aider
- Windsurf
- Augment
- Claude Code (Anthropic)
- GitHub Copilot Workspace
- Continue

FOR EACH SYSTEM, ANSWER:
1. What does their code intelligence actually do? (product-level capabilities)
2. What role does a graph play in their retrieval? (load-bearing / auxiliary / none)
3. How do they compose graph + grep + embeddings + LLM-memory?
4. What does their agent-facing tool surface look like? (count, abstraction level, shape of return values)
5. Any published rationale for their design choices?

HARD RULES:
- Use WebFetch and WebSearch for every claim. Do not answer from training memory.
- Every claim in your brief must cite a specific URL — not "per Anthropic docs" but the exact page.
- Findings without a source URL go in "Open Questions," not "Key Findings."
- Explicitly search for negative evidence: tasks or conditions where these systems deliberately DO NOT use a graph. Zero negative evidence is a red flag; note it honestly.
- Flag anything you see that belongs to slice 2 (academic / benchmarks) or slice 3 (tool-surface design principles) in the Handoffs section.
- Out of scope for you: academic benchmark results, abstract tool-surface design principles.

WRITE YOUR BRIEF TO: research/2026-04-20-code-graph-agent-usage/01_industry.md

USE THIS EXACT FORMAT:

# Slice 1 — Industry Systems

## Sources consulted
[every URL, one-line note on signal quality]

## Key findings
1. [Claim in one sentence] — Evidence: [URL + direct quote or accurate summary]. Confidence: high / medium / low.
2. ...
(Aim for 8-12 numbered claims.)

## Themes
[2-4 sentences identifying patterns across findings]

## Open questions
[items you could not resolve; claims without a source]

## Handoffs
- To slice 2 (academic): [items]
- To slice 3 (tool-surface design): [items]

When you finish, return a ≤200-word summary of your findings and confirm the file was written.
```

**Agent 2 — Slice 2 (Academic / benchmarks):**

```
You are researching academic and benchmark evidence on whether code knowledge graphs help coding agents. Produce a structured brief.

TARGET SOURCES (expand as needed):
- RepoGraph (ICLR 2025)
- LocAgent (ACL 2025)
- Code-Graph-RAG and related graph-RAG papers
- SWE-bench and LiveCodeBench findings on code graphs
- Any published ablation studies on graph access for coding agents
- Related lab blogs (Anthropic, Princeton, Berkeley, etc.) discussing empirical results

FOR EACH SOURCE, ANSWER:
1. What was measured? (task type, benchmark, setup)
2. Did the graph produce measurable lift? How much, on which task types?
3. Where did the graph fail to help or hurt performance?
4. What's the gap between "graph built" and "agent benefits"? (i.e., construction vs consumption)

HARD RULES:
- Use WebFetch and WebSearch for every claim. Do not answer from training memory.
- Every claim must cite a specific URL (paper, preprint, or blog).
- Findings without a source URL go in "Open Questions," not "Key Findings."
- Explicitly search for negative / null results and failure modes. Papers that report "it didn't help on task X" are especially valuable.
- Flag anything that belongs to slice 1 (industry products) or slice 3 (tool-surface design) in the Handoffs section.
- Out of scope for you: product descriptions, tool-count opinions without measured data.

WRITE YOUR BRIEF TO: research/2026-04-20-code-graph-agent-usage/02_academic.md

USE THIS EXACT FORMAT:

# Slice 2 — Academic / Benchmarks

## Sources consulted
[every URL, one-line note on signal quality]

## Key findings
1. [Claim in one sentence] — Evidence: [URL + direct quote or accurate summary]. Confidence: high / medium / low.
2. ...
(Aim for 8-12 numbered claims.)

## Themes
[2-4 sentences identifying patterns]

## Open questions
[items you could not resolve]

## Handoffs
- To slice 1 (industry): [items]
- To slice 3 (tool-surface design): [items]

When you finish, return a ≤200-word summary of your findings and confirm the file was written.
```

**Agent 3 — Slice 3 (Tool-surface design):**

```
You are researching what makes agent-facing tool surfaces effective. Produce a structured brief.

CORE QUESTION: Is "16 tools" too many for an LLM agent to navigate? Under what conditions? What tool abstractions work, and why?

TARGET SOURCES:
- Anthropic's writing on tool use (claude.ai/docs, engineering blog, cookbook)
- Model Context Protocol (MCP) docs and ecosystem patterns
- OpenAI function-calling guides and postmortems
- Published retrospectives or postmortems on tool-surface failures (agents that couldn't find the right tool)
- Practitioner writing on tool-count, return-format, and tool-abstraction choices
- Academic work on tool selection by LLMs (if any is findable)

QUESTIONS TO ANSWER:
1. What's the evidence on tool count? (Does >N tools measurably degrade selection accuracy?)
2. Low-level primitives vs high-level workflow tools — which wins, when?
3. Return format choices: structured data vs summarized text vs both?
4. Discovery mechanisms: how do successful systems help agents find the right tool?
5. One NL→Cypher escape hatch vs many typed tools — is there evidence either way?

HARD RULES:
- Use WebFetch and WebSearch for every claim. Do not answer from training memory.
- Every claim must cite a specific URL.
- Findings without a source URL go in "Open Questions."
- Take an explicit position where possible, citing evidence — not "it depends."
- Flag anything that belongs to slice 1 (specific company products) or slice 2 (graph-specific benchmarks) in Handoffs.
- Out of scope for you: specific company products (unless citing their tool-surface rationale specifically), graph-specific academic work.

WRITE YOUR BRIEF TO: research/2026-04-20-code-graph-agent-usage/03_tool_surface.md

USE THIS EXACT FORMAT:

# Slice 3 — Tool-Surface Design

## Sources consulted
[every URL, one-line note on signal quality]

## Key findings
1. [Claim in one sentence] — Evidence: [URL + direct quote or accurate summary]. Confidence: high / medium / low.
2. ...
(Aim for 8-12 numbered claims.)

## Themes
[2-4 sentences identifying patterns]

## Open questions
[items you could not resolve]

## Handoffs
- To slice 1 (industry): [items]
- To slice 2 (academic): [items]

When you finish, return a ≤200-word summary of your findings and confirm the file was written.
```

- [ ] **Step 2: Wait for all three agents to return**

Parallel dispatch means you get three separate tool-result messages. Read each summary but do not begin synthesis until all three briefs exist on disk.

---

## Task 4: Verify briefs meet format and quality

**Files:**
- Read: `research/2026-04-20-code-graph-agent-usage/01_industry.md`
- Read: `research/2026-04-20-code-graph-agent-usage/02_academic.md`
- Read: `research/2026-04-20-code-graph-agent-usage/03_tool_surface.md`

- [ ] **Step 1: Confirm each brief exists and follows the required format**

For each of the three files, verify all sections are present: Sources consulted, Key findings (≥8 numbered), Themes, Open questions, Handoffs.

- [ ] **Step 2: Spot-check citations (~20% sample)**

For each brief, pick 2 random key findings. Use WebFetch to confirm the cited URL actually exists and supports the claim. If a citation is fabricated or doesn't support the claim, the entire finding is rejected and the slice must be re-dispatched (go to Step 4).

- [ ] **Step 3: Check for red flags**

- Any brief with **zero** negative-evidence or skepticism findings: flag it. The charter required explicit search for negative evidence.
- Any brief with fewer than 8 numbered findings: flag as thin.
- Any brief with un-cited claims in "Key findings": reject those claims (move them to Open Questions).

- [ ] **Step 4: (Conditional) Re-dispatch a slice**

If a slice is rejected, re-dispatch it with a tighter prompt addressing the specific failure mode (fabricated citations, missing negative evidence, too thin). Do not proceed to synthesis until all three briefs pass verification.

- [ ] **Step 5: Commit the briefs**

```bash
git add research/2026-04-20-code-graph-agent-usage/01_industry.md \
        research/2026-04-20-code-graph-agent-usage/02_academic.md \
        research/2026-04-20-code-graph-agent-usage/03_tool_surface.md
git commit -m "research(phase-1): add three parallel research briefs"
```

---

## Task 5: Invoke research-results-analysis skill

- [ ] **Step 1: Invoke the skill**

Use the `Skill` tool with `skill: "research-results-analysis"`. The skill is designed for exactly this situation: synthesizing research outputs into an analysis document at `04_analysis.md` (or here, `04_synthesis.md`).

If the skill expects a different file naming convention than our spec (`04_synthesis.md`), follow the skill's convention and update the charter to match.

- [ ] **Step 2: Follow the skill's instructions**

The skill will guide you through structured synthesis. Do not freelance.

---

## Task 6: Write the unified synthesis

**Files:**
- Create: `research/2026-04-20-code-graph-agent-usage/04_synthesis.md`
- Read: all three briefs from Task 4

The synthesis is the deliverable the user reads. It must meet the spec's success criteria.

- [ ] **Step 1: Build the task-fit matrix**

Table with rows = agent coding tasks (aim for ≥6: impact analysis, onboarding to a feature, debugging, refactoring, code review, feature implementation, codebase Q&A, test authoring; add any that surfaced in the briefs). Columns: Graph role (load-bearing / helpful / marginal / unhelpful), Typical composition (graph-only / graph+grep / graph+embeddings / graph+LLM-memory), Source evidence (cite which brief + finding number).

Every cell must cite at least one finding from slice 1 or 2. No cell may be "uncertain" without an open-question footnote.

- [ ] **Step 2: Write the composition-patterns section**

Identify 3-5 distinct patterns experts use to combine graph + other retrieval. For each: a name (e.g., "graph-first with grep fallback"), a one-paragraph description, at least one concrete cited example.

- [ ] **Step 3: Write tool-surface recommendations**

Take an **explicit defended position** on:
- Tool count — how many is right for this graph, and why?
- Abstraction level — low-level primitives, high-level workflows, or a single NL→Cypher escape hatch?
- Return format — structured / summarized / both?

Cite slice 3 findings. If evidence doesn't support a strong position on a sub-question, say so plainly and move it to open questions. Do not hedge everywhere.

- [ ] **Step 4: Write "Implications for Pinpoint"**

Based on the current 16-tool MCP surface (see `mcp_server/server.py`), name specific tools to **keep**, **merge**, or **cut**. Name specific **use cases to prioritize** for the consumption-side build. Name specific **gaps** in what the current graph supports.

- [ ] **Step 5: Write open questions and phase-2 candidates**

List what didn't resolve. For each, note whether it's a candidate for phase-2 follow-up (empirical dogfooding, deeper literature, interview, etc.).

- [ ] **Step 6: Verify success criteria**

Read through the synthesis and confirm each of the success criteria from the charter holds:
- [ ] Task-fit matrix covers ≥6 task types with ≥2 evidence cells each
- [ ] ≥3 composition patterns, each with ≥1 concrete example
- [ ] Tool-surface recommendations take explicit defended positions
- [ ] Every synthesis claim cites a source URL (no un-cited assertions)
- [ ] "Implications for Pinpoint" names specific tools to keep / merge / cut and use cases to prioritize

If any criterion fails, fix the synthesis before committing.

- [ ] **Step 7: Commit the synthesis**

```bash
git add research/2026-04-20-code-graph-agent-usage/04_synthesis.md
git commit -m "research(phase-1): add unified synthesis with task-fit matrix and recommendations"
```

---

## Task 7: Findings QA with user

- [ ] **Step 1: Invoke research-findings-qa skill**

Use the `Skill` tool with `skill: "research-findings-qa"`. This skill walks the user through the synthesis and confirms understanding before the phase-decision step.

- [ ] **Step 2: Follow the skill's instructions**

The skill handles the user-facing walkthrough. Respond to user pushback by editing `04_synthesis.md` and amending the commit. Do not proceed to Task 8 until the user has explicitly confirmed understanding and agreement with the framing.

---

## Task 8: Phase decision

- [ ] **Step 1: Invoke research-phase-decision skill**

Use the `Skill` tool with `skill: "research-phase-decision"`. This produces a structured CONTINUE / CONCLUDE / PIVOT decision.

- [ ] **Step 2: Write the decision artifact**

Write the decision to `research/2026-04-20-code-graph-agent-usage/05_phase_decision.md`. Structure:

```markdown
# Phase 1 Decision

**Date:** [YYYY-MM-DD]
**Decision:** CONTINUE / CONCLUDE / PIVOT

## Reasoning
[One page max. Capture WHY this decision, grounded in specific synthesis findings.
This must be legible to future-you without re-reading the synthesis.]

## Implications
- [Concrete consequence 1]
- [Concrete consequence 2]

## Next step
- If CONTINUE or PIVOT: invoke research-next-phase-proposal (Task 9).
- If CONCLUDE: invoke superpowers:writing-plans on the scoped consumption-side build.
```

- [ ] **Step 3: Commit the decision**

```bash
git add research/2026-04-20-code-graph-agent-usage/05_phase_decision.md
git commit -m "research(phase-1): phase decision — [CONTINUE|CONCLUDE|PIVOT]"
```

---

## Task 9 (conditional): Next-phase proposal

**Only execute if Task 8 decision was CONTINUE or PIVOT.**

- [ ] **Step 1: Invoke research-next-phase-proposal skill**

Use the `Skill` tool with `skill: "research-next-phase-proposal"`. The skill scopes the next phase — question, slices, deliverable, success criteria.

- [ ] **Step 2: Present the proposal and await user approval**

Do not begin phase 2 work without explicit user approval. Phase 2 is its own cycle with its own charter, its own briefs, its own synthesis.

---

## Self-review (already performed)

**Spec coverage:** every section of the spec maps to a task:
- Motivation + research questions → Task 1 charter
- Three slices → Task 3 parallel dispatch (one agent per slice)
- Deliverable shape (brief format + synthesis sections) → embedded in Task 3 prompts and Task 6 synthesis steps
- Success criteria → Task 6 Step 6 explicit checklist
- Filesystem layout → File Structure section + Task 1/3/6/8 file paths
- Risks and mitigations (hallucinated citations, thin findings, etc.) → Task 4 verification steps
- Phase-decision mechanics → Tasks 7, 8, 9

**Placeholder scan:** no TBD/TODO. Dispatch prompts are the full content the engineer runs — not "similar to ..." references.

**Type / name consistency:** `04_synthesis.md` in the spec aligns with the plan. One known deviation: `research-results-analysis` skill may prefer `04_analysis.md`; Task 5 handles this by deferring to the skill's convention.

---

## Execution notes

- Task 3 (parallel dispatch) is the one step where getting the message structure right matters. Three `Agent` tool calls must be in a single assistant message to run in parallel.
- Tasks 2 and 7 are **user gates**. Do not skip them or proceed on implicit approval.
- Task 4 is the **quality gate**. Re-dispatch a slice rather than synthesizing over thin / fabricated briefs.
- If any of the research-* skills behave unexpectedly or their conventions conflict with this plan, follow the skill and note the deviation in the next commit message.
