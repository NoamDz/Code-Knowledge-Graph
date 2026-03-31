-- Child module that inherits via metatable from a base handler
local base_handler = require("common.base.lua.handler")

local _M = {}
local mt = { __index = base_handler }

function _M.new()
    local self = setmetatable({}, mt)
    return self
end

function _M:process(request)
    local result = self:validate(request)
    return result
end

return setmetatable(_M, { __index = base_handler })
