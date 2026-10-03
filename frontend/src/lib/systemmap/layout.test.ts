import { describe, expect, it } from 'vitest';
import { CY, hitTest, layout, tipFor } from './layout';
import type { MapBody, SystemMapModel } from './model';

const link = { onclick: () => {} };

const body = (id: string, aKm: number, more: Partial<MapBody> = {}): MapBody => ({
	id,
	name: id,
	aKm,
	tiltDeg: 0,
	radiusKm: 0,
	color: '#fff',
	link,
	...more
});

const model = (bodies: MapBody[]): SystemMapModel => ({
	primary: { id: 'p', name: 'Primary', radiusKm: 10, color: '#fff' },
	bodies,
	bands: [{ key: 'band', label: 'Band', innerKm: 20, outerKm: 60, tone: 'muted' }],
	unitKm: 1,
	domain: [1, 1000],
	ticks: [1, 10, 100],
	axisLabel: 'km',
	pxPerKm: 1,
	pxPerDeg: 1,
	text: {
		primary: 'primary',
		retrograde: 'retrograde',
		moons: (count) => `${count} moons`,
		distance: (km) => `${km} km`,
		axisAu: 'AU · log'
	}
});

describe('hitTest', () => {
	it('gives each of two crowded dots the ground nearest it', () => {
		const l = layout(model([body('a', 100), body('b', 103)]));
		const [a, b] = l.bodies;
		expect(b.cx - a.cx).toBeLessThan(4);
		expect(hitTest(l, a.cx - 5, CY)).toEqual({ kind: 'body', id: 'a' });
		expect(hitTest(l, a.cx, CY)).toEqual({ kind: 'body', id: 'a' });
		expect(hitTest(l, b.cx, CY)).toEqual({ kind: 'body', id: 'b' });
		expect(hitTest(l, b.cx + 5, CY)).toEqual({ kind: 'body', id: 'b' });
	});

	it('finds a small dot drawn over a large one at its centre', () => {
		const l = layout(model([body('large', 100, { radiusKm: 12 }), body('small', 101)]));
		const small = l.bodies.find((b) => b.id === 'small')!;
		const large = l.bodies.find((b) => b.id === 'large')!;
		expect(hitTest(l, small.cx, small.cy)).toEqual({ kind: 'body', id: 'small' });
		expect(hitTest(l, large.cx - 8, large.cy)).toEqual({ kind: 'body', id: 'large' });
	});

	it('prefers something to pick over the landmark beside it', () => {
		const l = layout(
			model([body('mark', 100, { link: undefined, reference: true }), body('b', 110)])
		);
		const mark = l.bodies[0];
		expect(hitTest(l, mark.cx + 6, CY)).toEqual({ kind: 'body', id: 'b' });
		expect(hitTest(l, mark.cx, CY)).toEqual({ kind: 'body', id: 'mark' });
	});

	it('reads a grouped stack as its body, and an ungrouped one as the stack', () => {
		const satellites = [{ id: 'm', name: 'm', radiusKm: 0, color: '#fff' }];
		const grouped = layout(model([body('a', 100, { satellites, grouped: true })]));
		const zone = grouped.moonZones[0];
		expect(hitTest(grouped, zone.x + 1, zone.y + 1)).toEqual({ kind: 'body', id: 'a' });
		const apart = layout(model([body('a', 100, { satellites, satellitesLink: link })]));
		expect(hitTest(apart, zone.x + 1, zone.y + 1)).toEqual({ kind: 'stack', id: 'a' });
	});

	it('gives each moon of a stack with no link of its own a slice of it', () => {
		const satellites = ['m', 'n'].map((id) => ({ id, name: id, radiusKm: 0, color: '#fff', link }));
		const l = layout(model([body('a', 100, { satellites })]));
		const [zone] = l.moonZones;
		expect(zone.perMoon).toBe(true);
		for (const moon of zone.moons)
			expect(hitTest(l, moon.cx + 8, moon.cy)).toEqual({ kind: 'moon', parent: 'a', id: moon.id });
		// The body's own dot is still the body.
		expect(hitTest(l, zone.parent.cx, zone.parent.cy)).toEqual({ kind: 'body', id: 'a' });
	});

	it('falls through to the band, then to nothing', () => {
		const l = layout(model([body('a', 500)]));
		expect(hitTest(l, l.xOf(40), CY)).toEqual({ kind: 'band', key: 'band' });
		expect(hitTest(l, l.xOf(200), CY)).toBeNull();
	});
});

describe('tipFor', () => {
	it('says how many moons a grouped body stands for', () => {
		const satellites = [{ id: 'm', name: 'm', radiusKm: 0, color: '#fff' }];
		const m = model([body('a', 100, { satellites, satelliteCount: 7, grouped: true })]);
		expect(tipFor(m, layout(m), { kind: 'body', id: 'a' })).toMatchObject({
			title: 'a',
			sub: '100 km · 7 moons'
		});
	});

	it('flags a retrograde orbit', () => {
		const m = model([body('a', 100, { tiltDeg: 150 })]);
		expect(tipFor(m, layout(m), { kind: 'body', id: 'a' })?.sub).toBe('100 km · retrograde');
	});
});
