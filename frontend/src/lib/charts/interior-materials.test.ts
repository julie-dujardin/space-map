import { describe, it, expect, vi } from 'vitest';
import { detailSpeciesName, detailSpeciesColor } from './interior-materials';

describe('layer-detail species', () => {
	// Fe-Ni is the only species whose variable name is not just the lowercased
	// formula, so it is the naming case worth asserting.
	it('keeps the hyphen when an alloy names its variable', () => {
		expect(detailSpeciesColor('SiO2')).toBe('var(--species-sio2)');
		expect(detailSpeciesColor('Fe-Ni')).toBe('var(--species-fe-ni)');
	});

	it('has a name for every species without falling back', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const species of [
			'SiO2',
			'Al2O3',
			'FeO',
			'MgO',
			'CaO',
			'Na2O',
			'K2O',
			'TiO2',
			'Fe',
			'Ni',
			'Co',
			'S',
			'Si',
			'Fe-Ni'
		]) {
			detailSpeciesName(species);
		}
		expect(warn).not.toHaveBeenCalled();
		warn.mockRestore();
	});

	it('falls back visibly for a species it has never seen', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(detailSpeciesColor('PH3')).toBe('var(--muted-foreground)');
		expect(detailSpeciesName('PH3')).toBe('PH₃');
		expect(warn).toHaveBeenCalledTimes(2);
		warn.mockRestore();
	});
});
