/**
 * A star system as its pages show it: the row of each node, the page name of
 * each node and member, and the planets of each host. The list rows come from
 * the members of the nodes, in member order.
 */

import * as m from '$lib/paraglide/messages.js';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { planetCatalogue, type Planet, type PlanetSystem } from '$lib/fetch/extrasolar/planets';
import {
	loadSystemNodes,
	type HeldStarValues,
	type SystemMember,
	type SystemNode
} from '$lib/fetch/extrasolar/systems';
import { fetchPageName } from './page-name';

export interface StarSystem {
	root: SystemNode;
	name: string;
	/** The rows of the tree, by ID. */
	nodes: ReadonlyMap<number, SystemNode>;
	/** The page names of the nodes and members, by ID. */
	names: ReadonlyMap<number, string>;
	/** The planets of each host of the system. */
	planets: ReadonlyMap<number, readonly Planet[]>;
}

/** One line of a system's list of stars. */
export interface SystemRow {
	member: SystemMember;
	/** Levels below the node the list starts from. */
	depth: number;
	name: string;
	/** The letter for its tile; undefined for one that does not fit. */
	letter: string | undefined;
	/** The stars of a member node; null for a star. */
	stars: number | null;
	/** The values of a held star. */
	held: HeldStarValues | null;
}

/** A host of a system, with its planets. */
export interface SystemHost {
	id: number;
	name: string;
	planets: readonly Planet[];
}

/** A component letter, alone or at the end of a name ("Sirius A"). A longer
 *  list of letters does not fit a tile. */
const TILE_LETTER = /(?:^|\s)([A-Z][A-Za-z0-9]{0,3})$/;

function tileLetter(...labels: (string | null | undefined)[]): string | undefined {
	for (const label of labels) {
		const letter = label?.match(TILE_LETTER)?.[1];
		if (letter) return letter;
	}
	return undefined;
}

/** A member's page name. An entry has no page: it takes its source's name,
 *  else its root's name and its letter, as a held star does. Most stars of a
 *  Gaia DR3 orbit have neither. */
function memberName(system: StarSystem, member: SystemMember, index: number): string {
	const page = member.id === null ? undefined : system.names.get(member.id);
	if (page) return page;
	const { label, letter } = member;
	if (label && label !== letter) return label;
	if (letter) return `${system.name} ${letter}`;
	return index === 0 ? m.system_member_primary() : m.system_member_companion();
}

/** The stars of the node `from`, in tree order: each member, then the members
 *  of a member node, one level down. */
export function systemRows(system: StarSystem, from: number): SystemRow[] {
	const out: SystemRow[] = [];
	const walk = (id: number, depth: number) => {
		system.nodes.get(id)?.members.forEach((member, index) => {
			const own = member.id === null ? undefined : system.nodes.get(member.id);
			out.push({
				member,
				depth,
				name: memberName(system, member, index),
				letter: tileLetter(own?.label, member.inner, member.letter, member.label),
				stars: member.kind === 'system' ? (own?.stars ?? null) : null,
				held: own?.star ?? null
			});
			if (member.kind === 'system' && member.id !== null) walk(member.id, depth + 1);
		});
	};
	walk(from, 0);
	return out;
}

/** The hosts at the node `from` and below it, in tree order. */
export function systemHosts(system: StarSystem, from: number): SystemHost[] {
	const ids = [from, ...systemRows(system, from).flatMap(({ member }) => member.id ?? [])];
	return ids.flatMap((id) => {
		const planets = system.planets.get(id);
		return planets ? [{ id, name: system.names.get(id) || String(id), planets }] : [];
	});
}

/** How many planets the page of the node `id` holds: its own and those below
 *  it. Before its system loads, the file gives only its own. */
export function nodePlanetCount(
	system: StarSystem | null,
	file: PlanetSystem | null,
	id: number
): number {
	if (!system) return file?.planets.filter((planet) => planet.host === id).length ?? 0;
	return systemHosts(system, id).reduce((sum, host) => sum + host.planets.length, 0);
}

/** The planets of each host among `ids`. The root keys the one planet file of
 *  a star system, and a system with no hosts has no file. */
async function loadPlanets(root: number, ids: ReadonlySet<number>): Promise<Map<number, Planet[]>> {
	const planets = new Map<number, Planet[]>();
	const index = await planetCatalogue.index();
	if (!index?.hostsOf(root).length) return planets;
	const file = await planetCatalogue.system(root);
	for (const planet of file.planets) {
		if (!ids.has(planet.host)) continue;
		planets.set(planet.host, [...(planets.get(planet.host) ?? []), planet]);
	}
	return planets;
}

/** The system of `rootId`. Null when the host may not show its rows. The stars
 *  still show when a name or the planets do not load. */
export async function loadStarSystem(rootId: number): Promise<StarSystem | null> {
	const rows = await loadSystemNodes(rootId);
	const root = rows.at(0);
	if (!root) return null;
	const ids = new Set(
		rows.flatMap((node) => [node.id, ...node.members.flatMap((x) => x.id ?? [])])
	);
	const named = await Promise.all(
		[...ids].map(async (id): Promise<[number, string]> => {
			const subject = { kind: 'body', id: extrasolarObjectId(id) } as const;
			return [id, await fetchPageName(subject).catch(() => '')];
		})
	);
	const planets = await loadPlanets(rootId, ids).catch((e: unknown) => {
		console.warn(`[systems] no planets for system ${rootId}:`, e);
		return new Map<number, Planet[]>();
	});
	const names = new Map(named);
	return {
		root,
		name: names.get(rootId) || String(rootId),
		nodes: new Map(rows.map((node) => [node.id, node])),
		names,
		planets
	};
}
