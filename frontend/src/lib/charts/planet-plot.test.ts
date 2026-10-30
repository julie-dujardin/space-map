/**
 * The Planets charts draw measured values and minimum masses, name the Solar
 * System's planets, and count the estimates they leave out.
 */

import { describe, expect, it } from 'vitest';
import type { PlanetPlotFile } from '$lib/fetch/groups/planet-plot';
import {
	logDomain,
	logExtent,
	logTicks,
	placeLabels,
	planetPlotPoints,
	powerOfTenLabel
} from './planet-plot';

/** Earth, then a true mass, a minimum mass, an estimated mass, an estimated
 *  radius and a planet with no radius. */
const FILE: PlanetPlotFile = {
	mass: [1, 300, 600, 5, 20, 2],
	mass_flag: [0, 0, 1, 2, 0, 0],
	radius: [1, 11, 12, 1.5, 4, null],
	radius_flag: [0, 0, 0, 0, 2, null],
	semi_major_axis: [1, 0.05, 2, 0.1, 0.3, 0.02],
	semi_major_axis_flag: [0, 0, 0, 0, 0, 0],
	solar: ['naif-399']
};

describe('planetPlotPoints', () => {
	it('plots mass against radius, measured values only', () => {
		const points = planetPlotPoints(FILE, 'radius');
		expect(points.solar).toEqual([{ id: 'naif-399', x: 1, y: 1 }]);
		expect(points.measured).toEqual([{ x: 300, y: 11 }]);
		expect(points.minimum).toEqual([{ x: 600, y: 12 }]);
		expect(points.estimated).toBe(2);
	});

	it('plots semi-major axis against mass', () => {
		const points = planetPlotPoints(FILE, 'distance');
		expect(points.measured).toEqual([
			{ x: 0.05, y: 300 },
			{ x: 0.3, y: 20 },
			{ x: 0.02, y: 2 }
		]);
		expect(points.minimum).toEqual([{ x: 2, y: 600 }]);
		expect(points.estimated).toBe(1);
	});
});

describe('logDomain', () => {
	it('keeps the pad clear of points at each end', () => {
		const extent = logExtent([4100, 0.02, 3]);
		expect(extent).toEqual([0.02, 4100]);
		const [lo, hi] = logDomain(extent, 200);
		const px = (v: number) => (200 * Math.log10(v / lo)) / Math.log10(hi / lo);
		expect(px(0.02)).toBeCloseTo(12);
		expect(px(4100)).toBeCloseTo(188);
	});

	it('gives one value a decade at each end', () => {
		const [lo, hi] = logDomain(logExtent([5]), 200);
		expect(lo).toBeCloseTo(0.5);
		expect(hi).toBeCloseTo(50);
	});
});

describe('logTicks', () => {
	it('puts a tick on every decade', () => {
		expect(logTicks([0.05, 2000])).toEqual([0.1, 1, 10, 100, 1000]);
	});

	it('keeps every second decade on a long axis', () => {
		expect(logTicks([5e-4, 2e5])).toEqual([1e-3, 0.1, 10, 1000, 1e5]);
	});

	it('adds the 2 and the 5 on a short axis', () => {
		expect(logTicks([0.3, 8])).toEqual([0.5, 1, 2, 5]);
	});
});

describe('powerOfTenLabel', () => {
	it('writes a far power of ten as 10ⁿ and leaves the near ones to the digits', () => {
		expect(powerOfTenLabel(1e-3)).toBe('10⁻³');
		expect(powerOfTenLabel(1e5)).toBe('10⁵');
		expect(powerOfTenLabel(100)).toBeNull();
		expect(powerOfTenLabel(2e5)).toBeNull();
	});
});

describe('placeLabels', () => {
	it('names a dot on its right, and a crowded neighbour on its left', () => {
		const labels = placeLabels(
			[
				{ px: 100, py: 50, width: 30 },
				{ px: 92, py: 50, width: 30 }
			],
			300,
			100
		);
		expect(labels[0]).toEqual({ x: 106, y: 50, anchor: 'start' });
		expect(labels[1]).toEqual({ x: 86, y: 50, anchor: 'end' });
	});

	it('keeps a name inside the plot', () => {
		const [label] = placeLabels([{ px: 290, py: 50, width: 30 }], 300, 100);
		expect(label.anchor).toBe('end');
	});
});
