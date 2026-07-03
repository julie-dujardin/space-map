/**
 * IAU planetary nomenclature labels — surface labels for craters, mons, etc.
 *
 * Labels are CSS2DObjects parented to the body's mesh, so they inherit
 * `applyOrientation`'s spin and `applyRadiiToMesh`'s triaxial scale. Local
 * coordinates use the orientation basis (pole on +Y, prime meridian on +X,
 * planetographic longitude increasing east).
 *
 * Shape-model bodies (hidden sphere, model in the unit-scale overlay scene)
 * parent labels to `bo.nomenclatureAnchor` instead — an identity-scale group
 * that gets the same IAU orientation as the model. Surface positions come from
 * ray-casting the model, mapped to main-scene units via `modelUnitScene`
 * (under that scale the overlay projects exactly like the main scene).
 *
 * Each label is shown only when its on-screen diameter falls in the
 * `[MIN_FEATURE_PX, MAX_FEATURE_FRACTION · viewport]` band; survivors are
 * passed through a greedy AABB collision cull, iterated in priority order
 * (largest effective diameter first — fixed at attach so the per-frame loop
 * is sort-free). Non-circular feature types (linear features, valleys,
 * ridges, lineae) are dropped client-side until the planned vector dataset
 * can render their actual geometry. Zero-diameter records (mostly Mars
 * albedo features) fall back to {@link DEFAULT_FEATURE_DIAMETER_M}.
 */

import { Group, Raycaster, Vector3, type Camera, type Object3D, type SphereGeometry } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { attachCanvasForwarders } from '$lib/scene/label/forward';
import { sampleDisplacementOffsets } from './displacement';
import { acceptedBodyLabelRects } from '$lib/scene/label/culling';
import { modelUnitScene } from '../body/model';
import type { BodyObjects } from '$lib/scene/types';

/** Effective focus for surface labels: a landed probe defers to its landing body. */
export function nomenclatureBodyId(
	focused: PositionedBody | undefined,
	bodyObjects: Map<string, BodyObjects>
): string | undefined {
	if (!focused) return undefined;
	const bo = bodyObjects.get(focused.data.id);
	if (bo?.isLanded) return focused.data.parentId;
	return focused.data.id;
}

const DEG2RAD = Math.PI / 180;

/** Body screen radius (px) below which we skip feature labels entirely. Cheap
 *  early-out before the per-feature projection loop. */
const MIN_BODY_SCREEN_RADIUS_PX = 128;

/** Fraction of the focused body's disc radius within which labels render. The
 *  outer ring is dropped because occlusion at grazing angles is noisy. */
const LABEL_DISC_FRACTION = 0.9;

/** Minimum on-screen feature diameter (px) for the label to draw. Below this
 *  the label text would be wider than the feature it names. */
const MIN_FEATURE_PX = 24;

/** Maximum on-screen feature diameter as a fraction of `min(screenW, screenH)`.
 *  Beyond this the feature dominates the view and naming it is redundant —
 *  hiding the big one lets contained sub-features compete in the collision pass. */
const MAX_FEATURE_FRACTION = 0.2;

/** Fallback diameter assigned to IAU records with no recorded extent (mostly
 *  Mars/Triton/Rhea albedo features). Small enough that they only surface at
 *  extreme zoom — accurate sizes would need a separate dataset. */
const DEFAULT_FEATURE_DIAMETER_M = 100;

/** Approximate text-box height (px) of `.scene-feature-label` (12px font +
 *  line-height + shadow). Used as the y-overlap threshold in the collision cull. */
const FEATURE_LINE_H = 16;

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

/** Click on a feature label — fired with the feature's id and the lat/lon
 *  the camera should fly to. Diameter is forwarded so the caller can pick a
 *  zoom level (small features need to fly closer than large ones). */
export type OnFeatureSelect = (
	featureId: number,
	lat: number,
	lon: number,
	diameterM: number
) => void;

