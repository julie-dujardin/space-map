/** Loader of the about page: its figures come from the payload of /about/data
 *  and the panorama index. */

import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import { fetchAboutData } from '$lib/about/data-payload';
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
		const [report, panoramas] = await Promise.all([
			fetchAboutData(fetch),
			fetchPanoramaIndex(fetch)
		]);
		return aboutFigures(report, panoramas);
	})();
	return { figures };
};
