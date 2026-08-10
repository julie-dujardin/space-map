import type { SatRec } from 'satellite.js';
import type { Quaternion } from 'three';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { NutPrec, Orientation, PointingSpec } from '$lib/math/orientation';
import type { AttitudeTrack } from '$lib/fetch/attitude/track';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';

export interface OrbitalElements {
	a: number; // semi-major axis (AU)
	e: number; // eccentricity
	i: number; // inclination (degrees)
	om: number; // longitude of ascending node (degrees)
	w: number; // argument of perihelion (degrees)
	ma: number; // mean anomaly at epoch (degrees)
	n: number; // mean motion (degrees/day)
	epoch: number; // epoch (Julian Date)
	/**
	 * Secular drift rates (deg/day) applied to om and w. Populated for SPICE
	 * moons via the Method C mean-element fit so the propagated orbit tracks
	 * J2-driven nodal/apsidal precession. Absent (or zero) means the angles
	 * are static — the default for Horizons/SBDB-sourced bodies.
	 */
	omDot?: number;
	wDot?: number;
	// Parabolic orbits (e=1): a/ma/n are not available; use q and tp instead
	q?: number; // perihelion distance (AU) — only for parabolic orbits
	tp?: number; // time of perihelion passage (Julian Date) — only for parabolic orbits
	/**
	 * True when i/om/w are referenced to Earth's mean equator of J2000 instead of
	 * the ecliptic. TLE-sourced Earth satellites (CelesTrak) are in TEME, treated
	 * here as equatorial; everything else (Horizons/SPICE) is ecliptic J2000.
	 */
	equatorial?: boolean;
}

/** Unified body data from the binary export. */
export interface BodyData extends OrbitalElements {
	id: string; // prefixed ID, e.g. "naif-499", "spkid-20134340" — matches backend Object.id and /data/v1/objects/ filenames
	name: string | null;
	/**
	 * `true` for promoted bodies the data side flagged as minor — currently
	 * designation-only moons (e.g. `naif-65289`/`S2020 S48`). Renders as a
	 * collapsed halo by default; expands and shows the label on hover. Set
	 * from the labels file's `m` flag at chunk parse time, alongside `name`.
	 */
	isMinor?: boolean;
	objectType: ObjectType;
	/** Physically-derived per-body surface colour (`__global__.sbdb.color`), set
	 *  lazily on focus by `loadBodyTexture`. Used for the rendered sphere of a
	 *  textureless small body; the point cloud and label keep their per-type
	 *  tint via `resolveBodyColor`. */
	color?: string;
	parentId: string; // always "naif-{n}" — parents are always major bodies / barycenters
	/** Probe-only: parent set at scene-load, never mutated by the per-frame
	 *  zone re-resolution. A mismatch with `parentId` marks the probe as
	 *  flying past — used by the hide-threshold to skip transient flybys. */
	loadParentId?: string;
	radiusKm: number;
	/** True iff the object has a localized detail bundle in at least one
	 *  language. Sourced from the `has_localized` uint8 column on the binary
	 *  chunk. Frontend uses this to gate the localized bundle fetch — a
	 *  detail-bundle fetch for `false` rows would 404. */
	hasLocalized: boolean;
	/** SBDB bits: 0 = NEO, 1 = PHA. Zero on non-SBDB bodies. Drives the orbit
	 *  worker's NEO/PHA per-point visibility mask. */
	flags?: number;
	/**
	 * SGP4 satellite record from satellite.js. Populated only for Earth
	 * satellites (SGP4 format chunks). When present, position propagation
	 * goes through sgp4() instead of the Kepler solver, capturing J2 and drag
	 * effects that the mean-motion Kepler step ignores.
	 */
	satrec?: SatRec;
	/**
	 * The same orbit taken about the Sun instead of the barycentre, for the
	 * bodies the ephemeris places against the SSB.
	 *
	 * The inherited elements are what the body is *drawn* from, and they are
	 * fitted to an SSB-relative state — which is not an orbit, so the fit is only
	 * good for the instant it was taken at. Anything propagating years ahead
	 * needs these instead. Absent for every body already referenced to the Sun,
	 * which is most of the catalogue.
	 */
	helioElements?: OrbitalElements;
	/**
	 * Chunk-level validity window (JD TDB) — inherited from the chunk header.
	 * Callers must skip propagation (and hide the body) when the current jd
	 * falls outside `[validityStart, validityEnd]`. `±Infinity` = unbounded
	 * (Kepler/parabolic orbits have no hard cutoff); tight windows come from
	 * SGP4 where extrapolation past the epoch spread produces nonsense.
	 */
	validityStart: number;
	validityEnd: number;
	/**
	 * Provider that produced these orbital elements — inherited from the chunk
	 * header byte (binary format v3+). Drives the dynamic attribution bar; for
	 * placeholder bodies built from global JSON the enum is parsed from
	 * `global.orbit.source` instead.
	 */
	orbitalSource: OrbitalSource;
	/**
	 * Days from J2000 to when the body came into existence (moon/sat discovery
	 * or launch). The render gate hides it while `jd - 2451545 < visibleFromDays`.
	 * NaN/undefined = always visible. Only elements-backed bodies carry it.
	 */
	visibleFromDays?: number;
}

