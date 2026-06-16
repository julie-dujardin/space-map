/**
 * Tests for `chunkIndexForJd` and the zoom-shape discriminators.
 *
 * The frontend's moon hot-reload trusts these two helpers to map sim time
 * onto the right binary chunk. A wrong clamp here puts the user on a stale
 * chunk (or off-by-one) without any visible error, so the boundary cases
 * matter more than the fence-post arithmetic suggests.
 */

import { describe, expect, it } from 'vitest';
import {
	chunkIndexForJd,
	isChebyshev,
	isChunkIndexed,
	isDateSegmented,
	isParted,
	partsForDate,
	snapshotDate,
	type ChebyshevZoom,
	type ChunkIndexedZoom,
	type DateSegmentedZoom,
	type PartedZoom
} from './metadata';

const ZOOM: ChunkIndexedZoom = {
	shape: 'chunked-parted',
	label: 'index',
	chunks: 200,
	chunk_days: 182.625,
	start_jd: 2433282.5,
	parts: 1
};

const CHUNK_DAYS = ZOOM.chunk_days;

describe('chunkIndexForJd', () => {
	it('returns 0 for jd exactly at start_jd', () => {
		expect(chunkIndexForJd(ZOOM, ZOOM.start_jd)).toBe(0);
	});

	it('returns 0 just inside the first chunk', () => {
		expect(chunkIndexForJd(ZOOM, ZOOM.start_jd + 0.001)).toBe(0);
	});

	it('returns 0 for jd well before start_jd (clamped low)', () => {
		expect(chunkIndexForJd(ZOOM, 1_000_000)).toBe(0);
	});

	it('returns chunks - 1 for jd well past the final chunk', () => {
		expect(chunkIndexForJd(ZOOM, ZOOM.start_jd + 1_000_000)).toBe(ZOOM.chunks - 1);
	});

	it('returns chunks - 1 at the exact final-chunk boundary', () => {
		// Final chunk covers [(chunks-1) * w, chunks * w). At chunks * w the JD
		// is one past coverage and must clamp to chunks-1, not overflow.
		const endJd = ZOOM.start_jd + ZOOM.chunks * CHUNK_DAYS;
		expect(chunkIndexForJd(ZOOM, endJd)).toBe(ZOOM.chunks - 1);
	});

	it('lands on the correct chunk for an interior midpoint', () => {
		// Middle of chunk 17: floor((midJd - start) / w) === 17.
		const midJd = ZOOM.start_jd + (17 + 0.5) * CHUNK_DAYS;
		expect(chunkIndexForJd(ZOOM, midJd)).toBe(17);
	});

	it('crosses cleanly at chunk boundaries', () => {
		// At exactly start + n * w the index becomes n. floor((n*w - n*w) / w)
		// = 0 for n=0 (covered above) and = n for n>0 with no FP slop, since
		// multiplication and division use the same `chunk_days`.
		for (const n of [1, 50, 100, 199]) {
			const boundaryJd = ZOOM.start_jd + n * CHUNK_DAYS;
			expect(chunkIndexForJd(ZOOM, boundaryJd)).toBe(n);
		}
	});

	it('handles a single-chunk zoom', () => {
		const single: ChunkIndexedZoom = {
			shape: 'chunked-parted',
			label: 'index',
			chunks: 1,
			chunk_days: 1826.25,
			start_jd: 2400000.0,
			parts: 1
		};
		expect(chunkIndexForJd(single, single.start_jd)).toBe(0);
		expect(chunkIndexForJd(single, single.start_jd + 100)).toBe(0);
		expect(chunkIndexForJd(single, single.start_jd - 100)).toBe(0);
	});
});

