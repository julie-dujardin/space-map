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

import { DATA_BASE, versionedUrl } from '../data-base';

export const MAGIC = 0x50414d53; // "SMAP" as little-endian uint32
export const VERSION = 13;

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
export const CHEBYSHEV_BODY_HEADER_SIZE = 32;

/** Per-sub-chunk record method byte values (probes payload). */
export const PROBE_METHOD_UNCOVERABLE = 0;
export const PROBE_METHOD_KEPLER_PURE = 1;
export const PROBE_METHOD_KEPLER_DRIFT = 2;
export const PROBE_METHOD_CHEBYSHEV = 3;
/** Sits OUTSIDE the regular sub-chunk grid — one trailing record per probe
 *  per chunk, gated by `PROBE_FLAG_HAS_LANDED_RECORD`, with its own start/end
 *  ET offsets decoupled from `subchunk_days × n_subchunks`. */
export const PROBE_METHOD_LANDED = 4;

/** Per-probe header size inside a probes-payload file. */
export const PROBE_HEADER_SIZE = 20;
/** Per-sub-chunk record header size (preceding the method-specific payload). */
export const SUBCHUNK_HEADER_SIZE = 8;
/** Per-system-interval record size (f64 startEt, f64 endEt, u8 systemNaifId). */
export const SYSTEM_INTERVAL_SIZE = 17;

/** Probe-header flags byte (offset 7) bit assignments. */
export const PROBE_FLAG_HAS_LANDED_RECORD = 0x01;

/** Chebyshev extension flags bit marking per-segment coefficients as float64.
 *  Sun-orbiter zones (`major`, `major_asteroids`) sit far enough from the SSB
 *  that float32 quantization shows up at km scale, so they ship f64. */
export const CHEBYSHEV_FLAG_FLOAT64_COEFFS = 0x01;

/** Pre-interaction labels file: one global gzipped index per language listing
 *  every promoted body's display name. The frontend's promoted set is exactly
 *  this file's keys — there is no separate hardcoded list. Served on the
 *  revalidating default (small, on the boot path), so no `?v=` token. */
export const labelsUrl = (lang: string): string => `${DATA_BASE}/v1/labels/${lang}.gz`;

/** The `{zoom}/` path segment — empty for flat single-zoom zones (zoom=null),
 *  present for multi-zoom zones (`major`, `small_bodies/{class}`). */
function zoomSegment(zoom: number | null): string {
	return zoom === null ? '' : `${zoom}/`;
}

/**
 * Build the position-file URL for one (zone, zoom, ...) combination. Three
 * URL shapes, dispatched by the zone's `shape` discriminator: `parted` →
 * `position/{zone}/[{zoom}/]{part}.bin.gz`; `chunked-parted` → same +
 * `{label}/` (ISO date for `earth`, chunk index for `moons`); `chunked` →
 * `position/{zone}/[{zoom}/]{chunk}.bin.gz` (chebyshev).
 */
export function partedUrl(zone: string, zoom: number | null, part: number): string {
	return versionedUrl(`/v1/position/${zone}/${zoomSegment(zoom)}${part}.bin.gz`, 'position');
}

export function chunkedPartedUrl(
	zone: string,
	zoom: number | null,
	label: string,
	part: number
): string {
	return versionedUrl(
		`/v1/position/${zone}/${zoomSegment(zoom)}${label}/${part}.bin.gz`,
		'position'
	);
}

export function chunkedUrl(zone: string, zoom: number | null, chunk: number): string {
	return versionedUrl(`/v1/position/${zone}/${zoomSegment(zoom)}${chunk}.bin.gz`, 'position');
}

/** Sentinel values for missing data in the binary format. */
export const MISSING_INT32 = -1;
export const MISSING_UINT8 = 255;

export enum Scale {
	PLANET = 0,
	SYSTEM = 1
}

/** Provenance of the orbital elements payload. Ordinals must stay in sync
 *  with `SOURCE_ORDINAL` in format.py. `UNKNOWN` (255) is the sentinel for
 *  files pre-dating the byte, so failed parses don't crash the UI. */
export enum OrbitalSource {
	HORIZONS = 0,
	SBDB = 1,
	CELESTRAK = 2,
	SPICE = 3,
	SBDB_MOON = 4,
	SPICE_PROBE = 5,
	SPACETRACK = 6,
	UNKNOWN = 255
}

/** Object-ID prefix for every row (elements) or body (chebyshev). Combined
 *  with the numeric value to rebuild `<prefix>-<numeric>` (e.g. `naif-399`).
 *  Ordinals must stay in sync with `ID_TYPE_ORDINAL` in format.py. */
export enum IdType {
	NAIF = 0,
	SPKID = 1,
	NORAD_SATCAT = 2,
	// Ordinal 3 used to belong to a now-removed `sbdb_moon` id-type
	// (asteroid moons now ship as `spkid-N20xxxxxx`); not reassigned so
	// previously-shipped files stay parseable.
	PROBE = 4,
	UNKNOWN = 255
}

/** Ordinal → string prefix. Matches the Python `ID_TYPES` StrEnum exactly. */
const ID_TYPE_PREFIX: Record<number, string> = {
	[IdType.NAIF]: 'naif',
	[IdType.SPKID]: 'spkid',
	[IdType.NORAD_SATCAT]: 'norad_satcat',
	[IdType.PROBE]: 'probe'
};

/**
 * Rebuild a full `Object.id` string from the id-type byte plus a numeric
 * value. Returns null when the type is unknown — caller should treat the row
 * as unidentifiable rather than ship a malformed ID.
 */
/** String prefix of an id-type byte, or undefined for an unknown type. */
export function idTypePrefix(idType: number): string | undefined {
	return ID_TYPE_PREFIX[idType];
}

const PREFIX_ID_TYPE = new Map<string, number>(
	Object.entries(ID_TYPE_PREFIX).map(([type, prefix]) => [prefix, Number(type)])
);

/** Id-type byte of a string prefix, or undefined for one the export never emits. */
export function idTypeForPrefix(prefix: string): number | undefined {
	return PREFIX_ID_TYPE.get(prefix);
}

export function buildObjectId(idType: number, value: number): string | null {
	const prefix = ID_TYPE_PREFIX[idType];
	return prefix ? `${prefix}-${value}` : null;
}
