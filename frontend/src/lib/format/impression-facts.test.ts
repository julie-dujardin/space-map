import { describe, expect, it } from 'vitest';
import { impressionFacts } from './impression-facts';

/** The warning lists only what the record measures. */

const host = { teff: 2566, radius: 0.1192 };
const record = (
	values: Record<string, number | string[]>,
	estimated: string[] = [],
	limits: string[] = []
) => ({
	values,
	estimated,
	limits
});

describe('impressionFacts', () => {
	it('lists every measured fact of a transiting planet with an atmosphere', () => {
		const planet = record({ radius: 0.08, mass: 0.002, molecules: ['H2O'], semi_major_axis: 0.03 });
		expect(impressionFacts(planet, host)).toEqual([
			'size',
			'mass',
			'molecules',
			'distance',
			'brightness'
		]);
	});

	it('leaves out an estimated radius and a mass that is an estimate or a limit', () => {
		const estimated = record({ radius: 0.09, mass: 0.003, semi_major_axis: 0.05 }, [
			'radius',
			'mass'
		]);
		expect(impressionFacts(estimated, host)).toEqual(['distance', 'brightness']);
		const limited = record({ radius: 0.18, mass: 0.03, semi_major_axis: 0.8 }, [], ['mass<']);
		expect(impressionFacts(limited, host)).toEqual(['size', 'distance', 'brightness']);
	});

	it('needs the temperature and the radius of the star for its brightness', () => {
		const planet = record({ mass: 6e-5, semi_major_axis: 0.19 }, ['radius']);
		expect(impressionFacts(planet, { teff: null, radius: null })).toEqual(['mass', 'distance']);
		expect(impressionFacts(record({ molecules: [] }), undefined)).toEqual([]);
	});
});
