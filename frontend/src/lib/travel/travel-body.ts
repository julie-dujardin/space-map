/**
 * Turning what the app already knows about a body into what the trajectory
 * kernel needs.
 *
 * The one subtlety is which orbit to hand over. A transfer is between two
 * *heliocentric* orbits, but Earth's own elements describe its motion about the
 * Earth-Moon barycentre, not about the Sun. So the elements come from the
 * body's heliocentric ancestor while the mass, radius and atmosphere — every
 * quantity the departure and arrival burns are priced against — come from the
 * body itself.
 */

import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { getAtmosphereParams } from '$lib/fetch/atmospheres';
import { OrbitalSource } from '$lib/fetch/position/format';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { bodyQuaternion, type Orientation } from '$lib/math/orientation';
import { J2000_JD } from '$lib/time/jd';
import { estimateMu, muFromElements, type TravelBody } from '$lib/math/travel';
import { AU_KM } from '$lib/math/units';
import type { Vec3 } from '$lib/math/travel/vec3';

const DEG2RAD = Math.PI / 180;
const SEC_PER_DAY = 86400;

/**
 * How fast the body turns, rad/s, sign dropped — a retrograde spin is still a
 * free ride, taken the other way round.
 */
function spinRadPerSec(orientation: Orientation | undefined): number | undefined {
	if (!orientation) return undefined;
	const rate = (Math.abs(orientation.w1) * DEG2RAD) / SEC_PER_DAY;
	return rate > 0 ? rate : undefined;
}

/**
 * The body's north pole as a unit vector in ecliptic J2000 axes.
 *
 * Taken from the same quaternion the globe is drawn with, so the equator the
 * kernel measures a plane against is the one the map shows. Read at J2000: the
 * pole moves hundredths of a degree per century and all it feeds is a cosine.
 */
function poleEcliptic(orientation: Orientation | undefined): Vec3 | undefined {
	if (!orientation) return undefined;
	const p = new Vector3(0, 1, 0).applyQuaternion(bodyQuaternion(orientation, J2000_JD));
	// Scene axes back to ecliptic: the inverse of `eclipticToScene`.
	return [p.x, -p.z, p.y];
}

/** NAIF ids at or below this are the Sun and the planetary barycentres. */
const SUN_ID = 10;
const SSB_ID = 0;
const SUN_OBJECT_ID = `naif-${SUN_ID}`;
const SSB_OBJECT_ID = `naif-${SSB_ID}`;

/** Numeric part of a `naif-<n>` id; null for any other prefix. */
export function naifId(objectId: string): number | null {
	if (!objectId.startsWith('naif-')) return null;
	const value = Number.parseInt(objectId.slice('naif-'.length), 10);
	return Number.isFinite(value) ? value : null;
}

/** True for the Sun or the solar-system barycentre — the roots of the walk. */
export function isHeliocentricRoot(objectId: string): boolean {
	const id = naifId(objectId);
	return id === SUN_ID || id === SSB_ID;
}

/**
 * How the walk finds a parent. A function rather than a map because the bodies
 * a trip needs come from several places — the scene's own index, and the
 * catalogue for anything it never loaded.
 */
export type BodyLookup = (id: string) => BodyData | null | undefined;

/** The lookup a plain map makes. */
export function lookupIn(bodiesById: ReadonlyMap<string, BodyData>): BodyLookup {
	return (id) => bodiesById.get(id);
}

/** How many links up the chain to follow. Real chains are three or four; the
 *  cap only guards against a cycle in malformed data. */
const MAX_HOPS = 8;

/**
 * The ancestor whose orbit is about the Sun.
 *
 * Earth resolves to the Earth-Moon barycentre, Europa to the Jupiter
 * barycentre, an asteroid to itself. Returns null when the chain cannot be
 * walked — a body whose parent the lookup cannot produce has no heliocentric
 * orbit we can name.
 */