export async function attachNomenclatureLabels(
	bo: BodyObjects,
	canvas: HTMLCanvasElement,
	onFeatureSelect?: OnFeatureSelect
): Promise<void> {
	if (bo.nomenclatureLabels || (!bo.mesh && !bo.model)) return;

	const detail = await fetchObjectDetail(bo.body.data.id, false);
	if (!detail.global?.has_nomenclature) return;
	if (bo.nomenclatureLabels) return;

	const features = await fetchBodyNomenclature(bo.body.data.id);
	if (bo.nomenclatureLabels) return;

	const renderable = features.filter((f) => !NON_CIRCULAR_TYPE_CODES.has(f.typeCode));
	renderable.sort((a, b) => {
		const da = a.diameterM > 0 ? a.diameterM : DEFAULT_FEATURE_DIAMETER_M;
		const db = b.diameterM > 0 ? b.diameterM : DEFAULT_FEATURE_DIAMETER_M;
		return db - da;
	});
	const n = renderable.length;

	// Per-feature radial label distance in parent-local units, and the parent
	// the CSS2DObjects attach to (sphere mesh or shape-model anchor group).
	const model = bo.model;
	const radial = new Float32Array(n);
	let parent: Object3D;
	if (model) {
		// Shape-model body: the sphere is hidden, so sample the overlay mesh.
		const modelRadii = await sampleModelRadii(model, renderable);
		if (bo.nomenclatureLabels || bo.model !== model) return; // unloaded mid-sample
		const s = modelUnitScene(bo);
		for (let i = 0; i < n; i++) radial[i] = modelRadii[i] * s;
		const anchor = new Group();
		// The overlay recentres the model by a constant -centerOffset; mirror it
		// (scaled) so labels track the rendered surface, not the raw COM frame.
		const centerOffset = model.userData.centerOffset as Vector3 | undefined;
		if (centerOffset) anchor.position.copy(centerOffset).multiplyScalar(-s);
		anchor.quaternion.copy(model.quaternion); // hold attitude until the next frame's pass
		bo.group.add(anchor);
		bo.nomenclatureAnchor = anchor;
		parent = anchor;
	} else {
		// Surface offset in mesh-local coords. The mesh's SphereGeometry vertices
		// sit at distance `parameters.radius` in local space — multiplying our
		// unit-sphere direction by that radius lands the label on the geometry's
		// surface, after which `applyRadiiToMesh`'s non-uniform mesh.scale carries
		// it to the correct ellipsoid surface in world space.
		const geometry = bo.mesh!.geometry as SphereGeometry;
		const r = geometry.parameters?.radius;
		if (!r) return; // not a SphereGeometry (virtual body — can't place features)

		// Lift labels onto the displaced terrain, else they float at the base radius.
		let dispOffsets: Float32Array | null = null;
		if (detail.global.displacement) {
			dispOffsets = await sampleDisplacementOffsets(
				detail.global.displacement,
				renderable.map((f) => ({ latRad: f.lat * DEG2RAD, lonRad: f.lon * DEG2RAD })),
				bo.radiusScene
			);
			if (bo.nomenclatureLabels || !bo.mesh) return;
		}
		for (let i = 0; i < n; i++) radial[i] = r + (dispOffsets ? dispOffsets[i] : 0);
		parent = bo.mesh!;
	}
	const labels: CSS2DObject[] = new Array(n);
	const diamsM = new Float32Array(n);
	const widths = new Float32Array(n).fill(-1);
	const sx = new Float32Array(n).fill(NaN);
	const sy = new Float32Array(n).fill(NaN);

	let fallbackCount = 0;
	for (let i = 0; i < n; i++) {
		const feature = renderable[i];
		const effDiam = feature.diameterM > 0 ? feature.diameterM : DEFAULT_FEATURE_DIAMETER_M;
		if (feature.diameterM <= 0) fallbackCount++;

		const el = document.createElement('div');
		el.className = 'scene-feature-label';
		el.textContent = feature.name;
		el.dataset.featureId = String(feature.featureId);

		// Re-dispatch wheel / drag gestures to the canvas — matches body labels
		// so scroll-zoom and orbit-drag keep working when the pointer is over a
		// feature label.
		attachCanvasForwarders(el, canvas);

		if (onFeatureSelect) {
			// Click-vs-drag guard mirroring the body-label pattern in
			// label/factory.ts:127–150. Without this, dragging the camera while
			// the pointer happens to start on a label would register as a click.
			let downX = 0;
			let downY = 0;
			el.addEventListener('pointerdown', (e: PointerEvent) => {
				downX = e.clientX;
				downY = e.clientY;
			});
			el.addEventListener('click', (e: MouseEvent) => {
				e.stopPropagation();
				const dx = e.clientX - downX;
				const dy = e.clientY - downY;
				if (dx * dx + dy * dy > 9) return;
				onFeatureSelect(feature.featureId, feature.lat, feature.lon, effDiam);
			});
		}

		const latRad = feature.lat * DEG2RAD;
		const lonRad = feature.lon * DEG2RAD;
		const cosLat = Math.cos(latRad);

		const rf = radial[i];
		const obj = new CSS2DObject(el);
		obj.position.set(
			rf * cosLat * Math.cos(lonRad),
			rf * Math.sin(latRad),
			-rf * cosLat * Math.sin(lonRad)
		);
		parent.add(obj);
		labels[i] = obj;
		diamsM[i] = effDiam;
	}

	if (fallbackCount > 0) {
		console.log(
			`[nomenclature] ${bo.body.data.id}: ${fallbackCount}/${n} features have no diameter — using ${DEFAULT_FEATURE_DIAMETER_M}m fallback`
		);
	}

	bo.nomenclatureLabels = labels;
	bo.nomenclatureDiamsM = diamsM;
	bo.nomenclatureWidths = widths;
	bo.nomenclatureSX = sx;
	bo.nomenclatureSY = sy;
	bo.nomenclatureActiveIndex = -1;
}

