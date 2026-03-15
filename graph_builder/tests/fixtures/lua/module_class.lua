-- Metatable class pattern
local Connection = {}
Connection.__index = Connection

local socket = require "resty.socket"

function Connection.new(host, port)
    local self = setmetatable({}, Connection)
    self.host = host
    self.port = port
    self.sock = nil
    return self
end

function Connection:connect()
    self.sock = socket.tcp()
    local ok, err = self.sock:connect(self.host, self.port)
    if not ok then
        return nil, err
    end
    ngx.ctx.active_connections = (ngx.ctx.active_connections or 0) + 1
    return true
end

function Connection:send(data)
    if not self.sock then
        return nil, "not connected"
    end
    return self.sock:send(data)
end

function Connection:close()
    if self.sock then
        self.sock:close()
        ngx.ctx.active_connections = (ngx.ctx.active_connections or 0) - 1
    end
end

return Connection
