import { MathUtils } from 'three';
import { describe, expect, it } from 'vitest';
import { TWIST_ENGAGE, TwoFingerGesture, type Point } from './two-finger';

/** Fingers side by side, 200 px apart. */
const A = { x: 400, y: 500 };
const B = { x: 600, y: 500 };

const shift = (p: Point, dx: number, dy: number): Point => ({ x: p.x + dx, y: p.y + dy });

/** Turn `p` clockwise on screen (y down) about `c`. */
function turned(p: Point, c: Point, angle: number): Point {
	const cos = Math.cos(angle);
	const sin = Math.sin(angle);
	const x = p.x - c.x;
	const y = p.y - c.y;
	return { x: c.x + x * cos - y * sin, y: c.y + x * sin + y * cos };
}

describe('TwoFingerGesture', () => {
	it('holds off until a finger has gone past the slop', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		expect(g.move(shift(A, 0, -4), shift(B, 0, -4)).mode).toBe('undecided');
	});

	it('reads both fingers sliding up side by side as a tilt', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		const step = g.move(shift(A, 1, -20), shift(B, -1, -18));
		expect(step.mode).toBe('tilt');
		expect(step.down).toBeCloseTo(-19, 9);
		expect(g.move(shift(A, 1, -30), shift(B, -1, -28)).down).toBeCloseTo(-10, 9);
		// And keeps it, however the fingers drift after.
		expect(g.move(shift(A, 40, -30), shift(B, 40, -28)).mode).toBe('tilt');
	});

	it('reads fingers one above the other sliding up as a pan', () => {
		const g = new TwoFingerGesture();
		g.begin({ x: 500, y: 400 }, { x: 500, y: 600 }, true);
		expect(g.move({ x: 500, y: 380 }, { x: 500, y: 580 }).mode).toBe('map');
	});

	it('reads a pinch as the map', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		expect(g.move(shift(A, -20, 0), shift(B, 20, 0)).mode).toBe('map');
	});

	it('reads a sideways slide as the map', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		expect(g.move(shift(A, 20, -5), shift(B, 20, -5)).mode).toBe('map');
	});

	it('reads one finger held and the other sliding up as the map', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		expect(g.move(A, shift(B, 0, -20)).mode).toBe('undecided');
		expect(g.move(A, shift(B, 0, -30)).mode).toBe('map');
	});

	it('waits for the second finger to report before it decides', () => {
		// Moves come one finger at a time: the first alone is not a pinch.
		const g = new TwoFingerGesture();
		g.begin(A, B, true);
		expect(g.move(shift(A, 0, -15), B).mode).toBe('undecided');
		const step = g.move(shift(A, 0, -15), shift(B, 0, -15));
		expect(step.mode).toBe('tilt');
		// All of it, the first finger's share included.
		expect(step.down).toBeCloseTo(-15, 9);
	});

	it('is the map from the start where the view cannot tilt', () => {
		const g = new TwoFingerGesture();
		g.begin(A, B, false);
		expect(g.move(shift(A, 0, -2), shift(B, 0, -2)).mode).toBe('map');
	});

	it('turns with a twist once past the threshold, from there on', () => {
		const g = new TwoFingerGesture();
		const c = { x: 500, y: 500 };
		g.begin(A, B, true);
		let twisted = 0;
		const total = MathUtils.degToRad(40);
		const steps = 40;
		for (let i = 1; i <= steps; i++) {
			const angle = (total * i) / steps;
			const step = g.move(turned(A, c, angle), turned(B, c, angle));
			// Held for the slop, as a finger goes under 2 px a step.
			expect(step.mode).toBe(i < 6 ? 'undecided' : 'map');
			twisted += step.twist;
		}
		// Clockwise, short of the whole twist by about the threshold.
		expect(twisted).toBeGreaterThan(total - TWIST_ENGAGE - total / steps - 1e-9);
		expect(twisted).toBeLessThanOrEqual(total - TWIST_ENGAGE);
	});

	it('does not turn for the wobble in a pinch', () => {
		const g = new TwoFingerGesture();
		const c = { x: 500, y: 500 };
		g.begin(A, B, true);
		const wobble = MathUtils.degToRad(5);
		const step = g.move(turned(shift(A, -30, 0), c, wobble), turned(shift(B, 30, 0), c, wobble));
		expect(step.twist).toBe(0);
		expect(g.move(shift(A, -40, 0), shift(B, 40, 0)).twist).toBe(0);
	});
});
