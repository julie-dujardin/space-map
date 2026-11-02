import { describe, expect, it } from 'vitest';
import type { PairOrbit, SystemMember, SystemNode } from '$lib/fetch/extrasolar/systems';
import { ExtrasolarLookup } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
import { loadSystemNodes } from '$lib/fetch/extrasolar/systems';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { GM_SUN_KM3_S2 } from '$lib/math/travel/constants';
import type { Vec3 } from '$lib/scene/animation/math';
import type { OrbitalElements } from '$lib/types/objects';
import {
	barycentreOf,
	carryingOrbits,
	drawnPairs,
	framedPair,
	haloCarrier,
	listedMass,
	memberMu,
	nodePlace,
	pairElements,
	pairLight,
	placeNodes,
	splitLight,
	starsShare
} from './pair-orbits';

const YEAR = 365.25;

function orbit(fields: Partial<PairOrbit> = {}): PairOrbit {
	return {
		a: 2,
		e: 0.3,
		i: 40,
		om: 70,
		w: 110,
		ma: 25,
		n: 8,
		epoch: 2455000,
		period: 45,
		barycentre: 0.25,
		centre: 'barycentre',
		...fields
	} as PairOrbit;
}

function member(id: number | null, kind: SystemMember['kind'] = 'star'): SystemMember {
	return { id, kind } as SystemMember;
}

function node(id: number, fields: Partial<SystemNode> = {}): SystemNode {
	return {
		id,
		point: false,
		depth: 0,
		primary: null,
		orbit: null,
		members: [],
		...fields
	} as SystemNode;
}

const byId = (...nodes: SystemNode[]) => new Map(nodes.map((n) => [n.id, n]));

function at(elements: OrbitalElements, jd: number): Vec3 {
	return orbitalElementsToPositionJD(elements, jd)!;
}

describe('pairElements', () => {
	const expectPlaces = (o: PairOrbit, jd: number): void => {
		const [first, second] = pairElements(o);
		const r = at({ ...o }, jd);
		const f = o.barycentre;
		at(second, jd).forEach((v, k) => expect(v).toBeCloseTo((1 - f) * r[k], 9));
		if (f > 0) at(first, jd).forEach((v, k) => expect(v).toBeCloseTo(-f * r[k], 9));
		else expect(first.a).toBe(0);
	};

	it('puts the two members opposite each other, by the mass ratio', () => {
		for (const jd of [2455000, 2455011.3, 2460123.7]) expectPlaces(orbit(), jd);
	});

	it('keeps the first member on the centre with no mass ratio', () => {
		expectPlaces(orbit({ barycentre: 0, centre: 'primary' }), 2455011.3);
	});

	it('adds the orbits of a nested pair to the outer one', () => {
		const outer = orbit({ a: 40, n: 0.1, barycentre: 0.2 });
		const inner = orbit({ a: 0.5, n: 30, barycentre: 0.4 });
		const jd = 2455123;
		const [, ofInner] = pairElements(outer);
		const [ofStar] = pairElements(inner);
		const r = at({ ...outer }, jd);
		const ri = at({ ...inner }, jd);
		const star = at(ofInner, jd).map((v, k) => v + at(ofStar, jd)[k]);
		star.forEach((v, k) => expect(v).toBeCloseTo(0.8 * r[k] - 0.4 * ri[k], 8));
	});
});

describe('barycentreOf', () => {
	it('weighs the two places by the share of the second', () => {
		expect(barycentreOf([10, 0, 0], [0, 10, 0], 0.25)).toEqual([7.5, 2.5, 0]);
		expect(barycentreOf([1, 2, 3], [4, 8, 12], 0)).toEqual([1, 2, 3]);
	});

	it('takes the distance of the first, whatever the parallax of the second', () => {
		expect(barycentreOf([10, 0, 0], [0, 200, 0], 0.5)).toEqual([5, 5, 0]);
	});
});

