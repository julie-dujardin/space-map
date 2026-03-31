/**
 * Shared constants for the binary export format.
 * Must stay in sync with Python export/format.py.
 */

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 1;
export const HEADER_SIZE = 16;

export const BASE_ELEMENT_PATH = '/data/v1/elements';
export const BASE_LABEL_PATH = '/data/v1/element_labels';

/** Sentinel values for missing data in the binary format. */
export const MISSING_INT32 = -1;
export const MISSING_UINT8 = 255;

export enum Scale {
	PLANET = 0,
	SYSTEM = 1
}
