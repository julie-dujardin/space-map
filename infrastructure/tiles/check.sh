#!/usr/bin/env bash
set -euo pipefail

# Checks the tile host against the tile tree, which holds the surface tiles and
# the extrasolar export. The host serves the tree as it is (compose/), so
# neither has an upload step: this is their whole deploy.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TILES_DIR="${TILES_DIR:-$REPO_ROOT/../space-map-tiles}"
TILES_URL="${TILES_URL:-https://tiles.spacemap.co}"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

[[ -d "$TILES_DIR/v1/tiles" ]] \
  || { echo "ERROR: no tiles at $TILES_DIR/v1/tiles — run space-map-ingest --targets tiles" >&2; exit 1; }

# The cache-buster skips the edge cache, so each answer comes from the origin.
stamp=$(date +%s)

# One tile per pyramid, end to end. A monthly map holds a pyramid per month,
# one folder down.
for pyramid in "$TILES_DIR"/v1/tiles/*/; do
  [[ "$pyramid" == *.building/ || "$pyramid" == *.retired/ ]] && continue
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
# A retry leaves the failed attempts' headers in front: read the last block.
header() {
  awk -F': ' -v name="$1" '/^HTTP\// { value = "" } tolower($1) == name { value = $2 } END { print value }' <<<"$headers"
}
expect() {
  [[ "$(header "$2")" == "$3" ]] || { echo "ERROR: /$1 has $2 '$(header "$2")', not '$3'" >&2; exit 1; }
}

expect "$tile" cache-control "public, max-age=31536000, immutable"
expect "$tile" access-control-allow-origin "*"
echo "tile headers verified"

edge_caches() {
  local status
  status=$(header cf-cache-status)
  case "$status" in
    "") echo "WARNING: no cf-cache-status header; $TILES_URL is not behind Cloudflare" >&2 ;;
    DYNAMIC | BYPASS)
      echo "ERROR: the edge does not cache $1 (cf-cache-status: $status)" >&2
      exit 1
      ;;
    *) echo "edge cache: $status" ;;
  esac
}
edge_caches tiles

# A browser's request: an encoding added to a .gz file would have the browser
# decode it before the client does.
probe() {
  headers=$(curl -fsS --retry 5 --retry-delay 3 --retry-all-errors --compressed \
    -H 'Accept-Encoding: gzip, br, zstd' -o "$scratch/body" -D - "$TILES_URL/$1" | tr -d '\r')
}

# The extrasolar export: each entry point, and one small tokened file of each
# root. Dust and glow are left out of the served root while their sources are
# undecided, so only the star tree is required.
declare -A small=([x]=metadata/split.bin.gz [dust]=high/far.bin.gz [glow]=regions.bin.gz)
declare -A command=([x]=extrasolar [dust]=dust [glow]=glow)
for root in x dust glow; do
  if [[ ! -f "$TILES_DIR/v1/$root/metadata.json" ]]; then
    message="no $TILES_DIR/v1/$root/metadata.json — run space-map-export --only ${command[$root]}"
    [[ "$root" == x ]] && { echo "ERROR: $message" >&2; exit 1; }
    echo "WARNING: $message" >&2
    continue
  fi

  # The entry points hold the tokens: an edge copy would pin old ones.
  path="v1/$root/metadata.json"
  probe "$path"
  cmp -s "$scratch/body" "$TILES_DIR/$path" \
    || { echo "ERROR: /$path differs from the tile tree" >&2; exit 1; }
  expect "$path" cache-control "no-cache"
  case "$(header cf-cache-status)" in
    "" | DYNAMIC | BYPASS) ;;
    *) echo "ERROR: the edge caches /$path (cf-cache-status: $(header cf-cache-status))" >&2; exit 1 ;;
  esac
  echo "entry point verified: /$path"

  path="v1/$root/${small[$root]}"
  probe "$path?deploy-check=$stamp"
  cmp -s "$scratch/body" "$TILES_DIR/$path" \
    || { echo "ERROR: /$path differs from the tile tree" >&2; exit 1; }
  expect "$path" content-encoding ""
  expect "$path" content-type "application/octet-stream"
  expect "$path" cache-control "public, max-age=31536000, immutable"
  expect "$path" access-control-allow-origin "*"
  echo "file verified: /$path"
  edge_caches "/$path"
done
