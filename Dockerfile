FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY graph_builder ./graph_builder
COPY mcp_server ./mcp_server
COPY watcher ./watcher

RUN pip install --no-cache-dir -e .

ENV MEMGRAPH_URI=bolt://memgraph:7687 \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "mcp_server.server"]
