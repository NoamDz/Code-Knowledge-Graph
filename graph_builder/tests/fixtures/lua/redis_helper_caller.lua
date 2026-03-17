-- Test fixture for redis abstraction resolution
-- Simulates a module that uses redis_helper methods

local redis_helper = require "lib.lua.redis_helper"
local json = require "cjson"

local _M = {}

function _M.get_user_flags(user_id)
    local key = "user:flags:" .. user_id
    local data = redis_helper:get(key)
    if data then
        return json.decode(data)
    end
    return nil
end

function _M.set_user_flags(user_id, flags)
    local key = "user:flags:" .. user_id
    redis_helper:set_json(key, flags)
    redis_helper:expire(key, 3600)
end

function _M.check_exists(user_id)
    local key = "user:" .. user_id
    return redis_helper:exists(key)
end

function _M.increment_counter(name)
    local key = "counter:" .. name
    redis_helper:incr_with_expire_once(key, 86400)
end

function _M.get_hash_data(user_id)
    local data = redis_helper:hgetall("user:profile:" .. user_id)
    local ttl = redis_helper:ttl("user:profile:" .. user_id)
    return data, ttl
end

function _M.pipeline_update(user_id, data)
    redis_helper:pipeline(function(pipe)
        pipe:hset("user:profile:" .. user_id, "name", data.name)
        pipe:hset("user:profile:" .. user_id, "email", data.email)
    end)
end

return _M
