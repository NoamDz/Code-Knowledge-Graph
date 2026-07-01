local require_version = require("loader.lua").require_version
local format = string.format

local M = {}

local collectors = { "device", "user_flow", "ipp" }

for _, name in ipairs(collectors) do
  local collector = require_version(format("ato.collectors.%s", name))
  M[collector.id] = collector
end

return M
