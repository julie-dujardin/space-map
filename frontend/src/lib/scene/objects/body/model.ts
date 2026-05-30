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
import { DATA_BASE } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { buildFallbackSpacecraftModel } from './fallback-model';
import type { BodyObjects } from '../../types';

/** Body types whose placeholder sphere is meaningless and should be hidden
 *  the moment a load starts (rather than waiting for the detail fetch to
 *  confirm `model_name`). Probes carry their own catalog; spacecraft/debris
 *  belong to the same family. Planets and moons never enter this branch, so
 *  their sphere doesn't flicker during focus. */
function isModelBearing(body: PositionedBody): boolean {
	const t = body.data.objectType;
	return (
		t === ObjectType.SPACECRAFT ||
		t === ObjectType.DEBRIS ||
		body.data.orbitalSource === OrbitalSource.SPICE_PROBE
	);
}

/** Subset of `metadata.json` (per-model public bundle) that's needed to
 *  register the focused-body credit. The exporter writes more fields per
 *  tier, but the scene only needs the catalog landing page + name for the
 *  high tier (which is what loadBodyModel fetches). For merged-manifest
 *  entries the low tier may originate in a different catalog. */
interface ModelBundleMeta {
	exports: {
		high: {
			source: string;
			source_url: string;
		};
	};
}

const _loader = new GLTFLoader();
_loader.setMeshoptDecoder(MeshoptDecoder);
const _bundleMetaCache = new Map<string, Promise<ModelBundleMeta>>();

function fetchBundleMeta(slug: string): Promise<ModelBundleMeta> {
	let p = _bundleMetaCache.get(slug);
	if (!p) {
		p = fetch(`${DATA_BASE}/v1/models/${slug}/metadata.json`).then((r) => r.json());
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
	// Pre-hide for model-bearing types (avoids placeholder flash); planets/moons skip this.
	const preHide = isModelBearing(bo.body) && bo.mesh?.visible === true;
	if (preHide && bo.mesh) bo.mesh.visible = false;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		const slug = detail.global?.model_name;
		if (!slug) {
			// Spacecraft-like types (pre-hide set) get a gray cuboid placeholder;
			// non-model-bearing bodies restore their sphere.
			if (preHide) {
				if ((bo.modelLoadEpoch ?? 0) !== epoch || !bo.mesh) return;
				const fallback = buildFallbackSpacecraftModel();
				fitToUnitRadius(fallback);
				modelScene.add(fallback);
				bo.model = fallback;
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
		const gltf = await _loader.loadAsync(`${DATA_BASE}/v1/models/${slug}/high.glb`);
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
		if (ctx) {
			try {
				const meta = await metaPromise;
				ctx.credits.registerModel({
					bodyId: bo.body.data.id,
					source: meta.exports.high.source_url,
					organisation: meta.exports.high.source
				});
			} catch (e) {
				// Credits are a nice-to-have; a missing/corrupt metadata.json
				// shouldn't tear down the loaded model.
				console.warn(`Failed to register model credit for ${slug}:`, e);
			}
		}
	} finally {
		// Load aborted before the GLB attached — put the sphere back and
		// restore the halo so the body stays visible.
		if (!bo.model) {
			if (bo.mesh) bo.mesh.visible = true;
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
	const root = bo.model;
	if (!root) {
		if (bo.mesh) bo.mesh.visible = true;
		return;
	}
	root.parent?.remove(root);
	disposeGltf(root);
	bo.model = null;
	bo.modelName = undefined;
	if (bo.mesh) bo.mesh.visible = true;
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
