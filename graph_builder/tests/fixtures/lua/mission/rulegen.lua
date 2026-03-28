-- Fixture: binding-based mission dispatch
local missioner = require("deferrer.missioner.client")

local function run_check()
    -- line 4: dispatch via bound variable
    missioner.add_mission("rulegen_check", {}, 0, "default")
end

return { run_check = run_check }
