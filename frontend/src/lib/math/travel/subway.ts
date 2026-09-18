/**
 * The Δv subway map: every body as a line of stops — surface, low orbit,
 * escape — joined to the others by the transfer that carries a trip out of
 * one system and into the next.
 *
 * Ideal patched conics throughout: a Hohmann ellipse about the body both ends
 * go round, burns at the two parking orbits only, and a free coast through any
 * well between them. The burn out of a parking orbit is split into "reach
 * escape" and "the rest", so the stops a body shares with every destination
 * carry one figure and the leg to each destination another. The sum is exact;
 * only the split is a convention, and the same one the classic map uses.
 */

import type { TravelBody } from './body';
import { SEC_PER_DAY } from './constants';
import {
	arrivalCostFromSpeed,
	ascentDv,
	canAeroBrake,
	circularSpeed,
	injectionDv,
	parkingRadiusKm,
	periapsisSpeed
} from './maneuvers';

export interface SubwayBody {
	id: string;
	/** Gravitational parameter, km³/s². */
	mu: number;
	/** The body this one goes round; null at the root. */
	primaryId: string | null;
	/** Semi-major axis about that primary, km; 0 at the root. */
	orbitRadiusKm: number;
	/** The kernel's view of the body, for the burns at its parking orbit. Null
	 *  where nothing departs from or arrives at — the root. */
	travel: TravelBody | null;
	/** Whether there is a surface to launch from and land on. */
	ground: boolean;
	/** Radius of the orbit that keeps pace with the body's spin, km; absent
	 *  where the spin is unknown. The one high orbit worth a stop of its own. */
	synchronousRadiusKm?: number;
}

export type SubwayBodies = ReadonlyMap<string, SubwayBody>;

export type StationKind = 'surface' | 'orbit' | 'escape' | 'transfer' | 'stationary';

/** A stop. `transfer` stops belong to the system being entered: one per
 *  destination system, shared by every body inside it. The origin's own
 *  `transfer` stop is the ellipse up to its `stationary` orbit. */
export interface SubwayStation {
	id: string;
	kind: StationKind;
	bodyId: string;
}

export type EdgeKind = 'ascent' | 'escape' | 'depart' | 'arrive' | 'circularize' | 'landing';

export interface SubwayEdge {
	from: string;
	to: string;
	kind: EdgeKind;
	dvKms: number;
	/** Wells coasted through with no burn, in travel order. */
	via: string[];
	/** True when an atmosphere at the arrival body can stand in for the burn. */
	aero: boolean;
}

export interface SubwayRoute {
	/** A trip to another body, up to the origin's own stationary orbit, or out
	 *  of the root's well altogether — the Solar System, from anywhere in it. */
	kind: 'body' | 'stationary' | 'escape';
	targetId: string;
	/** Stop ids in travel order, from the origin's first stop. */
	path: string[];
	/** Sum of the burns to the target's low orbit. */
	orbitKms: number;
	/** ... and on to its surface; null where there is none. */
	surfaceKms: number | null;
	/** The same two with the target's atmosphere doing the braking; null where
	 *  there is none to brake in. */
	aeroOrbitKms: number | null;
	aeroSurfaceKms: number | null;
	/** Half the transfer ellipse, days. */
	transferDays: number;
}

export interface SubwayMap {
	originId: string;
	stations: SubwayStation[];
	edges: SubwayEdge[];
	routes: SubwayRoute[];
}

export function stationId(kind: StationKind, bodyId: string): string {
	return `${kind}:${bodyId}`;
}

/** Speed on the ellipse between `r1Km` and `r2Km` where it crosses `rKm`. */
function ellipseSpeed(mu: number, rKm: number, r1Km: number, r2Km: number): number {
	return Math.sqrt(Math.max(0, mu * (2 / rKm - 2 / (r1Km + r2Km))));
}

/** Excess speed relative to a body on a circular orbit of radius `rKm` about a
 *  primary, for a craft passing that radius with excess speed `vInfKms`
 *  relative to the primary — tangentially, which is the cheapest meeting. */
function vInfInside(vInfKms: number, primaryMu: number, rKm: number): number {
	return Math.abs(periapsisSpeed(primaryMu, rKm, vInfKms) - circularSpeed(primaryMu, rKm));
}

/** Excess speed carried down `path` — a chain of bodies each going round the
 *  one before it — from the one it is quoted against to the last. */
function vInfAlong(bodies: SubwayBodies, path: readonly string[], vInfKms: number): number {
	let v = vInfKms;
	for (let i = 1; i < path.length; i++) {
		const primary = bodies.get(path[i - 1])!;
		const inner = bodies.get(path[i])!;
		v = vInfInside(v, primary.mu, inner.orbitRadiusKm);
	}
	return v;
}

