local _M = {}

local handlers = {
    event_a = require("events.event_type_a"),
    event_b = require("events.event_type_b"),
    event_c = require("events.event_type_c"),
}

function _M.dispatch(event_type, data)
    local handler = handlers[event_type]
    if handler then
        return handler:handle(data)
    end
    return nil, "unknown event type"
end

function _M.route_request(method)
    local routes = {
        GET = require("handlers.get_handler"),
        POST = require("handlers.post_handler"),
    }
    local route = routes[method]
    if route then
        return route:process()
    end
end

return _M
