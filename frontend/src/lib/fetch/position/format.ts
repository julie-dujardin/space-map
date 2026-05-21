/**
 * Shared constants and URL builders for the unified position file format.
 * Must stay in sync with `data/src/space_map_data/export/position/format.py`.
 *
 * One magic, one common header, two payload variants:
 *   - elements (columnar Keplerian / Parabolic / SGP4)
 *   - chebyshev (per-body segments)
 *
 * The format byte at offset 6 of the common header dispatches between them.
 */

import { DATA_BASE } from '../data-base';

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 8;

export const COMMON_HEADER_SIZE = 24;
export const EXTENSION_SIZE = 8;
export const HEADER_SIZE = COMMON_HEADER_SIZE + EXTENSION_SIZE; // 32

/** Top-level format byte at offset 6 of the common header. */
export const FORMAT_ELEMENTS = 0;
export const FORMAT_CHEBYSHEV = 1;
export const FORMAT_PROBES = 2;

/** Elements sub-format (uint16 at offset 24). */
export const SUBFORMAT_KEPLERIAN = 0;
export const SUBFORMAT_PARABOLIC = 1;
export const SUBFORMAT_SGP4 = 2;

/** Per-body chebyshev header size, follows the file header for cheb files. */
export const CHEBYSHEV_BODY_HEADER_SIZE = 24;

/** Per-sub-chunk record method byte values (probes payload). */
export const PROBE_METHOD_UNCOVERABLE = 0;
export const PROBE_METHOD_KEPLER_PURE = 1;
export const PROBE_METHOD_KEPLER_DRIFT = 2;
export const PROBE_METHOD_CHEBYSHEV = 3;
/**
 * `PROBE_METHOD_LANDED` sits OUTSIDE the regular sub-chunk grid — one
 * trailing record per probe per chunk, gated by
 * `PROBE_FLAG_HAS_LANDED_RECORD` in the probe header. Carries its own
 * start/end ET offsets so its lifetime is decoupled from
 * `subchunk_days × n_subchunks`. The parser skips past it for now;
 * landed probes simply have no trail in the renderer.
 */
export const PROBE_METHOD_LANDED = 4;

/** Per-probe header size inside a probes-payload file. */
export const PROBE_HEADER_SIZE = 20;
/** Per-sub-chunk record header size (preceding the method-specific payload). */
export const SUBCHUNK_HEADER_SIZE = 8;

/** Probe-header flags byte (offset 7) bit assignments. */
export const PROBE_FLAG_HAS_LANDED_RECORD = 0x01;

/**
 * Bit in the chebyshev extension's flags byte (offset 28 of the common header)
 * that marks the file's per-segment coefficients as float64 instead of the
 * default float32. Sun-orbiter zones (`major`, `major_asteroids`) carry their
 * absolute distances far enough from the SSB that float32 quantization shows
 * up at km scale, so they ship f64. Moon zones stay f32.
 */
export const CHEBYSHEV_FLAG_FLOAT64_COEFFS = 0x01;

export const BASE_POSITION_PATH = `${DATA_BASE}/v1/position`;

/** Pre-interaction labels file: one global gzipped index per language listing
 *  every promoted body's display name. The frontend's promoted set is exactly
 *  this file's keys — there is no separate hardcoded list. */
export const labelsUrl = (lang: string): string => `${DATA_BASE}/v1/labels/${lang}.gz`;

/**
 * Build the position-file URL for one (zone, zoom, ...) combination.
 *
 * Three URL shapes, dispatched by the zone's `shape` discriminator in
 * `metadata.position.zones[zone].zooms[zoom]`:
 *
 *   - `parted`         → `position/{zone}/{zoom}/{part}.bin.gz`
 *   - `chunked-parted` → `position/{zone}/{zoom}/{label}/{part}.bin.gz`
 *                        (label is an ISO date for `earth`, a chunk index for `moons`)
 *   - `chunked`        → `position/{zone}/{zoom}/{chunk}.bin.gz` (chebyshev)
 */
export function partedUrl(zone: string, zoom: number, part: number): string {
	return `${BASE_POSITION_PATH}/${zone}/${zoom}/${part}.bin.gz`;
}

export function chunkedPartedUrl(zone: string, zoom: number, label: string, part: number): string {
	return `${BASE_POSITION_PATH}/${zone}/${zoom}/${label}/${part}.bin.gz`;
}

export function chunkedUrl(zone: string, zoom: number, chunk: number): string {
	return `${BASE_POSITION_PATH}/${zone}/${zoom}/${chunk}.bin.gz`;
}

/** Probe zones use the `chunked` shape with no zoom segment — see
 *  [Probes payload](docs/export-format.md#probes-payload-format-byte--2). */
export function chunkedFlatUrl(zone: string, chunk: number): string {
	return `${BASE_POSITION_PATH}/${zone}/${chunk}.bin.gz`;
}

/** Sentinel values for missing data in the binary format. */
export const MISSING_INT32 = -1;
export const MISSING_UINT8 = 255;

export enum Scale {
	PLANET = 0,
	SYSTEM = 1
}

/**
 * Provenance of the orbital elements in a position file's elements payload.
 * Ordinals must stay in sync with `SOURCE_ORDINAL` in
 * `data/src/space_map_data/export/position/format.py`. The elements extension
 * stores the ordinal at byte offset 26 (extension byte 2). `UNKNOWN` (255) is
 * the sentinel for files pre-dating the byte (kept so failed parses don't
 * crash the UI).
 */
export enum OrbitalSource {
	HORIZONS = 0,
	SBDB = 1,
	CELESTRAK = 2,
	SPICE = 3,
	SBDB_MOON = 4,
	SPICE_PROBE = 5,
	UNKNOWN = 255
}

/**
 * Object-ID prefix for every row in an elements payload (or every body in a
 * chebyshev payload). Combined with the numeric value to rebuild the full
 * `<prefix>-<numeric>` form (e.g. `naif-399`). Ordinals must stay in sync
 * with `ID_TYPE_ORDINAL` in
 * `data/src/space_map_data/export/position/format.py`.
 */
export enum IdType {
	NAIF = 0,
	SPKID = 1,
	NORAD_SATCAT = 2,
	SBDB_MOON = 3,
	PROBE = 4,
	UNKNOWN = 255
}

/** Ordinal → string prefix. Matches the Python `ID_TYPES` StrEnum exactly. */
const ID_TYPE_PREFIX: Record<number, string> = {
	[IdType.NAIF]: 'naif',
	[IdType.SPKID]: 'spkid',
	[IdType.NORAD_SATCAT]: 'norad_satcat',
	[IdType.SBDB_MOON]: 'sbdb_moon',
	[IdType.PROBE]: 'probe'
};

/**
 * Rebuild a full `Object.id` string from the id-type byte plus a numeric
 * value. Returns null when the type is unknown — caller should treat the row
 * as unidentifiable rather than ship a malformed ID.
 *
 * For `SBDB_MOON`, the numeric is the per-parent `sat_index`; the full id
 * needs the parent's numeric prefix too. Use `buildSbdbMoonId(parent, sat)`
 * instead of this helper.
 */
export function buildObjectId(idType: number, value: number): string | null {
	if (idType === IdType.SBDB_MOON) return null;
	const prefix = ID_TYPE_PREFIX[idType];
	return prefix ? `${prefix}-${value}` : null;
}

/** Compose the compound `sbdb_moon-<parent_spkid>-<sat_index>` form. */
export function buildSbdbMoonId(parentSpkid: number, satIndex: number): string {
	return `sbdb_moon-${parentSpkid}-${satIndex}`;
}
