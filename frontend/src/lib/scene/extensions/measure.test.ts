import { describe, expect, it } from 'vitest';
import { AU_SCALE } from '$lib/math/units';
import { anchorDistanceKm, anchorOffsetKm, subsolarPoint } from './measure';
import { resolveAnchor } from './anchor';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';

const AU_KM = 149597870.7;
const JD = 2461300.5;

const EARTH_SPIN = {
	pole_ra_0: 0,
	pole_ra_1: -0.641,
	pole_dec_0: 90,
	pole_dec_1: -0.557,
	w0: 190.147,
	w1: 360.9856235,
	w2: 0
};

/** Bodies the frame loop placed for {@link JD}, their spin records read, and
 *  `cloud` ones: dots of a point cloud, which that loop does not place. */
function fakeCtx(
	bodies: Record<string, Partial<PositionedBody>>,
	cloud: Record<string, Partial<PositionedBody>> = {}
): ContextManager {
	const make = (entries: Record<string, Partial<PositionedBody>>, placed: object) =>
		Object.entries(entries).map(
			([id, body]) => [id, { data: { id, radiusKm: 1000 }, ...placed, ...body }] as const
		);
	const full = new Map(make(bodies, { placedJd: JD }) as [string, PositionedBody][]);
	const all = new Map([...full, ...(make(cloud, {}) as [string, PositionedBody][])]);
	return {
		getBody: (id: string) => all.get(id),
		bodies: { bodiesById: full, orientationRead: new Set(all.keys()) }
	} as unknown as ContextManager;
}

describe('anchorDistanceKm', () => {
	it('measures between two bodies in kilometres', () => {
		const ctx = fakeCtx({ a: { position: [0, 0, 0] }, b: { position: [AU_SCALE, 0, 0] } });
		expect(anchorDistanceKm({ body: 'a' }, { body: 'b' }, ctx, JD)).toBeCloseTo(AU_KM, 3);
	});

	it('measures from a place on a surface, not from the centre under it', () => {
		const ctx = fakeCtx({ a: { position: [0, 0, 0] } });
		const pole = { body: 'a', latitude: 90, longitude: 0 };
		expect(anchorDistanceKm(pole, { body: 'a' }, ctx, JD)).toBeCloseTo(1000, 6);
	});

	it('keeps the direction on ecliptic axes when asked for the offset', () => {
		// Scene +y is ecliptic +z, and scene −z is ecliptic +y.
		const ctx = fakeCtx({ a: { position: [0, 0, 0] }, b: { position: [0, AU_SCALE, -AU_SCALE] } });
		const offset = anchorOffsetKm({ body: 'a' }, { body: 'b' }, ctx, JD)!;
		expect(offset[0]).toBeCloseTo(0, 3);
		expect(offset[1]).toBeCloseTo(AU_KM, 3);
		expect(offset[2]).toBeCloseTo(AU_KM, 3);
	});

	it('places a dot of the belt from its orbit, not where it was loaded', () => {
		// A circular orbit of 1 AU, a quarter of the way round from where it
		// starts, ninety-one days on.
		const data = {
			id: 'rock',
			radiusKm: 1,
			parentId: 'naif-0',
			a: 1,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 360 / 365.25,
			epoch: JD,
			validityStart: 0,
			validityEnd: Infinity
		};
		const ctx = fakeCtx(
			{ 'naif-10': { position: [0, 0, 0] } },
			{ rock: { data, position: [9, 9, 9] } as unknown as PositionedBody }
		);
		const later = JD + 365.25 / 4;
		expect(anchorDistanceKm({ body: 'naif-10' }, { body: 'rock' }, ctx, later)).toBeCloseTo(
			AU_KM,
			-3
		);
		const offset = anchorOffsetKm({ body: 'naif-10' }, { body: 'rock' }, ctx, later)!;
		expect(Math.abs(offset[1])).toBeCloseTo(AU_KM, -3);
	});

	it('is null for a dot whose orbit does not reach the date', () => {
		const data = {
			id: 'rock',
			parentId: 'naif-0',
			a: 1,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 1,
			epoch: JD,
			validityStart: JD,
			validityEnd: JD + 1
		};
		const ctx = fakeCtx(
			{ 'naif-10': { position: [0, 0, 0] } },
			{ rock: { data, position: [1, 0, 0] } as unknown as PositionedBody }
		);
		expect(anchorDistanceKm({ body: 'naif-10' }, { body: 'rock' }, ctx, JD + 10)).toBeNull();
	});

	it('is null while one end is not loaded', () => {
		const ctx = fakeCtx({ a: { position: [0, 0, 0] } });
		expect(anchorDistanceKm({ body: 'a' }, { body: 'gone' }, ctx, JD)).toBeNull();
	});

	it('is null while one end is a stand-in position', () => {
		const ctx = fakeCtx({
			a: { position: [1, 0, 0] },
			b: { position: [0, 0, 0], positionUnknown: true }
		});
		expect(anchorDistanceKm({ body: 'a' }, { body: 'b' }, ctx, JD)).toBeNull();
	});
});

