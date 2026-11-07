import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	A,
	AB,
	B,
	C,
	ROOT,
	heldValues,
	member,
	systemNodeOf,
	threeStars
} from '$lib/fetch/extrasolar/__fixtures__/system-node';
import type { Planet, PlanetSystem } from '$lib/fetch/extrasolar/planets';

const { loadSystemNodes, fetchPageName, index, system } = vi.hoisted(() => ({
	loadSystemNodes: vi.fn(),
	fetchPageName: vi.fn(),
	index: vi.fn(),
	system: vi.fn()
}));
vi.mock('$lib/fetch/extrasolar/systems', async (original) => ({
	...(await original<typeof import('$lib/fetch/extrasolar/systems')>()),
	loadSystemNodes
}));
vi.mock('./page-name', () => ({ fetchPageName }));
vi.mock('$lib/fetch/extrasolar/planets', () => ({ planetCatalogue: { index, system } }));

import {
	loadStarSystem,
	radiusPaperPoint,
	nodePlanetCount,
	systemHosts,
	systemRows,
	type StarSystem
} from './star-system';

afterEach(() => vi.resetAllMocks());

/** A system of one node with `members`. */
function flat(...members: ReturnType<typeof member>[]) {
	const root = systemNodeOf(ROOT, { members });
	return { ...threeStars(), root, nodes: new Map([[ROOT, root]]) };
}

describe('systemRows', () => {
	it('lists the tree, each node followed by its members one level down', () => {
		const rows = systemRows(threeStars(), ROOT);
		expect(rows.map((r) => [r.depth, r.letter, r.name, r.stars])).toEqual([
			[0, 'AB', 'Alpha Centauri AB', 2],
			[1, 'A', 'Rigil Kentaurus', null],
			[1, 'B', 'Toliman', null],
			[0, 'C', 'Proxima Centauri', null]
		]);
	});

	it('starts at an inner node for its own page', () => {
		expect(systemRows(threeStars(), AB).map((r) => r.member.id)).toEqual([A, B]);
	});

	it('takes the letter from the end of a name, and leaves out one too long for a tile', () => {
		const rows = systemRows(
			flat(member(A, { letter: 'Sirius A' }), member(B, { letter: 'CEGSTUVWX' })),
			ROOT
		);
		expect(rows.map((r) => r.letter)).toEqual(['A', undefined]);
	});

	it('takes the letter of a held star from its own row', () => {
		const held = systemNodeOf(A, { label: 'Ab', parent: ROOT });
		const system = flat(member(A, { letter: 'Kepler-16', kind: 'held star' }));
		const nodes = new Map([...system.nodes, [A, held]]);
		expect(systemRows({ ...system, nodes }, ROOT)[0].letter).toBe('Ab');
	});

	it('names an entry by its source, else by the system and its letter, else by its place', () => {
		const rows = systemRows(
			flat(
				member(null, { kind: 'entry', label: 'Gliese 559 B', letter: 'B' }),
				member(null, { kind: 'entry', label: 'C', letter: 'C' })
			),
			ROOT
		);
		expect(rows.map((r) => r.name)).toEqual(['Gliese 559 B', 'Alpha Centauri C']);
		const pair = systemRows(flat(member(null), member(null)), ROOT);
		expect(pair.map((r) => r.name)).toEqual(['Primary star', 'Companion star']);
	});
});

describe('systemHosts', () => {
	it('groups the planets by host, in tree order', () => {
		expect(systemHosts(threeStars(), ROOT).map((h) => [h.name, h.planets.length])).toEqual([
			['Toliman', 1],
			['Proxima Centauri', 2]
		]);
	});

	it('keeps to the node of the page', () => {
		expect(systemHosts(threeStars(), AB).map((h) => h.id)).toEqual([B]);
	});

	it('counts a pair as a host, for its circumbinary planets', () => {
		const base = threeStars();
		const planets = new Map([[AB, [{ host: AB, number: 1 } as Planet]]]);
		expect(systemHosts({ ...base, planets }, ROOT).map((h) => h.id)).toEqual([AB]);
	});
});

