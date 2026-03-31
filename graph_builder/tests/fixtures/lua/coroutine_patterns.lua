local _M = {}

function _M.async_handler(callback)
    local co = coroutine.create(callback)
    local ok, result = coroutine.resume(co, "init_data")
    return ok, result
end

function _M.yielding_worker()
    local data = coroutine.yield()
    -- process data
    coroutine.yield(data)
end

function _M.wrapped_coroutine(func)
    local wrapped = coroutine.wrap(func)
    local result = wrapped()
    return result
end

function _M.check_running()
    local co = coroutine.running()
    if co then
        return true
    end
    return false
end

return _M
