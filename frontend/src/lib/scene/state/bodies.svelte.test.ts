import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { MinorBucket } from '$lib/fetch/position/minor-columns';

const BENNU = 'spkid-20101955';

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id' | 'orbitalSource'>): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.ASTEROID_INNER,
			parentId: 'naif-10',
			a: 1.126,
			e: 0.2,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 0,
			epoch: 2451545,
			radiusKm: 0,
			hasLocalized: false,
			equatorial: false,
			validityStart: -Infinity,
			validityEnd: Infinity,
			...data
		},
		position: [0, 0, 0]
	};
}

/**
 * A probe target's ephemeris spans its mission only, so the frame loop places
 * it from its catalogue elements the rest of the time, whichever of the two
 * the body was built from.
 */
describe('BodyIndex.elementRow', () => {
	function withBeltRow(): { bodies: BodyIndex; row: PositionedBody } {
		const bodies = new BodyIndex();
		const row = mkBody({ id: BENNU, orbitalSource: OrbitalSource.SBDB });
		const bucket = new MinorBucket(new Map());
		bucket.addPlaceholder(row);
		bodies.asteroidBodiesByZone.set('small_bodies/APO', bucket);
		return { bodies, row };
	}

	it('is the own data of a body built from its row', () => {
		const body = mkBody({ id: BENNU, orbitalSource: OrbitalSource.SBDB });
		expect(new BodyIndex().elementRow(body)).toBe(body.data);
	});

	it('is the row of the belt for a body built from the ephemeris', () => {
		const { bodies, row } = withBeltRow();
		const body = mkBody({ id: BENNU, orbitalSource: OrbitalSource.SPICE, parentId: 'naif-0' });
		expect(bodies.elementRow(body)).toBe(row.data);
	});

	it('is undefined for a body only the ephemeris carries', () => {
		const { bodies } = withBeltRow();
		const vesta = mkBody({ id: 'spkid-20000004', orbitalSource: OrbitalSource.SPICE });
		expect(bodies.elementRow(vesta)).toBeUndefined();
	});
});