export function heliocentricAncestor(body: BodyData, lookup: BodyLookup): BodyData | null {
	const chain = ancestry(body, lookup);
	return chain ? chain[chain.length - 1] : null;
}

/**
 * Levels that are a reading at the surface, whatever shape that surface is
 * given. Mirrors `_DATUM_OF_LEVEL` in the exporter's atmosphere module — Earth
 * quotes sea level and Mars the areoid, and both are the ground.
 *
 * `one_bar` and `cloud_top` are levels inside an envelope with no surface under
 * them, so they are deliberately absent: the giants have no ground to ascend
 * from or land on, whatever their pressure is quoted at. What they do have is an
 * atmosphere, which `hasAtmosphere` carries separately.
 */
const SURFACE_LEVELS: ReadonlySet<string> = new Set(['surface', 'sea_level', 'areoid']);

/** Surface pressure in bar, or undefined when there is no reading at a surface. */
function surfacePressureBar(detail: GlobalObjectData | null): number | undefined {
	const pressure = detail?.atmosphere?.pressure;
	if (!pressure) return undefined;
	if (!SURFACE_LEVELS.has(pressure.level)) {
		console.debug(
			`[travel] ${detail?.id}: pressure quoted at "${pressure.level}", not a surface — no ground to ascend from or land on.`
		);
		return undefined;
	}
	if (!Number.isFinite(pressure.pa) || pressure.pa <= 0) return undefined;
	return pressure.pa / 1e5;
}

/**
 * Whether any envelope at all has been detected — Mercury's exosphere counts.
 *
 * Not the braking-pass question, which `aeroPressurePa` answers from the
 * measured pressure: this one only marks that an envelope exists, so a gas
 * giant reading at one bar with nothing underneath can be told apart from an
 * airless body. A body whose detail never loaded reports nothing rather than no.
 */
export function hasAtmosphere(detail: GlobalObjectData | null): boolean | undefined {
	const pressure = detail?.atmosphere?.pressure;
	if (!pressure) return undefined;
	return Number.isFinite(pressure.pa) && pressure.pa > 0;
}

/**
 * Pressure of the envelope at the level the body's radius names — the surface,
 * or the 1 bar datum on a giant — in Pa. What a braking pass is judged and
 * priced against, so it reports nothing at all for readings that are not an
 * envelope to fly through: an upper limit (Mercury's, for instance) is a
 * non-detection dressed as a number, and a stellar photosphere has no top to
 * skim and come back out of.
 */
export function aeroPressurePa(detail: GlobalObjectData | null): number | undefined {
	const atmosphere = detail?.atmosphere;
	const pressure = atmosphere?.pressure;
	if (!pressure || pressure.qualifier === 'upper_limit') return undefined;
	const structure = atmosphere.structure;
	if ((structure?.datum ?? pressure.level) === 'photosphere') return undefined;
	const pa = structure?.datum_pressure_pa ?? pressure.pa;
	return Number.isFinite(pa) && pa > 0 ? pa : undefined;
}

/**
 * Which orbit describes the body in the frame its trip is solved in: the one
 * about the Sun, or its own about whatever it goes round. A trip across the
 * solar system needs the first; a trip inside one system needs the second.
 */
export type OrbitChoice = 'heliocentric' | 'own';

/**
 * Build the kernel's view of `body`.
 *
 * `detail` is optional — without it the body is treated as airless, which only
 * changes whether the arrival gets an aerocapture discount.
 *
 * Returns null when the body has no orbit of the requested kind.
 */
