-- Named module table pattern (uses descriptive name)
local auth = {}

local jwt = require "resty.jwt"
local redis = require "resty.redis"

auth.DEFAULT_TTL = 3600

function auth.verify(token)
    local result = jwt:verify("secret", token)
    if not result.verified then
        ngx.log(ngx.ERR, "JWT verification failed")
        return nil, "invalid token"
    end
    ngx.ctx.user_id = result.payload.sub
    return result.payload
end

function auth.get_current_user()
    return ngx.ctx.user_id
end

function auth.logout(session_id)
    local red = redis:new()
    red:del("session:" .. session_id)
    ngx.ctx.user_id = nil
end

local function hash_token(token)
    return ngx.md5(token)
end

return auth
