import {
	Box3,
	Mesh,
	MeshStandardMaterial,
	type Object3D,
	Quaternion,
	Raycaster,
	type Scene,
	Texture,
	Vector3
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { createAttitudeTrack } from '$lib/fetch/attitude/track';
import { versionedUrl } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { bodyMeshColor } from '$lib/utils';
import { getSettings } from '$lib/state/settings.svelte';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { BodyObjects } from '../../types';
import { setLabelNote } from '../../label/factory';
import { applyShapeModelMaterial, makeShapeModelMaterial, setShapeModelMap } from './model-texture';

/** Bodies whose shape model should render even though a DEM exists. By default
 *  a displacement map wins (textured relief sphere beats an untextured mesh —
 *  e.g. Dawn's Ceres/Vesta vs their convex lightcurve blobs); list exceptions
 *  here case by case. */
const PREFER_MODEL_OVER_DEM = new Set<string>([]);

/** Body types whose placeholder sphere is meaningless and should be hidden
 *  the moment a load starts (rather than waiting for the detail fetch to
 *  confirm `model_name`). Probes carry their own catalog; spacecraft/debris
 *  belong to the same family. Planets and moons never enter this branch, so
 *  their sphere doesn't flicker during focus. */
export function isModelBearing(body: PositionedBody): boolean {
	const t = body.data.objectType;
	return (
		t === ObjectType.SPACECRAFT ||
		t === ObjectType.DEBRIS ||
		body.data.orbitalSource === OrbitalSource.SPICE_PROBE
	);
}

/** Subset of `metadata.json` (per-model public bundle) the scene needs: the
 *  high-tier credit block (the GLB we fetched) and, when set, `scale_meters`
 *  — the real length of the model's longest dimension, used to size the mesh
 *  against scene units. The exporter writes more fields per tier
 *  (size/sha/stats/catalog/…) that we ignore. */
export interface ModelBundleMeta {
	/** `shape_model` for natural bodies; absent/other for spacecraft. Both
	 *  render in the unit-radius overlay scene. */
	kind?: string;
	/** Available GLB tiers; DAMIT bundles ship `high` only. */
	tiers?: string[];
	exports: {
		high: {
			credit: {
				name: string;
				url: string;
			};
		};
	};
	scale_meters?: number;
	/** Natural-body top-level credit + km bounds (shape-model bundles). */
	credit?: { name: string; url: string };
	true_scale?: {
		max_extent_km: number;
		bounding_radius_km: number;
	};
}

/** Shared meshopt-decoder-registered loader; every model fetch (focused body
 *  overlay, natural-body mesh, lineup meshes) reuses this one decoder path. */
export const modelLoader = new GLTFLoader();
modelLoader.setMeshoptDecoder(MeshoptDecoder);
const _loader = modelLoader;
const _bundleMetaCache = new Map<string, Promise<ModelBundleMeta>>();

export function fetchBundleMeta(slug: string): Promise<ModelBundleMeta> {
	let p = _bundleMetaCache.get(slug);
	if (!p) {
		p = fetch(versionedUrl(`/v1/models/${slug}/metadata.json`, 'models')).then((r) => r.json());
		_bundleMetaCache.set(slug, p);
	}
	return p;
}

/** Credit to display for a shape-model bundle: the natural-body top-level
 *  credit when set, else the high-tier GLB credit. */
export function shapeModelCredit(meta: ModelBundleMeta): { name: string; url: string } {
	return meta.credit ?? meta.exports.high.credit;
}

/**
 * Scene-units length of one overlay-model unit. Single source of truth for
 * mirroring the overlay in main-scene space: the overlay camera, label
 * occlusion, and surface-feature placement all derive from it.
 */
export function modelUnitScene(bo: BodyObjects): number {
	return bo.radiusScene;
}

/**
 * Fetch and attach the spacecraft 3D model into the overlay scene at unit-radius
 * scale, hiding the placeholder sphere. No-op when the body has no `model_name`.
 */
export async function loadBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	if (bo.model || bo.modelLoading) return;
	// Natural bodies with a shape-model bundle share the overlay path — extreme
	// zoom corrupts in-scene meshes, so both live in the unit-radius overlay.
	if (!isModelBearing(bo.body)) {
		await loadNaturalBodyModel(bo, modelScene, ctx);
		return;
	}
	const epoch = bo.modelLoadEpoch ?? 0;
	bo.modelLoading = true;
	// Model-bearing types show the cuboid/model, never the sphere placeholder.
	const modelBearing = isModelBearing(bo.body);
	if (modelBearing && bo.mesh) bo.mesh.visible = false;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		// Hand-edited pointing spec drives the focused model's attitude; the
		// per-frame loop reads it off the body (default: south-toward-parent).
		bo.body.pointing = detail.global?.pointing;
		// CK-refit attitude stream supersedes pointing over its window. Chunks
		// load lazily per playhead time, so the track is built without I/O here.
		const attitudeManifest = detail.global?.attitude;
		if (attitudeManifest && (bo.modelLoadEpoch ?? 0) === epoch) {
			const probeId = bo.body.data.id.replace(/^probe-/, '');
			bo.body.attitudeTrack = createAttitudeTrack(probeId, attitudeManifest);
		}
		const slug = detail.global?.model_name;
		if (!slug) {
			// Model-bearing → halo only (close-range note); natural bodies restore their sphere.
			if (modelBearing) {
				bo.noPhysical = 'model';
			} else if (bo.mesh) {
				bo.mesh.visible = true;
			}
			return;
		}
		// Cancelled by a focus change mid-fetch; don't stack a stale overlay.
		if ((bo.modelLoadEpoch ?? 0) !== epoch) return;
		// Swap halo → spinner so the model can snap in cleanly. The halo's loading
		// state is owned exclusively here; per-frame culling must not touch it.
		if (bo.mesh) bo.mesh.visible = false;
		setHaloLoading(bo, true);
		// Bundle metadata fires alongside the GLB so credit registers atomically.
		const metaPromise = fetchBundleMeta(slug);
		const gltf = await _loader.loadAsync(versionedUrl(`/v1/models/${slug}/high.glb`, 'models'));
		if ((bo.modelLoadEpoch ?? 0) !== epoch || !bo.mesh) {
			disposeGltf(gltf.scene);
			return;
		}
		const root = gltf.scene;
		fitToUnitRadius(root);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		setHaloLoading(bo, false);
		try {
			const meta = await metaPromise;
			// True-size the body from the model's longest dimension so the overlay
			// (sized off radiusScene) renders to scale against the solar system.
			if (meta.scale_meters && (bo.modelLoadEpoch ?? 0) === epoch) {
				bo.body.data.radiusKm = meta.scale_meters / 2000; // half the longest dim, km
				bo.radiusScene = kmToScene(effectiveRadiusKm(bo.body.data));
			}
			ctx?.credits.registerModel({
				bodyId: bo.body.data.id,
				source: meta.exports.high.credit.url,
				organisation: meta.exports.high.credit.name
			});
		} catch (e) {
			// Credit + scale are nice-to-haves; a missing/corrupt metadata.json
			// shouldn't tear down the loaded model.
			console.warn(`Failed to apply model metadata for ${slug}:`, e);
		}
	} finally {
		// Load aborted — restore the halo; only natural bodies put the sphere back.
		if (!bo.model) {
			if (bo.mesh && !modelBearing) bo.mesh.visible = true;
			setHaloLoading(bo, false);
		}
		bo.modelLoading = false;
	}
}

