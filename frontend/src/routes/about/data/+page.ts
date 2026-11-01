/**
 * Loader of the data page. The page is static: it imports nothing of the 3D
 * map.
 */

import { dataBase } from '$lib/fetch/data-base';
import type { AboutData } from '$lib/about/data-payload';
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
	const report = (async () => {
		const res = await fetch(`${dataBase()}/v1/about-data.json`);
		if (!res.ok) throw new Error(`Failed to load about-data.json: ${res.status}`);
		const data = (await res.json()) as AboutData;
		// A host or a cache can hold a file from an older export, which has no
		// objects or no names. The page then states an error.
		if (!data.objects || !data.names) throw new Error('about-data.json is older than the page');
		return data;
	})();
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
