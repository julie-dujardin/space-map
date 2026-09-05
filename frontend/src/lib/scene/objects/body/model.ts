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
import { kmToScene, sceneToKm } from '$lib/math/units';
import { frameMapQuaternion } from '$lib/math/orientation';
import { bodyMeshColor } from '$lib/utils';
import { getSettings } from '$lib/state/settings.svelte';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { BodyObjects } from '../../types';
import { setLabelAnnotation } from '../../label/annotations';
import { applyShapeModelMaterial, makeShapeModelMaterial, setShapeModelMap } from './model-texture';
import { shapeModelSkipReason } from './shape-model-policy';
import { applyBodyOrientation } from './orientation-apply';
import { attachEclipseShadowToBody } from '../surface/eclipse-shadow';
import { buildRadialIndex, radialIndexDistance, type RadialIndex } from './model-radial';

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

export interface ModelCredit {
	name: string;
	url: string;
	license?: string;
}

export type ModelTier = 'low' | 'high';

export interface ModelTierExport {
	credit: ModelCredit;
	/** GLB size on the CDN; what a small drawing weighs its tier choice against. */
	size_bytes?: number;
}

/** Subset of `metadata.json` the scene needs: the high-tier credit block and,
 *  when set, `scale_meters` — the model's real longest dimension, for sizing
 *  the mesh against scene units — beside the body-vs-deployed split that sizes
 *  the halo and seats the mesh. Other exporter fields are ignored. */
export interface ModelBundleMeta {
	/** `shape_model` for natural bodies; absent/other for spacecraft. */
	kind?: string;
	/** Available GLB tiers; DAMIT bundles ship `high` only. */
	tiers?: string[];
	exports: {
		high: ModelTierExport;
		/** A bundle can source its tiers from different catalogues (Cassini's
		 *  high tier is ESA's, its low tier NASA's), so whoever loads `low`
		 *  credits this one. */
		low?: ModelTierExport;
	};
	scale_meters?: number;
	/** The craft body's longest dimension as a fraction of the mesh's. Below 1
	 *  where the model draws booms or wire antennas around a much smaller craft
	 *  (Ulysses: a 63 m dipole around a 2 m bus). */
	body_span_ratio?: number;
	/** The body centre's offset from the mesh's bounding-box centre, in post-fit
	 *  units (the mesh spans 2 of them). Non-zero where the craft sits off to one
	 *  side of what it deploys, so the mesh centres on the craft, not the box. */
	model_anchor?: [number, number, number];
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
export function shapeModelCredit(meta: ModelBundleMeta): ModelCredit {
	return meta.credit ?? meta.exports.high.credit;
}

/** The cheap tier where a bundle ships one. A shape model's tiers are the same
 *  surface decimated (20k triangles against 400k), and a lineup disc is far too
 *  small to tell them apart, so it takes this one. */
export function cheapTier(meta: ModelBundleMeta): ModelTier {
	return meta.tiers?.includes('low') ? 'low' : 'high';
}

/** Bytes past which a small drawing gives up on a craft's best mesh. Three
 *  bundles cross it — the ISS at a million triangles, MAVEN, ICESat-2 — and
 *  nothing they carry survives being drawn 100 px wide. */
const CRAFT_TIER_BUDGET = 4_000_000;

/** The tier a craft lineup loads. A spacecraft's two tiers are often different
 *  models from different catalogues rather than one decimated (Cassini's low is
 *  NASA's, its high ESA's), so `low` is not simply a cheaper `high` — it can be
 *  a cruder machine. Prefer `high`, which is also what the main scene loads, so
 *  focusing the craft reuses the download. */
export function craftTier(meta: ModelBundleMeta): ModelTier {
	const size = meta.exports.high.size_bytes ?? 0;
	return size > CRAFT_TIER_BUDGET ? cheapTier(meta) : 'high';
}

/** Credit for the tier actually drawn — the two can name different catalogues. */
export function modelTierCredit(meta: ModelBundleMeta, tier: ModelTier): ModelCredit {
	return meta.exports[tier]?.credit ?? meta.exports.high.credit;
}

/**
 * Scene-units length of one model unit (models are normalised to unit radius
 * at load). Single source of truth for the mount's scale, the overlay camera,
 * label occlusion, and surface-feature placement.
 *
 * Craft that deploy booms carry their own factor: `radiusScene` is the body,
 * which the halo and the label are sized on, while the mesh is drawn on the
 * full span it reaches.
 */
export function modelUnitScene(bo: BodyObjects): number {
	return bo.modelUnitOverride ?? bo.radiusScene;
}

/** Mounts of natural-body models currently attached in the main scene (1–2
 *  alive: the focused body's, or a focused feature's host's). Pointer raycasts
 *  hit these recursively; `userData.pickBody` resolves hits to the body. */
export const attachedModelRoots = new Set<Object3D>();

/**
 * Mount the normalised model in the main scene: a wrapper scaled to
 * `modelUnitScene` under the body's group, so the model rides the body's
 * per-frame position while all unit-scale conventions (occluder spheres,
 * recentring offsets, surface casts) stay valid inside it.
 */
function mountModel(bo: BodyObjects, root: Object3D): void {
	const wrapper = new Group();
	wrapper.scale.setScalar(modelUnitScene(bo));
	wrapper.userData.pickBody = bo.body;
	wrapper.add(root);
	bo.group.add(wrapper);
	bo.modelRoot = wrapper;
	bo.model = root;
	attachedModelRoots.add(wrapper);
}

/** Attach the analytical eclipse factor to every standard material under
 *  `root`, sharing the body's self-position uniform so the per-frame eclipse
 *  pass drives the model exactly like it drives the sphere. */
function attachModelEclipse(bo: BodyObjects, root: Object3D): void {
	const seen = new Set<MeshStandardMaterial>();
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
		for (const m of mats) {
			if (!(m instanceof MeshStandardMaterial) || seen.has(m)) continue;
			seen.add(m);
			bo.eclipseShadow = attachEclipseShadowToBody(m, bo.eclipseShadow ?? undefined);
		}
	});
}