export function toTravelBody(
	body: BodyData,
	lookup: BodyLookup,
	detail: GlobalObjectData | null = null,
	orbit: OrbitChoice = 'heliocentric'
): TravelBody | null {
	const chain = orbit === 'own' ? [body] : ancestry(body, lookup);
	if (!chain) return null;
	const ancestor = chain[chain.length - 1];
	// A trip is solved by propagating these years ahead, so the Sun-centred fit
	// wins wherever one exists — see `helioElements`. `own` orbits are already
	// about the body they go round.
	const source = (orbit === 'own' ? undefined : ancestor.helioElements) ?? ancestor;

	const radiusKm = Number.isFinite(body.radiusKm) && body.radiusKm > 0 ? body.radiusKm : 1;
	const id = naifId(body.id);
	const measuredMu = id === null ? undefined : getGmKm3s2(id);
	const aeroPa = aeroPressurePa(detail);

	const travel: TravelBody = {
		id: body.id,
		// Most of the catalogue has no measured mass; an assumed density is close
		// enough that capture and landing stay in the right order of magnitude.
		mu: measuredMu && measuredMu > 0 ? measuredMu : estimateMu(radiusKm),
		muEstimated: !(measuredMu && measuredMu > 0),
		radiusKm,
		elements: {
			a: source.a,
			e: source.e,
			i: source.i,
			om: source.om,
			w: source.w,
			ma: source.ma,
			n: source.n,
			epoch: source.epoch,
			omDot: source.omDot,
			wDot: source.wDot,
			// A parabolic comet carries these instead of a/ma/n; without them the
			// propagator has nothing to work from and the body cannot be a trip end.
			q: source.q,
			tp: source.tp,
			equatorial: source.equatorial
		},
		surfacePressureBar: surfacePressureBar(detail),
		hasAtmosphere: hasAtmosphere(detail),
		aeroPressurePa: aeroPa,
		// The render pipeline's fitted scale height — the one per-body vertical
		// profile the app ships — so the kernel can put the pass where the density
		// is instead of at one Mars-calibrated altitude.
		aeroScaleHeightKm:
			aeroPa === undefined ? undefined : getAtmosphereParams(body.id)?.rayleighScaleHeightKm,
		spinRadPerSec: spinRadPerSec(detail?.orientation),
		poleEcliptic: poleEcliptic(detail?.orientation),
		parentId: body.parentId
	};
	travel.borrowedElements = straysFromElements(chain, travel);
	return travel;
}

/**
 * Whether the elements put the body somewhere it is not.
 *
 * Every body in a heliocentric plan flies on an ancestor's ellipse, so "the
 * elements are someone else's" cannot be the test: a planet borrows its own
 * system barycentre, which for the Earth-Moon pair sits 4700 km from Earth's
 * centre — inside the planet. The body itself is the scale that decides. A
 * centre under the surface is the body's own place at any zoom a trip is drawn
 * at; the Moon, Europa and Charon are whole orbits away from theirs and have to
 * be drawn off themselves.
 */
function straysFromElements(chain: readonly BodyData[], travel: TravelBody): boolean {
	// The farthest the body gets from the borrowed centre: every orbit on the way
	// up to it, each at its own apoapsis.
	const offsetKm = chain.slice(0, -1).reduce((sum, link) => sum + link.a * (1 + link.e) * AU_KM, 0);
	return offsetKm > travel.radiusKm;
}

/**
 * What kind of transfer a pair of bodies needs, or why it cannot have one.
 *
 * Two bodies in different systems are connected by an arc about the Sun. Two in
 * the same one are not: Earth to its own Moon shares a heliocentric orbit, so
 * there is no arc between them there, and the transfer belongs about the body
 * they both go round instead.
 *
 * Which of the two remaining kinds that is depends on where the ends sit. When
 * one end *is* the body at the centre, there is no escape to price at that end
 * and the trip is a transfer ellipse from its parking orbit. When neither is —
 * Io to Europa — the pair are siblings about a third body, and that is an
 * ordinary two-orbit transfer again, just about a planet rather than the Sun.
 */
export type TransferPlan =
	| { kind: 'heliocentric' }
	| { kind: 'system'; primary: 'origin' | 'target' }
	| { kind: 'sibling'; centreId: string; centralMu: number }
	| { kind: 'blocked'; reason: 'unknown-orbit' | 'unknown-primary' };