/**
 * Load a natural body's shape-model mesh into the unit-radius overlay scene,
 * hiding the sphere (and its displacement/self-shadow stack). Normalised like a
 * spacecraft model so `renderModelOverlay` reproduces its on-screen size;
 * oriented per frame by the same IAU rotation the sphere would get. No-op when
 * the body has no `model_name` or the bundle isn't a shape model.
 */
async function loadNaturalBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	// Debug: shape mesh off → keep the textured (triaxial) sphere, skip the mesh.
	if (!getSettings().showShapeMesh) return;
	const epoch = bo.modelLoadEpoch ?? 0;
	bo.modelLoading = true;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		const slug = detail.global?.model_name;
		if (!slug) return; // most bodies: sphere stays visible
		// A DEM sphere beats the shape model unless the body is listed as an
		// exception — loadBodyTexture attaches the displacement to the sphere.
		if (detail.global?.displacement && !PREFER_MODEL_OVER_DEM.has(bo.body.data.id)) return;
		// Model load can win the race against loadBodyTexture; make sure the spin
		// axis is on the body so the per-frame orientation pass finds it.
		if (detail.global?.orientation && !bo.body.orientation) {
			bo.body.orientation = detail.global.orientation;
		}
		const metaPromise = fetchBundleMeta(slug);
		const gltf = await _loader.loadAsync(versionedUrl(`/v1/models/${slug}/high.glb`, 'models'));
		if ((bo.modelLoadEpoch ?? 0) !== epoch) {
			disposeGltf(gltf.scene);
			return;
		}
		let meta: ModelBundleMeta;
		try {
			meta = await metaPromise;
		} catch (e) {
			disposeGltf(gltf.scene);
			console.warn(`Failed to load shape-model metadata for ${slug}:`, e);
			return;
		}
		// A non-shape-model bundle isn't a natural body; skip.
		if (meta.kind !== 'shape_model') {
			disposeGltf(gltf.scene);
			return;
		}
		const root = gltf.scene;
		fitToUnitRadius(root); // normalise to radius 1; overlay reproduces true size via radiusScene
		applyShapeModelMaterial(
			root,
			makeShapeModelMaterial(bo.body.data.color ?? bodyMeshColor(bo.body.data))
		);
		// The sphere path owns texture loading/LOD; mirror whatever it has now
		// (swapBodyTexture keeps later tier upgrades in sync).
		const sphereMap = bo.mesh ? (bo.mesh.material as MeshStandardMaterial).map : null;
		if (sphereMap)
			setShapeModelMap(root, sphereMap, bodyMeshColor(bo.body.data), bo.body.data.color);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		if (bo.mesh) bo.mesh.visible = false;
		// Size the overlay against the real half-extent (matches sphere radiusScene
		// role): model radius 1 ↔ max_extent_km/2, keeping true-to-scale framing.
		if (meta.true_scale) {
			bo.radiusScene = kmToScene(meta.true_scale.max_extent_km / 2);
			// Bodies whose chunk shipped no radius: the model's calibrated scale is
			// a real size, so backfill it (camera floor, LOD, framing) and drop the
			// no-size state — the halo must yield to the mesh, not sit on it.
			const radiusKnown = Number.isFinite(bo.body.data.radiusKm) && bo.body.data.radiusKm > 0;
			if (!radiusKnown) bo.body.data.radiusKm = meta.true_scale.max_extent_km / 2;
			if (bo.noPhysical) {
				bo.noPhysical = undefined;
				setLabelNote(bo, false);
			}
		}
		const credit = shapeModelCredit(meta);
		ctx?.credits.registerModel({
			bodyId: bo.body.data.id,
			source: credit.url,
			organisation: credit.name
		});
	} finally {
		// Aborted / no model → keep the sphere visible.
		if (!bo.model && bo.mesh) bo.mesh.visible = true;
		bo.modelLoading = false;
	}
}

