#!/usr/bin/env bash
set -euo pipefail

# Publishes the surface tile pyramids to object storage. Separate from
# deploy.sh: tiles change only when a pyramid is rebuilt, and they are too many
# files for the static project.
#
# One-time setup, outside this script: an R2 bucket served on a public domain,
# a CORS rule on it that allows GET from any origin (the SDK embeds the map on
# other sites), and an rclone remote for it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TILES_DIR="$REPO_ROOT/../space-map-tiles"

: "${TILES_REMOTE:?must name the rclone remote and bucket, e.g. r2:space-map-tiles}"
: "${TILES_URL:?must name the public origin of the bucket, e.g. https://tiles.example.org}"

[[ -d "$TILES_DIR/v1/tiles" ]] \
  || { echo "ERROR: no tiles at $TILES_DIR/v1/tiles — run space-map-ingest --targets tiles" >&2; exit 1; }

# Tile URLs carry a per-pyramid ?v= token, so a tile is safe to cache forever.
# --checksum compares content, not mtimes: a rebuild that reproduces a tile
# byte for byte uploads nothing. --fast-list keeps the listing to a few
# billable requests. A pyramid still being built stays local, with the saves
# its build resumes from.
rclone sync "$TILES_DIR/v1" "$TILES_REMOTE/v1" \
  --checksum --fast-list --transfers 32 --checkers 32 \
  --exclude "*.building/**" --exclude ".build/**" \
  --header-upload "Cache-Control: public, max-age=31536000, immutable" \
  --stats 30s --stats-one-line

# Verify one tile per pyramid end to end, through the public origin. A monthly
# map holds a pyramid per month, one folder down.
for pyramid in "$TILES_DIR"/v1/tiles/*/; do
  [[ "$pyramid" == *.building/ ]] && continue
  tile=""
  for first in "$pyramid"0/0/0.webp "$pyramid"*/0/0/0.webp; do
    [[ -f "$first" ]] && { tile="${first#"$TILES_DIR"/}"; break; }
  done
  [[ -n "$tile" ]] || { echo "ERROR: no first tile in $pyramid" >&2; exit 1; }
  curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$TILES_URL/$tile?deploy-check=$(date +%s)" \
    | cmp -s - "$TILES_DIR/$tile" \
    || { echo "ERROR: $tile unreachable or differs from the local build" >&2; exit 1; }
  echo "tiles deploy verified: /$tile"
done
