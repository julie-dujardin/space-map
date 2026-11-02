import { describe, it, expect } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { elementsToState, eclipticToScene } from './state';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { dot, norm } from './vec3';

const RAD2DEG = 180 / Math.PI;
const J2000 = 2451545.0;

/** Mean motion (deg/day) for a heliocentric semi-major axis in AU. */
function meanMotion(aAu: number): number {
	const aKm = aAu * AU_KM;
	return Math.sqrt(GM_SUN_KM3_S2 / (aKm * aKm * aKm)) * RAD2DEG * SEC_PER_DAY;
}

function heliocentric(aAu: number, e: number, i = 0, om = 0, w = 0, ma = 0): OrbitalElements {
	return { a: aAu, e, i, om, w, ma, n: meanMotion(aAu), epoch: J2000 };
}

describe('elementsToState', () => {
	it('puts a circular 1 AU orbit at 1 AU moving at 29.78 km/s', () => {
		const s = elementsToState(heliocentric(1, 0), J2000)!;
		expect(s).not.toBeNull();
		expect(norm(s.r) / AU_KM).toBeCloseTo(1, 9);
		expect(norm(s.v)).toBeCloseTo(29.784, 2);
	});

	it('keeps velocity perpendicular to radius on a circular orbit', () => {
		const s = elementsToState(heliocentric(1, 0, 15, 40, 0, 123), J2000)!;
		expect(dot(s.r, s.v) / (norm(s.r) * norm(s.v))).toBeCloseTo(0, 12);
	});

	it('satisfies vis-viva on an eccentric orbit', () => {
		const el = heliocentric(2.7, 0.35, 10, 80, 70, 200);
		for (const jd of [J2000, J2000 + 300, J2000 + 900]) {
			const s = elementsToState(el, jd)!;
			const expected = GM_SUN_KM3_S2 * (2 / norm(s.r) - 1 / (el.a * AU_KM));
			expect(dot(s.v, s.v)).toBeCloseTo(expected, 3);
		}
	});

	it('conserves energy and angular momentum along an orbit', () => {
		const el = heliocentric(1.8, 0.6, 25, 130, 200, 15);
		const samples = [0, 120, 240, 360, 500].map((d) => elementsToState(el, J2000 + d)!);
		const energy = (i: number) =>
			dot(samples[i].v, samples[i].v) / 2 - GM_SUN_KM3_S2 / norm(samples[i].r);
		for (let i = 1; i < samples.length; i++) {
			expect(energy(i) / energy(0)).toBeCloseTo(1, 6);
		}
	});

	it('conserves the angular momentum vector, not just its magnitude', () => {
		const el = heliocentric(1.8, 0.6, 25, 130, 200, 15);
		const h = (jd: number) => {
			const s = elementsToState(el, jd)!;
			return [
				s.r[1] * s.v[2] - s.r[2] * s.v[1],
				s.r[2] * s.v[0] - s.r[0] * s.v[2],
				s.r[0] * s.v[1] - s.r[1] * s.v[0]
			] as const;
		};
		const h0 = h(J2000);
		const h1 = h(J2000 + 400);
		for (let k = 0; k < 3; k++) expect(h1[k] / h0[k]).toBeCloseTo(1, 6);
	});

	it('agrees with the renderer position after the scene transform', () => {
		const el = heliocentric(1.52, 0.093, 1.85, 49.6, 286.5, 19.4);
		const jd = J2000 + 1234;
		const scene = eclipticToScene(elementsToState(el, jd)!.r);
		const expected = orbitalElementsToPositionJD(el, jd)!;
		for (let k = 0; k < 3; k++) expect(scene[k]).toBeCloseTo(expected[k], 6);
	});

	it('rotates equatorial (TLE-frame) elements onto the ecliptic', () => {
		const muEarth = 3.986004418e5;
		const aKm = 7000;
		const n = Math.sqrt(muEarth / aKm ** 3) * RAD2DEG * SEC_PER_DAY;
		const el: OrbitalElements = {
			a: aKm / AU_KM,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 30,
			n,
			epoch: J2000,
			equatorial: true
		};
		const s = elementsToState(el, J2000)!;
		expect(norm(s.r)).toBeCloseTo(aKm, 6);
		expect(norm(s.v)).toBeCloseTo(Math.sqrt(muEarth / aKm), 9);

		// An orbit in Earth's equatorial plane sits at the obliquity to the ecliptic.
		const h: [number, number, number] = [
			s.r[1] * s.v[2] - s.r[2] * s.v[1],
			s.r[2] * s.v[0] - s.r[0] * s.v[2],
			s.r[0] * s.v[1] - s.r[1] * s.v[0]
		];
		expect(Math.acos(h[2] / norm(h)) * RAD2DEG).toBeCloseTo(23.4392911, 6);
	});

	it('reads μ from the mean motion and the semi-major axis', () => {
		expect(elementsToState(heliocentric(1, 0), J2000)!.mu / GM_SUN_KM3_S2).toBeCloseTo(1, 12);
	});

	it('gives the speed of the drawn motion, whatever the mass of the star', () => {
		// 55 Cnc e: its period gives 0.905 solar masses, and the catalogue star has 1.015.
		const periodDays = 0.736547;
		const aAu = 0.01544;
		const el = { ...heliocentric(aAu, 0), n: 360 / periodDays };
		const drawn = (2 * Math.PI * aAu * AU_KM) / (periodDays * SEC_PER_DAY);
		expect(norm(elementsToState(el, J2000)!.v)).toBeCloseTo(drawn, 9);
	});

	it('flies a parabola on the Sun', () => {
		const comet = { ...heliocentric(1, 0), a: 0, n: 0, e: 1, q: 1, tp: J2000 };
		const s = elementsToState(comet, J2000)!;
		expect(s.mu).toBe(GM_SUN_KM3_S2);
		expect(norm(s.r) / AU_KM).toBeCloseTo(1, 7);
		expect(norm(s.v)).toBeCloseTo(Math.sqrt((2 * GM_SUN_KM3_S2) / AU_KM), 4);
	});

	it('returns finite state on a hyperbolic orbit', () => {
		const el: OrbitalElements = {
			a: -3.5,
			e: 1.2,
			i: 22,
			om: 40,
			w: 100,
			ma: 5,
			n: 0.02,
			epoch: J2000
		};
		const s = elementsToState(el, J2000 + 50);
		expect(s).not.toBeNull();
		expect(isFinite(norm(s!.r))).toBe(true);
		expect(isFinite(norm(s!.v))).toBe(true);
	});

	it('rejects unusable elements', () => {
		expect(elementsToState({ ...heliocentric(1, 0), a: NaN, n: NaN }, J2000)).toBeNull();
	});
});
