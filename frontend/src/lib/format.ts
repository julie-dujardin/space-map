/**
 * Shared constants for the binary export format.
 * Must stay in sync with Python export/format.py.
 */

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 1;
export const HEADER_SIZE = 16;

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

export enum Scale {
	PLANET = 0,
	SYSTEM = 1
}

/** Sentinel values for missing data in the binary format. */
export const MISSING_INT32 = -1;
export const MISSING_UINT8 = 255;

/** Check if a float64 value is missing (NaN). */
export function isMissing(v: number): boolean {
	return Number.isNaN(v);
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
