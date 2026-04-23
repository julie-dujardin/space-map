/**
 * Binary reader for chebyshev data.bin — position polynomial segments.
 *
 * One body per record; each body holds segment-wise Chebyshev coefficients for
 * ECLIPJ2000 parent-relative position in km. Segment starts/ends are float64
 * (JD precision), coefficients are float32.
 */

import {
	CHEBYSHEV_BODY_HEADER_SIZE,
	CHEBYSHEV_HEADER_SIZE,
	CHEBYSHEV_MAGIC,
	CHEBYSHEV_VERSION,
	FORMAT_POSITION_ONLY
} from '$lib/fetch/chebyshev/constants';

export interface ChebyshevBody {
	naifId: number;
	parentNaifId: number;
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

function parseHeader(view: DataView): {
	formatType: number;
	startJd: number;
	endJd: number;
	bodyCount: number;
} {
	const magic = view.getUint32(0, true);
	if (magic !== CHEBYSHEV_MAGIC) {
		throw new Error(`Invalid chebyshev file: bad magic 0x${magic.toString(16)}`);
	}
	const version = view.getUint16(4, true);
	if (version !== CHEBYSHEV_VERSION) {
		throw new Error(`Unsupported chebyshev version: ${version}`);
	}
	const formatType = view.getUint16(6, true);
	if (formatType !== FORMAT_POSITION_ONLY) {
		throw new Error(`Unknown chebyshev format type: ${formatType}`);
	}
	return {
		formatType,
		startJd: view.getFloat64(8, true),
		endJd: view.getFloat64(16, true),
		bodyCount: view.getUint32(24, true)
	};
}

export function parseChebyshev(buffer: ArrayBuffer): ChebyshevChunk {
	const view = new DataView(buffer);
	const { startJd, endJd, bodyCount } = parseHeader(view);

	const bodies: ChebyshevBody[] = [];
	let offset = CHEBYSHEV_HEADER_SIZE;

	for (let b = 0; b < bodyCount; b++) {
		const naifId = view.getInt32(offset, true);
		const parentNaifId = view.getInt32(offset + 4, true);
		const radiusKm = view.getFloat32(offset + 8, true);
		const coeffsPerAxis = view.getUint16(offset + 12, true);
		const segmentCount = view.getUint32(offset + 16, true);
		offset += CHEBYSHEV_BODY_HEADER_SIZE;

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
			naifId,
			parentNaifId,
			radiusKm,
			coeffsPerAxis,
			startJds,
			endJds,
			coeffs
		});
	}

	return { startJd, endJd, bodies };
}
