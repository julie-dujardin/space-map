import { describe, expect, it } from 'vitest';
import { bestTier, lowerTier, tierForWidth } from './sources';

describe('choosing a resolution tier', () => {
	it('takes the smallest tier that covers the width on screen', () => {
		expect(tierForWidth(900)).toBe('low');
		expect(tierForWidth(2048)).toBe('low');
		expect(tierForWidth(4096)).toBe('medium');
		expect(tierForWidth(9000)).toBe('high');
	});

	it('takes the largest tier there is for a width past all of them', () => {
		expect(tierForWidth(40000)).toBe('high');
	});

	it('takes the coarser of two tiers', () => {
		expect(lowerTier('high', 'medium')).toBe('medium');
		expect(lowerTier('low', 'high')).toBe('low');
	});

	it('never asks for a tier the bundle does not have', () => {
		expect(bestTier(['low', 'medium'], 'high')).toBe('medium');
		expect(bestTier(['low'], 'medium')).toBe('low');
	});
});
