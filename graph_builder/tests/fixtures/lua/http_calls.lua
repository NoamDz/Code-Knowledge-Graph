-- HTTP client calls to other services
local http = require "resty.http"
local cjson = require "cjson"

local _M = {}

function _M.call_python_service(data)
    local httpc = http.new()
    local res, err = httpc:request_uri("http://python-svc:8080/api/process", {
        method = "POST",
        body = cjson.encode(data),
        headers = { ["Content-Type"] = "application/json" },
    })
    if not res then
        return nil, err
    end
    return cjson.decode(res.body)
end

function _M.fetch_config()
    local httpc = http.new()
    local res, err = httpc:request_uri("http://config-svc:3000/config", {
        method = "GET",
    })
    if not res then
        return nil, err
    end
    return cjson.decode(res.body)
end

function _M.internal_fetch()
    local res = ngx.location.capture("/internal/data")
    if res.status ~= 200 then
        return nil, "failed"
    end
    return cjson.decode(res.body)
end

return _M
