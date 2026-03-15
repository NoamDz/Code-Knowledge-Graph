-- Complex OpenResty patterns: ngx.ctx, ngx.shared, pcall, dynamic require
local m = {}

local cjson = require "cjson.safe"

-- shared dict access
local rate_limiter = ngx.shared.rate_limit
local cache = ngx.shared.app_cache

function m.check_rate_limit(client_ip)
    local current = rate_limiter:incr(client_ip, 1, 0, 60)
    if current > 100 then
        ngx.ctx.rate_limited = true
        return nil, "rate limit exceeded"
    end
    return true
end

function m.get_cached(key)
    local val = cache:get(key)
    if val then
        return cjson.decode(val)
    end
    return nil
end

function m.set_cached(key, value, ttl)
    local encoded = cjson.encode(value)
    cache:set(key, encoded, ttl or 300)
end

-- pcall wrapper pattern
function m.safe_process(handler_name, ...)
    local handler = require("handlers." .. handler_name)
    local ok, result, err = pcall(handler.execute, ...)
    if not ok then
        ngx.log(ngx.ERR, "handler failed: ", result)
        ngx.ctx.last_error = result
        return nil, result
    end
    if err then
        ngx.ctx.last_error = err
        return nil, err
    end
    return result
end

-- reading from ngx.ctx set by other modules
function m.get_request_context()
    return {
        user_id = ngx.ctx.user_id,
        request_id = ngx.ctx.request_id,
        rate_limited = ngx.ctx.rate_limited,
    }
end

return m
