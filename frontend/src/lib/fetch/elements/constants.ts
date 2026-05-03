/**
 * Shared constants for the binary export format.
 * Must stay in sync with Python export/format.py.
 */

import { DATA_BASE } from '../data-base';

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 6;
export const HEADER_SIZE = 32;

/** Format types (uint16 at header offset 6). */
export const FORMAT_KEPLERIAN = 0;
export const FORMAT_PARABOLIC = 1;
export const FORMAT_SGP4 = 2;

export const BASE_ELEMENT_PATH = `${DATA_BASE}/v1/elements`;

/**
 * Build the chunk directory. Time-segmented zones (earth) insert an ISO-date
 * directory between zoom and part; flat zones (everything else, for now)
 * skip it.
 */
const chunkDir = (zone: string, zoom: number, time: string | null): string =>
	time ? `${BASE_ELEMENT_PATH}/${zone}/${zoom}/${time}` : `${BASE_ELEMENT_PATH}/${zone}/${zoom}`;

export const elementsBinUrl = (
	zone: string,
	zoom: number,
	part: number,
	time: string | null = null
): string => `${chunkDir(zone, zoom, time)}/${part}.bin.gz`;

/** Pre-interaction labels file: one global gzipped index per language listing
 *  every promoted body's display name. The frontend's promoted set is exactly
 *  this file's keys — there is no separate hardcoded list. */
export const labelsUrl = (lang: string): string => `${DATA_BASE}/v1/labels/${lang}.gz`;

/** Sentinel values for missing data in the binary format. */
export const MISSING_INT32 = -1;
export const MISSING_UINT8 = 255;

export enum Scale {
	PLANET = 0,
	SYSTEM = 1
}

/**
 * Provenance of the orbital elements in a binary chunk. Ordinals must stay in
 * sync with `SOURCE_ORDINAL` in [data/src/space_map_data/export/elements/format.py].
 * The header stores the ordinal at offset 28; `UNKNOWN` (255) is the sentinel
 * for chunks pre-dating the byte (kept so failed parses don't crash the UI).
 */
export enum OrbitalSource {
	HORIZONS = 0,
	SBDB = 1,
	CELESTRAK = 2,
	SPICE = 3,
	UNKNOWN = 255
}

/**
 * Object-ID prefix for every row in a chunk. Combined with column 0 (numeric)
 * to rebuild the full `<prefix>-<numeric>` form (e.g. `naif-399`). Stored as a
 * uint8 at header offset 29; ordinals must stay in sync with `ID_TYPE_ORDINAL`
 * in [data/src/space_map_data/export/elements/format.py]. `UNKNOWN` is the
 * sentinel for empty chunks or unsupported prefixes — consumers should drop
 * the row rather than crash.
 */
export enum IdType {
	NAIF = 0,
	SPKID = 1,
	NORAD_SATCAT = 2,
	UNKNOWN = 255
}

/** Ordinal → string prefix. Matches the Python `ID_TYPES` StrEnum exactly. */
const ID_TYPE_PREFIX: Record<number, string> = {
	[IdType.NAIF]: 'naif',
	[IdType.SPKID]: 'spkid',
	[IdType.NORAD_SATCAT]: 'norad_satcat'
};

/**
 * Rebuild a full `Object.id` string from the header's id-type byte plus a
 * numeric value (column 0 in the elements binary, or `obj_id_value` in the
 * chebyshev body header). Returns null when the type is unknown — caller
 * should treat the row as unidentifiable rather than ship a malformed ID.
 */
export function buildObjectId(idType: number, value: number): string | null {
	const prefix = ID_TYPE_PREFIX[idType];
	return prefix ? `${prefix}-${value}` : null;
}
