/**
 * Radial window the Overview's ring bar draws: body centre to the far edge of
 * its rings, so the empty gap between them is part of the picture, not cropped.
 * Unlike the Rings tab's chart, this bar is too short to mark an axis break, so
 * it stops instead of trying to represent the full extent.
 */

import type { RingFeature } from '$lib/fetch/objects/object-data';
import { span } from './catalog';

export interface RingBarWindow {
	/** Inner/outer edge of the ring material drawn, km from the body's centre. */
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
		// Stop once the gap ahead exceeds everything drawn so far — else outliers
		// like Saturn's Phoebe ring (12M km out) squeeze the visible rings tiny.
		if (from - outer > outer) break;
		outer = to;
	}
	return outer > inner ? { inner, outer } : null;
}
