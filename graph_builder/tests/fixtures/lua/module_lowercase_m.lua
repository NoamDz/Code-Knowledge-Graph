-- Module with lowercase m table, ngx.ctx writes, pcall
local utils = require "lib.utils"
local cjson = require "cjson"

local m = {}

function m.handle_request(params)
    ngx.ctx.request_data = params
    local result = utils.validate(params)
    return result
end

function m.process(data)
    local ok, err = pcall(utils.heavy_work, data)
    if not ok then
        ngx.log(ngx.ERR, "process failed: ", err)
    end
    return ok
end

function m.validate(input)
    return utils.check(input)
end

local function internal_helper(x)
    return x + 1
end

return m
