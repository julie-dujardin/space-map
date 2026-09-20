#!/usr/bin/env bash
set -euo pipefail

# Puts one SDK release on cdn.spacemap.co under its version. A version is
# immutable once served, so a path that already answers is never overwritten.
# Usage: publish.sh <version> <dist dir>   (needs CLOUDFLARE_API_TOKEN + ACCOUNT_ID, or a wrangler login)

BUCKET="spacemap-cdn"
BASE_URL="https://cdn.spacemap.co"
FILES=(spacemap.js spacemap.js.map spacemap.iife.js spacemap.iife.js.map)

version="${1:?version, e.g. 0.1.1}"
dist="${2:?dist dir holding the CDN build}"

for file in "${FILES[@]}"; do
  [[ -f "$dist/$file" ]] || { echo "ERROR: $dist/$file is missing — run pnpm build:sdk" >&2; exit 1; }
done

# The cache-buster reads R2 rather than the edge, and a 200 means this version shipped.
if curl -fsS -o /dev/null "$BASE_URL/$version/spacemap.js?publish-check=$(date +%s)"; then
  echo "ERROR: $BASE_URL/$version/ is already published; bump the version" >&2
  exit 1
fi

for file in "${FILES[@]}"; do
  case "$file" in
    *.map) type="application/json" ;;
    *) type="text/javascript; charset=utf-8" ;;
  esac
  npx wrangler r2 object put "$BUCKET/$version/$file" --file "$dist/$file" --remote \
    --content-type "$type" --cache-control "public, max-age=31536000, immutable"
done

curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$BASE_URL/$version/spacemap.js?publish-check=$(date +%s)" \
  | cmp -s - "$dist/spacemap.js" \
  || { echo "ERROR: $BASE_URL/$version/spacemap.js unreachable or differs from the build" >&2; exit 1; }
echo "cdn publish verified: $BASE_URL/$version/"

# Pinned in a page's script tag, these make a swapped file fail to load.
echo "Subresource integrity:"
for file in spacemap.js spacemap.iife.js; do
  echo "  $file  sha384-$(openssl dgst -sha384 -binary "$dist/$file" | base64 -w0)"
done
