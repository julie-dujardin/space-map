import { describe, it, expect } from 'vitest';
import { buildRoute, type RouteOptions } from '$lib/math/travel';
import { EARTH, J2000, MARS } from '$lib/math/travel/test-fixtures';
import type { TransferFrame } from '$lib/travel/travel-body';
import { hazardKey, routeKey, timelineKey } from './route-keys';

const FRAME: TransferFrame = { orbit: 'heliocentric' };
const CENTER = 'naif-10';
const DEPART = J2000 + 60;
const TOF = 210;

/** The same crossing, priced under different terms — the dates never move, so
 *  only the keys' own discriminators can tell the results apart. */
function priced(options: RouteOptions) {
	const route = buildRoute(EARTH, MARS, DEPART, TOF, { departureMode: 'orbit', ...options });
	expect(route).not.toBeNull();
	return route!;
}

const AIR_MARS = MARS;
/** Mars as the kernel sees it before the detail bundle lands: no air fields at
 *  all, so every arrival prices as airless. */
const UNKNOWN_MARS = {
	...MARS,
	hasAtmosphere: undefined,
	surfacePressureBar: undefined,
	aeroPressurePa: undefined,
	aeroScaleHeightKm: undefined
};

describe('route view keys', () => {
	// The panel re-solves on every input change and the optimizer often lands
	// on the same grid cell, so date movement alone can't invalidate a view —
	// each key must carry everything its view reads off the route.

	it('rebuilds the drawn end orbits when only their altitude changed', () => {
		const low = priced({ arrivalMode: 'low-orbit', targetOrbit: { rPeriKm: 3690, rApoKm: 3690 } });
		const high = priced({
			arrivalMode: 'low-orbit',
			targetOrbit: { rPeriKm: 20428, rApoKm: 20428 }
		});
		// Same crossing, different priced arrival — and the path draws the orbit
		// ring at the priced radius.
		expect(low.departJd).toBe(high.departJd);
		expect(low.totalDvKms).not.toBe(high.totalDvKms);
		expect(routeKey(low, CENTER, FRAME)).not.toBe(routeKey(high, CENTER, FRAME));
	});

	it('rescans hazards when the atmosphere turns out to exist', () => {
		// The detail bundle lands after the first solve: same trip and braking
		// request, but the arrival goes from priced-airless to flown through air.
		const dry = buildRoute(EARTH, UNKNOWN_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		const air = buildRoute(EARTH, AIR_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		expect(dry.entrySpeedKms).toBeUndefined();
		expect(air.entrySpeedKms).toBeGreaterThan(0);
		expect(hazardKey(dry, CENTER, FRAME)).not.toBe(hazardKey(air, CENTER, FRAME));
	});

	it('rescans hazards when the braking mode alone changed', () => {
		const engine = buildRoute(EARTH, AIR_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'none'
		})!;
		const braking = buildRoute(EARTH, AIR_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerobraking'
		})!;
		expect(hazardKey(engine, CENTER, FRAME)).not.toBe(hazardKey(braking, CENTER, FRAME));
	});

	it('rebuilds the timeline when only the priced arrival changed', () => {
		const bodies = { departure: EARTH, target: MARS };
		const low = priced({ arrivalMode: 'low-orbit', targetOrbit: { rPeriKm: 3690, rApoKm: 3690 } });
		const high = priced({
			arrivalMode: 'low-orbit',
			targetOrbit: { rPeriKm: 20428, rApoKm: 20428 }
		});
		// The final-orbit entry is drawn at the priced radius, and the capture
		// leg's Δv is the burn into it.
		expect(timelineKey(low, 'Earth', 'Mars', bodies)).not.toBe(
			timelineKey(high, 'Earth', 'Mars', bodies)
		);
	});

	it('rebuilds the timeline when air repriced the legs under the same dates', () => {
		const bodies = { departure: EARTH, target: MARS };
		const dry = buildRoute(EARTH, UNKNOWN_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerobraking'
		})!;
		const air = buildRoute(EARTH, AIR_MARS, DEPART, TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerobraking'
		})!;
		// Same dates, but the campaign the timeline draws only exists with air.
		expect(dry.arriveJd).toBe(air.arriveJd);
		expect(dry.legs.some((leg) => leg.kind === 'aerobrake')).toBe(false);
		expect(air.legs.some((leg) => leg.kind === 'aerobrake')).toBe(true);
		expect(timelineKey(dry, 'Earth', 'Mars', bodies)).not.toBe(
			timelineKey(air, 'Earth', 'Mars', bodies)
		);
	});
});
