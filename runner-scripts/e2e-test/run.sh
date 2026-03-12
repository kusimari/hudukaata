#!/usr/bin/env bash
# End-to-end integration test for hudukaata.
#
# What it does:
#   1. Creates a temporary media dir and copies the sample images into it.
#   2. Creates a temporary store dir for the index.
#   3. Writes a test config pointing at those dirs.
#   4. Runs the indexer.
#   5. Starts the search API in the background and waits for it to be ready.
#   6. Starts the webapp in the background and waits for it to be ready.
#   7. Curls the search API with a query that matches the sample images.
#   8. Verifies at least one result is returned.
#   9. Verifies the webapp responds.
#  10. Cleans up (kills background processes, removes temp dirs).
#
# Usage: ./run.sh
# Requires: nix (with flakes enabled)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNERS="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO="$(cd "$RUNNERS/.." && pwd)"
SAMPLES_DIR="$SCRIPT_DIR/samples"

# Use non-default ports to avoid conflicts with a running instance.
SEARCH_PORT=18080
WEBAPP_PORT=15173

WORK_DIR=""

cleanup() {
  echo ""
  echo "==> Cleanup"
  # Kill all background jobs from this shell and their children.
  local pids
  pids=$(jobs -p 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r pkill -P 2>/dev/null || true
    echo "$pids" | xargs -r kill 2>/dev/null || true
  fi
  # Force-kill anything still holding our ports.
  if command -v lsof &>/dev/null; then
    lsof -ti ":$SEARCH_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    lsof -ti ":$WEBAPP_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  fi
  if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
    rm -rf "$WORK_DIR"
    echo "Removed $WORK_DIR"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
echo "==> hudukaata end-to-end test"
echo ""

WORK_DIR=$(mktemp -d /tmp/hudukaata-e2e-XXXXXX)
MEDIA_DIR="$WORK_DIR/media"
STORE_DIR="$WORK_DIR/store"
CONF="$WORK_DIR/test.conf"

mkdir -p "$MEDIA_DIR" "$STORE_DIR"

# Copy sample images to the temp media dir.
cp "$SAMPLES_DIR"/*.png "$MEDIA_DIR/"
echo "Media files:"
ls "$MEDIA_DIR" | sed 's/^/  /'
echo ""

cat > "$CONF" <<EOF
media           = file://$MEDIA_DIR
store           = file://$STORE_DIR
caption_model   = blip2
vectorizer      = sentence-transformer
vector_store    = chroma
log_level       = INFO
search_port     = $SEARCH_PORT
search_api_host = http://localhost
webapp_port     = $WEBAPP_PORT
EOF

# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
echo "==> Indexing sample media (this downloads models on first run)..."
"$RUNNERS/index.sh" "$CONF"
echo ""

# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------
echo "==> Starting search API on port $SEARCH_PORT..."
"$RUNNERS/search.sh" "$CONF" >/tmp/hudukaata-search.log 2>&1 &

echo -n "Waiting for search API"
for i in $(seq 60); do
  if curl -sf "http://localhost:$SEARCH_PORT/readyz" >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo " TIMED OUT"
    echo "Search API log:"
    cat /tmp/hudukaata-search.log || true
    exit 1
  fi
  echo -n "."
  sleep 1
done
echo ""

# ---------------------------------------------------------------------------
# Webapp
# ---------------------------------------------------------------------------
echo "==> Starting webapp on port $WEBAPP_PORT..."
"$RUNNERS/webapp.sh" "$CONF" >/tmp/hudukaata-webapp.log 2>&1 &

echo -n "Waiting for webapp"
for i in $(seq 60); do
  if curl -sf "http://localhost:$WEBAPP_PORT" >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo " TIMED OUT"
    echo "Webapp log:"
    cat /tmp/hudukaata-webapp.log || true
    exit 1
  fi
  echo -n "."
  sleep 1
done
echo ""

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------
echo "==> Search API: query 'blue sky'"
SEARCH_RESPONSE=$(curl -sf "http://localhost:$SEARCH_PORT/search?q=blue+sky&n=5")
echo "Response: $SEARCH_RESPONSE"

RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(len(data))
for r in data:
    print(f'  path={r[\"relative_path\"]}', file=sys.stderr)
")
echo "Result count: $RESULT_COUNT"

if [ "$RESULT_COUNT" -eq 0 ]; then
  echo "FAIL: expected at least 1 search result, got 0"
  exit 1
fi

echo ""
echo "==> Webapp: GET http://localhost:$WEBAPP_PORT"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$WEBAPP_PORT")
if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: webapp returned HTTP $HTTP_STATUS, expected 200"
  exit 1
fi
echo "HTTP $HTTP_STATUS OK"

echo ""
echo "==> All assertions passed."
