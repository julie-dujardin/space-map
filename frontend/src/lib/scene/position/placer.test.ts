import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { J2000_JD } from '$lib/time/jd';
import { PositionDiagnostics } from './diagnostics';
import { Placer } from './placer';

const JD = 2461300;

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id' | 'parentId'>): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.ASTEROID_INNER,
			radiusKm: NaN,
			hasLocalized: false,
			a: 1.5,
			e: 0.1,
			i: 5,
			om: 20,
			w: 30,
			ma: 40,
			n: 0.5,
			epoch: 2461000,
			validityStart: -Infinity,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.SBDB,
			...data
		},
		position: null
	};
}

/** What a fake ephemeris answers for the bodies it tracks. */
interface FakeCheb {
	ids: string[];
	offset: (id: string, jd: number) => [number, number, number] | null;
	coverage?: { start: number; end: number };
	/** A chunk for the date is on its way. */
	loading?: boolean;
	/** Catalogue rows of the bodies that have one. */
	rows?: Map<string, BodyData>;
}

/** A probe store with no chunk for the date, and one on its way or not. */
const probeStoreWith = (loading: boolean) => ({
	ridesAt: () => [],
	probeWithCenter: () => null,
	loadingAt: () => loading
});

/** A placer over a scene that holds `bodies`. */
function placerOver(
	bodies: PositionedBody[],
	cheb?: FakeCheb,
	probeStore: ReturnType<typeof probeStoreWith> | null = null,
	held?: () => boolean
): Placer {
	const byId = new Map(bodies.map((b) => [b.data.id, b]));
	const ctx = {
		getBody: (id: string) => byId.get(id),
		bodies: {
			elementRow: (b: PositionedBody) => (cheb ? cheb.rows?.get(b.data.id) : b.data)
		},
		chebStore: cheb
			? {
					has: (id: string) => cheb.ids.includes(id),
					positionScene: cheb.offset,
					zoneCoverage: () => cheb.coverage ?? null,
					isLoading: () => cheb.loading ?? false
				}
			: null,
		probeStore,
		visibility: { activeSystemId: null }
	} as unknown as ContextManager;
	return new Placer(ctx, new Map(), new PositionDiagnostics(), held);
}

function placerFor(...bodies: PositionedBody[]): Placer {
	return placerOver(bodies);
}

describe('Placer.place', () => {
	it('places a body about the barycentre of the Solar System', () => {
		const rock = mkBody({ id: 'rock', parentId: 'naif-0' });
		const at = placerFor(rock).place(rock, JD);
		expect(at).not.toBeNull();
		expect(rock.position).toBe(at);
		expect(rock.unplaced).toBeUndefined();
	});

	it('places a child from the place of its parent at the same date', () => {
		const host = mkBody({ id: 'host', parentId: 'naif-0' });
		const moon = mkBody({ id: 'moon', parentId: 'host', a: 0.0001, n: 300 });
		const placer = placerFor(host, moon);
		// The parent has no place yet: the child settles it first.
		const at = placer.place(moon, JD)!;
		expect(host.position).not.toBeNull();
		expect(
			Math.hypot(at[0] - host.position![0], at[1] - host.position![1], at[2] - host.position![2])
		).toBeLessThan(0.01);
	});

	it('gives no place to a body whose parent has none', () => {
		const host = mkBody({ id: 'host', parentId: 'naif-0', visibleFromDays: 1e9 });
		const moon = mkBody({ id: 'moon', parentId: 'host' });
		const placer = placerFor(host, moon);
		expect(placer.place(moon, JD)).toBeNull();
		expect(moon.unplaced).toBe('parent');
		expect(host.unplaced).toBe('not-yet');
	});

	it('gives no place to a body whose parent is not in the scene', () => {
		const orphan = mkBody({ id: 'orphan', parentId: 'spkid-1' });
		expect(placerFor(orphan).place(orphan, JD)).toBeNull();
		expect(orphan.unplaced).toBe('parent');
	});

	it('gives no place to a page-only stand-in', () => {
		const page = mkBody({ id: 'page', parentId: 'naif-0', pageOnly: true, a: NaN });
		expect(placerFor(page).place(page, JD)).toBeNull();
		expect(page.unplaced).toBe('never');
	});

	it('takes the place away when the date leaves the data', () => {
		const sat = mkBody({
			id: 'sat',
			parentId: 'naif-0',
			validityStart: JD - 1,
			validityEnd: JD + 1
		});
		const placer = placerFor(sat);
		expect(placer.place(sat, JD)).not.toBeNull();
		expect(placer.place(sat, JD + 10)).toBeNull();
		expect(sat.position).toBeNull();
		expect(sat.unplaced).toBe('no-data');
	});

	it('gives the place back when the date comes back', () => {
		const moon = mkBody({ id: 'moon', parentId: 'naif-0', visibleFromDays: JD - J2000_JD });
		const placer = placerFor(moon);
		expect(placer.place(moon, JD - 1)).toBeNull();
		expect(placer.place(moon, JD + 1)).not.toBeNull();
		expect(moon.unplaced).toBeUndefined();
	});

	it('ends on a parent chain that loops', () => {
		const a = mkBody({ id: 'a', parentId: 'b' });
		const b = mkBody({ id: 'b', parentId: 'a' });
		expect(placerFor(a, b).place(a, JD)).toBeNull();
	});
});

