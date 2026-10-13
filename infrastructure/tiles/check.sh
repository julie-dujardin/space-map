#!/usr/bin/env bash
set -euo pipefail

# Checks the tile host against the tile tree. The host serves the tree as it
# is (compose/), so a pyramid has no upload step: this is its whole deploy.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TILES_DIR="${TILES_DIR:-$REPO_ROOT/../space-map-tiles}"
TILES_URL="${TILES_URL:-https://tiles.spacemap.co}"

[[ -d "$TILES_DIR/v1/tiles" ]] \
  || { echo "ERROR: no tiles at $TILES_DIR/v1/tiles — run space-map-ingest --targets tiles" >&2; exit 1; }

# The cache-buster skips the edge cache, so each answer comes from the origin.
stamp=$(date +%s)

# One tile per pyramid, end to end. A monthly map holds a pyramid per month,
# one folder down.
for pyramid in "$TILES_DIR"/v1/tiles/*/; do
  [[ "$pyramid" == *.building/ ]] && continue
  tile=""
  for first in "$pyramid"0/0/0.webp "$pyramid"*/0/0/0.webp; do
    [[ -f "$first" ]] && { tile="${first#"$TILES_DIR"/}"; break; }
  done
  [[ -n "$tile" ]] || { echo "ERROR: no first tile in $pyramid" >&2; exit 1; }
  curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$TILES_URL/$tile?deploy-check=$stamp" \
    | cmp -s - "$TILES_DIR/$tile" \
    || { echo "ERROR: /$tile unreachable or differs from the tile tree" >&2; exit 1; }
  echo "tile verified: /$tile"
done

# The edge keeps a tile only on the origin's word, and a page on another site
# reads it only with the CORS header. The first request above filled the edge
# cache for this URL, so this one shows whether the zone caches tiles at all.
headers=$(curl -fsS -o /dev/null -D - "$TILES_URL/$tile?deploy-check=$stamp" | tr -d '\r')
header() { awk -F': ' -v name="$1" 'tolower($1) == name { print $2 }' <<<"$headers"; }

[[ "$(header cache-control)" == "public, max-age=31536000, immutable" ]] \
  || { echo "ERROR: /$tile has Cache-Control '$(header cache-control)'" >&2; exit 1; }
[[ "$(header access-control-allow-origin)" == "*" ]] \
  || { echo "ERROR: /$tile has no CORS header for any origin" >&2; exit 1; }
echo "tile headers verified"

status=$(header cf-cache-status)
case "$status" in
  "") echo "WARNING: no cf-cache-status header; $TILES_URL is not behind Cloudflare" >&2 ;;
  DYNAMIC | BYPASS)
    echo "ERROR: the edge does not cache tiles (cf-cache-status: $status)" >&2
    exit 1
    ;;
  *) echo "edge cache: $status" ;;
esac
