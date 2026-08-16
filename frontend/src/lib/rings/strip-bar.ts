/**
 * The ring plane as a picture: the Rings tab's rendered profiles, laid out
 * horizontally with no axis, labels, or scale breaks. Backs the tiles on the
 * Ring Systems page for bodies with no photograph.
 *
 * Scale is linear and unbroken, unlike the panel's — a bar with no axis to
 * read can't imply a ratio it doesn't show. Cost: Saturn's main rings take a
 * sixth of the bar, the E ring the rest.
 */

import type { RingFeature } from '$lib/fetch/objects/object-data';
import { opacity, span, tauOpacity } from './catalog';
import { sampleProfiles, type RingStripProfile } from './strip';

/** Sample resolution, not layout — the tile stretches this to its own width.
 *  A little above the widest tile. */
const WIDTH = 256;
/** Minimum pixels a named feature keeps so it can't vanish into averaging:
 *  Uranus' ε ring is 58 km of a 65,000 km bar. */
const MIN_MARK = 3;
/** Untinted fallback for catalogued bands no bundle draws. Matches the panel's strip. */
const PALE: readonly [number, number, number] = [241, 245, 249];

interface Band {
	inner: number;
	outer: number;
	alpha: number;
}

/** Radial window the bar covers: what the render bundles actually draw, not
 *  the full catalogue — else outliers like Saturn's Phoebe ring (12M km out,
 *  never rendered) squeeze every visible ring into the first percent. */
function extent(
	profiles: readonly RingStripProfile[],
	bands: readonly Band[]
): [number, number] | null {
	const spans = profiles.length
		? profiles.map((p) => [p.inner, p.outer] as const)
		: bands.map((b) => [b.inner, b.outer] as const);
	if (!spans.length) return null;
	const min = Math.min(...spans.map(([inner]) => inner));
	const max = Math.max(...spans.map(([, outer]) => outer));
	return max > min ? [min, max] : null;
}

/** A 1-pixel-tall PNG of the body's rings, inner edge at the left, or null
 *  if nothing is known to draw. `window`, if given, overrides the drawn extent. */
export function paintRingBar(
	profiles: readonly RingStripProfile[],
	features: Record<string, RingFeature> | undefined,
	window?: readonly [number, number]
): string | null {
	if (typeof document === 'undefined') return null;
	const bands: Band[] = Object.values(features ?? {})
		.map((feature) => {
			const [inner, outer] = span(feature);
			return { inner, outer, alpha: opacity(feature) };
		})
		// Narrowest last, so a ringlet paints over the ring that contains it.
		.sort((a, b) => b.outer - b.inner - (a.outer - a.inner));
	const drawn = window ?? extent(profiles, bands);
	if (!drawn) return null;
	const [min, max] = drawn;

	const canvas = document.createElement('canvas');
	canvas.width = WIDTH;
	canvas.height = 1;
	const ctx = canvas.getContext('2d');
	if (!ctx) return null;
	const image = ctx.createImageData(WIDTH, 1);
	const perPixel = (max - min) / WIDTH;
	for (let x = 0; x < WIDTH; x++) {
		const lo = min + x * perPixel;
		const hi = lo + perPixel;
		const sample = sampleProfiles(profiles, lo, hi);
		let [red, green, blue] = PALE;
		let alpha = sample ? tauOpacity(sample.tau) : 0;
		if (alpha > 0) [red, green, blue] = sample!.rgb;
		// 8-bit quantisation loses faint material entirely (Uranus' ν and µ rings
		// sit 4 decades under the ε ring the strip is scaled for) — fall back to
		// the catalogue's number.
		if (!alpha) {
			const mid = (lo + hi) / 2;
			for (const band of bands) if (mid >= band.inner && mid <= band.outer) alpha = band.alpha;
		}
		image.data[x * 4] = red;
		image.data[x * 4 + 1] = green;
		image.data[x * 4 + 2] = blue;
		image.data[x * 4 + 3] = Math.round(alpha * 255);
	}
	// Every named feature keeps a mark at the catalogue's optical depth — the
	// box filter above averages narrow rings into the empty space around them.
	for (const band of bands) {
		const from = (band.inner - min) / perPixel;
		const to = (band.outer - min) / perPixel;
		if (to - from >= MIN_MARK || to < 0 || from > WIDTH) continue;
		const alpha = Math.round(band.alpha * 255);
		const first = Math.max(0, Math.min(WIDTH - MIN_MARK, Math.round((from + to - MIN_MARK) / 2)));
		for (let x = first; x < first + MIN_MARK; x++) {
			const at = x * 4;
			if (image.data[at + 3] >= alpha) continue;
			// Only recolour pixels the profile never touched.
			if (!image.data[at + 3]) [image.data[at], image.data[at + 1], image.data[at + 2]] = PALE;
			image.data[at + 3] = alpha;
		}
	}
	ctx.putImageData(image, 0, 0);
	return canvas.toDataURL();
}
