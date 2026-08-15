/** Which held arcs are a choice, and which are one crossing twice. */

import { describe, expect, it } from 'vitest';
import { listedTorchArcs, type TorchArc } from './torch-arcs';
import type { Route } from '$lib/math/travel';
import type { TorchOption } from './trip';

/** An arc as the list judges it: a name and a price. */
function arc(profile: TorchOption, totalDvKms: number): TorchArc {
	return { profile, route: { totalDvKms } as Route };
}

describe('listedTorchArcs', () => {
	it('keeps the arcs that get cheaper as the coast grows', () => {
		const kept = listedTorchArcs([
			arc('constant-thrust', 1968),
			arc('constant-thrust-balanced', 570),
			arc('constant-thrust-efficient', 245)
		]);
		expect(kept.map((a) => a.profile)).toEqual([
			'constant-thrust',
			'constant-thrust-balanced',
			'constant-thrust-efficient'
		]);
	});

	// The far end saturates when the geometry cannot absorb the coast. Two
	// presets then return one crossing under two names.
	it('drops an arc the geometry made a copy of the one before it', () => {
		const kept = listedTorchArcs([
			arc('constant-thrust', 52),
			arc('constant-thrust-balanced', 46),
			arc('constant-thrust-efficient', 46)
		]);
		expect(kept.map((a) => a.profile)).toEqual(['constant-thrust', 'constant-thrust-balanced']);
	});

	// A weak drive lands on a different root at each coast, so a longer crossing
	// is sometimes dearer.
	it('drops an arc that costs more than a quicker one', () => {
		const kept = listedTorchArcs([
			arc('constant-thrust', 52),
			arc('constant-thrust-balanced', 46),
			arc('constant-thrust-efficient', 48)
		]);
		expect(kept.map((a) => a.profile)).toEqual(['constant-thrust', 'constant-thrust-balanced']);
	});
});
