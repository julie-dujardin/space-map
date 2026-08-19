/**
 * Benchmarks: the model against published numbers.
 *
 * Every case here compares our output to a figure someone else derived — a
 * textbook constant, a flown mission, or a closed form we do not use in the
 * implementation. That is what makes them benchmarks rather than unit tests:
 * they can all pass while the code is self-consistently wrong only if the
 * external references are wrong too.
 *
 * Each entry carries its own tolerance, and the tolerance is part of the claim.
 * Exact geometry gets 1e-6; the ascent model, which is three fitted loss
 * factors, gets a few percent and should never be tightened to hide drift.
 *
 * Adding a reference is one row. If a row starts failing, the model changed —
 * decide whether that was intended before touching the number.
 */

import { describe, it, expect } from 'vitest';
import { AU_KM } from '$lib/math/units';
import { findAssistRoute } from './assist';
import { escapeSpeed, sphereOfInfluenceKm } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveFlyby, turnAngleRad } from './flyby';
import { solveLambert } from './lambert';
import {
	ascentDv,
	circularSpeed,
	injectionDv,
	parkingRadiusKm,
	periapsisRaiseDv
} from './maneuvers';
import { computePorkchop } from './porkchop';
import { buildRoute } from './route';
import { hohmannArcDays, systemArcBounds } from './system-transfer';
import type { ArrivalMode } from './maneuvers';
import {
	EARTH,
	EARTH_BARYCENTRIC,
	J2000,
	JUPITER,
	MARS,
	MOON,
	MOON_BARYCENTRIC,
	SATURN,
	VENUS
} from './test-fixtures';
import {
	hohmannTransferDays,
	nextTransferWindows,
	requiredPhaseAngle,
	synodicPeriodDays
} from './windows';
import { norm, sub } from './vec3';

interface Benchmark {
	quantity: string;
	/** Where the reference figure comes from. */
	source: string;
	expected: number;
	unit: string;
	/** Allowed relative deviation, as a fraction. */
	tolerance: number;
	compute: () => number;
}

/**
 * Magnitude of the analytic Hohmann departure burn between coplanar circular
 * orbits, km/s. Inward transfers brake rather than accelerate, so only the size
 * of the burn is returned.
 */
function analyticHohmannDepartureDv(r1: number, r2: number): number {
	return Math.abs(Math.sqrt(GM_SUN_KM3_S2 / r1) * (Math.sqrt((2 * r2) / (r1 + r2)) - 1));
}

/**
 * The same burn, obtained by asking our Lambert solver instead.
 *
 * The arc stops short of the far apse because an exact 180° transfer leaves the
 * plane undefined. That truncation moves the *arrival* point but not the
 * departure one, which stays on the apse the transfer starts from — periapsis
 * going outward, apoapsis coming inward — so the departure burn this returns is
 * exact for any `sweepDeg`, and the comparison has no geometric slack in it.
 */
function lambertHohmannDepartureDv(r1: number, r2: number, sweepDeg = 179.5): number {
	const aT = (r1 + r2) / 2;
	const e = Math.abs(r2 - r1) / (r1 + r2);
	const p = aT * (1 - e * e);
	const meanMotion = Math.sqrt(GM_SUN_KM3_S2 / aT ** 3);

	// Going outward the transfer begins at periapsis; going inward, at apoapsis.
	const startNu = r2 > r1 ? 0 : Math.PI;
	const endNu = startNu + (sweepDeg * Math.PI) / 180;

	const meanAnomaly = (nu: number) => {
		const E =
			2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
		return E - e * Math.sin(E);
	};
	const radius = (nu: number) => p / (1 + e * Math.cos(nu));
	const at = (nu: number): [number, number, number] => [
		radius(nu) * Math.cos(nu),
		radius(nu) * Math.sin(nu),
		0
	];

	const tof = (meanAnomaly(endNu) - meanAnomaly(startNu)) / meanMotion;
	const arc = solveLambert(at(startNu), at(endNu), tof, GM_SUN_KM3_S2);
	if (!arc) return NaN;
	return Math.abs(norm(arc.v1) - circularSpeed(GM_SUN_KM3_S2, r1));
}

/**
 * The slowest lunar arc — the half-ellipse from a parking orbit out to the
 * Moon. Every Apollo figure below is quoted against a transfer close to it.
 */
