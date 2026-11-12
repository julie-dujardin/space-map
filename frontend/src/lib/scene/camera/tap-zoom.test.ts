import { describe, expect, it } from 'vitest';
import { DOUBLE_TAP_GAP_MS, TAP_MAX_MS, TapZoomGesture, type TapZoomAction } from './tap-zoom';

/** Runs touches through a gesture and keeps what it asked for. */
function recorder() {
	const g = new TapZoomGesture();
	const actions: TapZoomAction[] = [];
	const keep = (a: TapZoomAction | null) => {
		if (a) actions.push(a);
	};
	return {
		g,
		actions,
		down: (id: number, x: number, y: number, t: number) => keep(g.down({ id, x, y, t })),
		move: (id: number, x: number, y: number, t: number) => keep(g.move({ id, x, y, t })),
		up: (id: number, x: number, y: number, t: number) => keep(g.up({ id, x, y, t })),
		cancel: (id: number) => keep(g.cancel(id))
	};
}

describe('TapZoomGesture', () => {
	it('zooms in where a double tap lands', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		expect(r.actions).toEqual([]);
		r.down(2, 104, 203, 200);
		expect(r.g.claims(2)).toBe(true);
		expect(r.g.holds(2)).toBe(true);
		r.up(2, 104, 203, 260);
		expect(r.actions).toEqual([{ type: 'in', x: 104, y: 203 }]);
		// The claim lasts past the lift, for the pick that reads it then.
		expect(r.g.claims(2)).toBe(true);
		expect(r.g.holds(2)).toBe(false);
	});

	it('does not claim a lone tap', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		expect(r.g.claims(1)).toBe(false);
		r.up(1, 100, 200, 80);
		expect(r.g.claims(1)).toBe(false);
	});

	it('takes taps too far apart in time as two taps', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.down(2, 100, 200, 80 + DOUBLE_TAP_GAP_MS + 1);
		r.up(2, 100, 200, 200 + DOUBLE_TAP_GAP_MS);
		expect(r.actions).toEqual([]);
		expect(r.g.claims(2)).toBe(false);
	});

	it('takes taps too far apart on screen as two taps', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.down(2, 200, 200, 150);
		r.up(2, 200, 200, 200);
		expect(r.actions).toEqual([]);
	});

	it('does not start a double tap from a press held too long', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, TAP_MAX_MS + 1);
		r.down(2, 100, 200, TAP_MAX_MS + 50);
		r.up(2, 100, 200, TAP_MAX_MS + 100);
		expect(r.actions).toEqual([]);
	});

	it('does not start a double tap from a drag', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.move(1, 140, 200, 40);
		r.up(1, 140, 200, 80);
		r.down(2, 140, 200, 150);
		r.up(2, 140, 200, 200);
		expect(r.actions).toEqual([]);
	});

	it('zooms out about the middle of a two-finger tap', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.down(2, 300, 200, 10);
		r.up(2, 300, 200, 90);
		r.up(1, 100, 200, 100);
		expect(r.actions).toEqual([{ type: 'out', x: 200, y: 200 }]);
	});

	it('leaves a two-finger gesture that moved to the pinch', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.down(2, 300, 200, 10);
		r.move(2, 340, 200, 50);
		r.up(2, 340, 200, 90);
		r.up(1, 100, 200, 100);
		expect(r.actions).toEqual([]);
	});

	it('zooms with the finger when a double tap stays down and slides', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.down(2, 100, 200, 150);
		r.move(2, 100, 205, 160);
		r.move(2, 100, 220, 170);
		r.move(2, 100, 250, 180);
		r.move(2, 100, 230, 190);
		r.up(2, 100, 230, 900);
		expect(r.actions).toEqual([
			{ type: 'drag-start', x: 100, y: 200 },
			{ type: 'drag', down: 30 },
			{ type: 'drag', down: -20 },
			{ type: 'drag-end' }
		]);
		expect(r.g.claims(2)).toBe(true);
	});

	it('hands a double tap to the pinch when a second finger comes down', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.down(2, 100, 200, 150);
		r.move(2, 100, 230, 170);
		r.down(3, 300, 200, 180);
		expect(r.g.holds(2)).toBe(false);
		r.move(2, 100, 260, 190);
		r.up(2, 100, 260, 200);
		r.up(3, 300, 200, 210);
		expect(r.actions).toEqual([{ type: 'drag-start', x: 100, y: 200 }, { type: 'drag-end' }]);
	});

	it('ends a drag the page took over', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.down(2, 100, 200, 150);
		r.move(2, 100, 230, 170);
		r.cancel(2);
		expect(r.actions.at(-1)).toEqual({ type: 'drag-end' });
	});

	it('forgets every touch on reset', () => {
		const r = recorder();
		r.down(1, 100, 200, 0);
		r.up(1, 100, 200, 80);
		r.g.reset();
		r.down(2, 100, 200, 150);
		r.up(2, 100, 200, 200);
		expect(r.actions).toEqual([]);
	});
});
