import type { SatRec } from 'satellite.js';
import { DEFAULT_FALLBACK_RADIUS_KM } from '$lib/constants';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { NutPrec, Orientation } from '$lib/math/orientation';
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
	UNDOCUMENTED = 15
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

/** Default visual radius in km for bodies with no known radius. */
const FALLBACK_RADIUS_KM: Partial<Record<ObjectType, number>> = {
	[ObjectType.SPACECRAFT]: 0.005
};
const FALLBACK_RADIUS_KM_BY_SOURCE: Partial<Record<number, number>> = {
	[OrbitalSource.SPICE_PROBE]: 0.005,
	[OrbitalSource.SBDB_MOON]: 0.1 * DEFAULT_FALLBACK_RADIUS_KM
};

/** Effective radius in km, using a fallback when the data has no known positive value. */
export function effectiveRadiusKm(data: BodyData): number {
	if (Number.isFinite(data.radiusKm) && data.radiusKm > 0) return data.radiusKm;
	const bySource = FALLBACK_RADIUS_KM_BY_SOURCE[data.orbitalSource];
	if (bySource !== undefined) return bySource;
	return FALLBACK_RADIUS_KM[data.objectType] ?? DEFAULT_FALLBACK_RADIUS_KM;
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
