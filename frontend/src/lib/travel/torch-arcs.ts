/**
 * The held arcs on offer, and which of them are worth listing.
 *
 * A brachistochrone has no launch window. Coasting between the burns trades Δv
 * for time, which is the same choice a window offers. So it is offered the same
 * way: named points on the coast span, plus a slider for the rest of it.
 */

import type { Route } from '$lib/math/travel';
import type { TorchOption } from './trip';

export interface TorchArc {
	profile: TorchOption;
	route: Route;
}

/** One named point on the coast span. */
export interface TorchPreset {
	profile: TorchOption;
	coastFraction: number;
}

/** Δv falls along the whole span, so the cheapest arc is the far end. Balanced
 *  sits at a quarter because the trade is steep near zero and flat after. */
export const TORCH_PRESETS: readonly TorchPreset[] = [
	{ profile: 'constant-thrust', coastFraction: 0 },
	{ profile: 'constant-thrust-balanced', coastFraction: 0.25 },
	{ profile: 'constant-thrust-efficient', coastFraction: 1 }
];

/** How much cheaper a longer crossing must be to get a row of its own. */
const WORTH_LISTING = 0.02;

/** Drop the arcs that aren't a choice, keeping the given coast order. The
 *  solver shortens a coast the geometry can't absorb, so two presets can
 *  return one crossing; a weak drive can also make a longer crossing dearer.
 *  Both fail the same test. */
export function listedTorchArcs(arcs: readonly TorchArc[]): TorchArc[] {
	const kept: TorchArc[] = [];
	let cheapest = Infinity;
	for (const arc of arcs) {
		if (arc.route.totalDvKms > cheapest * (1 - WORTH_LISTING)) continue;
		cheapest = arc.route.totalDvKms;
		kept.push(arc);
	}
	return kept;
}
