/**
 * The Δv map as the page draws it: a trunk for the origin and one row per
 * destination system, moons hanging off their planet's intercept stop.
 *
 * The graph knows stations and edges; the drawing wants rows. This is the
 * regrouping between them, with nothing about pixels in it, so the two
 * orientations the page needs can share it.
 */

import type { StationKind, SubwayEdge, SubwayMap, SubwayRoute } from '$lib/math/travel/subway';
import type { EndpointMode } from './trip';

export interface TreeStop {
	station: string;
	kind: StationKind;
	bodyId: string;
	/** Name and tint of the body the stop belongs to. */
	name: string;
	color: string;
	/** The planner mode this stop stands for: an arrival mode on a row, a
	 *  departure mode on the trunk. Null where the planner has no word for it. */
	mode: EndpointMode | null;
}

export interface TreeLeg {
	dvKms: number;
	aero: boolean;
}

export interface TreeTotals {
	orbitKms: number;
	surfaceKms: number | null;
	aeroOrbitKms: number | null;
	aeroSurfaceKms: number | null;
}

export interface TreeRow {
	targetId: string;
	name: string;
	color: string;
	/** Leaves the trunk at low orbit rather than at escape. */
	bound: boolean;
	/** Which trunk stop it leaves from. */
	trunkIndex: number;
	/** The origin's own stationary orbit, drawn as a bound row of two stops. */
	stationary: boolean;
	/** Out of the root's well: one stop, the last one off the trunk. */
	escape: boolean;
	/** The burn that puts the trip on its transfer, from the trunk to the first stop. */
	depart: TreeLeg;
	/** The intercept stop first, then the rest of the way in. A row whose own
	 *  body is not a target keeps only the intercept stop its moons hang off. */
	stops: TreeStop[];
	/** One per pair of consecutive stops. */
	legs: TreeLeg[];
	/** Null for a row that is only there for its moons. */
	totals: TreeTotals | null;
	moons: TreeRow[];
}

export interface Tree {
	originId: string;
	originName: string;
	/** Surface where there is ground, then low orbit, then one escape stop per
	 *  well the origin sits inside — its own, then its primary's, and so on.
	 *  Each stop carries the tint of the body it belongs to, so a trunk out of
	 *  a moon changes colour where it leaves the moon's well for the planet's. */
	trunk: TreeStop[];
	/** The well the trunk is in past its last stop, which no stop stands for:
	 *  the root's once the last stop is an escape. */
	trunkTailColor: string;
	trunkLegs: TreeLeg[];
	rows: TreeRow[];
}

/** What the planner calls arriving at each kind of stop. */
const ARRIVAL_MODE: Record<StationKind, EndpointMode | null> = {
	transfer: 'flyby',
	escape: 'elliptical',
	orbit: 'low-orbit',
	surface: 'surface',
	stationary: 'stationary'
};

/** ... and leaving from each kind on the trunk. */
const DEPARTURE_MODE: Partial<Record<StationKind, EndpointMode>> = {
	surface: 'surface',
	orbit: 'low-orbit'
};

function parseStation(station: string): { kind: StationKind; bodyId: string } {
	const cut = station.indexOf(':');
	return { kind: station.slice(0, cut) as StationKind, bodyId: station.slice(cut + 1) };
}

function edgeKey(from: string, to: string): string {
	return `${from}>${to}`;
}

