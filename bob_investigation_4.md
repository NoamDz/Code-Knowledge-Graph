# BOB Investigation — Round 4: Strategy Reset

## Context

We're building a **Code Knowledge Graph** — a tool that parses this codebase with Tree-sitter and builds a semantic graph of all code relationships. After 3 rounds of investigation and many code fixes, we still have **324 out of 1234 files (26%) completely disconnected** from the graph — zero edges to any other file.

**The problem isn't individual detection patterns anymore — it's fundamental architectural gaps** in how we model each language's dependency system.

Our current state:
- **Lua:** 93.9% import resolution, 48.7% call resolution, only 25 orphan files — GOOD
- **Go:** 0% import resolution, 73/73 files orphaned — BROKEN
- **JS:** 0% import resolution, 94/94 files orphaned — BROKEN
- **Python:** 36.7% import resolution, 22 orphans — NEEDS WORK
- **Ruby:** 2.3% import resolution, 139/151 files orphaned — BROKEN

We need to understand **how files in each language actually depend on each other** so we can build the right connection model.

---

## SECTION A: Go Module System (0% import resolution, 73 orphans)

**Background:** Our Go resolver tries suffix matching on file paths, but resolves 0/512 imports. Go uses a module system (`go.mod`) with module paths like `pinpoint/model_prediction/server/models`. We're clearly not understanding the Go import system correctly.

**A1.** Show the contents of the `go.mod` file(s) in the Go codebase. What is the module path declared? (e.g., `module github.com/company/project`)

**A2.** Show 5 import blocks from different Go files. For each one, categorize each import as:
- **Stdlib** (e.g., `"fmt"`, `"context"`, `"net/http"`)
- **Internal** (from within this project — what does the path look like?)
- **External** (third-party like `"github.com/go-redis/redis/v8"`)

**A3.** For an internal import like `"pinpoint/model_prediction/server/models"`, what is the actual file path on disk? Show the mapping: import path → directory path → files in that directory.

**A4.** How many Go imports are internal (should resolve) vs stdlib vs external? Rough percentage split.

**A5.** Are there multiple Go modules in this repo (multiple `go.mod` files), or just one?

---

## SECTION B: JavaScript Dependency Model (0% import resolution, 94 orphans)

**Background:** JS files in this codebase are browser IIFEs — they don't use `require()` or `import`. They share globals via `window.Container`, `window.Net`, etc. Our resolver looks for `require()` calls, which is why 0% resolves. But these files ARE connected — they're loaded together by the Ruby build system and depend on each other via shared globals.

**B1.** How are JS files loaded into the browser? Show the HTML template or ERB file that includes `<script>` tags. Is there a manifest file, a build script, or a template that lists which JS files get bundled together?

**B2.** Show a concrete example of how JS file A depends on JS file B. For example:
- File A defines `Container._sendRequest = function(...) {}`
- File B calls `Container._sendRequest("POST", "/api/assess")`
- How does the build system know to include both files?

**B3.** Is there a Ruby build/generator script that scans for JS files and produces the bundle? Show how it works — what directories does it scan? What order does it include files?

**B4.** Do JS files have any explicit dependency markers? Like comments (`// requires: net.js`), filename conventions, or directory structure that implies loading order?

**B5.** For the 94 JS files, how many are:
- Core library files (like `net.js`, `container.js`) that define shared infrastructure?
- Collector-specific files (like `device.js`, `behave.js`) that implement features?
- Utility files?
Give a rough categorization.

**B6.** Within a collector (e.g., device collector), what JS files exist and how do they relate to each other? Show one complete collector's file list and how they interact.

---

## SECTION C: Ruby File Relationships (2.3% import resolution, 139 orphans)

**Background:** Ruby resolution is at 2.3% with 139 orphan files. The Ruby code is build-time generators that produce ERB templates. We need to understand how Ruby files depend on each other.

**C1.** Show the directory structure of the Ruby codebase (just the first 2-3 levels, with file counts per directory).

