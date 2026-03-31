import { fetchLabels, fetchIds } from '$lib/fetch/elements/fetch';
import { orbitalElementsToPosition } from '$lib/kepler';
import { fetchElements, type ElementColumns } from '$lib/fetch/elements/elements';
import { ObjectType, Scale, isMajorBody } from '$lib/format';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types';

const KM_PER_AU = 149_597_870.7;

function columnarToBody(
	cols: ElementColumns,
	idx: number,
	labels: Map<number, string>,
	idMap: Map<number, string>
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;

	return {
		id: cols.id[idx],
		fileId: idMap.get(idx) ?? null,
		name: labels.get(idx) ?? null,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: cols.parentId[idx],
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

export async function loadChunk(
	context: string,
	zoom: number,
	part: number,
	date: Date
): Promise<PositionedBody[]> {
	const [cols, labels, idMap] = await Promise.all([
		fetchElements(context, zoom, part),
		fetchLabels(context, zoom, part),
		fetchIds(context, zoom, part)
	]);

	console.log(`Loaded: ${cols.rowCount} objects`);

	// Track positions by NAIF ID for parent lookups (not reactive — local computation only)

	const positions = new Map<number, [number, number, number]>();
	positions.set(0, [0, 0, 0]); // Solar System Barycenter

	// Store barycenter orbital elements for planet orbit drawing

	const barycenters = new Map<number, OrbitalElements>();

	const bodies: PositionedBody[] = [];

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
		const parentPos = positions.get(parentId) ?? positions.get(0)!;

		const body = columnarToBody(cols, idx, labels, idMap);
		const offset = orbitalElementsToPosition(body, date);
		const pos: [number, number, number] = [
			parentPos[0] + offset[0],
			parentPos[1] + offset[1],
			parentPos[2] + offset[2]
		];

		const id = cols.id[idx];

		// Store position by ID for child lookups (body-type objects use NAIF IDs)
		if (isMajorBody(objType)) {
			positions.set(id, pos);
		}

		if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
			// Barycenters: store elements for planet orbit drawing, don't render
			barycenters.set(id, body);
			positions.set(id, pos);
			continue;
		}

		if (isMajorBody(objType)) {
			const isMoon = objType === ObjectType.MOON;
			bodies.push({
				data: body,
				position: pos,
				orbitElements: isMoon ? body : (barycenters.get(parentId) ?? body),
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