/** Ray-cast start distance — safely beyond a unit-normalised model's bounding
 *  sphere (≤ √3) plus its recentring offset. */
const MODEL_CAST_DIST = 4;
/** Features ray-cast per macrotask, so a many-feature attach can't block a frame. */
const MODEL_CAST_CHUNK = 8;
/** Floor for the sampled radius: pathological geometry (surface beyond the COM
 *  along the cast line) must not flip a label to the far side of the body. */
const MODEL_MIN_RADIUS = 0.05;

const _bodyDir = new Vector3();
const _castDir = new Vector3();
const _castOrigin = new Vector3();

/**
 * Radial surface distance (model units, from the model's local origin) per
 * feature, by ray-casting the overlay mesh from outside along the feature's
 * lat/lon direction — the outermost hit, so concave terrain can't swallow a
 * label. Directions are rotated into the model's current attitude rather than
 * resetting its quaternion (hit distances are rotation-invariant). Misses
 * (scan holes) fall back to the bbox-ellipsoid radius.
 */
async function sampleModelRadii(
	model: Object3D,
	features: readonly { lat: number; lon: number }[]
): Promise<Float32Array> {
	const raycaster = new Raycaster();
	const out = new Float32Array(features.length);
	const he = model.userData.halfExtents as Vector3 | undefined;
	for (let i = 0; i < features.length; i++) {
		if (i > 0 && i % MODEL_CAST_CHUNK === 0) await new Promise((r) => setTimeout(r));
		const latRad = features[i].lat * DEG2RAD;
		const lonRad = features[i].lon * DEG2RAD;
		const cosLat = Math.cos(latRad);
		_bodyDir.set(cosLat * Math.cos(lonRad), Math.sin(latRad), -cosLat * Math.sin(lonRad));
		_castDir.copy(_bodyDir).applyQuaternion(model.quaternion);
		_castOrigin.copy(model.position).addScaledVector(_castDir, MODEL_CAST_DIST);
		raycaster.set(_castOrigin, _castDir.negate());
		const hit = raycaster.intersectObject(model, true)[0];
		if (hit) {
			out[i] = Math.max(MODEL_CAST_DIST - hit.distance, MODEL_MIN_RADIUS);
		} else if (he) {
			const qx = _bodyDir.x / Math.max(he.x, 1e-3);
			const qy = _bodyDir.y / Math.max(he.y, 1e-3);
			const qz = _bodyDir.z / Math.max(he.z, 1e-3);
			out[i] = 1 / Math.sqrt(qx * qx + qy * qy + qz * qz);
		} else {
			out[i] = 1;
		}
	}
	return out;
}

