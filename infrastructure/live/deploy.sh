#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIVE_DIR="$REPO_ROOT/../space-map-live"

# The poller writes this file; deploying a stale one is worse than not
# deploying, since the page states an age in days from it.
[[ -f "$LIVE_DIR/v1/activity.json" ]] \
  || { echo "ERROR: no activity.json in $LIVE_DIR — is the tracking service running?" >&2; exit 1; }

cp "$SCRIPT_DIR/_headers" "$LIVE_DIR/_headers"
npx wrangler deploy --config "$SCRIPT_DIR/wrangler.jsonc"

# Cache-buster, so the check reads the deploy rather than the edge.
curl -fsS --retry 5 --retry-delay 3 --retry-all-errors \
  "https://live.spacemap.co/v1/activity.json?deploy-check=$(date +%s)" \
  | cmp -s - "$LIVE_DIR/v1/activity.json" \
  || { echo "ERROR: activity.json unreachable or differs from local copy" >&2; exit 1; }
echo "live deploy verified: activity.json matches local copy"
