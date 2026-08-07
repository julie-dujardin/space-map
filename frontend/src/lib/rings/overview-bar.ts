/**
 * The radial window the Overview's ring bar draws: the body's centre out to the
 * far edge of its rings, so the emptiness between planet and rings is part of
 * the picture rather than cropped away.
 *
 * The Rings tab breaks its axis where a void would waste the chart. A bar this
 * short has no room to mark a break and no axis to read one off, so it stops
 * instead — the tab's own chart is where the full extent is readable.
 */

import type { RingFeature } from '$lib/fetch/objects/object-data';
import { span } from './catalog';

export interface RingBarWindow {
	/** Inner and outer edge of the ring material drawn, km from the body's
	 *  centre. The bar runs from 0 to `outer` plus a fixed margin. */
	inner: number;
	outer: number;
}

/** Radii holding material, inner → outer, merged where they meet. */
function runs(features: Record<string, RingFeature>): Array<[number, number]> {
	const spans = Object.values(features)
		.map(span)
		.filter(([inner, outer]) => Number.isFinite(inner) && Number.isFinite(outer))
		.sort((a, b) => a[0] - b[0]);
	const merged: Array<[number, number]> = [];
	for (const [inner, outer] of spans) {
		const last = merged[merged.length - 1];
		if (last && inner <= last[1]) last[1] = Math.max(last[1], outer);
		else merged.push([inner, outer]);
	}
	return merged;
}

export function ringBarWindow(features: Record<string, RingFeature>): RingBarWindow | null {
	const material = runs(features);
	if (!material.length) return null;
	const [inner] = material[0];
	let outer = material[0][1];
	for (const [from, to] of material.slice(1)) {
		// Stop where the empty stretch ahead is wider than everything drawn so
		// far: Saturn's Phoebe ring sits twelve million km out, and reaching it
		// would leave the rings anyone recognises inside the first 4% of the bar.
		if (from - outer > outer) break;
		outer = to;
	}
	return outer > inner ? { inner, outer } : null;
}
