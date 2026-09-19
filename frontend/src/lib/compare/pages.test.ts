/**
 * Tests the size bands: where the row is cut, and the neighbours each band
 * hands to the next. Getting the cut wrong either crowds a row until the small
 * bodies vanish, or splits a set that reads fine on one scale.
 */

import { describe, expect, it } from 'vitest';
import { bandsBySize } from './pages';

const size = (n: number) => n;

describe('bandsBySize', () => {
	it('keeps one band while the sizes stay close', () => {
		const bands = bandsBySize([6779, 3475, 939, 525], size);
		expect(bands).toHaveLength(1);
		expect(bands[0].items).toEqual([6779, 3475, 939, 525]);
	});

	it('cuts where the sizes jump, largest first in each band', () => {
		const bands = bandsBySize([32.7, 939, 6779, 52.8, 3475, 18.2, 525, 31.4], size);
		expect(bands.map((b) => b.items)).toEqual([
			[6779, 3475, 939, 525],
			[52.8, 32.7, 31.4, 18.2]
		]);
	});

	it('hands each band its neighbours, so the row can draw them', () => {
		const bands = bandsBySize([6779, 3475, 525, 52.8, 18.2], size);
		expect(bands[0].previous).toBeUndefined();
		expect(bands[0].next).toBe(52.8);
		expect(bands[1].previous).toBe(525);
		expect(bands[1].next).toBeUndefined();
	});

	it('splits exactly above the gap, not at it', () => {
		expect(bandsBySize([80, 10], size, 8)).toHaveLength(1);
		expect(bandsBySize([81, 10], size, 8)).toHaveLength(2);
	});

	it('cuts a band that stretches too far, even with no jump in it', () => {
		// Every step is small, but the last body would be 1% of the first.
		const smooth = [100, 50, 25, 12, 6, 3, 1.5, 0.8];
		expect(bandsBySize(smooth, size, 8, 25).map((b) => b.items)).toEqual([
			[100, 50, 25, 12, 6],
			[3, 1.5, 0.8]
		]);
	});

	it('drops what has no size, and has no bands for an empty set', () => {
		expect(bandsBySize([100, 0, NaN, 50], size)[0].items).toEqual([100, 50]);
		expect(bandsBySize([], size)).toEqual([]);
	});
});
