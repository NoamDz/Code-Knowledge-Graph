local require_version = require("loader.lua").require_version
local Store = require_version("common.base.lua.store")

local M = {}

function M.produce(store)
  store.assess_vector:set("session_info", { ok = true })
  store:set_dirty_flag("device_id", "ato")
end

function M.consume(store)
  local data = store.assess_vector:get("session_info")
  return data
end

return M
