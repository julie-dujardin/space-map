/**
 * Shared constants for the binary export format.
 * Must stay in sync with Python export/format.py.
 */

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 3;
export const HEADER_SIZE = 32;

/** Format types (uint16 at header offset 6). */
export const FORMAT_KEPLERIAN = 0;
export const FORMAT_PARABOLIC = 1;
export const FORMAT_SGP4 = 2;

export const BASE_ELEMENT_PATH = '/data/v1/elements';

export const elementsBinUrl = (zone: string, zoom: number, part: number): string =>
	`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.bin.gz`;
export const elementIdsUrl = (zone: string, zoom: number, part: number): string =>
	`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.id.gz`;
export const elementLabelsUrl = (lang: string, zone: string, zoom: number, part: number): string =>
	`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.loc.${lang}.gz`;

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
