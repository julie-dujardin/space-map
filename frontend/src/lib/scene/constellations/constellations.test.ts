import { describe, expect, it } from 'vitest';
import type { SkyCultureFigure, SkyCultureFile } from '$lib/fetch/extrasolar/skycultures';
import { labelOf } from '$lib/fetch/extrasolar/skycultures';
import { constellationShape, cullLabels, pageAimDue, type LabelBox } from './constellations';

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
			labels: { fr: 'Orion FR' },
			page: 'sky-orion'
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
						names: [{ english: 'Serpent' }],
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

	it('draws asterisms and leaves out any line to a star with no position', () => {
		expect([...constellationShape(FILE, 'en').positions]).toEqual([
			10, 0, 0, 0, 20, 0, 10, 0, 0, 0, 0, 30
		]);
	});

	it('draws a line to a stand-in as to a star', () => {
		const shape = constellationShape(
			{
				...FILE,
				members: [
					{ ra_hours: 1, dec: 2, position: [1, 0, 0], stand_in: 'culture-stars' },
					{ ref: 'DSO:M44', position: [0, 1, 0], stand_in: 'hunt-reffert-2024' }
				] as SkyCultureFile['members'],
				figures: [
					{ id: 'CON t A', kind: 'constellation', names: [{ english: 'A' }], lines: [[0, 1]] }
				]
			},
			'en'
		);
		expect([...shape.positions]).toEqual([1, 0, 0, 0, 1, 0]);
		expect(shape.labels).toHaveLength(1);
	});

	it('leaves out a ray helper', () => {
		const figures = FILE.figures.map((figure) => ({ ...figure, ray_helper: true }));
		expect(constellationShape({ ...FILE, figures }, 'en').positions).toHaveLength(0);
	});

	it('labels only a figure with a name and a place', () => {
		expect(constellationShape(FILE, 'en').labels).toHaveLength(1);
	});

	it('gives each label the first vertex of its figure', () => {
		const first = FILE.figures[0];
		const second = { ...first, id: 'CON t Two', names: [{ english: 'Two' }] };
		const { labels } = constellationShape({ ...FILE, figures: [first, second] }, 'en');
		const lines = labels[0].weight;
		expect(labels.map((label) => label.firstVertex).sort((a, b) => a - b)).toEqual([0, 2 * lines]);
	});

	it('names a star group at its stars, with no line', () => {
		const shape = constellationShape(
			{
				...FILE,
				figures: [
					{
						id: 'CON t Pleiades',
						kind: 'constellation',
						names: [{ english: 'Seven' }],
						lines: [],
						group: [0, 1, 2]
					}
				]
			},
			'en'
		);
		expect(shape.positions).toHaveLength(0);
		expect(shape.labels.map(({ name, weight }) => [name, weight])).toEqual([['Seven', 0]]);
	});

	it('breaks nothing on a figure that cannot draw', () => {
		const shape = constellationShape(
			{
				...FILE,
				figures: [
					{
						id: 'CON t Far',
						kind: 'constellation',
						names: [{ english: 'Far' }],
						lines: [[2, 2]],
						group: [2]
					}
				]
			},
			'en'
		);
		expect(shape).toMatchObject({ labels: [] });
	});

	it('names a figure in the language of the page, else by its English name', () => {
		expect(constellationShape(FILE, 'fr').labels[0].name).toBe('Orion FR');
		expect(constellationShape(FILE, 'de').labels[0].name).toBe('Hunter');
	});

	it('links a label to the page of its figure', () => {
		expect(constellationShape(FILE, 'fr').labels[0].slug).toBe('sky-orion');
	});

	it('anchors a label between its stars as the Sun sees them, at their median distance', () => {
		const [{ anchor }] = constellationShape(FILE, 'en').labels;
		expect(anchor[0]).toBeCloseTo(anchor[1]);
		expect(Math.hypot(...anchor)).toBeCloseTo(15);
	});

	it('keeps a label among its stars when one member lies far away', () => {
		const at = (distance: number, x: number): SkyCultureFile['members'][number] => ({
			position: [distance * x, distance, 0]
		});
		const members = [at(10, 0), at(12, 0.01), at(14, -0.01), at(772_000, 0)];
		const figures = [{ ...FILE.figures[0], lines: [[0, 1, 2, 3]] }];
		const [{ anchor }] = constellationShape({ ...FILE, members, figures }, 'en').labels;
		expect(Math.hypot(...anchor)).toBeCloseTo(13, 0);
		expect(anchor[0] / anchor[1]).toBeCloseTo(0, 2);
	});
});

