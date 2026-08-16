import {
	Box3,
	Group,
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
import { frameMapQuaternion } from '$lib/math/orientation';
import { bodyMeshColor } from '$lib/utils';
import { getSettings } from '$lib/state/settings.svelte';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { BodyObjects } from '../../types';
import { setLabelNote } from '../../label/factory';
import { applyShapeModelMaterial, makeShapeModelMaterial, setShapeModelMap } from './model-texture';
import { shapeModelSkipReason } from './shape-model-policy';
import { applyBodyOrientation } from './orientation-apply';

/** Types whose placeholder sphere is meaningless and hidden the moment a load
 *  starts, before the detail fetch confirms `model_name`. Planets and moons
 *  never enter this branch, so their sphere doesn't flicker during focus. */
export function isModelBearing(body: PositionedBody): boolean {
	const t = body.data.objectType;
	return (
		t === ObjectType.SPACECRAFT ||
		t === ObjectType.DEBRIS ||
		body.data.orbitalSource === OrbitalSource.SPICE_PROBE
	);
}

/** Subset of `metadata.json` the scene needs: the high-tier credit block and,
 *  when set, `scale_meters` — the model's real longest dimension, for sizing
 *  the mesh against scene units. Other exporter fields are ignored. */
export interface ModelBundleMeta {
	/** `shape_model` for natural bodies; absent/other for spacecraft. */
	kind?: string;
	/** Available GLB tiers; DAMIT bundles ship `high` only. */
	tiers?: string[];
	exports: {
		high: {
			credit: {
				name: string;
				url: string;
				license?: string;
			};
		};
	};
	scale_meters?: number;
	/** Model axis → spacecraft-body axis (1–2 pairs), correcting models authored
	 *  in a different convention (usually Y-up) than the CK/pointing frame. */
	frame_map?: Record<string, string>;
	/** Natural-body top-level credit + km bounds (shape-model bundles). */
	credit?: { name: string; url: string; license?: string };
	true_scale?: {
		max_extent_km: number;
		bounding_radius_km: number;
	};
}

/** Shared meshopt-decoder-registered loader, reused by every model fetch. */
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

/** Credit for a shape-model bundle: top-level credit if set, else the high-tier GLB's. */
export function shapeModelCredit(meta: ModelBundleMeta): {
	name: string;
	url: string;
	license?: string;
} {
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
 * Fetch and attach the body's 3D model into the overlay scene at unit-radius
 * scale, hiding the placeholder sphere. No-op when the body has no
 * `model_name`. Concurrent calls share one in-flight load, since callers chain
 * settle-time work (e.g. nomenclature reading `bo.model`) off its resolution.
 */
export function loadBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	if (bo.model) return Promise.resolve();
	if (bo.modelLoadPromise) return bo.modelLoadPromise;
	// Shape-model bundles share the overlay path too — extreme zoom corrupts
	// in-scene meshes, so both live at unit-radius.
	const p = (
		isModelBearing(bo.body)
			? loadSpacecraftModel(bo, modelScene, ctx)
			: loadNaturalBodyModel(bo, modelScene, ctx)
	).finally(() => {
		if (bo.modelLoadPromise === p) bo.modelLoadPromise = undefined;
	});
	bo.modelLoadPromise = p;
	return p;
}

async function loadSpacecraftModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	const epoch = bo.modelLoadEpoch ?? 0;
	// Model-bearing types show the cuboid/model, never the sphere placeholder.
	if (bo.mesh) bo.mesh.visible = false;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		// Hand-edited pointing spec drives the focused model's attitude; the
		// per-frame loop reads it off the body (default: south-toward-parent).
		bo.body.pointing = detail.global?.pointing;
		// CK-refit attitude supersedes pointing over its window; chunks load
		// lazily per playhead time, so building the track needs no I/O here.
		const attitudeManifest = detail.global?.attitude;
		if (attitudeManifest && (bo.modelLoadEpoch ?? 0) === epoch) {
			const probeId = bo.body.data.id.replace(/^probe-/, '');
			bo.body.attitudeTrack = createAttitudeTrack(probeId, attitudeManifest);
		}
		const slug = detail.global?.model_name;
		if (!slug) {
			// No GLB → halo only, with the close-range note.
			bo.noPhysical = 'model';
			return;
		}
		// Cancelled by a focus change mid-fetch; don't stack a stale overlay.
		if ((bo.modelLoadEpoch ?? 0) !== epoch) return;
		// Swap halo → spinner so the model can snap in cleanly. Loading state is
		// owned exclusively here; per-frame culling must not touch it.
		if (bo.mesh) bo.mesh.visible = false;
		setHaloLoading(bo, true);
		// Metadata fires alongside the GLB; frame_map must land before fitToUnitRadius.
		const metaPromise = fetchBundleMeta(slug);
		const gltf = await _loader.loadAsync(versionedUrl(`/v1/models/${slug}/high.glb`, 'models'));
		let meta: ModelBundleMeta | null = null;
		try {
			meta = await metaPromise;
		} catch (e) {
			// Metadata is a nice-to-have; missing/corrupt metadata.json shouldn't
			// tear down the loaded model.
			console.warn(`Failed to load model metadata for ${slug}:`, e);
		}
		if ((bo.modelLoadEpoch ?? 0) !== epoch || !bo.mesh) {
			disposeGltf(gltf.scene);
			return;
		}
		const baseFrame = meta?.frame_map ? frameMapQuaternion(meta.frame_map) : null;
		bo.body.modelBaseFrame = baseFrame ?? undefined;
		const root = withBaseFrame(gltf.scene, baseFrame);
		fitToUnitRadius(root);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		setHaloLoading(bo, false);
		if (meta) {
			// True-size from the model's longest dimension, so the overlay (sized
			// off radiusScene) renders to scale against the solar system.
			if (meta.scale_meters) {
				bo.body.data.radiusKm = meta.scale_meters / 2000; // half the longest dim, km
				bo.radiusScene = kmToScene(effectiveRadiusKm(bo.body.data));
			}
			ctx?.credits.registerModel({
				bodyId: bo.body.data.id,
				source: meta.exports.high.credit.url,
				organisation: meta.exports.high.credit.name,
				license: meta.exports.high.credit.license
			});
		}
	} finally {
		// Load aborted → back to the halo (never the sphere for these types).
		if (!bo.model) setHaloLoading(bo, false);
	}
}

