local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.actor")

local M = base:new()

function M:act(bundle, store_object, session_id, old_assess_vector, new_assess_vector)
    -- act() is always overridden, so this should resolve to same file
    local data = store_object:hget("users", "user_123")
    return {status = "ok"}
end

return M
