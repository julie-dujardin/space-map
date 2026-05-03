/**
 * Integration test: frontend Kepler+drift propagation vs. SPICE truth.
 *
 * The fixture (see [data/scripts/generate_spice_truth_fixtures.py]) ships
 * per-chunk mean elements for a handful of non-whitelisted moons together
 * with parent-relative SPICE positions sampled inside each chunk's validity
 * window. This test feeds those elements through the production
 * `orbitalElementsToPositionJD` and asserts the result matches SPICE within
 * a per-body km tolerance.
 *
 * Running this in CI catches regressions in:
 *   - Kepler solver / orbital-frame rotations
 *   - Secular `om_dot` / `w_dot` application
 *   - The Three.js coordinate convention round-trip
 *
 * Tolerances are picked to comfortably accommodate the Method C secular fit
 * residual at chunk-edge horizons (≈ ±90 d). Tightening them when the fit
 * improves is fine; loosening should be paired with an investigation.
 */

import { describe, expect, it } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { AU_KM, AU_SCALE } from '$lib/math/units';
import fixture from './spice-truth.fixtures.json';

interface FixtureSample {
	jd: number;
	expected_parent_relative_km: [number, number, number];
}

interface FixtureEntry {
	id: string;
	name: string;
	parent_id: string;
	propagation: 'keplerian_with_drift';
	chunk_idx: number;
	chunk_validity_jd: [number, number];
	elements: OrbitalElements;
	samples: FixtureSample[];
}

interface Fixture {
	frame: 'ECLIPJ2000';
	units: 'km';
	scale: 'parent_relative';
	entries: FixtureEntry[];
}

const TYPED_FIXTURE = fixture as unknown as Fixture;

/**
 * Invert `orbitalToThreeJS`: scene units → ecliptic-J2000 km. The forward
 * mapping is `[x, y, z]_threejs = [x_ecl, z_ecl, -y_ecl] * AU_SCALE`, so
 * the inverse pulls the ecliptic axes back out and scales km/AU.
 */
function sceneToEclipticKm(p: [number, number, number]): [number, number, number] {
	const x_ecl = p[0] / AU_SCALE;
	const y_ecl = -p[2] / AU_SCALE;
	const z_ecl = p[1] / AU_SCALE;
	return [x_ecl * AU_KM, y_ecl * AU_KM, z_ecl * AU_KM];
}

function distanceKm(a: [number, number, number], b: [number, number, number]): number {
	const dx = a[0] - b[0];
	const dy = a[1] - b[1];
	const dz = a[2] - b[2];
	return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/**
 * Per-body tolerance in km. Sized from the observed Method C residual at the
 * chunk edge (~90 d from the fit anchor) plus a small safety margin. The
 * residual itself is the gap between the secular mean orbit and the SPICE
 * osculating truth — solar perturbations on outer irregulars push it up to
 * ~10⁵ km regardless of the propagation code. These limits are tight enough
 * that a real propagation regression (e.g. dropped `omDot` term, sign flip
 * in the rotation, lost float precision) shoves errors well past the bound.
 */
const TOLERANCE_KM: Record<string, number> = {
	'naif-802': 6_000, // Nereid (Neptune)
	'naif-722': 3_000, // Francisco (Uranus)
	'naif-716': 7_000, // Caliban (Uranus)
	'naif-717': 110_000, // Sycorax (Uranus) — longer period, larger residual
	'naif-811': 80_000 // Sao (Neptune)
};

function propagationErrorKm(el: OrbitalElements, sample: FixtureSample): number {
	const scene = orbitalElementsToPositionJD(el, sample.jd);
	if (!scene) throw new Error(`propagation returned null for jd ${sample.jd}`);
	return distanceKm(sceneToEclipticKm(scene), sample.expected_parent_relative_km);
}

describe('Kepler+drift propagation matches SPICE truth (non-whitelisted moons)', () => {
	for (const entry of TYPED_FIXTURE.entries) {
		describe(`${entry.name} (${entry.id})`, () => {
			const tolerance = TOLERANCE_KM[entry.id];
			expect(tolerance, `missing tolerance for ${entry.id}`).toBeDefined();

			for (const sample of entry.samples) {
				const dt = sample.jd - entry.elements.epoch;
				it(`matches at JD ${sample.jd.toFixed(2)} (Δt = ${dt.toFixed(0)} d)`, () => {
					const err = propagationErrorKm(entry.elements, sample);
					expect(
						err,
						`${entry.name} @ Δt=${dt.toFixed(0)}d: ${err.toFixed(1)} km (limit ${tolerance})`
					).toBeLessThan(tolerance);
				});
			}
		});
	}
});

describe('secular drift fields reach the propagator', () => {
	// Property test, no SPICE involved: a synthetic Kepler orbit with non-zero
	// `omDot`/`wDot` must produce a position that differs from the same orbit
	// with zeroed rates. This catches a propagator that ignores the rate
	// fields — a regression the chunk-edge SPICE comparison wouldn't always
	// flag, since for outer irregulars the linear drift fit can drift in or
	// out of agreement with the chaotic real orbit.
	const base: OrbitalElements = {
		a: 0.05,
		e: 0.1,
		i: 30,
		om: 90,
		w: 45,
		ma: 60,
		n: 1.0,
		epoch: 2451545.0,
		equatorial: false
	};
	const jd = base.epoch + 100; // 100 days of integrated drift

	it('omDot moves the body off the no-drift orbit', () => {
		const ref = orbitalElementsToPositionJD(base, jd)!;
		const drifted = orbitalElementsToPositionJD({ ...base, omDot: 0.1 }, jd)!;
		expect(distanceKm(sceneToEclipticKm(ref), sceneToEclipticKm(drifted))).toBeGreaterThan(10_000);
	});

	it('wDot moves the body off the no-drift orbit', () => {
		const ref = orbitalElementsToPositionJD(base, jd)!;
		const drifted = orbitalElementsToPositionJD({ ...base, wDot: 0.1 }, jd)!;
		expect(distanceKm(sceneToEclipticKm(ref), sceneToEclipticKm(drifted))).toBeGreaterThan(10_000);
	});

	it('omDot=wDot=0 matches missing rates', () => {
		const a = orbitalElementsToPositionJD({ ...base, omDot: 0, wDot: 0 }, jd)!;
		const b = orbitalElementsToPositionJD(base, jd)!;
		expect(distanceKm(sceneToEclipticKm(a), sceneToEclipticKm(b))).toBeLessThan(1e-6);
	});
});
