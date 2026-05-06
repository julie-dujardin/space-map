/**
 * Binary reader for the chebyshev payload of a position file.
 *
 * One body per record; each body holds segment-wise Chebyshev coefficients for
 * ECLIPJ2000 parent-relative position in km. Segment starts/ends are float64
 * (JD precision), coefficients are float32.
 */

import {
	CHEBYSHEV_BODY_HEADER_SIZE,
	HEADER_SIZE,
	IdType,
	buildObjectId
} from '$lib/fetch/position/format';

export interface ChebyshevBody {
	/**
	 * Full Object ID (`<prefix>-<numeric>`), reconstructed from the body
	 * header's `id_type` + `obj_id_value`. Pluto and the perturber asteroids
	 * ride as `spkid-…` even though `naifId` is their planetary NAIF ID, so
	 * use this for cross-referencing with the elements export and object
	 * detail bundles.
	 *
	 * Empty string when the body header carries an unknown id-type — the
	 * consumer should drop the row rather than ship a malformed key.
	 */
	id: string;
	naifId: number;
	parentNaifId: number;
	/** 1 iff the body has a localized detail bundle in at least one language. */
	hasLocalized: boolean;
	/** ObjectType ordinal (same map as the elements `objectType` column). */
	objectType: number;
	/** NaN if unknown in the source. */
	radiusKm: number;
	/** Polynomial degree + 1 per axis. */
	coeffsPerAxis: number;
	/** Segment starts (JD TDB), sorted ascending, contiguous with endJds. */
	startJds: Float64Array;
	/** Segment ends (JD TDB), exclusive upper bound of each segment. */
	endJds: Float64Array;
	/**
	 * Flat coefficient store, laid out per segment as
	 * `[cx_0..cx_{N-1}, cy_0..cy_{N-1}, cz_0..cz_{N-1}]` with `N = coeffsPerAxis`.
	 * Length = `segmentCount * 3 * coeffsPerAxis`.
	 */
	coeffs: Float32Array;
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

	const bodies: ChebyshevBody[] = [];
	let offset = HEADER_SIZE;

	for (let b = 0; b < bodyCount; b++) {
		const naifId = view.getInt32(offset, true);
		const parentNaifId = view.getInt32(offset + 4, true);
		const objIdValue = view.getInt32(offset + 8, true);
		const radiusKm = view.getFloat32(offset + 12, true);
		const coeffsPerAxis = view.getUint16(offset + 16, true);
		const idType = view.getUint8(offset + 18) as IdType;
		const hasLocalized = view.getUint8(offset + 19) === 1;
		const objectType = view.getUint8(offset + 20);
		// offset 21 reserved
		const segmentCount = view.getUint16(offset + 22, true);
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
		const coeffs = new Float32Array(coeffsPerSeg * segmentCount);
		const segCoeffBytes = coeffsPerSeg * 4;

		for (let s = 0; s < segmentCount; s++) {
			startJds[s] = view.getFloat64(offset, true);
			endJds[s] = view.getFloat64(offset + 8, true);
			offset += 16;
			// offset is 4-byte aligned (16 + 12*N is a multiple of 4), so a
			// Float32Array view is valid.
			const segCoeffs = new Float32Array(buffer, offset, coeffsPerSeg);
			coeffs.set(segCoeffs, s * coeffsPerSeg);
			offset += segCoeffBytes;
		}

		bodies.push({
			id,
			naifId,
			parentNaifId,
			hasLocalized,
			objectType,
			radiusKm,
			coeffsPerAxis,
			startJds,
			endJds,
			coeffs
		});
	}

	return { startJd, endJd, bodies };
}
