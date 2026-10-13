import { describe, it, expect } from 'vitest';

import { formatBytes } from './bytes';

describe('formatBytes', () => {
	it.each([
		{ bytes: 0, expected: '0 byte' },
		{ bytes: 512, expected: '512 byte' },
		{ bytes: 119_434, expected: '119 kB' },
		{ bytes: 11_500_000, expected: '11.5 MB' },
		{ bytes: 1_030_000_000, expected: '1.03 GB' },
		{ bytes: 347_160_000_000, expected: '347 GB' },
		{ bytes: 1_400_000_000_000, expected: '1.4 TB' }
	])('$bytes → $expected', ({ bytes, expected }) => {
		expect(formatBytes(bytes)).toBe(expected);
	});

	it('takes the next unit when the rounded figure reaches a thousand', () => {
		expect(formatBytes(999_600_000)).toBe('1 GB');
	});
});
