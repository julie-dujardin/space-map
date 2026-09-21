/**
 * Tests the width fit the compare page cuts its screens with: the scale a
 * row of named boxes can hold, and how many bodies a screen takes before the
 * rest turn the page. A cut too late squeezes names off their bodies; too
 * early, and a set that fits is spread over screens for nothing.
 */

import { describe, expect, it } from 'vitest';
import {
	ASIDE_END_PAD,
	BOX_GAP,
	SIDE_PAD,
	VPAD,
	craftHeightRatio,
	craftWidthRatio,
	endStrip,
	fitScale,
	limbStrip,
	screenCount,
	screenFit,
	screenScale
} from './lineup-fit';

const body = (radiusKm: number, label = 0) => ({ radiusKm, label });

describe('fitScale', () => {
	it('keeps the full scale while the boxes fit', () => {
		expect(fitScale([body(100), body(50)], 1000, 1)).toBe(1);
	});

	it('shrinks until the boxes and their gap fit the run', () => {
		// 200 + 100 + gap at k = 1; the run holds half of that.
		const k = fitScale([body(100), body(50)], 150 + BOX_GAP, 1);
		expect(k).toBeCloseTo(0.5, 6);
	});

	it('cuts a craft box to the width it stands at', () => {
		// A rocket a fifth as wide as tall takes a fifth of a sphere's box.
		const rocket = { radiusKm: 100, label: 0, aspect: 0.2 };
		expect(fitScale([rocket, body(100)], 40 + 200 + BOX_GAP, 1)).toBeCloseTo(1, 6);
		expect(fitScale([rocket, body(100)], 120 + BOX_GAP, 1)).toBeCloseTo(0.5, 6);
	});

	it('counts a name wider than its body as the box', () => {
		// The small body's box is its 60 px name, whatever the scale.
		const k = fitScale([body(100), body(10, 60)], 200 + 60 + BOX_GAP, 1);
		expect(k).toBeCloseTo(1, 6);
		expect(fitScale([body(100), body(10, 60)], 100 + 60 + BOX_GAP, 1)).toBeCloseTo(0.5, 6);
	});
});

describe('endStrip', () => {
	it('gives a speck its gutter and anything wider a limb strip', () => {
		expect(endStrip(ASIDE_END_PAD / 2, 1000)).toBe(ASIDE_END_PAD);
		expect(endStrip(ASIDE_END_PAD / 2 + 1, 1000)).toBe(limbStrip(1000));
	});
});

describe('screenCount', () => {
	const width = 1000;
	const run = (first: boolean, padEnd: number) =>
		width - 2 * SIDE_PAD - (first ? 0 : limbStrip(width)) - padEnd;

	it('takes every body when they all fit, with no strip after the last', () => {
		expect(screenCount([body(100), body(100), body(100)], undefined, 1, 1, width, true)).toBe(3);
	});

	it('stops where the next body would not fit with its name', () => {
		// Two 200 px bodies fit the run; a third with a 600 px name overshoots it.
		const bodies = [body(100), body(100), body(100, 600)];
		expect(screenCount(bodies, undefined, 1, 1, width, true)).toBe(2);
	});

	it('keeps the strip the body after the screen needs, as the row will size it', () => {
		// Three boxes fill the run exactly when nothing follows...
		const exact = (run(true, 0) - 2 * BOX_GAP) / 3;
		const bodies = [body(exact / 2), body(exact / 2), body(exact / 2)];
		expect(screenCount(bodies, undefined, 1, 1, width, true)).toBe(3);
		// ...but not once a limb-sized body after them takes its strip.
		expect(screenCount(bodies, body(100), 1, 1, width, true)).toBe(2);
		// A speck after them takes only its gutter, which the third also lacks.
		expect(screenCount(bodies, body(1), 1, 1, width, true)).toBe(2);
		// What it will be is judged on the row's scale, not the fit's.
		expect(screenCount(bodies, body(20), 1, 1, width, true)).toBe(2);
		expect(screenCount(bodies, body(20), 1, 2, width, true)).toBe(2);
	});

	it('leaves room for the page before on every screen but the first', () => {
		const exact = (run(true, 0) - BOX_GAP) / 2;
		const bodies = [body(exact / 2), body(exact / 2)];
		expect(screenCount(bodies, undefined, 1, 1, width, true)).toBe(2);
		expect(screenCount(bodies, undefined, 1, 1, width, false)).toBe(1);
	});

	it('always takes at least one body, however wide', () => {
		expect(screenCount([body(5000), body(5000)], undefined, 1, 1, width, false)).toBe(1);
	});
});

