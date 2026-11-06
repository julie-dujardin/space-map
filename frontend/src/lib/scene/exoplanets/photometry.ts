import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';

/** The lunar-Lambert weight scale a body draws with in the scene, a lineup and
 *  /compare: its published fit, else none. A planet of another star has an
 *  artist's picture for a map, with no measured photometry, so it takes the
 *  Lambert law (0). */
export function lunarWeightScaleOf(id: string, published?: number): number | undefined {
	return isExtrasolarObjectId(id) ? 0 : published;
}
