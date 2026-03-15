#!/usr/bin/env bash
# Extract the generated nginx.conf from a running OpenResty container.
#
# Usage:
#   ./scripts/extract_nginx_conf.sh                     # auto-detect container
#   ./scripts/extract_nginx_conf.sh my-container-name   # explicit container
#
# The script tries common nginx.conf locations inside the container.
# After extraction, enable it in config.yml:
#   nginx_conf: ./extracted_nginx.conf

set -euo pipefail

OUTPUT="extracted_nginx.conf"
CONTAINER="${1:-}"

# --- Auto-detect container if not specified ---
if [ -z "$CONTAINER" ]; then
    # Look for running containers with "openresty" or "nginx" in image name
    CONTAINER=$(docker ps --format '{{.Names}}\t{{.Image}}' \
        | grep -iE 'openresty|nginx|resty' \
        | head -1 \
        | cut -f1)

    if [ -z "$CONTAINER" ]; then
        echo "ERROR: No running OpenResty/nginx container found."
        echo "Usage: $0 <container-name>"
        echo ""
        echo "Running containers:"
        docker ps --format '  {{.Names}}  ({{.Image}})'
        exit 1
    fi
    echo "Auto-detected container: $CONTAINER"
fi

# --- Common nginx.conf locations ---
CONF_PATHS=(
    "/usr/local/openresty/nginx/conf/nginx.conf"
    "/etc/nginx/nginx.conf"
    "/usr/local/nginx/conf/nginx.conf"
    "/opt/openresty/nginx/conf/nginx.conf"
    "/etc/openresty/nginx.conf"
)

echo "Searching for nginx.conf in container '$CONTAINER'..."

for path in "${CONF_PATHS[@]}"; do
    if docker exec "$CONTAINER" test -f "$path" 2>/dev/null; then
        echo "Found: $path"
        docker cp "$CONTAINER:$path" "$OUTPUT"
        echo ""
        echo "Extracted to: $OUTPUT"
        echo ""

        # Show lua_package_path if present
        LPP=$(grep -o 'lua_package_path[[:space:]]*"[^"]*"' "$OUTPUT" 2>/dev/null || true)
        if [ -n "$LPP" ]; then
            echo "Detected lua_package_path:"
            echo "  $LPP"
        fi

        # Count Lua directives
        LUA_COUNT=$(grep -cE '(access|content|rewrite|init|header_filter|body_filter|log|balancer)_by_lua' "$OUTPUT" 2>/dev/null || echo "0")
        echo "Lua phase directives found: $LUA_COUNT"
        echo ""
        echo "Next steps:"
        echo "  1. Review $OUTPUT"
        echo "  2. Add to config.yml:  nginx_conf: ./$OUTPUT"
        echo "  3. Re-run:  code-graph build -c config.yml"
        exit 0
    fi
done

# --- Fallback: try to find it anywhere ---
echo "Standard paths not found, searching..."
FOUND=$(docker exec "$CONTAINER" find / -name "nginx.conf" -type f 2>/dev/null | head -1 || true)

if [ -n "$FOUND" ]; then
    echo "Found: $FOUND"
    docker cp "$CONTAINER:$FOUND" "$OUTPUT"
    echo "Extracted to: $OUTPUT"
    exit 0
fi

echo "ERROR: Could not find nginx.conf inside container '$CONTAINER'."
echo "Try: docker exec $CONTAINER find / -name 'nginx.conf' -o -name '*.conf' | head -20"
exit 1
