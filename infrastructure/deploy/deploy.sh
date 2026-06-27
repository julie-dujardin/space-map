#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXPORT_DIR="$REPO_ROOT/../space-map-export"

# Both projects serve from the same export tree; the active .assetsignore picks
# which half each upload covers. Sequential, so swapping the file is safe.
cp "$SCRIPT_DIR/_headers" "$EXPORT_DIR/_headers"

cp "$SCRIPT_DIR/.assetsignore.static" "$EXPORT_DIR/.assetsignore"
npx wrangler deploy --config "$SCRIPT_DIR/wrangler.jsonc"

cp "$SCRIPT_DIR/.assetsignore.images" "$EXPORT_DIR/.assetsignore"
exec npx wrangler deploy --config "$SCRIPT_DIR/wrangler.images.jsonc"
