import { describe, expect, it } from 'vitest';
import { probeOsculatingElements } from './elements';
import {
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_UNCOVERABLE
} from '$lib/fetch/position/format';
import type { Probe, SubChunk } from './parse';
import { AU_KM } from '$lib/math/units';

const JD_J2000 = 2451545.0;
const SECONDS_PER_DAY = 86400;
const RAD2DEG = 180 / Math.PI;
// Earth GM, km^3/s^2 — a round number that matches the writer's GM source.
const MU_EARTH = 3.986004418e5;

function makeProbe(subStartEt: number[], subEndEt: number[], subChunks: SubChunk[]): Probe {
	return {
		id: 'probe-1',
		probeId: 1,
		hasLocalized: false,
		objectType: 13,
		subStartEt,
		subEndEt,
		subChunks
	};
}

describe('probeOsculatingElements', () => {
	describe('kepler_pure', () => {
		// Circular equatorial orbit anchored at the sub-chunk start.
		const aKm = 10_000;
		const sub: SubChunk = {
			method: PROBE_METHOD_KEPLER_PURE,
			aKm,
			e: 0,
			iRad: 0,
			om0: 0,
			w0: 0,
			m0: 0,
			tAnchorOffsetS: 0
		};
		const probe = makeProbe([0], [SECONDS_PER_DAY], [sub]);

		it('emits AU semi-major and deg/day mean motion from packed elements', () => {
			const el = probeOsculatingElements(probe, JD_J2000, MU_EARTH);
			expect(el).not.toBeNull();
			expect(el!.a).toBeCloseTo(aKm / AU_KM, 12);
			expect(el!.e).toBe(0);
			expect(el!.i).toBe(0);
			expect(el!.om).toBe(0);
			expect(el!.w).toBe(0);
			expect(el!.ma).toBe(0);
			const expectedNDegDay = Math.sqrt(MU_EARTH / (aKm * aKm * aKm)) * RAD2DEG * SECONDS_PER_DAY;
			expect(el!.n).toBeCloseTo(expectedNDegDay, 6);
			expect(el!.epoch).toBeCloseTo(JD_J2000, 12);
			expect(el!.equatorial).toBe(false);
			expect(el!.omDot).toBeUndefined();
			expect(el!.wDot).toBeUndefined();
		});

		it('returns null when mu is zero (mean motion would degenerate)', () => {
			expect(probeOsculatingElements(probe, JD_J2000, 0)).toBeNull();
		});
	});

	describe('kepler_drift', () => {
		const aKm = 10_000;
		const omDotRadS = 1e-8;
		const wDotRadS = 2e-8;
		const nMeanRadS = Math.sqrt(MU_EARTH / (aKm * aKm * aKm));
		const sub: SubChunk = {
			method: PROBE_METHOD_KEPLER_DRIFT,
			aKm,
			e: 0.01,
			iRad: 0.1,
			om0: 0.2,
			w0: 0.3,
			m0: 0.4,
			omDot: omDotRadS,
			wDot: wDotRadS,
			nMeanRadS,
			tAnchorOffsetS: 0
		};
		const probe = makeProbe([0], [SECONDS_PER_DAY], [sub]);

		it('converts omDot/wDot from rad/s to deg/day', () => {
			const el = probeOsculatingElements(probe, JD_J2000, MU_EARTH);
			expect(el).not.toBeNull();
			expect(el!.omDot).toBeCloseTo(omDotRadS * RAD2DEG * SECONDS_PER_DAY, 12);
			expect(el!.wDot).toBeCloseTo(wDotRadS * RAD2DEG * SECONDS_PER_DAY, 12);
		});

		it('uses the fitted nMeanRadS (does not re-derive from mu)', () => {
			const el = probeOsculatingElements(probe, JD_J2000, 0);
			// Drift elements don't need mu — they fall through with the packed n.
			expect(el).not.toBeNull();
			expect(el!.n).toBeCloseTo(nMeanRadS * RAD2DEG * SECONDS_PER_DAY, 6);
		});

		it('emits angles in degrees', () => {
			const el = probeOsculatingElements(probe, JD_J2000, MU_EARTH)!;
			expect(el.i).toBeCloseTo(0.1 * RAD2DEG, 12);
			expect(el.om).toBeCloseTo(0.2 * RAD2DEG, 12);
			expect(el.w).toBeCloseTo(0.3 * RAD2DEG, 12);
			expect(el.ma).toBeCloseTo(0.4 * RAD2DEG, 12);
		});
	});

	describe('chebyshev', () => {
		// One segment, position constant = (10000 km, 0, 0), velocity from a linear
		// term so the y-component is non-zero — gives a circular-ish state to
		// round-trip through stateVectorToElements.
		const N = 12;
		const cx = new Array(N).fill(0);
		cx[0] = 10_000; // constant position 10000 km on x
		const cy = new Array(N).fill(0);
		cy[1] = 5; // T_1(τ) = τ, so y(τ) = 5τ — non-zero velocity
		const cz = new Array(N).fill(0);
		const coeffs = new Float64Array([...cx, ...cy, ...cz]);
		const sub: SubChunk = {
			method: PROBE_METHOD_CHEBYSHEV,
			coeffsPerAxis: N,
			nSeg: 1,
			coeffs
		};
		const probe = makeProbe([0], [SECONDS_PER_DAY], [sub]);

		it('derives finite osculating elements from the polynomial state', () => {
			const el = probeOsculatingElements(probe, JD_J2000 + 0.5, MU_EARTH);
			expect(el).not.toBeNull();
			expect(Number.isFinite(el!.a)).toBe(true);
			expect(Number.isFinite(el!.e)).toBe(true);
			expect(Number.isFinite(el!.n)).toBe(true);
			expect(el!.epoch).toBeCloseTo(JD_J2000 + 0.5, 12);
			expect(el!.equatorial).toBe(false);
		});

		it('returns null when mu is zero', () => {
			expect(probeOsculatingElements(probe, JD_J2000 + 0.5, 0)).toBeNull();
		});

		it('returns null when the FD window touches outside coverage', () => {
			// Sample exactly at sub-chunk start — the ±30s window's minus branch
			// falls before subStartEt[0]=0, so probeStateKm returns null.
			expect(probeOsculatingElements(probe, JD_J2000, MU_EARTH)).toBeNull();
		});
	});

	describe('edge cases', () => {
		it('returns null for uncoverable sub-chunks', () => {
			const probe = makeProbe([0], [SECONDS_PER_DAY], [{ method: PROBE_METHOD_UNCOVERABLE }]);
			expect(probeOsculatingElements(probe, JD_J2000, MU_EARTH)).toBeNull();
		});

		it('returns null when jd is outside the probe coverage', () => {
			const probe = makeProbe(
				[0],
				[SECONDS_PER_DAY],
				[
					{
						method: PROBE_METHOD_KEPLER_PURE,
						aKm: 10_000,
						e: 0,
						iRad: 0,
						om0: 0,
						w0: 0,
						m0: 0,
						tAnchorOffsetS: 0
					}
				]
			);
			// 10 days after J2000 — well past subEndEt = 1 day.
			expect(probeOsculatingElements(probe, JD_J2000 + 10, MU_EARTH)).toBeNull();
			// Day before J2000 — before subStartEt = 0.
			expect(probeOsculatingElements(probe, JD_J2000 - 1, MU_EARTH)).toBeNull();
		});

		it('dispatches per sub-chunk across a transition', () => {
			// First day kepler_pure, second day uncoverable: querying inside the
			// second window must return null even though the first window has
			// valid elements.
			const probe = makeProbe(
				[0, SECONDS_PER_DAY],
				[SECONDS_PER_DAY, 2 * SECONDS_PER_DAY],
				[
					{
						method: PROBE_METHOD_KEPLER_PURE,
						aKm: 10_000,
						e: 0,
						iRad: 0,
						om0: 0,
						w0: 0,
						m0: 0,
						tAnchorOffsetS: 0
					},
					{ method: PROBE_METHOD_UNCOVERABLE }
				]
			);
			expect(probeOsculatingElements(probe, JD_J2000 + 0.5, MU_EARTH)).not.toBeNull();
			expect(probeOsculatingElements(probe, JD_J2000 + 1.5, MU_EARTH)).toBeNull();
		});
	});
});
