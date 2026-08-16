import { describe, it, expect } from 'vitest';
import {
	buildLowThrustRoute,
	driveAfter,
	edelbaumDvKms,
	rebuildSpiral,
	spiralDays,
	spiralTransfer,
	type LowThrustDrive
} from './low-thrust';
import { GM_SUN_KM3_S2 } from './constants';
import { circularSpeed, parkingRadiusKm } from './maneuvers';
import { buildTrajectoryPath } from './path';
import { craftPositionAt } from './path-sample';
import { routeDurationDays } from './route';
import { elementsToState } from './state';
import { norm, sub } from './vec3';
import { EARTH, J2000, MARS, MOON, VENUS } from './test-fixtures';

/**
 * Dawn as flown, loaded: 793 kg of airframe and 425 of xenon behind 92 mN of
 * gridded ion thruster at 3100 s. Every mission figure the tests below check
 * against belongs to this spacecraft.
 */
const DAWN: LowThrustDrive = {
	accelMs2: 0.092 / (793 + 425),
	veKms: (3100 * 9.80665) / 1000
};
/** Dawn's own Δv, km/s, from the same three figures. */
const DAWN_BUDGET_KMS = DAWN.veKms * Math.log((793 + 425) / 793);

const DAY = 86400;

describe('edelbaumDvKms', () => {
	it('costs the difference of the two speeds when the planes agree', () => {
		expect(edelbaumDvKms(29.78, 24.13, 0)).toBeCloseTo(5.65, 6);
	});

	// Mars's 1.85° of inclination is not free even though it looks it: turning
	// the velocity out of the ecliptic adds 160 m/s to the 5.65 the radius
	// change costs on its own.
	it('charges for the plane change on top', () => {
		const dv = edelbaumDvKms(29.78, 24.13, (1.85 * Math.PI) / 180);
		expect(dv).toBeCloseTo(5.81, 2);
	});

	// The limit that makes the escape spiral fall out of the same formula: an
	// orbit of no speed at all is one with no energy left to be bound by.
	it('costs the whole orbital speed to spiral out to nothing', () => {
		expect(edelbaumDvKms(7.73, 0, 0)).toBeCloseTo(7.73, 9);
	});

	it('is symmetric — down a well costs what up it does', () => {
		expect(edelbaumDvKms(24.13, 29.78, 0.03)).toBeCloseTo(edelbaumDvKms(29.78, 24.13, 0.03), 9);
	});
});

describe('spiralDays', () => {
	it('is the rocket equation solved for time at constant thrust', () => {
		// A drive that never lightened would take dv/a; a real one is quicker,
		// because the last kilometre per second pushes a lighter ship.
		const naive = (DAWN_BUDGET_KMS * 1000) / DAWN.accelMs2 / DAY;
		expect(spiralDays(DAWN_BUDGET_KMS, DAWN)).toBeLessThan(naive);
		// Spending the whole budget is spending the whole propellant, which at
		// 92 mN and 3.1 km/s of exhaust takes 425 kg / (92 mN / 30.4 km/s).
		const propellantSeconds = 425 / (0.092 / (DAWN.veKms * 1000));
		expect(spiralDays(DAWN_BUDGET_KMS, DAWN)).toBeCloseTo(propellantSeconds / DAY, 6);
	});

	it('charges nothing for a burn that is not one', () => {
		expect(spiralDays(0, DAWN)).toBe(0);
		expect(spiralDays(-1, DAWN)).toBe(0);
	});

	it('pushes harder once some of the mass is gone', () => {
		const later = driveAfter(DAWN, 5);
		expect(later.accelMs2).toBeGreaterThan(DAWN.accelMs2);
		// Five km/s at 30.4 of exhaust is e^(5/30.4) of the mass, so the same
		// again of the acceleration.
		expect(later.accelMs2 / DAWN.accelMs2).toBeCloseTo(Math.exp(5 / DAWN.veKms), 9);
		expect(later.veKms).toBe(DAWN.veKms);
	});
});

