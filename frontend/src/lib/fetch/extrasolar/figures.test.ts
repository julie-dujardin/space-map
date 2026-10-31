import { describe, expect, it, vi } from 'vitest';
import * as details from '$lib/fetch/groups/details';
import { fetchFigureDetail, fetchFigureName, figurePageName } from './figures';
import * as skycultures from './skycultures';
import type { LoadedSkyCulture, SkyCultureFile } from './skycultures';

vi.mock('./lookup', () => ({
	extrasolarLookup: {
		live: async (id: number) => ({
			kind: 'live',
			record: { metadata: { name: `HIP ${id}`, object: false } }
		})
	}
}));

const credit = {
	name: 'Maya',
	organisation: 'Stellarium',
	source: 'https://s',
	license: 'CC BY-SA'
};
const file = {
	token: 't',
	key: 'maya',
	members: [{ id: 1 }, { id: 2 }, { ra_hours: 1, dec: 2 }, { ref: 'M 31', designation: 'NGC 224' }],
	figures: [
		{
			id: 'CON maya 003',
			kind: 'constellation',
			names: [{ english: 'Turtle' }],
			labels: { fr: 'Tortue' },
			lines: [[0, 1, 2, 3, 0]],
			slug: '003',
			description: 'The text of the dataset.'
		},
		{ id: 'CON maya 004', kind: 'constellation', names: [], lines: [], slug: '004' },
		{
			id: 'CON maya Ori',
			kind: 'constellation',
			names: [{ english: 'Hearth' }],
			lines: [[1, 0]],
			page: 'sky-orion',
			slug: 'Ori'
		}
	],
	names: [{ member: 1, names: [{ english: 'Own name' }] }]
} as unknown as SkyCultureFile;

function load(group: string | null = 'central-america'): void {
	const culture = {
		file,
		entry: {
			key: 'maya',
			name: 'Maya',
			group,
			labels: { fr: 'Maya (fr)' },
			distribution: 'open',
			credit
		},
		credits: [credit]
	} as unknown as LoadedSkyCulture;
	vi.spyOn(skycultures, 'fetchSkyCulture').mockResolvedValue(culture);
}

describe('the page of a figure', () => {
	it('reads as a group: name, culture above it, stars, text and credit', async () => {
		load();
		const { global, localized } = await fetchFigureDetail('culture-maya', '003', 'fr');
		expect(localized?.name).toBe('Tortue');
		expect(global).toMatchObject({
			type: 'sky_constellation',
			parent_group: 'culture-maya',
			member_count: 2,
			culture_text: { text: 'The text of the dataset.', credit },
			figure_credit: credit
		});
		expect(localized?.parent_group_name).toBe('Maya (fr)');
		expect(global?.notable_members).toEqual([
			{ id: 'x-1', name: 'HIP 1' },
			{ id: 'x-2', name: 'HIP 2' },
			{ name: 'NGC 224' }
		]);
	});

	it('still has a page with no name, no line and no text', async () => {
		load();
		const { global, localized } = await fetchFigureDetail('culture-maya', '004', 'en');
		expect(localized?.name).toBe('004');
		expect(global?.member_count).toBe(0);
		expect(global?.culture_text).toBeUndefined();
	});

	it('takes the text and pictures of a constellation, and keeps its own stars', async () => {
		load();
		vi.spyOn(details, 'fetchGroupDetail').mockResolvedValue({
			global: {
				slug: 'sky-orion',
				images: [{ file: 'a.jpg' }],
				notable_members: [{ id: 'x-2', name: 'Betelgeuse', thumbnail: { file: 'b' } }]
			},
			localized: {
				name: 'Orion',
				wikipedia: { extract: 'Orion is…' },
				notable_member_names: { 'x-2': 'Bételgeuse' }
			}
		} as never);
		const { global, localized } = await fetchFigureDetail('culture-maya', 'Ori', 'fr');
		expect(localized).toMatchObject({
			name: 'Hearth',
			wikipedia: { extract: 'Orion is…' },
			notable_member_names: { 'x-2': 'Bételgeuse' }
		});
		expect(global?.images).toEqual([{ file: 'a.jpg' }]);
		expect(global?.notable_members?.map((member) => member.id)).toEqual(['x-2', 'x-1']);
	});

	it('climbs where the constellation does from a culture with no page', async () => {
		load(null);
		vi.spyOn(details, 'fetchGroupDetail').mockResolvedValue({
			global: { parent_group: 'culture-modern_iau' },
			localized: { parent_group_name: 'IAU' }
		} as never);
		const { global, localized } = await fetchFigureDetail('culture-maya', 'Ori', 'en');
		expect(global?.parent_group).toBe('culture-modern_iau');
		expect(localized?.parent_group_name).toBe('IAU');
	});

	it('refuses a figure the culture does not hold', async () => {
		load();
		await expect(fetchFigureDetail('culture-maya', '999', 'en')).rejects.toThrow('no figure');
		await expect(fetchFigureName('culture-other', '003')).rejects.toThrow('no figure');
	});

	it('goes by its id with no name and no segment', () => {
		expect(figurePageName({ id: 'CON maya 1', names: [] } as never, 'en')).toBe('CON maya 1');
	});
});
