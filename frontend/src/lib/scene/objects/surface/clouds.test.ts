import { describe, it, expect } from 'vitest';

import { cloudFrameForJd, type CloudCoverage } from './clouds';
import { dateToJD } from '$lib/time/jd';

/**
 * A frame is the start of the span it covers, not a sample point: it holds
 * until the next one is published. These pin that down across a frozen
 * upstream and across a hole where nothing was published at all.
 */

const jd = (iso: string) => dateToJD(new Date(iso));

// Shaped like the real export: a run holding 05-05, nothing until 08-03.
const FRAMES = ['2026050500', '2026050512', '2026080300', '2026080306'];
const COVERAGE: CloudCoverage = [
	['2026050500', '2026050512'],
	['2026080300', '2026080306']
];

describe('cloudFrameForJd', () => {
	it('holds a frame until the next one is published', () => {
		expect(cloudFrameForJd(jd('2026-05-05T00:00:00Z'), FRAMES, COVERAGE)).toBe('2026050500');
		expect(cloudFrameForJd(jd('2026-05-05T09:00:00Z'), FRAMES, COVERAGE)).toBe('2026050500');
		expect(cloudFrameForJd(jd('2026-05-05T11:59:00Z'), FRAMES, COVERAGE)).toBe('2026050500');
	});

	it('never shows a frame before it was published', () => {
		// Past the midpoint, a nearest-match pick would flip to the 12:00 frame
		// five hours early — the failure dedup makes visible.
		expect(cloudFrameForJd(jd('2026-05-05T07:00:00Z'), FRAMES, COVERAGE)).toBe('2026050500');
	});

	it('takes a frame exactly at its own timestamp', () => {
		expect(cloudFrameForJd(jd('2026-05-05T12:00:00Z'), FRAMES, COVERAGE)).toBe('2026050512');
	});

	it('holds the last frame of a run to the end of its slot', () => {
		expect(cloudFrameForJd(jd('2026-08-03T08:59:00Z'), FRAMES, COVERAGE)).toBe('2026080306');
	});

	it('does not hold a frame across a gap with no data', () => {
		// Mid-June sits in no run. Holding would answer 05-05's 12:00 frame;
		// the diurnal fallback matches the sim's hour instead.
		expect(cloudFrameForJd(jd('2026-06-15T06:00:00Z'), FRAMES, COVERAGE)).toBe('2026080306');
	});

	it('falls back to the frame span when the export states no coverage', () => {
		expect(cloudFrameForJd(jd('2026-05-05T09:00:00Z'), FRAMES)).toBe('2026050500');
	});

	it('has no answer without frames', () => {
		expect(cloudFrameForJd(jd('2026-05-05T00:00:00Z'), [])).toBeUndefined();
	});
});
