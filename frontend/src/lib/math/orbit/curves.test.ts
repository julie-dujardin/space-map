import { describe, it, expect, vi } from 'vitest';
import {
	ELLIPTIC_ORBITS,
	EMB,
	CERES,
	CHIRON,
	ERIS,
	HALLEY,
	MRKOS,
	A2020H9,
	CATALINA_HYP,
	SYNTHETIC_PARABOLIC,
	sceneDistances,
	maxGapRatio
} from './test-helpers';

vi.mock('$lib/format/date', () => ({
	dateToJD: (d: Date) => d.getTime() / 86400000 + 2440587.5
}));

import {
	orbitalElementsToEllipse,
	orbitalElementsToParabola,
	orbitalElementsToHyperbola,
	orbitalElementsToCurve
} from './curves';

describe('orbitalElementsToEllipse', () => {
	it.each(ELLIPTIC_ORBITS)('all points finite and loop closes for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 128);
		expect(pts.length).toBe(129);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
		// First and last point should coincide (closed loop)
		const first = pts[0];
		const last = pts[pts.length - 1];
		expect(first[0]).toBeCloseTo(last[0], 3);
		expect(first[1]).toBeCloseTo(last[1], 3);
		expect(first[2]).toBeCloseTo(last[2], 3);
	});

	it.each(ELLIPTIC_ORBITS)('perihelion and aphelion distances match for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 512);
		const distances = sceneDistances(pts);
		const expectedQ = el.a * (1 - el.e);
		const expectedQQ = el.a * (1 + el.e);
		expect(Math.min(...distances)).toBeCloseTo(expectedQ, 1);
		expect(Math.max(...distances)).toBeCloseTo(expectedQQ, 0);
	});

	it.each(ELLIPTIC_ORBITS)('no large gaps for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 512);
		// E-uniform sampling keeps max/mean gap ratio reasonable
		expect(maxGapRatio(pts)).toBeLessThan(5);
	});
});

describe('orbitalElementsToParabola', () => {
	it('generates finite points for synthetic parabolic orbit', () => {
		const pts = orbitalElementsToParabola(SYNTHETIC_PARABOLIC, 64);
		expect(pts.length).toBe(65);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});

	it('minimum distance is close to q for synthetic orbit', () => {
		const pts = orbitalElementsToParabola(SYNTHETIC_PARABOLIC, 512);
		const minDist = Math.min(...sceneDistances(pts));
		expect(minDist).toBeCloseTo(SYNTHETIC_PARABOLIC.q!, 1);
	});

	it('generates finite points for near-parabolic A/2020 H9', () => {
		const q = A2020H9.a * (1 - A2020H9.e);
		const pts = orbitalElementsToParabola({ ...A2020H9, q }, 512);
		expect(pts.length).toBeGreaterThan(0);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
		const minDist = Math.min(...sceneDistances(pts));
		expect(minDist).toBeCloseTo(q, 1);
	});
});

describe('orbitalElementsToHyperbola', () => {
	it('generates finite points for Catalina', () => {
		const pts = orbitalElementsToHyperbola(CATALINA_HYP, 64);
		expect(pts.length).toBeGreaterThan(0);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});
});

describe('orbitalElementsToCurve', () => {
	it.each([
		{ name: 'EMB (e=0.022)', el: EMB },
		{ name: 'Ceres (e=0.081)', el: CERES },
		{ name: 'Chiron (e=0.379)', el: CHIRON },
		{ name: 'Eris (e=0.438)', el: ERIS },
		{ name: 'Halley (e=0.968)', el: HALLEY },
		{ name: 'Mrkos (e=0.989)', el: MRKOS }
	])('returns closed curve for $name', ({ el }) => {
		const { isOpen, points } = orbitalElementsToCurve(el, 128);
		expect(isOpen).toBe(false);
		expect(points.length).toBeGreaterThan(0);
	});

	it('returns open curve for near-parabolic A/2020 H9 (e=0.992)', () => {
		const { isOpen } = orbitalElementsToCurve(A2020H9, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for synthetic parabolic orbit', () => {
		const { isOpen } = orbitalElementsToCurve(SYNTHETIC_PARABOLIC, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for Catalina (hyperbolic)', () => {
		const { isOpen } = orbitalElementsToCurve(CATALINA_HYP, 64);
		expect(isOpen).toBe(true);
	});
});
