/**
 * Vehicles a route can be flown with, and whether a given one can fly it.
 *
 * The catalogue is data now: `/data/v1/spacecraft.json`, built from cited
 * constants in the pipeline. Nothing here invents a figure, and a vehicle
 * missing the figure a check needs reports that it cannot judge rather than
 * guessing — "no published escape performance" and "cannot reach that energy"
 * are different answers.
 */

import type { Route } from './route';

export type PropulsionKind = 'chemical' | 'electric' | 'nuclear' | 'solar-sail' | 'fictional';
export type VehicleKind = 'launcher' | 'probe' | 'crewed' | 'lander' | 'fictional';
export type VehicleStatus = 'active' | 'retired' | 'planned' | 'concept' | 'fictional';
export type PowerSource = 'solar' | 'rtg' | 'nuclear' | 'battery' | 'fictional';

/** One figure and the source key backing it, so the panel can cite what it shows. */
export interface Measured {
	value: number;
	source: string;
}

export interface C3Curve {
	/** Ascending `[C3 km²/s², payload kg]`. */
	points: ReadonlyArray<readonly [number, number]>;
	source: string;
	/** The published range stops before the vehicle does. */
	truncated: boolean;
	crossCheck?: string;
}

export interface Vehicle {
	id: string;
	kind: VehicleKind;
	propulsion: PropulsionKind;
	status: VehicleStatus;
	/** Wikidata item, which is where the localized name comes from. */
	qid?: string;
	/** English name, for the few fictional ships with no Wikidata item. */
	name?: string;
	power?: PowerSource;

	dryMassKg?: Measured;
	propellantMassKg?: Measured;
	ispS?: Measured;
	thrustN?: Measured;
	/**
	 * Δv the vehicle can supply once in space, km/s, derived from the three
	 * fields above by the pipeline. Absent when any of them is — several real
	 * spacecraft have published masses and no published engine.
	 */
	dvKms?: number;

	/** Launchers only: what decides whether a departure is liftable at all. */
	c3Curve?: C3Curve;

	/** Everyone aboard: crew plus passengers, which are the same set on
	 *  every real spacecraft and not on a fictional liner. */
	crew?: Measured;
	enduranceDays?: Measured;
	maxEntrySpeedKms?: Measured;
	capabilities?: readonly string[];

	/** Constant-acceleration drives: a brachistochrone, not a transfer orbit. */
	accelMs2?: Measured;

	cost?: { usdMillions: number; year: number; kind: string; source: string };
	objectIds?: readonly string[];
	groupSlug?: string;
}

export type FeasibilityStatus =
	| 'ok'
	| 'insufficient-dv'
	| 'over-c3'
	/** Past the end of a curve whose source stopped early — unknown, not no. */
	| 'beyond-published'
	/** Continuous low thrust: impulsive Δv is the wrong yardstick. */
	| 'not-modelled'
	/** The vehicle is missing the figure this check needs. */
	| 'unknown';

export interface Feasibility {
	status: FeasibilityStatus;
	/** Δv to spare, km/s. Negative when the route is out of reach, NaN when unjudged. */
	marginKms: number;
	/** Payload the launcher can send on this trajectory, kg, when known. */
	payloadKg?: number;
	/**
	 * How many times over the trip outlasts the consumables, when both are
	 * known and it does. A route can be affordable in Δv and still be four
	 * times the life support.
	 */
	enduranceRatio?: number;
	/** Arrival speed, km/s, when it exceeds what the heat shield is rated for. */
	overEntrySpeedKms?: number;
}

/**
 * Acceleration below which a burn stops being usefully impulsive.
 *
 * A Lambert arc assumes the Δv is spent at a point. At 10 µm/s² — Dawn's ion
 * drive was an order of magnitude under this — a kilometre a second takes
 * three years to deliver, and the arc the solver drew never existed.
 */
const IMPULSIVE_FLOOR_M_S2 = 1e-4;

/** Whether the vehicle's thrust is too low for the impulsive model to hold. */
export function isLowThrust(vehicle: Vehicle): boolean {
	const { thrustN, dryMassKg, propellantMassKg } = vehicle;
	if (thrustN && dryMassKg && propellantMassKg) {
		const wetKg = dryMassKg.value + propellantMassKg.value;
		return thrustN.value / wetKg < IMPULSIVE_FLOOR_M_S2;
	}
	// No thrust figure: fall back to the propulsion type, which is what the
	// distinction is a proxy for anyway.
	return vehicle.propulsion === 'electric' || vehicle.propulsion === 'solar-sail';
}

/** Linear interpolation along the C3/payload curve; null beyond its end. */
export function payloadForC3(vehicle: Vehicle, c3: number): number | null {
	const curve = vehicle.c3Curve?.points;
	if (!curve || curve.length === 0) return null;
	if (c3 <= curve[0][0]) return curve[0][1];
	for (let i = 1; i < curve.length; i++) {
		const [c3a, ma] = curve[i - 1];
		const [c3b, mb] = curve[i];
		if (c3 <= c3b) {
			const t = (c3 - c3a) / (c3b - c3a);
			return ma + t * (mb - ma);
		}
	}
	return null; // Past the curve.
}

/** Endurance and heat-shield notes, which qualify a pass rather than deny it. */
function annotate(vehicle: Vehicle, route: Route, result: Feasibility): Feasibility {
	const endurance = vehicle.enduranceDays?.value;
	if (endurance && route.tofDays > endurance) {
		result.enduranceRatio = route.tofDays / endurance;
	}
	const rated = vehicle.maxEntrySpeedKms?.value;
	if (rated && route.arrivalMode === 'landing' && route.vInfArrKms > rated) {
		result.overEntrySpeedKms = route.vInfArrKms;
	}
	return result;
}

/**
 * Whether `vehicle` can fly `route`.
 *
 * A launcher is judged on whether it can reach the departure energy at all;
 * everything after injection is the spacecraft's problem. Everything else is
 * judged on in-space Δv, since the ascent belongs to whatever launched it.
 */
export function checkFeasibility(vehicle: Vehicle, route: Route): Feasibility {
	// A torch drive has no Δv budget to check against; it holds an
	// acceleration until it arrives, which is a different solver entirely.
	if (vehicle.accelMs2) {
		return { status: 'not-modelled', marginKms: NaN };
	}

	if (vehicle.kind === 'launcher') {
		if (!vehicle.c3Curve) return { status: 'unknown', marginKms: NaN };
		const payloadKg = payloadForC3(vehicle, route.c3Km2S2);
		if (payloadKg === null || payloadKg <= 0) {
			// Off the end of a curve that runs out where the rocket does is a
			// no; off the end of one the source truncated is a shrug.
			const status = vehicle.c3Curve.truncated ? 'beyond-published' : 'over-c3';
			return { status, marginKms: NaN };
		}
		return annotate(vehicle, route, { status: 'ok', marginKms: NaN, payloadKg });
	}

	if (isLowThrust(vehicle)) {
		return { status: 'not-modelled', marginKms: NaN };
	}
	if (vehicle.dvKms === undefined) {
		return { status: 'unknown', marginKms: NaN };
	}

	const marginKms = vehicle.dvKms - route.inSpaceDvKms;
	return annotate(vehicle, route, {
		status: marginKms >= 0 ? 'ok' : 'insufficient-dv',
		marginKms
	});
}

/** Routes this vehicle can fly, cheapest margin last. */
export function feasibleRoutes(vehicle: Vehicle, routes: Route[]): Route[] {
	return routes.filter((r) => checkFeasibility(vehicle, r).status === 'ok');
}