export interface PositionedBody {
	data: BodyData;
	position: [number, number, number];
	/** Elements used for orbit drawing — may differ from `data` (e.g. planets borrowing barycenter elements). */
	orbitElements?: OrbitalElements;
	/** World-space center of the orbit (parent position). Defaults to origin. */
	orbitCenter?: [number, number, number];
	/**
	 * Where the trail's brightest end sits when `position` is offset from the
	 * orbit curve (planets borrowing barycenter elements: curve passes through
	 * the barycenter so the trail head must too, or it kinks). Updated each frame.
	 */
	trailAnchor?: [number, number, number];
	/**
	 * Re-derive `orbitElements` at a new `jd`. Set on chebyshev bodies so the
	 * trail can periodically re-snapshot osculating elements as the body
	 * progresses through its chunk. Returns null on missing GM / sample miss /
	 * degenerate state; callers keep existing elements then.
	 */
	rederiveElements?: (jd: number) => OrbitalElements | null;
	/**
	 * Past-position ring buffer for probes whose chunk has any chebyshev sub-chunk
	 * (single-Kepler trails are wrong during flyby/capture). Buffer holds
	 * fit-center-relative samples; renderer adds the parent position at draw.
	 * Takes precedence over `orbitElements` in the trail builder.
	 */
	trailBuffer?: TrailBuffer;
	/** IAU pole + spin polynomial. Drives mesh orientation and body-fixed coords. */
	orientation?: Orientation;
	/** IAU nutation/precession sums (per-body coefficients + system-shared angles). */
	nutPrec?: NutPrec;
	/**
	 * Per-spacecraft pointing spec (export `pointing`). Set on focus when the
	 * model loads; drives the focused model's attitude instead of the default
	 * south-toward-parent. Cleared on unfocus.
	 */
	pointing?: PointingSpec;
	/** Debug-menu live override; takes precedence over `pointing` when set, and
	 *  clearing it restores the config/default attitude. */
	pointingOverride?: PointingSpec;
	/** Refit-from-CK attitude stream. Loaded lazily on focus; drives the model's
	 *  orientation directly over its coverage window, ahead of `pointing`. */
	attitudeTrack?: AttitudeTrack;
	/** Model→body base rotation (`frame_map`) of the loaded model bundle. Set on
	 *  focus when the model loads; the probe north reference reads it. Cleared on
	 *  unfocus. */
	modelBaseFrame?: Quaternion;
	/** Set on synthetic surface-feature focus bodies. The camera orbits `position`
	 *  (the seat); everything data-facing (terrain, nomenclature, attribution)
	 *  defers to `featureAnchor.hostId`. */
	featureAnchor?: FeatureAnchor;
}

