/**
 * Trajectory compute layer for the trip planner. Pure: it takes bodies and
 * dates and returns routes. It reads nothing from the fetch or scene layers.
 *
 * Main pipeline:
 *
 *   elements → state vectors → Lambert arc → v∞ at each end
 *            → departure and arrival costs → a route of priced legs
 *
 * A porkchop sweep over departure date and cruise length gives the fast,
 * balanced and efficient routes. Other route shapes:
 * - `brachistochrone`: a held drive for fictional ships with no Δv limit.
 * - `assist`: two Lambert arcs joined by a swing-by past a third body.
 * - `low-thrust`: a spiral out of one well and into the other.
 * - `interstellar`: a straight crossing between two star systems.
 *
 * A route gives the cost of a trip, not its shape. `path` builds the arcs again
 * from the inputs of the route, so the drawing and the costs always agree.
 *
 * Limits: each transfer is a patched conic about one primary, a swing-by route
 * has one pass, and only the zero-revolution Lambert branch is solved. The
 * manoeuvre costs use published loss factors, not an optimiser. The constants
 * module names each approximation.
 */

export { GM_SUN_KM3_S2, HILL_STABLE_FRACTION, PARKING_ALTITUDE_KM } from './constants';

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
	endOrbitPreviewRing,
	endDepartureOrbit,
	injectionDv,
	orbitPeriodHours,
	parkingAltitudeKm,
	parkingOrbit,
	parkingRadiusKm,
	periapsisRaiseDv,
	planeChangeDv,
	planeReachDeg,
	speedAtRadius
} from './maneuvers';

export type {
	InterstellarCrossing,
	OrbitChangeEnds,
	Route,
	RouteBase,
	RouteLeg,
	RouteOptions,
	LegKind
} from './route';
export {
	arrivalLegs,
	buildRoute,
	finishRoute,
	LEG_END,
	orbitChangeEnds,
	routeDurationDays,
	routeEndJd,
	routeShipDays,
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

export type {
	CrossingSweep,
	InterstellarCruiseOptions,
	InterstellarDrive,
	InterstellarOptions,
	InterstellarRefusal,
	InterstellarTorchOptions,
	RapidityRate,
	SystemEnd,
	Well
} from './interstellar';
export {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	crossingElapsed,
	crossingIntegral,
	crossingSweep,
	fastestCrossingEndJd,
	interstellarDrive
} from './interstellar';

export {
	DUST_MASS_KG_M3,
	MEASURED_GRAIN_RADIUS_M,
	grainMassKg,
	grainsAbove,
	largestGrainRadiusM
} from './dust';

export {
	GAS_DOSE,
	INTERSTELLAR_N_H_CM3,
	gasKineticMeV,
	hullDoseFromRest,
	hullDosePerProton
} from './gas';

export type { RadiationShield } from './shield';
export { CONCRETE_CAP_M, ISS_DOSE_SV_PER_DAY, radiationShield } from './shield';

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
	COSMIC_RAY_BOOST,
	DEFAULT_SHIELDING_G_CM2,
	HELIOPAUSE_AU,
	INTERSTELLAR_DOSE_SV_PER_DAY,
	JPL_SHELL_G_CM2,
	LETHAL_DOSE_GY,
	MODELLED_BELT_IDS,
	beltAttenuation,
	beltPassDoseGy,
	beltRateGyPerDay,
	beltShieldingFactor,
	cancerRiskFraction,
	cosmicRayBoost,
	cosmicRayBoostFromRest,
	decimalYearOf,
	gcrDoseRateSvPerDay,
	interstellarDoseRateSvPerDay,
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

export type {
	EdgeKind,
	StationKind,
	SubwayBodies,
	SubwayBody,
	SubwayEdge,
	SubwayMap,
	SubwayRoute,
	SubwayStation
} from './subway';
export { buildSubwayMap, stationId } from './subway';

export type { SolveResult } from './solver-client';
export { TravelSolver } from './solver-client';

export * as travelConstants from './constants';