/** The map regrouped into rows. `names` and `colors` are read by body id. */
export function buildTree(
	map: SubwayMap,
	names: ReadonlyMap<string, string> | Record<string, string>,
	colors: ReadonlyMap<string, string> | Record<string, string>
): Tree {
	const nameOf = (id: string) =>
		(names instanceof Map ? names.get(id) : (names as Record<string, string>)[id]) ?? id;
	const colorOf = (id: string) =>
		(colors instanceof Map ? colors.get(id) : (colors as Record<string, string>)[id]) ??
		'currentColor';
	const edges = new Map<string, SubwayEdge>(map.edges.map((e) => [edgeKey(e.from, e.to), e]));
	const leg = (from: string, to: string): TreeLeg => {
		const e = edges.get(edgeKey(from, to));
		return { dvKms: e?.dvKms ?? 0, aero: e?.aero ?? false };
	};
	const stopOf = (station: string, onTrunk = false): TreeStop => {
		const { kind, bodyId } = parseStation(station);
		return {
			station,
			kind,
			bodyId,
			name: nameOf(bodyId),
			color: colorOf(bodyId),
			mode: onTrunk ? (DEPARTURE_MODE[kind] ?? null) : ARRIVAL_MODE[kind]
		};
	};

	const { originId } = map;
	const trunkStations = map.trunk;
	const trunk = trunkStations.map((station) => stopOf(station, true));
	const trunkLegs = trunkStations.slice(1).map((station, i) => leg(trunkStations[i], station));
	// A row always leaves from a trunk stop; a map that says otherwise falls
	// back to the parking orbit rather than to geometry with no coordinates.
	const orbitIndex = trunkStations.findIndex((s) => s.startsWith('orbit:'));
	const trunkIndexOf = (station: string) => {
		const i = trunkStations.indexOf(station);
		return i === -1 ? Math.max(0, orbitIndex) : i;
	};

	// Rows are keyed by the intercept stop they share; the body the stop is
	// named for owns the row, and every other route through it is a moon.
	const rows = new Map<string, TreeRow>();
	const rowFor = (transfer: string, route: SubwayRoute): TreeRow => {
		const existing = rows.get(transfer);
		if (existing) return existing;
		const { bodyId } = parseStation(transfer);
		const entryIndex = route.path.indexOf(transfer);
		const from = route.path[entryIndex - 1];
		const row: TreeRow = {
			targetId: bodyId,
			name: nameOf(bodyId),
			color: colorOf(bodyId),
			bound: parseStation(from).kind === 'orbit',
			trunkIndex: trunkIndexOf(from),
			stationary: false,
			escape: false,
			depart: leg(from, transfer),
			stops: [stopOf(transfer)],
			legs: [],
			totals: null,
			moons: []
		};
		rows.set(transfer, row);
		return row;
	};
	const totalsOf = (route: SubwayRoute): TreeTotals => ({
		orbitKms: route.orbitKms,
		surfaceKms: route.surfaceKms,
		aeroOrbitKms: route.aeroOrbitKms,
		aeroSurfaceKms: route.aeroSurfaceKms
	});

	for (const route of map.routes) {
		if (route.kind === 'escape') {
			const out = route.path[route.path.length - 1];
			rows.set(out, {
				targetId: route.targetId,
				name: nameOf(route.targetId),
				color: colorOf(route.targetId),
				bound: false,
				trunkIndex: trunkIndexOf(route.path[route.path.length - 2]),
				stationary: false,
				escape: true,
				depart: leg(route.path[route.path.length - 2], out),
				stops: [{ ...stopOf(out), mode: null }],
				legs: [],
				totals: totalsOf(route),
				moons: []
			});
			continue;
		}
		const transfer = route.path.find((s) => s.startsWith('transfer:'));
		if (!transfer) continue;
		const after = route.path.slice(route.path.indexOf(transfer) + 1);
		if (route.kind === 'stationary') {
			const stops = [stopOf(transfer), ...after.map((s) => stopOf(s))];
			stops[0].mode = 'transfer';
			rows.set(`stationary:${originId}`, {
				targetId: originId,
				name: nameOf(originId),
				color: colorOf(originId),
				bound: true,
				trunkIndex: trunkIndexOf(`orbit:${originId}`),
				stationary: true,
				escape: false,
				depart: leg(route.path[route.path.indexOf(transfer) - 1], transfer),
				stops,
				legs: after.map((s, i) => leg(i === 0 ? transfer : after[i - 1], s)),
				totals: totalsOf(route),
				moons: []
			});
			continue;
		}
		const row = rowFor(transfer, route);
		if (route.targetId === row.targetId) {
			row.stops = [row.stops[0], ...after.map((s) => stopOf(s))];
			row.legs = after.map((s, i) => leg(i === 0 ? transfer : after[i - 1], s));
			row.totals = totalsOf(route);
		} else {
			row.moons.push({
				targetId: route.targetId,
				name: nameOf(route.targetId),
				color: colorOf(route.targetId),
				bound: false,
				trunkIndex: row.trunkIndex,
				stationary: false,
				escape: false,
				depart: leg(transfer, after[0]),
				stops: after.map((s) => stopOf(s)),
				legs: after.slice(1).map((s, i) => leg(after[i], s)),
				totals: totalsOf(route),
				moons: []
			});
		}
	}

	const tail = trunk[trunk.length - 1];
	const rootId = map.routes.find((r) => r.kind === 'escape')?.targetId;
	return {
		originId,
		originName: nameOf(originId),
		trunk,
		trunkTailColor:
			tail?.kind === 'escape' && rootId !== undefined
				? colorOf(rootId)
				: (tail?.color ?? 'currentColor'),
		trunkLegs,
		rows: [...rows.values()]
	};
}