/**
 * Load a natural body's shape-model mesh into the unit-radius overlay scene,
 * hiding the sphere. Normalised like a spacecraft model so `renderModelOverlay`
 * reproduces its on-screen size, oriented by the same IAU rotation the sphere
 * gets. No-op with no `model_name` or a non-shape-model bundle.
 */
async function loadNaturalBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	// Debug: shape mesh off → keep the textured (triaxial) sphere, skip the mesh.
	if (!getSettings().showShapeMesh) return;
	const epoch = bo.modelLoadEpoch ?? 0;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		const slug = detail.global?.model_name;
		if (!slug) return; // most bodies: sphere stays visible
		// Same gate the sources footer credits off; a DEM sphere wins here and
		// gets the displacement from loadBodyTexture.
		const skip = shapeModelSkipReason(detail.global);
		if (skip) {
			console.info(
				`Skipping ${detail.global?.render_quality ?? 'unrated'} shape mesh for ${bo.body.data.id}: ${skip}`
			);
			return;
		}
		// Model load can win the race against loadBodyTexture; make sure the
		// spin axis is on the body so per-frame orientation finds it.
		if (detail.global?.orientation && !bo.body.orientation) {
			applyBodyOrientation(bo, detail.global.orientation, ctx);
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
		// Sphere path owns texture loading/LOD; mirror it now (swapBodyTexture
		// keeps later tier upgrades in sync).
		const sphereMap = bo.mesh ? (bo.mesh.material as MeshStandardMaterial).map : null;
		if (sphereMap)
			setShapeModelMap(root, sphereMap, bodyMeshColor(bo.body.data), bo.body.data.color);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		if (bo.mesh) bo.mesh.visible = false;
		// Size the overlay against the real half-extent, matching radiusScene's
		// role: model radius 1 ↔ max_extent_km/2.
		if (meta.true_scale) {
			bo.radiusScene = kmToScene(meta.true_scale.max_extent_km / 2);
			// Backfill radiusKm from the model's calibrated scale when the chunk
			// shipped none, and drop no-size state — the halo yields to the mesh.
			const radiusKnown = Number.isFinite(bo.body.data.radiusKm) && bo.body.data.radiusKm > 0;
			if (!radiusKnown) bo.body.data.radiusKm = meta.true_scale.max_extent_km / 2;
			if (bo.noPhysical) {
				bo.noPhysical = undefined;
				setLabelNote(bo, false);
			}
		}
		const credit = shapeModelCredit(meta);
		const shape = detail.global?.model_source;
		ctx?.credits.registerModel({
			bodyId: bo.body.data.id,
			source: credit.url,
			organisation: credit.name,
			license: credit.license,
			provenance: shape?.provenance,
			technique: shape?.technique,
			archive: shape?.archive,
			archiveUrl: shape?.archive_url,
			mission: shape?.mission && {
				name: shape.mission.name,
				id: shape.mission.primary_id
			}
		});
	} finally {
		// Aborted / no model → keep the sphere visible.
		if (!bo.model && bo.mesh) bo.mesh.visible = true;
	}
}

