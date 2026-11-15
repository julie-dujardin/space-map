/**
 * Loader of the data page. The page is static: it imports nothing of the 3D
 * map.
 */

import { dataBase } from '$lib/fetch/data-base';
import { fetchAboutData, type AboutData } from '$lib/about/data-payload';
import type { Credits } from '$lib/credits/credits-payload';
import { fetchStarCatalogueCredits, referenceCount } from '$lib/credits/star-sources';

// On the server, a fetch of `/data` collides with the [type]/[id] route.
export const ssr = false;

// The payload is not awaited: the frame of the page draws before it lands.
export const load = ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): { report: Promise<AboutData>; references: Promise<number> } => {
	// A file from an older export is refused: the page then states an error.
	const report = fetchAboutData(fetch);
	const references = (async () => {
		const [res, stars] = await Promise.all([
			fetch(`${dataBase()}/v1/credits.json`),
			fetchStarCatalogueCredits()
		]);
		if (!res.ok) throw new Error(`Failed to load credits.json: ${res.status}`);
		return referenceCount((await res.json()) as Credits, stars);
	})();
	return { report, references };
};
