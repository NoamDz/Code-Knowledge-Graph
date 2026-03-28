-- Fixture: missioner_timer.post dispatch
local missioner_timer = require("lib.lua.missioner")

local function analyze(data)
    -- line 4: timer-based dispatch
    missioner_timer.post("analyze_batch", data, 5)
end

return { analyze = analyze }
