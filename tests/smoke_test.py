from mcp_server.query_engine import QueryEngine
from mcp_server.tools import composites, search, snippets

eng = QueryEngine("bolt://localhost:7687")

# read primitives
print(search.find_symbol(eng, "get_current"))
print(snippets.get_file_outline(eng, "src/ato/structured_policy/helpers.lua"))

# composites
print(composites.locate(eng, "session_info", limit=5))
print(composites.find_impact(eng, "session_info"))
print(composites.explain_flow(eng, "policy"))
print(composites.onboard_to(eng, "src/core/generator/generator.rb"))

# escape hatches
print(composites.locate(eng, "jwt token", limit=5, escape_hatch=True))