describe('the orbits that carry a star', () => {
	const pair = (id: number, first: number, second: number, point = false) => ({
		node: { id, point } as SystemNode,
		orbit: orbit({ barycentre: 0.25 }),
		first,
		second
	});
	// A hierarchical triple: 3 and 4 turn about 2, and 2 and 5 about the root.
	const PAIRS = [pair(1, 2, 5), pair(2, 3, 4)];

	it('runs from the star out to the root, innermost first', () => {
		const { orbits, top } = carryingOrbits(4, PAIRS);
		const [outer] = pairElements(PAIRS[0].orbit);
		expect(orbits).toEqual([pairElements(PAIRS[1].orbit)[1], outer]);
		expect(top).toBe(PAIRS[0]);
	});

	it('is empty for a star on no drawn orbit', () => {
		expect(carryingOrbits(9, PAIRS)).toEqual({ orbits: [], top: null });
	});

	it('places a resolved pair at the barycentre of its members', () => {
		const scene = new Map<number, Vec3>([
			[3, [10, 0, 0]],
			[4, [10, 0, 4]],
			[5, [10, 8, 0]]
		]);
		const place = nodePlace(1, PAIRS, (id) => scene.get(id) ?? null)!;
		const inner = barycentreOf([10, 0, 0], [10, 0, 4], 0.25);
		expect(place).toEqual(barycentreOf(inner, [10, 8, 0], 0.25));
	});

	it('takes the place of a node with its own point', () => {
		const at: Vec3 = [1, 2, 3];
		expect(nodePlace(1, [pair(1, 2, 5, true)], () => at)).toEqual(at);
	});

	it('reads only the nodes under a pair for its place', () => {
		expect(placeNodes(1, [...PAIRS, pair(6, 7, 8)])).toEqual([1, 2, 3, 4, 5]);
		expect(placeNodes(5, PAIRS)).toEqual([5]);
	});

	it('stops at a node with its own point', () => {
		expect(placeNodes(1, [pair(1, 2, 5), pair(2, 3, 4, true)])).toEqual([1, 2, 5]);
	});
});

describe('listedMass', () => {
	const star = (mass: number | null) => ({ star: { mass } }) as Partial<SystemNode>;
	const listed = { ...member(2), mass: 1.5 };

	it('reads the values of a held star first, as a pair weighs its light', () => {
		const nodes = byId(node(1, { members: [listed] }), node(2, star(1.7)));
		expect(listedMass(2, nodes)).toBe(1.7);
	});

	it('reads the row of the member when the held star lists no mass', () => {
		expect(listedMass(2, byId(node(1, { members: [listed] }), node(2, star(null))))).toBe(1.5);
	});

	it('gives nothing for a star the tables do not weigh', () => {
		expect(listedMass(2, byId(node(1, { members: [member(2)] })))).toBeNull();
		expect(listedMass(9, byId(node(1, { members: [listed] })))).toBeNull();
	});
});

describe('memberMu', () => {
	const PAIR = (barycentre: number) => ({
		node: { id: 1 } as SystemNode,
		orbit: orbit({ a: 20, n: 360 / (50 * YEAR), barycentre }),
		first: 2,
		second: 3
	});
	// 20 au in 50 years: 3.2 solar masses by Kepler's third law.
	const SUM = 20 ** 3 / 50 ** 2;
	const solar = (id: number, barycentre: number) =>
		memberMu(id, [PAIR(barycentre)])! / GM_SUN_KM3_S2;

	it('splits the sum of Kepler by the barycentre', () => {
		expect(solar(2, 0.25) / (0.75 * SUM)).toBeCloseTo(1, 3);
		expect(solar(3, 0.25) / (0.25 * SUM)).toBeCloseTo(1, 3);
	});

	it('gives nothing for a pair with no mass ratio', () => {
		expect(memberMu(2, [PAIR(0)])).toBeNull();
		expect(memberMu(3, [PAIR(0)])).toBeNull();
	});

	it('gives nothing for an ID in no pair', () => {
		expect(memberMu(9, [PAIR(0.25)])).toBeNull();
	});
});

