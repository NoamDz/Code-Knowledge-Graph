local require_version = require("loader.lua").require_version
local base = require_version("common.base.lua.handler")

local M = base:new()

function M:apply(input, bundle, web)
    -- Store vector chain: store.assess_vector:get()
    local scores = store.assess_vector:get("user_scores")
    store.assess_vector:set("user_scores", {1, 2, 3})
    store.collect_vector:setall("collected", {4, 5, 6})

    -- Deep chain: web.store.assess_vector:get()
    local deep_scores = web.store.assess_vector:get("deep_scores")

    -- Plain store field (not a vector, should NOT resolve to store_vector)
    local sid = store.session_id
end

function M:act(bundle, store_object, session_id, old_assess_vector, new_assess_vector)
    -- store_object is a Store instance
    local data = store_object:hget("users", "user_123")
    store_object:set("processed", "true")

    -- store_object vector chain
    local av = store_object.assess_vector:get("scores")
end

return M
