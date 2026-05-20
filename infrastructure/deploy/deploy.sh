#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WRANGLER="$REPO_ROOT/frontend/node_modules/.bin/wrangler"
EXPORT_DIR="$REPO_ROOT/../space-map-export"

cp "$SCRIPT_DIR/_headers" "$EXPORT_DIR/_headers"
cp "$SCRIPT_DIR/.assetsignore" "$EXPORT_DIR/.assetsignore"

exec "$WRANGLER" deploy --config "$SCRIPT_DIR/wrangler.jsonc"
