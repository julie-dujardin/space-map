/**
 * Earth-sat scatter samples for the orbit-class chart on Earth-orbit group
 * pages (LEO, MEO, …). Fetched once and cached.
 */

import { DATA_BASE } from '$lib/fetch/data-base';
import type { EarthOrbitSample } from '$lib/charts/orbit-zones';

interface SatOrbitSamplesFile {
	samples: EarthOrbitSample[];
}

let pending: Promise<EarthOrbitSample[]> | null = null;

export function fetchSatOrbitSamples(): Promise<EarthOrbitSample[]> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(`${DATA_BASE}/v1/groups/__sat_orbit_samples__.json.gz`);
		if (!res.ok) throw new Error(`Failed to fetch sat orbit samples: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		const file = (await new Response(res.body!.pipeThrough(ds)).json()) as SatOrbitSamplesFile;
		return file.samples;
	})();
	return pending;
}