/**
 * How the kernel is pointed at a pair: which orbit describes each end, which end
 * the arc goes round when one of them does, and μ of whatever it goes round.
 */
export interface TransferFrame {
	orbit: OrbitChoice;
	systemPrimary?: 'departure' | 'target';
	/** μ of the body the transfer orbits, km³/s². Absent means the Sun's. */
	centralMu?: number;
}

const HELIOCENTRIC_FRAME: TransferFrame = { orbit: 'heliocentric' };

/** The frame a plan implies. Blocked plans never reach a solve, so they take the
 *  heliocentric default rather than a case of their own. */
export function transferFrame(plan: TransferPlan | null): TransferFrame {
	if (plan?.kind === 'system') {
		return { orbit: 'own', systemPrimary: plan.primary === 'origin' ? 'departure' : 'target' };
	}
	if (plan?.kind === 'sibling') return { orbit: 'own', centralMu: plan.centralMu };
	return HELIOCENTRIC_FRAME;
}

/**
 * The body a transfer's positions are measured from, for anything that has to
 * place them in the scene. Null when the plan has no frame at all.
 *
 * This is the frame the *elements* are in, which is not always the body the
 * pricing calls its centre — get it wrong and the whole arc lands offset by
 * however far the two origins are apart, which for the Sun and the barycentre
 * is the better part of a million km. Two moons of one planet are the same
 * story at the barycentre inside it.
 *
 * A heliocentric arc has two sets of elements and so two frames to agree on —
 * asking the origin alone would make the answer depend on which way round the
 * trip is read, and silently draw the other end a barycentre offset away.
 */
export function transferCenterId(
	plan: TransferPlan,
	origin: BodyData,
	target: BodyData,
	lookup: BodyLookup
): string | null {
	if (plan.kind === 'blocked') return null;
	// One end is the centre, and `relativeState` differences the other against
	// it, so the positions come out about the body itself.
	if (plan.kind === 'system') return plan.primary === 'origin' ? origin.id : target.id;
	// Siblings keep their own elements, which are about the parent they share.
	if (plan.kind === 'sibling') return origin.parentId;
	const from = heliocentricAncestor(origin, lookup);
	const to = heliocentricAncestor(target, lookup);
	if (!from || !to) return null;
	const fromCenter = heliocentricCenterOf(from);
	const toCenter = heliocentricCenterOf(to);
	if (fromCenter === toCenter) return fromCenter;
	// No anchor suits both, because the solve itself already mixed two frames.
	// Reconciling on the barycentre would be possible — a body with
	// `helioElements` still carries its SSB fit — and is the worse trade: that
	// fit is not an orbit at all and walks the body millions of km per year of
	// propagation, against the ~0.8M km the frame offset costs. So the end that
	// has a real orbit keeps it, and the anchor follows it to the Sun.
	reportMixedFrames(from, to);
	return SUN_OBJECT_ID;
}

/**
 * The body a heliocentric orbit's elements are actually measured from.
 *
 * Not `parentId`, which says where the body hangs in the scene tree rather than
 * where its elements were taken: the shipped perturbing asteroids are filed
 * under the barycentre so the tree matches their Chebyshev ephemeris, yet the
 * catalogue row the resolver falls back on describes them with SBDB's
 * Sun-centred orbit. Only the raw Chebyshev fit is genuinely barycentric, and
 * only until `helioElements` supersedes it — everything else in the catalogue
 * already goes round the Sun.
 */
function heliocentricCenterOf(ancestor: BodyData): string {
	const barycentricFit =
		ancestor.parentId === SSB_OBJECT_ID &&
		ancestor.orbitalSource === OrbitalSource.SPICE &&
		!ancestor.helioElements;
	return barycentricFit ? SSB_OBJECT_ID : SUN_OBJECT_ID;
}

/** Pairs already reported — the solve re-runs several times a second. */
const reportedMixedFrames = new Set<string>();

