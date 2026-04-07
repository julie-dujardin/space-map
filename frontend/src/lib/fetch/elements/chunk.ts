import { fetchLabels, fetchIds } from '$lib/fetch/elements/fetch';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/kepler';
import { fetchElements, type ElementColumns } from '$lib/fetch/elements/elements';
import { isMajorBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { Scale, elementsBinUrl, elementIdsUrl, elementLabelsUrl } from './constants';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { getLocale } from '$lib/paraglide/runtime.js';
import { AU_KM } from '$lib/math/units';

/** Zone directory name for parabolic comets (OrbitClass.PAR.name in Python). */
const PARABOLIC_ZONE = 'PAR';

function columnarToBody(
	cols: ElementColumns,
	idx: number,
	labels: Map<number, string>,
	flags: Map<number, number>,
	idMap: Map<number, string>,
	zone: string
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const isParabolic = zone === PARABOLIC_ZONE;

	return {
		id: idMap.get(idx)!,
		name: labels.get(idx) ?? null,
		objectFileFlag: flags.get(idx) ?? 0,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `naif-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Planet-scale: a is in km, n is in rev/day → convert to AU and deg/day
		a: isPlanetScale ? cols.a[idx] / AU_KM : cols.a[idx],
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: isPlanetScale ? cols.n[idx] * 360 : cols.n[idx],
		epoch: cols.epochJd[idx],
		// Parabolic comets: binary encodes q in the 'a' slot and tp in the 'ma' slot
		...(isParabolic ? { q: cols.a[idx], tp: cols.ma[idx] } : {})
	};
}

export class ChunkLoader {
	/**
	 * Fire-and-forget fetch of the three files for a zone/zoom/part, so the browser
	 * caches them before the caller needs to process them.
	 */
	static prefetch(zone: string, zoom: number, part: number): void {
		const lang = getLocale();
		fetch(elementsBinUrl(zone, zoom, part));
		fetch(elementLabelsUrl(lang, zone, zoom, part));
		fetch(elementIdsUrl(zone, zoom, part));
	}

	// Track positions by ID for parent lookups (not reactive — local computation only)
	positions = new Map<number, [number, number, number]>();
	// Store barycenter orbital elements for planet orbit drawing
	barycenters = new Map<number, OrbitalElements>();

	constructor() {
		this.positions.set(0, [0, 0, 0]); // Solar System Barycenter
	}

	async process(zone: string, zoom: number, part: number, date: Date): Promise<PositionedBody[]> {
		const writePositions = this.barycenters.size === 0;
		const bodies: PositionedBody[] = [];

		const [cols, labelData, idMap] = await Promise.all([
			fetchElements(zone, zoom, part),
			fetchLabels(zone, zoom, part),
			fetchIds(zone, zoom, part)
		]);
		const { labels, flags } = labelData;

		console.log(`Loaded: ${cols.rowCount} objects`);

		for (let idx = 0; idx < cols.rowCount; idx++) {
			const a = cols.a[idx];
			const objType = cols.objectType[idx] as ObjectType;

			// Barycenters/Lagrange points with a=0 are structural (parent lookup tree);
			// all other bodies with a=0 are degenerate and should be skipped.
			if (a === 0 && objType !== ObjectType.BARYCENTER && objType !== ObjectType.LAGRANGE_POINT) {
				continue;
			}

			const parentId = cols.parentId[idx];
			if (!this.positions.has(parentId)) {
				console.warn(`Parent position not found for parentId=${parentId}, falling back to origin`);
			}
			const parentPos = this.positions.get(parentId) ?? this.positions.get(0)!;

			const body = columnarToBody(cols, idx, labels, flags, idMap, zone);
			const offset =
				a === 0
					? ([0, 0, 0] as [number, number, number])
					: body.q != null
						? parabolicToPosition(body, date)
						: orbitalElementsToPosition(body, date);
			if (!offset) {
				console.warn(
					`Failed to compute position for body id=${body.id} name=${body.name} (e=${body.e})`
				);
				continue;
			}
			const pos: [number, number, number] = [
				parentPos[0] + offset[0],
				parentPos[1] + offset[1],
				parentPos[2] + offset[2]
			];

			const id = cols.id[idx];

			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions) {
					// if parent is SSB, don't use it
					if (body.a > 0 && body.e < 1) {
						this.barycenters.set(id, body);
					}
					this.positions.set(id, pos);
				}
				bodies.push({ data: body, position: pos });
				continue;
			}

			if (writePositions && isMajorBody(objType)) {
				this.positions.set(id, pos);
			}

			if (isMajorBody(objType)) {
				const isMoon = objType === ObjectType.MOON;
				bodies.push({
					data: body,
					position: pos,
					orbitElements: isMoon ? body : (this.barycenters.get(parentId) ?? body),
					orbitCenter: isMoon ? parentPos : undefined
				});
			} else {
				bodies.push({
					data: body,
					position: pos
				});
			}
		}
		return bodies;
	}
}