/** Flip the `--active` class on the focused body's feature labels so the
 *  currently-selected feature renders larger/bolder. No-op when labels haven't
 *  attached yet — the renderer calls this again after attach via the
 *  `selectedFeatureId` arg of {@link attachNomenclatureLabels}. */
export function setActiveFeatureLabel(bo: BodyObjects, featureId: number | null): void {
	const labels = bo.nomenclatureLabels;
	if (!labels) return;
	const target = featureId === null ? null : String(featureId);
	let activeIdx = -1;
	for (let i = 0; i < labels.length; i++) {
		const el = labels[i].element as HTMLElement;
		const isActive = el.dataset.featureId === target;
		el.classList.toggle('scene-feature-label--active', isActive);
		if (isActive) activeIdx = i;
	}
	bo.nomenclatureActiveIndex = activeIdx;
}

export function disposeNomenclatureLabels(bo: BodyObjects): void {
	if (!bo.nomenclatureLabels) return;
	for (const label of bo.nomenclatureLabels) {
		label.element.remove();
		label.parent?.remove(label);
	}
	if (bo.nomenclatureAnchor) {
		bo.nomenclatureAnchor.parent?.remove(bo.nomenclatureAnchor);
		bo.nomenclatureAnchor = null;
	}
	bo.nomenclatureLabels = null;
	bo.nomenclatureDiamsM = undefined;
	bo.nomenclatureWidths = undefined;
	bo.nomenclatureSX = undefined;
	bo.nomenclatureSY = undefined;
	bo.nomenclatureActiveIndex = undefined;
}

const _bodyWorld = new Vector3();
const _camWorld = new Vector3();
const _labelWorld = new Vector3();
const _bodyNdc = new Vector3();
const _labelNdc = new Vector3();

/**
 * Per-frame visibility for feature labels. A label survives when its body is
 * focused and projects to at least {@link MIN_BODY_SCREEN_RADIUS_PX}, the
 * label is on the front hemisphere, sits inside {@link LABEL_DISC_FRACTION}
 * of the projected disc, and its on-screen diameter falls in the
 * `[MIN_FEATURE_PX, MAX_FEATURE_FRACTION · min(screenW, screenH)]` band.
 *
 * The URL-selected feature (`bo.nomenclatureActiveIndex`) is exempted from
 * the per-feature size / disc-fraction checks so a tiny or near-limb selected
 * feature is still shown — but the hemisphere check still applies so the
 * label doesn't bleed through the planet from the far side.
 *
 * When the body's cloud overlay is visible, non-active labels are hidden so
 * they don't read through the clouds; the active feature still survives.
 *
 * Survivors get their screen-space center written to `bo.nomenclatureSX/SY`
 * for the collision pass; hidden labels get `NaN` so the cull skips them.
 */