describe('drawnPairs', () => {
	it('gives the outermost pair first, with its members', () => {
		const inner = node(2, {
			depth: 1,
			point: true,
			orbit: orbit({ a: 1 }),
			members: [member(5, 'held star'), member(6, 'held star')]
		});
		const root = node(1, { orbit: orbit(), members: [member(2, 'system'), member(3)] });
		const pairs = drawnPairs(byId(inner, root));
		expect(pairs.map((p) => [p.node.id, p.first, p.second])).toEqual([
			[1, 2, 3],
			[2, 5, 6]
		]);
	});

	it('leaves out a pair with an entry', () => {
		const pair = node(1, { orbit: orbit(), members: [member(3), member(null, 'entry')] });
		expect(drawnPairs(byId(pair))).toEqual([]);
	});

	it('leaves out a flat list and a node with no orbit', () => {
		const three = node(1, { orbit: orbit(), members: [member(3), member(4), member(5)] });
		expect(drawnPairs(byId(three, node(2, { members: [member(6), member(7)] })))).toEqual([]);
	});

	it('takes a point with no orbit as a member, but no resolved node', () => {
		const point = node(2, { point: true, members: [member(5, 'held star')] });
		const resolved = node(4, { members: [member(7), member(8)] });
		const withPoint = node(1, { orbit: orbit(), members: [member(2, 'system'), member(3)] });
		const withResolved = node(6, { orbit: orbit(), members: [member(4, 'system'), member(3)] });
		const pairs = drawnPairs(byId(point, resolved, withPoint, withResolved));
		expect(pairs.map((p) => p.node.id)).toEqual([1]);
	});

	it('leaves a pair of over 100,000 years at its catalogue places', () => {
		const wide = orbit({ period: 2e5 * YEAR });
		const inner = node(2, { depth: 1, orbit: orbit(), members: [member(5), member(6)] });
		const root = node(1, { orbit: wide, members: [member(2, 'system'), member(3)] });
		expect(drawnPairs(byId(root, inner)).map((p) => p.node.id)).toEqual([2]);
	});
});

describe('framedPair', () => {
	const pairNode = node(2, {
		depth: 1,
		primary: 5,
		orbit: orbit(),
		members: [member(5), member(6)]
	});
	const other = node(3, {
		depth: 1,
		primary: 7,
		orbit: orbit({ a: 90 }),
		members: [member(7), member(8)]
	});
	const root = node(1, { primary: 5, members: [member(3, 'system'), member(2, 'system')] });
	const nodes = byId(root, pairNode, other);
	const pairs = drawnPairs(nodes);

	it('frames a node with a pair of its own by that pair', () => {
		expect(framedPair(3, nodes, pairs)?.node.id).toBe(3);
	});

	it('goes down through the primary, past a wider sibling', () => {
		expect(framedPair(1, nodes, pairs)?.node.id).toBe(2);
	});

	it('frames nothing for a star', () => {
		expect(framedPair(5, nodes, pairs)).toBeNull();
		expect(framedPair(404, nodes, pairs)).toBeNull();
	});
});

describe('haloCarrier', () => {
	const pair = (id: number, barycentre: number, first = 5, second = 6): SystemNode =>
		node(id, {
			depth: 1,
			primary: first,
			orbit: orbit({ barycentre }),
			members: [member(first), member(second)]
		});
	const carrier = (id: number, ...all: SystemNode[]): number => {
		const nodes = byId(...all);
		return haloCarrier(id, nodes, drawnPairs(nodes));
	};

	it('leaves the halo of a pair with a barycentre on the pair', () => {
		expect(carrier(2, pair(2, 0.25))).toBe(2);
	});

	it('gives the halo of a pair to the star on its barycentre', () => {
		expect(carrier(2, pair(2, 0))).toBe(5);
	});

	it('gives the halo of a root to the star of the pair it frames', () => {
		const root = node(1, { primary: 5, members: [member(2, 'system'), member(7)] });
		expect(carrier(1, root, pair(2, 0))).toBe(5);
		expect(carrier(1, root, pair(2, 0.25))).toBe(1);
	});

	it('goes on down through a pair on the barycentre', () => {
		const inner = pair(2, 0);
		const outer = node(1, {
			primary: 5,
			orbit: orbit({ barycentre: 0 }),
			members: [member(2, 'system'), member(7)]
		});
		expect(carrier(1, outer, inner)).toBe(5);
	});

	it('stops at a pair with a barycentre under one with none', () => {
		const inner = pair(2, 0.25);
		const outer = node(1, {
			primary: 5,
			orbit: orbit({ barycentre: 0 }),
			members: [member(2, 'system'), member(7)]
		});
		expect(carrier(1, outer, inner)).toBe(2);
	});

	it('gives a node with no drawn orbit to its primary, having no barycentre', () => {
		const wide = pair(2, 0);
		wide.orbit = orbit({ barycentre: 0, period: 2e5 * YEAR });
		expect(carrier(2, wide)).toBe(wide.primary);
	});

	it('leaves a star and an unknown ID', () => {
		expect(carrier(5, pair(2, 0))).toBe(5);
		expect(carrier(404, pair(2, 0))).toBe(404);
	});
});

