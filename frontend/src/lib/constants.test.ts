import { describe, expect, it } from 'vitest';
import { naifId } from './constants';

describe('naifId', () => {
	it('reads the numeric part of a naif id', () => {
		expect(naifId('naif-499')).toBe(499);
		expect(naifId('naif-0')).toBe(0);
	});

	it('returns null for other id prefixes', () => {
		expect(naifId('spkid-2000004')).toBeNull();
		expect(naifId('probe-7')).toBeNull();
	});
});
