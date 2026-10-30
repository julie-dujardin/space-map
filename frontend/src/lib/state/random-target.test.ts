/**
 * The draw picks a kind of thing first, then descends one level at a time, so a
 * million-member zone is one choice among its siblings rather than the whole
 * draw. Collection pages are their own root slot, drawn flat off the group
 * index; the Planets slot draws an exoplanet off the planet index; the
 * categories that only re-list bodies seen elsewhere are no slot at all.
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
import { MEMBER_ATTEMPTS, randomTarget, randomTargetPath } from './random-target';

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
	// Structure & Activity is listed by the root and dropped by the draw;
	// Satellites and Debris are not listed and added by it.
	[CAT_SOLAR_SYSTEM]: detail(1592942, [
		CAT_PLANETS,
		CAT_MOONS,
		CAT_ASTEROIDS,
		CAT_STRUCTURE_ACTIVITY
	]),
	[CAT_PLANETS]: {
		...detail(6782, ['planet-giant-planet']),
		global: {
			slug: CAT_PLANETS,
			member_count: 6782,
			solar_members: [
				{ id: 'naif-399', name: 'Earth' },
				{ id: 'naif-599', name: 'Jupiter' }
			]
		} as GroupDetailData['global']
	},
	'planet-giant-planet': detail(2715),
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
const SLOTS = [0, 0.2, 0.4, 0.55, 0.75, 0.9];
const [COLLECTIONS, PLANETS, MOONS, ASTEROIDS, SATELLITES] = SLOTS;

const INDEX = { [CAT_SOLAR_SYSTEM]: {}, [CAT_PLANETS]: {}, 'const-starlink': {} };

vi.mock('$lib/fetch/groups/registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/groups/registry')>()),
	fetchGroupIndex: () => Promise.resolve(INDEX)
}));

vi.mock('$lib/fetch/groups/details', () => ({
	fetchGroupDetail: (slug: string) => Promise.resolve(groups[slug])
}));

let lastQuery: { slug: string; offset: number } | null = null;
/** Ids the collection hands out, in order, when a test cares which. */
let memberIds: string[] = [];
/** The index gives no answer: no key, or no server. */
let indexDown = false;
vi.mock('$lib/search/client', () => ({
	MAX_TOTAL_HITS: 1000,
	isSearchEnabled: () => true,
	localizedName: (hit: { name: string }) => hit.name,
	searchGroupMembers: (slug: string, offset: number): Promise<GroupMemberPage> => {
		lastQuery = { slug, offset };
		if (indexDown) return Promise.reject(new Error('no search key'));
		const id = memberIds.shift() ?? `naif-${offset}`;
		return Promise.resolve({
			hits: [{ kind: 'object', id, name: `member ${offset}` }],
			estimatedTotalHits: 1000
		} as GroupMemberPage);
	}
}));

/** Two placed hosts with three planets, the second a brown dwarf, and one
 *  host with no place. */
const PLACED = 26297087;
const UNPLACED = 20014192;
let planetIndex: { file: { hosts: object[] } } | null = null;
const planetClass: Record<string, string> = {};
vi.mock('$lib/fetch/extrasolar/planets', () => ({
	planetCatalogue: {
		index: () => Promise.resolve(planetIndex),
		planet: (host: number, n: number) =>
			Promise.resolve({
				planet: { host, number: n, name: `${host} ${n}`, class: planetClass[`${host}/${n}`] }
			})
	}
}));

const UNIFORM = { kind: 'object', id: 'spkid-20000433', name: 'drawn uniformly' };
vi.mock('./uniform-random-target', () => ({
	uniformRandomTarget: () => Promise.resolve(UNIFORM)
}));

/** A bundle the map can place: the pipeline wrote the dates it covers. */
const COVERED = { coverage: { windows: [[2460000, null]] } };
/** Bundles with no coverage. Every other member draws {@link COVERED}. */
const uncovered: Record<string, object> = {
	// A moon of an asteroid published without an orbit.
	'spkid-1': { type: 'moon' }
};

