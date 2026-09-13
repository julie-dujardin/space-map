import { describe, expect, it } from 'vitest';
import { clampHeading } from './view';

describe('clampHeading', () => {
	it('keeps headings on the arc', () => {
		expect(clampHeading(45, [0, 90])).toBe(45);
		expect(clampHeading(350, [300, 60])).toBe(350);
		expect(clampHeading(30, [300, 60])).toBe(30);
	});

	it('snaps to the nearer end', () => {
		expect(clampHeading(100, [0, 90])).toBe(90);
		expect(clampHeading(-20, [0, 90])).toBe(0);
		expect(clampHeading(170, [300, 60])).toBe(60);
		expect(clampHeading(200, [300, 60])).toBe(300);
	});

	it('locks on equal ends', () => {
		expect(clampHeading(123, [90, 90])).toBe(90);
	});
});
