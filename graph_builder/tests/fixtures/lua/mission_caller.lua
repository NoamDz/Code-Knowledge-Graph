local require_version = require("loader.lua").require_version
local missioner = require_version("core.deferrer.missioner.client")

local M = {}

function M:apply(input, bundle, web)
    missioner.add_mission("pts_run", {
        component = "ato",
        session_id = input.session_id,
    }, 0, "policy")

    missioner.add_mission("model_prediction", {
        component = "ato",
        model_data = input.data,
    }, 0, "model_prediction")
end

return M
