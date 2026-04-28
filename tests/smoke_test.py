from mcp_server.query_engine import QueryEngine
from mcp_server.tools import composites, search, snippets

eng = QueryEngine("bolt://localhost:7687")

# read primitives
print(search.find_symbol(eng, "your_known_function_name"))
print(snippets.get_file_outline(eng, "relative/path/to/file.lua"))

# composites
print(composites.locate(eng, "endpoint that handles login", limit=5))
print(composites.find_impact(eng, "your_known_function_name"))
print(composites.explain_flow(eng, "/api/some/endpoint"))
print(composites.onboard_to(eng, "services/auth"))

# escape hatches
print(composites.locate(eng, "auth token issuer", limit=5, escape_hatch=True))