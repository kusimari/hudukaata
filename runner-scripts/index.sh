#!/usr/bin/env bash
# Run the hudukaata indexer inside the nix-managed environment.
# Usage: ./index.sh [path/to/hudukaata.conf]
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
CAPTION=$(cfg caption_model blip2)
LOG=$(cfg log_level INFO)
FOLDER=$(cfg folder "")
CHECKPOINT=$(cfg checkpoint_interval "")
CLUSTER_THRESHOLD=$(cfg cluster_threshold "")

if [ -z "$MEDIA" ] || [ -z "$STORE" ]; then
  echo "ERROR: 'media' and 'store' are required in $CONF" >&2
  exit 1
fi

# Map caption_model name to the indexer registry key used by `indexer index`.
case "$CAPTION" in
  blip2)       INDEXER_KEY="blip2_sentok_exif_chroma" ;;
  blip2_faces) INDEXER_KEY="blip2_sentok_exif_insightface_chroma" ;;
  *)
    echo "ERROR: unknown caption_model '$CAPTION' — supported values: blip2, blip2_faces" >&2
    exit 1
    ;;
esac

echo "==> Indexing media"
echo "    media  : $MEDIA"
echo "    store  : $STORE"
echo "    model  : $CAPTION  ($INDEXER_KEY)"
[ -n "$FOLDER" ] && echo "    folder : $FOLDER"
echo ""

# Build a JSON config file for `indexer index`.  Use Python for correct
# JSON encoding so that paths with special characters are handled safely.
TMP_JSON=$(mktemp /tmp/hudukaata-indexer-XXXXXX.json)
trap 'rm -f "$TMP_JSON"' EXIT

export _IDX_MEDIA="$MEDIA"
export _IDX_STORE="$STORE"
export _IDX_INDEXER_KEY="$INDEXER_KEY"
export _IDX_LOG="$LOG"
export _IDX_FOLDER="$FOLDER"
export _IDX_CHECKPOINT="$CHECKPOINT"
export _IDX_CLUSTER_THRESHOLD="$CLUSTER_THRESHOLD"
export TMP_JSON

python3 - <<'PYEOF'
import json, os

folder = os.environ.get("_IDX_FOLDER") or None
checkpoint_raw = os.environ.get("_IDX_CHECKPOINT", "")
cluster_threshold_raw = os.environ.get("_IDX_CLUSTER_THRESHOLD", "")
config = {
    "indexer": os.environ["_IDX_INDEXER_KEY"],
    "media_uri": os.environ["_IDX_MEDIA"],
    "store_uri": os.environ["_IDX_STORE"],
    "folder": folder,
    "checkpoint_interval": int(checkpoint_raw) if checkpoint_raw else 0,
    "log_level": os.environ["_IDX_LOG"],
}
if cluster_threshold_raw:
    config["cluster_threshold"] = float(cluster_threshold_raw)
with open(os.environ["TMP_JSON"], "w") as f:
    json.dump(config, f, indent=2)
PYEOF

nix develop "$REPO#indexer" --command bash -c '
  cd "$REPO/indexer"
  indexer index "$TMP_JSON"
'
