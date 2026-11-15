import { describe, expect, it } from 'vitest';
import { fitFrame } from './frame';
import {
	HALF_PEAK_SHARE,
	halved,
	MAX_PAINT_PIXELS,
	paintedFlux,
	paintRatio,
	rayUniforms,
	type Pixels
} from './sky';

function sky(width: number, height: number, level: number): Pixels {
	const data = new Uint8ClampedArray(width * height * 4).fill(level);
	return { data, width, height };
}

function paint(pixels: Pixels, x: number, y: number, level: number): void {
	pixels.data.fill(level, (y * pixels.width + x) * 4, (y * pixels.width + x) * 4 + 3);
}

describe('the painted sky', () => {
	it('gives a star its light over the sky around it', () => {
		const pixels = sky(40, 40, 30);
		expect(paintedFlux(pixels, 20, 20, 2)).toBe(0);
		paint(pixels, 20, 20, 230);
		expect(paintedFlux(pixels, 20, 20, 2)).toBeCloseTo(200, 0);
	});

	it('ranks a bright star over a faint one', () => {
		const pixels = sky(60, 40, 20);
		paint(pixels, 15, 20, 250);
		paint(pixels, 45, 20, 90);
		expect(paintedFlux(pixels, 15, 20, 2)).toBeGreaterThan(paintedFlux(pixels, 45, 20, 2));
	});

	it('gives nothing off the picture', () => {
		expect(paintedFlux(sky(40, 40, 200), 1, 1, 2)).toBe(0);
	});

	it('gives a source the axes and the half size of the frame', () => {
		const frame = fitFrame([[1, 0, 0]], { width: 400, height: 200 });
		const uniforms = rayUniforms(frame);
		expect(uniforms.uForward).toEqual([1, 0, 0]);
		expect(uniforms.uHalf[0]).toBeCloseTo(uniforms.uHalf[1] * 2, 12);
	});
});

describe('halved', () => {
	it('keeps a share of a star that is one pixel of four', () => {
		const pixels = sky(4, 4, 20);
		paint(pixels, 2, 0, 220);
		const half = halved(pixels);
		expect([half.width, half.height]).toEqual([2, 2]);
		expect(half.data[0]).toBe(20);
		expect(half.data[4]).toBe(Math.round(70 + 150 * HALF_PEAK_SHARE));
		expect([half.data[3], half.data[7]]).toEqual([255, 255]);
	});
});

describe('paintRatio', () => {
	it('is the ratio wanted for a frame under the limit', () => {
		expect(paintRatio(357, 300)).toBe(2);
		expect(paintRatio(1210, 900)).toBe(2);
		expect(paintRatio(1210, 900, 1)).toBe(1);
	});

	it('holds a large frame at the most pixels of a paint', () => {
		const ratio = paintRatio(3840, 2160);
		expect(ratio).toBeLessThan(1);
		expect(3840 * ratio * 2160 * ratio).toBeCloseTo(MAX_PAINT_PIXELS, 0);
		expect(paintRatio(3840, 2160, 1)).toBe(ratio);
	});
});

describe('paintRatio of a chart that fills a screen', () => {
	it('paints at the ratio of the screen, up to the most', () => {
		for (const [device, painted] of [
			[1, 1],
			[1.25, 1.25],
			[1.5, 1.5],
			[2, 2],
			[3, 2]
		]) {
			expect(paintRatio(1210, 900, device)).toBe(painted);
		}
	});
});
