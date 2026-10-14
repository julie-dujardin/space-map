import { describe, it, expect } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { elementsToState } from './state';
import { solveLambert, transferArc, type LambertArc } from './lambert';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { cross, norm, scale, sub, type Vec3 } from './vec3';

const RAD2DEG = 180 / Math.PI;
const J2000 = 2451545.0;

function meanMotion(aAu: number): number {
	const aKm = aAu * AU_KM;
	return Math.sqrt(GM_SUN_KM3_S2 / (aKm * aKm * aKm)) * RAD2DEG * SEC_PER_DAY;
}

function heliocentric(aAu: number, e: number, i = 0, om = 0, w = 0, ma = 0): OrbitalElements {
	return { a: aAu, e, i, om, w, ma, n: meanMotion(aAu), epoch: J2000 };
}

/**
 * The core correctness check: sample two states off a known orbit and require
 * Lambert to recover the very velocities that orbit had. Any error in the
 * solver, the frame, or the units shows up here.
 */
function expectRecoversOrbit(el: OrbitalElements, jd1: number, jd2: number, digits = 6) {
	const s1 = elementsToState(el, jd1, GM_SUN_KM3_S2)!;
	const s2 = elementsToState(el, jd2, GM_SUN_KM3_S2)!;
	const normal = cross(s1.r, s1.v);
	const arc = solveLambert(s1.r, s2.r, (jd2 - jd1) * SEC_PER_DAY, GM_SUN_KM3_S2, normal)!;
	expect(arc).not.toBeNull();
	expect(norm(sub(arc.v1, s1.v)) / norm(s1.v)).toBeCloseTo(0, digits);
	expect(norm(sub(arc.v2, s2.v)) / norm(s2.v)).toBeCloseTo(0, digits);
}

