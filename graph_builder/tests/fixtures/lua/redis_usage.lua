-- Redis operations: get, set, hget, publish
local redis = require "resty.redis"
local cjson = require "cjson"

local _M = {}

function _M.get_user_flag(user_id)
    local red = redis:new()
    red:connect("127.0.0.1", 6379)
    local val = red:get("user:flags:" .. user_id)
    red:set_keepalive(10000, 100)
    return val
end

function _M.set_processing_flag(job_id, status)
    local red = redis:new()
    red:connect("127.0.0.1", 6379)
    red:set("job:status:" .. job_id, status)
    red:publish("job:events", cjson.encode({id = job_id, status = status}))
    red:set_keepalive(10000, 100)
end

function _M.get_cached_config(key)
    local red = redis:new()
    red:connect("127.0.0.1", 6379)
    local val = red:hget("app:config", key)
    red:set_keepalive(10000, 100)
    return val
end

return _M
