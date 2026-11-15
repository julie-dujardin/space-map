import { describe, expect, it } from 'vitest';
import { normalize, type Vec3 } from '$lib/math/travel/vec3';
import { centreScaleDeg, figureAspect, fitFrame, planeHalf, project } from './frame';

function icrs(raDeg: number, decDeg: number): Vec3 {
	const ra = (raDeg * Math.PI) / 180;
	const dec = (decDeg * Math.PI) / 180;
	return [Math.cos(dec) * Math.cos(ra), Math.cos(dec) * Math.sin(ra), Math.sin(dec)];
}

function inside(frame: { width: number; height: number }, [x, y]: [number, number]): boolean {
	return x > 0 && y > 0 && x < frame.width && y < frame.height;
}

const SIZE = { width: 400, height: 300 };

describe('the frame of a chart', () => {
	it('has north up and east to the left', () => {
		const frame = fitFrame([icrs(80, -5), icrs(90, 10)], SIZE);
		const [x, y] = project(frame, icrs(85, 2));
		expect(project(frame, icrs(85, 4))[1]).toBeLessThan(y);
		expect(project(frame, icrs(87, 2))[0]).toBeLessThan(x);
	});

	it('holds every star with room around it, at the centre', () => {
		const stars = [icrs(80, -10), icrs(92, 8), icrs(84, 0)];
		const frame = fitFrame(stars, SIZE);
		const points = stars.map((star) => project(frame, star));
		for (const [x, y] of points) {
			expect(x).toBeGreaterThan(30);
			expect(x).toBeLessThan(370);
			expect(y).toBeGreaterThan(30);
			expect(y).toBeLessThan(270);
		}
		const ys = points.map(([, y]) => y);
		expect((Math.min(...ys) + Math.max(...ys)) / 2).toBeCloseTo(150, 0);
	});

	it('holds a figure around a pole', () => {
		const stars = [0, 90, 180, 270].map((ra) => icrs(ra, 80));
		const frame = fitFrame([...stars, icrs(0, 90)], SIZE);
		for (const star of stars) expect(inside(frame, project(frame, star))).toBe(true);
		expect(frame.forward[2]).toBeGreaterThan(0.999);
		expect(Number.isFinite(frame.up[0])).toBe(true);
	});

	it('holds a figure across RA 0h', () => {
		const stars = [icrs(350, 0), icrs(10, 5)];
		const frame = fitFrame(stars, SIZE);
		expect(normalize(frame.forward)[0]).toBeGreaterThan(0.98);
		for (const star of stars) expect(inside(frame, project(frame, star))).toBe(true);
	});

	it('holds a figure that spans more than a quarter of the sky', () => {
		const stars = [130, 150, 180, 210, 225].map((ra) => icrs(ra, -15));
		const frame = fitFrame(stars, { width: 600, height: 300 });
		for (const star of stars) expect(inside(frame, project(frame, star))).toBe(true);
	});

	it('shows more sky in a wider frame, at the same scale', () => {
		const stars = [icrs(80, -10), icrs(84, 12)];
		const tall = fitFrame(stars, { width: 300, height: 400 });
		const wide = fitFrame(stars, { width: 800, height: 400 });
		expect(centreScaleDeg(wide)).toBeCloseTo(centreScaleDeg(tall), 9);
		expect(planeHalf(wide)[0]).toBeGreaterThan(planeHalf(tall)[0] * 2);
	});

	it('gives one star the smallest field', () => {
		const frame = fitFrame([icrs(100, 20)], { ...SIZE, minFieldDeg: 8 });
		expect(centreScaleDeg(frame) * frame.height).toBeCloseTo(8, 1);
		const [x, y] = project(frame, icrs(100, 20));
		expect(x).toBeCloseTo(200, 9);
		expect(y).toBeCloseTo(150, 9);
	});

	it('takes the aspect of the figure, within limits', () => {
		expect(figureAspect([icrs(80, -10), icrs(84, 10)], 0.8, 1.8)).toBe(0.8);
		expect(figureAspect([icrs(60, 0), icrs(120, 5)], 0.8, 1.8)).toBe(1.8);
		const square = figureAspect([icrs(80, 0), icrs(90, 10), icrs(80, 10), icrs(90, 0)], 0.8, 1.8);
		expect(square).toBeCloseTo(1, 1);
	});
});
