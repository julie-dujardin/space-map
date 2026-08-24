/**
 * IAU planetary nomenclature labels — surface labels for craters, mons, etc.
 *
 * Labels are CSS2DObjects parented to the body's mesh, inheriting
 * `applyOrientation`'s spin and `applyRadiiToMesh`'s triaxial scale (pole on
 * +Y, prime meridian on +X, longitude increasing east). Shape-model bodies
 * parent to `bo.nomenclatureAnchor` instead — an identity-scale group with
 * the model's IAU orientation — with positions from ray-casting the model,
 * mapped to scene units via `modelUnitScene`.
 *
 * A label shows only when its on-screen diameter falls in the
 * `[MIN_FEATURE_PX, MAX_FEATURE_FRACTION · viewport]` band; survivors go
 * through a greedy AABB collision cull in priority order (largest diameter
 * first, fixed at attach so the per-frame loop is sort-free). Non-circular
 * feature types are dropped client-side until a vector dataset can render
 * their real geometry. Zero-diameter records fall back to
 * {@link DEFAULT_FEATURE_DIAMETER_M}.
 */

import { Group, Quaternion, Vector3, type Camera, type Object3D, type SphereGeometry } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import { effectiveRadiusKm, isSurfaceFeature, type PositionedBody } from '$lib/types/objects';
import { attachCanvasForwarders } from '$lib/scene/label/forward';
import { bodyFixedUnit, displacementsKmAt } from '$lib/scene/position/rendered-surface';
import { kmToScene } from '$lib/math/units';
import { acceptedBodyLabelRects } from '$lib/scene/label/culling';
import { castModelRadius, modelUnitScene } from '../body/model';
import type { BodyObjects } from '$lib/scene/types';

/** Effective focus for surface labels: a landed probe or a focused surface
 *  feature defers to its host body (where the labels actually live). */
