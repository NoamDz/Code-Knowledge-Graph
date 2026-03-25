local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    local feature_enabled = bundle:get("features.fraud_detection", false)
    local session_data = web.store:get("session:123")
    local user_data = web.store:hget("users", "user_123")
end

function M:assess(bundle, store, assessor_context)
    local config_value = bundle:get("config.threshold", 0.5)
    local device_data = store:hget("devices", "device_123")
    store:set("assessment:done", "true")
end

return M
