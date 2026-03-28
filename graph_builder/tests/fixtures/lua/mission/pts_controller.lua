-- Fixture: mission dispatch from a controller
local missioner = require("deferrer.missioner.client")

local function apply(request)
    -- some logic here
    -- some more logic
    -- line 7: dispatch call
    missioner.add_mission("pts_run", params, 0, "policy")
end

return { apply = apply }
