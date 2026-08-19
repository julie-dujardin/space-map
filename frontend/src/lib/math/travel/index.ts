/**
 * Trajectory compute layer for the "go somewhere" feature. Pure: takes bodies
 * and dates, returns routes, no reach into fetch or scene layers.
 *
 * Main pipeline:
 *
 *   elements → state vectors → Lambert arc → v∞ at each end
 *            → departure/arrival manoeuvre costs → a route of priced legs
 *
 * topped by a porkchop sweep over departure date and cruise length, yielding
 * fast / balanced / efficient options. Three more route shapes beside it: a
 * held drive from departure to arrival for fictional ships without a Δv budget
 * (`brachistochrone`); two Lambert arcs patched by a third-body swing-by,
 * searched over years rather than one synodic period (`assist`); and, for
 * drives that can't burn at all, an ion-engine spiral out of one well and down
 * into the other, no Lambert arc or launch energy involved (`low-thrust`).
 *
 * A route says what a trip costs, not where it goes — `path` re-derives the
 * arcs from the same inputs the route was priced from and walks them with
 * `propagate`, so geometry and ladder can't disagree because neither is stored.
 *
 * Scope limits: transfers are patched-conic legs about one primary (a moon
 * needs its own leg from its planet), a swing-by route carries exactly one
 * pass, only the zero-revolution Lambert branch is solved, and the manoeuvre
 * model is published loss factors rather than an optimiser. See the constants
 * module for every approximation by name.
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
	endOrbitNormal,
	endDepartureOrbit,
	injectionDv,
	orbitPeriodHours,
	parkingOrbit,
	parkingRadiusKm,
	periapsisRaiseDv,
	planeChangeDv,
	planeReachDeg,
	speedAtRadius
} from './maneuvers';

export type { OrbitChangeEnds, Route, RouteLeg, RouteOptions, LegKind } from './route';
export {
	arrivalLegs,
	buildRoute,
	orbitChangeEnds,
	routeDurationDays,
	routeEndJd,
	SAME_RADIUS_KM
} from './route';

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
	BELT_PROFILES,
	BELT_SHIELDING_FLOOR,
	CANCER_RISK_PER_SV,
	DEFAULT_SHIELDING_G_CM2,
	JPL_SHELL_G_CM2,
	LETHAL_DOSE_GY,
	MODELLED_BELT_IDS,
	beltAttenuation,
	beltPassDoseGy,
	beltRateGyPerDay,
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
	fastestArcDays,
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