describe('splitLight', () => {
	const sum = (a: number | null, b: number | null): number =>
		-2.5 * Math.log10(10 ** (-0.4 * a!) + 10 ** (-0.4 * b!));

	it('keeps the ratio of two magnitudes, and the light of the point', () => {
		const [a, b] = splitLight(1, [2, 3], [1, 1]);
		expect(sum(a, b)).toBeCloseTo(1, 9);
		expect(b! - a!).toBeCloseTo(1, 9);
	});

	it('shares by mass to the 3.5 with both masses', () => {
		const [a, b] = splitLight(5, [null, null], [1, 0.5]);
		expect(sum(a, b)).toBeCloseTo(5, 9);
		expect(b! - a!).toBeCloseTo(2.5 * 3.5 * Math.log10(2), 9);
	});

	it('prefers the masses to one magnitude', () => {
		const [a, b] = splitLight(5, [5.1, null], [1, 0.5]);
		expect(sum(a, b)).toBeCloseTo(5, 9);
		expect(b! - a!).toBeCloseTo(2.5 * 3.5 * Math.log10(2), 9);
	});

	it('leaves the rest of the light to the other star, with no masses', () => {
		const [a, b] = splitLight(5, [null, 6], [1, null]);
		expect(b).toBe(6);
		expect(sum(a, b)).toBeCloseTo(5, 9);
	});

	it('shares equally when one star is said to be brighter than the point', () => {
		const [a, b] = splitLight(5, [4, null], [null, null]);
		expect(a).toBeCloseTo(b!, 9);
		expect(sum(a, b)).toBeCloseTo(5, 9);
	});

	it('shares equally with nothing to go on', () => {
		const [a, b] = splitLight(5, [null, null], [null, null]);
		expect(a).toBeCloseTo(5 + 2.5 * Math.log10(2), 9);
		expect(b).toBeCloseTo(a!, 9);
	});

	it('leaves each star its own with no light in the point', () => {
		expect(splitLight(null, [4, null], [1, 1])).toEqual([4, null]);
	});
});

describe('starsShare', () => {
	it('gives the point alone up close on screen, and the stars alone apart', () => {
		expect(starsShare(0)).toBe(0);
		expect(starsShare(2)).toBe(0);
		expect(starsShare(6)).toBe(1);
		expect(starsShare(100)).toBe(1);
	});

	it('rises with no step', () => {
		let last = 0;
		for (let px = 2; px <= 6; px += 0.25) {
			const share = starsShare(px);
			expect(share).toBeGreaterThanOrEqual(last);
			expect(share - last).toBeLessThan(0.15);
			last = share;
		}
	});
});