function lunarRoute(arrivalMode: ArrivalMode) {
	const bounds = systemArcBounds(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000);
	if (!bounds) throw new Error('no lunar arc bounds');
	const route = buildRoute(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000, bounds.slowestDays, {
		departureMode: 'surface',
		arrivalMode,
		systemPrimary: 'departure'
	});
	if (!route) throw new Error('no lunar route');
	return route;
}

function lunarLegDv(kind: string, arrivalMode: ArrivalMode): number {
	return lunarRoute(arrivalMode).legs.find((leg) => leg.kind === kind)?.dvKms ?? NaN;
}

const EARTH_ORBIT_KM = EARTH.elements.a * AU_KM;
const MARS_ORBIT_KM = MARS.elements.a * AU_KM;
const VENUS_ORBIT_KM = VENUS.elements.a * AU_KM;
const JUPITER_ORBIT_KM = JUPITER.elements.a * AU_KM;

const BENCHMARKS: Benchmark[] = [
	{
		quantity: 'trans-lunar injection from low Earth orbit',
		source: 'Apollo trans-lunar injection burns, 3.05-3.15 km/s',
		expected: 3.1,
		unit: 'km/s',
		tolerance: 0.03,
		compute: () => lunarLegDv('injection', 'low-orbit')
	},
	{
		quantity: 'combined plane change and circularisation, GTO to GEO',
		source: 'textbook apogee burn for a 28.6° inclined GTO, ~1.84 km/s',
		expected: 1.84,
		unit: 'km/s',
		tolerance: 0.01,
		compute: () => {
			const gto = { rPeriKm: parkingRadiusKm(EARTH), rApoKm: 42164, incDeg: 28.6 };
			const geo = { rPeriKm: 42164, rApoKm: 42164, incDeg: 0 };
			const tof = hohmannArcDays(EARTH.mu, gto.rPeriKm, 42164);
			const route = buildRoute(EARTH, EARTH, J2000, tof, {
				orbitChange: true,
				departureMode: 'orbit',
				arrivalMode: 'low-orbit',
				departureOrbit: gto,
				targetOrbit: geo
			});
			return route?.legs.find((leg) => leg.kind === 'capture')?.dvKms ?? NaN;
		}
	},
	{
		quantity: 'lunar orbit insertion',
		source: 'Apollo LOI, ~0.8-0.9 km/s',
		expected: 0.82,
		unit: 'km/s',
		tolerance: 0.05,
		compute: () => lunarLegDv('capture', 'low-orbit')
	},
	{
		quantity: 'Hohmann time from low Earth orbit to the Moon',
		source: 'textbook trans-lunar coast, ~5 days',
		expected: 4.98,
		unit: 'days',
		tolerance: 0.02,
		compute: () => lunarRoute('low-orbit').tofDays
	},
	{
		quantity: 'Earth surface to the lunar surface',
		source: 'standard delta-v budget, ~15.2 km/s',
		expected: 15.2,
		unit: 'km/s',
		tolerance: 0.03,
		compute: () => lunarRoute('landing').totalDvKms
	},
	{
		quantity: 'trans-lunar launch energy',
		source: 'lunar C3, about -2 km2/s2 — bound to Earth, unlike an escape',
		expected: -2.04,
		unit: 'km2/s2',
		tolerance: 0.03,
		compute: () => lunarRoute('low-orbit').c3Km2S2
	},
	{
		quantity: "Earth's mean orbital speed",
		source: 'NASA Earth fact sheet',
		expected: 29.78,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => circularSpeed(GM_SUN_KM3_S2, EARTH_ORBIT_KM)
	},
	{
		quantity: 'Earth escape velocity',
		source: 'NASA Earth fact sheet',
		expected: 11.186,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => escapeSpeed(EARTH)
	},
	{
		quantity: 'Mars escape velocity',
		source: 'NASA Mars fact sheet',
		expected: 5.03,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => escapeSpeed(MARS)
	},
	{
		quantity: 'Moon escape velocity',
		source: 'NASA Moon fact sheet',
		expected: 2.38,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => escapeSpeed(MOON)
	},
	{
		quantity: "Earth's sphere of influence",
		source: 'Standard astrodynamics tables',
		expected: 0.924e6,
		unit: 'km',
		tolerance: 0.01,
		compute: () => sphereOfInfluenceKm(EARTH, GM_SUN_KM3_S2, EARTH_ORBIT_KM)
	},
	{
		quantity: "Jupiter's sphere of influence",
		source: 'Standard astrodynamics tables',
		expected: 48.2e6,
		unit: 'km',
		tolerance: 0.01,
		compute: () => sphereOfInfluenceKm(JUPITER, GM_SUN_KM3_S2, JUPITER_ORBIT_KM)
	},
	{
		quantity: 'Earth-Mars synodic period',
		source: 'NASA Mars fact sheet',
		expected: 779.9,
		unit: 'days',
		tolerance: 0.005,
		compute: () => synodicPeriodDays(EARTH, MARS)!
	},
	{
		quantity: 'Earth-Venus synodic period',
		source: 'NASA Venus fact sheet',
		expected: 583.9,
		unit: 'days',
		tolerance: 0.005,
		compute: () => synodicPeriodDays(EARTH, VENUS)!
	},
	{
		quantity: 'Earth-Jupiter synodic period',
		source: 'NASA Jupiter fact sheet',
		expected: 398.9,
		unit: 'days',
		tolerance: 0.005,
		compute: () => synodicPeriodDays(EARTH, JUPITER)!
	},
	{
		quantity: 'Earth-Mars Hohmann transfer time',
		source: 'Curtis, Orbital Mechanics for Engineering Students',
		expected: 258.9,
		unit: 'days',
		tolerance: 0.01,
		compute: () => hohmannTransferDays(EARTH, MARS)!
	},
	{
		quantity: 'Earth-Jupiter Hohmann transfer time',
		source: 'Curtis, Orbital Mechanics for Engineering Students',
		expected: 997.5,
		unit: 'days',
		tolerance: 0.01,
		compute: () => hohmannTransferDays(EARTH, JUPITER)!
	},
	{
		quantity: 'Earth-Mars launch phase angle',
		source: 'Standard mission-design tables',
		expected: 44.3,
		unit: 'degrees',
		tolerance: 0.02,
		compute: () => (requiredPhaseAngle(EARTH, MARS)! * 180) / Math.PI
	},
	{
		quantity: 'Low Earth orbit circular speed (200 km)',
		source: 'Vis-viva at 6571 km',
		expected: 7.784,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => circularSpeed(EARTH.mu, parkingRadiusKm(EARTH))
	},
	{
		quantity: 'Escape burn from low Earth orbit',
		source: 'Standard astrodynamics tables',
		expected: 3.22,
		unit: 'km/s',
		tolerance: 0.01,
		compute: () => injectionDv(EARTH.mu, parkingRadiusKm(EARTH), 0)
	},
	{
		quantity: 'Trans-Mars injection from low Earth orbit',
		source: 'NASA mission-design references',
		expected: 3.6,
		unit: 'km/s',
		tolerance: 0.02,
		compute: () =>
			injectionDv(
				EARTH.mu,
				parkingRadiusKm(EARTH),
				analyticHohmannDepartureDv(EARTH_ORBIT_KM, MARS_ORBIT_KM)
			)
	},
	{
		quantity: 'Earth surface to low Earth orbit',
		source: 'Conventional launch-vehicle budget',
		expected: 9.4,
		unit: 'km/s',
		// Three fitted loss factors, not a derivation. Percent-level is the most
		// this model can honestly claim.
		tolerance: 0.05,
		compute: () => ascentDv(EARTH)
	},
	{
		quantity: 'Lunar surface to lunar orbit',
		source: 'Apollo lunar module ascent stage',
		expected: 1.87,
		unit: 'km/s',
		tolerance: 0.05,
		compute: () => ascentDv(MOON)
	},
	{
		quantity: 'Mars surface to low Mars orbit',
		source: 'Mars ascent vehicle studies',
		expected: 4.1,
		unit: 'km/s',
		tolerance: 0.05,
		compute: () => ascentDv(MARS)
	},
	{
		quantity: 'Mars aerocapture periapsis raise, into 200 x 2000 km',
		// Aerocapture design reference missions, arXiv 2308.10384 Table 2, which
		// gives 33 m/s for exactly this orbit.
		source: 'Aerocapture DRM set (2023)',
		expected: 0.033,
		unit: 'km/s',
		// Two-body geometry once the pass altitude is fixed, and the pass altitude
		// is a single constant standing in for an entry interface — this is the
		// tightest tolerance that assumption earns.
		tolerance: 0.05,
		compute: () =>
			periapsisRaiseDv(MARS.mu, MARS.radiusKm + 50, MARS.radiusKm + 200, MARS.radiusKm + 2000)
	},
	// Aerobraking is deliberately not in this table. The four flown Mars campaigns
	// removed 1.0-1.2 km/s over 77 to 290 active days, and how hard a campaign is
	// flown spreads the rate four-fold — wider than the 5% every row here is held
	// to. Its range is asserted in maneuvers.test.ts, where a range belongs.
	{
		quantity: 'Earth-Mars Hohmann departure Δv (heliocentric)',
		source: 'Closed-form Hohmann, via our Lambert solver',
		expected: 2.945,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => lambertHohmannDepartureDv(EARTH_ORBIT_KM, MARS_ORBIT_KM)
	},
	{
		quantity: 'Earth-Venus Hohmann departure Δv (heliocentric)',
		source: 'Closed-form Hohmann, via our Lambert solver',
		expected: 2.496,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => lambertHohmannDepartureDv(EARTH_ORBIT_KM, VENUS_ORBIT_KM)
	},
	{
		quantity: 'Earth-Jupiter Hohmann departure Δv (heliocentric)',
		source: 'Closed-form Hohmann, via our Lambert solver',
		expected: 8.79,
		unit: 'km/s',
		tolerance: 0.005,
		compute: () => lambertHohmannDepartureDv(EARTH_ORBIT_KM, JUPITER_ORBIT_KM)
	}
];

