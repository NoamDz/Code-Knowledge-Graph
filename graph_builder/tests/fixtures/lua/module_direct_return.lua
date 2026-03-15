-- Direct table return pattern (no module variable)
local http = require "resty.http"

local function fetch_url(url)
    local httpc = http.new()
    local res, err = httpc:request_uri(url, { method = "GET" })
    if not res then
        return nil, err
    end
    return res.body
end

local function post_json(url, body)
    local cjson = require "cjson"
    local httpc = http.new()
    local res, err = httpc:request_uri(url, {
        method = "POST",
        body = cjson.encode(body),
        headers = { ["Content-Type"] = "application/json" },
    })
    if not res then
        return nil, err
    end
    return cjson.decode(res.body)
end

return {
    fetch_url = fetch_url,
    post_json = post_json,
}