**C2.** Show 5 `require` or `require_relative` statements from different Ruby files, with:
- The exact string argument
- The actual file path the import should resolve to
- Whether the import is a gem (external) or internal project code

**C3.** How does the Ruby build system work? Is there a main entry point (like a Rakefile or script) that orchestrates everything? Show how Ruby files get invoked.

**C4.** Do the Ruby generator files have a fixed execution order? Or can they run independently?

**C5.** For the 139 orphan files — pick 5 representative ones and show:
- What the file does
- What it imports
- What imports IT (who depends on it)
- Why it's an orphan (is it truly isolated, or is the resolver missing connections?)

---

## SECTION D: Python Gaps (36.7% import resolution, 22 orphans)

**D1.** For the 22 orphan Python files — pick 5 and show:
- What the file does (entry point? utility? test?)
- What it imports (all imports at the top)
- Is it a standalone script, or does it have internal imports that should resolve?

**D2.** Are the Python services (deferrer, aggregator, poller) structured as packages? Do they have `__init__.py` files? Show the directory structure.

---

## SECTION E: Lua Remaining Gaps (25 orphans, 48.7% call resolution)

**E1.** For the 25 orphan Lua files — pick 5 and show:
- What the file does
- Does it have any `require` or `require_version` calls?
- Is it a standalone config/script, or should it be connected?

**E2.** The call resolution jumped from 33% to 48.7% (great!). What are the remaining 51.3% unresolved calls? Run `code-graph spot-check` on 2 handler files that have many unresolved calls. Show the output — specifically the list of unresolved calls. What callee_strings appear most often?

**E3.** Are there Lua files that are loaded by nginx but NOT via `require()`? For example, `content_by_lua_file` directives point directly to files without going through the module system. How many such files exist?

---

## SECTION F: Cross-Language Connections

**Background:** A code knowledge graph should capture not just within-language dependencies but cross-language flows. This codebase has: Ruby generates JS → JS calls Lua → Lua calls Go → Lua writes Redis → Python reads Redis. These cross-language edges are what make the graph valuable for understanding the system.

**F1.** The Ruby→JS connection: Show exactly how a Ruby generator takes a `.js.erb` template and produces a final `.js` file. What Ruby file processes what JS template? Show 2-3 concrete examples.

**F2.** The JS→Lua connection: When `Container._sendRequest("POST", "/api/assess")` is called, the request goes to nginx which dispatches to Lua. Is there a way to know which nginx location serves `/api/assess`? (We know the answer from previous rounds — just confirm the mapping: `/api/*` → `router/main.lua` → controller → handler)

**F3.** The Lua→Python connection: Show 2-3 concrete examples of Lua writing to `/tmp/pinpoint_missions/` and which Python file processes those missions. Is there a direct mapping (mission type → Python handler)?

**F4.** Are there any other cross-language connections we haven't discussed? For example:
- Does Go call back into Lua or Python?
- Does Python call any Go or Lua services?
- Are there shared config files read by multiple languages?

---

## SECTION G: What Would Make This Graph Actually Useful?

**Background:** The ultimate consumer of this graph is an AI agent (like BOB) that needs to answer questions about the codebase. We want to ask questions like "what happens when a user hits /api/assess?" and get a complete answer tracing through all layers.

**G1.** If you could ask any questions about this codebase and get instant answers, what would be the top 5 most useful questions? Think about what's hardest to figure out manually.

**G2.** When you investigate a bug or trace a request flow, what information do you wish you had that requires reading multiple files? Show a concrete example of a question that requires understanding 3+ files.

**G3.** Are there any "hidden" connections between files that aren't captured by imports/requires? For example:
- Files that communicate via Redis channels
- Files that share data through file system conventions
- Files that are connected by naming conventions (e.g., `handler/policy.lua` and `assessors/policy.lua` are related by the "policy" name)
- Configuration files that reference Lua module paths

**G4.** What documentation or config files exist that describe the system architecture? (e.g., README files, architecture docs, docker-compose.yml, deployment configs). These might contain connection information not visible in code.
