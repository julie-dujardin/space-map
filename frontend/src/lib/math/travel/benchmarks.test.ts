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
import { AU_KM, LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { radiusFromMassEarth } from '$lib/travel/extrasolar-end';
import { findAssistRoute } from './assist';
import { escapeSpeed, muFromElements, sphereOfInfluenceKm, type TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveFlyby, turnAngleRad } from './flyby';
import {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	type InterstellarCruiseOptions,
	type SystemEnd
} from './interstellar';
import { solveLambert } from './lambert';
import {
	arrivalCost,
	ascentDv,
	circularSpeed,
	injectionDv,
	orbitPeriodHours,
	orbitSpeedAtRadius,
	parkingOrbit,
	parkingRadiusKm,
	periapsisRaiseDv
} from './maneuvers';
import { computePorkchop } from './porkchop';
import { buildRoute, routeShipDays, type Route } from './route';
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
	const bounds = systemArcBounds(
		EARTH_BARYCENTRIC,
		MOON_BARYCENTRIC,
		parkingOrbit(EARTH_BARYCENTRIC),
		J2000
	);
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

const YEAR_S = 365.25 * SEC_PER_DAY;
const YEAR_DAYS = 365.25;
const G0_MS2 = 9.80665;
/** The FAQ's own g, 1.03 ly/yr². */
const FAQ_ACCEL_MS2 = (1.03 * LIGHT_YEAR_KM * 1000) / YEAR_S ** 2;
/** A held arc stands 1 au off the star at each end. */
const HELD_STAND_OFF_KM = 2 * AU_KM;

/** A star at `km` on the x axis, with no planet. `massSolar` null leaves its μ unknown. */
function starAt(km: number, massSolar: number | null = 1): SystemEnd {
	const mu = massSolar === null ? undefined : massSolar * GM_SUN_KM3_S2;
	return {
		body: {
			id: `x-${km}`,
			mu: mu ?? 0,
			muEstimated: true,
			radiusKm: 700_000,
			elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: J2000 }
		},
		starKm: [km, 0, 0],
		starMu: mu,
		atStar: true
	};
}

/** The held arc of `ly` light-years between two stars, as flown. */
function heldArc(ly: number, accelMs2: number, arrivalMode: 'rendezvous' | 'flyby'): Route {
	const far = starAt(ly * LIGHT_YEAR_KM + HELD_STAND_OFF_KM);
	const options = { departureMode: 'rendezvous', arrivalMode } as const;
	const route = buildInterstellarTorchRoute(starAt(0), far, J2000, accelMs2, options);
	if (!route) throw new Error(`no held arc of ${ly} ly`);
	return route;
}

/** Propellant per kilogram of payload, for a perfect rocket at light speed. */
const fuelPerKg = (route: Route) => Math.expm1(route.totalDvKms / SPEED_OF_LIGHT_KM_S);

/** A body on a round orbit of `aAu` about a star of `mu`. */
function roundOrbit(id: string, aAu: number, mu: number, ma = 0): TravelBody {
	const n = (Math.sqrt(mu / (aAu * AU_KM) ** 3) * SEC_PER_DAY * 180) / Math.PI;
	return {
		id,
		mu: 4e5,
		muEstimated: true,
		radiusKm: 6_500,
		elements: { a: aAu, e: 0, i: 0, om: 0, w: 0, ma, n, epoch: J2000 }
	};
}

const AT_EARTH: SystemEnd = {
	body: EARTH,
	starKm: [0, 0, 0],
	starMu: GM_SUN_KM3_S2,
	atStar: false
};
const ROUND_EARTH: SystemEnd = {
	...AT_EARTH,
	body: { ...EARTH, elements: roundOrbit('naif-399', 1, GM_SUN_KM3_S2).elements }
};
/** Four light-years out, opposite `ROUND_EARTH` at J2000. An orbit that only just
 *  escapes leaves there on the side of the Sun away from where it started. */
const BEYOND = starAt(-4 * LIGHT_YEAR_KM);

