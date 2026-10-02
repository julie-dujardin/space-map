import { describe, expect, it } from 'vitest';
import { AU_SCALE } from '$lib/math/units';
import { anchorDistanceKm, anchorOffsetKm, directionToLonLat, subsolarPoint } from './measure';
import { resolveAnchor, surfaceDirection } from './anchor';
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

function fakeCtx(bodies: Record<string, Partial<PositionedBody>>): ContextManager {
	const full = Object.fromEntries(
		Object.entries(bodies).map(([id, body]) => [id, { data: { id, radiusKm: 1000 }, ...body }])
	);
	return { getBody: (id: string) => full[id] } as unknown as ContextManager;
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

	it('is null while one end is not loaded', () => {
		const ctx = fakeCtx({ a: { position: [0, 0, 0] } });
		expect(anchorDistanceKm({ body: 'a' }, { body: 'gone' }, ctx, JD)).toBeNull();
	});
});

describe('directionToLonLat', () => {
	it('undoes the direction a surface anchor is placed along', () => {
		for (const [lat, lon] of [
			[0, 0],
			[37, 122],
			[-64, -170],
			[89, 10]
		]) {
			const at = directionToLonLat(...surfaceDirection(lat, lon));
			expect(at.lat).toBeCloseTo(lat, 9);
			expect(at.lon).toBeCloseTo(lon, 9);
		}
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

	it('is null for the Sun itself, and for a body not loaded', () => {
		const ctx = fakeCtx({ 'naif-10': { position: [0, 0, 0] }, rock: { position: [1, 0, 0] } });
		expect(subsolarPoint('naif-10', ctx, JD)).toBeNull();
		expect(subsolarPoint('gone', ctx, JD)).toBeNull();
	});
});