/**
 * The orbit centre of a moon is its planet, and the planet has its own place.
 * The moon holds a copy, so a write to the centre cannot move the planet.
 */
describe('orbit centre', () => {
	function system() {
		const bary = mkBody({ id: 'bary', parentId: 'naif-0', objectType: ObjectType.BARYCENTER });
		const planet = mkBody({
			id: 'planet',
			parentId: 'bary',
			objectType: ObjectType.PLANET,
			a: 0.00003,
			n: 13
		});
		const moon = mkBody({
			id: 'moon',
			parentId: 'bary',
			objectType: ObjectType.MOON,
			a: 0.0025,
			n: 13
		});
		moon.orbitCenterId = 'planet';
		return { bary, planet, moon, placer: placerFor(bary, planet, moon) };
	}

	it('is where the centre body is', () => {
		const { planet, moon, placer } = system();
		placer.place(moon, JD);
		expect(moon.orbitCenter).toEqual(planet.position);
		expect(moon.orbitCenter).not.toBe(planet.position);
	});

	it('leaves the planet off its barycentre', () => {
		const { bary, planet, moon, placer } = system();
		placer.begin(JD, undefined, undefined);
		for (const body of [bary, planet, moon]) placer.placeInPass(body);
		const off = Math.hypot(
			planet.position![0] - bary.position![0],
			planet.position![1] - bary.position![1],
			planet.position![2] - bary.position![2]
		);
		expect(off).toBeGreaterThan(0);
	});

	it('is null while the centre body has no place', () => {
		const { planet, moon, placer } = system();
		planet.data.visibleFromDays = 1e9;
		expect(placer.place(moon, JD)).not.toBeNull();
		expect(moon.orbitCenter).toBeNull();
	});
});

describe('Placer pass', () => {
	it('settles a body once per pass', () => {
		const rock = mkBody({ id: 'rock', parentId: 'naif-0' });
		const placer = placerFor(rock);
		placer.begin(JD, undefined, undefined);
		placer.placeInPass(rock);
		const first = [...rock.position!];
		// Other elements, same pass: the place is the settled one.
		rock.data.ma += 90;
		expect([...placer.place(rock, JD)!]).toEqual(first);
		placer.begin(JD, undefined, undefined);
		expect([...placer.place(rock, JD)!]).not.toEqual(first);
	});
});

describe('a scene held at the date of its last pass', () => {
	it('gives a reader the place it shows, whatever date the reader asks for', () => {
		const rock = mkBody({ id: 'rock', parentId: 'naif-0' });
		let held = false;
		const placer = placerOver([rock], undefined, null, () => held);
		placer.begin(JD, undefined, undefined);
		placer.placeInPass(rock);
		const shown = [...rock.position!];
		held = true;
		expect([...placer.place(rock, JD + 50)!]).toEqual(shown);
		expect([...rock.position!]).toEqual(shown);
		held = false;
		expect([...placer.place(rock, JD + 50)!]).not.toEqual(shown);
	});
});

