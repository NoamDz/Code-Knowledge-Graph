-- Metatable inheritance pattern test fixture
-- Tests detection of setmetatable-based OOP inheritance

local base_model = require("ato.models.base_model")
local validator = require("ato.utils.validator")

-- Child table with metatable inheritance from a required module
local global_device = {}
global_device.__index = global_device
setmetatable(global_device, {__index = base_model})

function global_device.new(attrs)
    local self = setmetatable({}, global_device)
    self.attrs = attrs
    return self
end

function global_device:validate()
    return validator.check(self.attrs)
end

function global_device:save()
    -- Inherited from base_model via metatable
    return self:persist()
end

-- Second child inheriting from the same parent
local session_device = {}
session_device.__index = session_device
setmetatable(session_device, {__index = base_model})

function session_device.new(session_id)
    local self = setmetatable({}, session_device)
    self.session_id = session_id
    return self
end

function session_device:get_session()
    return self.session_id
end

-- Direct metatable pattern (parent used directly, not via table constructor)
local special_device = {}
special_device.__index = special_device
setmetatable(special_device, base_model)

-- Self-referential pattern — should NOT be detected as inheritance
local standalone = {}
standalone.__index = standalone
setmetatable(standalone, {__index = standalone})

return {
    GlobalDevice = global_device,
    SessionDevice = session_device,
    SpecialDevice = special_device,
}
