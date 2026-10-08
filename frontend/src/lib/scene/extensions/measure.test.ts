import { describe, expect, it } from 'vitest';
import { AU_SCALE } from '$lib/math/units';
import { anchorDistanceKm, anchorOffsetKm, subsolarPoint, sunlightAt, type Ball } from './measure';
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

/** A scene that holds `bodies`, their spin records read. It places each one
 *  where its fixture says at every date, unless `place` says otherwise. */
function fakeCtx(
	bodies: Record<string, Partial<PositionedBody>>,
	place: ContextManager['place'] = (body) => body.position
): ContextManager {
	const all = new Map(
		Object.entries(bodies).map(
			([id, body]) => [id, { data: { id, radiusKm: 1000 }, ...body } as PositionedBody] as const
		)
	);
	return {
		getBody: (id: string) => all.get(id),
		place,
		bodies: { orientationRead: new Set(all.keys()) }
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

	it('measures to where the scene places a body at the date asked, not where it was left', () => {
		// The scene has the rock an AU along ecliptic +y at the later date.
		const later = JD + 91;
		const ctx = fakeCtx(
			{ 'naif-10': { position: [0, 0, 0] }, rock: { position: [9, 9, 9] } },
			(body, jd) => (body.data.id === 'rock' && jd === later ? [0, 0, -AU_SCALE] : body.position)
		);
		expect(anchorDistanceKm({ body: 'naif-10' }, { body: 'rock' }, ctx, later)).toBeCloseTo(
			AU_KM,
			3
		);
		const offset = anchorOffsetKm({ body: 'naif-10' }, { body: 'rock' }, ctx, later)!;
		expect(offset[1]).toBeCloseTo(AU_KM, 3);
	});

	it('is null at a date the scene has no place for one end', () => {
		// The rock keeps the place it was left with, and the scene answers for the date.
		const ctx = fakeCtx(
			{ 'naif-10': { position: [0, 0, 0] }, rock: { position: [1, 0, 0] } },
			(body, jd) => (body.data.id === 'rock' && jd > JD + 1 ? null : body.position)
		);
		expect(anchorDistanceKm({ body: 'naif-10' }, { body: 'rock' }, ctx, JD)).not.toBeNull();
		expect(anchorDistanceKm({ body: 'naif-10' }, { body: 'rock' }, ctx, JD + 10)).toBeNull();
	});

	it('is null while one end is not loaded', () => {
		const ctx = fakeCtx({ a: { position: [0, 0, 0] } });
		expect(anchorDistanceKm({ body: 'a' }, { body: 'gone' }, ctx, JD)).toBeNull();
	});

	it('is null while one end has no place', () => {
		const ctx = fakeCtx({ a: { position: [1, 0, 0] }, b: { position: null } });
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
		const earth = ctx.getBody('earth')!.position!;
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
		const rock = ctx.getBody('rock')!.position!;
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

	it('is null while the body or the Sun has no place', () => {
		const noRock = fakeCtx({ 'naif-10': { position: [1, 0, 0] }, rock: { position: null } });
		expect(subsolarPoint('rock', noRock, JD)).toBeNull();
		const noSun = fakeCtx({ 'naif-10': { position: null }, rock: { position: [1, 0, 0] } });
		expect(subsolarPoint('rock', noSun, JD)).toBeNull();
	});

	it('is null for the Sun itself, and for a body not loaded', () => {
		const ctx = fakeCtx({ 'naif-10': { position: [0, 0, 0] }, rock: { position: [1, 0, 0] } });
		expect(subsolarPoint('naif-10', ctx, JD)).toBeNull();
		expect(subsolarPoint('gone', ctx, JD)).toBeNull();
	});
});

describe('sunlightAt', () => {
	/** Enceladus, 238 000 km from Saturn, with the Sun along +x. */
	const SUN: Ball = { centre: [1.4e9, 0, 0], radiusKm: 695700 };
	const MOON_KM = 250;
	const saturn = (ahead: number, aside: number): Ball => ({
		centre: [ahead, aside, 0],
		radiusKm: 60000
	});

	it('is 1 when nothing is between the body and the Sun', () => {
		expect(sunlightAt(MOON_KM, SUN, [])).toBe(1);
		expect(sunlightAt(MOON_KM, SUN, [saturn(-238000, 0)])).toBe(1);
		expect(sunlightAt(MOON_KM, SUN, [saturn(0, 238000)])).toBe(1);
		expect(sunlightAt(MOON_KM, SUN, [saturn(238000, 61000)])).toBe(1);
	});

	it('is 0 when all of the body is in the umbra', () => {
		expect(sunlightAt(MOON_KM, SUN, [saturn(238000, 0)])).toBe(0);
		expect(sunlightAt(MOON_KM, SUN, [saturn(238000, 59000)])).toBe(0);
	});

	it('is a half when the edge of the shadow is on the centre of the body', () => {
		expect(sunlightAt(MOON_KM, SUN, [saturn(238000, 60000)])).toBeCloseTo(0.5, 2);
	});

	it('counts each point by the area it shows to the Sun', () => {
		// A Sun this small gives a sharp edge. Half a radius from the centre, the
		// edge cuts 19.6% off a disc.
		const small = { ...SUN, radiusKm: 7000 };
		const cut = (Math.acos(0.5) - 0.5 * Math.sqrt(0.75)) / Math.PI;
		const lit = sunlightAt(MOON_KM, small, [saturn(238000, 60000 + MOON_KM / 2)]);
		const dark = sunlightAt(MOON_KM, small, [saturn(238000, 60000 - MOON_KM / 2)]);
		expect(Math.abs(lit - (1 - cut))).toBeLessThan(0.005);
		expect(Math.abs(dark - cut)).toBeLessThan(0.005);
	});

	it('is a little less than 1 under the shadow of a small moon', () => {
		const titan: Ball = { centre: [1.2e6, 0, 0], radiusKm: 2575 };
		const lit = sunlightAt(60000, SUN, [titan]);
		expect(lit).toBeLessThan(1);
		expect(lit).toBeGreaterThan(0.99);
	});

	it('multiplies the shadows of two bodies', () => {
		const one = sunlightAt(MOON_KM, SUN, [saturn(238000, 60000)]);
		const two = sunlightAt(MOON_KM, SUN, [saturn(238000, 60000), saturn(238000, -60000)]);
		expect(two).toBeLessThan(one * one + 0.01);
		expect(two).toBeGreaterThan(0);
	});

	it('takes a body with no size as one point', () => {
		expect(sunlightAt(0, SUN, [saturn(238000, 59500)])).toBe(0);
		expect(sunlightAt(0, SUN, [saturn(238000, 60500)])).toBe(1);
	});

	it('is 1 when the Sun has no size to hide', () => {
		expect(sunlightAt(MOON_KM, { ...SUN, radiusKm: NaN }, [saturn(238000, 0)])).toBe(1);
	});
});
