#!/usr/bin/env bash
# Start the hudukaata webapp inside the nix-managed environment.
# Usage: ./webapp.sh [path/to/hudukaata.conf]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="${1:-$SCRIPT_DIR/hudukaata.conf}"

if [ ! -f "$CONF" ]; then
  echo "ERROR: config file not found: $CONF" >&2
  echo "Copy $SCRIPT_DIR/hudukaata.conf.example to $SCRIPT_DIR/hudukaata.conf and fill in your paths." >&2
  exit 1
fi

cfg() {
  local key="$1" default="${2:-}"
  local val
  val=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$CONF" \
        | head -1 \
        | sed 's/^[^=]*=[[:space:]]*//' \
        | sed 's/[[:space:]]*#.*//' \
        | xargs)
  echo "${val:-$default}"
}

API_HOST=$(cfg search_api_host http://localhost)
API_PORT=$(cfg search_port 8080)
WEBAPP_PORT=$(cfg webapp_port 5173)

echo "==> Starting webapp"
echo "    search API : $API_HOST:$API_PORT"
echo "    webapp url : http://localhost:$WEBAPP_PORT"
echo ""

nix develop "$REPO#webapp" --command bash -c "
  VITE_API_URL='$API_HOST:$API_PORT' \
  npm run dev -- --host --port '$WEBAPP_PORT'
"
