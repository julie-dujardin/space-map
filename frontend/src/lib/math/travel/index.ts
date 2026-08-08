/**
 * Trajectory compute layer for the "go somewhere" feature.
 *
 * Everything here is pure: it takes bodies and dates and returns routes, with
 * no reach into the fetch or scene layers. The UI supplies `TravelBody` records
 * built from whatever data it already has.
 *
 * The pipeline is:
 *
 *   elements → state vectors → Lambert arc → v∞ at each end
 *            → departure/arrival manoeuvre costs → a route of priced legs
 *
 * and above that, a porkchop sweep over departure date and cruise length that
 * yields the fast / balanced / efficient options to offer.
 *
 * Scope limits worth knowing: transfers are single patched-conic legs about one
 * primary (no gravity assists, and a moon needs its own leg from its planet),
 * only the zero-revolution Lambert branch is solved, and the manoeuvre model is
 * a set of published loss factors rather than an optimiser. See the constants
 * module for every approximation by name.
 */

export type { Vec3 } from './vec3';
export { add, cross, dot, norm, normalize, scale, sub } from './vec3';

export type { TravelBody } from './body';
export { estimateMu, escapeSpeed, muFromElements, sphereOfInfluenceKm } from './body';

export type { StateVector } from './state';
export { elementsToState, eclipticToScene } from './state';

export type { LambertArc } from './lambert';
export { solveLambert } from './lambert';

export type { ArrivalMode, ArrivalCost, DepartureMode } from './maneuvers';
export {
	arrivalCost,
	ascentDv,
	captureDv,
	characteristicEnergy,
	circularSpeed,
	departureCost,
	hasUsableAtmosphere,
	injectionDv,
	parkingRadiusKm
} from './maneuvers';

export type { Route, RouteLeg, RouteOptions, LegKind } from './route';
export { buildRoute } from './route';

export type { PorkchopGrid, PorkchopOptions, RouteChoice, RouteProfile } from './porkchop';
export { computePorkchop, selectRoutes } from './porkchop';

export type { RadialArc, SystemArcBounds } from './system-transfer';
export {
	hohmannArcDays,
	relativeState,
	separationKm,
	solveRadialArc,
	systemArcBounds
} from './system-transfer';

export {
	crossingTimeDays,
	hohmannTransferDays,
	nextTransferWindows,
	requiredPhaseAngle,
	synodicPeriodDays
} from './windows';

export type {
	C3Curve,
	Feasibility,
	FeasibilityStatus,
	Manifest,
	ManifestFit,
	Measured,
	PowerSource,
	PropulsionKind,
	Vehicle,
	VehicleKind,
	VehicleStatus
} from './vehicles';
export {
	canDepartFrom,
	checkFeasibility,
	checkManifest,
	crewCapacity,
	dvWithPayloadKms,
	EMPTY_MANIFEST,
	feasibleRoutes,
	isLowThrust,
	payloadForC3
} from './vehicles';

export type { SolveResult } from './solver-client';
export { TravelSolver } from './solver-client';

export * as travelConstants from './constants';
