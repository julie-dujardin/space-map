/**
 * Binary reader for the chebyshev payload of a position file. One body per
 * record, each holding segment-wise Chebyshev coefficients for ECLIPJ2000
 * parent-relative position in km. Segment starts/ends are float64;
 * coefficients are float32 unless `CHEBYSHEV_FLAG_FLOAT64_COEFFS` is set
 * (Sun-orbiter zones, where distance exceeds float32's resolution budget).
 */

import {
	CHEBYSHEV_BODY_HEADER_SIZE,
	CHEBYSHEV_FLAG_FLOAT64_COEFFS,
	HEADER_SIZE,
	IdType,
	buildObjectId
} from '$lib/fetch/position/format';

export interface ChebyshevBody {
	/** Full Object ID (`<prefix>-<numeric>`). Pluto and perturber asteroids ride
	 *  as `spkid-…` even though `naifId` is their planetary NAIF ID, so use
	 *  this for cross-referencing. Empty string on unknown id-type — drop the row. */
	id: string;
	naifId: number;
	parentId: number;
	/** 1 iff the body has a localized detail bundle in at least one language. */
	hasLocalized: boolean;
	/** ObjectType ordinal (same map as the elements `objectType` column). */
	objectType: number;
	/** NaN if unknown in the source. */
	radiusKm: number;
	/**
	 * Days from J2000 to the body's discovery. The render gate hides it while
	 * `jd - J2000 < visibleFromDays`. NaN = always visible.
	 */
	visibleFromDays: number;
	/** Polynomial degree + 1 per axis. */
	coeffsPerAxis: number;
	/** Segment starts (JD TDB), sorted ascending, contiguous with endJds. */
	startJds: Float64Array;
	/** Segment ends (JD TDB), exclusive upper bound of each segment. */
	endJds: Float64Array;
	/** Flat coefficient store, per segment as `[cx_0..cx_{N-1}, cy_0..cy_{N-1},
	 *  cz_0..cz_{N-1}]` with `N = coeffsPerAxis`. `Float32Array` for most
	 *  zones, `Float64Array` for Sun-orbiter zones — read via indexed access
	 *  so either dtype works. */
	coeffs: Float32Array | Float64Array;
}

export interface ChebyshevChunk {
	startJd: number;
	endJd: number;
	bodies: ChebyshevBody[];
}

/**
 * Parse the chebyshev payload of a position file. The caller has already
 * verified the magic and version and confirmed the format byte selects
 * `FORMAT_CHEBYSHEV`. `startJd`/`endJd` come from the common header and bound
 * the whole file's coverage.
 */
export function parseChebyshevPayload(
	buffer: ArrayBuffer,
	startJd: number,
	endJd: number
): ChebyshevChunk {
	const view = new DataView(buffer);
	const bodyCount = view.getUint32(24, true);
	const float64Coeffs = (view.getUint8(28) & CHEBYSHEV_FLAG_FLOAT64_COEFFS) !== 0;
	const coeffBytes = float64Coeffs ? 8 : 4;

	const bodies: ChebyshevBody[] = [];
	let offset = HEADER_SIZE;

	for (let b = 0; b < bodyCount; b++) {
		const naifId = view.getInt32(offset, true);
		const parentId = view.getInt32(offset + 4, true);
		const objIdValue = view.getInt32(offset + 8, true);
		const radiusKm = view.getFloat32(offset + 12, true);
		const coeffsPerAxis = view.getUint16(offset + 16, true);
		const idType = view.getUint8(offset + 18) as IdType;
		const hasLocalized = view.getUint8(offset + 19) === 1;
		const objectType = view.getUint8(offset + 20);
		// offset 21 reserved
		const segmentCount = view.getUint16(offset + 22, true);
		const visibleFromDays = view.getFloat32(offset + 24, true);
		// offsets 28..31 reserved (pad keeping float64 segments 8-aligned)
		offset += CHEBYSHEV_BODY_HEADER_SIZE;
		// Empty string when id-type is unknown — store/loaders will drop the row.
		const id = buildObjectId(idType, objIdValue) ?? '';
		if (!id) {
			console.warn(
				`chebyshev body[${b}] (naifId=${naifId}) has unknown id-type ${idType}; routing keyed lookups will skip it`
			);
		}

		const startJds = new Float64Array(segmentCount);
		const endJds = new Float64Array(segmentCount);
		const coeffsPerSeg = 3 * coeffsPerAxis;
		const coeffs: Float32Array | Float64Array = float64Coeffs
			? new Float64Array(coeffsPerSeg * segmentCount)
			: new Float32Array(coeffsPerSeg * segmentCount);
		const segCoeffBytes = coeffsPerSeg * coeffBytes;

		for (let s = 0; s < segmentCount; s++) {
			startJds[s] = view.getFloat64(offset, true);
			endJds[s] = view.getFloat64(offset + 8, true);
			offset += 16;
			// Typed-array view needs `offset` aligned to its element size.
			// f32: stride 16 + 12·N is 4-aligned. f64: stride 16 + 24·N is
			// 8-aligned, and the 32-byte body header preserves it across body
			// boundaries.
			if (float64Coeffs) {
				const segCoeffs = new Float64Array(buffer, offset, coeffsPerSeg);
				(coeffs as Float64Array).set(segCoeffs, s * coeffsPerSeg);
			} else {
				const segCoeffs = new Float32Array(buffer, offset, coeffsPerSeg);
				(coeffs as Float32Array).set(segCoeffs, s * coeffsPerSeg);
			}
			offset += segCoeffBytes;
		}

		bodies.push({
			id,
			naifId,
			parentId,
			hasLocalized,
			objectType,
			radiusKm,
			visibleFromDays,
			coeffsPerAxis,
			startJds,
			endJds,
			coeffs
		});
	}

	return { startJd, endJd, bodies };
}