describe('zoom-shape discriminators', () => {
	const flat: PartedZoom = { shape: 'parted', parts: 1 };
	const dated: DateSegmentedZoom = {
		shape: 'chunked-parted',
		label: 'date',
		start_date: '2026-04-23',
		end_date: '2026-04-27',
		parts: 1,
		parts_by_date: {
			'2026-04-23': 1,
			'2026-04-24': 1,
			'2026-04-25': 1,
			'2026-04-26': 1,
			'2026-04-27': 1
		}
	};
	const cheb: ChebyshevZoom = {
		shape: 'chunked',
		chunks: 20,
		chunk_days: 1826.25,
		start_jd: 2433282.5,
		end_jd: 2469807.5
	};

	it('isChunkIndexed picks only the chunked-parted/index shape', () => {
		expect(isChunkIndexed(flat)).toBe(false);
		expect(isChunkIndexed(dated)).toBe(false);
		expect(isChunkIndexed(cheb)).toBe(false);
		expect(isChunkIndexed(ZOOM)).toBe(true);
	});

	it('isDateSegmented picks only the chunked-parted/date shape', () => {
		expect(isDateSegmented(flat)).toBe(false);
		expect(isDateSegmented(dated)).toBe(true);
		expect(isDateSegmented(cheb)).toBe(false);
		expect(isDateSegmented(ZOOM)).toBe(false);
	});

	it('isParted picks only the static parted shape', () => {
		expect(isParted(flat)).toBe(true);
		expect(isParted(dated)).toBe(false);
		expect(isParted(cheb)).toBe(false);
		expect(isParted(ZOOM)).toBe(false);
	});

	it('isChebyshev picks only the chebyshev shape', () => {
		expect(isChebyshev(flat)).toBe(false);
		expect(isChebyshev(dated)).toBe(false);
		expect(isChebyshev(cheb)).toBe(true);
		expect(isChebyshev(ZOOM)).toBe(false);
	});

	it('shape predicates are mutually exclusive', () => {
		// The export emits one shape per zoom; if multiple predicates fire on
		// the same zoom the manifest reader's dispatch is ambiguous.
		for (const zoom of [flat, dated, ZOOM, cheb]) {
			const matches = [
				isParted(zoom),
				isDateSegmented(zoom),
				isChunkIndexed(zoom),
				isChebyshev(zoom)
			].filter(Boolean).length;
			expect(matches).toBe(1);
		}
	});
});

describe('snapshotDate / partsForDate (sparse date axis)', () => {
	// Weekly history (Mondays) + a daily-ish recent cluster, irregular gaps.
	const sparse: DateSegmentedZoom = {
		shape: 'chunked-parted',
		label: 'date',
		start_date: '2024-01-01',
		end_date: '2024-06-17',
		parts: 3,
		parts_by_date: {
			'2024-01-01': 3,
			'2024-01-08': 3,
			'2024-01-15': 2,
			'2024-06-17': 1
		}
	};
	const at = (iso: string) => new Date(`${iso}T12:00:00Z`);

	it('snaps to the nearest available snapshot, not a day-truncation', () => {
		// Tue 2024-01-09 is closer to Mon 01-08 than Mon 01-15.
		expect(snapshotDate(sparse, at('2024-01-09'))).toBe('2024-01-08');
		// Thu 2024-01-11 sits midweek but still nearer 01-08.
		expect(snapshotDate(sparse, at('2024-01-11'))).toBe('2024-01-08');
		// Sat 2024-01-13 is nearer 01-15.
		expect(snapshotDate(sparse, at('2024-01-13'))).toBe('2024-01-15');
	});

	it('clamps out-of-range dates to the first/last snapshot', () => {
		expect(snapshotDate(sparse, at('2020-01-01'))).toBe('2024-01-01');
		expect(snapshotDate(sparse, at('2030-01-01'))).toBe('2024-06-17');
	});

	it('partsForDate returns the per-date count, capped', () => {
		expect(partsForDate(sparse, '2024-01-01')).toBe(3);
		expect(partsForDate(sparse, '2024-01-15')).toBe(2);
		expect(partsForDate(sparse, '2024-06-17')).toBe(1);
		expect(partsForDate(sparse, '2024-01-01', 2)).toBe(2); // cap clamps
		expect(partsForDate(sparse, '2024-01-15', 5)).toBe(2); // cap above count
	});
});
