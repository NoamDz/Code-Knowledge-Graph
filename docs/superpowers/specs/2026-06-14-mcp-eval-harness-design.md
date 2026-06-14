# Spec — Eval Harness for the MCP Tool Surface

**Date:** 2026-06-14
**Status:** approved design, ready for implementation plan
**Scope:** a lightweight, incremental way to check that the 7 MCP tools
(`explain_flow`, `find_impact`, `onboard_to`, `locate`, `find_symbol`,
`get_code_snippet`, `get_file_outline`) return *meaningful* answers — not just
non-empty ones.

## Why

The current tests (`graph_builder/tests/`) cover the parsers/builder, not the
agent-facing tools. The only check on the tool surface is `tests/smoke_test.py`,
which *prints* output but asserts nothing — so `find_impact` shipped a Cypher
crash that no test caught (see `logs.txt`). We need tests that fail when a tool
stops giving useful information. Curating a big question set by hand is
expensive, so the design's first principle is: **derive the answer key from the
codebase at runtime wherever possible, so most tests need no hand-curation.**

## The five kinds of test (plain version)

A test here is a question asked of a tool where we already know what a good
answer looks like. Five kinds, cheapest first:

1. **Does it run?** Call the tool; it must not crash or return empty.
   *Catches the live `find_impact` crash.*
2. **Is it telling the truth?** Compare the answer to the real source. For
   simple facts (where is function X defined?) the **source code is the answer
   key** — the harness searches the files and checks the tool agrees. Automatic,
   no human input.
3. **Is it pointing at the right thing, not dumping noise?** The obvious target
   ranks near the top; a leaf symbol does not report a huge blast radius.
   *Needs a human to mark "the obvious answer" a handful of times.*
4. **Is the clever part actually clever?** The composites filter middleware and
   rerank by importance. Call a tool twice — normally and with
   `escape_hatch=True` — and assert the filtered version really differs (e.g.
   middleware hidden in one, shown in the other). Compares the tool to itself,
   so no answer key needed.
5. **Can someone get work done with it?** Give an agent a real developer
   question, let it use the tools, judge whether it reaches the right answer
   cheaply. *Most signal, most cost — last.*

## Phasing (start small, climb)

- **Phase 1 (now):** kinds **1, 2, 4**. Computer-checkable, near-zero curation,
  catches the live bug. This is the whole first deliverable.
- **Phase 2 (next):** kind **3**. Add a small set of human-marked "obvious
  answers" and simple scoring (how often the right target lands in the top *k*).
- **Phase 3 (later):** kind **5** — agent dogfood (this is the deferred
  `DESIGN.md` dogfood). Optionally an LLM judge that grades composite answers
  against the source at scale. Adds the first external dependency; out of scope
  until earlier phases are stable.

## Architecture (Phase 1)

Three small files under `tests/`, plain `pytest` + the existing `QueryEngine`.
**No new dependencies.**

```
tests/
├── eval_cases.py   # the questions + expected facts, as DATA (the only curated part)
├── conftest.py     # engine fixture; skips the whole suite if no graph is reachable
└── test_eval.py    # generic, parametrized over eval_cases.py; never changes per-case
```

Key decision: **cases are data, not code.** Adding a test = adding one row, so
growth is cheap and `test_eval.py` stays fixed.

Case shape (sketch — final form decided in the plan):

```python
@dataclass
class EvalCase:
    tool: str                       # "find_symbol" | "explain_flow" | ...
    input: dict                     # kwargs for the tool
    must_contain: list[str] = ()    # facts that must appear (regex ok)
    must_not_contain: list[str] = ()
    min_results: int | None = None  # sanity bounds (kind 3)
    max_results: int | None = None
    note: str = ""                  # why this is true — the verification trail
```

Two test families in `test_eval.py`:

- **Source-oracle cases (kind 2):** for `find_symbol` / `get_file_outline` /
  `get_code_snippet`, the harness scans `repo_root` for real definitions and
  asserts the tool reports the same file. Auto-generated from the source; no
  hand-curated facts.
- **Differential cases (kind 4):** for all four composites (`explain_flow`,
  `find_impact`, `onboard_to`, `locate`), call with `escape_hatch=False` vs
  `True` and assert the filtered result genuinely differs from the expanded one
  (the filtered output is a strict subset / different ordering). This needs **no
  hand-curated facts** — the tool is compared to itself. Optionally, once a
  specific middleware name is known, assert it appears only in the expanded
  version.

Plus a thin layer of **liveness cases (kind 1)**: one per tool, asserting it
runs and returns non-empty against a known input.

## Where it runs / labor split

Running anything needs a **populated Memgraph + the indexed source**, which live
on the Mac. The harness handles absence gracefully:

| Work | Needs source/graph? | Where it happens |
|---|---|---|
| Scaffolding + source-oracle + differential code | No (codebase-agnostic plumbing) | Any machine |
| Running the suite, fixing `find_impact` | Yes | Mac |
| The few Phase-2 "obvious answer" marks | Yes | Mac (drafted from source/BOB, human-approved) |

- **No graph reachable** → `conftest` skips the suite (clean on Windows / CI
  without a DB). Import of `QueryEngine` is lazy so collection never fails.
- **A tool raises** → test failure with traceback (this is how the
  `find_impact` crash surfaces). Phase-1 work: write that failing liveness case
  first, then fix the Cypher.

## Curation strategy (the expensive part, minimized)

- Phase 1 needs **no** hand-curated facts — the source is the answer key and the
  composites are checked against themselves.
- Phase 2 needs only ~5–10 human-marked "obvious answers," drafted by reading
  the source or via IBM BOB and approved by the user.
- **Regression-driven growth:** whenever a tool gives a bad answer in real use,
  paste it in as a new case. Curation never restarts.

## Success criteria (Phase 1)

1. `pytest tests/` runs the eval suite and **cleanly skips** when no graph is
   reachable.
2. Every one of the 7 tools has at least a liveness case (kind 1).
3. The `find_impact` crash is reproduced by a test, then fixed, then green.
4. Source-oracle cases (kind 2) exist for the three read primitives and pass
   against the real graph.
5. At least one differential case (kind 4) exists for each composite.

## Out of scope (YAGNI for now)

RAGAS / DeepEval / any eval framework; LLM-as-judge; a hermetic fixture repo;
CI wiring; the agent dogfood harness. Each belongs to a later phase above.