/** The least Δv budget from a 200 km orbit that leaves the Sun, on a pass of `BEYOND`. */
function solarEscape(from: SystemEnd, options: InterstellarCruiseOptions = {}): Route {
	const orbit = { rPeriKm: 6578.1, rApoKm: 6578.1 };
	const leave = (dvKms: number) =>
		buildInterstellarCruiseRoute(
			from,
			BEYOND,
			J2000,
			{ kind: 'budget', dvKms },
			{ departureMode: 'orbit', arrivalMode: 'flyby', departureOrbit: orbit, ...options }
		);
	let lo = 1;
	let hi = 80;
	for (let i = 0; i < 40; i++) {
		const mid = (lo + hi) / 2;
		if (typeof leave(mid) === 'string') lo = mid;
		else hi = mid;
	}
	return leave(hi) as Route;
}

/** TRAPPIST-1, Agol et al. 2021, Tables 2, 6, 7. */
const TRAPPIST_MU = 0.0898 * GM_SUN_KM3_S2;
const TRAPPIST_D_AU = 0.02227;
const TRAPPIST_E_AU = 0.02925;

/** Δv of a transfer from d to e on round orbits, against a closed-form Hohmann. The
 *  arc sweeps 179.5°, because an exact half turn leaves its plane undefined. */