/**
 * Dispose the loaded model and restore the placeholder sphere. Bumps the
 * load epoch so any concurrent `loadBodyModel` for `bo` aborts.
 */
export function unloadBodyModel(bo: BodyObjects): void {
	bo.modelLoadEpoch = (bo.modelLoadEpoch ?? 0) + 1;
	setHaloLoading(bo, false);
	// Model-bearing types revert to their dot, never the sphere.
	const restoreSphere = !isModelBearing(bo.body);
	const root = bo.model;
	if (!root) {
		if (bo.mesh && restoreSphere) bo.mesh.visible = true;
		return;
	}
	root.parent?.remove(root);
	disposeGltf(root);
	bo.model = null;
	bo.modelName = undefined;
	bo.body.pointing = undefined;
	bo.body.attitudeTrack = undefined;
	if (bo.mesh && restoreSphere) bo.mesh.visible = true;
}

/** Create or remove the body's loading spinner. It's a plain DOM element
 *  pinned to the viewport (see `.scene-label__loader` CSS) — outside the
 *  scene graph entirely so it doesn't drift with the focused body's
 *  per-frame world-position updates. Per-frame culling toggles `display`. */
function setHaloLoading(bo: BodyObjects, loading: boolean): void {
	if (loading) {
		if (bo.loadingEl) return;
		const el = document.createElement('div');
		el.className = 'scene-label__loader';
		el.style.display = 'none';
		document.body.appendChild(el);
		bo.loadingEl = el;
	} else if (bo.loadingEl) {
		bo.loadingEl.remove();
		bo.loadingEl = null;
	}
}