describe('published reference values', () => {
	it.each(BENCHMARKS)('$quantity — $source', (benchmark) => {
		const actual = benchmark.compute();
		expect(Number.isFinite(actual), `${benchmark.quantity} produced ${actual}`).toBe(true);
		const relative = Math.abs(actual - benchmark.expected) / Math.abs(benchmark.expected);
		expect(
			relative,
			`${benchmark.quantity}: got ${actual.toPrecision(6)} ${benchmark.unit}, ` +
				`expected ${benchmark.expected.toPrecision(6)} ${benchmark.unit} ` +
				`(off by ${(relative * 100).toFixed(3)}%, allowed ${(benchmark.tolerance * 100).toFixed(1)}%)`
		).toBeLessThanOrEqual(benchmark.tolerance);
	});

	it('covers every part of the pipeline', () => {
		// A benchmark table is only worth having if it fails when something real
		// breaks; this guards against it quietly shrinking to the easy cases.
		expect(BENCHMARKS.length).toBeGreaterThanOrEqual(18);
		for (const b of BENCHMARKS) {
			expect(b.source, `${b.quantity} has no source`).toBeTruthy();
			expect(b.tolerance).toBeGreaterThan(0);
			expect(b.tolerance).toBeLessThanOrEqual(0.05);
		}
	});
});

