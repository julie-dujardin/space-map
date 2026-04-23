/**
 * Chebyshev ephemeris binary format constants.
 * Must stay in sync with [data/src/space_map_data/export/chebyshev/format.py].
 */

/** "SCHB" as little-endian uint32. */
export const CHEBYSHEV_MAGIC = 0x42484353;
export const CHEBYSHEV_VERSION = 1;
export const CHEBYSHEV_HEADER_SIZE = 32;
export const CHEBYSHEV_BODY_HEADER_SIZE = 20;

/** Format types (uint16 at header offset 6). */
export const FORMAT_POSITION_ONLY = 0;

export const BASE_CHEBYSHEV_PATH = '/data/v1/chebyshev';

export const chebyshevBinUrl = (zone: string, chunk: number): string =>
	`${BASE_CHEBYSHEV_PATH}/${zone}/${chunk}/data.bin.gz`;
export const chebyshevIdsUrl = (zone: string, chunk: number): string =>
	`${BASE_CHEBYSHEV_PATH}/${zone}/${chunk}/data.id.gz`;
