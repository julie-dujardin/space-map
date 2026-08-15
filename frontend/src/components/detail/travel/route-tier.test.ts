import { describe, expect, it } from 'vitest';
import { routeMark, routeTier, TIER_MARK } from './route-tier';

describe('routeTier', () => {
	it('pairs each held arc with the window that makes the same trade', () => {
		expect(routeTier('constant-thrust')).toBe(routeTier('fast'));
		expect(routeTier('constant-thrust-balanced')).toBe(routeTier('balanced'));
		expect(routeTier('constant-thrust-efficient')).toBe(routeTier('efficient'));
	});

	it('gives the three tiers three colours', () => {
		expect(new Set(Object.values(TIER_MARK)).size).toBe(3);
	});
});

describe('routeMark', () => {
	it('marks both hand-set options alike, and apart from the named ones', () => {
		const byHand = routeMark('custom');
		expect(routeMark('constant-thrust-custom')).toBe(byHand);
		expect(Object.values(TIER_MARK)).not.toContain(byHand);
	});

	it('leaves the families that offer one trajectory unmarked', () => {
		expect(routeMark('low-thrust')).toBeNull();
		expect(routeMark('gravity-assist')).toBeNull();
	});
});
