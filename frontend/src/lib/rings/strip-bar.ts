/**
 * The ring plane as a picture: the same rendered profiles the Rings tab charts,
 * laid out along the horizontal and stripped of the axis, the labels and the
 * scale breaks. It backs the tiles on the Ring Systems page for the bodies no
 * photograph of the rings exists for.
 *
 * The scale is linear and unbroken, unlike the panel's: a bar with nothing to
 * read the axis off would state a radius ratio it does not have. What that
 * costs is Saturn's main rings taking a sixth of the bar and the E ring the
 * rest, which is the shape of the system.
 */

import type { RingFeature } from '$lib/fetch/objects/object-data';
import { opacity, span, tauOpacity } from './catalog';
import { sampleProfiles, type RingStripProfile } from './strip';

/** Samples across the bar. The tile stretches it to whatever width it has, so
 *  this is resolution rather than layout — a little above the widest tile. */
const WIDTH = 256;
/** Samples a named feature keeps even where the profile averages it away:
 *  Uranus' ε ring is 58 km of a 65,000 km bar and would otherwise vanish. */
const MIN_MARK = 3;
/** Untinted material — a catalogued band no bundle draws has no colour of its
 *  own. Matches the panel's strip. */
const PALE: readonly [number, number, number] = [241, 245, 249];

interface Band {
	inner: number;
	outer: number;
	alpha: number;
}

/** Radial window the bar covers: what the render bundles actually draw, not
 *  what the catalogue lists. Saturn's Phoebe ring sits twelve million km out
 *  and nothing renders it, so including it would squeeze every visible ring
 *  into the first percent of the bar. */
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
 *  when nothing is known to draw. The caller stretches it over the tile, or
 *  over the stretch of a wider chart `window` names. */
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
		// A bundle whose eight bits quantise its faintest material away says as
		// little as no bundle at all: Uranus' ν and µ rings sit four decades under
		// the ε ring its strip is scaled for and come back empty. The catalogue
		// has a number for them.
		if (!alpha) {
			const mid = (lo + hi) / 2;
			for (const band of bands) if (mid >= band.inner && mid <= band.outer) alpha = band.alpha;
		}
		image.data[x * 4] = red;
		image.data[x * 4 + 1] = green;
		image.data[x * 4 + 2] = blue;
		image.data[x * 4 + 3] = Math.round(alpha * 255);
	}
	// Every named feature keeps a mark of its own, at the catalogue's optical
	// depth — the box filter above averages a narrow ring into the empty space
	// around it, which is most of what the small bodies have.
	for (const band of bands) {
		const from = (band.inner - min) / perPixel;
		const to = (band.outer - min) / perPixel;
		if (to - from >= MIN_MARK || to < 0 || from > WIDTH) continue;
		const alpha = Math.round(band.alpha * 255);
		const first = Math.max(0, Math.min(WIDTH - MIN_MARK, Math.round((from + to - MIN_MARK) / 2)));
		for (let x = first; x < first + MIN_MARK; x++) {
			const at = x * 4;
			if (image.data[at + 3] >= alpha) continue;
			// Only a pixel the profile never reached needs a colour of its own.
			if (!image.data[at + 3]) [image.data[at], image.data[at + 1], image.data[at + 2]] = PALE;
			image.data[at + 3] = alpha;
		}
	}
	ctx.putImageData(image, 0, 0);
	return canvas.toDataURL();
}
