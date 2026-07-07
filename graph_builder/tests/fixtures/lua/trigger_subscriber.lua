local require_version = require("loader.lua").require_version
local triggers = require_version("core.triggers")

local M = {}

-- Auto-loaded!
function M.init()
  triggers.bind("new_policy_result", function() end)
end

return M
