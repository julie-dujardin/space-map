# Search load test (Meilisearch)

k6 harness answering "how many parallel searches per CPU core, and how cheap a VPS?"
against the `catalog` index (184k docs — the prod set; the 1.5M bare asteroids aren't
indexed). `search-load.js` replays the two real frontend requests (`client.ts`):
autocomplete (`/indexes/catalog/search`) and faceted (`/multi-search`). Closed-loop
`constant-vus` — throughput self-limits at capacity, latency stays honest.
`run-sweep.sh` CPU-limits the container (`docker update --cpus`) to 1/2/4 cores and
sweeps concurrency.

```bash
export SEARCH_KEY=<scoped key from frontend/.env>
./run-sweep.sh autocomplete          # or: faceted   [DROP_GROUPS_FACET=1]
```

## Results

| workload | rps/core (p95 ≤ ~5 ms) | engine time |
| --- | --- | --- |
| autocomplete (per keystroke) | ~1300 | <1 ms |
| faceted (open catalog/filter) | ~235 | ~4–5 ms |

Scales linearly with cores.

**Sizing:** a 2-core / 2–4 GB VPS handles ~2500 autocomplete + ~500 faceted rps —
thousands of concurrent users. CPU isn't the limit; RAM is (index ~960 MB disk /
~1.1 GB resident). Loopback numbers — add real network RTT.
