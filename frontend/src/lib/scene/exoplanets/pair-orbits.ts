/**
 * The pairs of a star system that draw up close, and the numbers each one
 * needs: the orbits of its members, the place of its barycentre, the object
 * that carries its halo, the light of a held star, the held host that takes
 * over its point, and the handover from a point to its two stars. Nothing here
 * reads the scene.
 */

import {
	pairMembers,
	type PairOrbit,
	type SystemMember,
	type SystemNode
} from '$lib/fetch/extrasolar/systems';
import { muFromElements } from '$lib/math/travel/body';
import type { Vec3 } from '$lib/scene/animation/math';
import type { OrbitalElements } from '$lib/types/objects';

/** A wider pair stays at its catalogue places. No clock shows it move, and
 *  the record's place is better than the place from such an orbit. */
const MAX_PERIOD_DAYS = 1e5 * 365.25;
/** The separation on screen (CSS px) up to which a point draws alone, and
 *  from which its two stars draw alone. */
const POINT_ALONE_PX = 2;
const STARS_ALONE_PX = 6;
/** Luminosity goes as this power of the mass, on the main sequence. */
const MASS_LUMINOSITY = 3.5;

const NO_HOSTS: ReadonlyMap<number, number> = new Map();

/** Two values, of a pair's first and second member. */
export type Both<T> = readonly [T, T];

/** A node whose two members draw on its orbit. */
export interface DrawnPair {
	node: SystemNode;
	orbit: PairOrbit;
	first: number;
	second: number;
}

/** The orbits of the two members about their barycentre. The first member is
 *  opposite the second, so its ω is 180° on. */
export function pairElements(orbit: PairOrbit): Both<OrbitalElements> {
	const { a, e, i, om, w, ma, n, epoch, barycentre } = orbit;
	const second = { a: a * (1 - barycentre), e, i, om, w, ma, n, epoch };
	return [{ ...second, a: a * barycentre, w: (w + 180) % 360 }, second];
}

/** The barycentre of a pair from the places of its members. */
export function barycentreOf(first: Readonly<Vec3>, second: Readonly<Vec3>, share: number): Vec3 {
	return [
		first[0] + share * (second[0] - first[0]),
		first[1] + share * (second[1] - first[1]),
		first[2] + share * (second[2] - first[2])
	];
}

/** The fixed place of `id`: the catalogue's, or for a resolved pair the barycentre
 *  of its members. The catalogue keeps a resolved pair's barycentre where its
 *  stars are. */
export function nodePlace(
	id: number,
	pairs: readonly DrawnPair[],
	sceneOf: (id: number) => Readonly<Vec3> | null
): Vec3 | null {
	const pair = pairs.find((p) => p.node.id === id);
	if (!pair || pair.node.point) {
		const at = sceneOf(id);
		return at && [at[0], at[1], at[2]];
	}
	const first = nodePlace(pair.first, pairs, sceneOf);
	const second = nodePlace(pair.second, pairs, sceneOf);
	return first && second && barycentreOf(first, second, pair.orbit.barycentre);
}

/** `id` and the nodes that {@link nodePlace} reads below it. */
export function placeNodes(id: number, pairs: readonly DrawnPair[]): number[] {
	const pair = pairs.find((p) => p.node.id === id);
	if (!pair || pair.node.point) return [id];
	return [id, ...placeNodes(pair.first, pairs), ...placeNodes(pair.second, pairs)];
}

/** The orbits that carry `id`, innermost first, and the outermost pair of them. */
export function carryingOrbits(
	id: number,
	pairs: readonly DrawnPair[]
): { orbits: OrbitalElements[]; top: DrawnPair | null } {
	const orbits: OrbitalElements[] = [];
	let top: DrawnPair | null = null;
	let at = id;
	for (;;) {
		const pair = pairs.find(({ first, second }) => first === at || second === at);
		if (!pair) return { orbits, top };
		orbits.push(pairElements(pair.orbit)[pair.first === at ? 0 : 1]);
		top = pair;
		at = pair.node.id;
	}
}

