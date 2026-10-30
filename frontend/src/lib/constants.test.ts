import { describe, expect, it } from 'vitest';
import { dominantPlanetId, naifId, planetSystemId } from './constants';

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

describe('planetSystemId', () => {
	it('leads from a planet to its system barycenter, the inverse of dominantPlanetId', () => {
		expect(planetSystemId('naif-599')).toBe('naif-5');
		expect(dominantPlanetId(planetSystemId('naif-399')!)).toBe('naif-399');
	});

	it('is null for anything that heads no planetary system', () => {
		expect(planetSystemId('naif-501')).toBeNull();
		expect(planetSystemId('naif-10')).toBeNull();
		expect(planetSystemId('spkid-20000099')).toBeNull();
	});
});
