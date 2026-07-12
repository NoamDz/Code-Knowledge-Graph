.PHONY: help all up down restart logs build-image build-graph schema rebuild mcp clean stats spot-check check-config

CONFIG ?= config.yml

help:
	@echo "Code Knowledge Graph — make targets"
	@echo ""
	@echo "  make all           One-shot: install, Memgraph, schema, build, stats"
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

# One-shot full rebuild — the command to run on a fresh machine or after a pull.
all:
	CONFIG=$(CONFIG) bash scripts/rebuild.sh

# Fail loudly if config.yml is missing: code-graph otherwise falls back to its
# defaults (repo_root=".") and silently indexes the wrong tree.
check-config:
	@test -f $(CONFIG) || { \
	  echo "ERROR: $(CONFIG) not found. Copy config_example.yml to $(CONFIG) and set repo_root."; \
	  exit 1; }

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

schema: check-config
	code-graph -c $(CONFIG) schema

build-graph: check-config
	code-graph -c $(CONFIG) build

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
	code-graph -c $(CONFIG) validate || true

clean:
	docker compose down -v
