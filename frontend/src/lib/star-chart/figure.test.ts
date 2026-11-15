import { describe, expect, it } from 'vitest';
import type { SkyCultureFile } from '$lib/fetch/extrasolar/skycultures';
import { figureChart, figurePlaced } from './figure';

const file = {
	token: 't',
	key: 'maya',
	members: [
		{ id: 1, position: [10, 0, 0] },
		{ id: 2, position: [0, 5, 0] },
		{ id: 3 },
		{ ref: 'DSO:M44', designation: 'M44', position: [0, 0, 100] },
		{ id: 5, position: [3, 4, 0] },
		{ id: 6, position: [0, 3, 4] }
	],
	figures: [
		{ id: 'a', kind: 'constellation', names: [], lines: [[0, 1, 2, 3, 0, 0]] },
		{ id: 'b', kind: 'asterism', names: [], lines: [], group: [4, 2] }
	],
	names: [
		{ member: 1, names: [{ native: 'Xux', english: 'Wasp' }] },
		{ member: 4, names: [{ pronounce: 'Ek' }] },
		{ member: 2, names: [{ english: 'No place' }] }
	]
} as unknown as SkyCultureFile;

const international = {
	members: [
		{ id: 5, position: [3, 4, 0] },
		{ id: 6, position: [0, 3, 4] }
	],
	figures: [],
	names: [
		{ member: 0, names: [{ english: 'Other name' }] },
		{ member: 1, names: [{ english: 'Vega' }] }
	]
} as unknown as SkyCultureFile;

describe('the chart of a figure', () => {
	it('draws the lines between the members that have a place', () => {
		const chart = figureChart(file, file.figures[0]);
		expect(chart.lines).toEqual([
			[
				[1, 0, 0],
				[0, 1, 0]
			],
			[
				[0, 0, 1],
				[1, 0, 0]
			]
		]);
		expect(chart.points).toHaveLength(3);
	});

	it('has the stars of the figure, with the name the culture gives', () => {
		const chart = figureChart(file, file.figures[0]);
		expect(chart.stars).toEqual([
			{ id: 1, direction: [1, 0, 0], given: undefined },
			{ id: 2, direction: [0, 1, 0], given: 'Wasp' }
		]);
	});

	it('marks a member that is no star, by the name of its row in the member list', () => {
		const chart = figureChart(file, file.figures[0]);
		expect(chart.standIns).toEqual([{ direction: [0, 0, 1], name: 'M44' }]);
	});

	it('marks a figure whose only place is such a member', () => {
		const alone = { id: 'c', kind: 'constellation', names: [], lines: [[3, 3]] } as never;
		const chart = figureChart(file, alone);
		expect(chart).toMatchObject({ stars: [], lines: [], standIns: [{ name: 'M44' }] });
		expect(chart.points).toHaveLength(1);
		expect(figurePlaced(file, alone)).toBe(true);
	});

	it('has no chart for a figure with no place in the sky', () => {
		const nowhere = { id: 'd', kind: 'asterism', names: [], lines: [[2]] } as never;
		expect(figurePlaced(file, nowhere)).toBe(false);
		expect(figurePlaced(file, file.figures[1])).toBe(true);
	});

	it('has the stars of a group with no lines', () => {
		const chart = figureChart(file, file.figures[1]);
		expect(chart.lines).toEqual([]);
		expect(chart.stars).toEqual([{ id: 5, direction: [0.6, 0.8, 0], given: 'Ek' }]);
	});

	it('takes the named stars out of the figure as neighbours', () => {
		const chart = figureChart(file, file.figures[0], [international]);
		expect(chart.neighbours).toEqual([
			{ id: 5, direction: [0.6, 0.8, 0], given: 'Ek' },
			{ id: 6, direction: [0, 0.6, 0.8], given: 'Vega' }
		]);
	});
});
