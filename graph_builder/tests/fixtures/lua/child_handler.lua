local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    if not self:validate_input(input) then
        return self:user_error("Invalid input")
    end
    local result = self:process(input, web)
    if not result then
        self:log_error("Processing failed")
    end
    return result
end

function M:process(input, web)
    return {status = "ok"}
end

return M
