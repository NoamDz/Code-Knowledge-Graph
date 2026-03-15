-- Standard _M pattern (canonical OpenResty)
local _M = {}

local redis = require "resty.redis"
local cjson = require "cjson"

function _M.validate_token(token)
    local red = redis:new()
    local ok, err = red:get("token:" .. token)
    if not ok then
        return nil, err
    end
    return cjson.decode(ok)
end

function _M.refresh_session(session_id, ttl)
    local red = redis:new()
    return red:set("session:" .. session_id, "active", "EX", ttl)
end

local function _check_expiry(token_data)
    return token_data.exp > ngx.time()
end

return _M
