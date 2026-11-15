import { describe, expect, it, vi } from 'vitest';
import * as details from '$lib/fetch/groups/details';
import { configureHost } from '$lib/host';
import * as files from './files';
import {
	fetchFigureChart,
	fetchFigureDetail,
	fetchFigureName,
	figurePageName,
	StarChartError
} from './figures';
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

describe('the chart of a figure page', () => {
	const placed = {
		...file,
		members: [
			{ id: 1, position: [1, 0, 0] },
			{ id: 2, position: [0, 2, 0] },
			file.members[2],
			{ ...file.members[3], position: [0, 0, 3] }
		]
	} as unknown as SkyCultureFile;
	const places = { name: 'Gaia Data Release 3', organisation: 'ESA', source: 'https://g' };
	const deepSky = { name: 'OpenNGC', organisation: 'o', source: 'https://d', deep_sky: true };
	const international = { name: 'Stellarium sky cultures', organisation: 's', source: 'https://i' };

	function loadPlaced(): void {
		const culture = {
			file: placed,
			entry: { key: 'maya', group: 'x', labels: {}, credit },
			credits: [credit, places, deepSky]
		};
		vi.spyOn(skycultures, 'fetchSkyCulture').mockResolvedValue(culture as never);
		vi.spyOn(skycultures, 'fetchInternationalNames').mockResolvedValue({
			file: {
				members: [{ id: 9, position: [1, 1, 0] }],
				figures: [],
				names: [{ member: 0, names: [{ english: 'Nine' }] }]
			} as never,
			credit: international
		});
	}

	it('is on the page of a figure with a place in the sky, and on no other', async () => {
		load();
		expect(
			(await fetchFigureDetail('culture-maya', '003', 'en')).global?.star_chart
		).toBeUndefined();
		loadPlaced();
		expect((await fetchFigureDetail('culture-maya', '003', 'en')).global?.star_chart).toMatchObject(
			{ slug: 'culture-maya', figure: '003' }
		);
	});

	it('names a star as the member list does, and no star that readers do not know', async () => {
		loadPlaced();
		const { global } = await fetchFigureDetail('culture-maya', '003', 'en');
		const { chart, name } = await global!.star_chart!.load();
		expect(chart.lines).toHaveLength(2);
		expect(chart.standIns).toEqual([{ direction: [0, 0, 1], name: 'NGC 224' }]);
		const listed = new Map(global!.notable_members!.map((member) => [member.id, member.name]));
		expect(await Promise.all(chart.stars.map(name))).toEqual([null, listed.get('x-2')]);
	});

	it('takes the names of a constellation as the member list shows them', async () => {
		loadPlaced();
		vi.spyOn(details, 'fetchGroupDetail').mockResolvedValue({
			global: { notable_members: [{ id: 'x-2', name: 'Betelgeuse' }] },
			localized: { notable_member_names: { 'x-2': 'Bételgeuse' } }
		} as never);
		const { global } = await fetchFigureDetail('culture-maya', 'Ori', 'fr');
		const { chart, name } = await global!.star_chart!.load();
		expect(await Promise.all(chart.stars.map(name))).toEqual(['Bételgeuse', null]);
	});

	it('credits what it draws from: a deep-sky catalogue only with such a member', async () => {
		loadPlaced();
		const turtle = await fetchFigureDetail('culture-maya', '003', 'en');
		expect((await turtle.global!.star_chart!.load()).credits).toEqual([
			credit,
			places,
			deepSky,
			international
		]);
		const hearth = await fetchFigureDetail('culture-maya', 'Ori', 'en');
		expect((await hearth.global!.star_chart!.load()).credits).toEqual([
			credit,
			places,
			international
		]);
	});

	it('draws with no neighbours when their names do not load, and reads them again', async () => {
		loadPlaced();
		const names = vi.spyOn(skycultures, 'fetchInternationalNames');
		names.mockRejectedValueOnce(new Error('offline'));
		const { global } = await fetchFigureDetail('culture-maya', '003', 'en');
		const first = await global!.star_chart!.load();
		expect(first.chart.neighbours).toEqual([]);
		expect(first.credits).not.toContain(international);
		const fuller = await first.more!();
		expect(fuller.more).toBeUndefined();
		expect(fuller.chart.neighbours.map(({ id }) => id)).toEqual([9]);
		expect(fuller.credits).toContain(international);
		// The figure stays the same objects, so its frame stays.
		expect(fuller.chart.points).toBe(first.chart.points);
		expect(fuller.chart.lines).toBe(first.chart.lines);
	});

	it('does not read the names again when the host has no such file', async () => {
		loadPlaced();
		vi.spyOn(skycultures, 'fetchInternationalNames').mockRejectedValue(
			new files.ExtrasolarStatusError('https://t/v1/x/names.json.gz', 404)
		);
		const { global } = await fetchFigureDetail('culture-maya', '003', 'en');
		expect((await global!.star_chart!.load()).more).toBeUndefined();
	});
});

describe('the chart of a figure with no page around it', () => {
	const placed = {
		...file,
		members: [
			{ id: 1, position: [1, 0, 0] },
			{ id: 2, position: [0, 2, 0] },
			...file.members.slice(2)
		]
	} as unknown as SkyCultureFile;

	function serve(distribution: string): void {
		vi.spyOn(files, 'fetchExtrasolarMetadata').mockResolvedValue({
			skycultures: { cultures: [{ key: 'maya', distribution }] }
		} as never);
		vi.spyOn(skycultures, 'fetchSkyCulture').mockResolvedValue({
			file: placed,
			entry: { key: 'maya', group: 'x', labels: {}, credit },
			credits: [credit]
		} as never);
		vi.spyOn(skycultures, 'fetchInternationalNames').mockResolvedValue(null);
	}

	async function reason(slug: string, figure: string): Promise<string | undefined> {
		const error = await fetchFigureChart(slug, figure, 'en').catch((e: unknown) => e);
		return error instanceof StarChartError ? error.reason : undefined;
	}

	it('is unavailable where the host serves no sky cultures', async () => {
		vi.spyOn(files, 'fetchExtrasolarMetadata').mockResolvedValue(null);
		expect(await reason('culture-maya', '003')).toBe('unavailable');
	});

	it('needs the non-commercial tier for a non-commercial culture', async () => {
		serve('non-commercial');
		configureHost({ textures: 'open' });
		expect(await reason('culture-maya', '003')).toBe('non-commercial');
		configureHost({ textures: 'non-commercial' });
		const { name, chart } = await fetchFigureChart('culture-maya', '003', 'en');
		expect(name).toBe('Turtle');
		expect(chart.chart.lines).toHaveLength(1);
		configureHost({});
	});

	it('is not found for another culture, another figure, or a figure with no place', async () => {
		serve('open');
		expect(await reason('culture-inca', '003')).toBe('not-found');
		expect(await reason('maya', '003')).toBe('not-found');
		expect(await reason('culture-maya', '999')).toBe('not-found');
		vi.spyOn(skycultures, 'fetchSkyCulture').mockResolvedValue({
			file,
			entry: { key: 'maya', group: 'x', labels: {}, credit },
			credits: [credit]
		} as never);
		expect(await reason('culture-maya', '003')).toBe('not-found');
	});
});
