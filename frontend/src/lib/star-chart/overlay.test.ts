import { describe, expect, it } from 'vitest';
import type { FigureChart } from './figure';
import { project } from './frame';
import {
	chartPoints,
	chooseFrame,
	findNames,
	layoutNames,
	linePath,
	noNames,
	rememberNames,
	type ChartNames
} from './overlay';
import type { Pixels } from './sky';
import { projectStarChart } from './star-chart';

const unit = (ra: number, dec: number): [number, number, number] => {
	const r = (ra * Math.PI) / 180;
	const d = (dec * Math.PI) / 180;
	return [Math.cos(d) * Math.cos(r), Math.cos(d) * Math.sin(r), Math.sin(d)];
};

const a = unit(80, 0);
const b = unit(90, 10);
const c = unit(85, -5);
const chart: FigureChart = {
	points: [a, b, c],
	lines: [[a, b]],
	stars: [
		{ id: 1, direction: a },
		{ id: 2, direction: b }
	],
	standIns: [{ direction: c, name: 'M42' }],
	neighbours: [{ id: 3, direction: unit(86, 3), given: 'Near' }]
};

/** A dark sky with a bright disc at each of `at`, in a picture `ratio` times the frame. */
function sky(width: number, height: number, ratio: number, at: [number, number][]): Pixels {
	const w = Math.round(width * ratio);
	const h = Math.round(height * ratio);
	const data = new Uint8ClampedArray(w * h * 4);
	for (const [x, y] of at) {
		for (let dy = -2; dy <= 2; dy++)
			for (let dx = -2; dx <= 2; dx++) {
				const i = ((Math.round(y * ratio) + dy) * w + Math.round(x * ratio) + dx) * 4;
				data[i] = data[i + 1] = data[i + 2] = 255;
			}
	}
	return { data, width: w, height: h };
}

describe('the frame of a chart', () => {
	it('fits the figure at its own shape, or fills the box', () => {
		const fit = chooseFrame(chart, {
			width: 400,
			height: 0,
			fill: false,
			labels: true,
			minAspect: 1,
			maxAspect: 1.6
		});
		expect(fit.frame?.width).toBe(400);
		expect(fit.frame?.height).toBe(Math.round(400 / fit.ratio));
		const fill = chooseFrame(chart, {
			width: 400,
			height: 300,
			fill: true,
			labels: true,
			minAspect: 1,
			maxAspect: 1.6
		});
		expect([fill.frame?.width, fill.frame?.height]).toEqual([400, 300]);
	});

	it('has none with no size or no chart', () => {
		expect(
			chooseFrame(null, {
				width: 400,
				height: 0,
				fill: false,
				labels: true,
				minAspect: 1,
				maxAspect: 1.6
			}).frame
		).toBeNull();
		expect(
			chooseFrame(chart, {
				width: 0,
				height: 0,
				fill: false,
				labels: true,
				minAspect: 1,
				maxAspect: 1.6
			}).frame
		).toBeNull();
	});
});

describe('what a chart draws over its sky', () => {
	const frame = chooseFrame(chart, {
		width: 400,
		height: 300,
		fill: true,
		labels: true,
		minAspect: 1,
		maxAspect: 1.6
	}).frame!;
	const points = chartPoints(frame, chart);

	it('projects the lines, stars and stand-ins', () => {
		expect(points.segments).toEqual([[...project(frame, a), ...project(frame, b)]]);
		expect(points.stars).toEqual([project(frame, a), project(frame, b)]);
		expect(points.standIns).toEqual([project(frame, c)]);
	});

	it('projects a place given in degrees as a direction', () => {
		const [x, y] = projectStarChart(frame, 90, 10);
		expect(x).toBeCloseTo(points.stars[1][0], 6);
		expect(y).toBeCloseTo(points.stars[1][1], 6);
	});

	it('cuts each line short at both ends', () => {
		const [x1, y1, x2, y2] = points.segments[0];
		const path = linePath(points.segments, true);
		const [mx, my, lx, ly] = path.match(/-?\d+\.\d/g)!.map(Number);
		const length = Math.hypot(x2 - x1, y2 - y1);
		expect(Math.hypot(mx - x1, my - y1)).toBeCloseTo(5, 0);
		expect(Math.hypot(lx - x2, ly - y2)).toBeCloseTo(5, 0);
		expect(Math.hypot(lx - mx, ly - my)).toBeLessThan(length);
	});

	it('finds the members, then the neighbours that stand out as much', async () => {
		const near = project(frame, chart.neighbours[0].direction);
		const pixels = sky(400, 300, 2, [...points.stars, near]);
		const names = { 1: 'Alpha', 2: null, 3: 'Near' } as Record<number, string | null>;
		const heard: ChartNames[] = [];
		await findNames(
			{
				frame,
				chart,
				pixels,
				points,
				most: 14,
				neighbours: true,
				name: async (star) => names[star.id],
				current: () => true
			},
			(found) => heard.push(found)
		);
		expect(heard).toHaveLength(2);
		expect(heard[0].own.map(({ name }) => name)).toEqual(['M42', 'Alpha']);
		expect(heard[0].members.map(({ name }) => name).sort()).toEqual(['Alpha', null]);
		expect(heard[1].around).toEqual([{ x: near[0], y: near[1], name: 'Near', id: 'x-3' }]);
		const placed = layoutNames(heard[1], (text) => text.length * 6);
		expect(placed.map(({ name, neighbour }) => [name, neighbour])).toEqual([
			['M42', false],
			['Alpha', false],
			['Near', true]
		]);
	});

	it('names no neighbour on a chart with no sky, or when asked for none', async () => {
		const run = (pixels: Pixels | null, neighbours: boolean) => {
			const heard: ChartNames[] = [];
			return findNames(
				{
					frame,
					chart,
					pixels,
					points,
					most: 14,
					neighbours,
					name: async () => 'x',
					current: () => true
				},
				(found) => heard.push(found)
			).then(() => heard);
		};
		expect(await run(null, true)).toHaveLength(1);
		expect(await run(sky(400, 300, 2, points.stars), false)).toHaveLength(1);
	});

	it('stops a search that is no longer current', async () => {
		const heard: ChartNames[] = [];
		await findNames(
			{
				frame,
				chart,
				pixels: null,
				points,
				most: 14,
				neighbours: true,
				name: async () => 'x',
				current: () => false
			},
			(found) => heard.push(found)
		);
		expect(heard).toEqual([]);
	});

	it('keeps no name off a taken box', () => {
		const names: ChartNames = {
			...noNames(frame, points),
			limit: 5,
			own: [{ x: 200, y: 150, name: 'Alpha' }]
		};
		const taken = [{ left: 0, top: 0, width: 400, height: 300 }];
		expect(layoutNames(names, () => 30, taken)).toEqual([]);
		expect(layoutNames(names, () => 30)).toHaveLength(1);
	});

	it('asks for the name of a star once', async () => {
		let asked = 0;
		const name = rememberNames(async () => {
			asked++;
			return 'Alpha';
		});
		await name(chart.stars[0]);
		await name(chart.stars[0]);
		expect(asked).toBe(1);
	});
});