function trappistTransferDv(): number {
	const from = roundOrbit('x-d', TRAPPIST_D_AU, TRAPPIST_MU);
	const days = hohmannTransferDays(
		from,
		roundOrbit('x-e', TRAPPIST_E_AU, TRAPPIST_MU),
		TRAPPIST_MU
	)!;
	const motion = roundOrbit('x-e', TRAPPIST_E_AU, TRAPPIST_MU).elements.n;
	const to = roundOrbit('x-e', TRAPPIST_E_AU, TRAPPIST_MU, 179.5 - motion * days);
	const route = buildRoute(from, to, J2000, days, {
		departureMode: 'rendezvous',
		arrivalMode: 'rendezvous',
		centralMu: TRAPPIST_MU
	});
	return route?.totalDvKms ?? NaN;
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
			// The two steps of the one apogee burn: circularising, and the turn out
			// of the launch plane that rides it.
			const dv = (kind: string) => route?.legs.find((leg) => leg.kind === kind)?.dvKms ?? NaN;
			return dv('capture') + dv('turn-in');
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
	},
	{
		quantity: 'ship time, 4.3 ly with a stop, at 1.03 ly/yr²',
		source: 'Gibbs & Baez, The Relativistic Rocket, table of stops',
		expected: 3.6,
		unit: 'yr',
		tolerance: 0.02,
		compute: () => routeShipDays(heldArc(4.3, FAQ_ACCEL_MS2, 'rendezvous')) / YEAR_DAYS
	},
	{
		quantity: 'ship time, 27 ly with a stop, at 1.03 ly/yr²',
		source: 'Gibbs & Baez, The Relativistic Rocket, table of stops',
		expected: 6.6,
		unit: 'yr',
		tolerance: 0.01,
		compute: () => routeShipDays(heldArc(27, FAQ_ACCEL_MS2, 'rendezvous')) / YEAR_DAYS
	},
	{
		quantity: 'Earth time, 1839 ly on one burn, at 1.03 ly/yr²',
		source: 'Gibbs & Baez, The Relativistic Rocket, first table',
		expected: 1840,
		unit: 'yr',
		tolerance: 1e-3,
		compute: () => heldArc(1839, FAQ_ACCEL_MS2, 'flyby').tofDays / YEAR_DAYS
	},
	{
		quantity: 'γ, 113,242 ly on one burn, at 1.03 ly/yr²',
		source: 'Gibbs & Baez, The Relativistic Rocket, first table',
		expected: 116_641,
		unit: '',
		tolerance: 1e-4,
		compute: () => heldArc(113_242, FAQ_ACCEL_MS2, 'flyby').interstellar!.gamma
	},
	{
		quantity: 'propellant per kg of payload, 27 ly with a stop',
		source: 'Gibbs & Baez, The Relativistic Rocket, table of stops',
		expected: 886,
		unit: 'kg',
		tolerance: 5e-3,
		compute: () => fuelPerKg(heldArc(27, FAQ_ACCEL_MS2, 'rendezvous'))
	},
	{
		quantity: 'propellant per kg of payload, 30,000 ly on one burn',
		source: 'Gibbs & Baez, The Relativistic Rocket, table of passes',
		expected: 62_000,
		unit: 'kg',
		tolerance: 0.01,
		compute: () => fuelPerKg(heldArc(30_000, FAQ_ACCEL_MS2, 'flyby'))
	},
	{
		quantity: 'Earth time, 6000 ly with a stop, at 0.1 g',
		source: 'Closed form: t = 2(c/a)√(γ² − 1), γ = 1 + a(d/2)/c²',
		expected: 6019.34312,
		unit: 'yr',
		tolerance: 1e-6,
		compute: () => heldArc(6000, 0.1 * G0_MS2, 'rendezvous').tofDays / YEAR_DAYS
	},
	{
		quantity: 'ship time, 6000 ly with a stop, at 0.1 g',
		source: 'Closed form: τ = 2(c/a) acosh γ',
		expected: 124.61426,
		unit: 'yr',
		tolerance: 1e-6,
		compute: () => routeShipDays(heldArc(6000, 0.1 * G0_MS2, 'rendezvous')) / YEAR_DAYS
	},
	{
		quantity: 'γ, 6000 ly with a stop, at 0.1 g',
		source: 'Closed form: γ = 1 + a(d/2)/c²',
		expected: 310.68858,
		unit: '',
		tolerance: 1e-6,
		compute: () => heldArc(6000, 0.1 * G0_MS2, 'rendezvous').interstellar!.gamma
	},
	{
		quantity: 'escape from a 300 km Earth orbit',
		source: 'Beals et al. 1988, NASA-CR-184718, Project Longshot',
		expected: 3.2002,
		unit: 'km/s',
		tolerance: 1e-3,
		compute: () => injectionDv(EARTH.mu, 6678.1, 0)
	},
	{
		quantity: 'leaving the Sun from a 200 km orbit, on a round orbit',
		source: 'Closed form: excess (√2 − 1)v of Earth, through the well of Earth',
		expected: 8.75,
		unit: 'km/s',
		tolerance: 1e-3,
		compute: () => solarEscape(ROUND_EARTH).totalDvKms
	},
	{
		quantity: 'excess speed against Earth to leave the solar system',
		source: 'Beals et al. 1988, NASA-CR-184718, Project Longshot',
		expected: 12.4273,
		unit: 'km/s',
		tolerance: 0.01,
		compute: () => solarEscape(AT_EARTH, { launchWindow: true }).vInfDepKms
	},
	{
		quantity: 'γ at 0.2 c',
		source: 'Lubin 2016, arXiv 1604.01356: 1/√(1 − 0.04)',
		expected: 1.02062,
		unit: '',
		tolerance: 1e-5,
		compute: () => {
			const route = buildInterstellarCruiseRoute(
				starAt(0, null),
				starAt(4.37 * LIGHT_YEAR_KM),
				J2000,
				{ kind: 'budget', dvKms: SPEED_OF_LIGHT_KM_S * Math.atanh(0.2) },
				{ departureMode: 'rendezvous', arrivalMode: 'flyby' }
			) as Route;
			return route.interstellar!.gamma;
		}
	},
	{
		quantity: 'arrival at Proxima b in low orbit, at 63.691 km/s',
		// m sin i of 1.055 Earth masses and the radius of Chen & Kipping, as in the
		// catalogue, on Faria et al. 2022.
		source: 'Closed form: √(v∞² + v_esc²) − v_circ at the parking orbit',
		expected: 56.7587,
		unit: 'km/s',
		tolerance: 1e-4,
		compute: () =>
			arrivalCost(
				{
					...roundOrbit('x-b', 0.04848, 0.1221 * GM_SUN_KM3_S2),
					mu: 420_523.267682,
					radiusKm: 6527.2196
				},
				63.691,
				'low-orbit'
			).captureKms
	},
	{
		quantity: 'closing speed of a tangent meeting, on a round orbit, as a share of the closed form',
		source: 'Closed form: √(v² + v_esc²) − v_circ at the orbit',
		expected: 1,
		unit: '',
		tolerance: 1e-3,
		compute: () => {
			const mu = 0.122 * GM_SUN_KM3_S2;
			const star = { ...starAt(4.24 * LIGHT_YEAR_KM, 0.122), atStar: false };
			const target = { ...star, body: roundOrbit('x-b', 0.0485, mu) };
			const route = buildInterstellarCruiseRoute(
				AT_EARTH,
				target,
				J2000,
				{ kind: 'budget', dvKms: 120 },
				{ departureMode: 'orbit', arrivalMode: 'low-orbit' }
			) as Route;
			const rKm = 0.0485 * AU_KM;
			const fall = Math.hypot(route.interstellar!.rapidityKms, Math.sqrt((2 * mu) / rKm));
			return route.vInfArrKms / (fall - Math.sqrt(mu / rKm));
		}
	},
	{
		quantity: 'TRAPPIST-1 d to e, Hohmann time',
		source: 'Agol et al. 2021, 10.3847/PSJ/abd022, by Kepler’s third law',
		expected: 2.5197,
		unit: 'days',
		tolerance: 1e-4,
		compute: () =>
			hohmannTransferDays(
				roundOrbit('x-d', TRAPPIST_D_AU, TRAPPIST_MU),
				roundOrbit('x-e', TRAPPIST_E_AU, TRAPPIST_MU),
				TRAPPIST_MU
			) ?? NaN
	},
	{
		quantity: 'TRAPPIST-1 d to e, Δv on round orbits, with no wells',
		source: 'Agol et al. 2021, 10.3847/PSJ/abd022, by closed-form Hohmann',
		expected: 7.587,
		unit: 'km/s',
		tolerance: 1e-3,
		compute: trappistTransferDv
	},
	{
		quantity: 'mass of TRAPPIST-1 from the period and semi-major axis of b',
		source: 'Agol et al. 2021, 10.3847/PSJ/abd022: 0.0898 ± 0.0023',
		expected: 0.0898,
		unit: 'solar masses',
		tolerance: 0.01,
		compute: () => {
			const b = { a: 0.01154, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 360 / 1.510826, epoch: J2000 };
			return muFromElements(b) / GM_SUN_KM3_S2;
		}
	},
	{
		quantity: 'period of a round orbit of 1000 au about the Sun',
		source: 'Kepler’s third law',
		expected: 31_623.374,
		unit: 'yr',
		tolerance: 1e-5,
		compute: () =>
			orbitPeriodHours(GM_SUN_KM3_S2, { rPeriKm: 1000 * AU_KM, rApoKm: 1000 * AU_KM }) /
			(24 * YEAR_DAYS)
	},
	{
		quantity: 'speed on a round orbit of 1000 au about the Sun',
		source: 'Closed form: √(μ/r)',
		expected: 0.941875,
		unit: 'km/s',
		tolerance: 1e-5,
		compute: () => {
			const orbit = { rPeriKm: 1000 * AU_KM, rApoKm: 1000 * AU_KM };
			return orbitSpeedAtRadius(GM_SUN_KM3_S2, orbit, orbit.rPeriKm);
		}
	},
	{
		quantity: 'radius of a body of 1 Earth mass',
		source: 'Chen & Kipping 2017, 10.3847/1538-4357/834/1/17, Table 1',
		expected: 1.008,
		unit: 'Earth radii',
		tolerance: 1e-3,
		compute: () => radiusFromMassEarth(1)
	},
	{
		quantity: 'radius of a body of 2.04 Earth masses',
		source: 'Chen & Kipping 2017, 10.3847/1538-4357/834/1/17, Table 1',
		expected: 1.2298,
		unit: 'Earth radii',
		tolerance: 1e-3,
		compute: () => radiusFromMassEarth(2.04)
	},
	{
		quantity: 'radius of a body of 131.6 Earth masses',
		source: 'Chen & Kipping 2017, 10.3847/1538-4357/834/1/17, Table 1',
		expected: 14.31,
		unit: 'Earth radii',
		tolerance: 1e-3,
		compute: () => radiusFromMassEarth(131.6)
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