describe('screenFit', () => {
	const width = 1000;
	/** The height the largest body fills at 1 px per km, so half scale is 0.5. */
	const heightFor = (radiusKm: number) => 2 * radiusKm + 2 * VPAD;

	it('fills the height when the bodies fit at full scale', () => {
		const screen = screenFit(
			[body(100), body(100), body(100)],
			undefined,
			width,
			heightFor(100),
			true
		);
		expect(screen).toEqual({ count: 3, scale: 1 });
	});

	it('shrinks the largest, to half the height at most, to take in more', () => {
		// Nine bodies of 100 px at half scale, plus gaps, fit the run; a tenth
		// does not, and takes a limb strip off the ninth as well.
		const nine = Array.from({ length: 9 }, () => body(100));
		const all = screenFit(nine, undefined, width, heightFor(100), true);
		expect(all.count).toBe(9);
		expect(all.scale).toBeCloseTo((width - 2 * SIDE_PAD - 8 * BOX_GAP) / 1800, 6);
		const ten = screenFit([...nine, body(100)], undefined, width, heightFor(100), true);
		expect(ten.count).toBe(8);
		// The eight then stand on the widest scale that holds them and the strip.
		const run = width - 2 * SIDE_PAD - limbStrip(width);
		expect(ten.scale).toBeCloseTo((run - 7 * BOX_GAP) / 1600, 6);
	});

	it('keeps a strip for the page before on every screen but the first', () => {
		const nine = Array.from({ length: 9 }, () => body(100));
		expect(screenFit(nine, undefined, width, heightFor(100), false).count).toBe(8);
	});

	it('takes one body however wide, shrunk to the width', () => {
		const screen = screenFit([body(5000), body(5000)], undefined, width, heightFor(5000), true);
		expect(screen.count).toBe(1);
		expect(screen.scale).toBeCloseTo((width - 2 * SIDE_PAD - limbStrip(width)) / 10000, 6);
	});
});

describe('screenScale', () => {
	const width = 1000;
	const heightFor = (radiusKm: number) => 2 * radiusKm + 2 * VPAD;

	it('fills the height when the bodies fit, whatever scale they were cut on', () => {
		expect(screenScale([body(10), body(10)], undefined, width, heightFor(10), false)).toBe(1);
	});

	it('shrinks to the run, with the strips of a later page taken off', () => {
		const run = width - 2 * SIDE_PAD - limbStrip(width) - ASIDE_END_PAD;
		const k = screenScale([body(500), body(500)], body(1), width, heightFor(500), false);
		expect(k).toBeCloseTo((run - BOX_GAP) / 2000, 6);
	});
});

describe('craft pose ratios', () => {
	it('stands a tall mesh nearly full height and a strip wide', () => {
		const rocket = [0.1, 1, 0.1];
		expect(craftHeightRatio(rocket)).toBeGreaterThan(0.95);
		expect(craftWidthRatio(rocket)).toBeLessThan(0.2);
	});

	it('lays a long mesh across the row', () => {
		const bus = [1, 0.25, 0.3];
		expect(craftWidthRatio(bus)).toBeGreaterThan(0.9);
		expect(craftHeightRatio(bus)).toBeLessThan(0.5);
	});
});
