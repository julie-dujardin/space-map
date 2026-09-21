/**
 * Everyday objects drawn beside the row, so a craft has something next to it the
 * reader has actually stood by.
 *
 * Which one a page gets is read off the scale the row actually came out at, so
 * a reference is always drawn at a size the reader can take in beside the
 * comparison rather than at whatever its own metres happen to be. Sizes come
 * from each model bundle, so adding one is a manifest entry and a name.
 */

import * as m from '$lib/paraglide/messages.js';
import { fetchModelIndex } from '$lib/fetch/models';
import { craftHeightRatio } from '../../components/detail/charts/lineup-fit';

export interface Comparable {
	/** Model bundle slug; also the id the lineup draws it under. */
	slug: string;
	label: () => string;
}

/** Ordered small to large, as the picker walks them. */
export const COMPARABLES: Comparable[] = [
	{ slug: 'comparable-banana', label: m.compare_comparable_banana },
	{ slug: 'comparable-cat', label: m.compare_comparable_cat },
	{ slug: 'comparable-bicycle', label: m.compare_comparable_bicycle },
	{ slug: 'comparable-toyota-corolla', label: m.compare_comparable_corolla },
	{ slug: 'comparable-city-bus', label: m.compare_comparable_bus },
	{ slug: 'comparable-blue-whale', label: m.compare_comparable_whale },
	{ slug: 'comparable-boeing-737', label: m.compare_comparable_boeing },
	{ slug: 'comparable-football-pitch', label: m.compare_comparable_pitch },
	{ slug: 'comparable-container-ship', label: m.compare_comparable_ship },
	{ slug: 'comparable-eiffel-tower', label: m.compare_comparable_eiffel },
	{ slug: 'comparable-burj-khalifa', label: m.compare_comparable_burj },
	{ slug: 'comparable-golden-gate', label: m.compare_comparable_goldengate }
];

/** A comparable with the size and shape its bundle gives it. */
export interface SizedComparable extends Comparable {
	/** Half the object's real span, in km — the lineup's own measure. */
	radiusKm: number;
	/** How tall it stands on screen as a fraction of that span, so the box it is
	 *  drawn in is as flat as a bus and as tall as a tower. 1 where the bundle
	 *  never measured the mesh. */
	flatness: number;
}

/** The share of the stage's height a comparable is drawn at: big enough to read
 *  as an object, small enough that it never competes with the comparison. */
export const TARGET_SPAN = [1 / 4, 1 / 3] as const;

/** How far short of that band the best available reference may fall and still
 *  be worth drawing. Generous, because the list has gaps an order of magnitude
 *  wide and a bicycle a tenth of the stage still reads as a bicycle; past it
 *  the reader is asked to picture a speck against a wall. */
export const MAX_FACTOR = 12;

/**
 * The comparable a page is drawn with: the one that comes out nearest the
 * target share of the stage, never one that would overrun the top of the band,
 * and none at all once the page has left everyday sizes so far behind that the
 * nearest is still meaningless.
 */
export function pickComparable(
	all: readonly SizedComparable[],
	stageHeight: number,
	pxPerKm: number
): SizedComparable | null {
	if (!(stageHeight > 0) || !(pxPerKm > 0)) return null;
	const want = (stageHeight * midpoint(TARGET_SPAN)) / 2 / pxPerKm;
	const ceiling = (stageHeight * TARGET_SPAN[1]) / 2 / pxPerKm;
	let best: SizedComparable | null = null;
	let closest = Math.log(MAX_FACTOR);
	for (const candidate of all) {
		if (candidate.radiusKm > ceiling) continue;
		const apart = Math.abs(Math.log(candidate.radiusKm / want));
		if (apart > closest) continue;
		best = candidate;
		closest = apart;
	}
	return best;
}

/** Geometric, since the band is walked in ratios. */
function midpoint([lo, hi]: readonly [number, number]): number {
	return Math.sqrt(lo * hi);
}

/** Every comparable whose bundle carries a span. Bundles without one are
 *  dropped rather than guessed at: a reference of unknown size is worse than
 *  none. */
export async function loadComparables(): Promise<SizedComparable[]> {
	const index = await fetchModelIndex().catch(() => null);
	if (!index) return [];
	const sized: SizedComparable[] = [];
	for (const comparable of COMPARABLES) {
		const bundle = index.find((e) => e.slug === comparable.slug);
		const span = bundle?.scale_meters;
		if (!span) continue;
		sized.push({
			...comparable,
			radiusKm: (span * (bundle.body_span_ratio ?? 1)) / 2000,
			flatness: bundle.span_ratios ? craftHeightRatio(bundle.span_ratios) || 1 : 1
		});
	}
	return sized.sort((a, b) => a.radiusKm - b.radiusKm);
}
