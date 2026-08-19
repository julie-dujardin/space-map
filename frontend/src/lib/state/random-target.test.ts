/**
 * The draw picks a kind of thing first, then descends one level at a time, so a
 * million-member zone is one choice among its siblings rather than the whole
 * draw. Collection pages are their own root slot, drawn flat off the group
 * index; the categories that only re-list bodies seen elsewhere are no slot at
 * all.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	CAT_ASTEROIDS,
	CAT_DEBRIS,
	CAT_MOONS,
	CAT_PLANETS,
	CAT_SATELLITES,
	CAT_SOLAR_SYSTEM,
	CAT_STRUCTURE_ACTIVITY
} from '$lib/fetch/groups/registry';
import type { GroupDetailData } from '$lib/fetch/groups/details';
import type { GroupMemberPage } from '$lib/search/client';
import { randomTarget, randomTargetPath } from './random-target';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string>) => `${route} ${JSON.stringify(params)}`
}));

function detail(memberCount: number, children: string[] = [], name?: string): GroupDetailData {
	return {
		global: { slug: '', member_count: memberCount } as GroupDetailData['global'],
		localized: {
			name,
			child_groups: children.map((slug) => ({
				name: slug,
				primary_id: slug,
				role: 'category',
				n: 1
			}))
		} as GroupDetailData['localized']
	};
}

const groups: Record<string, GroupDetailData> = {
	// Planets and Structure & Activity are listed by the root and dropped by the
	// draw; Satellites and Debris are not listed and added by it.
	[CAT_SOLAR_SYSTEM]: detail(1592942, [
		CAT_PLANETS,
		CAT_MOONS,
		CAT_ASTEROIDS,
		CAT_STRUCTURE_ACTIVITY
	]),
	[CAT_PLANETS]: detail(8),
	[CAT_MOONS]: detail(987),
	[CAT_ASTEROIDS]: detail(1554068, ['class-MBA', 'class-TNO']),
	'class-MBA': detail(1374806),
	'class-TNO': detail(7129),
	[CAT_STRUCTURE_ACTIVITY]: detail(26, ['cat-radiation']),
	[CAT_SATELLITES]: detail(30000),
	[CAT_DEBRIS]: detail(5000),
	'const-starlink': detail(12221, [], 'Starlink')
};

/** Root slots, in the order the draw builds them: the collections slot, the
 *  drawing categories the root lists, then the two it doesn't. */
const SLOTS = [0, 0.3, 0.5, 0.7, 0.9];
const [COLLECTIONS, MOONS, ASTEROIDS, SATELLITES] = SLOTS;

const INDEX = { [CAT_SOLAR_SYSTEM]: {}, [CAT_PLANETS]: {}, 'const-starlink': {} };

vi.mock('$lib/fetch/groups/registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/groups/registry')>()),
	fetchGroupIndex: () => Promise.resolve(INDEX)
}));

vi.mock('$lib/fetch/groups/details', () => ({
	fetchGroupDetail: (slug: string) => Promise.resolve(groups[slug])
}));

let lastQuery: { slug: string; offset: number } | null = null;
vi.mock('$lib/search/client', () => ({
	MAX_TOTAL_HITS: 1000,
	isSearchEnabled: () => true,
	localizedName: (hit: { name: string }) => hit.name,
	searchGroupMembers: (slug: string, offset: number): Promise<GroupMemberPage> => {
		lastQuery = { slug, offset };
		return Promise.resolve({
			hits: [{ kind: 'object', id: `naif-${offset}`, name: `member ${offset}` }],
			estimatedTotalHits: 1000
		} as GroupMemberPage);
	}
}));

/** Successive draws over the unit interval, so a test names the branch it takes. */
function draws(...values: number[]) {
	let i = 0;
	vi.spyOn(Math, 'random').mockImplementation(() => values[Math.min(i++, values.length - 1)]);
}

const RECENT_KEY = 'space-map-random-recent';
const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
	getItem: (k: string) => store.get(k) ?? null,
	setItem: (k: string, v: string) => void store.set(k, v),
	removeItem: (k: string) => void store.delete(k)
});

function seedRecent(recent: { targets?: string[]; categories?: string[] }) {
	store.set(RECENT_KEY, JSON.stringify({ targets: [], categories: [], ...recent }));
}

function recorded() {
	return JSON.parse(store.get(RECENT_KEY) ?? '{}');
}

beforeEach(() => {
	store.clear();
	lastQuery = null;
});
afterEach(() => vi.restoreAllMocks());

