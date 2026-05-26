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
import type { BodyObjects } from '../../types';

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
 * Build the neutral environment cubemap used by the model-overlay scene.
 * Mirrors gltf-viewer's `RoomEnvironment` + PMREM setup — needed so PBR
 * metals/specular surfaces have something to reflect. The overlay scene
 * dims this aggressively via `environmentIntensity` because in deep space
 * we want the sun's directional shadow to dominate; the env's only job
 * here is to keep metallics from going pure black.
 */
export function makeModelEnvMap(renderer: WebGLRenderer): Texture {
	const pmrem = new PMREMGenerator(renderer);
	const tex = pmrem.fromScene(new RoomEnvironment()).texture;
	pmrem.dispose();
	return tex;
}

/**
 * Fetch and attach the spacecraft 3D model for `bo` if its global JSON
 * carries `model_name`. The model is added to `modelScene` (a sibling scene
 * rendered in its own pass with linear-depth-friendly near/far) at
 * unit-radius scale around origin. `repositionBodies` doesn't touch the
 * overlay scene — the main camera mirrors orientation onto the overlay
 * camera per frame instead. Hides the focused body's placeholder sphere
 * so the model takes its visual slot.
 */
export async function loadBodyModel(
	bo: BodyObjects,
	modelScene: Scene,
	ctx?: ContextManager
): Promise<void> {
	if (bo.model || bo.modelLoading) return;
	bo.modelLoading = true;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		const slug = detail.global?.model_name;
		if (!slug) return;
		// Body was un-focused (mesh torn down) while the bundle fetch was in
		// flight. Drop the load so we don't attach a stray model.
		if (!bo.mesh) return;
		// Kick the bundle metadata fetch alongside the GLB — small and
		// cacheable. Registering the credit as the model becomes visible
		// keeps the attribution bar/popover in lockstep with what's on screen.
		const metaPromise = fetchBundleMeta(slug);
		const gltf = await _loader.loadAsync(`${DATA_BASE}/v1/models/${slug}/high.glb`);
		if (!bo.mesh) {
			disposeGltf(gltf.scene);
			return;
		}
		const root = gltf.scene;
		fitToUnitRadius(root);
		enableShadows(root);
		modelScene.add(root);
		bo.model = root;
		bo.modelName = slug;
		bo.mesh.visible = false;
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
		bo.modelLoading = false;
	}
}

/**
 * Dispose the loaded model and restore the placeholder sphere. No-op when
 * no model is attached. Called from `downgradeBodyMesh`. Removes the model
 * from whichever scene it was parented to (the overlay's modelScene).
 */
export function unloadBodyModel(bo: BodyObjects): void {
	const root = bo.model;
	if (!root) return;
	root.parent?.remove(root);
	disposeGltf(root);
	bo.model = null;
	bo.modelName = undefined;
	if (bo.mesh) bo.mesh.visible = true;
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
