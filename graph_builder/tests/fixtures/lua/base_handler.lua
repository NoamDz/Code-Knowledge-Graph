-- Base handler module at common.base.lua.handler
local _M = {}

function _M:validate(request)
    if not request then
        return nil, "missing request"
    end
    return true
end

function _M:dispatch(request)
    return self:validate(request)
end

function _M:handle_web_request(req)
    return self:dispatch(req)
end

function _M:add_handler_error(err_msg)
    -- error handling logic
end

function _M:parse_postdata(body)
    return body
end

-- Private helper (should NOT be in public methods)
local function _internal_helper()
    return true
end

return _M
