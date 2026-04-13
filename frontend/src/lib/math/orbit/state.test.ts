import { describe, it, expect } from 'vitest';
import { EMB, CATALINA_HYP, SYNTHETIC_PARABOLIC } from './test-helpers';
import { currentStateFromElements } from './state';

const NOW_JD = Date.now() / 86400000 + 2440587.5;

describe('currentStateFromElements', () => {
	it('Earth-Moon Barycenter is near 1 AU and moves at ~29.8 km/s', () => {
		const s = currentStateFromElements(EMB, NOW_JD)!;
		expect(s).not.toBeNull();
		const AU_KM = 149_597_870.7;
		expect(s.rKm / AU_KM).toBeGreaterThan(0.95);
		expect(s.rKm / AU_KM).toBeLessThan(1.05);
		expect(s.vKms).toBeGreaterThan(28);
		expect(s.vKms).toBeLessThan(31);
	});

	it('returns finite state for a hyperbolic orbit', () => {
		const s = currentStateFromElements(CATALINA_HYP, NOW_JD);
		expect(s).not.toBeNull();
		expect(isFinite(s!.rKm)).toBe(true);
		expect(isFinite(s!.vKms)).toBe(true);
		expect(s!.vKms).toBeGreaterThan(0);
	});

	it('returns finite state for parabolic orbits via Barker + heliocentric GM', () => {
		const s = currentStateFromElements(SYNTHETIC_PARABOLIC, NOW_JD);
		expect(s).not.toBeNull();
		expect(isFinite(s!.rKm)).toBe(true);
		expect(isFinite(s!.vKms)).toBe(true);
		expect(s!.rKm).toBeGreaterThan(0);
		expect(s!.vKms).toBeGreaterThan(0);
	});

	it('returns null for parabolic orbits missing q/tp', () => {
		const s = currentStateFromElements(
			{ ...SYNTHETIC_PARABOLIC, q: undefined, tp: undefined },
			NOW_JD
		);
		expect(s).toBeNull();
	});
});
