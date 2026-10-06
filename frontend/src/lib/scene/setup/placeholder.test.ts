/**
 * What `createPlaceholderBody` hands back: bodies with no place yet, the
 * target last, and a page-only stand-in for an object with no orbit, so the
 * scene can still focus it.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

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

/** A bundle with an orbit is one the map can place: it has coverage. */
function detail(name: string, type: string, orbit?: Record<string, unknown>): ObjectDetailData {
	const coverage = orbit && { windows: [[null, null]] };
	return {
		global: { name, type, orbit, coverage },
		localized: null
	} as unknown as ObjectDetailData;
}

/** A scene that holds the bodies in `held` and no others. */
function scene(...held: string[]): ContextManager {
	return {
		getBody: (id: string) => (held.includes(id) ? { data: { id } } : undefined)
	} as unknown as ContextManager;
}

describe('createPlaceholderBody', () => {
	beforeEach(() => details.clear());

	it('stands in for a moon published without an orbit', async () => {
		details.set('spkid-120000243', detail('Dactyl', 'moon'));
		const [entry, ...rest] = await createPlaceholderBody('spkid-120000243', scene());
		expect(rest).toHaveLength(0);
		expect(entry.body.data.pageOnly).toBe(true);
		expect(entry.body.data.name).toBe('Dactyl');
		expect(entry.body.data.parentId).toBe('');
		expect(entry.body.position).toBeNull();
	});

	it('adds only the target when the scene holds its parent', async () => {
		details.set('spkid-2000001', detail('Ceres', 'asteroid_main_belt', KEPLER));
		const entries = await createPlaceholderBody('spkid-2000001', scene('naif-10'));
		expect(entries).toHaveLength(1);
		const { body } = entries[0];
		expect(body.data.pageOnly).toBeUndefined();
		expect(body.orbitElements).toBe(body.data);
		expect(body.orbitCenterId).toBe('naif-10');
		// The placement pass gives it a place.
		expect(body.position).toBeNull();
	});

	it('puts a parent the scene does not hold before the target', async () => {
		details.set(
			'spkid-120000243',
			detail('Dactyl', 'moon', { ...KEPLER, parent_id: 'spkid-2000243' })
		);
		details.set('spkid-2000243', detail('243 Ida', 'asteroid_main_belt'));
		const entries = await createPlaceholderBody('spkid-120000243', scene());
		expect(entries.map((e) => e.body.data.id)).toEqual(['spkid-2000243', 'spkid-120000243']);
		const [parent, target] = entries;
		// The parent has no orbit, so it is a stand-in. The target keeps its own
		// elements: the placement pass finds that its parent has no place.
		expect(parent.body.data.pageOnly).toBe(true);
		expect(target.body.data.pageOnly).toBeUndefined();
		expect(target.body.orbitCenterId).toBe('spkid-2000243');
		expect(entries.every((e) => e.body.position === null)).toBe(true);
	});

	it('hides an id with no catalogue record at all', async () => {
		expect(await createPlaceholderBody('probe-75771904', scene())).toEqual([]);
	});
});