describe('pairLight', () => {
	const held = (id: number) => member(id, 'held star');
	const drawn = (handed: number, ...all: SystemNode[]) =>
		drawnPairs(byId(...all)).map((pair) => ({ pair, handed }));

	it('gives a point and its stars one whole between them', () => {
		const point = node(1, { point: true, orbit: orbit(), members: [held(5), held(6)] });
		for (const handed of [0, 0.2, 0.5, 1]) {
			const light = pairLight(drawn(handed, point));
			expect(light.get(1)).toBeCloseTo(1 - handed, 12);
			expect(light.get(5)).toBeCloseTo(handed, 12);
			expect(light.get(6)).toBeCloseTo(handed, 12);
		}
	});

	it('leaves the members of a resolved pair their whole light', () => {
		const pair = node(1, { orbit: orbit(), members: [member(5), member(6)] });
		const light = pairLight(drawn(0, pair));
		expect(light.get(5)).toBe(1);
		expect(light.get(6)).toBe(1);
	});

	it('gives the stars of a resolved pair inside a point the share of the point', () => {
		const inner = node(2, { depth: 1, orbit: orbit(), members: [held(7), held(8)] });
		const point = node(1, {
			point: true,
			orbit: orbit(),
			members: [held(5), member(2, 'system')]
		});
		for (const handed of [0, 0.3, 1]) {
			const light = pairLight(drawn(handed, point, inner));
			expect(light.get(1)).toBeCloseTo(1 - handed, 12);
			for (const star of [5, 7, 8]) expect(light.get(star)).toBeCloseTo(handed, 12);
		}
	});

	it('hands a point inside a resolved pair over by its own share', () => {
		const inner = node(2, {
			depth: 1,
			point: true,
			orbit: orbit(),
			members: [held(7), held(8)]
		});
		const root = node(1, { orbit: orbit(), members: [member(2, 'system'), member(5)] });
		const light = pairLight(drawn(0.25, root, inner));
		expect(light.get(5)).toBe(1);
		expect(light.get(2)).toBeCloseTo(0.75, 12);
		expect(light.get(7)).toBeCloseTo(0.25, 12);
	});

	it('hands a point inside a point over by both shares', () => {
		const inner = node(2, {
			depth: 1,
			point: true,
			orbit: orbit(),
			members: [held(7), held(8)]
		});
		const outer = node(1, {
			point: true,
			orbit: orbit(),
			members: [held(5), member(2, 'system')]
		});
		const light = pairLight(drawn(0.5, outer, inner));
		expect(light.get(1)).toBeCloseTo(0.5, 12);
		expect(light.get(5)).toBeCloseTo(0.5, 12);
		expect(light.get(2)).toBeCloseTo(0.25, 12);
		expect(light.get(7)).toBeCloseTo(0.25, 12);
	});
});

describe.skipIf(!HAS_EXPORT)('real pairs', () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const nodesOf = async (root: number) =>
		new Map((await loadSystemNodes(root, lookup)).map((n) => [n.id, n]));

	it('draws the two held stars of Kepler-16 about its point', async () => {
		const pairs = drawnPairs(await nodesOf(20657986));
		expect(pairs.map((p) => [p.node.id, p.first, p.second])).toEqual([
			[20657986, 1127954242, 591083330]
		]);
		expect(pairs[0].orbit.period).toBeCloseTo(41.08, 1);
	});

	it('draws A and B of Alpha Centauri, and leaves Proxima where it is', async () => {
		const nodes = await nodesOf(597894079);
		const pairs = drawnPairs(nodes);
		expect(pairs.map((p) => p.node.id)).toEqual([61023167]);
		expect(framedPair(597894079, nodes, pairs)?.node.id).toBe(61023167);
	});

	it('weighs Rigil Kentaurus and Sirius A from their orbits', async () => {
		const solar = async (root: number, id: number) =>
			memberMu(id, drawnPairs(await nodesOf(root)))! / GM_SUN_KM3_S2;
		// Pourbaix & Boffin 2016, A&A 586, A90: 1.133 ± 0.005. The ratio is the MSC's.
		expect(await solar(597894079, 27468735)).toBeCloseTo(1.139, 3);
		// Bond et al. 2017, ApJ 840, 70: 2.063 ± 0.023.
		expect(await solar(55692301, 22137869)).toBeCloseTo(2.058, 3);
	});

	it('lists the mass of Sirius A in its tables', async () => {
		expect(listedMass(22137869, await nodesOf(55692301))).toBeCloseTo(2.063, 5);
	});

	it('nests the three pairs of Castor under its root', async () => {
		const pairs = drawnPairs(await nodesOf(588825732));
		expect(pairs.map((p) => p.node.id)).toEqual([51954820, 18400388, 555271300]);
	});

	it('lets Procyon A carry the halo of Procyon, and leaves Kepler-16 its own', async () => {
		const procyon = await nodesOf(56040586);
		const pairs = drawnPairs(procyon);
		expect(pairs[0].orbit.barycentre).toBe(0);
		expect(haloCarrier(56040586, procyon, pairs)).toBe(pairs[0].first);
		const kepler = await nodesOf(20657986);
		expect(haloCarrier(20657986, kepler, drawnPairs(kepler))).toBe(20657986);
	});
});
