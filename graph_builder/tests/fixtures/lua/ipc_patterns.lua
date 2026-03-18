local http = require "resty.http"
local cjson = require "cjson"
local redis_helper = require "lib.lua.redis_helper"

local _M = {}

function _M.send_mission(mission_type, data)
    local mission_file = "/tmp/pinpoint_missions/" .. mission_type .. ".json"
    local file = io.open(mission_file, "w")
    file:write(cjson.encode(data))
    file:close()
end

function _M.publish_event(channel, event_data)
    local redis = redis_helper.get_connection()
    redis:publish(channel, cjson.encode(event_data))
end

function _M.call_model(data)
    local httpc = http.new()
    httpc:connect("unix:/tmp/model_prediction.sock")
    local res = httpc:request({
        path = "/predict",
        method = "POST",
        body = cjson.encode(data)
    })
    return cjson.decode(res.body)
end

return _M