describe('randomTarget: the root slots', () => {
	it('draws no bodies from the categories that only re-list them', async () => {
		// Whichever slot comes up, none of them leads to the Planets page's members
		// or to Structure & Activity — the bodies there have a home elsewhere.
		for (const slot of SLOTS) {
			store.clear();
			draws(slot, 0.5);
			await randomTarget();
			expect(lastQuery?.slug).not.toBe(CAT_PLANETS);
			expect(lastQuery?.slug).not.toBe(CAT_STRUCTURE_ACTIVITY);
		}
	});

	it('reaches a zone through its category, not through the whole catalogue', async () => {
		draws(ASTEROIDS, 0, 0.5);
		await expect(randomTarget()).resolves.toMatchObject({ kind: 'object' });
		expect(lastQuery?.slug).toBe('class-MBA');
	});

	it('gives the belt no more weight than any other zone', async () => {
		// The same draw one slot along lands on the 7129-member zone: the 1.37 M
		// one is a sibling, not a majority.
		draws(ASTEROIDS, 0.9, 0.5);
		await randomTarget();
		expect(lastQuery?.slug).toBe('class-TNO');
	});

	it('can draw the Earth-orbiter collections the root does not list', async () => {
		draws(SATELLITES, 0.5);
		await randomTarget();
		expect(lastQuery?.slug).toBe(CAT_SATELLITES);
	});

	it("draws a member out of the collection's own count", async () => {
		draws(MOONS, 0.5);
		await randomTarget();
		// 987 moons, so the offset is 493 — not a slice of the 1000-hit cap.
		expect(lastQuery).toEqual({ slug: CAT_MOONS, offset: 493 });
	});
});

describe('randomTarget: the collections slot', () => {
	it('draws any page in the group index, named from its bundle', async () => {
		// Slot 0 is the collections slot; index entry 2 is the constellation.
		draws(COLLECTIONS, 0.9);
		await expect(randomTarget()).resolves.toEqual({
			kind: 'group',
			slug: 'const-starlink',
			name: 'Starlink'
		});
		expect(lastQuery).toBeNull();
	});

	it('can draw the pages no category leads to any more', async () => {
		draws(COLLECTIONS, 0.5);
		await expect(randomTarget()).resolves.toMatchObject({ slug: CAT_PLANETS });
	});

	it('records every collection under the one meta category', async () => {
		draws(COLLECTIONS, 0.9);
		await randomTarget();
		expect(recorded().categories).toEqual(['collections']);
	});
});

describe('randomTarget: what the last draws already covered', () => {
	it('redraws when the destination is one of the recent ones', async () => {
		seedRecent({ targets: ['naif-0'] });
		// First attempt draws offset 0 (= naif-0, refused); the second draws 493.
		draws(MOONS, 0, MOONS, 0.5);
		await expect(randomTarget()).resolves.toMatchObject({ id: 'naif-493' });
	});

	it('strikes the recent categories off the root', async () => {
		seedRecent({ categories: [CAT_MOONS] });
		// With Moons struck off, the four remaining slots shift: 0.3 is Asteroids.
		draws(0.3, 0, 0.5);
		await randomTarget();
		expect(lastQuery?.slug).toBe('class-MBA');
	});

	it('takes a repeat rather than giving up when every attempt is recent', async () => {
		seedRecent({ targets: ['naif-0'] });
		// Every attempt walks to the same refused member; the last one is taken.
		draws(...Array.from({ length: 8 }, () => [MOONS, 0]).flat());
		await expect(randomTarget()).resolves.toMatchObject({ id: 'naif-0' });
	});

	it('records the destination and the category it came through', async () => {
		draws(MOONS, 0.5);
		await randomTarget();
		expect(recorded()).toEqual({ targets: ['naif-493'], categories: [CAT_MOONS] });
	});
});

describe('randomTargetPath', () => {
	it('routes a feature to its host body', () => {
		expect(
			randomTargetPath({ kind: 'feature', bodyId: 'naif-301', featureId: 12, name: 'Copernicus' })
		).toBe(
			'/[type]/[id]/f/[featureId]/[[name]] {"type":"b","id":"301","featureId":"12","name":"Copernicus"}'
		);
	});

	it('routes a collection to its /g page', () => {
		expect(randomTargetPath({ kind: 'group', slug: 'class-MBA', name: 'Main Belt' })).toBe(
			'/[type]/[id]/[[name]] {"type":"g","id":"class-MBA","name":"Main%20Belt"}'
		);
	});
});
