import { describe, expect, it } from 'vitest';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import {
	entryJd,
	hasExtent,
	hasHeading,
	scaleBar,
	splitPath,
	traverseFrame,
	viewWedge
} from './minimap';

function entry(id: string, time: string, lat = 0, lon = 0): PanoramaEntry {
	return { id, time, lat, lon, north_offset_deg: 0 };
}

const run = [
	entry('a', '2021-01-01T00:00:00Z', 0, 0),
	entry('b', '2021-01-02T00:00:00Z', 0, 1),
	entry('c', '2021-01-03T00:00:00Z', 1, 1)
];

describe('splitPath', () => {
	it('shares the clock point between past and future', () => {
		const { past, future } = splitPath(run, entryJd(run[1]));
		expect(past).toEqual([
			{ lon: 0, lat: 0 },
			{ lon: 1, lat: 0 }
		]);
		expect(future).toEqual([
			{ lon: 1, lat: 0 },
			{ lon: 1, lat: 1 }
		]);
	});

	it('is all future before the first and all past after the last', () => {
		expect(splitPath(run, entryJd(run[0]) - 1).past).toEqual([]);
		expect(splitPath(run, entryJd(run[0]) - 1).future).toHaveLength(3);
		expect(splitPath(run, entryJd(run[2]) + 1).past).toHaveLength(3);
		expect(splitPath(run, entryJd(run[2]) + 1).future).toHaveLength(1);
	});
});

describe('viewWedge', () => {
	it('opens north around a north heading', () => {
		const points = viewWedge(entry('a', '2021-01-01T00:00:00Z'), 0, 90, 1);
		expect(points[0]).toEqual({ lon: 0, lat: 0 });
		expect(points[1].lon).toBeCloseTo(-Math.SQRT1_2, 5);
		expect(points[points.length - 1].lon).toBeCloseTo(Math.SQRT1_2, 5);
		expect(points[5].lat).toBeCloseTo(1, 5);
	});
});

describe('traverseFrame', () => {
	it('pads the box and holds a floor for a short traverse', () => {
		const frame = traverseFrame(run, 0.1);
		expect(frame.centerLon).toBe(0.5);
		expect(frame.lonSpan).toBeCloseTo(1.4, 5);
		expect(traverseFrame([run[0]], 0.1).latSpan).toBe(0.1);
	});
});

describe('scaleBar', () => {
	it('picks the longest round length that fits', () => {
		expect(scaleBar(1, 100)).toEqual({ metres: 100, px: 100 });
		expect(scaleBar(1, 99)).toEqual({ metres: 50, px: 50 });
		expect(scaleBar(0.5, 100)).toEqual({ metres: 50, px: 100 });
		expect(scaleBar(3, 100)).toEqual({ metres: 200, px: 200 / 3 });
	});
});

describe('hasHeading', () => {
	it('is false only where the sphere sits at an unknown azimuth', () => {
		expect(hasHeading(entry('a', '2021-01-01T00:00:00Z'))).toBe(true);
		expect(
			hasHeading({ ...entry('a', '2021-01-01T00:00:00Z'), orientation: 'caption-aligned' })
		).toBe(true);
		expect(hasHeading({ ...entry('a', '2021-01-01T00:00:00Z'), orientation: 'unknown' })).toBe(
			false
		);
	});

	it('is false for a stop published without its sphere', () => {
		const placed: PanoramaEntry = { ...entry('a', '2021-01-01T00:00:00Z'), imagery: 'withheld' };
		delete placed.north_offset_deg;
		expect(hasHeading(placed)).toBe(false);
	});
});

describe('hasExtent', () => {
	it('is true for a traverse that covered ground', () => {
		expect(hasExtent(run)).toBe(true);
	});

	it('is false for a lander that shot everything from one spot', () => {
		const spot = [
			entry('a', '1971-08-01T00:00:00Z', 26.13, 3.63),
			entry('b', '1971-08-02T00:00:00Z', 26.13, 3.63)
		];
		expect(hasExtent(spot)).toBe(false);
		expect(hasExtent([spot[0]])).toBe(false);
		expect(hasExtent([])).toBe(false);
	});
});