describe('nodePlanetCount', () => {
	const file = { planets: [{ host: AB }, { host: AB }, { host: B }] } as unknown as PlanetSystem;

	it('counts the planets at the node and below it once the system is in', () => {
		const planets = new Map([
			[AB, [{ host: AB, number: 1 } as Planet]],
			[B, [{ host: B, number: 1 } as Planet]],
			[C, [{ host: C, number: 1 } as Planet]]
		]);
		expect(nodePlanetCount({ ...threeStars(), planets }, file, AB)).toBe(2);
	});

	it('counts the planets of the node itself from its file before that', () => {
		expect(nodePlanetCount(null, file, AB)).toBe(2);
	});

	it('is 0 with neither', () => {
		expect(nodePlanetCount(null, null, AB)).toBe(0);
	});
});

describe('loadStarSystem', () => {
	const rows = () => [...threeStars().nodes.values()];

	it('reads the planets of the hosts from the one file of the root', async () => {
		loadSystemNodes.mockResolvedValue(rows());
		fetchPageName.mockImplementation(async ({ id }: { id: string }) => `name of ${id}`);
		index.mockResolvedValue({ hostsOf: (key: number) => (key === ROOT ? [B, C] : []) });
		system.mockResolvedValue({
			planets: [
				{ host: B, number: 1 },
				{ host: C, number: 1 },
				{ host: 999, number: 1 }
			]
		});
		const loaded = await loadStarSystem(ROOT);
		expect(system.mock.calls).toEqual([[ROOT]]);
		expect([...loaded!.planets.keys()].sort()).toEqual([B, C]);
		expect(loaded!.name).toBe(`name of x-${ROOT}`);
	});

	it('asks for no file for a system with no hosts', async () => {
		loadSystemNodes.mockResolvedValue(rows());
		fetchPageName.mockResolvedValue('');
		index.mockResolvedValue({ hostsOf: () => [] });
		const loaded = await loadStarSystem(ROOT);
		expect(system).not.toHaveBeenCalled();
		expect(loaded?.planets.size).toBe(0);
	});

	it('is null when the host may not show the rows', async () => {
		loadSystemNodes.mockResolvedValue([]);
		await expect(loadStarSystem(ROOT)).resolves.toBeNull();
	});

	it('keeps the stars when a name or the planets do not load', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		loadSystemNodes.mockResolvedValue(rows());
		fetchPageName.mockRejectedValue(new Error('no name'));
		index.mockRejectedValue(new Error('no index'));
		const loaded = await loadStarSystem(ROOT);
		expect(loaded?.nodes.size).toBe(2);
		expect(loaded?.planets.size).toBe(0);
		expect(loaded?.name).toBe(String(ROOT));
		expect(warn).toHaveBeenCalled();
	});
});

describe('radiusPaperPoint', () => {
	const point = systemNodeOf(AB, { point: true, paperRadius: true, members: [member(A)] });
	const system: StarSystem = {
		root: point,
		name: '',
		nodes: new Map([[AB, point]]),
		names: new Map(),
		planets: new Map()
	};
	const held = (radiusSource: string | null, dominant = true) =>
		systemNodeOf(A, { parent: AB, star: heldValues({ radiusSource, dominant }) });
	const paper = { solar: 800, source: 'literature' } as const;

	it('gives the point of a held star whose paper radius is not its own', () => {
		expect(radiusPaperPoint(system, held('msc'), paper)?.id).toBe(AB);
		expect(radiusPaperPoint(system, held(null), paper)?.id).toBe(AB);
	});

	it('gives none for a paper of its own, for another source, or before the system loads', () => {
		expect(radiusPaperPoint(system, held('literature'), paper)).toBeNull();
		expect(radiusPaperPoint(system, held(null), { solar: 800, source: 'jmdc' })).toBeNull();
		expect(radiusPaperPoint(system, held(null), null)).toBeNull();
		expect(radiusPaperPoint(null, held(null), paper)).toBeNull();
	});

	it('gives none for a member that does not dominate its point', () => {
		expect(radiusPaperPoint(system, held(null, false), paper)).toBeNull();
	});
});
