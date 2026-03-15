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
INDEX_STORE=$(cfg index_store indexer.stores.chroma_caption.ChromaCaptionIndexStore)
LOG=$(cfg log_level INFO)
FOLDER=$(cfg folder "")
CHECKPOINT=$(cfg checkpoint_interval "")

if [ -z "$MEDIA" ] || [ -z "$STORE" ]; then
  echo "ERROR: 'media' and 'store' are required in $CONF" >&2
  exit 1
fi

echo "==> Indexing media"
echo "    media  : $MEDIA"
echo "    store  : $STORE"
echo "    model  : $CAPTION"
[ -n "$FOLDER" ] && echo "    folder : $FOLDER"
echo ""

# Pass optional parameters via environment variables so that values with shell
# metacharacters are never interpolated inside a bash -c string.
export _IDX_MEDIA="$MEDIA"
export _IDX_STORE="$STORE"
export _IDX_CAPTION="$CAPTION"
export _IDX_INDEX_STORE="$INDEX_STORE"
export _IDX_LOG="$LOG"
export _IDX_FOLDER="$FOLDER"
export _IDX_CHECKPOINT="$CHECKPOINT"

nix develop "$REPO#indexer" --command bash -c '
  cd "$REPO/indexer"
  EXTRA_ARGS=()
  [ -n "$_IDX_FOLDER" ]     && EXTRA_ARGS+=(--folder "$_IDX_FOLDER")
  [ -n "$_IDX_CHECKPOINT" ] && EXTRA_ARGS+=(--checkpoint-interval "$_IDX_CHECKPOINT")
  indexer index \
    --media        "$_IDX_MEDIA" \
    --store        "$_IDX_STORE" \
    --caption-model "$_IDX_CAPTION" \
    --index-store  "$_IDX_INDEX_STORE" \
    --log-level    "$_IDX_LOG" \
    "${EXTRA_ARGS[@]}"
'