/**
 * Fetch and attach the body's 3D model, hiding the placeholder sphere: natural
 * bodies mount in the main scene, spacecraft in the unit-radius overlay scene.
 * No-op when the body has no `model_name`. Concurrent calls share one
 * in-flight load, since callers chain settle-time work (e.g. nomenclature
 * reading `bo.model`) off its resolution.
 */
export function loadBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	if (bo.model) return Promise.resolve();
	if (bo.modelLoadPromise) return bo.modelLoadPromise;
	const p = (
		isModelBearing(bo.body)
			? loadSpacecraftModel(bo, modelScene, ctx)
			: loadNaturalBodyModel(bo, ctx)
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
		// The anchor is measured in the model's own frame, so it turns with it.
		const anchor = meta?.model_anchor ? new Vector3(...meta.model_anchor) : null;
		fitToUnitRadius(root, anchor && baseFrame ? anchor.applyQuaternion(baseFrame) : anchor);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		setHaloLoading(bo, false);
		if (meta) {
			// True-size from the model's longest dimension, so the overlay (sized
			// off modelUnitScene) renders to scale against the solar system. The
			// body radius is the craft itself — a boom or a wire dipole is drawn,
			// but it is not how big the craft reads, so the halo, the label and
			// the camera's closest approach stay off the body.
			if (meta.scale_meters) {
				const spanKm = meta.scale_meters / 2000; // half the longest dim, km
				bo.body.data.radiusKm = spanKm * (meta.body_span_ratio ?? 1);
				bo.radiusScene = kmToScene(effectiveRadiusKm(bo.body.data));
				bo.modelUnitOverride = meta.body_span_ratio ? kmToScene(spanKm) : undefined;
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
 * Load a natural body's shape-model mesh, hiding the sphere. Normalised to
 * unit radius and mounted in the main scene (the mount reproduces true size
 * via radiusScene), oriented by the same IAU rotation the sphere gets. No-op
 * with no `model_name` or a non-shape-model bundle.
 */
async function loadNaturalBodyModel(bo: BodyObjects, ctx?: ContextManager): Promise<void> {
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
		fitToUnitRadius(root); // normalise to radius 1; the mount reproduces true size via radiusScene
		// Only a main-scene model is measurable: the camera clamp reads radii in
		// mount units, which say nothing about an overlay model's drawn size.
		root.userData.radialIndex = buildRadialIndex(root);
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
		attachModelEclipse(bo, root);
		// Size the mount against the real half-extent, matching radiusScene's
		// role: model radius 1 ↔ max_extent_km/2. Must land before mountModel so
		// the wrapper scale is right on frame 1.
		if (meta.true_scale) {
			bo.radiusScene = kmToScene(meta.true_scale.max_extent_km / 2);
			// Backfill radiusKm from the model's calibrated scale when the chunk
			// shipped none, and drop no-size state — the halo yields to the mesh.
			const radiusKnown = Number.isFinite(bo.body.data.radiusKm) && bo.body.data.radiusKm > 0;
			if (!radiusKnown) bo.body.data.radiusKm = meta.true_scale.max_extent_km / 2;
			if (bo.noPhysical) {
				bo.noPhysical = undefined;
				setLabelAnnotation(bo, 'missing', null);
			}
		}
		mountModel(bo, root);
		bo.modelName = slug;
		if (bo.mesh) bo.mesh.visible = false;
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
	if (bo.modelRoot) {
		attachedModelRoots.delete(bo.modelRoot);
		bo.modelRoot.removeFromParent();
		bo.modelRoot = null;
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
		bo.loadingShown = false;
	} else if (bo.loadingEl) {
		bo.loadingEl.remove();
		bo.loadingEl = null;
		bo.loadingShown = undefined;
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
 * in a unit-radius sphere), origin at the bbox center or, with an `anchor`, at
 * the craft body inside it. A mount's or the overlay camera's single scale
 * factor then makes it true-sized.
 *
 * Records `centerOffset`/`feetOffset` in `userData` — the overlay seats a
 * landed probe on its feet, not bbox-centred. `occluderSpheres` feeds the
 * label-occlusion pass so CSS2D labels behind the model get hidden.
 */
function fitToUnitRadius(root: Object3D, anchor: Vector3 | null = null): void {
	root.updateMatrixWorld(true);
	const bbox = new Box3().setFromObject(root);
	const size = bbox.getSize(new Vector3());
	const center = bbox.getCenter(new Vector3());
	const maxDim = Math.max(size.x, size.y, size.z);
	if (maxDim <= 0) return;
	const k = 2 / maxDim;
	// Seat the craft body at the origin, not the box centre: the body is what
	// the orbit anchors and the label point at, and a long boom drags the box
	// centre off it. The anchor is in post-fit units, hence the half-span.
	if (anchor) center.addScaledVector(anchor, maxDim / 2);
	root.scale.multiplyScalar(k);
	// The normalisation lives in root.scale; the overlay rescales secondary
	// models per frame and must compose with (not clobber) this factor.
	root.userData.fitScale = root.scale.x;
	root.position.copy(center).multiplyScalar(-k);
	root.userData.centerOffset = center.clone().multiplyScalar(k);
	root.userData.feetOffset = new Vector3(center.x, bbox.min.y, center.z).multiplyScalar(k);
	root.userData.halfExtents = size.clone().multiplyScalar(k * 0.5);
	const fit = buildOccluderSpheres(root, size, k, root.userData.centerOffset);
	root.userData.occluderSpheres = fit.spheres;
	// Radii the camera clamp reads, from the model's own origin. The recentring
	// offset widens the outer bound and narrows the inner one, so both still
	// bound the mesh when read as spheres about the body centre — which is what
	// the orbit-control fence and the sampling gate do.
	const offset = root.userData.centerOffset.length();
	root.userData.minRadius = Math.max(0, fit.minRadius - offset);
	root.userData.maxRadius = root.userData.halfExtents.length() + offset;
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
 *
 * Also returns the smallest sampled vertex radius — the sphere that fits
 * inside the model, which is how close the camera may come on any heading.
 */
function buildOccluderSpheres(
	root: Object3D,
	size: Vector3,
	k: number,
	offset: Vector3
): { spheres: OccluderSphere[]; minRadius: number } {
	root.updateMatrixWorld(true);
	const axis = size.x >= size.y && size.x >= size.z ? 0 : size.y >= size.z ? 1 : 2;
	// Total vertex count first, so sampling strides uniformly across meshes.
	let total = 0;
	root.traverse((obj) => {
		if (obj instanceof Mesh) total += obj.geometry.attributes.position?.count ?? 0;
	});
	if (!total) return { spheres: [], minRadius: 0 };
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

	// Widened by the recentring offset: slicing is about the model's origin,
	// which an anchored craft sits off-centre of.
	const half = (size.getComponent(axis) * k) / 2 + Math.abs(offset.getComponent(axis));
	const buckets: Vector3[][] = Array.from({ length: OCCLUDER_SLICES }, () => []);
	for (const p of pts) {
		const t = (p.getComponent(axis) + half) / (2 * half);
		const idx = Math.min(OCCLUDER_SLICES - 1, Math.max(0, Math.floor(t * OCCLUDER_SLICES)));
		buckets[idx].push(p);
	}

	let minRadius = Infinity;
	for (const p of pts) minRadius = Math.min(minRadius, p.length());

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
	return { spheres, minRadius: Number.isFinite(minRadius) ? minRadius : 0 };
}

/** Ray-cast start distance — safely beyond a unit-normalised model's bounding
 *  sphere (≤ √3) plus its recentring offset. */
const MODEL_CAST_DIST = 4;
/** Cast-radius floor, so pathological geometry can't flip a point to the far side. */
const MODEL_MIN_RADIUS = 0.05;

const _castBodyDir = new Vector3();
const _castDir = new Vector3();
const _castOrigin = new Vector3();
const _castScale = new Vector3();
const _castInvQuat = new Quaternion();
const _radialDir = new Vector3();
const _caster = new Raycaster();

/**
 * Surface distance (model units, from the model's own origin) along a
 * body-fixed lat/lon direction — the frame nomenclature latitudes and
 * longitudes are quoted in — by ray-casting the mesh from outside. Outermost
 * hit, so concave terrain can't swallow the result. The direction rotates into
 * the model's current attitude (hit distances are rotation-invariant). The cast
 * runs in world space: origin and hit distances go through the parent mount's
 * uniform scale (1 for overlay-scene models), while directions pass through
 * untouched — the mount carries no rotation. `outNormal`, if given, receives
 * the hit's body-fixed surface normal. Null on a miss (scan holes).
 */
export function castModelRadius(
	model: Object3D,
	latRad: number,
	lonRad: number,
	outNormal?: Vector3
): number | null {
	const mount = model.parent;
	if (!mount) return null;
	mount.updateMatrixWorld(true);
	const s = mount.getWorldScale(_castScale).x;
	if (!(s > 0)) return null;
	const cosLat = Math.cos(latRad);
	_castBodyDir.set(cosLat * Math.cos(lonRad), Math.sin(latRad), -cosLat * Math.sin(lonRad));
	_castDir.copy(_castBodyDir).applyQuaternion(model.quaternion);
	_castOrigin.copy(model.position).addScaledVector(_castDir, MODEL_CAST_DIST);
	mount.localToWorld(_castOrigin);
	_caster.set(_castOrigin, _castDir.negate());
	const hit = _caster.intersectObject(model, true)[0];
	if (!hit) return null;
	if (outNormal && hit.face) {
		outNormal
			.copy(hit.face.normal)
			.transformDirection(hit.object.matrixWorld)
			.applyQuaternion(_castInvQuat.copy(model.quaternion).invert());
	}
	return Math.max(MODEL_CAST_DIST - hit.distance / s, MODEL_MIN_RADIUS);
}

/**
 * Distance (km) from the body centre to the shape model's surface along a
 * body-fixed unit direction — the mesh twin of the DEM sampler, so the camera
 * floor follows the scan mesh a sphere at the body's radius pokes through.
 * Answered off the face index, cheap enough to run every frame. Null with no
 * model, or where the scan has a hole.
 */
export function modelSurfaceRadialKm(
	bo: BodyObjects | undefined,
	dir: [number, number, number]
): number | null {
	const index = bo?.model?.userData.radialIndex as RadialIndex | null | undefined;
	if (!index) return null;
	const r = radialIndexDistance(index, _radialDir.set(dir[0], dir[1], dir[2]));
	return r === null ? null : sceneToKm(r * modelUnitScene(bo!));
}

/**
 * Whether `bo` renders a shape model the camera clamp can measure against.
 * Only a mounted main-scene model qualifies: a spacecraft model is drawn in
 * the overlay at its own camera's scale, so the body's scene radius — a
 * nominal stand-in for a craft with no measured size — would wall the camera
 * off tens of craft lengths away.
 */
export function hasModelSurface(bo: BodyObjects | undefined): boolean {
	// Mounted, not just loaded: during an overlay episode the secondary-model
	// pass rewrites the model's scale and position, so mount units stop
	// describing what's drawn and the clamp falls back to the sphere.
	return Boolean(bo?.model?.userData.radialIndex) && bo!.model!.parent === bo!.modelRoot;
}

/** Where the mounted model's radii are measured from, in scene units off the
 *  body centre: the fit recentres the mesh on its bounding box, so the model's
 *  own origin — which every radius here is reckoned from — sits that far away.
 *  The mount carries no rotation, so this offset is fixed in the scene frame. */
export function modelCenterOffsetScene(
	bo: BodyObjects | undefined
): [number, number, number] | undefined {
	if (!hasModelSurface(bo)) return undefined;
	const p = bo!.model!.position;
	const s = modelUnitScene(bo!);
	return [p.x * s, p.y * s, p.z * s];
}

/** Radius (km) of a sphere the mounted model certainly fits inside — the
 *  clamp skips its surface sampling outside it. */
export function modelOuterRadiusKm(bo: BodyObjects | undefined): number | undefined {
	if (!hasModelSurface(bo)) return undefined;
	return sceneToKm((bo!.model!.userData.maxRadius as number) * modelUnitScene(bo!));
}

/** Radius (km) of the largest sphere that fits inside the mounted model — how
 *  close the orbit controls may let the camera come on any heading, with the
 *  per-frame mesh clamp holding the real surface. */
export function modelMinRadiusKm(bo: BodyObjects | undefined): number | undefined {
	if (!hasModelSurface(bo)) return undefined;
	return sceneToKm((bo!.model!.userData.minRadius as number) * modelUnitScene(bo!));
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
