local M = {}
M.__index = M
M.name = "device_id"
M.assess_key = "device_id"
M.id = "13"

function M.new() return setmetatable({}, M) end

return M