export function updateNomenclatureVisibility(
	bo: BodyObjects,
	isFocused: boolean,
	screenR: number,
	camera: Camera,
	screenW: number,
	screenH: number
): void {
	const labels = bo.nomenclatureLabels;
	if (!labels) return;

	if (!isFocused || screenR < MIN_BODY_SCREEN_RADIUS_PX) {
		for (const lbl of labels) lbl.visible = false;
		return;
	}

	const diamsM = bo.nomenclatureDiamsM!;
	const sxA = bo.nomenclatureSX!;
	const syA = bo.nomenclatureSY!;
	const activeIdx = bo.nomenclatureActiveIndex ?? -1;
	const n = labels.length;
	const cloudsVisible = !!bo.clouds?.mesh.visible;

	const realRadiusM = effectiveRadiusKm(bo.body.data) * 1000;
	const pxPerMeter = screenR / realRadiusM;
	const maxFeaturePx = MAX_FEATURE_FRACTION * Math.min(screenW, screenH);

	// Fast path: labels are pre-sorted by effective diameter desc, so if the
	// largest feature can't clear MIN_FEATURE_PX, none can. Same shortcut when
	// clouds occlude the surface — every non-active label is suppressed.
	// Skipped when an active feature is set so its label still gets projected.
	if (activeIdx < 0 && (n === 0 || cloudsVisible || diamsM[0] * pxPerMeter < MIN_FEATURE_PX)) {
		for (const lbl of labels) lbl.visible = false;
		return;
	}

	bo.group.getWorldPosition(_bodyWorld);
	camera.getWorldPosition(_camWorld);
	const cdx = _camWorld.x - _bodyWorld.x;
	const cdy = _camWorld.y - _bodyWorld.y;
	const cdz = _camWorld.z - _bodyWorld.z;

	_bodyNdc.copy(_bodyWorld).project(camera);
	// `screenR` from the caller is R/D · f (small-angle). The true projected
	// disc radius is R·f / √(D² − R²) = screenR / √(1 − (R/D)²) — equal to
	// screenR when D ≫ R, but visibly larger as the camera closes in.
	// Without this correction the limb labels get clipped on zoom-in.
	const distSq = cdx * cdx + cdy * cdy + cdz * cdz;
	const rSq = bo.radiusScene * bo.radiusScene;
	const trueDiscR = screenR / Math.sqrt(Math.max(1 - rSq / distSq, 1e-6));
	const maxPxSq = (LABEL_DISC_FRACTION * trueDiscR) ** 2;
	const halfW = 0.5 * screenW;
	const halfH = 0.5 * screenH;

	for (let i = 0; i < n; i++) {
		const lbl = labels[i];
		const isActive = i === activeIdx;
		const featurePx = diamsM[i] * pxPerMeter;
		const occluded = cloudsVisible && !isActive;
		if (occluded || (!isActive && (featurePx < MIN_FEATURE_PX || featurePx > maxFeaturePx))) {
			lbl.visible = false;
			sxA[i] = NaN;
			syA[i] = NaN;
			continue;
		}
		lbl.getWorldPosition(_labelWorld);
		const lx = _labelWorld.x - _bodyWorld.x;
		const ly = _labelWorld.y - _bodyWorld.y;
		const lz = _labelWorld.z - _bodyWorld.z;
		// Perspective horizon reject: P is on the visible cap iff its outward
		// normal faces camera, (K − P) · (P − C) > 0, i.e. K'·L > L·L. Strictly
		// tighter than the `> 0` hemisphere check, which would let points just
		// behind the perspective limb leak through and project into the disc.
		// Applies to the active feature too — otherwise its DOM label bleeds
		// through the planet from the far side (CSS2D doesn't depth-test).
		const dot = lx * cdx + ly * cdy + lz * cdz;
		const lenSqL = lx * lx + ly * ly + lz * lz;
		if (dot <= lenSqL) {
			lbl.visible = false;
			sxA[i] = NaN;
			syA[i] = NaN;
			continue;
		}
		_labelNdc.copy(_labelWorld).project(camera);
		const dxPx = (_labelNdc.x - _bodyNdc.x) * halfW;
		const dyPx = (_labelNdc.y - _bodyNdc.y) * halfH;
		if (!isActive && dxPx * dxPx + dyPx * dyPx >= maxPxSq) {
			lbl.visible = false;
			sxA[i] = NaN;
			syA[i] = NaN;
			continue;
		}
		lbl.visible = true;
		sxA[i] = (_labelNdc.x * 0.5 + 0.5) * screenW;
		syA[i] = (-_labelNdc.y * 0.5 + 0.5) * screenH;
	}
}