function reportMixedFrames(from: BodyData, to: BodyData): void {
	const key = `${from.id}>${to.id}`;
	if (reportedMixedFrames.has(key)) return;
	reportedMixedFrames.add(key);
	console.debug(
		`[travel] ${from.id} and ${to.id} carry elements in different frames — solving about the Sun.`
	);
}

/**
 * The body at the centre of a planetary barycentre, by the NAIF numbering the
 * export uses throughout: barycentre `naif-N` holds planet `naif-N99`. Null for
 * anything that is not one of the nine.
 */
function primaryBodyOf(barycentreId: string): string | null {
	const id = naifId(barycentreId);
	if (id === null || id < 1 || id > 9) return null;
	return `naif-${id}99`;
}

/** The body and every ancestor up to its heliocentric orbit, nearest first. */
function ancestry(body: BodyData, lookup: BodyLookup): BodyData[] | null {
	const chain: BodyData[] = [];
	let current = body;
	for (let hop = 0; hop < MAX_HOPS; hop++) {
		chain.push(current);
		if (isHeliocentricRoot(current.parentId)) return chain;
		const parent = lookup(current.parentId);
		if (!parent) return null;
		current = parent;
	}
	return null;
}

/** Bodies already reported. The search exclusions ask about every body in the
 *  scene on every render, and the answer does not change between them. */
const reportedUnwalkable = new Set<string>();

function reportUnwalkableChain(id: string): void {
	if (reportedUnwalkable.has(id)) return;
	reportedUnwalkable.add(id);
	console.debug(`[travel] no heliocentric ancestor for ${id}`);
}

export function transferPlan(origin: BodyData, target: BodyData, lookup: BodyLookup): TransferPlan {
	const from = ancestry(origin, lookup);
	const to = ancestry(target, lookup);
	if (!from || !to) {
		reportUnwalkableChain((from ? target : origin).id);
		return { kind: 'blocked', reason: 'unknown-orbit' };
	}
	if (from[from.length - 1].id !== to[to.length - 1].id) return { kind: 'heliocentric' };

	// One system. The transfer is about the nearest body both ends go round —
	// either one of them, or, when they meet at a barycentre, the planet inside it.
	const shared = new Set(to.map((b) => b.id));
	const meeting = from.find((b) => shared.has(b.id));
	if (!meeting) return { kind: 'blocked', reason: 'unknown-primary' };
	const centre =
		meeting.id === origin.id || meeting.id === target.id
			? meeting.id
			: (primaryBodyOf(meeting.id) ?? meeting.id);
	if (centre === origin.id) return { kind: 'system', primary: 'origin' };
	if (centre === target.id) return { kind: 'system', primary: 'target' };

	// Siblings. Both ends orbit the centre, so their own elements already share a
	// frame and the only thing the kernel is missing is the mass at its focus.
	const centralMu = centralMuFor(centre, origin);
	if (!(centralMu > 0)) {
		reportUnknownCentre(centre);
		return { kind: 'blocked', reason: 'unknown-primary' };
	}
	return { kind: 'sibling', centreId: centre, centralMu };
}

/**
 * μ of the body a sibling pair both go round, km³/s².
 *
 * The measured GM when the export ships one — a barycentre resolves to a planet,
 * and every planet has one — and otherwise Kepler's third law on a satellite's
 * own orbit, which covers a moon of an asteroid.
 */
function centralMuFor(centreId: string, satellite: BodyData): number {
	const id = naifId(centreId);
	const measured = id === null ? undefined : getGmKm3s2(id);
	return measured && measured > 0 ? measured : muFromElements(satellite);
}

/** Centres already reported, on the same footing as `reportedUnwalkable`. */
const reportedCentres = new Set<string>();

function reportUnknownCentre(centreId: string): void {
	if (reportedCentres.has(centreId)) return;
	reportedCentres.add(centreId);
	console.debug(`[travel] no mass for ${centreId} — cannot solve about it.`);
}
