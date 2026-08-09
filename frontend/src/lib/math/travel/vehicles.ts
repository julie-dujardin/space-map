/**
 * Vehicles a route can be flown with, and whether a given one can fly it.
 *
 * The catalogue is data now: `/data/v1/spacecraft.json`, built from cited
 * constants in the pipeline. Nothing here invents a figure, and a vehicle
 * missing the figure a check needs reports that it cannot judge rather than
 * guessing — "no published escape performance" and "cannot reach that energy"
 * are different answers.
 */

import type { DepartureMode } from './maneuvers';
import type { Route } from './route';

export type PropulsionKind = 'chemical' | 'electric' | 'nuclear' | 'solar-sail' | 'fictional';
export type VehicleKind = 'launcher' | 'probe' | 'crewed' | 'lander' | 'fictional';
export type VehicleStatus =
	| 'active'
	| 'retired'
	| 'planned'
	/** Never flew and now never will, but keeps whatever was published for it. */
	| 'cancelled'
	| 'concept'
	| 'fictional';
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
	/**
	 * Which configuration this is, where the name cannot say — three Falcon
	 * Heavy entries share one Wikidata item and one label. Message-key slugs,
	 * rendered beside the name.
	 */
	variant?: readonly string[];
	/**
	 * Where a trip with this vehicle can start. Empty means nowhere: a rover is
	 * cargo, not something a trip is flown with. Undefined means an export
	 * older than the field, which is not a claim — see `canDepartFrom`.
	 */
	departsFrom?: readonly DepartureMode[];
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
	/**
	 * Cargo the vehicle can take beyond its own dry mass, kg. Launchers state
	 * theirs as a curve against C3 instead, since what they can lift depends on
	 * where it is going.
	 */
	payloadCapacityKg?: Measured;
	enduranceDays?: Measured;
	maxEntrySpeedKms?: Measured;
	capabilities?: readonly string[];

	/** Constant-acceleration drives: a brachistochrone, not a transfer orbit. */
	accelMs2?: Measured;
	/**
	 * Propellant is not a constraint the work imposes. Only ever set on fiction,
	 * and it is what lets a ship with no stated Δv be judged against a route at
	 * all — as well as what admits it to the constant-thrust solver, which is a
	 * separate claim from having an acceleration. See `constantThrustAccelMs2`.
	 */
	unlimitedDv?: boolean;

	cost?: { usdMillions: number; year: number; kind: string; source: string };
	objectIds?: readonly string[];
	groupSlug?: string;
}

export type FeasibilityStatus =
	| 'ok'
	| 'insufficient-dv'
	| 'over-c3'
	/** More cargo than the vehicle can send on this trajectory. */
	| 'over-payload'
	/** Past the end of a curve whose source stopped early — unknown, not no. */
	| 'beyond-published'
	/** Continuous low thrust: impulsive Δv is the wrong yardstick. */
	| 'not-modelled'
	/** The trip starts somewhere this vehicle cannot start from. */
	| 'wrong-departure'
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

/**
 * Whether a trip starting `mode` can be flown with this vehicle at all.
 *
 * Undefined is an export older than the field rather than a claim, so it
 * passes: silently dropping every vehicle from the picker would be a worse
 * failure than offering one that cannot lift off. An empty list *is* a claim —
 * a rover departs from nowhere.
 */
export function canDepartFrom(vehicle: Vehicle, mode: DepartureMode): boolean {
	return vehicle.departsFrom === undefined || vehicle.departsFrom.includes(mode);
}

/**
 * The acceleration this craft may be flown a constant-thrust arc at, or
 * undefined when it may not be.
 *
 * Two things have to hold, and the second is the one that is easy to lose. An
 * arc flown under power the whole way is spending the whole way, so it is only
 * honest for a craft whose propellant is not a constraint — and an acceleration
 * on its own does not say that. A solar sail publishes one and cannot hold it:
 * the figure is true at one distance and falls off as the inverse square.
 */
export function constantThrustAccelMs2(vehicle: Vehicle): number | undefined {
	return vehicle.unlimitedDv ? vehicle.accelMs2?.value : undefined;
}

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

/**
 * What a trip is carrying.
 *
 * Mass moves no trajectory — a Δv is a Δv whatever it is spent on — so a
 * manifest never re-solves anything. It decides what the vehicle can do with
 * the Δv the route already asks for, and whether it had room in the first place.
 */
export interface Manifest {
	/** People aboard. */
	passengers: number;
	/** Cargo, kg, on top of what the vehicle's dry mass already accounts for. */
	payloadKg: number;
}

export const EMPTY_MANIFEST: Manifest = { passengers: 0, payloadKg: 0 };

/**
 * Seats aboard; null when nothing published says.
 *
 * Zero is an answer rather than a gap. A probe carries nobody, and a launcher's
 * passengers ride in whatever it lifts rather than in the launcher, so only the
 * kinds built around people can have a seat count no source wrote down.
 */
export function crewCapacity(vehicle: Vehicle): number | null {
	if (vehicle.crew) return vehicle.crew.value;
	return vehicle.kind === 'crewed' || vehicle.kind === 'fictional' ? null : 0;
}

/** Standard gravity, m/s² — what turns an Isp in seconds into an exhaust speed. */
const G0_M_S2 = 9.80665;

