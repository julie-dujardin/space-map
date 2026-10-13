import { describe, expect, it } from 'vitest';
import { heightValues, packHeightBytes } from './heights';

/** A 2 × 2 tile: red and green hold the height, blue and alpha do not. */
const rgba = Uint8ClampedArray.of(1, 2, 0, 255, 3, 4, 0, 255, 5, 6, 0, 255, 7, 8, 0, 255);

describe('packHeightBytes', () => {
	it('keeps the two height bytes of each pixel, south row first', () => {
		expect(Array.from(packHeightBytes(rgba, 2))).toEqual([5, 6, 7, 8, 1, 2, 3, 4]);
	});
});

describe('heightValues', () => {
	it('joins the high and the low byte, north row first', () => {
		expect(Array.from(heightValues(rgba, 2))).toEqual([258, 772, 1286, 1800]);
	});
});
