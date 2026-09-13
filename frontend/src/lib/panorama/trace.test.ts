import { describe, expect, it } from 'vitest';
import { nearestOnScreen } from './trace';

describe('nearestOnScreen', () => {
	const screen = new Float32Array([10, 10, 50, 50, 52, 50]);
	const facing = new Uint8Array([1, 1, 1]);

	it('picks the closest place within reach', () => {
		expect(nearestOnScreen(screen, facing, 3, 53, 51, 8)).toBe(2);
		expect(nearestOnScreen(screen, facing, 3, 49, 50, 8)).toBe(1);
	});

	it('finds nothing out of reach', () => {
		expect(nearestOnScreen(screen, facing, 3, 30, 30, 8)).toBe(-1);
	});

	it('skips places on the far side', () => {
		expect(nearestOnScreen(screen, new Uint8Array([1, 0, 0]), 3, 51, 50, 8)).toBe(-1);
	});
});