/**
 * Δv the vehicle has once the cargo is aboard, km/s.
 *
 * The published figure is for the vehicle as flown, so cargo joins the dry mass
 * and the rocket equation gives back less. A Δv published without the masses
 * behind it cannot be re-derived and is returned unchanged: overstating it is
 * the lesser of two wrongs against saying nothing about a vehicle whose
 * performance is known.
 *
 * People are not weighed. A crewed vehicle's dry mass already carries its seats,
 * suits and consumables, and no source states what one more passenger costs.
 */
export function dvWithPayloadKms(vehicle: Vehicle, payloadKg: number): number | undefined {
	if (payloadKg <= 0 || vehicle.dvKms === undefined) return vehicle.dvKms;
	const dry = vehicle.dryMassKg?.value;
	const propellant = vehicle.propellantMassKg?.value;
	const isp = vehicle.ispS?.value;
	if (!dry || !propellant || !isp) return vehicle.dvKms;
	const loaded = dry + payloadKg;
	return (isp * G0_M_S2 * Math.log((loaded + propellant) / loaded)) / 1000;
}

/**
 * The heaviest cargo the vehicle could take on this route, kg.
 *
 * A launcher reads it off its curve at the route's energy; anything else gets
 * the rocket equation solved backwards for the payload at which its Δv just
 * meets the route's. Null when nothing published can answer — and for craft
 * whose propellant is no constraint, where the route imposes no limit to state.
 * A constant-thrust arc is priced at a fixed acceleration, which extra mass
 * would not hold, so it takes no answer either — and a drive too weak for the
 * impulsive model gets the same refusal to judge as `checkFeasibility` gives it.
 */
export function maxPayloadKgForRoute(vehicle: Vehicle, route: Route): number | null {
	if (route.constantThrust || vehicle.unlimitedDv) return null;
	if (vehicle.kind === 'launcher') return payloadForC3(vehicle, route.c3Km2S2);
	if (isLowThrust(vehicle)) return null;
	const dry = vehicle.dryMassKg?.value;
	const propellant = vehicle.propellantMassKg?.value;
	const isp = vehicle.ispS?.value;
	if (!dry || !propellant || !isp || !(route.inSpaceDvKms > 0)) return null;
	const ratio = Math.exp((route.inSpaceDvKms * 1000) / (isp * G0_M_S2));
	const loaded = propellant / (ratio - 1);
	return loaded > dry ? loaded - dry : null;
}

export type ManifestFit =
	| { status: 'ok' }
	| { status: 'over-capacity'; seats: number }
	| { status: 'over-payload'; capacityKg: number }
	/** Carries people, but no source says how many. */
	| { status: 'unknown-capacity' };

/**
 * Whether the vehicle has room for the manifest — a question about the vehicle
 * alone. Seats and hold do not change with the destination, so this is answered
 * once beside the craft instead of against every route.
 */
export function checkManifest(vehicle: Vehicle, manifest: Manifest): ManifestFit {
	if (manifest.passengers > 0) {
		const seats = crewCapacity(vehicle);
		if (seats === null) return { status: 'unknown-capacity' };
		if (manifest.passengers > seats) return { status: 'over-capacity', seats };
	}
	const hold = vehicle.payloadCapacityKg?.value;
	if (hold !== undefined && manifest.payloadKg > hold) {
		return { status: 'over-payload', capacityKg: hold };
	}
	return { status: 'ok' };
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
 * Whether `vehicle` can fly `route` with `manifest` aboard.
 *
 * A launcher is judged on whether it can reach the departure energy at all, and
 * on whether the cargo fits under its curve there; everything after injection is
 * the spacecraft's problem. Everything else is judged on in-space Δv, since the
 * ascent belongs to whatever launched it.
 *
 * Room aboard is deliberately not checked here — see `checkManifest`, which
 * answers it once rather than identically for every route.
 */
export function checkFeasibility(
	vehicle: Vehicle,
	route: Route,
	manifest: Manifest = EMPTY_MANIFEST
): Feasibility {
	// First, because everything below it is moot: an SLS cannot be lifted out
	// of the parking orbit it was going to put something into, and a Δv margin
	// for that trip would be an answer to a question nobody can ask.
	if (!canDepartFrom(vehicle, route.departureMode)) {
		return { status: 'wrong-departure', marginKms: NaN };
	}

	// Both of these are about a craft that is not spending a budget, so they come
	// before every check that weighs one.
	if (route.constantThrust) {
		return constantThrustAccelMs2(vehicle) === undefined
			? { status: 'not-modelled', marginKms: NaN }
			: annotate(vehicle, route, { status: 'ok', marginKms: Infinity });
	}
	if (vehicle.unlimitedDv) {
		return annotate(vehicle, route, { status: 'ok', marginKms: Infinity });
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
		const status = manifest.payloadKg > payloadKg ? 'over-payload' : 'ok';
		return annotate(vehicle, route, { status, marginKms: NaN, payloadKg });
	}

	if (isLowThrust(vehicle)) {
		return { status: 'not-modelled', marginKms: NaN };
	}
	const dvKms = dvWithPayloadKms(vehicle, manifest.payloadKg);
	if (dvKms === undefined) {
		return { status: 'unknown', marginKms: NaN };
	}

	const marginKms = dvKms - route.inSpaceDvKms;
	return annotate(vehicle, route, {
		status: marginKms >= 0 ? 'ok' : 'insufficient-dv',
		marginKms
	});
}

/** Routes this vehicle can fly, cheapest margin last. */
export function feasibleRoutes(
	vehicle: Vehicle,
	routes: Route[],
	manifest: Manifest = EMPTY_MANIFEST
): Route[] {
	return routes.filter((r) => checkFeasibility(vehicle, r, manifest).status === 'ok');
}
