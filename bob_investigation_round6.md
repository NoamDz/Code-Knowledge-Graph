# BOB Investigation — Round 6: Mission Dispatch Detection Gap

## Context

We built a mission dispatch detector that scans Lua code for `missioner.add_mission("task_name", ...)` and `missioner_timer.post(...)` calls. It matches these patterns in CallRef objects and via binding resolution from `require_version("core.deferrer.missioner.client")`.

**Problem:** We detect only **6 mission dispatches** but BOB previously confirmed **74 call sites** exist. Our pattern matching works for the calls it finds — the issue is that most mission calls in the codebase don't appear as `missioner.add_mission` or `missioner_timer.post` callee strings in the AST.

BOB previously said: "Most missions use async timers (`missioner_timer.post()`) rather than direct `add_mission()` calls."

We need to understand the EXACT syntax of these timer-based calls to fix our detection.

---

## Questions

**Q1.** Show 5 concrete `missioner_timer.post(...)` calls from different Lua files with full context (3 lines before and after). For each, show:
- The exact line of code
- How `missioner_timer` is imported/required (what module path?)
- Is `missioner_timer` a local variable bound via `require_version()`?

**Q2.** Are there mission dispatch patterns BESIDES `missioner.add_mission()` and `missioner_timer.post()`? For example:
- `missioner:add_mission()` (colon syntax instead of dot)
- `local m = missioner; m.add_mission()` (aliased variable)
- `deferrer.add_mission()` or `deferrer_client.add_mission()`
- Any other wrapper functions that internally call `add_mission`

Show examples of each pattern that exists.

**Q3.** How is `missioner_timer` required? Is it:
- `local missioner_timer = require_version("core.deferrer.missioner.timer")`
- `local missioner_timer = require_version("lib.lua.missioner_timer")`
- Something else?

Show the exact require statement from 3 different files that use `missioner_timer.post()`.

**Q4.** When `missioner_timer.post()` is called, what are the arguments? Is it the same signature as `add_mission(name, params, delay, queue)`? Show 3 examples with the actual argument values so we can extract the task name.

**Q5.** Are there files that dispatch missions through wrapper/helper functions? For example:
```lua
local function defer_task(name, data)
    missioner.add_mission(name, data, 0, "default")
end
-- Later:
defer_task("assess", params)
```
If wrapper patterns exist, show 3 examples with the wrapper function and its callers.
