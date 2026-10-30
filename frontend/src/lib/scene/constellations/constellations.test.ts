import { describe, expect, it } from 'vitest';
import type { SkyCultureFile } from '$lib/fetch/extrasolar/skycultures';
import { constellationShape, cullLabels, type LabelBox } from './constellations';

const FILE: SkyCultureFile = {
	token: '0',
	key: 'modern_iau',
	members: [
		{ id: 1, position: [10, 0, 0] },
		{ id: 2, position: [0, 20, 0] },
		{ id: 3 },
		{ id: 4, position: [0, 0, 30] }
	],
	figures: [
		{
			id: 'CON modern_iau Ori',
			kind: 'constellation',
			names: [{ native: 'Orion', english: 'Hunter' }],
			lines: [[0, 1, 2, 3]],
			iau: 'Ori',
			labels: { fr: 'Orion FR' }
		},
		{ id: 'AST modern_iau Big', kind: 'asterism', names: [], lines: [[0, 3]] },
		{ id: 'CON modern_iau Xxx', kind: 'constellation', names: [], lines: [[2, 3]] }
	]
};

describe('constellationShape', () => {
	it('anchors a label on the largest part of a figure in two parts', () => {
		const star = (x: number) => ({ position: [x, 1, 0] as [number, number, number] });
		const [{ anchor }] = constellationShape(
			{
				...FILE,
				members: [star(0), star(0.1), star(0.2), star(-50), star(-51)],
				figures: [
					{
						id: 'CON t Ser',
						kind: 'constellation',
						names: [],
						lines: [
							[0, 1, 2],
							[3, 4]
						]
					}
				]
			},
			'en'
		).labels;
		expect(anchor[0]).toBeGreaterThan(0);
	});

	it('leaves out asterisms and any line to a star with no position', () => {
		expect([...constellationShape(FILE, 'en').positions]).toEqual([10, 0, 0, 0, 20, 0]);
	});

	it('gives no label to a figure with no line', () => {
		expect(constellationShape(FILE, 'en').labels).toHaveLength(1);
	});

	it('names a figure in the language of the page, else by its Latin name', () => {
		expect(constellationShape(FILE, 'fr').labels[0].name).toBe('Orion FR');
		expect(constellationShape(FILE, 'de').labels[0].name).toBe('Orion');
	});

	it('anchors a label between its stars as the Sun sees them, at their mean distance', () => {
		const [{ anchor }] = constellationShape(FILE, 'en').labels;
		expect(anchor[0]).toBeCloseTo(anchor[1]);
		expect(Math.hypot(...anchor)).toBeCloseTo(15);
	});
});

function box(left: number, top: number, inView = true): LabelBox {
	return { left, right: left + 50, top, bottom: top + 14, inView, shown: false };
}

describe('cullLabels', () => {
	it('keeps the first of two boxes that meet', () => {
		const boxes = [box(0, 0), box(40, 5)];
		cullLabels(boxes, []);
		expect(boxes.map((b) => b.shown)).toEqual([true, false]);
	});

	it('keeps boxes that only touch', () => {
		const boxes = [box(0, 0), box(50, 0), box(0, 14)];
		cullLabels(boxes, []);
		expect(boxes.map((b) => b.shown)).toEqual([true, true, true]);
	});

	it('does not let a hidden box hide another', () => {
		const boxes = [box(0, 0), box(40, 0), box(80, 0)];
		cullLabels(boxes, []);
		expect(boxes.map((b) => b.shown)).toEqual([true, false, true]);
	});

	it('does not let a box out of view hide another', () => {
		const boxes = [box(0, 0, false), box(0, 0)];
		cullLabels(boxes, []);
		expect(boxes.map((b) => b.shown)).toEqual([false, true]);
	});

	it('hides a box that meets a body label or halo', () => {
		const boxes = [box(0, 0), box(200, 0)];
		const rects = [{ left: 30, right: 90, y: 7, h: 22 }];
		cullLabels(boxes, [{ rects, count: 1 }]);
		expect(boxes.map((b) => b.shown)).toEqual([false, true]);
	});

	it('reads only the counted rects of a pool', () => {
		const boxes = [box(0, 0)];
		cullLabels(boxes, [{ rects: [{ left: 0, right: 50, y: 7, h: 22 }], count: 0 }]);
		expect(boxes[0].shown).toBe(true);
	});
});
