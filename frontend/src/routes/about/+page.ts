/** Loader of the about page: its figures come from the payload of /about/data
 *  and the panorama index. */

import { dataBase } from '$lib/fetch/data-base';
import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import type { AboutData } from '$lib/about/data-payload';
import { aboutFigures, type AboutFigures } from '$lib/about/about-figures';

// On the server, a fetch of `/data` collides with the [type]/[id] route.
export const ssr = false;

// Not awaited: the text draws at once and the figures fill in.
export const load = ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): { figures: Promise<AboutFigures> } => {
	const figures = (async () => {
		const [res, panoramas] = await Promise.all([
			fetch(`${dataBase()}/v1/about-data.json`),
			fetchPanoramaIndex(fetch)
		]);
		if (!res.ok) throw new Error(`Failed to load about-data.json: ${res.status}`);
		return aboutFigures((await res.json()) as AboutData, panoramas);
	})();
	return { figures };
};
