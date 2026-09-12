/**
 * Shared scatter-plot samples for the orbit-class chart on small-body group
 * pages. Fetched once and cached (~1k objects, ~30 KB gzipped).
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';
import type { OrbitSample } from '$lib/charts/orbit-zones';

interface OrbitSamplesFile {
	samples: OrbitSample[];
}

const loadFile = memoizedGzJson<OrbitSamplesFile>(
	() => `${dataBase()}/v1/groups/__orbit_samples__.json.gz`,
	{ error: (res) => `Failed to fetch orbit samples: ${res.status}` }
);

export async function fetchOrbitSamples(): Promise<OrbitSample[]> {
	return (await loadFile()).samples;
}
