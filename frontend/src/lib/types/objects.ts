export interface OrbitalElements {
	a: number; // semi-major axis (AU)
	e: number; // eccentricity
	i: number; // inclination (degrees)
	om: number; // longitude of ascending node (degrees)
	w: number; // argument of perihelion (degrees)
	ma: number; // mean anomaly at epoch (degrees)
	n: number; // mean motion (degrees/day)
	epoch: number; // epoch (Julian Date)
}

/** Unified body data from the binary export. */
export interface BodyData extends OrbitalElements {
	id: number; // type-specific ID (NAIF ID for bodies/probes, SPK ID for small bodies, NORAD cat ID for satellites)
	fileId: string | null; // key into /data/v1/objects/ JSON files (e.g. "naif-399", "spkid-20000001")
	name: string | null;
	objectType: ObjectType;
	parentId: number; // NAIF ID of parent (0 = SSB, 399 = Earth, etc.)
	radiusKm: number;
}

export interface PositionedBody {
	data: BodyData;
	position: [number, number, number];
	/** Orbital elements to use for drawing the orbit (may differ from data's own elements, e.g. barycenter elements for planets) */
	orbitElements?: OrbitalElements;
	/** World-space center of the orbit (parent position). Defaults to origin. */
	orbitCenter?: [number, number, number];
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