/** Dispose the loaded model and restore the placeholder sphere. Bumps the
 *  load epoch so any concurrent `loadBodyModel` for `bo` aborts. */
export function unloadBodyModel(bo: BodyObjects): void {
	bo.modelLoadEpoch = (bo.modelLoadEpoch ?? 0) + 1;
	// Epoch bump aborts the in-flight load; drop its shared promise so the next
	// loadBodyModel starts fresh instead of latching onto the aborted one.
	bo.modelLoadPromise = undefined;
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
	bo.body.modelBaseFrame = undefined;
	if (bo.mesh && restoreSphere) bo.mesh.visible = true;
}

/** Create or remove the body's loading spinner: a plain DOM element pinned to
 *  the viewport (`.scene-label__loader`), outside the scene graph so it
 *  doesn't drift with per-frame position updates. Culling toggles `display`. */
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

/** Bake the bundle's model→body base rotation (`frame_map`) into a wrapper
 *  group, so per-frame attitude/pointing code keeps writing body-frame
 *  quaternions on the returned root. Null rotation returns the scene untouched. */
function withBaseFrame(scene: Object3D, q: Quaternion | null): Object3D {
	if (!q) return scene;
	const wrapper = new Group();
	scene.quaternion.copy(q);
	wrapper.add(scene);
	return wrapper;
}

/**
 * Uniformly scale + translate `root` so its bbox max-dim becomes 2 (inscribed
 * in a unit-radius sphere), bbox center at origin. Run before adding to the
 * overlay scene, whose camera then orbits a unit-radius target regardless of
 * the focused body's tiny scene-space radius.
 *
 * Records `centerOffset`/`feetOffset` in `userData` — the overlay seats a
 * landed probe on its feet, not bbox-centred. `occluderSpheres` feeds the
 * label-occlusion pass so CSS2D labels behind the model get hidden.
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

/** A model-hugging occluder blob: `center` is post-fit units in the root's
 *  rotation frame (excludes recentring `root.position`), `r` its radius. */
export interface OccluderSphere {
	center: Vector3;
	r: number;
}

/** Slices along the model's longest bbox axis — enough to hug a bent/elongated
 *  body (a single bounding ellipsoid lets labels peek through Eros's lobes),
 *  at trivial per-frame cost. */
const OCCLUDER_SLICES = 8;
/** Cap on vertices sampled for occluder fitting; scan meshes can be huge. */
const OCCLUDER_SAMPLE_TARGET = 4096;

/**
 * Fit a chain of spheres to the model for label occlusion: vertices bucketed
 * into slices along the longest bbox axis, one bounding sphere per slice. The
 * union hugs bent/elongated shapes far better than a single sphere/ellipsoid.
 * Centers are relative to `root.position` so the per-frame pass can rotate
 * them with the model: world = root.position + quat · center.
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
		if (bucket.length < 3) continue; // sliver — neighbours cover it
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
/** Cast-radius floor, so pathological geometry can't flip a point to the far side. */
const MODEL_MIN_RADIUS = 0.05;

const _castBodyDir = new Vector3();
const _castDir = new Vector3();
const _castOrigin = new Vector3();
const _castInvQuat = new Quaternion();
const _caster = new Raycaster();

/**
 * Surface distance (model units, from local origin) along a body-fixed lat/lon
 * direction, by ray-casting the overlay mesh from outside — outermost hit, so
 * concave terrain can't swallow the result. Direction rotates into the model's
 * current attitude (hit distances are rotation-invariant). `outNormal`, if
 * given, receives the hit's body-fixed surface normal. Null on a miss (scan holes).
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
