import { describe, expect, it, vi } from 'vitest';
import * as files from './files';
import {
	fetchStarFigures,
	pickableCultures,
	pickedCulture,
	type ExtrasolarSkyCultures
} from './skycultures';

vi.mock('$lib/host', async (original) => ({
	...(await original<typeof import('$lib/host')>()),
	textureAllowed: (tier: string) => tier === 'open'
}));

const entry = (key: string, group: string | null, distribution = 'open') => ({
	key,
	name: key,
	group,
	labels: {},
	figures: 1,
	distribution,
	credit: { name: key, organisation: 'o', source: 's' }
});
const TABLE = {
	cultures: [
		entry('modern_iau', 'modern'),
		entry('chinese', 'eastern-asia'),
		entry('modern_st', null),
		entry('closed', 'eastern-asia', 'site-only')
	]
} as unknown as ExtrasolarSkyCultures;

describe('the cultures a reader may pick', () => {
	it('leaves out a culture with no group, and one the host may not serve', () => {
		expect(pickableCultures(TABLE).map((c) => c.key)).toEqual(['modern_iau', 'chinese']);
	});

	it('reads a stored key the list does not hold as the default', () => {
		const list = pickableCultures(TABLE);
		expect(pickedCulture(list, 'chinese')?.key).toBe('chinese');
		expect(pickedCulture(list, 'closed')?.key).toBe('modern_iau');
		expect(pickedCulture(list, 'modern_st')?.key).toBe('modern_iau');
	});
});

describe('the figures of a star', () => {
	const star = 2 * 64 + 5;
	const table = {
		...TABLE,
		token: 't',
		star_figures: 'skycultures/stars/{shard}.json.gz',
		star_shards: 64
	};
	const figure = { names: [{ english: 'Hunter' }] };

	it('reads one shard, and only the cultures a reader may pick', async () => {
		vi.spyOn(files, 'fetchExtrasolarMetadata').mockResolvedValue({
			skycultures: table
		} as never);
		const json = vi.spyOn(files, 'fetchExtrasolarJson').mockResolvedValue({
			token: 't',
			stars: { [star]: { chinese: [figure], modern_st: [figure], closed: [figure] } }
		} as never);
		const found = await fetchStarFigures(star);
		expect(json).toHaveBeenCalledWith('skycultures/stars/5.json.gz', 't');
		expect(found.cultures.map((c) => c.key)).toEqual(['chinese']);
		expect(found.figures.chinese).toEqual([figure]);
		expect((await fetchStarFigures(1)).cultures).toEqual([]);
	});
});
