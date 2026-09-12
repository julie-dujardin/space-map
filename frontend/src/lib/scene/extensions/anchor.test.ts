import { describe, expect, it } from 'vitest';
import { Quaternion, Vector3 } from 'three';
import { AU_SCALE } from '$lib/math/units';
import { resolveAnchor, rotateByQuaternion, surfaceDirection } from './anchor';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';

const AU_KM = 149597870.7;

/** A body at a known place, with a measured radius and no orientation data —
 *  the surface path then falls back to the unrotated sphere. */
function fakeCtx(
	body: Partial<PositionedBody> & { position: [number, number, number] }
): ContextManager {
	const full = {
		data: { id: 'test', radiusKm: 1000 },
		...body
	} as unknown as PositionedBody;
	return {
		getBody: (id: string) => (id === 'test' ? full : undefined)
	} as unknown as ContextManager;
}

describe('resolveAnchor', () => {
	it('is the body itself without an offset', () => {
		const ctx = fakeCtx({ position: [1, 2, 3] });
		expect(resolveAnchor({ body: 'test' }, ctx, 2460000)).toEqual([1, 2, 3]);
	});

	it('is null while the body is not loaded', () => {
		const ctx = fakeCtx({ position: [0, 0, 0] });
		expect(resolveAnchor({ body: 'elsewhere' }, ctx, 2460000)).toBeNull();
	});

	it('turns an ecliptic offset in km into the scene axes', () => {
		const ctx = fakeCtx({ position: [0, 0, 0] });
		const oneAu = resolveAnchor({ body: 'test', offsetKm: [AU_KM, 0, 0] }, ctx, 2460000);
		expect(oneAu?.[0]).toBeCloseTo(AU_SCALE, 6);
		// Ecliptic +z is scene +y, and ecliptic +y is scene −z.
		const north = resolveAnchor({ body: 'test', offsetKm: [0, 0, AU_KM] }, ctx, 2460000);
		expect(north?.[1]).toBeCloseTo(AU_SCALE, 6);
		const along = resolveAnchor({ body: 'test', offsetKm: [0, AU_KM, 0] }, ctx, 2460000);
		expect(along?.[2]).toBeCloseTo(-AU_SCALE, 6);
	});

	it('reads a time-dependent offset at the date of the frame', () => {
		const ctx = fakeCtx({ position: [0, 0, 0] });
		const anchor = { body: 'test', offsetKm: (jd: number) => [jd - 2460000, 0, 0] as const };
		expect(resolveAnchor(anchor, ctx, 2460001)?.[0]).toBeCloseTo(AU_SCALE / AU_KM, 12);
	});

	it('puts a surface anchor one radius out, and altitude above that', () => {
		const ctx = fakeCtx({ position: [0, 0, 0] });
		const surface = resolveAnchor({ body: 'test', latitude: 0, longitude: 0 }, ctx, 2460000)!;
		expect(Math.hypot(...surface)).toBeCloseTo((1000 * AU_SCALE) / AU_KM, 12);
		const up = resolveAnchor(
			{ body: 'test', latitude: 0, longitude: 0, altitudeKm: 1000 },
			ctx,
			2460000
		)!;
		expect(Math.hypot(...up)).toBeCloseTo((2000 * AU_SCALE) / AU_KM, 12);
	});

	it('sends the north pole to scene +y and the prime meridian to +x', () => {
		const ctx = fakeCtx({ position: [0, 0, 0] });
		const scale = (1000 * AU_SCALE) / AU_KM;
		const pole = resolveAnchor({ body: 'test', latitude: 90, longitude: 0 }, ctx, 2460000)!;
		expect(pole[1]).toBeCloseTo(scale, 12);
		const meridian = resolveAnchor({ body: 'test', latitude: 0, longitude: 0 }, ctx, 2460000)!;
		expect(meridian[0]).toBeCloseTo(scale, 12);
	});
});

describe('surfaceDirection', () => {
	it('is a unit vector for any place', () => {
		for (const [lat, lon] of [
			[0, 0],
			[45, 30],
			[-60, 200],
			[90, 0]
		]) {
			expect(Math.hypot(...surfaceDirection(lat, lon))).toBeCloseTo(1, 12);
		}
	});

	it('sends longitude east, away from scene +z', () => {
		const east = surfaceDirection(0, 90);
		expect(east[0]).toBeCloseTo(0, 12);
		expect(east[2]).toBeCloseTo(-1, 12);
	});
});

describe('rotateByQuaternion', () => {
	it('turns a vector the way three does', () => {
		const q = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 3);
		const expected = new Vector3(1, 2, 3).applyQuaternion(q);
		const out = [0, 0, 0];
		rotateByQuaternion(q, 1, 2, 3, out, 0);
		expect(out[0]).toBeCloseTo(expected.x, 12);
		expect(out[1]).toBeCloseTo(expected.y, 12);
		expect(out[2]).toBeCloseTo(expected.z, 12);
	});

	it('writes where it is told to', () => {
		const out = new Float64Array(6);
		rotateByQuaternion(new Quaternion(), 1, 2, 3, out, 3);
		expect([...out]).toEqual([0, 0, 0, 1, 2, 3]);
	});
});