/**
 * Uniformly scale + translate `root` so its bbox max-dim becomes 2 (i.e.
 * inscribed in a unit-radius sphere) and its bbox center sits at origin.
 * Run before adding to the overlay scene. The overlay camera then orbits
 * a unit-radius target — no need to coordinate scale with the focused
 * body's tiny scene-space radius.
 *
 * Records `centerOffset`/`feetOffset` (scaled units) in `userData`: the overlay
 * seats a landed probe on its feet, not bbox-centred (which buries half of it).
 * `occluderSpheres` feeds the label-occlusion pass so CSS2D labels behind the
 * rendered model get hidden.
 */
function fitToUnitRadius(root: Object3D): void {
	root.updateMatrixWorld(true);
	const bbox = new Box3().setFromObject(root);
	const size = bbox.getSize(new Vector3());
	const center = bbox.getCenter(new Vector3());
	const maxDim = Math.max(size.x, size.y, size.z);
	if (maxDim <= 0) return;
	const k = 2 / maxDim;
	root.scale.multiplyScalar(k);
	root.position.copy(center).multiplyScalar(-k);
	root.userData.centerOffset = center.clone().multiplyScalar(k);
	root.userData.feetOffset = new Vector3(center.x, bbox.min.y, center.z).multiplyScalar(k);
	root.userData.halfExtents = size.clone().multiplyScalar(k * 0.5);
	root.userData.occluderSpheres = buildOccluderSpheres(root, size, k);
}

/** A model-hugging occluder blob: `center` is in the root's rotation frame
 *  (post-fit units, excludes the recentring `root.position`), `r` its radius. */
export interface OccluderSphere {
	center: Vector3;
	r: number;
}

/** Slices along the model's longest bbox axis. Enough to hug a bent/elongated
 *  body (one bounding ellipsoid lets labels peek through e.g. Eros's lobes)
 *  while staying a trivial per-frame cost in the occluder pass. */
const OCCLUDER_SLICES = 8;
/** Cap on vertices sampled for occluder fitting; scan meshes can be huge. */
const OCCLUDER_SAMPLE_TARGET = 4096;

/**
 * Fit a chain of spheres to the model for label occlusion: vertices bucketed
 * into slices along the longest bbox axis, one bounding sphere per slice. The
 * union hugs bent/elongated shapes far better than any single sphere/ellipsoid,
 * while each sphere reuses the tangent-cone occluder math unchanged.
 * Centers are stored relative to `root.position` so the per-frame pass can
 * rotate them with the model: world = root.position + quat · center.
 */
