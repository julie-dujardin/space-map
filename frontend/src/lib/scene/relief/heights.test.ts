import { describe, expect, it } from 'vitest';
import { heightValues, packHeightBytes, packHeightValues } from './heights';

/** A 2 × 2 tile: red and green hold the height, blue a part of its step. */
const rgba = Uint8ClampedArray.of(1, 2, 0, 255, 3, 4, 64, 255, 5, 6, 0, 255, 7, 8, 128, 255);

describe('packHeightBytes', () => {
	it('keeps the two height bytes of each pixel, south row first', () => {
		expect(Array.from(packHeightBytes(rgba, 2))).toEqual([5, 6, 7, 8, 1, 2, 3, 4]);
	});
});

describe('packHeightValues', () => {
	it('gives each height as one number with its part of a step, south row first', () => {
		expect(Array.from(packHeightValues(rgba, 2))).toEqual([1286, 1800.5, 258, 772.25]);
	});
});

describe('heightValues', () => {
	it('joins the high and the low byte, north row first', () => {
		expect(Array.from(heightValues(rgba, 2, false))).toEqual([258, 772, 1286, 1800]);
	});

	it('adds the part of a step that a tile of a patch states', () => {
		expect(Array.from(heightValues(rgba, 2, true))).toEqual([258, 772.25, 1286, 1800.5]);
	});
});
