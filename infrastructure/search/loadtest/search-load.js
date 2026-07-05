// k6 load test for the Meilisearch `catalog` index. Replays the frontend's two
// request shapes (client.ts): autocomplete and faceted multi-search.
//
//   MODE=autocomplete VUS=64 k6 run search-load.js
//
// Closed-loop (constant-vus) so throughput self-limits at capacity and every
// request completes — an open arrival-rate model lets saturated requests drain
// into gracefulStop, corrupting both the rate and the latency percentiles.
//
// Env: MEILI_URL, SEARCH_KEY, MODE (autocomplete|faceted|mixed),
//      VUS (concurrent clients), DURATION (s), TAG (summary label).

import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import {
	AUTOCOMPLETE_TERMS,
	autocompleteBody,
	facetedBody,
	FACETED_COUNT,
	LOCALES
} from './queries.js';

const URL = __ENV.MEILI_URL || 'http://127.0.0.1:7700';
const KEY = __ENV.SEARCH_KEY || '';
const MODE = __ENV.MODE || 'mixed';
const VUS = parseInt(__ENV.VUS || '32', 10);
const DURATION = parseInt(__ENV.DURATION || '15', 10);
const TAG = __ENV.TAG || 'na';

// Meilisearch's own reported query time, separate from HTTP round-trip.
const meiliMs = new Trend('meili_processing_ms', true);
const errors = new Counter('search_errors');

const headers = {
	'Content-Type': 'application/json',
	Authorization: `Bearer ${KEY}`
};

export const options = {
	discardResponseBodies: false,
	summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
	scenarios: {
		load: {
			executor: 'constant-vus',
			vus: VUS,
			duration: `${DURATION}s`
		}
	},
	thresholds: {
		// Informational only (abortOnFail off): flag when the p95 round-trip
		// crosses a search-as-you-type-acceptable bound.
		http_req_duration: [{ threshold: 'p(95)<150', abortOnFail: false }],
		http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }]
	}
};

function pick(arr, i) {
	return arr[i % arr.length];
}

let n = 0;

export default function () {
	n++;
	const locale = pick(LOCALES, n);
	let body, path;

	const faceted =
		MODE === 'faceted' || (MODE === 'mixed' && n % 100 < 15); // ~15% faceted in mixed

	if (faceted) {
		path = '/multi-search';
		body = facetedBody(n % FACETED_COUNT, locale);
	} else {
		path = '/indexes/catalog/search';
		body = autocompleteBody(pick(AUTOCOMPLETE_TERMS, n * 7), locale);
	}

	const res = http.post(`${URL}${path}`, body, { headers, tags: { kind: faceted ? 'faceted' : 'autocomplete' } });

	const ok = check(res, { '2xx': (r) => r.status >= 200 && r.status < 300 });
	if (!ok) {
		errors.add(1);
		return;
	}

	// Sum processingTimeMs across sub-queries for multi-search.
	try {
		const j = res.json();
		if (j.processingTimeMs != null) meiliMs.add(j.processingTimeMs);
		else if (Array.isArray(j.results))
			meiliMs.add(j.results.reduce((s, q) => s + (q.processingTimeMs || 0), 0));
	} catch (_e) {
		// non-JSON error body; already counted by the check
	}
}

export function handleSummary(data) {
	const m = data.metrics;
	const g = (name, stat) => (m[name] && m[name].values ? m[name].values[stat] : null);
	const out = {
		tag: TAG,
		mode: MODE,
		vus: VUS,
		http_reqs: g('http_reqs', 'count'),
		rps_achieved: g('http_reqs', 'rate'),
		failed_rate: g('http_req_failed', 'rate'),
		errors: g('search_errors', 'count'),
		rtt_ms: {
			avg: g('http_req_duration', 'avg'),
			p50: g('http_req_duration', 'med'),
			p90: g('http_req_duration', 'p(90)'),
			p95: g('http_req_duration', 'p(95)'),
			p99: g('http_req_duration', 'p(99)'),
			max: g('http_req_duration', 'max')
		},
		meili_processing_ms: {
			avg: g('meili_processing_ms', 'avg'),
			p95: g('meili_processing_ms', 'p(95)')
		}
	};
	const file = `results/summary_${MODE}_${TAG}.json`;
	return {
		stdout: '\n' + JSON.stringify(out, null, 2) + '\n',
		[file]: JSON.stringify(out, null, 2)
	};
}