/** A synthetic surface-feature focus target — see {@link FeatureAnchor}. */
export function isSurfaceFeature(body: PositionedBody): boolean {
	return body.data.objectType === ObjectType.SURFACE_FEATURE;
}

/**
 * ObjectType ordinals — matches ObjectType StrEnum order in Python.
 * Used as uint8 values in elements.bin.
 */
export enum ObjectType {
	BARYCENTER = 0,
	LAGRANGE_POINT = 1,
	STAR = 2,
	PLANET = 3,
	DWARF_PLANET = 4,
	MOON = 5,
	ASTEROID = 6,
	ASTEROID_INNER = 7,
	ASTEROID_MAIN_BELT = 8,
	ASTEROID_TROJAN = 9,
	ASTEROID_CENTAUR = 10,
	ASTEROID_TNO = 11,
	COMET = 12,
	SPACECRAFT = 13,
	DEBRIS = 14,
	UNDOCUMENTED = 15,
	/** Frontend-only: a synthetic focus target for an IAU surface feature seated on
	 *  a host body. Never appears in binary chunks (ordinals 0–15 are the wire
	 *  format), so it can't collide with a real object type. */
	SURFACE_FEATURE = 16
}

/** Identifies a {@link PositionedBody} synthesised as an orbitable surface
 *  feature (see {@link ObjectType.SURFACE_FEATURE}). The camera orbits the seat;
 *  the `host` supplies terrain, nomenclature and attribution. */
export interface FeatureAnchor {
	hostId: string;
	featureId: number;
	/** Planetographic degrees, IAU convention (lon 0–360 east-positive). */
	lat: number;
	lon: number;
	diameterM: number;
}
/**
 * Semi-major axis range (AU) for each SBDB orbit-class zone.
 * Used to gate asteroid point-cloud visibility based on camera distance.
 * Groups not defined by semi-major axis (most comets, parabolic/hyperbolic, unclassified) are omitted
 * and treated as always-visible.
 */
export const ZONE_A_RANGE: Record<string, { minA: number; maxA: number }> = {
	// Near-Earth — ranges from perihelion/aphelion constraints
	IEO: { minA: 0, maxA: 0.983 }, // Q < 0.983 → a ≤ Q
	ATE: { minA: 0.5, maxA: 1.0 }, // a < 1.0
	APO: { minA: 1.0, maxA: 3.2 }, // a > 1.0; practical upper bound
	AMO: { minA: 1.0, maxA: 3.2 }, // q > 1.017 → a > ~1.0; practical upper bound
	MCA: { minA: 1.3, maxA: 3.2 }, // a < 3.2; q > 1.3
	// Main belt — direct a ranges
	IMB: { minA: 1.666, maxA: 2.0 },
	MBA: { minA: 2.0, maxA: 3.2 },
	OMB: { minA: 3.2, maxA: 4.6 },
	// Jupiter-region comets — show alongside-ish Trojans
	// excentricity range is much higher, values fine-tuned from min perihelion/max aphelion in DB
	ETc: { minA: 0, maxA: 5.5 },
	JFC: { minA: 0, maxA: 15 },
	// Outer solar system — direct a ranges
	TJN: { minA: 4.6, maxA: 5.5 },
	CEN: { minA: 5.5, maxA: 30.1 },
	TNO: { minA: 30.1, maxA: Infinity },
	// Earth satellites — LEO to GEO (~42,200 km ≈ 0.00028 AU)
	earth: { minA: 0, maxA: 0.0003 }
};

/** SBDB orbit-class slug from `(a, e)`. Mirrors the OrbitClass rules in
 *  `data/src/space_map_data/models/object/sbdb.py` — used for bodies that
 *  don't carry the class as data (dwarf planets in `bodiesById`). */
