import { describe, expect, it } from 'vitest';
import { placeNames, segmentMeetsBox, type LabelCandidate } from './labels';

const FRAME = { width: 300, height: 200, gap: 6, limit: 10 };

function star(x: number, y: number, width = 50): LabelCandidate {
	return { x, y, width, height: 13 };
}

describe('the names of a chart', () => {
	it('puts a name to the right of its star', () => {
		const [label] = placeNames([star(100, 100)], FRAME);
		expect(label).toMatchObject({ index: 0, left: 106, top: 93.5 });
	});

	it('moves a name to the left at the right edge', () => {
		const [label] = placeNames([star(280, 100)], FRAME);
		expect(label.left + label.width).toBeLessThanOrEqual(274);
	});

	it('keeps two names apart, the first where it likes', () => {
		const labels = placeNames([star(100, 100), star(100, 110)], FRAME);
		expect(labels).toHaveLength(2);
		expect(labels[0].left).toBe(106);
		const [a, b] = labels;
		const apart =
			a.left + a.width <= b.left ||
			b.left + b.width <= a.left ||
			a.top + a.height <= b.top ||
			b.top + b.height <= a.top;
		expect(apart).toBe(true);
	});

	it('leaves out a name with no free side', () => {
		const labels = placeNames([star(10, 8, 290)], FRAME);
		expect(labels).toEqual([]);
	});

	it('stops at the limit, the first names first', () => {
		const stars = [star(50, 30), star(50, 90), star(50, 150)];
		const labels = placeNames(stars, { ...FRAME, limit: 2 });
		expect(labels.map(({ index }) => index)).toEqual([0, 1]);
	});

	it('does not cover another star', () => {
		const [label] = placeNames([star(100, 100)], { ...FRAME, points: [[130, 100]] });
		expect(label.left + label.width).toBeLessThanOrEqual(100);
	});

	it('stays off a line when another side is free', () => {
		const [label] = placeNames([star(100, 100)], { ...FRAME, segments: [[100, 100, 200, 100]] });
		expect(label.left).toBeLessThan(100);
	});

	it('stays off the boxes that are taken', () => {
		const taken = [{ left: 104, top: 90, width: 60, height: 20 }];
		const [label] = placeNames([star(100, 100)], { ...FRAME, taken });
		expect(label.left).toBeLessThan(100);
	});

	it('knows a line through a box from a line beside it', () => {
		const box = { left: 10, top: 10, width: 20, height: 10 };
		expect(segmentMeetsBox([0, 0, 40, 30], box)).toBe(true);
		expect(segmentMeetsBox([0, 15, 5, 15], box)).toBe(false);
		expect(segmentMeetsBox([0, 30, 40, 30], box)).toBe(false);
	});
});
