/**
 * Shared scatter-plot samples for the orbit-class chart on small-body group
 * pages. Fetched once and cached (~1k objects, ~30 KB gzipped).
 */

import { dataBase } from '$lib/fetch/data-base';
import type { OrbitSample } from '$lib/charts/orbit-zones';

interface OrbitSamplesFile {
	samples: OrbitSample[];
}

let pending: Promise<OrbitSample[]> | null = null;

export function fetchOrbitSamples(): Promise<OrbitSample[]> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(`${dataBase()}/v1/groups/__orbit_samples__.json.gz`);
		if (!res.ok) throw new Error(`Failed to fetch orbit samples: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		const file = (await new Response(res.body!.pipeThrough(ds)).json()) as OrbitSamplesFile;
		return file.samples;
	})();
	return pending;
}
