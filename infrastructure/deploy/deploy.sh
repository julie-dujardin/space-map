#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXPORT_DIR="$REPO_ROOT/../space-map-export"

# Both projects serve from the same export tree; the active .assetsignore picks
# which half each upload covers. Sequential, so swapping the file is safe.
cp "$SCRIPT_DIR/_headers" "$EXPORT_DIR/_headers"

probe() {
  curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$1"
}

# Images before static: static's metadata.json emits new ?v= tokens for images
# the edge caches immutably for a year — ship the bytes before the tokens.
cp "$SCRIPT_DIR/.assetsignore.images" "$EXPORT_DIR/.assetsignore"
npx wrangler deploy --config "$SCRIPT_DIR/wrangler.images.jsonc"

# Verify with an image from this export (URL-safe names only, to skip encoding).
image_path=$(cd "$EXPORT_DIR" && find v1/images -type f | grep -m1 -E '^[A-Za-z0-9._/-]+$' || true)
if [[ -z "$image_path" ]]; then
  echo "WARNING: no URL-safe image found in export; skipping images verification" >&2
else
  probe "https://images.spacemap.co/$image_path" >/dev/null
  echo "images deploy verified: /$image_path"
fi

cp "$SCRIPT_DIR/.assetsignore.static" "$EXPORT_DIR/.assetsignore"
npx wrangler deploy --config "$SCRIPT_DIR/wrangler.jsonc"

# The cache-buster skips the edge cache so we compare against the new deploy,
# not a stale copy.
probe "https://static.spacemap.co/v1/metadata.json?deploy-check=$(date +%s)" \
  | cmp -s - "$EXPORT_DIR/v1/metadata.json" \
  || { echo "ERROR: metadata.json unreachable or differs from local export" >&2; exit 1; }
echo "static deploy verified: metadata.json matches local export"