describe('a body the ephemeris tracks', () => {
	const moon = () =>
		mkBody({ id: 'naif-301', parentId: 'naif-0', orbitalSource: OrbitalSource.SPICE });
	const coverage = { start: JD - 100, end: JD + 100 };

	it('is placed from the ephemeris', () => {
		const body = moon();
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => [1, 2, 3] });
		expect(placer.place(body, JD)).toEqual([1, 2, 3]);
	});

	it('has no place before its discovery, whatever the ephemeris holds', () => {
		const body = moon();
		body.data.visibleFromDays = JD - J2000_JD + 1;
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => [1, 2, 3] });
		expect(placer.place(body, JD)).toBeNull();
		expect(body.unplaced).toBe('not-yet');
	});

	it('waits for a chunk that is on its way', () => {
		const body = moon();
		const placer = placerOver([body], {
			ids: ['naif-301'],
			offset: () => null,
			coverage,
			loading: true
		});
		expect(placer.place(body, JD)).toBeNull();
		expect(body.unplaced).toBe('loading');
	});

	it('has no data inside its coverage when no chunk is on its way', () => {
		const body = moon();
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => null, coverage });
		expect(placer.place(body, JD)).toBeNull();
		expect(body.unplaced).toBe('no-data');
	});

	it('has no data outside the coverage of its zone, and the pass counts it', () => {
		const body = moon();
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => null, coverage });
		placer.begin(JD + 500, undefined, undefined);
		placer.placeInPass(body);
		expect(body.unplaced).toBe('no-data');
		expect(placer.noData).toEqual({
			count: 1,
			earliestStart: coverage.start,
			latestEnd: coverage.end
		});
	});

	it('is placed from its catalogue row where the ephemeris ends', () => {
		const body = mkBody({ id: 'spkid-1', parentId: 'naif-0', orbitalSource: OrbitalSource.SPICE });
		const row = mkBody({ id: 'spkid-1', parentId: 'naif-0' });
		const placer = placerOver([body], {
			ids: ['spkid-1'],
			offset: () => null,
			coverage,
			rows: new Map([['spkid-1', row.data]])
		});
		expect(placer.place(body, JD)).not.toBeNull();
		expect(body.unplaced).toBeUndefined();
	});
});

/** A load ends by itself, so it is not a loss of place: the reason passes down
 *  to everything placed from the body that waits. */
describe('a body whose data is on its way', () => {
	const waiting = { ids: ['bary'], offset: () => null, loading: true };
	const bary = () => mkBody({ id: 'bary', parentId: 'naif-0', objectType: ObjectType.BARYCENTER });

	it('makes the bodies placed from it wait too', () => {
		const moon = mkBody({ id: 'moon', parentId: 'bary', objectType: ObjectType.MOON });
		const lander = mkBody({ id: 'lander', parentId: 'moon' });
		const placer = placerOver([bary(), moon, lander], waiting);
		expect(placer.place(lander, JD)).toBeNull();
		expect(moon.unplaced).toBe('loading');
		expect(lander.unplaced).toBe('loading');
	});

	it('leaves a body under a parent with no data without a place for that reason', () => {
		const moon = mkBody({ id: 'moon', parentId: 'bary' });
		const placer = placerOver([bary(), moon], { ...waiting, loading: false });
		expect(placer.place(moon, JD)).toBeNull();
		expect(moon.unplaced).toBe('parent');
	});

	it('makes a probe wait while a probe chunk for the date is on its way', () => {
		const craft = () =>
			mkBody({ id: 'probe-1', parentId: 'naif-0', orbitalSource: OrbitalSource.SPICE_PROBE });
		const loading = craft();
		placerOver([loading], undefined, probeStoreWith(true)).place(loading, JD);
		expect(loading.unplaced).toBe('loading');
		const absent = craft();
		placerOver([absent], undefined, probeStoreWith(false)).place(absent, JD);
		expect(absent.unplaced).toBe('no-data');
	});
});
