/**
 * Vehicles a route can be flown with, and whether a given one can fly it.
 *
 * The feasibility model is the deliverable here. The catalogue below is a
 * placeholder with rounded, unsourced figures — it exists so the selector has
 * something to drive, and every entry needs a real citation before it ships.
 */

import type { Route } from './route';

export type PropulsionKind = 'chemical' | 'electric' | 'nuclear' | 'fictional';

export interface Vehicle {
	id: string;
	kind: 'launcher' | 'probe' | 'crewed' | 'fictional';
	propulsion: PropulsionKind;
	/** Δv the vehicle can supply once in space, km/s. */
	dvKms: number;
	/**
	 * Payload delivered against launch energy: ascending `[C3 km²/s², kg]`.
	 * Launchers only — this is what decides whether a departure is liftable.
	 */
	c3Curve?: ReadonlyArray<readonly [number, number]>;
	/**
	 * Continuous low thrust. Impulsive Δv is the wrong yardstick for these, so
	 * feasibility is reported as unmodelled rather than guessed.
	 */
	lowThrust?: boolean;
}

export type FeasibilityStatus = 'ok' | 'insufficient-dv' | 'over-c3' | 'not-modelled';

export interface Feasibility {
	status: FeasibilityStatus;
	/** Δv to spare, km/s. Negative when the route is out of reach. */
	marginKms: number;
	/** Payload the launcher can send on this trajectory, kg, when known. */
	payloadKg?: number;
}

/** Linear interpolation along the C3/payload curve; null beyond its end. */
export function payloadForC3(vehicle: Vehicle, c3: number): number | null {
	const curve = vehicle.c3Curve;
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
	return null; // Past the curve: the vehicle cannot reach this energy.
}

/**
 * Whether `vehicle` can fly `route`.
 *
 * A launcher is judged on whether it can reach the departure energy at all;
 * everything after injection is the spacecraft's problem. Everything else is
 * judged on in-space Δv, since the ascent belongs to whatever launched it.
 */
export function checkFeasibility(vehicle: Vehicle, route: Route): Feasibility {
	if (vehicle.lowThrust) {
		return { status: 'not-modelled', marginKms: NaN };
	}

	if (vehicle.kind === 'launcher') {
		const payloadKg = payloadForC3(vehicle, route.c3Km2S2);
		if (payloadKg === null || payloadKg <= 0) {
			return { status: 'over-c3', marginKms: NaN };
		}
		return { status: 'ok', marginKms: NaN, payloadKg };
	}

	const marginKms = vehicle.dvKms - route.inSpaceDvKms;
	return { status: marginKms >= 0 ? 'ok' : 'insufficient-dv', marginKms };
}

/** Routes this vehicle can fly, cheapest margin last. */
export function feasibleRoutes(vehicle: Vehicle, routes: Route[]): Route[] {
	return routes.filter((r) => checkFeasibility(vehicle, r).status === 'ok');
}

/**
 * Placeholder catalogue. Figures are rounded order-of-magnitude values chosen to
 * exercise the selector, NOT sourced performance data — replace before shipping.
 */
export const PLACEHOLDER_VEHICLES: readonly Vehicle[] = [
	{
		id: 'falcon-heavy',
		kind: 'launcher',
		propulsion: 'chemical',
		dvKms: 0,
		c3Curve: [
			[0, 15000],
			[20, 9500],
			[40, 6000],
			[60, 3800],
			[100, 1500]
		]
	},
	{
		id: 'sls-block-1b',
		kind: 'launcher',
		propulsion: 'chemical',
		dvKms: 0,
		c3Curve: [
			[0, 27000],
			[20, 18000],
			[40, 12000],
			[60, 8000],
			[100, 4000]
		]
	},
	{ id: 'apollo-csm', kind: 'crewed', propulsion: 'chemical', dvKms: 2.8 },
	{ id: 'starship-refuelled', kind: 'crewed', propulsion: 'chemical', dvKms: 6.9 },
	{ id: 'voyager-class', kind: 'probe', propulsion: 'chemical', dvKms: 0.2 },
	{ id: 'dawn-class', kind: 'probe', propulsion: 'electric', dvKms: 11, lowThrust: true },
	{ id: 'epstein-drive', kind: 'fictional', propulsion: 'fictional', dvKms: 3000 },
	{ id: 'discovery-one', kind: 'fictional', propulsion: 'nuclear', dvKms: 60 }
];
