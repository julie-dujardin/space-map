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

/**
 * The scene holds one object per id: the renderer and the drawer refer to it.
 * A row a loader reads for an object the scene holds refreshes that object.
 */
describe('BodyIndex.putSpacecraft', () => {
	const MIR = 'norad_satcat-16609';
	const sat = (data: Partial<BodyData> = {}) =>
		mkBody({ id: MIR, orbitalSource: OrbitalSource.SPACETRACK, parentId: 'naif-399', ...data });

	it('adds a new row to the bucket of its parent', () => {
		const bodies = new BodyIndex();
		const row = sat();
		expect(bodies.putSpacecraft(row)).toBe(true);
		expect(bodies.getBody(MIR)).toBe(row);
	});

	it('turns a page-only stand-in into the object, and keeps the object', () => {
		const bodies = new BodyIndex();
		const standIn = sat({ pageOnly: true, parentId: '', a: NaN });
		bodies.addBodies([standIn]);
		const row = sat({ a: 4.5e-5 });
		expect(bodies.putSpacecraft(row)).toBe(false);
		expect(bodies.getBody(MIR)).toBe(standIn);
		expect(standIn.data).toBe(row.data);
		expect(bodies.bodiesById.has(MIR)).toBe(false);
		expect(bodies.spacecraftByParent.get('naif-399')?.get(MIR)).toBe(standIn);
	});

	it('refreshes a row from another snapshot in place', () => {
		const bodies = new BodyIndex();
		const first = sat({ epoch: 1 });
		bodies.putSpacecraft(first);
		const second = sat({ epoch: 2 });
		expect(bodies.putSpacecraft(second)).toBe(false);
		expect(bodies.getBody(MIR)).toBe(first);
		expect(first.data.epoch).toBe(2);
	});

	it('tells the position pass that data arrived', () => {
		const bodies = new BodyIndex();
		const before = bodies.dataVersion;
		bodies.putSpacecraft(sat());
		expect(bodies.dataVersion).toBeGreaterThan(before);
	});
});

describe('BodyIndex.addBodies', () => {
	it('refreshes a body it holds in place', () => {
		const bodies = new BodyIndex();
		const held = mkBody({ id: 'naif-301', orbitalSource: OrbitalSource.SPICE, epoch: 1 });
		bodies.addBodies([held]);
		bodies.addBodies([mkBody({ id: 'naif-301', orbitalSource: OrbitalSource.SPICE, epoch: 2 })]);
		expect(bodies.getBody('naif-301')).toBe(held);
		expect(held.data.epoch).toBe(2);
	});
});

describe('BodyIndex, the stars and planets of other systems', () => {
	const star = (n: number) =>
		mkBody({
			id: `x-${2 ** 24 + n}`,
			orbitalSource: OrbitalSource.UNKNOWN,
			objectType: ObjectType.EXTRASOLAR
		});

	it('keeps a pinned star past the LRU of a few dozen', () => {
		const bodies = new BodyIndex();
		bodies.addExtrasolar(star(0));
		bodies.pinExtrasolar(new Set([star(0).data.id]));
		for (let n = 1; n <= 100; n++) bodies.addExtrasolar(star(n));
		expect(bodies.getBody(star(0).data.id)).toBeDefined();
		expect(bodies.getBody(star(1).data.id)).toBeUndefined();
		expect(bodies.getBody(star(100).data.id)).toBeDefined();
		bodies.pinExtrasolar(new Set());
		bodies.addExtrasolar(star(101));
		expect(bodies.getBody(star(0).data.id)).toBeUndefined();
	});

	it('holds planets apart from bodiesById, and refreshes one it holds', () => {
		const bodies = new BodyIndex();
		const planet = mkBody({
			id: 'x-27424668-b-1',
			orbitalSource: OrbitalSource.UNKNOWN,
			objectType: ObjectType.EXOPLANET,
			parentId: 'x-27424668'
		});
		bodies.addExoplanets([planet]);
		expect(bodies.getBody(planet.data.id)).toBe(planet);
		expect(bodies.bodiesById.has(planet.data.id)).toBe(false);
		const fresh = { ...planet, data: { ...planet.data, a: 0.05 } };
		bodies.addExoplanets([fresh]);
		expect(bodies.getBody(planet.data.id)).toBe(planet);
		expect(planet.data.a).toBe(0.05);
		bodies.dropExoplanets([planet.data.id]);
		expect(bodies.getBody(planet.data.id)).toBeUndefined();
	});
});