describe('spiralTransfer', () => {
	const v0 = circularSpeed(GM_SUN_KM3_S2, 149597870.7);
	const v1 = circularSpeed(GM_SUN_KM3_S2, 1.52371034 * 149597870.7);

	it('takes years and a couple of revolutions to reach Mars', () => {
		const transfer = spiralTransfer(v0, v1, 0, GM_SUN_KM3_S2, DAWN)!;
		expect(transfer).not.toBeNull();
		// Real low-thrust Earth-to-Mars studies fly two to three years and about
		// two turns round the Sun; this is the same trip without the coast arcs.
		expect(transfer.days / 365.25).toBeGreaterThan(1.5);
		expect(transfer.days / 365.25).toBeLessThan(3);
		expect(transfer.sweepRad / (2 * Math.PI)).toBeGreaterThan(1);
		expect(transfer.sweepRad / (2 * Math.PI)).toBeLessThan(3);
	});

	it('opens the orbit out from one radius to the other, in order', () => {
		const transfer = spiralTransfer(v0, v1, 0, GM_SUN_KM3_S2, DAWN)!;
		expect(transfer.radiiKm[0]).toBeCloseTo(GM_SUN_KM3_S2 / (v0 * v0), 3);
		expect(transfer.radiiKm[transfer.radiiKm.length - 1]).toBeCloseTo(GM_SUN_KM3_S2 / (v1 * v1), 3);
		for (let i = 1; i < transfer.radiiKm.length; i++) {
			expect(transfer.radiiKm[i]).toBeGreaterThan(transfer.radiiKm[i - 1]);
			expect(transfer.sweptRad[i]).toBeGreaterThan(transfer.sweptRad[i - 1]);
			expect(transfer.elapsedDays[i]).toBeGreaterThan(transfer.elapsedDays[i - 1]);
		}
	});

	it('spends the Δv the formula charges, over the time the drive needs', () => {
		const transfer = spiralTransfer(v0, v1, 0.03, GM_SUN_KM3_S2, DAWN)!;
		expect(transfer.dvKms).toBeCloseTo(edelbaumDvKms(v0, v1, 0.03), 9);
		expect(transfer.days).toBeCloseTo(spiralDays(transfer.dvKms, DAWN), 6);
	});

	it('has nothing to fly between two bodies already sharing an orbit', () => {
		const transfer = spiralTransfer(v0, v0, 0, GM_SUN_KM3_S2, DAWN)!;
		expect(transfer.dvKms).toBe(0);
		expect(transfer.days).toBe(0);
		expect(transfer.sweepRad).toBe(0);
	});

	it('refuses a drive that is not one', () => {
		expect(spiralTransfer(v0, v1, 0, GM_SUN_KM3_S2, { accelMs2: 0, veKms: 30 })).toBeNull();
		expect(spiralTransfer(v0, v1, 0, GM_SUN_KM3_S2, { accelMs2: 1e-4, veKms: 0 })).toBeNull();
	});
});

