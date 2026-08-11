/**
 * What a trajectory puts the craft through, as opposed to what it costs.
 *
 * Two routes to the same place for the same Δv can be very different trips: one
 * dips inside Mercury's orbit, one spends a year where an array makes a
 * twenty-fifth of its Earth-orbit output, one passes behind the Sun with the
 * link down, one arrives by hitting an atmosphere at eleven kilometres a second.
 * None of that is visible in a Δv ladder, and all of it is a property of the
 * trajectory rather than of the destination.
 *
 * **Nothing here carries a position.** A hazard is dates and figures; the map
 * turns a date into a place with `craftPositionAt`. That is what lets one scan
 * feed the row you choose from, the detail you read and the arc on the map
 * without the three ever disagreeing about where a threshold falls.
 *
 * The geometry is re-derived rather than stored, the same rule `path.ts` runs
 * on: the scan rebuilds the trajectory from the inputs the route was priced
 * from, at its own fixed sample count, so a hazard is a deterministic function
 * of the route and never of how finely something else happened to draw it.
 */

import {
	beltPassDoseGy,
	buildTrajectoryPath,
	CANCER_RISK_PER_SV,
	DEFAULT_SHIELDING_G_CM2,
	elementsToState,
	gcrDoseRateSvPerDay,
	LETHAL_DOSE_GY,
	MODELLED_BELT_IDS,
	norm,
	sub,
	travelConstants,
	type Route,
	type TravelBody,
	type Vec3,
	type Vehicle
} from '$lib/math/travel';
import { crossingWindow } from '$lib/math/travel/path-sample';
import { AU_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { sunsAt } from './sunlight';

export type HazardKind =
	/** Close enough to the Sun that the heat is a design problem. */
	| 'solar-heat'
	/** Far enough out that sunlight stops being a usable power source. */
	| 'solar-power'
	/** The Sun between the craft and where it left from: no link. */
	| 'conjunction'
	/** Far enough that nothing can be flown, only sent instructions and waited on. */
	| 'signal-lag'
	/** The arrival is flown through air, which takes hardware built for it. */
	| 'aeroassist'
	/** Cosmic rays, accumulated over the whole crossing. */
	| 'radiation'
	/** A swing-by flown through a planet's trapped-particle belts. */
	| 'belt-crossing';

export type HazardSeverity = 'notice' | 'caution' | 'severe';

const SEVERITY_RANK: Record<HazardSeverity, number> = { notice: 0, caution: 1, severe: 2 };

/** A stretch of trip at one tier, for the map to draw the arc in. */
export interface HazardBand {
	severity: HazardSeverity;
	startJd: number;
	endJd: number;
}

export interface Hazard {
	kind: HazardKind;
	severity: HazardSeverity;
	/** The stretch of trip it covers. Equal to `startJd` for a moment. */
	startJd: number;
	endJd: number;
	/** When it is at its worst — the date the figure below was read at, and the
	 *  point the map hangs its marker off. */
	peakJd: number;
	/**
	 * The figure the severity was read off, in the kind's own unit: multiples of
	 * Earth-orbit sunlight for heat, the same quantity as a fraction for power,
	 * degrees for a conjunction, seconds for the lag, km/s for an entry.
	 */
	peak: number;
	/** Distance from the Sun at the peak, AU. Only on the kinds that are about one. */
	auAtPeak?: number;
	/**
	 * The rate behind an accumulated figure, in the kind's unit per day. Only on
	 * `radiation`, whose `peak` is a trip integral rather than a moment: without
	 * this there is no way to say whether a sievert was collected in a fortnight
	 * or over nine years.
	 */
	rateAtPeak?: number;
	/**
	 * The hazard is real and its size is not known — a belt nobody has published
	 * a dose profile for. Distinct from a `peak` of zero, which would be a claim
	 * that crossing it is free.
	 */
	unpriced?: boolean;
	/** The body a moment happens at. Only on the kinds that pick one out. */
	bodyId?: string;
	/**
	 * The stretch broken into the tiers actually in force along it, in flight
	 * order — what the map paints the arc with. Empty when there is nothing to
	 * paint, which is how a hazard says it is not about a place.
	 *
	 * Split rather than one band at the worst tier, because a stretch drawn in one
	 * colour claims the whole of it is as bad as its worst point: a trip inside
	 * Venus's orbit would read as sunshade country from the moment it crossed,
	 * when that only becomes true near perihelion.
	 */
	bands: readonly HazardBand[];
}

/**
 * How finely the trajectory is walked, days per sample.
 *
 * Set by the narrowest thing being looked for rather than by the smoothest.
 * A perihelion is quadratic in time and would be found by a dozen samples over
 * any trip; a conjunction is a fortnight somewhere inside a crossing that can
 * run for years, and a scan that steps over it reports no blackout at all. Two
 * days finds one and places its ends about as well as taking the Sun to sit at
 * the barycentre does.
 */
const HAZARD_SAMPLE_DAYS = 2;
const MIN_HAZARD_SAMPLES = 64;
/** A decade-long crossing would otherwise ask for thousands. Past this the
 *  spacing widens again, which is the honest trade: the alternative is making
 *  the panel wait on a scan nobody asked for. */
const MAX_HAZARD_SAMPLES = 1024;

/**
 * The sample count for a route — a function of the route alone, so the list, the
 * detail and the map cannot land on different sides of a threshold.
 */
function hazardSamples(route: Route): number {
	const wanted = Math.round(route.tofDays / HAZARD_SAMPLE_DAYS);
	return Math.min(MAX_HAZARD_SAMPLES, Math.max(MIN_HAZARD_SAMPLES, wanted));
}

/**
 * Both distance hazards are really thresholds on a **place**, so they are
 * written as distances and turned into the figure the panel quotes. Putting them
 * the other way round hides what they mean and makes them impossible to check.
 *
 * Going in: Venus's orbit is where thermal design starts; 0.45 AU is where it
 * dominates; 0.30 AU is inside Mercury's perihelion, where MESSENGER and
 * BepiColombo both needed a sunshade rather than a design — the step from "hot"
 * to "a different kind of craft".
 */
const HEAT_AU = { notice: 0.71, caution: 0.45, severe: 0.3 };
const HEAT_SUNS: Thresholds = {
	notice: sunsAt(HEAT_AU.notice),
	caution: sunsAt(HEAT_AU.caution),
	severe: sunsAt(HEAT_AU.severe)
};

/**
 * Going out, the tiers are drawn either side of the two orbits solar power has
 * actually been flown to, so neither of them is called a problem.
 *
 * 1.38 AU is Mars at perihelion: from there out sunlight is under half of
 * Earth's and arrays are sized for it, which is worth knowing and nothing more —
 * Mars is where solar spacecraft go. 1.67 AU clears Mars's aphelion, so the
 * middle tier starts past its orbit rather than inside it. 5.5 AU clears
 * Jupiter's, where Juno, JUICE and Europa Clipper all fly on panels: enormous
 * ones, which is exactly the middle tier. Only past Jupiter has nothing solar
 * ever gone.
 */
const POWER_AU = { notice: 1.38, caution: 1.67, severe: 5.5 };
const POWER_FRACTION: Thresholds = {
	notice: sunsAt(POWER_AU.notice),
	caution: sunsAt(POWER_AU.caution),
	severe: sunsAt(POWER_AU.severe)
};

/**
 * Sun–origin–craft angle, degrees: how close to the Sun the craft appears from
 * the place it left. Five degrees is where the link starts losing data to solar
 * noise, and inside two JPL stops commanding Mars orbiters altogether.
 *
 * One tier and no more, however close it gets. A conjunction is a fortnight of
 * silence on a calendar every mission plans around; it costs no hardware and
 * changes no trajectory, so it is something to know rather than something to
 * answer.
 */
const CONJUNCTION_DEG: Thresholds = { notice: 5 };

/**
 * One-way light time, seconds. Five minutes is the end of anything resembling
 * supervision — Mars runs 4 to 24 — and half an hour is Jupiter.
 *
 * It stops there. Past that the lag stops being a matter of degree: nothing is
 * flown from here at any distance, and a craft that copes with an hour copes
 * with four. Both of these are about the link, and the link is never what a
 * different spacecraft would fix.
 */
const LAG_SECONDS: Thresholds = { notice: 300, caution: 1800 };

/**
 * Speed the craft meets the air at, km/s.
 *
 * Any of it takes a heat shield, so the mildest tier is every atmospheric
 * arrival. Above 8 is a return from another body rather than an entry from
 * orbit — Apollo came back at 11.0 — and above 13 is Galileo's probe territory,
 * which met Jupiter at 47.4 behind a shield that was half the probe's mass.
 */
const ENTRY_KMS: Thresholds = { notice: 0, caution: 8, severe: 13 };

/**
 * Cosmic ray dose over the whole trip, sieverts.
 *
 * Absolute, not a fraction of anybody's career limit. Those are policy — they
 * differ between agencies, they have moved twice in twenty years, and quoting a
 * percentage of one turns a physical quantity into an administrative one.
 *
 * The upper two tiers are placed on added lifetime cancer risk instead, at
 * ICRP's nominal 4.1% per Sv, and written as the risk rather than the dose so
 * that moving the coefficient moves them with it. A quarter and a half.
 *
 * Those are deliberately high, and the effect is that almost every trip anyone
 * would fly sits in the mildest tier: a Mars round trip is 1.59 Sv at worst,
 * which is under 7%. The tiers are for the trips that are actually a problem —
 * a decade in the outer system reaches a quarter, and nothing crewed has ever
 * been proposed that reaches a half.
 *
 * None of this is about dying of the trip. A sievert collected over ten years
 * produces no radiation sickness at all, which is the whole reason this is a
 * different quantity from a belt pass.
 */
const TRIP_DOSE_SV: Thresholds = {
	notice: 0.1,
	caution: 0.25 / CANCER_RISK_PER_SV,
	severe: 0.5 / CANCER_RISK_PER_SV
};

/**
 * Absorbed dose of one belt pass, grays.
 *
 * A different quantity from the one above and deliberately not summed with it:
 * these are the tiers of acute injury, not of lifetime risk.
 *
 * Both upper tiers are fractions of `LETHAL_DOSE_GY` rather than doses written
 * out, because the row quotes the figure as a percentage of exactly that: red
 * begins at one whole lethal dose and amber at half of one, so the colour and
 * the number on screen say the same thing. The mildest tier is well under any
 * symptom threshold and exists so that a small pass still gets a line — "4% of
 * a lethal dose" is worth saying.
 *
 * Severity is read off the central estimate, like every other hazard here. The
 * band the row prints beside it is wide enough near the top tier to cross it,
 * which is the model's honest state and not something to resolve by escalating.
 *
 * Judged on the dose behind the assumed hull, which is what a crew would take.
 * Unshielded is about a hundred times worse.
 */
const BELT_PASS_GY: Thresholds = {
	notice: 0.1,
	caution: 0.5 * LETHAL_DOSE_GY,
	severe: LETHAL_DOSE_GY
};

/** Which way a kind gets worse: with a rising figure, or with a falling one. */
type Direction = 'rising' | 'falling';

/** A kind may leave a tier out — a conjunction is either interfering with the
 *  link or it is not, and there is no mild version of it worth a row. */
type Thresholds = Partial<Record<HazardSeverity, number>>;

/** The mildest figure that is worth reporting at all, which is also where a
 *  hazard's stretch is measured from. */
function mildest(thresholds: Thresholds): number {
	return thresholds.notice ?? thresholds.caution ?? thresholds.severe!;
}

function severityFor(
	peak: number,
	thresholds: Thresholds,
	direction: Direction
): HazardSeverity | null {
	const past = (limit: number | undefined) =>
		limit !== undefined && (direction === 'rising' ? peak >= limit : peak <= limit);
	if (past(thresholds.severe)) return 'severe';
	if (past(thresholds.caution)) return 'caution';
	if (past(thresholds.notice)) return 'notice';
	return null;
}

/** One point on the trajectory, with everything the scan reads off it. */
interface Sample {
	jd: number;
	/** Distance from the Sun, AU. */
	au: number;
	/** Sunlight there, as a multiple of 1 AU's. */
	suns: number;
	/** Angle at the origin between the Sun and the craft, degrees. */
	sepDeg: number;
	/** One-way light time back to the origin, seconds. */
	lagSec: number;
	/** Cosmic ray dose equivalent rate in free space here, Sv/day. */
	doseSvPerDay: number;
}

/** Sunlight is one quantity read two ways, so both distance hazards scan the
 *  same field and differ only in which direction is the bad one. */
const sunsOf = (sample: Sample): number => sample.suns;

interface Span {
	startJd: number;
	endJd: number;
	peakJd: number;
	peak: number;
	auAtPeak: number;
	/** The stretch split at every tier change along it, in flight order. */
	bands: HazardBand[];
}

/**
 * The worst the trip gets, and the unbroken stretch around it.
 *
 * The stretch is grown out from the peak rather than drawn between the first and
 * last samples that qualify. A trip to Saturn passes through six conjunctions as
 * the Earth laps the Sun under it; bounding them all as one would report a
 * six-year blackout, which is not a thing that happens. One episode, the worst
 * one, is what a reader can do something with. Null when the threshold is never
 * met.
 */
function spanOf(
	samples: readonly Sample[],
	value: (sample: Sample) => number,
	thresholds: Thresholds,
	direction: Direction
): Span | null {
	const threshold = mildest(thresholds);
	const worseThan = (a: number, b: number) => (direction === 'rising' ? a > b : a < b);
	const past = (v: number) => (direction === 'rising' ? v >= threshold : v <= threshold);

	let peakIndex = -1;
	for (let i = 0; i < samples.length; i++) {
		const current = value(samples[i]);
		if (!past(current)) continue;
		if (peakIndex < 0 || worseThan(current, value(samples[peakIndex]))) peakIndex = i;
	}
	if (peakIndex < 0) return null;

	let first = peakIndex;
	while (first > 0 && past(value(samples[first - 1]))) first--;
	let last = peakIndex;
	while (last < samples.length - 1 && past(value(samples[last + 1]))) last++;

	// Split where the tier changes, so the arc reddens as it approaches the worst
	// of it rather than being red for the whole of a stretch that is mostly mild.
	const bands: HazardBand[] = [];
	for (let i = first; i <= last; i++) {
		const severity = severityFor(value(samples[i]), thresholds, direction)!;
		const open = bands[bands.length - 1];
		if (open && open.severity === severity) open.endJd = samples[i].jd;
		else bands.push({ severity, startJd: samples[i].jd, endJd: samples[i].jd });
	}
	// Each band reaches the next one's first sample, or the tiers would be drawn
	// with a sample-wide gap between them.
	for (let i = 0; i < bands.length - 1; i++) bands[i].endJd = bands[i + 1].startJd;

	return {
		startJd: samples[first].jd,
		endJd: samples[last].jd,
		peakJd: samples[peakIndex].jd,
		peak: value(samples[peakIndex]),
		auAtPeak: samples[peakIndex].au,
		bands
	};
}

/**
 * Which hazards are a **place** on the trip rather than a fact about the whole
 * of it, and so which get drawn along the arc.
 *
 * The lag and the power both hold for most of a crossing by the time they hold
 * at all — banding them paints the entire trajectory, which says nothing about
 * where anything happens and buries the two that do. They keep their marker,
 * their chip and their row; what they lose is the claim that some part of the
 * trip is worse than the rest, which for those two is not true.
 */
const BANDED: ReadonlySet<HazardKind> = new Set<HazardKind>(['solar-heat', 'conjunction']);

/** A hazard off a span, at the severity its worst figure earns. Null when the
 *  figure never reaches even the mildest tier. */
function fromSpan(
	kind: HazardKind,
	span: Span | null,
	thresholds: Thresholds,
	direction: Direction,
	options: { withAu?: boolean } = {}
): Hazard | null {
	if (!span) return null;
	const severity = severityFor(span.peak, thresholds, direction);
	if (!severity) return null;
	return {
		kind,
		severity,
		startJd: span.startJd,
		endJd: span.endJd,
		peakJd: span.peakJd,
		peak: span.peak,
		auAtPeak: options.withAu ? span.auAtPeak : undefined,
		bands: BANDED.has(kind) ? span.bands : []
	};
}

export interface HazardContext {
	/** The body the trajectory's positions are measured from. */
	centerId: string;
	/** μ of that body, km³/s². Defaults to the Sun's. */
	centralMu?: number;
	/** Set when the trip stays inside one system — see `RouteOptions`. */
	systemPrimary?: 'departure' | 'target';
	/** Bodies a swing-by route passes; without the right one its second arc
	 *  cannot be rebuilt and the scan has no geometry to read. */
	vias?: readonly TravelBody[];
	retrograde?: boolean;
}

/**
 * Frames a distance from the centre is a distance from the **Sun** in.
 *
 * The barycentre is in the list because it stands in for the Sun to within
 * 0.0055 AU, which is nothing against any threshold here.
 *
 * This is a question about the *centre*, not about the kind of transfer, and
 * getting that wrong is what left a trip to the Sun itself with no heat hazard
 * at all: `Earth → Sun` is a **system** transfer whose primary happens to be the
 * Sun, and a trip between two comets is a **sibling** transfer about it. Both
 * measure from the Sun; neither is what the kernel calls heliocentric. Only a
 * trip inside a planet's own system measures from something else, and there the
 * scan says nothing rather than something false.
 */
const SOLAR_CENTERS: ReadonlySet<string> = new Set(['naif-10', 'naif-0']);

function aboutTheSun(context: HazardContext): boolean {
	return SOLAR_CENTERS.has(context.centerId);
}

/**
 * Everything `route` puts the craft through, worst first.
 *
 * The atmospheric arrival is read off the route itself and is reported whatever
 * frame the trip is in; the other four need the shape of the trajectory, and are
 * left out when there is none to rebuild or when it does not go round the Sun.
 */
export function routeHazards(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	context: HazardContext
): Hazard[] {
	const hazards: Hazard[] = [];

	const entry = aeroHazard(route);
	if (entry) hazards.push(entry);

	// Independent of the frame: a swing-by is priced from its own periapsis and
	// speed, not from the trajectory the scan walks.
	hazards.push(...beltHazards(route, context.vias ?? []));

	if (aboutTheSun(context)) {
		const samples = scan(departure, target, route, context);
		const dose = radiationHazard(samples);
		if (dose) hazards.push(dose);
		const found = [
			fromSpan('solar-heat', spanOf(samples, sunsOf, HEAT_SUNS, 'rising'), HEAT_SUNS, 'rising', {
				withAu: true
			}),
			fromSpan(
				'solar-power',
				spanOf(samples, sunsOf, POWER_FRACTION, 'falling'),
				POWER_FRACTION,
				'falling',
				{
					withAu: true
				}
			),
			fromSpan(
				'conjunction',
				spanOf(samples, (s) => s.sepDeg, CONJUNCTION_DEG, 'falling'),
				CONJUNCTION_DEG,
				'falling'
			),
			fromSpan(
				'signal-lag',
				spanOf(samples, (s) => s.lagSec, LAG_SECONDS, 'rising'),
				LAG_SECONDS,
				'rising'
			)
		];
		for (const hazard of found) if (hazard) hazards.push(hazard);
	}

	return sortHazards(hazards);
}

/** Declaration order of {@link HazardKind}, so equal-severity hazards line up
 *  the same way on every route instead of shuffling with their dates. */
const KIND_RANK: Record<HazardKind, number> = {
	'solar-heat': 0,
	'solar-power': 1,
	conjunction: 2,
	'signal-lag': 3,
	aeroassist: 4,
	radiation: 5,
	'belt-crossing': 6
};

/** Worst first, then by kind, then the one met first. */
export function sortHazards(hazards: Hazard[]): Hazard[] {
	return hazards.sort(
		(a, b) =>
			SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
			KIND_RANK[a.kind] - KIND_RANK[b.kind] ||
			a.startJd - b.startJd
	);
}

/**
 * The arrival, when it is flown through air.
 *
 * `entrySpeedKms` is set exactly when the atmosphere was asked to do some of the
 * work, which is the same test the feasibility check uses to decide a craft needs
 * something to fly a pass behind. A propulsive landing through the same air is
 * not one of these: nothing is being asked of the atmosphere, so nothing has to
 * survive it.
 */
function aeroHazard(route: Route): Hazard | null {
	const entrySpeedKms = route.entrySpeedKms;
	if (entrySpeedKms === undefined) return null;
	const severity = severityFor(entrySpeedKms, ENTRY_KMS, 'rising');
	if (!severity) return null;
	// The campaign that follows the first pass, where there is one. The fastest
	// pass is the first: every one after it arrives on a slower orbit.
	const campaignDays = route.legs.reduce(
		(sum, leg) => (leg.kind === 'aerobrake' ? sum + leg.days : sum),
		0
	);
	return {
		kind: 'aeroassist',
		severity,
		startJd: route.arriveJd,
		endJd: route.arriveJd + campaignDays,
		peakJd: route.arriveJd,
		peak: entrySpeedKms,
		// Nothing to paint: the pass happens where the arc ends, and the campaign
		// after it is flown round the destination rather than along the way there.
		bands: []
	};
}

/**
 * Below this the craft has not really left, and the angle it makes with the Sun
 * is the noise in a difference of two nearly equal vectors rather than a
 * geometry — at the departure sample it is a difference of zero. A hundredth of
 * an AU; nothing is out of contact at that range, so those samples are reported
 * as pointing straight away from the Sun rather than being left out, which would
 * put a hole in the middle of every other hazard's stretch.
 */
const CONJUNCTION_FLOOR_KM = 0.01 * AU_KM;

const RAD_TO_DEG = 180 / Math.PI;

/** Walk the rebuilt trajectory, reading off everything the hazards are judged on. */
function scan(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	context: HazardContext
): Sample[] {
	const centralMu = context.centralMu ?? travelConstants.GM_SUN_KM3_S2;
	const path = buildTrajectoryPath(departure, target, route, {
		centerId: context.centerId,
		centralMu,
		systemPrimary: context.systemPrimary,
		retrograde: context.retrograde,
		vias: context.vias,
		samples: hazardSamples(route)
	});
	if (!path) return [];

	// The trip leaves from the frame's centre when the centre is the origin —
	// leaving the Sun for somewhere. Its own elements describe a different orbit
	// then (the Sun's about the barycentre), and differencing against those would
	// misplace the craft and point the conjunction test at nothing.
	const originAtCenter = departure.id === context.centerId;

	const samples: Sample[] = [];
	for (const [index, arc] of path.arcs.entries()) {
		// Only the crossing proper. Past the trim the conic runs on to the body's
		// centre, which is not where the craft goes — and at the Sun that is a
		// sample at nought AU reporting an infinity of sunlight.
		const { from, to } = crossingWindow(path, index);
		for (let i = from; i < to; i++) {
			const sample = sampleAt(arc.points[i], arc.jds[i], departure, centralMu, originAtCenter);
			if (sample) samples.push(sample);
		}
	}
	return samples;
}

/** One point on the trajectory turned into the figures the thresholds are read
 *  against. Null when the origin's position at that date is unavailable. */
function sampleAt(
	r: Vec3,
	jd: number,
	origin: TravelBody,
	centralMu: number,
	originAtCenter: boolean
): Sample | null {
	const au = norm(r) / AU_KM;
	if (!(au > 0) || !Number.isFinite(au)) return null;

	const home = originAtCenter
		? { r: [0, 0, 0] as Vec3 }
		: elementsToState(origin.elements, jd, centralMu);
	if (!home) return null;
	const toCraft = sub(r, home.r);
	const separationKm = norm(toCraft);

	// The Sun is taken to sit at the barycentre the elements are referenced to.
	// It is about 0.8 M km off it, which is roughly 0.3° of conjunction angle at
	// Earth's distance — a couple of days at either end of a blackout, and not
	// worth carrying the Sun's own ephemeris through this module to correct.
	const toSun = [-home.r[0], -home.r[1], -home.r[2]] as Vec3;
	const sunKm = norm(toSun);
	const cosine =
		separationKm > CONJUNCTION_FLOOR_KM && sunKm > 0
			? (toCraft[0] * toSun[0] + toCraft[1] * toSun[1] + toCraft[2] * toSun[2]) /
				(separationKm * sunKm)
			: -1;

	return {
		jd,
		au,
		suns: sunsAt(au),
		sepDeg: Math.acos(Math.min(1, Math.max(-1, cosine))) * RAD_TO_DEG,
		lagSec: separationKm / SPEED_OF_LIGHT_KM_S,
		doseSvPerDay: gcrDoseRateSvPerDay(jd, au)
	};
}

/**
 * Cosmic rays over the whole crossing, integrated along the samples.
 *
 * Trapezoid, because the rate varies smoothly and slowly — it is a percent per
 * tenth of an AU and a factor of 2.4 across eleven years, so the two-day
 * sampling the conjunction test needs is far finer than this term wants.
 *
 * The craft is taken to be in free space for all of it. That understates a trip
 * that spends time low over a body, which blocks half the sky, and overstates
 * nothing — so the cruise figure is an upper bound on its own terms, and the
 * ends of the trip are where it is loosest.
 */
function cruiseDose(samples: readonly Sample[]): {
	sv: number;
	peakRate: number;
	peakJd: number;
} {
	let sv = 0;
	let peakRate = 0;
	let peakJd = samples.length > 0 ? samples[0].jd : 0;
	for (let i = 0; i < samples.length; i++) {
		if (samples[i].doseSvPerDay > peakRate) {
			peakRate = samples[i].doseSvPerDay;
			peakJd = samples[i].jd;
		}
		if (i === 0) continue;
		const days = samples[i].jd - samples[i - 1].jd;
		sv += ((samples[i].doseSvPerDay + samples[i - 1].doseSvPerDay) / 2) * days;
	}
	return { sv, peakRate, peakJd };
}

/**
 * Bodies with belts worth naming a pass through. Wider than the set that has a
 * dose profile, which is the point: passing Saturn is worth a line saying the
 * cost is unknown, and passing Mars is not worth a line at all.
 */
const BELTED_BODY_IDS: ReadonlySet<string> = new Set([
	'naif-599',
	'naif-699',
	'naif-799',
	'naif-899',
	'naif-399'
]);

/**
 * The cosmic ray total as a hazard, from an already-walked trajectory.
 *
 * The figure is the whole trip's dose in sieverts rather than a rate at a
 * moment, which makes this the one kind whose `peak` is an integral. It is not
 * banded: the rate varies by a few percent across an inner-system crossing, so
 * painting the arc with it would claim a structure that is not there.
 */
function radiationHazard(samples: readonly Sample[]): Hazard | null {
	if (samples.length < 2) return null;
	const { sv, peakRate, peakJd } = cruiseDose(samples);
	const severity = severityFor(sv, TRIP_DOSE_SV, 'rising');
	if (!severity) return null;
	return {
		kind: 'radiation',
		severity,
		startJd: samples[0].jd,
		endJd: samples[samples.length - 1].jd,
		peakJd,
		peak: sv,
		rateAtPeak: peakRate,
		bands: []
	};
}

/**
 * Each swing-by through a belt, as its own moment.
 *
 * One per pass rather than a total, because they happen in different places to
 * different degrees and a summed figure would hide which one was the problem.
 */
function beltHazards(route: Route, vias: readonly TravelBody[]): Hazard[] {
	const hazards: Hazard[] = [];
	for (const pass of route.flybys ?? []) {
		if (!BELTED_BODY_IDS.has(pass.bodyId)) continue;
		const body = vias.find((candidate) => candidate.id === pass.bodyId);
		const moment = { startJd: pass.jd, endJd: pass.jd, peakJd: pass.jd, bands: [] };

		if (!body || !MODELLED_BELT_IDS.has(pass.bodyId)) {
			// Known to be a belt and not known how bad. Reported at the middle
			// tier: calling it mild would be a claim, and calling it severe would
			// be the same claim in the other direction.
			hazards.push({
				kind: 'belt-crossing',
				severity: 'caution',
				peak: 0,
				unpriced: true,
				bodyId: pass.bodyId,
				...moment
			});
			continue;
		}

		const gy = beltPassDoseGy(
			body.radiusKm + pass.altitudeKm,
			(pass.vInfInKms + pass.vInfOutKms) / 2,
			DEFAULT_SHIELDING_G_CM2,
			body.radiusKm,
			body.mu
		);
		const severity = severityFor(gy, BELT_PASS_GY, 'rising');
		if (!severity) continue;
		hazards.push({
			kind: 'belt-crossing',
			severity,
			peak: gy,
			bodyId: pass.bodyId,
			...moment
		});
	}
	return hazards;
}

/** Why a hazard reads differently once a craft is chosen. */
export type CraftNote =
	/** It does not run on sunlight, so the dark stretch costs it nothing. */
	| { kind: 'nuclear-power' }
	/** The entry is faster than the shield is published to survive. */
	| { kind: 'entry-rating'; ratedKms: number };

export interface AdjustedHazard extends Hazard {
	/** Absent when the craft has nothing to say about this hazard. */
	craftNote?: CraftNote;
}

/**
 * The same hazards read against the craft that would fly them.
 *
 * Kept off the list of trajectories on purpose: a row there is a statement about
 * where the trip goes, and it should not change severity because a craft was
 * picked — least of all during the window after a shared link names one and
 * before the catalogue lands, when nothing about it is knowable.
 *
 * Nothing is ever removed. A cruise beyond Jupiter is still a cold, dark cruise
 * with an RTG aboard; what changes is whether it is a problem.
 */
export function adjustForVehicle(
	hazards: readonly Hazard[],
	vehicle: Vehicle | null,
	route: Route
): AdjustedHazard[] {
	if (!vehicle) return [...hazards];
	const nuclear = vehicle.power === 'rtg' || vehicle.power === 'nuclear';
	const ratedKms = vehicle.maxEntrySpeedKms?.value;
	const overRated =
		ratedKms !== undefined && route.entrySpeedKms !== undefined && route.entrySpeedKms > ratedKms;

	return sortHazards(
		hazards.map((hazard): AdjustedHazard => {
			if (hazard.kind === 'solar-power' && nuclear) {
				return { ...hazard, severity: 'notice', craftNote: { kind: 'nuclear-power' } };
			}
			if (hazard.kind === 'aeroassist' && overRated) {
				return { ...hazard, severity: 'severe', craftNote: { kind: 'entry-rating', ratedKms } };
			}
			return { ...hazard };
		})
	);
}
