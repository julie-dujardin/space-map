/**
 * The measures of a map, without a map. They give the distance between two
 * places, the place on a body where the Sun is overhead, and the sunlight
 * that reaches a body. Each reads the export for its date and resolves with
 * the answer.
 *
 * Planets, moons and small bodies are placed as the map places them.
 * Spacecraft are not placed. A satellite of Earth is placed only near the
 * present. Use the map for both.
 */

import { SSB_ID, SUN_ID } from '$lib/constants';
import type { LonLat } from '$lib/flatmap/geometry';
import {
	chebyshevZoneParams,
	chunkIndexForJd,
	fetchMetadata,
	flatZoom,
	isChunkIndexed,
	type Metadata
} from '$lib/fetch/metadata';
import { bodyDataFromGlobal } from '$lib/fetch/objects/global-body';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { chebyshevPositionScene } from '$lib/fetch/position/chebyshev/propagate';
import { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { fetchElements } from '$lib/fetch/position/chunk';
import { rowId } from '$lib/fetch/position/elements/parse';
import { materializeBodyData } from '$lib/fetch/position/elements/row';
import { OrbitalSource } from '$lib/fetch/position/format';
import { getNutPrecAngles, loadSystemsGlobal, ownerIdFor } from '$lib/fetch/systems-global';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import type { Vec3 } from '$lib/scene/animation/math';
import { dateToJD, J2000_JD } from '$lib/time/jd';
import type { BodyData } from '$lib/types/objects';
import { placeAnchor, type Anchor, type AnchorBody, type OffsetKm } from './anchor';
import { sceneToEcliptic } from './camera';
import { subsolarAt, sunlightAt, type Ball } from './measure';

/** The export, opened at one date. */
interface Reading {
	jd: number;
	metadata: Metadata;
	chebyshev: ChebyshevStore | null;
}

/** A body where its parent is the origin. */
interface Offset {
	data: AnchorBody['data'];
	parentId: string;
	offset: Vec3;
}

interface Placed {
	data: AnchorBody['data'];
	centre: Vec3;
	/** The bodies it orbits, nearest first, without the barycentre of the
	 *  Solar System. */
	parents: string[];
}

let chebyshev: ChebyshevStore | null = null;
let queue: Promise<unknown> = Promise.resolve();

/** Runs one read at a time. The store keeps only the chunks of the last date
 *  it was asked for. */
function inTurn<T>(read: () => Promise<T>): Promise<T> {
	const turn = queue.then(read, read);
	queue = turn.catch(() => {});
	return turn;
}

async function open(date: Date): Promise<Reading> {
	const jd = dateToJD(date);
	const metadata = await fetchMetadata();
	if (!chebyshev) {
		const params = chebyshevZoneParams(metadata);
		if (params.size > 0) chebyshev = new ChebyshevStore(params);
	}
	try {
		await chebyshev?.ensure(jd).done;
	} catch (error) {
		// A store does not fetch a date twice. The next read makes a new store.
		chebyshev = null;
		throw error;
	}
	return { jd, metadata, chebyshev };
}

/** False before the body was discovered. NaN and undefined are always. */
function discovered(visibleFromDays: number | undefined, jd: number): boolean {
	return !(visibleFromDays !== undefined && jd - J2000_JD < visibleFromDays);
}

/** The row of a moon the ephemeris does not carry, from the elements fitted
 *  for the window `jd` is in. */
async function moonRow(id: string, { jd, metadata }: Reading): Promise<BodyData | null> {
	const zone = metadata.position.zones.moons;
	const zoom = zone && flatZoom(zone);
	if (!zoom) return null;
	const time = isChunkIndexed(zoom) ? String(chunkIndexForJd(zoom, jd)) : null;
	const cols = await fetchElements('moons', null, 0, time);
	for (let i = 0; i < cols.rowCount; i++) {
		if (rowId(cols, i) === id) return materializeBodyData(cols, i, new Map(), 'naif');
	}
	return null;
}

function elementsOffset(data: BodyData, jd: number): Vec3 | null {
	if (!discovered(data.visibleFromDays, jd)) return null;
	if (jd < data.validityStart || jd > data.validityEnd) return null;
	if (data.satrec) return sgp4PositionScene(data.satrec, jd);
	if (data.q != null) return parabolicToPositionJD(data, jd);
	if (data.a === 0) return [0, 0, 0];
	return orbitalElementsToPositionJD(data, jd);
}

async function locate(id: string, at: Reading): Promise<Offset | null> {
	const { jd } = at;
	if (at.chebyshev?.has(id)) {
		const body = at.chebyshev.body(id, jd);
		if (body && !discovered(body.visibleFromDays, jd)) return null;
		const offset = body && chebyshevPositionScene(body, jd);
		if (offset) {
			const { radiusKm, objectType } = body;
			return {
				data: { radiusKm, objectType, orbitalSource: OrbitalSource.SPICE },
				parentId: `naif-${body.parentId}`,
				offset
			};
		}
		// A planet or a moon is nowhere outside its ephemeris. A small body
		// falls back to its orbit.
		if (id.startsWith('naif-')) return null;
	}
	const data =
		(id.startsWith('naif-') ? await moonRow(id, at) : null) ??
		bodyDataFromGlobal(id, await fetchObjectDetail(id, false));
	const offset = data && elementsOffset(data, jd);
	return offset ? { data, parentId: data.parentId, offset } : null;
}

async function place(
	id: string,
	at: Reading,
	above: ReadonlySet<string> = new Set()
): Promise<Placed | null> {
	if (above.has(id)) return null;
	const own = await locate(id, at);
	if (!own) return null;
	if (own.parentId === SSB_ID) return { data: own.data, centre: own.offset, parents: [] };
	const parent = await place(own.parentId, at, new Set(above).add(id));
	if (!parent) return null;
	const [x, y, z] = parent.centre;
	return {
		data: own.data,
		centre: [x + own.offset[0], y + own.offset[1], z + own.offset[2]],
		parents: [own.parentId, ...parent.parents]
	};
}

/** The bodies whose shadow can be on `id`. They are the bodies it orbits, and
 *  the bodies of the ephemeris that orbit the same ones. */
function neighbours(id: string, { parents }: Placed, at: Reading): string[] {
	const ids = new Set(parents);
	for (const { body } of at.chebyshev?.bodiesAt(at.jd) ?? []) {
		if (parents.includes(`naif-${body.parentId}`)) ids.add(body.id);
	}
	ids.delete(id);
	return [...ids];
}

/** How `id` spins, as the map reads it. */
async function spinOf(id: string): Promise<Pick<AnchorBody, 'orientation' | 'nutPrec'>> {
	const [detail] = await Promise.all([fetchObjectDetail(id, false), loadSystemsGlobal()]);
	const orientation = detail.global?.orientation;
	const sums = detail.global?.nut_prec;
	const naif = /^naif-(-?\d+)$/.exec(id);
	const angles = naif ? getNutPrecAngles(ownerIdFor(parseInt(naif[1], 10))) : undefined;
	return { orientation, nutPrec: sums && angles ? { ...sums, angles } : undefined };
}

async function resolve(anchor: Anchor, at: Reading): Promise<Vec3 | null> {
	const placed = await place(anchor.body, at);
	if (!placed) return null;
	const spin = 'latitude' in anchor ? await spinOf(anchor.body) : {};
	return placeAnchor(anchor, { data: placed.data, ...spin }, placed.centre, at.jd);
}

/**
 * From one place to another at `date`, in kilometres on ecliptic J2000 axes.
 * Null when either end is nowhere at that date. Rejects when the data does
 * not load.
 */
export function offsetKm(from: Anchor, to: Anchor, date: Date): Promise<OffsetKm | null> {
	return inTurn(async () => {
		const at = await open(date);
		const a = await resolve(from, at);
		const b = a && (await resolve(to, at));
		// Subtract in scene units first. The ends can be an AU from the origin
		// and a kilometre apart.
		return a && b ? sceneToEcliptic([b[0] - a[0], b[1] - a[1], b[2] - a[2]]) : null;
	});
}

/** Kilometres between two places at `date`. Null and rejection are those of
 *  {@link offsetKm}. */
export async function distanceKm(from: Anchor, to: Anchor, date: Date): Promise<number | null> {
	const offset = await offsetKm(from, to, date);
	return offset && Math.hypot(...offset);
}

/**
 * The place on `id` where the Sun is overhead at `date`, in the frame of a
 * surface anchor. Null for the Sun, and for a body that is nowhere at that
 * date. Rejects when the data does not load.
 */
export function subsolarPoint(id: string, date: Date): Promise<LonLat | null> {
	return inTurn(async () => {
		if (id === SUN_ID) return null;
		const at = await open(date);
		const body = await place(id, at);
		const sun = body && (await place(SUN_ID, at));
		if (!body || !sun) return null;
		return subsolarAt({ data: body.data, ...(await spinOf(id)) }, body.centre, sun.centre, at.jd);
	});
}

/**
 * The part of the light of the Sun that reaches `id` at `date`, from 0 to 1.
 * It is 1 in full sunlight and 0 when all of the body is in the shadow of
 * another. Between the two, a part of its sunlit face is in shadow.
 *
 * Only the bodies of its own system can be in the way. These are the body it
 * orbits, and the planet and the moons that orbit the same body. Each is a
 * ball of the radius the map draws it with. The value is a mean over 1024
 * points of the sunlit face. Null and rejection are those of
 * {@link subsolarPoint}.
 */
export function sunlight(id: string, date: Date): Promise<number | null> {
	return inTurn(async () => {
		if (id === SUN_ID) return null;
		const at = await open(date);
		const body = await place(id, at);
		const sun = body && (await place(SUN_ID, at));
		if (!body || !sun) return null;
		const ball = ({ data, centre }: Placed): Ball => ({
			centre: sceneToEcliptic([
				centre[0] - body.centre[0],
				centre[1] - body.centre[1],
				centre[2] - body.centre[2]
			]),
			radiusKm: data.radiusKm
		});
		const occluders: Ball[] = [];
		for (const other of neighbours(id, body, at)) {
			const placed = await place(other, at);
			if (placed && placed.data.radiusKm > 0) occluders.push(ball(placed));
		}
		return sunlightAt(body.data.radiusKm > 0 ? body.data.radiusKm : 0, ball(sun), occluders);
	});
}
