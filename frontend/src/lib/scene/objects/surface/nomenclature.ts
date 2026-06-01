/**
 * IAU planetary nomenclature labels — surface labels for craters, mons, etc.
 *
 * Labels are CSS2DObjects parented to the body's mesh, so they inherit
 * `applyOrientation`'s spin and `applyRadiiToMesh`'s triaxial scale. Local
 * coordinates use the orientation basis (pole on +Y, prime meridian on +X,
 * planetographic longitude increasing east).
 *
 * Non-circular feature types (linear features, valleys, ridges, lineae) are
 * dropped client-side until the planned vector dataset can render their
 * actual geometry. The exclusion set is hardcoded here so swapping the layer
 * over once that lands is a one-file change.
 */

import { Vector3, type Camera, type SphereGeometry } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import type { BodyObjects } from '$lib/scene/types';

/** Body screen radius (px) at which feature labels start drawing. Roughly
 *  the point where a landed-probe-sized surface offset is large enough on
 *  screen to actually distinguish individual features. */
const MIN_BODY_SCREEN_RADIUS_PX = 128;

const DEG2RAD = Math.PI / 180;

/** Cap per body so dense surfaces (Moon at 9k features) stay legible. */
const MAX_LABELS_PER_BODY = 80;

/** Feature types whose geometry isn't usefully approximated by a center+radius
 *  circle. Hidden until a dedicated vector layer can render them properly. */
const NON_CIRCULAR_TYPE_CODES = new Set([
	'CA', // catena, catenae — crater chains
	'DO', // dorsum, dorsa — ridges
	'FL', // flumen, flumina — channels
	'FO', // fossa, fossae — long narrow depressions
	'LF', // landing site flow
	'LI', // lineae — linear features (Europa)
	'RI', // rima, rimae — fissures
	'RT', // rupes — scarp/cliff
	'VA', // vallis, valles — valleys
	'VL', // vallis lineae?
	'CH' // chasma, chasmata — deep elongated depressions
]);

export async function attachNomenclatureLabels(bo: BodyObjects): Promise<void> {
	if (bo.nomenclatureLabels || !bo.mesh) return;

	const detail = await fetchObjectDetail(bo.body.data.id, false);
	if (!detail.global?.has_nomenclature) return;
	if (bo.nomenclatureLabels || !bo.mesh) return;

	const features = await fetchBodyNomenclature(bo.body.data.id);
	if (bo.nomenclatureLabels || !bo.mesh) return;

	// Surface offset in mesh-local coords. The mesh's SphereGeometry vertices
	// sit at distance `parameters.radius` in local space — multiplying our
	// unit-sphere direction by that radius lands the label on the geometry's
	// surface, after which `applyRadiiToMesh`'s non-uniform mesh.scale carries
	// it to the correct ellipsoid surface in world space.
	const geometry = bo.mesh.geometry as SphereGeometry;
	const r = geometry.parameters?.radius;
	if (!r) return; // not a SphereGeometry (model-based body — can't place features)

	const renderable = features
		.filter((f) => !NON_CIRCULAR_TYPE_CODES.has(f.typeCode))
		.sort((a, b) => b.diameterM - a.diameterM)
		.slice(0, MAX_LABELS_PER_BODY);

	const labels: CSS2DObject[] = [];
	for (const feature of renderable) {
		const el = document.createElement('div');
		el.className = 'scene-feature-label';
		el.textContent = feature.name;

		const latRad = feature.lat * DEG2RAD;
		const lonRad = feature.lon * DEG2RAD;
		const cosLat = Math.cos(latRad);

		const obj = new CSS2DObject(el);
		obj.position.set(
			r * cosLat * Math.cos(lonRad),
			r * Math.sin(latRad),
			-r * cosLat * Math.sin(lonRad)
		);
		bo.mesh.add(obj);
		labels.push(obj);
	}
	bo.nomenclatureLabels = labels;
}

export function disposeNomenclatureLabels(bo: BodyObjects): void {
	if (!bo.nomenclatureLabels) return;
	for (const label of bo.nomenclatureLabels) {
		label.element.remove();
		label.parent?.remove(label);
	}
	bo.nomenclatureLabels = null;
}

const _bodyWorld = new Vector3();
const _camWorld = new Vector3();
const _labelWorld = new Vector3();

/**
 * Per-frame visibility for feature labels. Gated on:
 *
 *   1. focused body only — features are detail for what the user is looking at,
 *      not navigational context for the rest of the system,
 *   2. body screen radius ≥ {@link MIN_BODY_SCREEN_RADIUS_PX} — the sphere is
 *      big enough on screen that a per-feature surface offset is meaningful,
 *   3. backface culling per label — far-hemisphere features hidden via a
 *      camera-from-body / label-outward dot product.
 */
export function updateNomenclatureVisibility(
	bo: BodyObjects,
	isFocused: boolean,
	screenR: number,
	camera: Camera
): void {
	const labels = bo.nomenclatureLabels;
	if (!labels) return;

	if (!isFocused || screenR < MIN_BODY_SCREEN_RADIUS_PX) {
		for (const lbl of labels) lbl.visible = false;
		return;
	}

	bo.group.getWorldPosition(_bodyWorld);
	camera.getWorldPosition(_camWorld);
	const cdx = _camWorld.x - _bodyWorld.x;
	const cdy = _camWorld.y - _bodyWorld.y;
	const cdz = _camWorld.z - _bodyWorld.z;

	for (const lbl of labels) {
		lbl.getWorldPosition(_labelWorld);
		const lx = _labelWorld.x - _bodyWorld.x;
		const ly = _labelWorld.y - _bodyWorld.y;
		const lz = _labelWorld.z - _bodyWorld.z;
		lbl.visible = lx * cdx + ly * cdy + lz * cdz > 0;
	}
}
