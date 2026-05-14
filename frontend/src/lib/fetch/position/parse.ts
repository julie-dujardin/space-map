/**
 * Top-level reader for position files. Dispatches on the format byte at offset
 * 6 of the common header to one of the section parsers (elements columnar
 * layout, chebyshev per-body segments, or probes per-sub-chunk records).
 *
 * Common header layout (24 bytes, 8-aligned):
 *   0   char[4]  magic = "SMAP"
 *   4   uint16   version
 *   6   uint8    format        (0 = elements, 1 = chebyshev, 2 = probes)
 *   7   uint8    reserved
 *   8   float64  start_jd
 *   16  float64  end_jd
 *
 * The probes payload's coefficient dtype (f32 vs f64) isn't in the file
 * header — it's a zone-level property surfaced by
 * `metadata.position.zones[zone].float64_coeffs`. Callers fetching a probes
 * file must pass `opts.probesFloat64` accordingly; the flag is ignored for
 * non-probes payloads.
 */

import { parseChebyshevPayload, type ChebyshevChunk } from '$lib/fetch/position/chebyshev/parse';
import { parseElementsPayload, type ElementColumns } from '$lib/fetch/position/elements/parse';
import {
	FORMAT_CHEBYSHEV,
	FORMAT_ELEMENTS,
	FORMAT_PROBES,
	MAGIC,
	VERSION
} from '$lib/fetch/position/format';
import { parseProbesPayload, type ProbeChunk } from '$lib/fetch/position/probes/parse';

export type PositionPayload =
	| { kind: 'elements'; columns: ElementColumns }
	| { kind: 'chebyshev'; chunk: ChebyshevChunk }
	| { kind: 'probes'; chunk: ProbeChunk };

export interface ParsePositionOptions {
	/** Required for FORMAT_PROBES files; ignored otherwise. Comes from the
	 *  zone's manifest entry (`float64_coeffs` boolean). */
	probesFloat64?: boolean;
}

/**
 * Read the common header, validate magic+version, and dispatch the rest of the
 * buffer to the section parser keyed by the format byte. Throws on bad magic,
 * unsupported version, or an unknown format byte.
 */
export function parsePosition(
	buffer: ArrayBuffer,
	opts: ParsePositionOptions = {}
): PositionPayload {
	const view = new DataView(buffer);
	const magic = view.getUint32(0, true);
	if (magic !== MAGIC) {
		throw new Error(`Invalid position file: bad magic 0x${magic.toString(16)}`);
	}
	const version = view.getUint16(4, true);
	if (version !== VERSION) {
		throw new Error(`Unsupported position file version: ${version}`);
	}
	const format = view.getUint8(6);
	const startJd = view.getFloat64(8, true);
	const endJd = view.getFloat64(16, true);

	if (format === FORMAT_ELEMENTS) {
		return { kind: 'elements', columns: parseElementsPayload(buffer, startJd, endJd) };
	}
	if (format === FORMAT_CHEBYSHEV) {
		return { kind: 'chebyshev', chunk: parseChebyshevPayload(buffer, startJd, endJd) };
	}
	if (format === FORMAT_PROBES) {
		return {
			kind: 'probes',
			chunk: parseProbesPayload(buffer, startJd, endJd, opts.probesFloat64 ?? false)
		};
	}
	throw new Error(`Unknown position-file format: ${format}`);
}
