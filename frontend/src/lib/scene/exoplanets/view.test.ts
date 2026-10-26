import { describe, expect, it } from 'vitest';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { sphericalToCartesian } from '$lib/math/spherical';
import { AU_SCALE } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/animation/math';
import { FRAME_ELEVATION_DEG, frameDirection, orbitNormal, systemView } from './view';

/** A link frames its system from 45° above the plane, at four outer orbits. */

const dot = (a: Readonly<Vec3>, b: Readonly<Vec3>) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const unit = (v: Vec3): Vec3 => {
	const l = Math.hypot(...v);
	return [v[0] / l, v[1] / l, v[2] / l];
};

describe('orbitNormal', () => {
	it('is the angular momentum of an orbit drawn by the scene', () => {
		const el = { a: 1, e: 0, i: 37, om: 120, w: 15, ma: 0, n: 1, epoch: 2451545 };
		const p0 = orbitalElementsToPositionJD(el, 2451545)!;
		const p1 = orbitalElementsToPositionJD(el, 2451545 + 5)!;
		const h = unit([
			p0[1] * p1[2] - p0[2] * p1[1],
			p0[2] * p1[0] - p0[0] * p1[2],
			p0[0] * p1[1] - p0[1] * p1[0]
		]);
		const n = orbitNormal(37, 120);
		for (let k = 0; k < 3; k++) expect(n[k]).toBeCloseTo(h[k], 9);
	});

	it('is the ecliptic pole for an orbit in the ecliptic', () => {
		const [x, y, z] = orbitNormal(0, 75);
		expect([x, y, z].map((v) => +v.toFixed(12))).toEqual([0, 1, 0]);
	});
});

describe('frameDirection', () => {
	const host: Vec3 = [3e6, -1e6, 2e6];
	const toSun = unit([-host[0], -host[1], -host[2]]);

	it.each([
		['edge-on', orbitNormal(90, 30)],
		['tilted', orbitNormal(40, 200)],
		['retrograde', orbitNormal(150, 300)]
	])('stands %s orbits 45° over their plane, on the side of the Sun', (_, normal) => {
		const d = frameDirection(host, normal, FRAME_ELEVATION_DEG);
		expect(Math.hypot(...d)).toBeCloseTo(1, 12);
		expect(Math.abs(dot(d, normal))).toBeCloseTo(Math.SQRT1_2, 12);
		// Toward the Sun along the plane, and on its side of the plane.
		const inPlane: Vec3 = [
			d[0] - dot(d, normal) * normal[0],
			d[1] - dot(d, normal) * normal[1],
			d[2] - dot(d, normal) * normal[2]
		];
		expect(dot(inPlane, toSun)).toBeGreaterThan(0);
		expect(Math.sign(dot(d, normal))).toBe(Math.sign(dot(toSun, normal)) || 1);
	});

	it('turns a plane face-on to the Sun to the side, still 45° up', () => {
		const normal = unit([-host[0], -host[1], -host[2]]);
		const d = frameDirection(host, normal, FRAME_ELEVATION_DEG);
		expect(dot(d, normal)).toBeCloseTo(Math.SQRT1_2, 12);
		expect(Math.hypot(...d)).toBeCloseTo(1, 12);
	});
});

describe('systemView', () => {
	it('puts the camera four outer orbits off, in scene axes', () => {
		const host: Vec3 = [-1e6, 2e5, 3e6];
		const normal = orbitNormal(70, 10);
		const view = systemView(host, normal, 1.5);
		expect(view.distance).toBeCloseTo(4 * 1.5 * AU_SCALE, 12);
		const at = sphericalToCartesian([0, 0, 0], view.latitude, view.longitude, 1);
		const d = frameDirection(host, normal, FRAME_ELEVATION_DEG);
		for (let k = 0; k < 3; k++) expect(at[k]).toBeCloseTo(d[k], 9);
	});
});