describe('subsolarPoint', () => {
	it('names the place whose zenith is the Sun', () => {
		const ctx = fakeCtx({
			'naif-10': { position: [0, 0, 0] },
			earth: { position: [0.6 * AU_SCALE, 0.01 * AU_SCALE, -0.8 * AU_SCALE] } as never
		});
		(ctx.getBody('earth') as { orientation: unknown }).orientation = EARTH_SPIN;
		const noon = subsolarPoint('earth', ctx, JD)!;
		const earth = ctx.getBody('earth')!.position;
		const up = resolveAnchor({ body: 'earth', latitude: noon.lat, longitude: noon.lon }, ctx, JD)!;
		const zenith = up.map((v, i) => v - earth[i]);
		const toSun = earth.map((v) => -v);
		const cosine =
			zenith.reduce((sum, v, i) => sum + v * toSun[i], 0) /
			(Math.hypot(...zenith) * Math.hypot(...toSun));
		expect(cosine).toBeCloseTo(1, 9);
		// The Sun never stands outside the tropics.
		expect(Math.abs(noon.lat)).toBeLessThan(23.5);
	});

	it('answers in the frame an anchor falls back to, for a body with no measured spin', () => {
		const ctx = fakeCtx({
			'naif-10': { position: [0, 0, 0] },
			rock: { position: [0.3, -0.2, 0.9] }
		});
		const noon = subsolarPoint('rock', ctx, JD)!;
		const rock = ctx.getBody('rock')!.position;
		const up = resolveAnchor({ body: 'rock', latitude: noon.lat, longitude: noon.lon }, ctx, JD)!;
		const zenith = up.map((v, i) => v - rock[i]);
		const cosine =
			-zenith.reduce((sum, v, i) => sum + v * rock[i], 0) /
			(Math.hypot(...zenith) * Math.hypot(...rock));
		expect(cosine).toBeCloseTo(1, 9);
	});

	it('is null until the spin of the body has been read', () => {
		const ctx = fakeCtx({ 'naif-10': { position: [0, 0, 0] }, rock: { position: [1, 0, 0] } });
		ctx.bodies.orientationRead.delete('rock');
		expect(subsolarPoint('rock', ctx, JD)).toBeNull();
		ctx.bodies.orientationRead.add('rock');
		expect(subsolarPoint('rock', ctx, JD)).not.toBeNull();
	});

	it('is null for a body at a stand-in position', () => {
		const ctx = fakeCtx({
			'naif-10': { position: [1, 0, 0] },
			rock: { position: [0, 0, 0], positionUnknown: true }
		});
		expect(subsolarPoint('rock', ctx, JD)).toBeNull();
	});

	it('is null for the Sun itself, and for a body not loaded', () => {
		const ctx = fakeCtx({ 'naif-10': { position: [0, 0, 0] }, rock: { position: [1, 0, 0] } });
		expect(subsolarPoint('naif-10', ctx, JD)).toBeNull();
		expect(subsolarPoint('gone', ctx, JD)).toBeNull();
	});
});