vi.mock('$lib/fetch/objects/object-data', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/objects/object-data')>()),
	fetchObjectDetail: (id: string) =>
		Promise.resolve({ global: uncovered[id] ?? COVERED, localized: null })
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
	memberIds = [];
	indexDown = false;
	planetIndex = {
		file: {
			hosts: [
				{ id: UNPLACED, position: null, planets: [1] },
				{ id: PLACED, position: [1, 2, 3], planets: [1, 2, 3] }
			]
		}
	};
	Object.assign(planetClass, {
		[`${PLACED}/1`]: 'planet',
		[`${PLACED}/2`]: 'brown dwarf',
		[`${PLACED}/3`]: 'planet',
		[`${UNPLACED}/1`]: 'planet'
	});
});
afterEach(() => vi.restoreAllMocks());

describe('randomTarget: the root slots', () => {
	it('asks search for no member of Planets or of Structure & Activity', async () => {
		// The Planets slot draws off the planet index; Structure & Activity holds
		// collections, which have their own slot.
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
		// With Moons struck off, the five remaining slots shift: 0.5 is Asteroids.
		draws(0.5, 0, 0.5);
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

describe('randomTarget: the Planets slot', () => {
	it('draws an exoplanet whose star has a place', async () => {
		// Ticket 0 of the three placed planets is the first.
		draws(PLANETS, 0);
		await expect(randomTarget()).resolves.toEqual({
			kind: 'object',
			id: `x-${PLACED}-b-1`,
			name: `${PLACED} 1`
		});
		expect(recorded().categories).toEqual([CAT_PLANETS]);
		expect(lastQuery).toBeNull();
	});

	it('redraws a brown dwarf', async () => {
		draws(PLANETS, 0.5, 0.9);
		await expect(randomTarget()).resolves.toMatchObject({ id: `x-${PLACED}-b-3` });
	});

	// The families list only exoplanets, which the map places from the index.
	it('draws a Solar System planet when no planets are served', async () => {
		planetIndex = null;
		draws(PLANETS, 0.5);
		await expect(randomTarget()).resolves.toEqual({
			kind: 'object',
			id: 'naif-599',
			name: 'Jupiter'
		});
		expect(recorded().categories).toEqual([CAT_PLANETS]);
		expect(lastQuery).toBeNull();
	});
});

describe('randomTarget: what the map can place', () => {
	it('redraws an object the scene has nowhere to put', async () => {
		// A moon of an asteroid published without an orbit, then a real one.
		memberIds = ['spkid-1', 'spkid-2'];
		draws(MOONS, 0.5);
		await expect(randomTarget()).resolves.toMatchObject({ id: 'spkid-2' });
	});

	it('hands back the collection when nothing in it can be placed', async () => {
		memberIds = Array.from({ length: MEMBER_ATTEMPTS }, () => 'spkid-1');
		draws(MOONS, 0.5);
		await expect(randomTarget()).resolves.toEqual({
			kind: 'group',
			slug: CAT_MOONS,
			name: CAT_MOONS
		});
	});

	it('asks nothing of a landform or a collection', async () => {
		draws(COLLECTIONS, 0.9);
		await expect(randomTarget()).resolves.toMatchObject({ kind: 'group' });
	});
});

describe('randomTarget: an index that gives no answer', () => {
	it('draws uniformly, and records nothing of the walk', async () => {
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		indexDown = true;
		draws(MOONS, 0.5);
		await expect(randomTarget()).resolves.toEqual(UNIFORM);
		expect(lastQuery?.slug).toBe(CAT_MOONS);
		expect(store.has(RECENT_KEY)).toBe(false);
	});

	it('still walks to a collection page, which asks the index nothing', async () => {
		indexDown = true;
		draws(COLLECTIONS, 0.99);
		await expect(randomTarget()).resolves.toMatchObject({ kind: 'group' });
		expect(lastQuery).toBeNull();
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

	it('routes an exoplanet to its planet page', () => {
		expect(randomTargetPath({ kind: 'object', id: `x-${PLACED}-b-2`, name: 'HD 100546 c' })).toBe(
			`/x/[id]/b/[n]/[[name]] {"id":"${PLACED}","n":"2","name":"HD%20100546%20c"}`
		);
	});

	it('routes a collection to its /g page', () => {
		expect(randomTargetPath({ kind: 'group', slug: 'class-MBA', name: 'Main Belt' })).toBe(
			'/[type]/[id]/[[name]] {"type":"g","id":"class-MBA","name":"Main%20Belt"}'
		);
	});
});
