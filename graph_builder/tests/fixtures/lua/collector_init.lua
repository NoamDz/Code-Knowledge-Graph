-- Collector registration file (init.lua)
local collector = {
    name = "device",
    js_files = {
        "device_utils.js.erb",
        "device_id.js.erb",
        "sensor.js.erb",
        "device_container.js.erb",
    },
    endpoint = "/api/device_id",
}

return collector
