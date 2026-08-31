/**
 * What `createPlaceholderBody` hands back for an object the catalogue cannot
 * place: a stand-in the scene can still focus, rather than nothing at all.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import type { ChunkLoader } from '$lib/fetch/position/chunk';

const details = new Map<string, ObjectDetailData>();

vi.mock('$lib/fetch/objects/object-data', () => ({
	fetchObjectDetail: async (id: string) => details.get(id) ?? { global: null, localized: null }
}));

const { createPlaceholderBody } = await import('./placeholder');

const KEPLER = {
	epoch_jd: 2460000,
	a: 2.3,
	e: 0.1,
	i: 5,
	om: 20,
	w: 30,
	ma: 40,
	n: 0.2,
	parent_id: 'naif-10',
	source: 'sbdb'
};

function detail(name: string, type: string, orbit?: Record<string, unknown>): ObjectDetailData {
	return { global: { name, type, orbit }, localized: null } as unknown as ObjectDetailData;
}

function loader(positions: Record<string, [number, number, number]> = {}): ChunkLoader {
	return { positions: new Map(Object.entries(positions)) } as unknown as ChunkLoader;
}

const DATE = new Date('2026-08-30T00:00:00Z');

describe('createPlaceholderBody', () => {
	beforeEach(() => details.clear());

	it('stands in for a moon published without an orbit', async () => {
		details.set('spkid-120000243', detail('Dactyl', 'moon'));
		const [entry, ...rest] = await createPlaceholderBody('spkid-120000243', DATE, loader());
		expect(rest).toHaveLength(0);
		expect(entry.body.data.unplaceable).toBe(true);
		expect(entry.body.data.name).toBe('Dactyl');
		expect(entry.body.positionUnknown).toBe(true);
	});

	it('places an object whose parent is already in the loader', async () => {
		details.set('spkid-2000001', detail('Ceres', 'asteroid_main_belt', KEPLER));
		const [entry] = await createPlaceholderBody(
			'spkid-2000001',
			DATE,
			loader({ 'naif-10': [1, 1, 1] })
		);
		expect(entry.body.data.unplaceable).toBeUndefined();
		expect(entry.body.positionUnknown).toBeUndefined();
	});

	it('stands in for a body whose parent cannot be anchored', async () => {
		details.set(
			'spkid-120000243',
			detail('Dactyl', 'moon', { ...KEPLER, parent_id: 'spkid-2000243' })
		);
		details.set('spkid-2000243', detail('243 Ida', 'asteroid_main_belt'));
		const entries = await createPlaceholderBody('spkid-120000243', DATE, loader());
		const target = entries[entries.length - 1];
		expect(target.body.data.id).toBe('spkid-120000243');
		expect(target.body.data.unplaceable).toBe(true);
	});

	it('hides an id with no catalogue record at all', async () => {
		expect(await createPlaceholderBody('probe-75771904', DATE, loader())).toEqual([]);
	});
});