/** The mass of the star `id` in the system's tables, solar masses. */
export function listedMass(id: number, nodes: ReadonlyMap<number, SystemNode>): number | null {
	const member = [...nodes.values()].flatMap((n) => n.members).find((m) => m.id === id);
	return nodes.get(id)?.star?.mass ?? member?.mass ?? null;
}

/** μ of the member `id` of a pair, km³/s². Kepler's third law gives the sum of the
 *  pair, and the barycentre gives the share of each member. Null for an ID in no
 *  pair, and for a pair with no mass ratio. */
export function memberMu(id: number, pairs: readonly DrawnPair[]): number | null {
	const pair = pairs.find(({ first, second }) => first === id || second === id);
	if (!pair || pair.orbit.barycentre === 0) return null;
	const { orbit, first } = pair;
	return muFromElements(orbit) * (first === id ? 1 - orbit.barycentre : orbit.barycentre);
}

/**
 * The nodes of `nodes` that draw, outermost first. Each member of the pair
 * needs an ID, and a member node needs something to draw: its own point, or a
 * pair of its own. The members stay at their catalogue places otherwise. A
 * point of three stars draws its pair, and its third star stays with the point.
 */
export function drawnPairs(nodes: ReadonlyMap<number, SystemNode>): DrawnPair[] {
	const drawable = ({ id, kind }: SystemMember): boolean => {
		if (id === null) return false;
		if (kind !== 'system') return true;
		const inner = nodes.get(id);
		return inner !== undefined && (inner.point || draws(inner));
	};
	const draws = (node: SystemNode): boolean =>
		node.orbit !== null &&
		node.orbit.period <= MAX_PERIOD_DAYS &&
		pairMembers(node, node.orbit).every(drawable);
	return [...nodes.values()]
		.filter(draws)
		.sort((a, b) => a.depth - b.depth)
		.map((node) => {
			const orbit = node.orbit!;
			const [first, second] = pairMembers(node, orbit);
			return { node, orbit, first: first.id!, second: second.id! };
		});
}

/**
 * The pair that a page of the node `id` frames, the outermost one on the way
 * down through the node's primary. A sibling of the primary is far away and
 * has no place in this view. Null when no such pair draws.
 */
export function framedPair(
	id: number,
	nodes: ReadonlyMap<number, SystemNode>,
	pairs: readonly DrawnPair[]
): DrawnPair | null {
	let node = nodes.get(id);
	while (node?.members.length) {
		const { id: nodeId, primary, members } = node;
		const pair = pairs.find((p) => p.node.id === nodeId);
		if (pair) return pair;
		const inner = members.map((m) => (m.kind === 'system' ? nodes.get(m.id!) : undefined));
		node = inner.find((n) => n?.primary === primary);
	}
	return null;
}

/**
 * The object that carries the halo and name of the node `id`: the node, or the
 * member on the barycentre of the pair that the node frames. That member takes
 * over the node, as the Sun takes over the solar system. With no pair that
 * draws there is no barycentre, and the primary takes over, or the held host
 * that takes over the primary's point (see {@link heldHosts}).
 */
export function haloCarrier(
	id: number,
	nodes: ReadonlyMap<number, SystemNode>,
	pairs: readonly DrawnPair[],
	hosts: ReadonlyMap<number, number> = NO_HOSTS
): number {
	const pair = framedPair(id, nodes, pairs);
	if (pair) return pair.orbit.barycentre === 0 ? haloCarrier(pair.first, nodes, pairs, hosts) : id;
	const primary = nodes.get(id)?.primary ?? id;
	return hosts.get(primary) ?? primary;
}

/**
 * The held star that takes over each point, by point ID. It is the one held
 * member that hosts planets. Its planets need its sphere to circle, so it
 * draws in the point's stead with the point's light. A point with two such
 * members stays a point, because one sphere would stand for both. No star
 * takes over a point on a drawn orbit or a point whose own pair draws. Such a
 * point sits at its pair's barycentre and hands its light to its two stars.
 */
