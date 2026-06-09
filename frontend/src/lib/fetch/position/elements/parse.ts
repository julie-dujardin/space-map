/**
 * Binary reader for the elements payload of a position file.
 * Creates zero-copy typed array views over the fetched ArrayBuffer.
 */

import {
	HEADER_SIZE,
	IdType,
	OrbitalSource,
	SUBFORMAT_KEPLERIAN,
	SUBFORMAT_PARABOLIC,
	SUBFORMAT_SGP4,
	buildObjectId
} from '$lib/fetch/position/format';

/**
 * File-level validity window (JD TDB). Propagation is only defined inside
 * `[validityStart, validityEnd]`; consumers hide bodies whose current `jd` is
 * outside the window. `-Infinity`/`+Infinity` means unbounded — Keplerian/
 * parabolic orbits have no hard cutoff, so exporters leave them unbounded.
 */
export interface Validity {
	validityStart: number;
	validityEnd: number;
}

/**
 * File-level metadata shared by every row in the elements payload — validity
 * window plus the provider that produced the elements.
 */
export interface ChunkMeta extends Validity {
	source: OrbitalSource;
	/**
	 * `<prefix>-<numeric>` Object IDs reconstructed from the file header's
	 * id-type byte and column 0. Indexed by row.
	 */
	idMap: Map<number, string>;
}

/** `hasLocalized` gates the localized-bundle fetch (flag-0 rows would 404).
 *  `flags` carries SBDB bits per point (0 = NEO, 1 = PHA); zero on non-SBDB rows. */
export interface HasLocalizedColumn {
	hasLocalized: Uint8Array;
	flags: Uint8Array;
}

/** Per-point flag bits (column 16 on Keplerian, 19 on SGP4, 13 on Parabolic). */
export const ELEMENTS_FLAG_NEO = 0x01;
export const ELEMENTS_FLAG_PHA = 0x02;

export interface KeplerianColumns extends ChunkMeta, HasLocalizedColumn {
	kind: 'keplerian';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	/** Secular drift rates (deg/day). Populated for SPICE moons via the Method C
	 * mean-element fit; zero for sources (Horizons/SBDB) that don't fit them. */
	omDot: Float32Array;
	wDot: Float32Array;
	rowCount: number;
}

export interface ParabolicColumns extends ChunkMeta, HasLocalizedColumn {
	kind: 'parabolic';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	q: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	tp: Float64Array;
	radiusKm: Float32Array;
	rowCount: number;
}

/**
 * SGP4 columns — superset of Keplerian with the extra OMM fields that
 * satellite.js `json2satrec` needs. Raw OMM units: `a` in km, `n` in rev/day,
 * angles in degrees, BSTAR in 1/Earth radii, n-dot in rev/day², n-ddot in rev/day³.
 */
export interface SGP4Columns extends ChunkMeta, HasLocalizedColumn {
	kind: 'sgp4';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	bstar: Float32Array;
	meanMotionDot: Float32Array;
	meanMotionDdot: Float32Array;
	elementSetNo: Int32Array;
	revAtEpoch: Int32Array;
	rowCount: number;
}

export type ElementColumns = KeplerianColumns | ParabolicColumns | SGP4Columns;

/** Round up to next multiple of 8. */
function align8(n: number): number {
	return (n + 7) & ~7;
}

/**
 * Parse the elements extension fields (offsets 24..31). Caller has already
 * validated the magic, version, and format byte and seeded `validityStart`/
 * `validityEnd` from the common header.
 */
function parseExtension(view: DataView): {
	subFormat: number;
	rowCount: number;
	idType: IdType;
	source: OrbitalSource;
} {
	return {
		subFormat: view.getUint16(24, true),
		source: view.getUint8(26) as OrbitalSource,
		idType: view.getUint8(27) as IdType,
		rowCount: view.getUint32(28, true)
	};
}

/**
 * Walk column 0 once and build the row-index → full-id Map. Logs (without
 * crashing) when the file's id-type is unknown — the row remains numerically
 * usable but keyed lookups against object bundles will fail, so the consumer
 * sees the warning and the missing entry rather than a corrupted-looking ID.
 */
function buildIdMap(idCol: Int32Array, idType: IdType): Map<number, string> {
	const map = new Map<number, string>();
	if (idType === IdType.UNKNOWN) {
		if (idCol.length > 0) {
			console.warn(
				`elements payload has unknown id-type — ${idCol.length} row(s) will lack reconstructed IDs`
			);
		}
		return map;
	}
	for (let i = 0; i < idCol.length; i++) {
		const id = buildObjectId(idType, idCol[i]);
		if (id !== null) map.set(i, id);
	}
	return map;
}

/** Parse shared columns 0–3 (id, objectType, parentId, scale). */
function parseSharedColumns(
	buffer: ArrayBuffer,
	rowCount: number
): {
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	offset: number;
} {
	let offset = HEADER_SIZE;

	const id = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	const objectType = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	const parentId = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	const scale = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	return { id, objectType, parentId, scale, offset };
}

/** Parse the common Keplerian columns 4–12. Returns the columns plus the next byte offset. */
function parseKeplerianColumns(
	buffer: ArrayBuffer,
	rowCount: number,
	startOffset: number
): {
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	offset: number;
} {
	let offset = startOffset;

	// Column 4: epoch_jd (float64 — Julian Dates need full precision)
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Columns 5–11: float32 orbital elements
	const a = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const e = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const i = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const om = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const w = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const ma = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const n = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 12: radius_km (float32)
	const radiusKm = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	return { epochJd, a, e, i, om, w, ma, n, radiusKm, offset };
}

