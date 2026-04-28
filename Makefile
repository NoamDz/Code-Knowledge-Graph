.PHONY: help up down restart logs build-image build-graph schema rebuild mcp clean stats spot-check

CONFIG ?= config.yml

help:
	@echo "Code Knowledge Graph — make targets"
	@echo ""
	@echo "  make up            Start Memgraph (background)"
	@echo "  make down          Stop all services"
	@echo "  make restart       Restart Memgraph"
	@echo "  make logs          Tail Memgraph logs"
	@echo "  make build-image   Build the MCP server Docker image"
	@echo "  make schema        Create Memgraph indexes (CONFIG=$(CONFIG))"
	@echo "  make build-graph   Full graph build (CONFIG=$(CONFIG))"
	@echo "  make rebuild       Down, up, schema, build-graph"
	@echo "  make mcp           Run the MCP server locally (stdio)"
	@echo "  make stats         Print graph statistics"
	@echo "  make clean         Stop services and delete the Memgraph volume"

up:
	docker compose up -d memgraph

down:
	docker compose down

restart:
	docker compose restart memgraph

logs:
	docker compose logs -f memgraph

build-image:
	docker compose build mcp

schema:
	code-graph schema -c $(CONFIG)

build-graph:
	code-graph build -c $(CONFIG)

rebuild: down up wait-memgraph
	$(MAKE) schema
	$(MAKE) build-graph

wait-memgraph:
	@echo "Waiting for Memgraph to become healthy..."
	@for i in $$(seq 1 60); do \
		status=$$(docker inspect --format='{{.State.Health.Status}}' code-graph-memgraph 2>/dev/null || echo "starting"); \
		if [ "$$status" = "healthy" ]; then echo "Memgraph healthy"; exit 0; fi; \
		sleep 2; \
	done; \
	echo "Memgraph did not become healthy in 120s"; exit 1

mcp:
	python -m mcp_server.server

stats:
	code-graph validate -c $(CONFIG) || true

clean:
	docker compose down -v
