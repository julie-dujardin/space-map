import { describe, expect, it } from 'vitest';
import { sortNames } from './name';

describe('sortNames', () => {
	it('sorts in the order of the language, not of the global names', () => {
		// Io, Earth, Enceladus, Triton in Russian.
		const names = ['Ио', 'Земля', 'Энцелад', 'Тритон'];
		expect(sortNames(names, 'ru')).toEqual(['Земля', 'Ио', 'Тритон', 'Энцелад']);
		expect(sortNames(['Élara', 'Io', 'Europe'], 'fr')).toEqual(['Élara', 'Europe', 'Io']);
	});
});
