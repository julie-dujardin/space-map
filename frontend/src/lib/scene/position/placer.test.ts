import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { J2000_JD, jdToEt } from '$lib/time/jd';
import type { Probe } from '$lib/fetch/position/probes/parse';
import { PositionDiagnostics } from './diagnostics';
import { makeFeatureBody } from '$lib/scene/focus/feature-focus';
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
	/** Each body's kernel spans; one span over the zone for a body not listed. */
	spans?: Record<string, [number, number][]>;
	/** The zone's span. */
	zone?: { start: number; end: number };
	/** A chunk for the date is on its way. */
	loading?: boolean;
	/** Catalogue rows of the bodies that have one. */
	rows?: Map<string, BodyData>;
}

/** A probe store with no chunk for the date, and one on its way or not. */
const probeStoreWith = (loading: boolean) => ({
	ridesAt: () => [],
	probeWithCenter: () => null,
	awaitedAt: () => loading
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
					coverage: (id: string) =>
						cheb.spans?.[id] ?? (cheb.zone ? [[cheb.zone.start, cheb.zone.end]] : undefined),
					zoneCoverage: () => cheb.zone,
					isAwaited: () => cheb.loading ?? false
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

	it('gives no place at any date to a body under one that has none at any date', () => {
		const page = mkBody({ id: 'page', parentId: 'naif-0', pageOnly: true, a: NaN });
		const moon = mkBody({ id: 'moon', parentId: 'page' });
		expect(placerFor(page, moon).place(moon, JD)).toBeNull();
		expect(moon.unplaced).toBe('never');
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
		mkBody({
			id: 'naif-301',
			parentId: 'naif-0',
			objectType: ObjectType.MOON,
			orbitalSource: OrbitalSource.SPICE
		});
	const zone = { start: JD - 100, end: JD + 100 };

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
			zone,
			loading: true
		});
		expect(placer.place(body, JD)).toBeNull();
		expect(body.unplaced).toBe('loading');
	});

	it('has no data inside its coverage when no chunk is on its way', () => {
		const body = moon();
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => null, zone });
		expect(placer.place(body, JD)).toBeNull();
		expect(body.unplaced).toBe('no-data');
		expect(placer.noData.count).toBe(0);
	});

	it('has no data past the end of the ephemeris, and the pass says so', () => {
		const body = moon();
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => null, zone });
		placer.begin(JD + 500, undefined, undefined);
		placer.placeInPass(body);
		expect(body.unplaced).toBe('no-data');
		expect(placer.noData.count).toBe(1);
		expect(placer.noData.sides[0]).toBe('after');
		expect(placer.noData.edges[0]).toBe(zone.end);
		expect(placer.noData.ephemerisEdges[0]).toBe(true);
	});

	it('names a body past its own kernels while the ephemeris goes on', () => {
		const body = moon();
		body.data.name = 'Moon';
		const placer = placerOver([body], {
			ids: ['naif-301'],
			offset: () => null,
			zone,
			spans: { 'naif-301': [[JD - 100, JD - 50]] },
			// Its chunk for the date is on its way, and holds nothing of it.
			loading: true
		});
		placer.begin(JD, undefined, undefined);
		placer.placeInPass(body);
		expect(body.unplaced).toBe('no-data');
		expect(placer.noData.names.slice(0, placer.noData.count)).toEqual(['Moon']);
		expect(placer.noData.edges[0]).toBe(JD - 50);
		expect(placer.noData.ephemerisEdges[0]).toBe(false);
	});

	it('is in a hole between two spans', () => {
		const body = moon();
		const placer = placerOver([body], {
			ids: ['naif-301'],
			offset: () => null,
			zone,
			spans: {
				'naif-301': [
					[JD - 100, JD - 10],
					[JD + 10, JD + 100]
				]
			}
		});
		placer.begin(JD, undefined, undefined);
		placer.placeInPass(body);
		expect(placer.noData.sides[0]).toBe('outside');
	});

	it('says nothing of a body before its discovery, out of its kernels or not', () => {
		const body = moon();
		body.data.visibleFromDays = JD + 1000 - J2000_JD;
		const placer = placerOver([body], { ids: ['naif-301'], offset: () => null, zone });
		placer.begin(JD + 500, undefined, undefined);
		placer.placeInPass(body);
		expect(body.unplaced).toBe('not-yet');
		expect(placer.noData.count).toBe(0);
	});

	it('leaves a body that is not a planet or a moon out of the notice', () => {
		const rock = mkBody({ id: 'spkid-2', parentId: 'naif-0', orbitalSource: OrbitalSource.SPICE });
		const placer = placerOver([rock], { ids: ['spkid-2'], offset: () => null, zone });
		placer.begin(JD + 500, undefined, undefined);
		placer.placeInPass(rock);
		expect(rock.unplaced).toBe('no-data');
		expect(placer.noData.count).toBe(0);
	});

	it('is placed from its catalogue row where the ephemeris ends', () => {
		const body = mkBody({ id: 'spkid-1', parentId: 'naif-0', orbitalSource: OrbitalSource.SPICE });
		const row = mkBody({ id: 'spkid-1', parentId: 'naif-0' });
		const placer = placerOver([body], {
			ids: ['spkid-1'],
			offset: () => null,
			zone,
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

/** A lander is placed from the spin of the body it stands on. */
describe('a lander', () => {
	const SPIN = {
		pole_ra_0: 317,
		pole_ra_1: 0,
		pole_dec_0: 54,
		pole_dec_1: 0,
		w0: 176,
		w1: 350,
		w2: 0
	};
	const landedProbe = {
		subEndEt: new Float64Array(0),
		landed: {
			bodyNaifId: 499,
			isStatic: true,
			isDestroyed: false,
			startEt: jdToEt(JD - 1),
			endEt: jdToEt(JD + 1),
			latRefDeg: -4.6,
			lngRefDeg: 137.4,
			altRefM: 0,
			sampleEt: new Float64Array(0),
			sampleLatDeg: new Float32Array(0),
			sampleLngDeg: new Float32Array(0),
			sampleAltM: new Float32Array(0)
		}
	} as unknown as Probe;

	function scene() {
		const mars = mkBody({ id: 'naif-499', parentId: 'naif-0', radiusKm: 3389.5 });
		const lander = mkBody({
			id: 'probe-1',
			parentId: 'naif-0',
			orbitalSource: OrbitalSource.SPICE_PROBE
		});
		const byId = new Map([mars, lander].map((b) => [b.data.id, b]));
		const ctx = {
			getBody: (id: string) => byId.get(id),
			bodies: { bodiesById: byId, elementRow: (b: PositionedBody) => b.data },
			chebStore: null,
			probeStore: {
				ridesAt: () => [],
				probeWithCenter: () => ({ probe: landedProbe, fitCenterNaifId: 499 }),
				awaitedAt: () => false
			},
			visibility: { activeSystemId: null }
		} as unknown as ContextManager;
		return { mars, lander, placer: new Placer(ctx, new Map(), new PositionDiagnostics()) };
	}

	it('has no place on a body with no spin', () => {
		const { lander, placer } = scene();
		expect(placer.place(lander, JD)).toBeNull();
		expect(lander.unplaced).toBe('parent');
	});

	it('stands on the body once its spin is read', () => {
		const { mars, lander, placer } = scene();
		mars.orientation = SPIN;
		const pos = placer.place(lander, JD);
		expect(pos).not.toBeNull();
		expect(lander.data.parentId).toBe('naif-499');
	});
});

describe('a star on a drawn orbit', () => {
	const star = (data: Partial<BodyData> & Pick<BodyData, 'id' | 'parentId'>): PositionedBody => ({
		...mkBody({ objectType: ObjectType.EXTRASOLAR, ...data }),
		extrasolar: { scene: [100, 0, 0] } as PositionedBody['extrasolar']
	});

	it('stays at its record with no parent', () => {
		const alone = star({ id: 'x-1', parentId: '' });
		expect(placerOver([alone]).place(alone, JD)).toEqual([100, 0, 0]);
	});

	it('moves about the body of its pair, through a nested pair', () => {
		const pair = star({ id: 'x-1', parentId: '' });
		const inner = star({ id: 'x-2', parentId: 'x-1', a: 2 });
		const moving = star({ id: 'x-3', parentId: 'x-2', a: 0.1, n: 30 });
		const placer = placerOver([pair, inner, moving]);
		const at = [...placer.place(moving, JD)!];
		const parent = placer.place(inner, JD)!;
		expect(parent[0]).not.toBe(100);
		const offset = Math.hypot(at[0] - parent[0], at[1] - parent[1], at[2] - parent[2]);
		expect(offset).toBeGreaterThan(0.9);
		expect(offset).toBeLessThan(1.3);
		expect(placer.place(moving, JD + 1)).not.toEqual(at);
	});

	it('sits on the barycentre when its pair has no mass ratio', () => {
		const pair = star({ id: 'x-1', parentId: '' });
		const primary = star({ id: 'x-2', parentId: 'x-1', a: 0 });
		expect(placerOver([pair, primary]).place(primary, JD)).toEqual([100, 0, 0]);
	});

	it('has no place when its pair has none', () => {
		const orphan = star({ id: 'x-2', parentId: 'x-1' });
		expect(placerOver([orphan]).place(orphan, JD)).toBeNull();
	});
});

describe('a surface feature focused again', () => {
	const anchor = { hostId: 'naif-499', featureId: 2757, lat: -7, lon: 275, diameterM: 1e5 };

	it('places a new body under the id of one placed in the same pass', () => {
		const host = mkBody({ id: 'naif-499', parentId: 'naif-0', radiusKm: 3389 });
		const placer = placerOver([host]);
		placer.begin(JD, undefined, undefined);
		const first = placer.place(makeFeatureBody(anchor, null), JD);
		expect(first).not.toBeNull();
		const again = makeFeatureBody(anchor, 'Ius Chasma');
		expect(placer.place(again, JD)).toEqual(first);
		expect(again.position).toEqual(first);
	});
});