// AABB pool for the collision cull. Module-level — only one focused body's
// labels go through here per frame, so a single pool is fine. `h` carries the
// rect's vertical extent so mixed body-label (22px) and feature-label (16px)
// rects can be checked for box overlap rather than a single fixed threshold.
type Rect = { left: number; right: number; y: number; h: number };
const _acceptedNom: Rect[] = [];

function ensureRect(idx: number): Rect {
	let r = _acceptedNom[idx];
	if (!r) {
		r = { left: 0, right: 0, y: 0, h: 0 };
		_acceptedNom[idx] = r;
	}
	return r;
}

/** Try to accept label `i` into the running accepted set. With `forceAccept`,
 *  overlap is ignored and the label is added regardless — used so the focused
 *  feature claims its rect first, and every other label has to defer to it. */
function tryAcceptNomenclature(
	bo: BodyObjects,
	i: number,
	forceAccept: boolean,
	acceptedCount: number
): number {
	const labels = bo.nomenclatureLabels!;
	const lbl = labels[i];
	if (!lbl.visible) return acceptedCount;
	const cx = bo.nomenclatureSX![i];
	const cy = bo.nomenclatureSY![i];
	if (Number.isNaN(cx) || Number.isNaN(cy)) return acceptedCount;
	const widths = bo.nomenclatureWidths!;
	let w = widths[i];
	if (w < 0) {
		const measured = lbl.element.offsetWidth;
		if (measured > 0) {
			widths[i] = measured;
			w = measured;
		} else {
			// CSS2DRenderer hasn't appended the element yet — fall back this
			// frame; the cache stays at -1 so we re-measure next frame.
			w = 60;
		}
	}
	const halfW = w * 0.5;
	const left = cx - halfW;
	const right = cx + halfW;
	if (!forceAccept) {
		for (let j = 0; j < acceptedCount; j++) {
			const a = _acceptedNom[j];
			const yThreshold = (a.h + FEATURE_LINE_H) * 0.5;
			if (left < a.right && right > a.left && Math.abs(cy - a.y) < yThreshold) {
				lbl.visible = false;
				return acceptedCount;
			}
		}
	}
	const a = ensureRect(acceptedCount);
	a.left = left;
	a.right = right;
	a.y = cy;
	a.h = FEATURE_LINE_H;
	return acceptedCount + 1;
}

/**
 * Greedy AABB collision cull for the focused body's feature labels. Labels
 * are iterated in pre-sorted priority order (largest effective diameter
 * first); each accepts unless its box overlaps an already-accepted box, in
 * which case it's hidden for the frame. The active feature (if any) is
 * accepted first and force-accepted so it always survives and others defer
 * to it. The accepted pool is pre-seeded with the body-label cull's accepted
 * rects so feature labels lose to any body label. Text widths are measured
 * lazily on the first frame the label is in DOM (first measure may return 0;
 * we retry next frame with a 60px fallback).
 */
export function cullOverlappingNomenclatureLabels(bo: BodyObjects): void {
	const labels = bo.nomenclatureLabels;
	if (!labels) return;
	const activeIdx = bo.nomenclatureActiveIndex ?? -1;

	let acceptedCount = 0;
	// Seed with body-label rects from the last body cull (every-3rd-frame; the
	// rects drift slightly between culls, accepted) so features get hidden
	// whenever their box would overlap any body label.
	const bodyRects = acceptedBodyLabelRects;
	const bodyCount = bodyRects.count;
	for (let i = 0; i < bodyCount; i++) {
		const b = bodyRects.rects[i];
		const a = ensureRect(acceptedCount++);
		a.left = b.left;
		a.right = b.right;
		a.y = b.y;
		a.h = b.h;
	}
	if (activeIdx >= 0) {
		acceptedCount = tryAcceptNomenclature(bo, activeIdx, true, acceptedCount);
	}
	for (let i = 0; i < labels.length; i++) {
		if (i === activeIdx) continue;
		acceptedCount = tryAcceptNomenclature(bo, i, false, acceptedCount);
	}
}
