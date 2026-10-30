import { describe, expect, it } from 'vitest';
import { Container } from './container';
import { ExtrasolarLookup, type ExtrasolarRecord, type LookupSource } from './lookup';
import { HAS_EXPORT, diskSource, own } from './__fixtures__/export';
import { resolvedSystemRecord } from './__fixtures__/record';
import { BINARY, HELD, SECOND, STAR, SYSTEM, syntheticExport } from './__fixtures__/synthetic';
import {
	loadSystemPoints,
	pointOf,
	systemNode,
	systemPointIds,
	systemRoot,
	type SystemNode
} from './systems';

function syntheticLookup(): ExtrasolarLookup {
	const { meta, payloads } = syntheticExport();
	const files = Object.fromEntries(
		Object.entries(payloads).map(([path, payload]) => [path, new Container(own(payload))])
	);
	const source: LookupSource = {
		metadata: async () => meta,
		file: async (path) => files[path],
		allowed: () => true
	};
	return new ExtrasolarLookup(source);
}

async function record(lookup: ExtrasolarLookup, id: number): Promise<ExtrasolarRecord> {
	const result = await lookup.lookup(id);
	if (result.kind !== 'live') throw new Error(`${id} is not live`);
	return result.record;
}

async function node(lookup: ExtrasolarLookup, id: number): Promise<SystemNode> {
	const read = systemNode(await record(lookup, id));
	if (!read) throw new Error(`${id} has no System row`);
	return read;
}

describe('the System row', () => {
	it('reads the fields of a node', async () => {
		const root = await node(syntheticLookup(), SYSTEM);
		expect(root).toMatchObject({
			id: SYSTEM,
			point: false,
			depth: 0,
			stars: 3,
			ra: 45,
			dec: 30,
			label: 'AB',
			spectralType: 'G2V+K1V',
			evidence: null,
			sources: ['msc', 'wds'],
			treeSource: 'star-systems',
			parent: null,
			root: SYSTEM,
			primary: BINARY,
			distance: 100,
			star: null
		});
	});

	it('reads the whole tree of a root, and none on another row', async () => {
		const lookup = syntheticLookup();
		const { tree } = await node(lookup, SYSTEM);
		expect(tree).toEqual([
			{ id: SYSTEM, parent: null, point: false, stars: 3, label: 'AB', class: 'multiple star' },
			{ id: HELD, parent: BINARY, point: false, stars: 1, label: 'Aa', class: 'star' },
			{ id: BINARY, parent: SYSTEM, point: true, stars: 2, label: null, class: 'binary star' }
		]);
		expect((await node(lookup, BINARY)).tree).toBeNull();
	});

	it('reads every member field, with the lists of each member', async () => {
		const lookup = syntheticLookup();
		const [first, second] = (await node(lookup, SYSTEM)).members;
		expect(first).toMatchObject({ id: BINARY, kind: 'system', letter: 'A', vMag: 1.5, known: [] });
		expect(second).toEqual({
			id: SECOND,
			kind: 'star',
			letter: 'B',
			inner: null,
			label: 'Second',
			source: 'msc',
			spectralType: 'K1V',
			vMag: null,
			gMag: 2.5,
			mass: 0.5,
			separation: 17.5,
			positionAngle: 90,
			period: 29000,
			eccentricity: 0.5,
			semiMajorAxis: 17.5,
			known: ['visual', 'visual orbit'],
			ids: []
		});
		const [held, entry] = (await node(lookup, BINARY)).members;
		expect(held).toMatchObject({ id: HELD, kind: 'held star', known: ['spectroscopic'] });
		expect(entry).toMatchObject({
			id: null,
			kind: 'entry',
			inner: 'b',
			mass: 0.25,
			ids: [{ catalogue: 'gaia', release: 'dr3', catalogueId: '43' }]
		});
	});

	it('reads the orbit of a pair, its lists included', async () => {
		const lookup = syntheticLookup();
		const { orbit } = await node(lookup, SYSTEM);
		expect(orbit).toEqual({
			a: 23.5,
			e: 0.5,
			i: 80,
			om: 200,
			w: 230,
			ma: 10,
			n: 0.01,
			epoch: 2451545,
			phase: 'periastron',
			period: 29000,
			semiMajorAxis: 23.5,
			semiMajorAxisArcsec: null,
			eccentricity: 0.5,
			inclination: 79,
			node: 205,
			nodeAscending: false,
			argPeriastron: 231,
			periastronTime: 2435000,
			barycentre: 0.45,
			centre: 'barycentre',
			massRatioSource: 'literature',
			periodSource: 'orb6',
			semiMajorAxisSource: 'gaia-dr3-orbits',
			eccentricitySource: 'orb6',
			inclinationSource: 'orb6',
			nodeSource: null,
			argPeriastronSource: 'orb6',
			epochSource: 'orb6',
			assumed: ['node'],
			computed: ['semi_major_axis'],
			references: [
				{ source: 'orb6', reference: 'Msn2023', short: null, title: null, url: null },
				{
					source: 'literature',
					reference: 'doyle2011',
					short: 'Doyle et al. 2011',
					title: 'A title',
					url: 'https://example.org/'
				}
			]
		});
		expect((await node(lookup, BINARY)).orbit).toBeNull();
	});

	it('reads the values of a held star', async () => {
		const lookup = syntheticLookup();
		const held = await node(lookup, HELD);
		expect(held).toMatchObject({ primary: null, parent: BINARY, stars: 1, members: [] });
		expect(held.star).toEqual({
			mass: 0.5,
			radius: null,
			teff: 4500,
			spectralType: 'K1V',
			massSource: 'literature',
			radiusSource: null,
			teffSource: 'open-exoplanet-catalogue',
			spectralTypeSource: 'msc',
			references: [
				{
					source: 'literature',
					reference: 'doyle2011',
					short: 'Doyle et al. 2011',
					title: 'A title',
					url: 'https://example.org/'
				}
			]
		});
		expect((await node(lookup, SYSTEM)).star).toBeNull();
	});

	it('has no System row on a star', async () => {
		expect(systemNode(await record(syntheticLookup(), SECOND))).toBeNull();
	});
});