function buildOccluderSpheres(root: Object3D, size: Vector3, k: number): OccluderSphere[] {
	root.updateMatrixWorld(true);
	const axis = size.x >= size.y && size.x >= size.z ? 0 : size.y >= size.z ? 1 : 2;
	// Total vertex count first, so sampling strides uniformly across meshes.
	let total = 0;
	root.traverse((obj) => {
		if (obj instanceof Mesh) total += obj.geometry.attributes.position?.count ?? 0;
	});
	if (!total) return [];
	const stride = Math.max(1, Math.floor(total / OCCLUDER_SAMPLE_TARGET));

	const pts: Vector3[] = [];
	const v = new Vector3();
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		const pos = obj.geometry.attributes.position;
		if (!pos) return;
		for (let i = 0; i < pos.count; i += stride) {
			v.fromBufferAttribute(pos, i).applyMatrix4(obj.matrixWorld).sub(root.position);
			pts.push(v.clone());
		}
	});

	const half = (size.getComponent(axis) * k) / 2;
	const buckets: Vector3[][] = Array.from({ length: OCCLUDER_SLICES }, () => []);
	for (const p of pts) {
		const t = (p.getComponent(axis) + half) / (2 * half);
		const idx = Math.min(OCCLUDER_SLICES - 1, Math.max(0, Math.floor(t * OCCLUDER_SLICES)));
		buckets[idx].push(p);
	}

	const spheres: OccluderSphere[] = [];
	for (const bucket of buckets) {
		if (bucket.length < 3) continue; // degenerate sliver — neighbours cover it
		const center = new Vector3();
		for (const p of bucket) center.add(p);
		center.divideScalar(bucket.length);
		let r2 = 0;
		for (const p of bucket) r2 = Math.max(r2, center.distanceToSquared(p));
		spheres.push({ center, r: Math.sqrt(r2) });
	}
	return spheres;
}

/** Ray-cast start distance — safely beyond a unit-normalised model's bounding
 *  sphere (≤ √3) plus its recentring offset. */
const MODEL_CAST_DIST = 4;
/** Floor for the cast radius: pathological geometry (surface beyond the local
 *  origin along the cast line) must not flip a point to the far side. */
const MODEL_MIN_RADIUS = 0.05;

const _castBodyDir = new Vector3();
const _castDir = new Vector3();
const _castOrigin = new Vector3();
const _castInvQuat = new Quaternion();
const _caster = new Raycaster();

/**
 * Surface distance (model units, from the model's local origin) along the
 * body-fixed lat/lon direction, by ray-casting the overlay mesh from outside —
 * the outermost hit, so concave terrain can't swallow the result. The
 * direction is rotated into the model's current attitude rather than resetting
 * its quaternion (hit distances are rotation-invariant). `outNormal`, when
 * given, receives the hit's body-fixed surface normal. Returns null on a miss
 * (scan holes).
 */
export function castModelRadius(
	model: Object3D,
	latRad: number,
	lonRad: number,
	outNormal?: Vector3
): number | null {
	const cosLat = Math.cos(latRad);
	_castBodyDir.set(cosLat * Math.cos(lonRad), Math.sin(latRad), -cosLat * Math.sin(lonRad));
	_castDir.copy(_castBodyDir).applyQuaternion(model.quaternion);
	_castOrigin.copy(model.position).addScaledVector(_castDir, MODEL_CAST_DIST);
	_caster.set(_castOrigin, _castDir.negate());
	const hit = _caster.intersectObject(model, true)[0];
	if (!hit) return null;
	if (outNormal && hit.face) {
		outNormal
			.copy(hit.face.normal)
			.transformDirection(hit.object.matrixWorld)
			.applyQuaternion(_castInvQuat.copy(model.quaternion).invert());
	}
	return Math.max(MODEL_CAST_DIST - hit.distance, MODEL_MIN_RADIUS);
}

function enableShadows(root: Object3D): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		obj.castShadow = true;
		obj.receiveShadow = true;
	});
}

export function disposeGltf(root: Object3D): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		obj.geometry?.dispose();
		const mat = obj.material;
		const list = Array.isArray(mat) ? mat : [mat];
		for (const m of list) {
			if (!m) continue;
			for (const v of Object.values(m as Record<string, unknown>)) {
				if (v instanceof Texture) v.dispose();
			}
			m.dispose();
		}
	});
}
