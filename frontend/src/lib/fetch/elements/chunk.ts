import { fetchLabels, fetchIds } from '$lib/fetch/elements/fetch';
import { orbitalElementsToPosition } from '$lib/math/kepler';
import { fetchElements, type ElementColumns } from '$lib/fetch/elements/elements';
import { isMajorBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { Scale, BASE_ELEMENT_PATH, BASE_LABEL_PATH } from './constants';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { getLocale } from '$lib/paraglide/runtime.js';

const KM_PER_AU = 149_597_870.7;

function columnarToBody(
	cols: ElementColumns,
	idx: number,
	labels: Map<number, string>,
	idMap: Map<number, string>
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;

	return {
		id: idMap.get(idx)!,
		name: labels.get(idx) ?? null,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `naif-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Planet-scale: a is in km, n is in rev/day → convert to AU and deg/day
		a: isPlanetScale ? cols.a[idx] / KM_PER_AU : cols.a[idx],
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: isPlanetScale ? cols.n[idx] * 360 : cols.n[idx],
		epoch: cols.epochJd[idx]
	};
}

export class ChunkLoader {
	/**
	 * Fire-and-forget fetch of the three files for a zone/zoom/part, so the browser
	 * caches them before the caller needs to process them.
	 */
	static prefetch(zone: string, zoom: number, part: number): void {
		const lang = getLocale();
		fetch(`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.bin`);
		fetch(`${BASE_LABEL_PATH}/${lang}/${zone}/${zoom}/${part}.txt`);
		fetch(`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.txt`);
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

		const [cols, labels, idMap] = await Promise.all([
			fetchElements(zone, zoom, part),
			fetchLabels(zone, zoom, part),
			fetchIds(zone, zoom, part)
		]);

		console.log(`Loaded: ${cols.rowCount} objects`);

		for (let idx = 0; idx < cols.rowCount; idx++) {
			const a = cols.a[idx];
			const e = cols.e[idx];
			const objType = cols.objectType[idx] as ObjectType;

			if (!(a > 0) || e >= 1) {
				if (
					isMajorBody(objType) ||
					objType === ObjectType.BARYCENTER ||
					objType === ObjectType.LAGRANGE_POINT
				) {
					// Major bodies with near-zero orbits (e.g. planets at their barycenter) are
					// still valid — they sit at the parent position with zero offset.
					console.debug(
						`Body idx=${idx} id=${cols.id[idx]} (${ObjectType[objType]}) has a=${a} e=${e}, keeping as major body`
					);
				} else {
					console.debug(
						`Skipping idx=${idx} id=${cols.id[idx]} (${ObjectType[objType]}): invalid orbit a=${a} e=${e}`
					);
					continue;
				}
			}

			const parentId = cols.parentId[idx];
			if (!this.positions.has(parentId)) {
				console.warn(`Parent position not found for parentId=${parentId}, falling back to origin`);
			}
			const parentPos = this.positions.get(parentId) ?? this.positions.get(0)!;

			const body = columnarToBody(cols, idx, labels, idMap);
			const offset = orbitalElementsToPosition(body, date);
			const pos: [number, number, number] = [
				parentPos[0] + offset[0],
				parentPos[1] + offset[1],
				parentPos[2] + offset[2]
			];

			const id = cols.id[idx];

			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions) {
					this.barycenters.set(id, body);
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