export function nomenclatureBodyId(
	focused: PositionedBody | undefined,
	bodyObjects: Map<string, BodyObjects>
): string | undefined {
	if (!focused) return undefined;
	if (isSurfaceFeature(focused)) return focused.featureAnchor!.hostId;
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
 *  circle. Hidden until a dedicated vector layer can render them properly.
 *  Codes are IAU descriptor codes — see `FEATURE_TYPES` in the data package. */
const NON_CIRCULAR_TYPE_CODES = new Set([
	'CA', // catena — crater chains
	'CH', // chasma — deep elongated depressions
	'DO', // dorsum — ridges
	'FL', // fluctus — flow terrain
	'FO', // fossa — long narrow depressions
	'LI', // linea — elongate markings (Europa)
	'RI', // rima — fissures
	'RU', // rupes — scarps
	'VA' // vallis — valleys
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
		// Shape-model body: the sphere is hidden, so sample the model mesh.
		const surface = await sampleModelSurface(model, renderable);
		if (bo.nomenclatureLabels || bo.model !== model) return; // unloaded mid-sample
		const s = modelUnitScene(bo);
		for (let i = 0; i < n; i++) radial[i] = surface.radii[i] * s;
		bo.nomenclatureNormals = surface.normals;
		const anchor = new Group();
		// The model is recentred by a constant -centerOffset; mirror it (scaled)
		// so labels track the rendered surface, not the raw COM frame.
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

		// Lift labels onto the displaced terrain, else they float at the base
		// radius. Same height rows the probe seat / camera floor sample, so a
		// label and the terrain under it can't disagree.
		let dispKm: Float64Array | null = null;
		if (detail.global.displacement) {
			dispKm = await displacementsKmAt(
				bo,
				bo.body.data.id,
				detail.global.displacement,
				effectiveRadiusKm(bo.body.data),
				renderable.map((f) => ({ latRad: f.lat * DEG2RAD, lonRad: f.lon * DEG2RAD }))
			);
			if (bo.nomenclatureLabels || !bo.mesh) return;
		}
		for (let i = 0; i < n; i++) radial[i] = r + (dispKm ? kmToScene(dispKm[i]) : 0);
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
		el.dir = 'auto'; // Latin feature names must not bidi-reorder in an RTL page
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

		const [ux, uy, uz] = bodyFixedUnit(feature.lat * DEG2RAD, feature.lon * DEG2RAD);
		const rf = radial[i];
		const obj = new CSS2DObject(el);
		obj.position.set(rf * ux, rf * uy, rf * uz);
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

/** Features ray-cast per macrotask, so a many-feature attach can't block a frame. */
const MODEL_CAST_CHUNK = 8;

const _castNormal = new Vector3();

/**
 * Per-feature surface radius (model units) and body-fixed normal from
 * ray-casting the overlay mesh. Misses (scan holes) fall back to the
 * bbox-ellipsoid radius/normal. Normals feed the per-frame local-horizon
 * test, since the sphere-cap check alone lets near-limb labels leak through.
 */
async function sampleModelSurface(
	model: Object3D,
	features: readonly { lat: number; lon: number }[]
): Promise<{ radii: Float32Array; normals: Float32Array }> {
	const n = features.length;
	const radii = new Float32Array(n);
	const normals = new Float32Array(n * 3);
	const he = model.userData.halfExtents as Vector3 | undefined;
	for (let i = 0; i < n; i++) {
		if (i > 0 && i % MODEL_CAST_CHUNK === 0) await new Promise((r) => setTimeout(r));
		const latRad = features[i].lat * DEG2RAD;
		const lonRad = features[i].lon * DEG2RAD;
		const r = castModelRadius(model, latRad, lonRad, _castNormal);
		if (r !== null) {
			radii[i] = r;
		} else {
			const [dx, dy, dz] = bodyFixedUnit(latRad, lonRad);
			const hx = Math.max(he?.x ?? 1, 1e-3);
			const hy = Math.max(he?.y ?? 1, 1e-3);
			const hz = Math.max(he?.z ?? 1, 1e-3);
			radii[i] = 1 / Math.sqrt((dx / hx) ** 2 + (dy / hy) ** 2 + (dz / hz) ** 2);
			_castNormal.set(dx / (hx * hx), dy / (hy * hy), dz / (hz * hz)).normalize();
		}
		normals[i * 3] = _castNormal.x;
		normals[i * 3 + 1] = _castNormal.y;
		normals[i * 3 + 2] = _castNormal.z;
	}
	return { radii, normals };
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
	bo.nomenclatureNormals = undefined;
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
const _anchorQuat = new Quaternion();
const _normalWorld = new Vector3();

/** Grazing margin (sin of elevation) for the surface-normal horizon test.
 *  Labels whose terrain faces the camera shallower than this are hidden —
 *  the sphere-cap check alone lets labels just past the local limb of an
 *  irregular body leak through. */
const MODEL_HORIZON_MARGIN = 0.12;

/**
 * Per-frame visibility for feature labels. A label survives when its body is
 * focused and projects to at least {@link MIN_BODY_SCREEN_RADIUS_PX}, sits on
 * the front hemisphere within {@link LABEL_DISC_FRACTION} of the disc, and
 * its on-screen diameter falls in the `[MIN_FEATURE_PX, MAX_FEATURE_FRACTION
 * · min(screenW, screenH)]` band.
 *
 * The URL-selected feature is exempted from the size/disc-fraction checks
 * (but not the hemisphere check, so it can't bleed through the far side).
 * Non-active labels hide when the cloud overlay is visible.
 *
 * Survivors write their screen-space center to `bo.nomenclatureSX/SY` for the
 * collision pass; hidden labels get `NaN`.
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
	// screenR from the caller is small-angle; the true disc radius is
	// screenR / √(1 − (R/D)²), noticeably larger as the camera closes in —
	// without this, limb labels get clipped on zoom-in.
	const distSq = cdx * cdx + cdy * cdy + cdz * cdz;
	const rSq = bo.radiusScene * bo.radiusScene;
	const trueDiscR = screenR / Math.sqrt(Math.max(1 - rSq / distSq, 1e-6));
	const maxPxSq = (LABEL_DISC_FRACTION * trueDiscR) ** 2;
	const halfW = 0.5 * screenW;
	const halfH = 0.5 * screenH;

	// Shape-model bodies carry per-label body-fixed surface normals; rotate
	// them by the anchor's attitude for the per-label local-horizon test.
	const normals = bo.nomenclatureNormals;
	if (normals && bo.nomenclatureAnchor) bo.nomenclatureAnchor.getWorldQuaternion(_anchorQuat);

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
		// Perspective horizon reject, stricter than a plain hemisphere check
		// (which lets points just behind the perspective limb leak through).
		// Applies to the active feature too — CSS2D doesn't depth-test, so its
		// label would otherwise bleed through the planet from the far side.
		const dot = lx * cdx + ly * cdy + lz * cdz;
		const lenSqL = lx * lx + ly * ly + lz * lz;
		if (dot <= lenSqL) {
			lbl.visible = false;
			sxA[i] = NaN;
			syA[i] = NaN;
			continue;
		}
		// Local-horizon reject (shape models): the cap test treats each label
		// as sitting on its own sphere, letting labels near an irregular body's
		// limb leak through. Require the actual terrain normal to face the
		// camera above a grazing margin.
		if (normals) {
			_normalWorld
				.set(normals[i * 3], normals[i * 3 + 1], normals[i * 3 + 2])
				.applyQuaternion(_anchorQuat);
			const vx = cdx - lx;
			const vy = cdy - ly;
			const vz = cdz - lz;
			const vLen = Math.sqrt(vx * vx + vy * vy + vz * vz);
			const facing = _normalWorld.x * vx + _normalWorld.y * vy + _normalWorld.z * vz;
			if (facing < MODEL_HORIZON_MARGIN * vLen) {
				lbl.visible = false;
				sxA[i] = NaN;
				syA[i] = NaN;
				continue;
			}
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

// AABB pool for the collision cull. Module-level: only one focused body's
// labels go through here per frame. `h` carries vertical extent so mixed
// body-label (22px) and feature-label (16px) rects overlap-check correctly.
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
 * Greedy AABB collision cull for the focused body's feature labels, in
 * pre-sorted priority order (largest diameter first); each accepts unless it
 * overlaps an already-accepted box. The active feature is force-accepted
 * first so others defer to it. Pre-seeded with the body-label cull's rects
 * so feature labels lose to any body label. Text widths are measured lazily
 * once the label is in DOM, with a 60px fallback until then.
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
