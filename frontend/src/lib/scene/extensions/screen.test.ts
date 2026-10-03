import { describe, expect, it } from 'vitest';
import { PerspectiveCamera } from 'three';
import { SeenLine, parseDash, reachesBehind, screenLengths } from './screen';

describe('parseDash', () => {
	it('reads a dash and a gap', () => {
		expect(parseDash('4 3')).toEqual([4, 3]);
		expect(parseDash('4,3')).toEqual([4, 3]);
	});

	it('takes one number as both', () => {
		expect(parseDash('5')).toEqual([5, 5]);
	});

	it('leaves a line solid without a pattern it can draw', () => {
		expect(parseDash(undefined)).toBeNull();
		expect(parseDash('')).toBeNull();
		expect(parseDash('0 4')).toBeNull();
		expect(parseDash('dotted')).toBeNull();
	});
});

describe('screenLengths', () => {
	// A 90° view 800 px tall: a point as far to the side as it is ahead sits
	// 400 px from the middle.
	const camera = new PerspectiveCamera(90, 1, 0.1, 1000);

	it('measures the line in pixels, not along its depth', () => {
		const points = new Float32Array([0, 0, -10, 10, 0, -10, 1000, 0, -1000]);
		const out = new Float32Array(3);
		screenLengths(points, 3, camera, 800, out);
		expect(out[0]).toBe(0);
		expect(out[1]).toBeCloseTo(400, 3);
		// Out along the same line of sight: no further on screen.
		expect(out[2]).toBeCloseTo(400, 3);
	});

	it('follows the camera as it turns and moves', () => {
		const turned = new PerspectiveCamera(90, 1, 0.1, 1000);
		turned.position.set(5, 0, 0);
		turned.lookAt(5, 0, 10);
		const points = new Float32Array([5, 0, 10, 5, 10, 10]);
		const out = new Float32Array(2);
		screenLengths(points, 2, turned, 800, out);
		expect(out[1]).toBeCloseTo(400, 3);
	});

	it('adds nothing for a point behind the camera', () => {
		const points = new Float32Array([0, 0, -10, 10, 0, 10, 10, 0, -10]);
		const out = new Float32Array(3);
		screenLengths(points, 3, camera, 800, out);
		expect(out[1]).toBe(0);
		expect(out[2]).toBeCloseTo(400, 3);
	});
});

describe('SeenLine', () => {
	const camera = new PerspectiveCamera(90, 1, 0.1, 1000);
	const solid = (n: number) => new Float32Array(n).fill(1);
	const at = (line: SeenLine, i: number) => [...line.points.slice(i * 3, i * 3 + 3)];

	it('leaves a line in view as it is, measured in pixels', () => {
		const line = new SeenLine();
		line.see(new Float32Array([0, 0, -10, 10, 0, -10]), solid(2), 2, camera, 800);
		expect(line.count).toBe(2);
		expect(at(line, 1)).toEqual([10, 0, -10]);
		expect([...line.lengths.slice(0, 2)]).toEqual([0, 400]);
	});

	it('cuts a line that runs behind the camera where it leaves the view', () => {
		const points = new Float32Array([0, 0, -10, 0, 0, 10]);
		expect(reachesBehind(points, 2, camera)).toBe(true);
		const line = new SeenLine();
		line.see(points, solid(2), 2, camera, 800);
		expect(line.count).toBe(2);
		expect(at(line, 1)[2]).toBeCloseTo(-0.2, 5);
	});

	it('cuts a line at the reach of the screen, so its length stays countable', () => {
		const line = new SeenLine();
		line.see(new Float32Array([0, 0, -10, 1e6, 0, -10]), solid(2), 2, camera, 800);
		// Three half-screens out, on a screen 800 px across.
		expect(line.lengths[1]).toBeCloseTo(1200, 2);
	});

	it('draws nothing of a line wholly out of view', () => {
		const line = new SeenLine();
		line.see(new Float32Array([0, 0, 10, 5, 0, 20]), solid(2), 2, camera, 800);
		expect(line.count).toBe(0);
	});

	it('joins the pieces either side of a gap with a stretch at no opacity', () => {
		// Ahead, behind, ahead again.
		const points = new Float32Array([-5, 0, -10, 0, 0, 10, 5, 0, -10]);
		const line = new SeenLine();
		line.see(points, solid(3), 3, camera, 800);
		expect([...line.alphas.slice(0, line.count)]).toEqual([1, 1, 0, 0, 1, 1]);
		expect(at(line, 2)).toEqual(at(line, 1));
		expect(at(line, 3)).toEqual(at(line, 4));
		expect(at(line, 5)).toEqual([5, 0, -10]);
	});

	it('keeps a line with a bend in view as one strip', () => {
		const points = new Float32Array([-5, 0, -10, 0, 0, -10, 5, 0, -10]);
		const line = new SeenLine();
		line.see(points, solid(3), 3, camera, 800);
		expect(line.count).toBe(3);
		expect([...line.lengths.slice(0, 3)]).toEqual([0, 200, 400]);
	});
});