/** Burn from the parking orbit to escape speed. */
function escapeKms(travel: TravelBody): number {
	return injectionDv(travel.mu, parkingRadiusKm(travel), 0);
}

/** What leaving with excess speed costs over reaching bare escape. */
function extraKms(travel: TravelBody, vInfKms: number): number {
	return injectionDv(travel.mu, parkingRadiusKm(travel), vInfKms) - escapeKms(travel);
}

/** Half a period of the ellipse between two radii, days. */
function halfEllipseDays(mu: number, r1Km: number, r2Km: number): number {
	const a = (r1Km + r2Km) / 2;
	return (Math.PI * Math.sqrt((a * a * a) / mu)) / SEC_PER_DAY;
}

/** The body and every primary above it, nearest first; null when the chain
 *  leaves the map before reaching a root. */
function chainOf(bodies: SubwayBodies, id: string): string[] | null {
	const chain: string[] = [];
	let current: string | null = id;
	while (current !== null) {
		if (chain.includes(current)) return null;
		const body = bodies.get(current);
		if (!body) return null;
		chain.push(current);
		current = body.primaryId;
	}
	return chain;
}

/** Where a trip between the two chains is flown: the nearest body both go
 *  round, and each side's body directly under it. */
interface Meeting {
	centreId: string;
	/** The origin-side chain from the body under the centre down to the origin. */
	originSide: string[];
	/** The target-side chain from the body under the centre down to the target. */
	targetSide: string[];
}

function meet(originChain: readonly string[], targetChain: readonly string[]): Meeting | null {
	const onTarget = new Set(targetChain);
	const i = originChain.findIndex((id) => onTarget.has(id));
	if (i === -1) return null;
	const centreId = originChain[i];
	const j = targetChain.indexOf(centreId);
	return {
		centreId,
		originSide: originChain.slice(0, i).reverse(),
		targetSide: targetChain.slice(0, j).reverse()
	};
}

/** The stops and burns from one body's parking orbit to another's. */
interface Crossing {
	transferId: string;
	/** Burn out of the origin's parking orbit; bound when the transfer stays
	 *  about the origin and no escape is crossed. */
	departKms: number;
	departBound: boolean;
	departVia: string[];
	/** Burn into the target's parking orbit; bound when the transfer arrives
	 *  on an ellipse about the target rather than a hyperbola. */
	arriveKms: number;
	arriveBound: boolean;
	arriveVia: string[];
	/** Speed at the target's parking periapsis on arrival — what an atmosphere
	 *  would have to shed. */
	arrivePeriKms: number;
	transferDays: number;
}

function crossing(
	bodies: SubwayBodies,
	origin: SubwayBody,
	target: SubwayBody,
	meeting: Meeting
): Crossing {
	const originTravel = origin.travel!;
	const targetTravel = target.travel!;
	const rParkO = parkingRadiusKm(originTravel);
	const rParkT = parkingRadiusKm(targetTravel);
	const { centreId, originSide, targetSide } = meeting;
	const centre = bodies.get(centreId)!;

	if (centreId === origin.id) {
		// The target goes round the origin: an ellipse from the parking orbit up
		// to the target's own orbit, and the rest of the way in on its excess.
		const top = bodies.get(targetSide[0])!;
		const r2 = top.orbitRadiusKm;
		const departKms = Math.abs(
			ellipseSpeed(origin.mu, rParkO, rParkO, r2) - circularSpeed(origin.mu, rParkO)
		);
		const vInfTop = Math.abs(
			circularSpeed(origin.mu, r2) - ellipseSpeed(origin.mu, r2, rParkO, r2)
		);
		const vInf = vInfAlong(bodies, targetSide, vInfTop);
		return {
			transferId: top.id,
			departKms,
			departBound: true,
			departVia: [],
			arriveKms: extraKms(targetTravel, vInf),
			arriveBound: false,
			arriveVia: targetSide.slice(0, -1),
			arrivePeriKms: periapsisSpeed(target.mu, rParkT, vInf),
			transferDays: halfEllipseDays(origin.mu, rParkO, r2)
		};
	}

	if (centreId === target.id) {
		// The origin goes round the target: the same ellipse flown inward, met
		// on its far end with the excess the origin has to leave with.
		const top = bodies.get(originSide[0])!;
		const r2 = top.orbitRadiusKm;
		const vInfTop = Math.abs(
			circularSpeed(target.mu, r2) - ellipseSpeed(target.mu, r2, rParkT, r2)
		);
		const vInf = vInfAlong(bodies, originSide, vInfTop);
		const arrivePeriKms = ellipseSpeed(target.mu, rParkT, rParkT, r2);
		return {
			transferId: target.id,
			departKms: extraKms(originTravel, vInf),
			departBound: false,
			departVia: originSide.slice(0, -1).reverse(),
			arriveKms: Math.abs(arrivePeriKms - circularSpeed(target.mu, rParkT)),
			arriveBound: true,
			arriveVia: [],
			arrivePeriKms,
			transferDays: halfEllipseDays(target.mu, rParkT, r2)
		};
	}

	// Both go round a third body: a Hohmann between the two orbits about it,
	// entered and left on an excess carried through whatever lies between.
	const a = bodies.get(originSide[0])!;
	const b = bodies.get(targetSide[0])!;
	const rA = a.orbitRadiusKm;
	const rB = b.orbitRadiusKm;
	const vInfA = Math.abs(ellipseSpeed(centre.mu, rA, rA, rB) - circularSpeed(centre.mu, rA));
	const vInfB = Math.abs(ellipseSpeed(centre.mu, rB, rA, rB) - circularSpeed(centre.mu, rB));
	const vInfO = vInfAlong(bodies, originSide, vInfA);
	const vInfT = vInfAlong(bodies, targetSide, vInfB);
	return {
		transferId: b.id,
		departKms: extraKms(originTravel, vInfO),
		departBound: false,
		departVia: originSide.slice(0, -1).reverse(),
		arriveKms: extraKms(targetTravel, vInfT),
		arriveBound: false,
		arriveVia: targetSide.slice(0, -1),
		arrivePeriKms: periapsisSpeed(target.mu, rParkT, vInfT),
		transferDays: halfEllipseDays(centre.mu, rA, rB)
	};
}

