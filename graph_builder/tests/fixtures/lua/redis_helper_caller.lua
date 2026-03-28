-- Test fixture for redis abstraction resolution
-- Simulates a module that uses store methods (wrapping redis_helper)

local store = require "lib.lua.store"
local json = require "cjson"

local _M = {}

function _M.get_user_flags(user_id)
    local key = "user:flags:" .. user_id
    local data = store.get(key)
    if data then
        return json.decode(data)
    end
    return nil
end

function _M.set_user_flags(user_id, flags)
    local key = "user:flags:" .. user_id
    store.set(key, json.encode(flags), 3600)
end

function _M.check_exists(user_id)
    return store.exists("user:" .. user_id)
end

function _M.update_hash(user_id, field, value)
    store.hset("user:profile:" .. user_id, field, value)
end

function _M.collect_actions(user_id, actions)
    local vector = store.collect_vector("user_actions:" .. user_id, 86400, 1000)
    for _, action in ipairs(actions) do
        vector:set(action)
    end
end

return _M
