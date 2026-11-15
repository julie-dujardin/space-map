import { describe, expect, it } from 'vitest';
import { normalize, type Vec3 } from '$lib/math/travel/vec3';
import {
	centreScaleDeg,
	directionAt,
	figureAspect,
	FILL_MARGIN,
	FILL_MAX_SCALE,
	fillFrame,
	fitFrame,
	planeHalf,
	project
} from './frame';

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

describe('directionAt', () => {
	it('is the reverse of project', () => {
		const frame = fitFrame([icrs(80, 5), icrs(95, -10)], { width: 400, height: 300 });
		for (const [fx, fy] of [
			[0.5, 0.5],
			[0, 0],
			[0.9, 0.2]
		]) {
			const [x, y] = project(frame, directionAt(frame, fx, fy));
			expect(x).toBeCloseTo(fx * 400, 9);
			expect(y).toBeCloseTo(fy * 300, 9);
		}
	});
});

describe('the frame that fills an area', () => {
	// Taller than wide, as Orion: 16 by 26 degrees.
	const stars = [icrs(78, -8), icrs(89, 7), icrs(84, -1), icrs(81, 6), icrs(87, -10), icrs(84, 18)];
	const clear = [16, 72] as const;
	const areas = {
		wide: { width: 1210, height: 900 },
		tall: { width: 390, height: 844 },
		square: { width: 700, height: 700 }
	};

	function box(points: [number, number][]) {
		const xs = points.map(([x]) => x);
		const ys = points.map(([, y]) => y);
		return {
			left: Math.min(...xs),
			right: Math.max(...xs),
			top: Math.min(...ys),
			bottom: Math.max(...ys)
		};
	}

	for (const [shape, area] of Object.entries(areas)) {
		const frame = fillFrame(stars, { ...area, clear });
		const points = stars.map((star) => project(frame, star));
		const { left, right, top, bottom } = box(points);

		it(`has the size of a ${shape} area`, () => {
			expect([frame.width, frame.height]).toEqual([area.width, area.height]);
		});

		it(`holds the figure at the centre of a ${shape} area, out of the cleared edges`, () => {
			expect((left + right) / 2).toBeCloseTo(area.width / 2, 0);
			expect((top + bottom) / 2).toBeCloseTo(area.height / 2, 0);
			expect(left).toBeGreaterThan(clear[0]);
			expect(right).toBeLessThan(area.width - clear[0]);
			expect(top).toBeGreaterThan(clear[1]);
			expect(bottom).toBeLessThan(area.height - clear[1]);
		});

		it(`gives the figure its share of a ${shape} area, and sky to the rest`, () => {
			const across = (right - left) / (area.width - 2 * clear[0]);
			const down = (bottom - top) / (area.height - 2 * clear[1]);
			expect(Math.max(across, down)).toBeCloseTo(1 / (1 + FILL_MARGIN), 2);
		});

		it(`does not stretch the figure in a ${shape} area`, () => {
			// The same figure in its own frame: every distance grows by one factor.
			const own = fitFrame(stars, { width: 300, height: 400 });
			const reference = stars.map((star) => project(own, star));
			const factors: number[] = [];
			for (let i = 1; i < stars.length; i++) {
				factors.push(
					Math.hypot(points[i][0] - points[0][0], points[i][1] - points[0][1]) /
						Math.hypot(reference[i][0] - reference[0][0], reference[i][1] - reference[0][1])
				);
				// Each star keeps its bearing from the first.
				expect(Math.atan2(points[i][1] - points[0][1], points[i][0] - points[0][0])).toBeCloseTo(
					Math.atan2(reference[i][1] - reference[0][1], reference[i][0] - reference[0][0]),
					9
				);
			}
			for (const factor of factors) expect(factor).toBeCloseTo(factors[0], 9);
			const [halfWidth, halfHeight] = planeHalf(frame);
			expect(halfWidth / halfHeight).toBeCloseTo(area.width / area.height, 12);
		});
	}

	it('shows more sky in a larger area, at the same share', () => {
		const small = fillFrame(stars, { width: 600, height: 400 });
		const large = fillFrame(stars, { width: 1800, height: 400 });
		expect(centreScaleDeg(large)).toBeCloseTo(centreScaleDeg(small), 12);
		expect(planeHalf(large)[0]).toBeCloseTo(planeHalf(small)[0] * 3, 12);
	});

	it('does not magnify a small figure past the finest tiles', () => {
		const frame = fillFrame([icrs(56.6, 24.1)], { width: 1600, height: 1200 });
		expect(1 / centreScaleDeg(frame)).toBeCloseTo(FILL_MAX_SCALE, 9);
	});

	it('keeps the smallest field on a small area', () => {
		const frame = fillFrame([icrs(56.6, 24.1)], { width: 390, height: 844 });
		expect(centreScaleDeg(frame) * 390).toBeCloseTo(8, 1);
	});

	it('keeps half of a side for the figure when the cleared edges take more', () => {
		const frame = fillFrame(stars, { width: 800, height: 200, clear: [16, 72] });
		const { top, bottom } = box(stars.map((star) => project(frame, star)));
		expect(bottom - top).toBeCloseTo(100 / (1 + FILL_MARGIN), 0);
	});
});