describe('solveLambert', () => {
	it('recovers the velocities of a circular orbit', () => {
		expectRecoversOrbit(heliocentric(1, 0), J2000, J2000 + 80);
	});

	it('recovers an eccentric inclined orbit across a short arc', () => {
		expectRecoversOrbit(heliocentric(1.9, 0.42, 18, 75, 250, 30), J2000, J2000 + 60);
	});

	it('recovers an arc spanning more than half a revolution', () => {
		// Transfer angle > π flips the sign of lambda; this is the branch that
		// silently produces a mirrored orbit if ih is handled wrongly.
		expectRecoversOrbit(heliocentric(1.3, 0.25, 12, 200, 45, 0), J2000, J2000 + 350);
	});

	it('recovers a high-eccentricity comet-like arc', () => {
		expectRecoversOrbit(heliocentric(3.4, 0.85, 60, 15, 320, 350), J2000 + 10, J2000 + 200, 5);
	});

	it('recovers a retrograde orbit round its own normal', () => {
		expectRecoversOrbit(heliocentric(1.5, 0.2, 165, 30, 60, 0), J2000, J2000 + 120);
	});

	it('recovers an orbit tipped just past 90°, as the moons of Uranus are', () => {
		expectRecoversOrbit(heliocentric(1.2, 0.01, 97.8, 167.6, 40, 0), J2000, J2000 + 90);
	});

	it('returns the wrong arc for retrograde motion under the ecliptic-north default', () => {
		// Geometry alone cannot tell which way round the transfer goes, so a
		// retrograde orbit needs the caller to give its normal.
		const el = heliocentric(1.5, 0.2, 165, 30, 60, 0);
		const s1 = elementsToState(el, J2000, GM_SUN_KM3_S2)!;
		const s2 = elementsToState(el, J2000 + 120, GM_SUN_KM3_S2)!;
		const arc = solveLambert(s1.r, s2.r, 120 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		expect(norm(sub(arc.v1, s1.v)) / norm(s1.v)).toBeGreaterThan(0.1);
	});

	it('recovers a near-parabolic arc where the Battin series takes over', () => {
		expectRecoversOrbit(heliocentric(50, 0.98, 5, 0, 0, 0.4), J2000, J2000 + 900, 4);
	});

	it('matches the analytic Hohmann Δv between circular orbits', () => {
		const r1 = AU_KM;
		const r2 = 1.523679 * AU_KM;
		const aT = (r1 + r2) / 2;
		const mu = GM_SUN_KM3_S2;

		const dv1 = Math.sqrt(mu / r1) * (Math.sqrt((2 * r2) / (r1 + r2)) - 1);
		const dv2 = Math.sqrt(mu / r2) * (1 - Math.sqrt((2 * r1) / (r1 + r2)));
		const tof = Math.PI * Math.sqrt(aT ** 3 / mu);

		// An exact 180° transfer leaves the plane undefined, so nudge the arrival
		// just short of antipodal and accept a correspondingly small mismatch.
		const angle = Math.PI * 0.998;
		const start: [number, number, number] = [r1, 0, 0];
		const end: [number, number, number] = [r2 * Math.cos(angle), r2 * Math.sin(angle), 0];
		const arc = solveLambert(start, end, tof, mu)!;
		expect(arc).not.toBeNull();

		const vCirc1: [number, number, number] = [0, Math.sqrt(mu / r1), 0];
		const vCirc2: [number, number, number] = [
			-Math.sqrt(mu / r2) * Math.sin(angle),
			Math.sqrt(mu / r2) * Math.cos(angle),
			0
		];
		expect(norm(sub(arc.v1, vCirc1))).toBeCloseTo(dv1, 1);
		expect(norm(sub(vCirc2, arc.v2))).toBeCloseTo(dv2, 1);
	});

	it('is self-consistent when the time of flight is varied', () => {
		// A slower transfer between the same endpoints must cost a different, and
		// for these radii lower, departure speed.
		const r1: [number, number, number] = [AU_KM, 0, 0];
		const r2: [number, number, number] = [0, 5.2 * AU_KM, 0];
		const fast = solveLambert(r1, r2, 400 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		const slow = solveLambert(r1, r2, 1000 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		expect(norm(fast.v1)).toBeGreaterThan(norm(slow.v1));
	});

	it('rejects degenerate geometry and bad inputs', () => {
		const r: [number, number, number] = [AU_KM, 0, 0];
		expect(solveLambert(r, r, 100 * SEC_PER_DAY, GM_SUN_KM3_S2)).toBeNull();
		expect(solveLambert(r, [-AU_KM, 0, 0], 100 * SEC_PER_DAY, GM_SUN_KM3_S2)).toBeNull();
		expect(solveLambert(r, [0, AU_KM, 0], 0, GM_SUN_KM3_S2)).toBeNull();
		expect(solveLambert(r, [0, AU_KM, 0], 100 * SEC_PER_DAY, 0)).toBeNull();
	});
});

describe('transferArc', () => {
	const excess = (arc: LambertArc, from: { v: Vec3 }, to: { v: Vec3 }) =>
		norm(sub(arc.v1, from.v)) + norm(sub(arc.v2, to.v));

	it('goes round the way the departure goes when the target goes the same way', () => {
		const from = elementsToState(heliocentric(1, 0.0167), J2000, GM_SUN_KM3_S2)!;
		const to = elementsToState(
			heliocentric(1.524, 0.0934, 1.85, 49.6),
			J2000 + 259,
			GM_SUN_KM3_S2
		)!;
		const tof = 259 * SEC_PER_DAY;
		const along = solveLambert(from.r, to.r, tof, GM_SUN_KM3_S2, cross(from.r, from.v))!;
		expect(transferArc(from, to, tof, GM_SUN_KM3_S2)).toEqual(along);
	});

	it('takes the cheaper way between orbits that go round in opposite senses', () => {
		// From a slow retrograde orbit in to a fast prograde one: turning the
		// craft round at the start costs less than meeting the target head-on.
		const from = elementsToState(heliocentric(5, 0, 180), J2000, GM_SUN_KM3_S2)!;
		const to = elementsToState(heliocentric(1, 0, 0, 0, 0, 100), J2000 + 900, GM_SUN_KM3_S2)!;
		const tof = 900 * SEC_PER_DAY;
		const normal = cross(from.r, from.v);
		const along = solveLambert(from.r, to.r, tof, GM_SUN_KM3_S2, normal)!;
		const against = solveLambert(from.r, to.r, tof, GM_SUN_KM3_S2, scale(normal, -1))!;
		const arc = transferArc(from, to, tof, GM_SUN_KM3_S2)!;
		expect(excess(arc, from, to)).toBeCloseTo(
			Math.min(excess(along, from, to), excess(against, from, to)),
			9
		);
		expect(excess(against, from, to)).toBeLessThan(excess(along, from, to));
	});
});
