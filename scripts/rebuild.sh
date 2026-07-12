#!/usr/bin/env bash
#
# Full end-to-end rebuild of the code knowledge graph.
#
#   install (editable)  ->  start Memgraph  ->  wait healthy
#     ->  schema (indexes)  ->  build (wipe + rebuild)  ->  coverage report
#
# Safe to re-run: `build` wipes the graph before it writes, so every run
# produces the graph from scratch. Usage:
#
#   ./scripts/rebuild.sh                 # uses config.yml
#   CONFIG=other.yml ./scripts/rebuild.sh
#   make rebuild                         # same thing via the Makefile
#
set -euo pipefail

# Run from the repo root no matter where this is invoked from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONFIG="${CONFIG:-config.yml}"
CONTAINER="code-graph-memgraph"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# 1. Config must exist. If it doesn't, `code-graph` silently falls back to
#    its defaults (repo_root=".") and indexes the wrong tree with no error.
if [ ! -f "$CONFIG" ]; then
  die "$CONFIG not found.
       Copy config_example.yml to $CONFIG and set repo_root to your target codebase:
         cp config_example.yml $CONFIG"
fi

# 2. Docker must be up (Memgraph runs in it).
docker info >/dev/null 2>&1 \
  || die "Docker is not running. Start Docker Desktop and retry."

# 3. Install the package (editable). Fast when already satisfied; also picks
#    up dependency / entry-point changes after a git pull.
log "Installing code-graph (editable)"
python3 -m pip install -e . --quiet

# 4. Clean restart of Memgraph (preserves the volume; `build` wipes the data).
log "Restarting Memgraph"
docker compose down
docker compose up -d memgraph

# 5. Wait for the container's healthcheck to pass before talking Bolt to it.
log "Waiting for Memgraph to become healthy"
ready=false
for _ in $(seq 1 60); do
  status="$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo starting)"
  if [ "$status" = "healthy" ]; then ready=true; break; fi
  sleep 2
done
[ "$ready" = true ] || die "Memgraph did not become healthy within 120s. Check: docker compose logs memgraph"

# 6. Indexes, then the build itself (scan -> parse -> resolve -> wipe -> ingest).
log "Creating schema (indexes)"
code-graph -c "$CONFIG" schema

log "Building graph"
code-graph -c "$CONFIG" build

# 7. Coverage report. Informational — never fail the run on it.
log "Coverage report"
code-graph -c "$CONFIG" validate || true

log "Done. Memgraph Lab: http://localhost:3000  |  Bolt: bolt://localhost:7687"
