import { describe, expect, it } from 'vitest';
import { fitFrame } from './frame';
import { paintedFlux, rayUniforms, type Pixels } from './sky';

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
