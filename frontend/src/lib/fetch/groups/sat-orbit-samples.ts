/**
 * Earth-sat scatter samples for the orbit-class chart on Earth-orbit group
 * pages (LEO, MEO, …). Fetched once and cached.
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';
import type { EarthOrbitSample } from '$lib/charts/orbit-zones';

interface SatOrbitSamplesFile {
	samples: EarthOrbitSample[];
}

const loadFile = memoizedGzJson<SatOrbitSamplesFile>(
	() => `${dataBase()}/v1/groups/__sat_orbit_samples__.json.gz`,
	{ error: (res) => `Failed to fetch sat orbit samples: ${res.status}` }
);

export async function fetchSatOrbitSamples(): Promise<EarthOrbitSample[]> {
	return (await loadFile()).samples;
}
