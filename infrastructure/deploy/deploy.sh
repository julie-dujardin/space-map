#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXPORT_DIR="$REPO_ROOT/../space-map-export"
# Meili's admin port binds to loopback on the VPS; forward it first with
# `ssh -L 9751:127.0.0.1:9751 <vps>`.
MEILI_URL="${MEILI_URL:-http://127.0.0.1:9751}"

probe() {
  curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$1"
}

# Fail before uploading anything if the search leg can't run: the asset upload
# is the expensive half, and a half-done deploy leaves search stale.
: "${MEILI_MASTER_KEY:?must be set for the search push}"
probe "$MEILI_URL/health" >/dev/null \
  || { echo "ERROR: Meili unreachable at $MEILI_URL — is the SSH forward up?" >&2; exit 1; }

# Both projects serve from the same export tree; the active .assetsignore picks
# which half each upload covers. Sequential, so swapping the file is safe.
cp "$SCRIPT_DIR/_headers" "$EXPORT_DIR/_headers"

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

# Last: the index links into pages the static deploy just published, so results
# never point at data that isn't live yet. The push itself swaps atomically.
(cd "$REPO_ROOT/data" && MEILI_URL="$MEILI_URL" uv run space-map-search push --export-dir "$EXPORT_DIR")

docs=$(curl -fsS -H "Authorization: Bearer $MEILI_MASTER_KEY" "$MEILI_URL/indexes/catalog/stats" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["numberOfDocuments"])')
[[ "$docs" -gt 0 ]] || { echo "ERROR: catalog index is empty after push" >&2; exit 1; }
echo "search push verified: catalog holds $docs documents"
