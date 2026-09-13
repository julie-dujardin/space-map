/**
 * Which panoramas of a traverse stand for it: the best-covered sweeps, spread
 * over the years the rover drove rather than clustered on its best week.
 */

import type { PanoramaEntry } from '$lib/fetch/objects/object-data';

/** Colour reads as a photograph of the place; a grayscale sweep reads as
 *  instrument data, so it only wins on much wider coverage. */
const COLOR_BONUS = 15;

function score(entry: PanoramaEntry): number {
	const covered = entry.sphere_percent ?? 0;
	return covered + (entry.color && entry.color !== 'grayscale' ? COLOR_BONUS : 0);
}

/**
 * Up to `limit` entries, one from each equal slice of the traverse's span, so
 * the set walks the mission from landing to now. Slices the rover skipped give
 * their place back to the next-best entry anywhere, which keeps the count at
 * `limit` on a traverse whose stops bunch up.
 */
export function panoramaHighlights(
	entries: readonly PanoramaEntry[],
	limit: number
): PanoramaEntry[] {
	if (entries.length <= limit) return [...entries];
	const times = entries.map((e) => Date.parse(e.time));
	const first = Math.min(...times);
	const span = Math.max(...times) - first;
	const best = new Map<number, PanoramaEntry>();
	entries.forEach((entry, i) => {
		// The last entry sits exactly on the span's end, which would index a
		// slice past the last one.
		const slice = span ? Math.min(limit - 1, Math.floor(((times[i] - first) / span) * limit)) : 0;
		const held = best.get(slice);
		if (!held || score(entry) > score(held)) best.set(slice, entry);
	});
	const picked = [...best.values()];
	if (picked.length < limit) {
		const rest = entries
			.filter((e) => !picked.includes(e))
			.sort((a, b) => score(b) - score(a))
			.slice(0, limit - picked.length);
		picked.push(...rest);
	}
	return picked.sort((a, b) => a.time.localeCompare(b.time));
}