describe('the system of an ID', () => {
	it('finds the root from a root, a node, a star and a held star', async () => {
		const lookup = syntheticLookup();
		for (const id of [SYSTEM, BINARY, SECOND, HELD]) {
			expect(systemRoot(await record(lookup, id))).toBe(SYSTEM);
		}
		expect(systemRoot(await record(lookup, STAR))).toBeNull();
	});

	it('finds the point of a star, a node, a point and a held star', async () => {
		const lookup = syntheticLookup();
		expect(pointOf(await record(lookup, SECOND))).toBe(SECOND);
		expect(pointOf(await record(lookup, SYSTEM))).toBe(BINARY);
		expect(pointOf(await record(lookup, BINARY))).toBe(BINARY);
		expect(pointOf(await record(lookup, HELD))).toBe(BINARY);
		expect(pointOf(resolvedSystemRecord(7, 3))).toBe(3);
	});

	it('lists the points and the member stars, with no held star or entry', async () => {
		expect(await loadSystemPoints(SYSTEM, syntheticLookup())).toEqual([BINARY, SECOND]);
	});

	it('lists a star once, and no member with no ID', () => {
		const tree = [{ id: 1, parent: null, point: true, stars: 2, label: null, class: null }];
		const members = [
			{ id: 1, kind: 'star' },
			{ id: 2, kind: 'star' },
			{ id: null, kind: 'star' },
			{ id: 3, kind: 'system' }
		];
		expect(systemPointIds(tree, [{ members } as unknown as SystemNode])).toEqual([1, 2]);
	});

	it('lists nothing for an ID that is not live', async () => {
		const missing = { live: async () => ({ kind: 'missing', reason: 'barred' }) as const };
		expect(await loadSystemPoints(SYSTEM, missing)).toEqual([]);
	});
});

describe.skipIf(!HAS_EXPORT)('real star systems', () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const RIGIL_KENTAURUS = 27468735;
	const TOLIMAN = 564339647;
	const PROXIMA = 27424668;

	it('reads Alpha Centauri, its pair and its stars', async () => {
		const root = await node(lookup, 597894079);
		expect(root.members.map((m) => [m.id, m.kind])).toEqual([
			[61023167, 'system'],
			[PROXIMA, 'star']
		]);
		expect(root.tree?.map((n) => n.id).sort()).toEqual([597894079, 61023167].sort());
		const ids = await loadSystemPoints(597894079, lookup);
		expect(ids.sort()).toEqual([RIGIL_KENTAURUS, TOLIMAN, PROXIMA].sort());
		expect((await node(lookup, 61023167)).orbit?.period).toBeGreaterThan(29000);
	});

	it('lists a point with its held stars once, as a point', async () => {
		expect(await loadSystemPoints(20657986, lookup)).toEqual([20657986]);
		const held = await node(lookup, 591083330);
		expect(held.parent).toBe(20657986);
		expect(held.star).not.toBeNull();
	});

	it('lists the three points of Castor', async () => {
		const ids = await loadSystemPoints(588825732, lookup);
		expect(ids.sort()).toEqual([18400388, 555271300, 1092142212].sort());
	});
});
