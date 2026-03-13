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
VECTORIZER=$(cfg vectorizer sentence-transformer)
VSTORE=$(cfg vector_store chroma)
LOG=$(cfg log_level INFO)
FOLDER=$(cfg folder "")
CHECKPOINT=$(cfg checkpoint_interval "")

if [ -z "$MEDIA" ] || [ -z "$STORE" ]; then
  echo "ERROR: 'media' and 'store' are required in $CONF" >&2
  exit 1
fi

# Build optional extra flags.
EXTRA=""
[ -n "$FOLDER" ]     && EXTRA="$EXTRA --folder '$FOLDER'"
[ -n "$CHECKPOINT" ] && EXTRA="$EXTRA --checkpoint-interval '$CHECKPOINT'"

echo "==> Indexing media"
echo "    media  : $MEDIA"
echo "    store  : $STORE"
echo "    model  : $CAPTION"
[ -n "$FOLDER" ] && echo "    folder : $FOLDER"
echo ""

nix develop "$REPO#indexer" --command bash -c "
  cd '$REPO/indexer'
  indexer index \
    --media '$MEDIA' \
    --store '$STORE' \
    --caption-model '$CAPTION' \
    --vectorizer '$VECTORIZER' \
    --vector-store '$VSTORE' \
    --log-level '$LOG' \
    $EXTRA
"
