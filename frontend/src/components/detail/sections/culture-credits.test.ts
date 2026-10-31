import { describe, expect, it } from 'vitest';
import { cultureSource, datasetSources } from './culture-credits';

const credit = (organisation: string, repo: string, license: string, name = 'A') => ({
	name,
	organisation,
	source: `${repo}/tree/abc/skycultures/${name}`,
	license
});
const STELLARIUM = 'https://github.com/Stellarium/stellarium';

describe('datasetSources', () => {
	it('gives one row per dataset, on the dataset', () => {
		const rows = datasetSources([
			credit('Stellarium', STELLARIUM, 'CC BY-SA 4.0', 'a'),
			credit('Stellarium', STELLARIUM, 'CC BY-SA 4.0', 'b'),
			credit('Doina Bucur', 'https://github.com/doinab/constellation-lines', 'CC BY 4.0')
		]);
		expect(rows.map(({ label, url }) => [label, url])).toEqual([
			['Stellarium', STELLARIUM],
			['Doina Bucur', 'https://github.com/doinab/constellation-lines']
		]);
		expect(rows[0].note).toContain('CC BY-SA 4.0');
	});

	it('names no licence where the cultures differ', () => {
		const [row] = datasetSources([
			credit('Stellarium', STELLARIUM, 'CC BY-SA 4.0', 'a'),
			credit('Stellarium', STELLARIUM, 'CC BY-NC 4.0', 'b')
		]);
		expect(row.note).not.toContain('CC BY');
	});
});

describe('cultureSource', () => {
	it('leaves the team out of the authors', () => {
		const row = cultureSource(
			{ ...credit('Stellarium', STELLARIUM, 'x'), authors: ["Stellarium's team", 'J. Doe'] },
			'note'
		);
		expect(row.label).toBe('Stellarium, A, J. Doe');
	});
});
