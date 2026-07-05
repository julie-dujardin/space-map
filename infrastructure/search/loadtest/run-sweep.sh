#!/usr/bin/env bash
# Sweep search throughput across CPU allotments to size a cheap VPS. Per CPU count,
# live-limit the container and ramp concurrency; the throughput plateau (where
# latency starts rising) is the sustainable req/s.
#
# Usage: ./run-sweep.sh [MODE] [CONTAINER]     MODE: autocomplete|faceted|mixed
# Env: MEILI_URL, SEARCH_KEY (see .env), CPUS, VULIST
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-autocomplete}"
CONTAINER="${2:-space-map-meili-1}"
export MEILI_URL="${MEILI_URL:-http://127.0.0.1:7700}"
export SEARCH_KEY="${SEARCH_KEY:-efea539197bab57084a160f442f693c5fb45ab9fc45dac3e9be729e1c1d691bf}"

CPUS="${CPUS:-1 2 4}"
# Faceted requests are heavier, so fewer VUs saturate.
if [ "$MODE" = "faceted" ]; then
	VULIST="${VULIST:-2 4 8 16 32 64}"
else
	VULIST="${VULIST:-4 8 16 32 64 128 256}"
fi

# quota -1 is the only reliable "unlimited" reset — `--cpus 0` is a silent no-op.
restore() {
	echo ">> restoring container to unlimited CPU"
	docker update --cpu-quota -1 "$CONTAINER" >/dev/null 2>&1 || true
}
trap restore EXIT

mkdir -p results
echo "mode=$MODE  cpus=[$CPUS]  vus=[$VULIST]  url=$MEILI_URL"

for c in $CPUS; do
	echo "=================================================================="
	echo ">> limiting $CONTAINER to $c CPU(s)"
	docker update --cpus "$c" "$CONTAINER" >/dev/null
	sleep 2
	# Warm the OS page cache / index at this allotment before measuring.
	MODE="$MODE" VUS=8 DURATION=8 TAG="warm" k6 run --quiet search-load.js >/dev/null 2>&1 || true

	for v in $VULIST; do
		tag="${c}c_v${v}"
		echo "-- $c CPU, $v concurrent clients"
		MODE="$MODE" VUS="$v" DURATION=15 TAG="$tag" \
			k6 run --quiet search-load.js >/dev/null 2>&1 || true
		# Compact one-line readout from the JSON summary.
		python3 - "$tag" "$MODE" <<'PY'
import json,sys
tag,mode=sys.argv[1],sys.argv[2]
try:
	d=json.load(open(f"results/summary_{mode}_{tag}.json"))
	r=d["rtt_ms"]; m=d["meili_processing_ms"]
	print(f"   {d['rps_achieved']:6.0f} rps | p50 {r['p50']:5.1f}ms  p95 {r['p95']:6.1f}ms  p99 {r['p99']:6.1f}ms"
	      f" | meili p95 {m['p95'] or 0:5.1f}ms | fail {d['failed_rate']*100:.2f}%")
except Exception as e:
	print(f"   (no summary: {e})")
PY
	done
done
echo "=================================================================="
echo "done. per-run JSON in results/summary_${MODE}_*.json"
