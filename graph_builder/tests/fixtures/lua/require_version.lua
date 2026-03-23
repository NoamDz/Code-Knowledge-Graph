local require_version = require("loader.lua").require_version

local base = require_version("common.base.lua.handler")
local helpers = require_version("ato.helpers")
local context = require("lib.lua.context")
local store = require_version("lib.lua.store")

local M = base:new()

function M:apply(input, bundle, web)
    local device_id = context.get("device_id")
    local config = bundle:get("features.enabled", false)
    local data = store:get("user:123")
    helpers.do_thing(data)
end

return M