export function heldHosts(
	nodes: ReadonlyMap<number, SystemNode>,
	pairs: readonly DrawnPair[],
	hostsPlanets: (id: number) => boolean
): Map<number, number> {
	const drawn = new Set(pairs.flatMap(({ node, first, second }) => [node.id, first, second]));
	const out = new Map<number, number>();
	for (const node of nodes.values()) {
		if (!node.point || drawn.has(node.id)) continue;
		const hosts = node.members.flatMap(({ id, kind }) =>
			kind === 'held star' && id !== null && hostsPlanets(id) ? [id] : []
		);
		if (hosts.length === 1) out.set(node.id, hosts[0]);
	}
	return out;
}

function flux(mag: number): number {
	return 10 ** (-0.4 * mag);
}

function magnitude(light: number): number {
	return -2.5 * Math.log10(light);
}

/**
 * Absolute magnitudes of the stars inside a point, which sum to `total`, the
 * point's. Stars that all have magnitudes of their own keep their ratio. Stars
 * that all have masses share by the mass-luminosity law. Else the stars with a
 * magnitude keep it, and the others share the rest of the light equally. With
 * nothing better, or when those stars are brighter than the point, all stars
 * share equally. A point with no magnitude leaves each star its own.
 */
export function splitLight(
	total: number | null,
	own: readonly (number | null)[],
	masses: readonly (number | null)[]
): (number | null)[] {
	if (total === null) return [...own];
	const all = flux(total);
	const shares = (weights: readonly number[]): number[] => {
		const sum = weights.reduce((a, b) => a + b, 0);
		return weights.map((weight) => magnitude((all * weight) / sum));
	};
	if (own.every((mag): mag is number => mag !== null)) return shares(own.map(flux));
	if (masses.every((mass): mass is number => mass !== null)) {
		return shares(masses.map((mass) => mass ** MASS_LUMINOSITY));
	}
	const known = own.filter((mag): mag is number => mag !== null);
	const lit = known.reduce((sum, mag) => sum + flux(mag), 0);
	if (known.length === 0 || lit >= all) return shares(own.map(() => 1));
	const rest = magnitude((all - lit) / (own.length - known.length));
	return own.map((mag) => mag ?? rest);
}

/** The share of the light `total` of a point that its stars on no drawn orbit
 *  keep, from the magnitudes that {@link splitLight} gives its members. */
export function keptLight(
	total: number | null,
	light: readonly (number | null)[],
	{ first, second }: PairOrbit
): number {
	if (total === null) return 0;
	const kept = light.reduce<number>(
		(sum, mag, i) => (i === first || i === second || mag === null ? sum : sum + flux(mag)),
		0
	);
	return kept / flux(total);
}

/** The share of a pair's light that its two stars draw at a separation on
 *  screen, and the rest of it their point. */
export function starsShare(separationPx: number): number {
	const t = (separationPx - POINT_ALONE_PX) / (STARS_ALONE_PX - POINT_ALONE_PX);
	const x = Math.min(Math.max(t, 0), 1);
	return x * x * (3 - 2 * x);
}

/**
 * The share of its own light that each object of a system draws. `handed` is
 * the share that a pair's point gives to its two stars. `kept` is the share of
 * the point's light that its stars on no orbit hold, and it stays with the
 * point. A point and its stars sum to the share that the point has. A resolved
 * node has no light to keep, so its members take its whole share. `pairs` go
 * outermost first.
 */
export function pairLight(
	pairs: readonly { pair: DrawnPair; handed: number; kept: number }[]
): Map<number, number> {
	const light = new Map<number, number>();
	for (const { pair, handed, kept } of pairs) {
		const { node, first, second } = pair;
		const own = light.get(node.id) ?? 1;
		const stars = node.point ? handed : 1;
		light.set(node.id, own * (1 - stars * (1 - kept)));
		light.set(first, own * stars);
		light.set(second, own * stars);
	}
	return light;
}