/**
 * Parse the elements payload of a position file. The caller has already
 * verified the magic and version and confirmed the format byte selects
 * `FORMAT_ELEMENTS`. `validityStart`/`validityEnd` come from the common
 * header and apply to the whole file.
 */
export function parseElementsPayload(
	buffer: ArrayBuffer,
	validityStart: number,
	validityEnd: number
): ElementColumns {
	const view = new DataView(buffer);
	const { subFormat, rowCount, source, idType } = parseExtension(view);

	if (subFormat === SUBFORMAT_PARABOLIC) {
		return parseParabolicElements(buffer, rowCount, validityStart, validityEnd, source, idType);
	}
	if (subFormat === SUBFORMAT_SGP4) {
		return parseSGP4Elements(buffer, rowCount, validityStart, validityEnd, source, idType);
	}
	if (subFormat !== SUBFORMAT_KEPLERIAN) {
		throw new Error(`Unknown elements sub-format: ${subFormat}`);
	}

	const { id, objectType, parentId, scale, offset } = parseSharedColumns(buffer, rowCount);
	const kepler = parseKeplerianColumns(buffer, rowCount, offset);
	let tail = kepler.offset;
	// Columns 13–14: om_dot, w_dot (float32, deg/day). Keplerian-only — SGP4
	// uses 13–15 for BSTAR/n-dot/n-ddot instead.
	const omDot = new Float32Array(buffer, tail, rowCount);
	tail += align8(rowCount * 4);
	const wDot = new Float32Array(buffer, tail, rowCount);
	tail += align8(rowCount * 4);
	// Column 15: has_localized (uint8).
	const hasLocalized = new Uint8Array(buffer, tail, rowCount);
	tail += align8(rowCount);
	// Column 16: flags (uint8) — last column on every sub-format.
	const flags = new Uint8Array(buffer, tail, rowCount);
	const meta: ChunkMeta = {
		validityStart,
		validityEnd,
		source,
		idMap: buildIdMap(id, idType)
	};

	return {
		kind: 'keplerian',
		id,
		objectType,
		parentId,
		scale,
		epochJd: kepler.epochJd,
		a: kepler.a,
		e: kepler.e,
		i: kepler.i,
		om: kepler.om,
		w: kepler.w,
		ma: kepler.ma,
		n: kepler.n,
		radiusKm: kepler.radiusKm,
		omDot,
		wDot,
		hasLocalized,
		flags,
		rowCount,
		...meta
	};
}

function parseSGP4Elements(
	buffer: ArrayBuffer,
	rowCount: number,
	validityStart: number,
	validityEnd: number,
	source: OrbitalSource,
	idType: IdType
): SGP4Columns {
	const {
		id,
		objectType,
		parentId,
		scale,
		offset: sharedEnd
	} = parseSharedColumns(buffer, rowCount);
	const kepler = parseKeplerianColumns(buffer, rowCount, sharedEnd);
	let offset = kepler.offset;
	const meta: ChunkMeta = {
		validityStart,
		validityEnd,
		source,
		idMap: buildIdMap(id, idType)
	};

	// Columns 13–15: bstar, mean_motion_dot, mean_motion_ddot (float32)
	const bstar = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const meanMotionDot = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const meanMotionDdot = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Columns 16–17: element_set_no, rev_at_epoch (int32)
	const elementSetNo = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const revAtEpoch = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	// Column 18: has_localized (uint8).
	const hasLocalized = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);
	// Column 19: flags (uint8) — always zero for SGP4, emitted for uniformity.
	const flags = new Uint8Array(buffer, offset, rowCount);

	return {
		kind: 'sgp4',
		id,
		objectType,
		parentId,
		scale,
		epochJd: kepler.epochJd,
		a: kepler.a,
		e: kepler.e,
		i: kepler.i,
		om: kepler.om,
		w: kepler.w,
		ma: kepler.ma,
		n: kepler.n,
		radiusKm: kepler.radiusKm,
		bstar,
		meanMotionDot,
		meanMotionDdot,
		elementSetNo,
		revAtEpoch,
		hasLocalized,
		flags,
		rowCount,
		...meta
	};
}

function parseParabolicElements(
	buffer: ArrayBuffer,
	rowCount: number,
	validityStart: number,
	validityEnd: number,
	source: OrbitalSource,
	idType: IdType
): ParabolicColumns {
	const {
		id,
		objectType,
		parentId,
		scale,
		offset: startOffset
	} = parseSharedColumns(buffer, rowCount);
	let offset = startOffset;
	const meta: ChunkMeta = {
		validityStart,
		validityEnd,
		source,
		idMap: buildIdMap(id, idType)
	};

	// Column 4: epoch_jd (float64 — Julian Dates need full precision)
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Column 5: q (float32, perihelion distance AU)
	const q = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Columns 6–9: e, i, om, w (float32)
	const e = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const i = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const om = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const w = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 10: tp (float64 — Julian Dates need full precision)
	const tp = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Column 11: radius_km (float32)
	const radiusKm = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	// Column 12: has_localized (uint8).
	const hasLocalized = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);
	// Column 13: flags (uint8) — last column on every sub-format.
	const flags = new Uint8Array(buffer, offset, rowCount);

	return {
		kind: 'parabolic',
		id,
		objectType,
		parentId,
		scale,
		epochJd,
		q,
		e,
		i,
		om,
		w,
		tp,
		radiusKm,
		hasLocalized,
		flags,
		rowCount,
		...meta
	};
}
