/**
 * A trip end is any object in the catalogue, most of them nowhere near what the
 * scene is drawing — so the resolver has to reach past it, and has to keep
 * reaching all the way up to the orbit a transfer is actually flown between.
 */

import { describe, expect, it, vi } from 'vitest';
import { ObjectType, type BodyData } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';

/** Bundles the fake catalogue can serve, keyed by object id. */
const bundles = new Map<string, { parent: string; a: number }>();

vi.mock('$lib/fetch/objects/object-data', () => ({
	fetchObjectDetail: (id: string) => {
		const entry = bundles.get(id);
		if (!entry) return Promise.reject(new Error(`no bundle for ${id}`));
		return Promise.resolve({
			global: {
				type: 'asteroid',
				orbit: {
					epoch_jd: 2451545,
					e: 0.1,
					i: 1,
					om: 2,
					w: 3,
					ma: 4,
					n: 0.2,
					a: entry.a,
					scale: 'sun',
					parent_id: entry.parent,
					source: 'sbdb'
				}
			},
			localized: null
		});
	}
}));

const { resolveTripBodies } = await import('./resolve');

function residentBody(id: string, parentId: string): BodyData {
	return {
		id,
		name: id,
		hasLocalized: false,
		objectType: ObjectType.PLANET,
		parentId,
		radiusKm: 1000,
		a: 9,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 1,
		epoch: 2451545,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.SPICE
	};
}

describe('resolveTripBodies', () => {
	it('reads a body the scene never loaded out of its bundle', async () => {
		bundles.set('spkid-1', { parent: 'naif-10', a: 2.77 });
		const bodies = await resolveTripBodies(['spkid-1'], () => undefined);
		expect(bodies.get('spkid-1')!.a).toBe(2.77);
	});

	it('prefers what the scene already holds', async () => {
		bundles.set('spkid-2', { parent: 'naif-10', a: 2.77 });
		const resident = residentBody('spkid-2', 'naif-10');
		const bodies = await resolveTripBodies(['spkid-2'], (id) =>
			id === 'spkid-2' ? resident : undefined
		);
		expect(bodies.get('spkid-2')).toBe(resident);
	});

	it('walks up to the heliocentric orbit, pulling in the links on the way', async () => {
		// A moon of an asteroid: neither it nor its host orbits the Sun directly.
		bundles.set('spkid-3-moon', { parent: 'spkid-3', a: 0.00001 });
		bundles.set('spkid-3', { parent: 'naif-10', a: 3.1 });
		const bodies = await resolveTripBodies(['spkid-3-moon'], () => undefined);
		expect([...bodies.keys()].sort()).toEqual(['spkid-3', 'spkid-3-moon']);
	});

	it('shares the chain between both ends of a trip', async () => {
		bundles.set('spkid-4a', { parent: 'spkid-4host', a: 0.00002 });
		bundles.set('spkid-4b', { parent: 'spkid-4host', a: 0.00003 });
		bundles.set('spkid-4host', { parent: 'naif-10', a: 5.2 });
		const bodies = await resolveTripBodies(['spkid-4a', 'spkid-4b'], () => undefined);
		expect(bodies.size).toBe(3);
	});

	it('leaves out an end whose chain cannot be closed', async () => {
		bundles.set('spkid-5', { parent: 'spkid-5-missing', a: 1 });
		const bodies = await resolveTripBodies(['spkid-5'], () => undefined);
		// The end itself resolved, but with no heliocentric ancestor above it the
		// panel has nothing to price — that is the caller's read, not ours.
		expect(bodies.has('spkid-5-missing')).toBe(false);
	});

	it('returns nothing for an object with no bundle at all', async () => {
		const bodies = await resolveTripBodies(['spkid-nonexistent'], () => undefined);
		expect(bodies.size).toBe(0);
	});
});