describe('Lambert against closed-form Hohmann', () => {
	// Sweeping the ratio rather than naming planets: the solver has to hold up
	// across the whole range the catalogue spans, inward transfers included.
	const pairs: Array<[string, number, number]> = [
		['Earth to Venus (inward)', EARTH_ORBIT_KM, VENUS_ORBIT_KM],
		['Earth to Mars', EARTH_ORBIT_KM, MARS_ORBIT_KM],
		['Earth to Jupiter', EARTH_ORBIT_KM, JUPITER_ORBIT_KM],
		['Earth to Saturn', EARTH_ORBIT_KM, SATURN.elements.a * AU_KM],
		['Venus to Jupiter', VENUS_ORBIT_KM, JUPITER_ORBIT_KM],
		['Jupiter to Earth (inward)', JUPITER_ORBIT_KM, EARTH_ORBIT_KM]
	];

	it.each(pairs)('%s departure burn matches the analytic value', (_name, r1, r2) => {
		const analytic = analyticHohmannDepartureDv(r1, r2);
		const solved = lambertHohmannDepartureDv(r1, r2);
		expect(Math.abs(solved - analytic) / Math.abs(analytic)).toBeLessThan(0.005);
	});

	it('is exact at every sweep angle, not just near 180 degrees', () => {
		// Truncating the arc moves only the arrival end, so the departure burn
		// must come back identical however much of the ellipse is flown. A
		// solver that merely approximated Hohmann would drift as the arc shortens.
		const analytic = analyticHohmannDepartureDv(EARTH_ORBIT_KM, MARS_ORBIT_KM);
		for (const sweep of [30, 90, 150, 175, 179.9]) {
			const solved = lambertHohmannDepartureDv(EARTH_ORBIT_KM, MARS_ORBIT_KM, sweep);
			expect(Math.abs(solved - analytic) / analytic).toBeLessThan(1e-9);
		}
	});
});

