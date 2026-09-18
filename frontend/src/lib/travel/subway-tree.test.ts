import { describe, expect, it } from 'vitest';
import { stationId, type SubwayMap } from '$lib/math/travel/subway';
import { buildTree } from './subway-tree';

/** A map from Earth with the Moon (bound), Jupiter with Europa hanging off
 *  its intercept, a Europa-only trip whose planet is not a target, and the
 *  stationary orbit — enough shapes to exercise the regrouping. */
function map(): SubwayMap {
	const E = 'naif-399';
	const s = (kind: Parameters<typeof stationId>[0], id: string) => stationId(kind, id);
	const path = (...ids: string[]) => ids;
	const edges = [
		[s('surface', E), s('orbit', E), 'ascent', 9.36, false],
		[s('orbit', E), s('escape', E), 'escape', 3.23, false],
		[s('orbit', E), s('transfer', 'naif-301'), 'depart', 3.13, false],
		[s('transfer', 'naif-301'), s('escape', 'naif-301'), 'arrive', 0.15, false],
		[s('escape', 'naif-301'), s('orbit', 'naif-301'), 'circularize', 0.66, false],
		[s('orbit', 'naif-301'), s('surface', 'naif-301'), 'landing', 1.89, false],
		[s('escape', E), s('transfer', 'naif-599'), 'depart', 3.08, false],
		[s('transfer', 'naif-599'), s('escape', 'naif-599'), 'arrive', 0.26, true],
		[s('escape', 'naif-599'), s('orbit', 'naif-599'), 'circularize', 17.6, true],
		[s('transfer', 'naif-599'), s('escape', 'naif-502'), 'arrive', 4.86, false],
		[s('escape', 'naif-502'), s('orbit', 'naif-502'), 'circularize', 0.56, false],
		[s('orbit', 'naif-502'), s('surface', 'naif-502'), 'landing', 1.61, false],
		[s('escape', E), s('transfer', 'naif-699'), 'depart', 4.06, false],
		[s('transfer', 'naif-699'), s('escape', 'naif-606'), 'arrive', 2.2, true],
		[s('escape', 'naif-606'), s('orbit', 'naif-606'), 'circularize', 0.75, true],
		[s('orbit', 'naif-606'), s('surface', 'naif-606'), 'landing', 2.13, true],
		[s('orbit', E), s('transfer', E), 'depart', 2.46, false],
		[s('transfer', E), s('stationary', E), 'circularize', 1.48, false]
	] as const;
	const stations = new Set<string>();
	for (const [from, to] of edges) {
		stations.add(from);
		stations.add(to);
	}
	const totals = { orbitKms: 1, surfaceKms: null, aeroOrbitKms: null, aeroSurfaceKms: null };
	return {
		originId: E,
		stations: [...stations].map((id) => {
			const [kind, bodyId] = id.split(':');
			return { id, kind: kind as never, bodyId };
		}),
		edges: edges.map(([from, to, kind, dvKms, aero]) => ({ from, to, kind, dvKms, via: [], aero })),
		routes: [
			{
				kind: 'stationary',
				targetId: E,
				path: path(s('surface', E), s('orbit', E), s('transfer', E), s('stationary', E)),
				...totals,
				transferDays: 0.2
			},
			{
				kind: 'body',
				targetId: 'naif-301',
				path: path(
					s('surface', E),
					s('orbit', E),
					s('transfer', 'naif-301'),
					s('escape', 'naif-301'),
					s('orbit', 'naif-301'),
					s('surface', 'naif-301')
				),
				...totals,
				transferDays: 5
			},
			{
				kind: 'body',
				targetId: 'naif-599',
				path: path(
					s('surface', E),
					s('orbit', E),
					s('escape', E),
					s('transfer', 'naif-599'),
					s('escape', 'naif-599'),
					s('orbit', 'naif-599')
				),
				...totals,
				transferDays: 997
			},
			{
				kind: 'body',
				targetId: 'naif-502',
				path: path(
					s('surface', E),
					s('orbit', E),
					s('escape', E),
					s('transfer', 'naif-599'),
					s('escape', 'naif-502'),
					s('orbit', 'naif-502'),
					s('surface', 'naif-502')
				),
				...totals,
				transferDays: 997
			},
			{
				kind: 'body',
				targetId: 'naif-606',
				path: path(
					s('surface', E),
					s('orbit', E),
					s('escape', E),
					s('transfer', 'naif-699'),
					s('escape', 'naif-606'),
					s('orbit', 'naif-606'),
					s('surface', 'naif-606')
				),
				...totals,
				transferDays: 2208
			}
		]
	};
}

