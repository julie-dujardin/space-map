import { describe, expect, it } from 'vitest';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { panoramaHighlights } from './highlights';

function entry(id: string, time: string, sphere: number, color = 'grayscale'): PanoramaEntry {
	return { id, time, lat: 0, lon: 0, north_offset_deg: 0, sphere_percent: sphere, color };
}

describe('panoramaHighlights', () => {
	it('keeps a traverse shorter than the limit whole', () => {
		const run = [entry('a', '2021-01-01T00:00:00Z', 10), entry('b', '2021-06-01T00:00:00Z', 20)];
		expect(panoramaHighlights(run, 20)).toEqual(run);
	});

	it('takes the best-covered entry of each stretch, not the best overall', () => {
		const run = [
			entry('early-poor', '2021-01-01T00:00:00Z', 10),
			entry('early-best', '2021-01-02T00:00:00Z', 90),
			entry('late-poor', '2021-12-01T00:00:00Z', 20),
			entry('late-best', '2021-12-31T00:00:00Z', 30)
		];
		expect(panoramaHighlights(run, 2).map((e) => e.id)).toEqual(['early-best', 'late-best']);
	});

	it('prefers colour over a slightly wider grayscale sweep', () => {
		const run = [
			entry('grey', '2021-01-01T00:00:00Z', 60),
			entry('color', '2021-01-02T00:00:00Z', 50, 'rgb'),
			entry('last', '2021-12-31T00:00:00Z', 10)
		];
		expect(panoramaHighlights(run, 2).map((e) => e.id)).toEqual(['color', 'last']);
	});

	it('fills the count from the stretches that have entries when others are empty', () => {
		const run = [
			entry('a', '2021-01-01T00:00:00Z', 10),
			entry('b', '2021-01-02T00:00:00Z', 90),
			entry('c', '2021-01-03T00:00:00Z', 50),
			entry('d', '2021-12-31T00:00:00Z', 20)
		];
		expect(panoramaHighlights(run, 3)).toHaveLength(3);
	});

	it('returns the picks in time order', () => {
		const run = [
			entry('a', '2021-01-01T00:00:00Z', 10),
			entry('b', '2021-06-01T00:00:00Z', 90),
			entry('c', '2021-12-31T00:00:00Z', 50)
		];
		expect(panoramaHighlights(run, 2).map((e) => e.time)).toEqual([
			'2021-06-01T00:00:00Z',
			'2021-12-31T00:00:00Z'
		]);
	});
});