function box(left: number, top: number, inView = true): LabelBox {
	return { left, right: left + 50, top, bottom: top + 14, inView, occluded: false, shown: false };
}

describe('pageAimDue', () => {
	const page = { culture: 'modern_iau', slug: 'sky-orion', opening: false, hidden: false };

	it('turns once the figures are in', () => {
		expect(pageAimDue(page, null, 'modern_iau', false)).toBe(true);
		expect(pageAimDue(page, null, 'chinese', false)).toBe(false);
	});

	it('waits for a flight to land', () => {
		expect(pageAimDue(page, null, 'modern_iau', true)).toBe(false);
	});

	it('turns once for a page', () => {
		expect(pageAimDue(page, 'sky-orion', 'modern_iau', false)).toBe(false);
	});

	it('does not turn to a sky the reader switched off, and does when it is back', () => {
		expect(pageAimDue({ ...page, hidden: true }, null, 'modern_iau', false)).toBe(false);
		expect(pageAimDue({ ...page, hidden: false }, null, 'modern_iau', false)).toBe(true);
	});

	it('has nothing to turn to on a culture page', () => {
		expect(pageAimDue({ ...page, slug: null }, null, 'modern_iau', false)).toBe(false);
	});
});

describe('cullLabels', () => {
	it('drops a label behind a body, and it blocks nothing', () => {
		const boxes = [{ ...box(0, 0), occluded: true }, box(10, 0)];
		cullLabels(boxes, []);
		expect(boxes.map((b) => b.shown)).toEqual([false, true]);
	});

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

describe('labelOf', () => {
	const figure = (names: SkyCultureFigure['names'], extra = {}): SkyCultureFigure => ({
		id: 'CON t 1',
		kind: 'constellation',
		names,
		lines: [],
		...extra
	});
	const net = [{ native: '毕宿', english: 'Net', pronounce: 'Bì Xiù' }];

	it('reads the name in the language of the page', () => {
		expect(labelOf(figure(net, { labels: { fr: 'Filet' } }), 'fr')).toBe('Filet');
	});

	it('gives a reader of the native script the native name', () => {
		expect(labelOf(figure(net), 'zh')).toBe('毕宿');
	});

	it('prefers the native name to a translation of its English gloss', () => {
		expect(labelOf(figure(net, { labels: { zh: '网' } }), 'zh')).toBe('毕宿');
	});

	it('gives other readers the English name', () => {
		expect(labelOf(figure(net), 'en')).toBe('Net');
		expect(labelOf(figure(net), 'fr')).toBe('Net');
		expect(labelOf(figure(net), 'ar')).toBe('Net');
	});

	it('falls back on what the figure has', () => {
		expect(labelOf(figure([{ pronounce: 'Bì' }]), 'en')).toBe('Bì');
		expect(labelOf(figure([{ native: 'བུ' }]), 'en')).toBe('བུ');
		expect(labelOf(figure([]), 'en')).toBeNull();
	});
});

describe('constellationShape pages', () => {
	it('links only a figure with a page, whatever its iau field says', () => {
		const member = { position: [1, 0, 0] as [number, number, number] };
		const other = { position: [0, 1, 0] as [number, number, number] };
		const line = {
			kind: 'constellation' as const,
			lines: [[0, 1]]
		};
		const { labels } = constellationShape(
			{
				...FILE,
				members: [member, other],
				figures: [
					{ ...line, id: 'a', names: [{ english: 'Net' }], page: 'sky-net' },
					{ ...line, id: 'b', names: [{ native: 'Orion' }], iau: 'Ori', labels: { fr: 'Orion' } }
				]
			},
			'en'
		);
		expect(labels.map((label) => label.slug).sort()).toEqual([null, 'sky-net'].sort());
	});
});
