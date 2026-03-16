-- Context module abstraction pattern (wraps ngx.ctx)
local context = require "core.context"
local table_utils = require "lib.lua.table_utils"

local CTX = "triggers"

local M = {}

function M.add_trigger(trigger)
    local ctx = context.get(CTX)
    local existing_context = ctx.tree or {}
    ctx.tree = table_utils.update_table(trigger.active_tree or {}, existing_context)
    ctx.pending_triggers = ctx.pending_triggers or {}
end

function M.get_config()
    local ctx = context.get("global_config")
    if ctx.component == nil then
        ctx.component = "common"
    end
    if ctx.is_deferrer == nil then
        ctx.is_deferrer = false
    end
    return ctx
end

function M.set_deferrer()
    local ctx = context.get("global_config")
    ctx.is_deferrer = true
end

return M
