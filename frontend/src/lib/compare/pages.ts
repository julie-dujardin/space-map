/**
 * Pages for the comparison row. One scale can only carry so much: past a
 * point the smallest body is a pixel beside the largest, and the row stops
 * saying anything. So the set is cut where its own sizes make a jump, and each
 * band is drawn on its own scale. A band is then cut again into screens, where
 * the bodies and their names run out of width, each screen on a scale of its
 * own: what a page holds is what stands on it large.
 */

/** A jump this large between neighbouring sizes starts a new band: the row
 *  has left one class of thing for another. */
export const BAND_GAP = 8;
/** And a band never spans more than this, however smoothly its sizes run —
 *  past it the smallest is a few pixels beside the largest and says nothing. */
export const BAND_SPAN = 25;

export interface SizeBand<T> {
	/** Largest first, as the row draws them. */
	items: T[];
	/** The band before this one, ending with its smallest body: the row draws
	 *  it at this band's scale, where it towers over everything. */
	previous?: T;
	/** The band after this one, starting with its largest body. */
	next?: T;
}

/**
 * Cut `items` into bands: at a jump between neighbours, and wherever a band
 * has stretched as far as one scale can carry. Sizes must be positive and in
 * one unit; anything else is dropped, since a body with no size has no place
 * in a size comparison.
 */
export function bandsBySize<T>(
	items: readonly T[],
	size: (item: T) => number,
	gap: number = BAND_GAP,
	span: number = BAND_SPAN
): SizeBand<T>[] {
	const sized = items.filter((item) => size(item) > 0);
	if (sized.length === 0) return [];
	const ordered = [...sized].sort((a, b) => size(b) - size(a));

	const bands: T[][] = [[ordered[0]]];
	let largest = size(ordered[0]);
	for (let i = 1; i < ordered.length; i++) {
		const next = size(ordered[i]);
		if (size(ordered[i - 1]) / next > gap || largest / next > span) {
			bands.push([]);
			largest = next;
		}
		bands[bands.length - 1].push(ordered[i]);
	}

	return bands.map((band, i) => ({
		items: band,
		previous: bands[i - 1]?.at(-1),
		next: bands[i + 1]?.[0]
	}));
}

/** One screen of a band: what the row draws at once. */
export interface SizeScreen<T> extends SizeBand<T> {
	/** Pixels per unit of size on this screen. */
	scale: number;
}

/** How many bodies stand on a screen, and the scale they are drawn on. */
export interface ScreenFit {
	count: number;
	scale: number;
}

/**
 * Cut each band into screens, so that a name is never squeezed off a body:
 * the rest turn the page instead. `fit` is handed what is left of the band,
 * the body that follows the band, and whether this is the band's first
 * screen, which has no page before it to keep a strip for.
 */
export function screensOf<T>(
	bands: readonly SizeBand<T>[],
	fit: (rest: readonly T[], after: T | undefined, first: boolean) => ScreenFit
): SizeScreen<T>[] {
	const screens: SizeScreen<T>[] = [];
	for (const band of bands) {
		let rest = band.items;
		let previous = band.previous;
		while (rest.length) {
			const screen = fit(rest, band.next, rest === band.items);
			const n = Math.max(1, screen.count);
			const items = rest.slice(0, n);
			rest = rest.slice(n);
			screens.push({ items, previous, next: rest[0] ?? band.next, scale: screen.scale });
			previous = items[n - 1];
		}
	}
	return screens;
}