describe('swing-by against the closed form', () => {
	/**
	 * A free pass turns the excess velocity without changing its length, so the
	 * velocity it hands back to the heliocentric frame differs by a chord:
	 * |Δv| = 2·v∞·sin(δ/2). The implementation never writes that down — it solves
	 * a periapsis radius by bisection and differences two periapsis speeds — so
	 * the identity is an outside check on both halves at once.
	 */
	it('changes heliocentric velocity by the chord the turn subtends', () => {
		for (const vInf of [4, 6, 9]) {
			for (const rPeri of [200_000, 500_000, 2_000_000]) {
				const turn = turnAngleRad(JUPITER.mu, rPeri, vInf);
				const before: [number, number, number] = [vInf, 0, 0];
				const after: [number, number, number] = [vInf * Math.cos(turn), vInf * Math.sin(turn), 0];

				// The pass that joins these two is the one we started from, and it is free.
				const pass = solveFlyby(JUPITER, before, after)!;
				expect(pass.periapsisKm / rPeri).toBeCloseTo(1, 6);
				expect(pass.dvKms).toBeCloseTo(0, 9);

				expect(norm(sub(after, before))).toBeCloseTo(2 * vInf * Math.sin(turn / 2), 9);
			}
		}
	});
});

describe('grid throughput', () => {
	// A tripwire, not a measurement — the bound is ~50x the observed time so it
	// catches an accidental order-of-magnitude regression (an allocation added
	// to the inner solve) without failing on a loaded CI box.
	it('solves a 40x40 porkchop well inside interactive budget', () => {
		const window = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
		const started = performance.now();
		const grid = computePorkchop(EARTH, MARS, {
			departFromJd: window - 60,
			departToJd: window + 60,
			tofMinDays: 120,
			tofMaxDays: 400,
			departSteps: 40,
			tofSteps: 40
		});
		const elapsed = performance.now() - started;
		expect(grid.solvedCount).toBeGreaterThan(1500);
		expect(elapsed).toBeLessThan(2000);
	});

	// The same kind of tripwire for the swing-by search, which is the most
	// expensive thing the planner runs: three candidate bodies over a twenty-year
	// horizon, ~210 ms observed. It is what a re-solve on the panel costs, so an
	// order of magnitude lost here is a second of staring at a placeholder.
	it('hunts a swing-by well inside the panel budget', () => {
		const started = performance.now();
		const route = findAssistRoute(EARTH, SATURN, [VENUS, MARS, JUPITER], {
			nowJd: J2000,
			departureMode: 'surface',
			arrivalMode: 'low-orbit'
		});
		const elapsed = performance.now() - started;
		expect(route?.flybys?.[0].bodyId).toBe(JUPITER.id);
		expect(elapsed).toBeLessThan(5000);
	});
});

describe('benchmark inputs', () => {
	it('uses a J2000 epoch consistent across fixtures', () => {
		for (const body of [EARTH, MARS, VENUS, JUPITER, SATURN]) {
			expect(body.elements.epoch).toBe(J2000);
		}
	});

	it('derives fixture mean motions that match their semi-major axes', () => {
		for (const body of [EARTH, MARS, VENUS, JUPITER, SATURN]) {
			const aKm = body.elements.a * AU_KM;
			const expected = ((Math.sqrt(GM_SUN_KM3_S2 / aKm ** 3) * 180) / Math.PI) * SEC_PER_DAY;
			expect(body.elements.n).toBeCloseTo(expected, 9);
		}
	});
});
