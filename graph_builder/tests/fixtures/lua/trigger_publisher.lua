local require_version = require("loader.lua").require_version
local triggers = require_version("core.triggers")

local M = {}

function M.run(bundle, store)
  triggers.defer("new_policy_result", { ok = true })
  triggers.fire(bundle, store, "update_user_profile", {})
end

return M
