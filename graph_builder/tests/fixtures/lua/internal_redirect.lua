-- Internal routing patterns: ngx.exec, ngx.location.capture
local cjson = require "cjson"

local _M = {}

function _M.process_request()
    -- Validate first
    local user_id = ngx.ctx.user_id
    if not user_id then
        return ngx.exit(401)
    end

    -- Reroute to internal handler
    ngx.exec("/internal/process")
end

function _M.aggregate_data()
    -- Subrequest to internal API
    local res = ngx.location.capture("/internal/fetch_data")
    if res.status ~= 200 then
        return nil, "fetch failed"
    end

    local data = cjson.decode(res.body)
    return data
end

function _M.parallel_fetch()
    -- Parallel subrequests
    local res1, res2 = ngx.location.capture_multi({
        {"/internal/service_a"},
        {"/internal/service_b"},
    })
    return res1.body, res2.body
end

return _M
