-- Test fixture for local alias detection
local format = string.format
local gsub, match = string.gsub, string.match
local encode, decode = cjson.encode, cjson.decode
local insert = table.insert
local floor = math.floor
local my_func = some_module.do_thing

local M = {}

function M:apply()
    format("hello %s", "world")
    gsub("hello", "h", "j")
    match("hello", "h")
    encode({key = "value"})
    decode('{"key": "value"}')
    insert({}, 1)
    floor(3.14)
    my_func()
end

return M