const NAMES = {
	'naif-399': 'Earth',
	'naif-301': 'Moon',
	'naif-599': 'Jupiter',
	'naif-502': 'Europa',
	'naif-699': 'Saturn',
	'naif-606': 'Titan'
};

describe('buildTree', () => {
	const tree = buildTree(map(), NAMES, { 'naif-599': '#c98' });

	it('lays the trunk as surface, low orbit, escape, with departure modes', () => {
		expect(tree.trunk.map((s) => s.kind)).toEqual(['surface', 'orbit', 'escape']);
		expect(tree.trunk.map((s) => s.mode)).toEqual(['surface', 'low-orbit', null]);
		expect(tree.trunkLegs.map((l) => l.dvKms)).toEqual([9.36, 3.23]);
	});

	it('marks the rows that leave from low orbit as bound', () => {
		const byId = Object.fromEntries(tree.rows.map((r) => [r.stationary ? 'geo' : r.targetId, r]));
		expect(byId.geo.bound).toBe(true);
		expect(byId['naif-301'].bound).toBe(true);
		expect(byId['naif-599'].bound).toBe(false);
		expect(byId['naif-301'].depart.dvKms).toBe(3.13);
	});

	it('hangs a moon off its planet intercept stop', () => {
		const jupiter = tree.rows.find((r) => r.targetId === 'naif-599')!;
		expect(jupiter.stops.map((s) => s.kind)).toEqual(['transfer', 'escape', 'orbit']);
		expect(jupiter.legs.map((l) => l.aero)).toEqual([true, true]);
		expect(jupiter.color).toBe('#c98');
		expect(jupiter.moons).toHaveLength(1);
		const europa = jupiter.moons[0];
		expect(europa.name).toBe('Europa');
		expect(europa.depart.dvKms).toBe(4.86);
		expect(europa.stops.map((s) => s.mode)).toEqual(['elliptical', 'low-orbit', 'surface']);
		expect(europa.legs.map((l) => l.dvKms)).toEqual([0.56, 1.61]);
	});

	it('keeps a planet that is not a target as a bare intercept stop for its moons', () => {
		const saturn = tree.rows.find((r) => r.targetId === 'naif-699')!;
		expect(saturn.name).toBe('Saturn');
		expect(saturn.stops.map((s) => s.kind)).toEqual(['transfer']);
		expect(saturn.totals).toBeNull();
		expect(saturn.moons.map((m) => m.name)).toEqual(['Titan']);
	});

	it('keeps the way out of the Solar System as its own one-stop row', () => {
		const withOut: SubwayMap = map();
		withOut.edges.push({
			from: stationId('escape', 'naif-399'),
			to: stationId('escape', 'naif-10'),
			kind: 'depart',
			dvKms: 5.53,
			via: [],
			aero: false
		});
		withOut.routes.push({
			kind: 'escape',
			targetId: 'naif-10',
			path: [
				stationId('surface', 'naif-399'),
				stationId('orbit', 'naif-399'),
				stationId('escape', 'naif-399'),
				stationId('escape', 'naif-10')
			],
			orbitKms: 18.12,
			surfaceKms: null,
			aeroOrbitKms: null,
			aeroSurfaceKms: null,
			transferDays: Infinity
		});
		const out = buildTree(withOut, NAMES, {}).rows.find((r) => r.escape)!;
		expect(out.depart.dvKms).toBe(5.53);
		expect(out.stops.map((s) => [s.kind, s.mode])).toEqual([['escape', null]]);
		expect(out.bound).toBe(false);
	});

	it('draws the stationary orbit as a two-stop row of the origin', () => {
		const geo = tree.rows.find((r) => r.stationary)!;
		expect(geo.targetId).toBe('naif-399');
		expect(geo.stops.map((s) => [s.kind, s.mode])).toEqual([
			['transfer', 'transfer'],
			['stationary', 'stationary']
		]);
		expect(geo.depart.dvKms).toBe(2.46);
		expect(geo.legs.map((l) => l.dvKms)).toEqual([1.48]);
	});
});
