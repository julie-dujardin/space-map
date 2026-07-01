import {
	Box3,
	Mesh,
	type Object3D,
	PMREMGenerator,
	type Scene,
	Texture,
	Vector3,
	type WebGLRenderer
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { createAttitudeTrack } from '$lib/fetch/attitude/track';
import { versionedUrl } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { BodyObjects } from '../../types';

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
interface ModelBundleMeta {
	exports: {
		high: {
			credit: {
				name: string;
				url: string;
			};
		};
	};
	scale_meters?: number;
}

const _loader = new GLTFLoader();
_loader.setMeshoptDecoder(MeshoptDecoder);
const _bundleMetaCache = new Map<string, Promise<ModelBundleMeta>>();

function fetchBundleMeta(slug: string): Promise<ModelBundleMeta> {
	let p = _bundleMetaCache.get(slug);
	if (!p) {
		p = fetch(versionedUrl(`/v1/models/${slug}/metadata.json`, 'models')).then((r) => r.json());
		_bundleMetaCache.set(slug, p);
	}
	return p;
}

/**
 * Neutral IBL cubemap for the model-overlay scene so PBR metals have something
 * to reflect. The overlay heavily dims it via `environmentIntensity` — the sun
 * dominates; this just keeps metallics from going pure black.
 */
export function makeModelEnvMap(renderer: WebGLRenderer): Texture {
	const pmrem = new PMREMGenerator(renderer);
	const tex = pmrem.fromScene(new RoomEnvironment()).texture;
	pmrem.dispose();
	return tex;
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
}

function enableShadows(root: Object3D): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		obj.castShadow = true;
		obj.receiveShadow = true;
	});
}

function disposeGltf(root: Object3D): void {
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
