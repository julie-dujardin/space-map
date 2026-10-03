import { describe, expect, it } from 'vitest';
import { Quaternion, Vector3 } from 'three';
import { AU_SCALE } from '$lib/math/units';
import { bodyCentre, resolveAnchor, rotateByQuaternion, surfaceDirection } from './anchor';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { OrbitalSource } from '$lib/fetch/position/format';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';

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
		getBody: (id: string) => (id === 'test' ? full : undefined),
		bodies: { bodiesById: new Map([['test', full]]) }
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

describe('bodyCentre', () => {
	const JD = 2460000;
	const moonCtx = (moon: object, offset: Vec3 | null = [0, 2, 0]) => {
		const planet = { data: { id: 'planet' }, position: [5, 0, 0], placedJd: JD };
		const full = {
			position: [1, 1, 1],
			...moon,
			data: { id: 'moon', objectType: ObjectType.MOON, parentId: 'planet', ...moon }
		} as unknown as PositionedBody;
		const ctx = {
			getBody: (id: string) => ({ planet, moon: full })[id],
			chebStore: { has: () => true, positionScene: () => offset }
		} as unknown as ContextManager;
		return { ctx, moon: full };
	};

	it('places a moon the frame loop left at another date from its orbit', () => {
		const { ctx, moon } = moonCtx({});
		expect(bodyCentre(moon, ctx, JD)).toEqual([5, 2, 0]);
		// Written through, so everything else that reads the moon agrees.
		expect(moon.position).toEqual([5, 2, 0]);
	});

	it('leaves a moon the frame loop placed for this date where it is', () => {
		const { ctx, moon } = moonCtx({});
		moon.placedJd = JD;
		expect(bodyCentre(moon, ctx, JD)).toEqual([1, 1, 1]);
	});

	it('is nowhere for a moon with no orbit, before its discovery, or off its ephemeris', () => {
		const unplaceable = moonCtx({ unplaceable: true });
		expect(bodyCentre(unplaceable.moon, unplaceable.ctx, JD)).toBeNull();
		const unborn = moonCtx({ visibleFromDays: 1e6 });
		expect(bodyCentre(unborn.moon, unborn.ctx, JD)).toBeNull();
		const uncovered = moonCtx({}, null);
		expect(bodyCentre(uncovered.moon, uncovered.ctx, JD)).toBeNull();
	});

	it('is nowhere for a probe the frame loop skipped, and asks that loop to place it', () => {
		const probe = {
			data: { id: 'probe', orbitalSource: OrbitalSource.SPICE_PROBE },
			position: [1, 2, 3]
		} as unknown as PositionedBody;
		const bodies = { hostRead: new Map<string, number>(), hostReadVersion: 0 };
		const ctx = { bodies } as unknown as ContextManager;
		expect(bodyCentre(probe, ctx, JD)).toBeNull();
		expect(bodies.hostRead.has('probe')).toBe(true);
		expect(bodies.hostReadVersion).toBe(1);
		// Placed by the next frame, and still asked for while it is read.
		probe.placedJd = JD;
		expect(bodyCentre(probe, ctx, JD)).toEqual([1, 2, 3]);
		expect(bodies.hostReadVersion).toBe(1);
	});

	it('places a moon against its host where that is now, not where it was left', () => {
		const host = {
			data: {
				id: 'host',
				parentId: 'naif-0',
				a: 0,
				validityStart: -Infinity,
				validityEnd: Infinity
			},
			position: [9, 9, 9],
			positionUnknown: true
		} as unknown as PositionedBody;
		const moon = {
			data: { id: 'moon', objectType: ObjectType.MOON, parentId: 'host', a: 0 },
			position: [1, 1, 1]
		} as unknown as PositionedBody;
		const ctx = {
			getBody: (id: string) => ({ host, moon })[id],
			bodies: { bodiesById: new Map() }
		} as unknown as ContextManager;
		// The host is a dot of a point cloud: placed from its orbit, at the origin.
		expect(bodyCentre(moon, ctx, JD)).toEqual([0, 0, 0]);
	});
});
