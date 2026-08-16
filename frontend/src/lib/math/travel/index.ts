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
 * And a fourth for the drives that cannot burn at all: an ion engine spirals out
 * of one well, reshapes its orbit under months of thrust, and spirals down into
 * the other. No Lambert arc, no launch energy, and a Δv that buys a different
 * trip than the same figure spent at an instant. See `low-thrust`.
 *
 * A route says what a trip costs, not where it goes. Drawing one needs the
 * second thing, so `path` re-derives the arcs from the same inputs the route was
 * priced from and walks them with `propagate` — the geometry and the ladder
 * therefore cannot disagree, because neither is stored.
 *
 * Scope limits worth knowing: transfers are patched-conic legs about one primary
 * (a moon needs its own leg from its planet), a swing-by route carries exactly
 * one pass, only the zero-revolution Lambert branch is solved, and the manoeuvre
 * model is a set of published loss factors rather than an optimiser. See the
 * constants module for every approximation by name.
 */

export { GM_SUN_KM3_S2, PARKING_ALTITUDE_KM } from './constants';

export type { Vec3 } from './vec3';
export { add, cross, dot, norm, normalize, scale, sub } from './vec3';

export type { EphemerisSamples, TravelBody } from './body';
export { estimateMu, escapeSpeed, muFromElements, sphereOfInfluenceKm } from './body';

export type { StateVector } from './state';
export { elementsToState, eclipticToScene } from './state';

export type { LambertArc } from './lambert';
export { solveLambert } from './lambert';

export type { AeroAssist, ArrivalMode, ArrivalCost, DepartureMode, EndOrbit } from './maneuvers';
export {
	aeroPassRadiusKm,
	arrivalCost,
	arrivalCampaignDays,
	ascentDv,
	canAeroBrake,
	captureDv,
	characteristicEnergy,
	circularSpeed,
	departureCost,
	endArrivalOrbit,
	endDepartureOrbit,
	injectionDv,
	orbitPeriodHours,
	parkingOrbit,
	parkingRadiusKm,
	periapsisRaiseDv,
	speedAtRadius
} from './maneuvers';

export type { Route, RouteLeg, RouteOptions, LegKind } from './route';
export { arrivalLegs, buildRoute, routeDurationDays, routeEndJd } from './route';

export { propagateState } from './propagate';

export type {
	PathArc,
	PathArcKind,
	PathOptions,
	PathStop,
	PathStopKind,
	TrajectoryFrame,
	TrajectoryPath
} from './path';
export { buildTrajectoryPath } from './path';

export type { ConstantThrustOptions } from './brachistochrone';
export { buildConstantThrustRoute } from './brachistochrone';

export type { LowThrustDrive, SpiralTransfer } from './low-thrust';
export {
	buildLowThrustRoute,
	driveAfter,
	edelbaumDvKms,
	rebuildSpiral,
	spiralDays,
	spiralTransfer
} from './low-thrust';

export {
	BELT_MODEL_UNCERTAINTY_FACTOR,
	BELT_SHIELDING_FLOOR,
	CANCER_RISK_PER_SV,
	DEFAULT_SHIELDING_G_CM2,
	LETHAL_DOSE_GY,
	MODELLED_BELT_IDS,
	beltPassDoseGy,
	beltShieldingFactor,
	cancerRiskFraction,
	decimalYearOf,
	gcrDoseRateSvPerDay,
	jovianBeltRateGyPerDay,
	lethalDoseFraction,
	openSkyFraction,
	radialFactor,
	solarCycleFactor
} from './radiation';

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

export type { TransferScale } from './windows';
export {
	crossingTimeDays,
	hohmannTransferDays,
	nextTransferWindows,
	requiredPhaseAngle,
	synodicPeriodDays,
	transferScale
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
	canAeroAssist,
	canDepartFrom,
	checkFeasibility,
	constantThrustAccelMs2,
	checkManifest,
	crewCapacity,
	dvWithPayloadKms,
	EMPTY_MANIFEST,
	feasibleRoutes,
	isLowThrust,
	lowThrustDrive,
	maxPayloadKgForRoute,
	payloadForC3
} from './vehicles';

export type { SolveResult } from './solver-client';
export { TravelSolver } from './solver-client';

export * as travelConstants from './constants';
