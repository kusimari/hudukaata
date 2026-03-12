#!/usr/bin/env bash
# Start the hudukaata search API inside the nix-managed environment.
# Usage: ./search.sh [path/to/hudukaata.conf]
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

MEDIA=$(cfg media)
STORE=$(cfg store)
PORT=$(cfg search_port 8080)
LOG=$(cfg log_level INFO)

if [ -z "$MEDIA" ] || [ -z "$STORE" ]; then
  echo "ERROR: 'media' and 'store' are required in $CONF" >&2
  exit 1
fi

echo "==> Starting search API"
echo "    store : $STORE"
echo "    media : $MEDIA"
echo "    url   : http://0.0.0.0:$PORT"
echo ""

nix develop "$REPO#search" --command bash -c "
  SEARCH_STORE='$STORE' \
  SEARCH_MEDIA='$MEDIA' \
  SEARCH_PORT='$PORT' \
  SEARCH_LOG_LEVEL='$LOG' \
  python -m search
"
