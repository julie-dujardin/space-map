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
 * Beside it sits one arc that is not a transfer orbit at all: a drive held from
 * departure to arrival, which is what the catalogue's fictional ships fly and
 * the only thing an acceleration without a Δv budget can be priced as. See
 * `brachistochrone`.
 *
 * Beside both sits a third shape: two arcs patched by a swing-by past a third
 * body, searched over a horizon of years rather than one synodic period. See
 * `assist`.
 *
 * Scope limits worth knowing: transfers are patched-conic legs about one primary
 * (a moon needs its own leg from its planet), a swing-by route carries exactly
 * one pass, only the zero-revolution Lambert branch is solved, and the manoeuvre
 * model is a set of published loss factors rather than an optimiser. See the
 * constants module for every approximation by name.
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

export { buildConstantThrustRoute } from './brachistochrone';

export type { FlybyPass } from './flyby';
export { minFlybyRadiusKm, solveFlyby, turnAngleRad } from './flyby';

export type { AssistOptions, AssistSearchOptions } from './assist';
export { buildAssistRoute, findAssistRoute, searchAssist } from './assist';

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
	constantThrustAccelMs2,
	checkManifest,
	crewCapacity,
	dvWithPayloadKms,
	EMPTY_MANIFEST,
	feasibleRoutes,
	isLowThrust,
	maxPayloadKgForRoute,
	payloadForC3
} from './vehicles';

export type { SolveResult } from './solver-client';
export { TravelSolver } from './solver-client';

export * as travelConstants from './constants';