/** Propulsive descent from the parking orbit, and the same with an atmosphere
 *  taking the entry — null where there is none to take it. */
function landingKms(travel: TravelBody): { plain: number; aero: number | null } {
	const vPark = circularSpeed(travel.mu, parkingRadiusKm(travel));
	const plain = arrivalCostFromSpeed(travel, vPark, 'landing', 'none').descentKms;
	if (!canAeroBrake(travel)) return { plain, aero: null };
	return { plain, aero: arrivalCostFromSpeed(travel, vPark, 'landing', 'aerocapture').descentKms };
}

/**
 * The map from one origin to a set of targets. A target the map cannot reach —
 * off the tree, or the origin itself — gets no route. Stops and edges are
 * shared between routes wherever the trip is the same, which is what makes it
 * a subway rather than a table.
 */
export function buildSubwayMap(
	bodies: SubwayBodies,
	originId: string,
	targetIds: readonly string[]
): SubwayMap {
	const stations = new Map<string, SubwayStation>();
	const edges = new Map<string, SubwayEdge>();
	const routes: SubwayRoute[] = [];

	const stop = (kind: StationKind, bodyId: string): string => {
		const id = stationId(kind, bodyId);
		if (!stations.has(id)) stations.set(id, { id, kind, bodyId });
		return id;
	};
	const join = (
		from: string,
		to: string,
		kind: EdgeKind,
		dvKms: number,
		via: string[] = [],
		aero = false
	): void => {
		const key = `${from}>${to}`;
		if (!edges.has(key)) edges.set(key, { from, to, kind, dvKms, via, aero });
	};

	const origin = bodies.get(originId);
	const originChain = chainOf(bodies, originId);
	if (!origin?.travel || !originChain) return { originId, stations: [], edges: [], routes: [] };

	// The trunk every route shares.
	const trunk: string[] = [];
	const originOrbit = stop('orbit', originId);
	if (origin.ground) {
		trunk.push(stop('surface', originId));
		join(trunk[0], originOrbit, 'ascent', ascentDv(origin.travel));
	}
	trunk.push(originOrbit);

	// The stationary orbit is the one high orbit of the origin worth a stop:
	// a Hohmann up from parking, circularised at the top.
	const rSync = origin.synchronousRadiusKm;
	const rPark = parkingRadiusKm(origin.travel);
	if (rSync !== undefined && rSync > rPark) {
		const gto = stop('transfer', originId);
		const geo = stop('stationary', originId);
		const departKms =
			ellipseSpeed(origin.mu, rPark, rPark, rSync) - circularSpeed(origin.mu, rPark);
		const circKms = circularSpeed(origin.mu, rSync) - ellipseSpeed(origin.mu, rSync, rPark, rSync);
		join(originOrbit, gto, 'depart', departKms);
		join(gto, geo, 'circularize', circKms);
		const path = [...trunk, gto, geo];
		routes.push({
			kind: 'stationary',
			targetId: originId,
			path,
			orbitKms: sumAlong(edges, path),
			surfaceKms: null,
			aeroOrbitKms: null,
			aeroSurfaceKms: null,
			transferDays: halfEllipseDays(origin.mu, rPark, rSync)
		});
	}

	for (const targetId of targetIds) {
		if (targetId === originId) continue;
		const target = bodies.get(targetId);
		const targetChain = chainOf(bodies, targetId);
		if (!target?.travel) continue;
		const meeting = targetChain && meet(originChain, targetChain);
		if (!meeting) continue;

		const x = crossing(bodies, origin, target, meeting);
		const path = [...trunk];
		const transfer = stop('transfer', x.transferId);

		if (x.departBound) {
			join(originOrbit, transfer, 'depart', x.departKms, x.departVia);
		} else {
			const escape = stop('escape', originId);
			join(originOrbit, escape, 'escape', escapeKms(origin.travel));
			join(escape, transfer, 'depart', x.departKms, x.departVia);
			path.push(escape);
		}
		path.push(transfer);

		const aero = canAeroBrake(target.travel);
		const targetOrbit = stop('orbit', targetId);
		if (x.arriveBound) {
			join(transfer, targetOrbit, 'arrive', x.arriveKms, x.arriveVia, aero);
		} else {
			const escape = stop('escape', targetId);
			join(transfer, escape, 'arrive', x.arriveKms, x.arriveVia, aero);
			join(escape, targetOrbit, 'circularize', escapeKms(target.travel), [], aero);
			path.push(escape);
		}
		path.push(targetOrbit);

		const orbitKms = sumAlong(edges, path);
		// Aero figures come from the kernel's own arrival pricing, which brakes
		// the whole approach at once rather than stop by stop.
		const beforeArrival = orbitKms - x.arriveKms - (x.arriveBound ? 0 : escapeKms(target.travel));
		const aeroOrbitKms = aero
			? beforeArrival +
				arrivalCostFromSpeed(target.travel, x.arrivePeriKms, 'low-orbit', 'aerocapture').captureKms
			: null;

		let surfaceKms: number | null = null;
		let aeroSurfaceKms: number | null = null;
		if (target.ground) {
			const landing = landingKms(target.travel);
			const surface = stop('surface', targetId);
			join(targetOrbit, surface, 'landing', landing.plain, [], landing.aero !== null);
			path.push(surface);
			surfaceKms = orbitKms + landing.plain;
			if (aero) {
				const direct = arrivalCostFromSpeed(
					target.travel,
					x.arrivePeriKms,
					'landing',
					'aerocapture'
				);
				aeroSurfaceKms = beforeArrival + direct.captureKms + direct.descentKms;
			}
		}

		routes.push({
			kind: 'body',
			targetId,
			path,
			orbitKms,
			surfaceKms,
			aeroOrbitKms,
			aeroSurfaceKms,
			transferDays: x.transferDays
		});
	}

	// Out of the root's well: the excess speed that escapes the root from the
	// orbit of the origin's outermost ancestor, carried down to the origin.
	const rootId = originChain[originChain.length - 1];
	if (rootId !== originId) {
		const root = bodies.get(rootId)!;
		const originSide = originChain.slice(0, -1).reverse();
		const top = bodies.get(originSide[0])!;
		const vInfTop =
			Math.sqrt((2 * root.mu) / top.orbitRadiusKm) - circularSpeed(root.mu, top.orbitRadiusKm);
		const vInf = vInfAlong(bodies, originSide, vInfTop);
		const escape = stop('escape', originId);
		const out = stop('escape', rootId);
		join(originOrbit, escape, 'escape', escapeKms(origin.travel));
		join(escape, out, 'depart', extraKms(origin.travel, vInf), originSide.slice(0, -1).reverse());
		const path = [...trunk, escape, out];
		routes.push({
			kind: 'escape',
			targetId: rootId,
			path,
			orbitKms: sumAlong(edges, path),
			surfaceKms: null,
			aeroOrbitKms: null,
			aeroSurfaceKms: null,
			transferDays: Infinity
		});
	}

	return { originId, stations: [...stations.values()], edges: [...edges.values()], routes };
}

function sumAlong(edges: ReadonlyMap<string, SubwayEdge>, path: readonly string[]): number {
	let total = 0;
	for (let i = 1; i < path.length; i++) {
		total += edges.get(`${path[i - 1]}>${path[i]}`)?.dvKms ?? 0;
	}
	return total;
}