describe('buildLowThrustRoute', () => {
	const options = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;

	it('charges the whole of low Earth orbit to climb out of it', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		expect(route).not.toBeNull();
		const climb = route.legs.find((leg) => leg.kind === 'spiral-out')!;
		// The result that makes these missions launch on a chemical stage: an
		// impulsive escape from the same orbit costs 3.2 km/s, a spiral 7.7.
		expect(climb.dvKms).toBeCloseTo(circularSpeed(EARTH.mu, parkingRadiusKm(EARTH)), 9);
		expect(climb.dvKms).toBeGreaterThan(7.6);
		expect(climb.days).toBeGreaterThan(365);
	});

	it('puts Mars out of reach from low Earth orbit', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		// Escape, cross, capture — 16-odd km/s against the 13 the spacecraft
		// carried. Dawn was thrown to escape by a Delta II for exactly this
		// reason, and the panel is entitled to say so.
		expect(route.totalDvKms).toBeGreaterThan(DAWN_BUDGET_KMS);
		expect(route.inSpaceDvKms).toBe(route.totalDvKms);
	});

	it('arrives with nothing to capture from and nothing to launch on', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		expect(route.c3Km2S2).toBe(0);
		expect(route.vInfDepKms).toBe(0);
		expect(route.vInfArrKms).toBe(0);
		// No hyperbola means no entry, so nothing here needs a heat shield.
		expect(route.entrySpeedKms).toBeUndefined();
	});

	it('leaves on the date the spiral comes out where the target is', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		const rebuilt = rebuildSpiral(EARTH, MARS, route, { arrivalMode: 'low-orbit' })!;
		const from = elementsToState(EARTH.elements, rebuilt.startJd, GM_SUN_KM3_S2)!;
		const to = elementsToState(MARS.elements, route.arriveJd, GM_SUN_KM3_S2)!;

		const lonFrom = Math.atan2(from.r[1], from.r[0]);
		const lonTo = Math.atan2(to.r[1], to.r[0]);
		const closing = ((lonTo - lonFrom - rebuilt.transfer.sweepRad) % (2 * Math.PI)) + 2 * Math.PI;
		const miss = Math.min(closing % (2 * Math.PI), 2 * Math.PI - (closing % (2 * Math.PI)));
		// Within a tenth of a degree of where Mars will be, having waited for it.
		expect(miss).toBeLessThan(0.002);
		expect(route.departJd).toBeGreaterThanOrEqual(J2000);
		// Earth and Mars line up every 780 days, so the wait is never longer.
		expect(route.departJd - J2000).toBeLessThan(780);
	});

	it('takes longer with cargo aboard, and the same route otherwise', () => {
		const loaded: LowThrustDrive = { ...DAWN, accelMs2: 0.092 / (793 + 425 + 500) };
		const light = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		const heavy = buildLowThrustRoute(EARTH, MARS, J2000, loaded, options)!;
		expect(heavy.tofDays).toBeGreaterThan(light.tofDays);
		expect(heavy.totalDvKms).toBeCloseTo(light.totalDvKms, 6);
	});

	it('stops the arrival spiral at whatever orbit was asked for', () => {
		const low = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		const loose = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, {
			departureMode: 'orbit',
			arrivalMode: 'capture'
		})!;
		const dropOf = (route: typeof low) =>
			route.legs.find((leg) => leg.kind === 'spiral-in')?.dvKms ?? 0;
		// A loose ellipse is a higher orbit, and a spiral stopped higher up is a
		// spiral that spent less getting there.
		expect(dropOf(loose)).toBeLessThan(dropOf(low));
		// A flyby never drops in at all.
		const pass = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(dropOf(pass)).toBe(0);
	});

	it('refuses to take off or land under its own thrust', () => {
		expect(
			buildLowThrustRoute(EARTH, MARS, J2000, DAWN, {
				departureMode: 'surface',
				arrivalMode: 'low-orbit'
			})
		).toBeNull();
		// A thousandth of Mars's gravity does not hold anything off the ground,
		// however much Δv is left in the tanks.
		expect(
			buildLowThrustRoute(EARTH, MARS, J2000, DAWN, {
				departureMode: 'orbit',
				arrivalMode: 'landing'
			})
		).toBeNull();
	});

	it('flies inward as readily as outward', () => {
		const route = buildLowThrustRoute(EARTH, VENUS, J2000, DAWN, options)!;
		expect(route).not.toBeNull();
		expect(route.tofDays).toBeGreaterThan(200);
		const cruise = route.legs.find((leg) => leg.kind === 'powered-cruise')!;
		// Venus's orbit is 5.2 km/s faster than Earth's, and dropping into it
		// costs the same as climbing would.
		expect(cruise.dvKms).toBeGreaterThan(5);
	});

	it('never leaves the primary on a trip to its own moon', () => {
		const route = buildLowThrustRoute(EARTH, MOON, J2000, DAWN, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			systemPrimary: 'departure'
		})!;
		expect(route).not.toBeNull();
		// The climb out of low orbit *is* the crossing here, so there is no
		// separate escape to pay for — and no phasing wait, because where the
		// craft starts in its parking orbit is nobody's constraint.
		expect(route.legs.some((leg) => leg.kind === 'spiral-out')).toBe(false);
		expect(route.departJd).toBe(J2000);
		const cruise = route.legs.find((leg) => leg.kind === 'powered-cruise')!;
		expect(cruise.dvKms).toBeGreaterThan(6);
		expect(cruise.dvKms).toBeLessThan(8);
	});

	// The crossing is two thirds of the trip; the rest is spent going round one
	// body or the other. Drawing only the crossing stopped the craft dead at the
	// encounter while the clock ran on for another year.
	it('draws the whole trip, not just the crossing', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: 'naif-10' })!;
		expect(path.arcs.map((arc) => arc.kind)).toEqual(['spiral-out', 'spiral', 'spiral-in']);
		expect(path.arcs[0].startJd).toBeCloseTo(route.departJd, 9);
		expect(path.arcs[1].endJd).toBeCloseTo(route.arriveJd, 9);
		expect(path.arcs[2].endJd).toBeCloseTo(route.departJd + routeDurationDays(route), 6);

		// Each end rides with its body: the spiral itself is thousands of loops
		// inside a dot, and where that dot is, is what a transfer picture can say.
		const climbEnd = path.arcs[0].points[path.arcs[0].points.length - 1];
		const earthThen = elementsToState(EARTH.elements, path.arcs[0].endJd, GM_SUN_KM3_S2)!;
		expect(norm(sub(climbEnd, earthThen.r))).toBeLessThan(1);

		// The craft has to be somewhere for every day of the trip, not just vanish
		// at the encounter.
		const lastDay = route.departJd + routeDurationDays(route) - 1;
		expect(craftPositionAt(path, lastDay)).not.toBeNull();
		expect(craftPositionAt(path, route.departJd - 1)).toBeNull();
	});

	it('rebuilds the crossing it was priced with', () => {
		const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, options)!;
		const rebuilt = rebuildSpiral(EARTH, MARS, route, { arrivalMode: 'low-orbit' })!;
		const cruise = route.legs.find((leg) => leg.kind === 'powered-cruise')!;
		expect(rebuilt.transfer.dvKms).toBeCloseTo(cruise.dvKms, 9);
		expect(rebuilt.transfer.days).toBeCloseTo(cruise.days, 9);
		expect(rebuilt.startJd).toBeCloseTo(route.arriveJd - cruise.days, 9);
	});

	it('has no answer for a route it cannot be flown as', () => {
		expect(rebuildSpiral(EARTH, MARS, { ...buildRouteWithoutDrive() }, {})).toBeNull();
	});
});

/** A route with no drive on it — anything the impulsive solver returns. */
function buildRouteWithoutDrive() {
	const route = buildLowThrustRoute(EARTH, MARS, J2000, DAWN, {
		departureMode: 'orbit',
		arrivalMode: 'low-orbit'
	})!;
	return { ...route, lowThrust: undefined };
}