export function sbdbOrbitClass(a: number, e: number): string | null {
	if (!Number.isFinite(a) || a <= 0 || !Number.isFinite(e)) return null;
	const q = a * (1 - e);
	const Q = a * (1 + e);
	if (Q < 0.983) return 'IEO';
	if (a < 1.0) return 'ATE';
	if (q < 1.017) return 'APO';
	if (q < 1.3) return 'AMO';
	if (q < 1.666 && a < 3.2) return 'MCA';
	if (a < 2.0) return 'IMB';
	if (a < 3.2) return 'MBA';
	if (a < 4.6) return 'OMB';
	if (a < 5.5 && e < 0.3) return 'TJN';
	if (a < 30.1) return 'CEN';
	return 'TNO';
}

/**
 * Nominal radii (km) substituted when a body's true size is unknown, keyed by
 * orbital source (checked first) then object type. Nothing is drawn at these
 * sizes — unsized bodies render as a halo only. The value only feeds
 * size-derived behaviour (camera approach distance, LOD, framing), so it's
 * picked per scale-class: metres for craft, debris and probes; tens of metres
 * for unsized moons. {@link NOMINAL_RADIUS_KM_DEFAULT} is the generic floor.
 */
const NOMINAL_RADIUS_KM_BY_SOURCE: Partial<Record<OrbitalSource, number>> = {
	[OrbitalSource.SPICE_PROBE]: 0.005,
	[OrbitalSource.SBDB_MOON]: 0.01
};
const NOMINAL_RADIUS_KM_BY_TYPE: Partial<Record<ObjectType, number>> = {
	[ObjectType.SPACECRAFT]: 0.005,
	[ObjectType.DEBRIS]: 0.005,
	// Metres-scale so min-zoom lets the camera reach the surface at the feature;
	// arrival framing is sized from the feature diameter separately.
	[ObjectType.SURFACE_FEATURE]: 0.001
};
const NOMINAL_RADIUS_KM_DEFAULT = 0.1;

/**
 * The body's radius in km: the measured value when known, else a nominal
 * stand-in (see {@link NOMINAL_RADIUS_KM_BY_SOURCE}). Safe wherever a size is
 * needed for camera/LOD/framing — it never implies a drawn surface.
 */
export function effectiveRadiusKm(data: BodyData): number {
	if (Number.isFinite(data.radiusKm) && data.radiusKm > 0) return data.radiusKm;
	return (
		NOMINAL_RADIUS_KM_BY_SOURCE[data.orbitalSource] ??
		NOMINAL_RADIUS_KM_BY_TYPE[data.objectType] ??
		NOMINAL_RADIUS_KM_DEFAULT
	);
}

/** Returns true for any asteroid subtype. */
export function isAsteroid(type: ObjectType): boolean {
	return type >= ObjectType.ASTEROID && type <= ObjectType.ASTEROID_TNO;
}
/** Returns true for types that get rendered as individual 3D bodies (not points). */

export function isMajorBody(type: ObjectType): boolean {
	return (
		type === ObjectType.STAR ||
		type === ObjectType.PLANET ||
		type === ObjectType.DWARF_PLANET ||
		type === ObjectType.MOON
	);
}

/** Natural celestial bodies — stars, planets, moons, asteroids, comets (not craft/debris/features). */
export function isNaturalBody(type: ObjectType): boolean {
	return isMajorBody(type) || isAsteroid(type) || type === ObjectType.COMET;
}

/** String-typed counterpart of {@link isNaturalBody} for `GlobalObjectData.type`. */
export function isNaturalBodyType(type: string | undefined): boolean {
	if (!type) return false;
	const key = type.toUpperCase() as keyof typeof ObjectType;
	const ordinal = ObjectType[key];
	return typeof ordinal === 'number' && isNaturalBody(ordinal);
}
