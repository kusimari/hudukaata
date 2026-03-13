#!/usr/bin/env bash
# End-to-end integration test for hudukaata — two-phase incremental index.
#
# Phase 1 — initial index
#   1. Copy blue_sky.png + green_field.png into MEDIA_DIR/batch1/.
#   2. Generate a synthetic MEDIA_DIR/batch2/red_sunset.png via PIL.
#   3. Run the indexer scoped to batch1 (2 files).
#   4. Start search API + webapp; verify HTML and >= 1 search result.
#   5. Shut down services.
#
# Phase 2 — incremental update
#   6. Run the indexer scoped to batch2 (1 new file); index is updated, not rebuilt.
#   7. Start search API + webapp; verify HTML, >= 3 search results, and that
#      a batch2 path appears in the results (confirms the new file was indexed).
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
SEARCH_PID=""
WEBAPP_PID=""

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
  echo ""
  echo "==> Cleanup"
  local pids
  pids=$(jobs -p 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r pkill -P 2>/dev/null || true
    echo "$pids" | xargs -r kill 2>/dev/null || true
  fi
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
# Helpers
# ---------------------------------------------------------------------------

wait_for_http() {
  local url="$1" label="$2" pid_var="$3" timeout=300
  local elapsed=0
  echo -n "Waiting for $label"
  while [ "$elapsed" -lt "$timeout" ]; do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo " ready (${elapsed}s)"
      return 0
    fi
    local pid
    pid="${!pid_var}"
    if ! kill -0 "$pid" 2>/dev/null; then
      echo " FAILED -- process exited after ${elapsed}s"
      return 1
    fi
    echo -n "."
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo " TIMED OUT after ${timeout}s"
  return 1
}

stop_services() {
  echo "==> Stopping search API and webapp"
  [ -n "$SEARCH_PID" ] && kill "$SEARCH_PID" 2>/dev/null || true
  [ -n "$WEBAPP_PID" ]  && kill "$WEBAPP_PID"  2>/dev/null || true
  if command -v lsof &>/dev/null; then
    lsof -ti ":$SEARCH_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    lsof -ti ":$WEBAPP_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  fi
  SEARCH_PID=""
  WEBAPP_PID=""
  echo ""
}

write_conf() {
  local conf_path="$1" folder="${2:-}"
  cat > "$conf_path" <<EOF
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
  if [ -n "$folder" ]; then
    echo "folder          = $folder" >> "$conf_path"
  fi
}

start_services() {
  local conf="$1"
  "$RUNNERS/search.sh" "$conf" >/tmp/hudukaata-search.log 2>&1 &
  SEARCH_PID=$!
  wait_for_http "http://localhost:$SEARCH_PORT/readyz" "search API" SEARCH_PID || {
    echo "Search API log:"
    cat /tmp/hudukaata-search.log || true
    exit 1
  }

  "$RUNNERS/webapp.sh" "$conf" >/tmp/hudukaata-webapp.log 2>&1 &
  WEBAPP_PID=$!
  wait_for_http "http://localhost:$WEBAPP_PORT" "webapp" WEBAPP_PID || {
    echo "Webapp log:"
    cat /tmp/hudukaata-webapp.log || true
    exit 1
  }
  echo ""
}

assert_html() {
  local phase="$1"
  echo "==> [$phase] Webapp HTML: GET http://localhost:$WEBAPP_PORT"
  local html
  html=$(curl -sf "http://localhost:$WEBAPP_PORT")
  if ! echo "$html" | grep -qi "<html"; then
    echo "FAIL [$phase]: webapp response does not look like HTML"
    echo "$html"
    exit 1
  fi
  echo "Got HTML OK"
  echo ""
}

assert_search() {
  local phase="$1" query="$2" min_results="$3" path_fragment="${4:-}"
  echo "==> [$phase] Search: GET http://localhost:$WEBAPP_PORT/api/search?q=$query"
  local response count
  response=$(curl -sf "http://localhost:$WEBAPP_PORT/api/search?q=$query&n=5")
  echo "Response: $response"
  count=$(echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(len(data))
for r in data:
    print(f'  path={r[\"relative_path\"]}', file=sys.stderr)
")
  echo "Result count: $count"
  if [ "$count" -lt "$min_results" ]; then
    echo "FAIL [$phase]: expected >= $min_results results, got $count"
    exit 1
  fi
  if [ -n "$path_fragment" ]; then
    if ! echo "$response" | grep -q "$path_fragment"; then
      echo "FAIL [$phase]: expected a result containing '$path_fragment'"
      exit 1
    fi
    echo "Found expected path fragment '$path_fragment' OK"
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
echo "==> hudukaata end-to-end test (two-phase incremental index)"
echo ""

WORK_DIR=$(mktemp -d /tmp/hudukaata-e2e-XXXXXX)
MEDIA_DIR="$WORK_DIR/media"
STORE_DIR="$WORK_DIR/store"

mkdir -p "$MEDIA_DIR/batch1" "$MEDIA_DIR/batch2" "$STORE_DIR"

# Phase 1 media: the two bundled sample images.
cp "$SAMPLES_DIR/blue_sky.png"    "$MEDIA_DIR/batch1/"
cp "$SAMPLES_DIR/green_field.png" "$MEDIA_DIR/batch1/"

# Phase 2 media: generate a synthetic orange-red image inside the indexer nix
# shell so PIL is guaranteed to be available.  No binary asset is committed.
echo "==> Generating batch2/red_sunset.png via PIL..."
nix develop "$REPO#indexer" --command python3 -c "
from PIL import Image
img = Image.new('RGB', (64, 64), color=(200, 80, 30))
img.save('$MEDIA_DIR/batch2/red_sunset.png')
"

echo "Media layout:"
find "$MEDIA_DIR" -type f | sort | sed 's/^/  /'
echo ""

# ---------------------------------------------------------------------------
# Phase 1 -- initial index of batch1 (2 files)
# ---------------------------------------------------------------------------
echo "==> [Phase 1] Indexing batch1 (2 files)..."
CONF1="$WORK_DIR/phase1.conf"
write_conf "$CONF1" "batch1"
"$RUNNERS/index.sh" "$CONF1"
echo ""

echo "==> [Phase 1] Starting services..."
start_services "$CONF1"
assert_html "Phase 1"
assert_search "Phase 1" "blue+sky" 1 ""
stop_services

# ---------------------------------------------------------------------------
# Phase 2 -- incremental update with batch2 (1 new file)
# ---------------------------------------------------------------------------
echo "==> [Phase 2] Updating index with batch2 (1 new file)..."
CONF2="$WORK_DIR/phase2.conf"
write_conf "$CONF2" "batch2"
"$RUNNERS/index.sh" "$CONF2"
echo ""

echo "==> [Phase 2] Starting services..."
start_services "$CONF2"
assert_html "Phase 2"
# After the incremental update the index contains all 3 files (batch1 x2 +
# batch2 x1).  Verify the count and that a batch2 path is present.
assert_search "Phase 2" "blue+sky" 3 "batch2"

echo "==> All assertions passed (both phases)."
