local http_handler = require("lib.lua.http_handler")

local function call_model_prediction(data, headers)
    local response, err = http_handler.post(
        "/predict",
        nil,
        "unix:/var/run/model_prediction.sock",
        headers,
        data
    )
    return response
end

local function get_health(headers)
    local response, err = http_handler.get(
        "/health",
        nil,
        "unix:/var/run/model_prediction.sock",
        headers
    )
    return response
end

local function send_custom(method, url, data)
    local response, err = http_handler.send_request(
        method,
        url,
        nil,
        nil,
        nil,
        data
    )
    return response
end
