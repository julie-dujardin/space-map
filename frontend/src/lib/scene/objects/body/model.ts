import { Box3, Mesh, type Object3D, type Scene, Texture, Vector3 } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { DATA_BASE } from '$lib/fetch/data-base';
import type { BodyObjects } from '../../types';

const _loader = new GLTFLoader();
_loader.setMeshoptDecoder(MeshoptDecoder);

/**
 * Fetch and attach the spacecraft 3D model for `bo` if its global JSON
 * carries `model_name`. Idempotent — re-entry while a load is in flight or
 * after a successful load is a no-op. Auto-fits the model so its largest
 * bbox half-extent matches the body's `radiusScene`, so it visually replaces
 * the placeholder sphere mesh at the same screen size. The sphere mesh is
 * left in place but hidden; un-hidden by `unloadBodyModel` on un-focus.
 */
export async function loadBodyModel(bo: BodyObjects, scene: Scene): Promise<void> {
	if (bo.model || bo.modelLoading) return;
	bo.modelLoading = true;
	try {
		const detail = await fetchObjectDetail(bo.body.data.id, false);
		const slug = detail.global?.model_name;
		if (!slug) return;
		// Body was un-focused (mesh torn down) while the bundle fetch was in
		// flight. Drop the load so we don't attach a stray model to a body
		// whose sphere was already disposed.
		if (!bo.mesh) return;
		const gltf = await _loader.loadAsync(`${DATA_BASE}/v1/models/${slug}/high.glb`);
		if (!bo.mesh) {
			disposeGltf(gltf.scene);
			return;
		}
		const root = gltf.scene;
		fitToRadius(root, bo.radiusScene);
		scene.add(root);
		bo.extraObjects.push(root);
		bo.model = root;
		bo.modelName = slug;
		bo.mesh.visible = false;
	} finally {
		bo.modelLoading = false;
	}
}

/**
 * Dispose the loaded model and restore the placeholder sphere. No-op when no
 * model is attached. Called from `downgradeBodyMesh`.
 */
export function unloadBodyModel(bo: BodyObjects, scene: Scene): void {
	const root = bo.model;
	if (!root) return;
	scene.remove(root);
	const idx = bo.extraObjects.indexOf(root);
	if (idx >= 0) bo.extraObjects.splice(idx, 1);
	disposeGltf(root);
	bo.model = null;
	bo.modelName = undefined;
	if (bo.mesh) bo.mesh.visible = true;
}

/**
 * Uniformly scale `root` so its largest bbox half-extent equals `radiusScene`.
 * Bbox is computed in `root`'s local space before any prior scale, then
 * applied by overwriting `root.scale`. Sub-meshes keep their authored local
 * transforms.
 */
function fitToRadius(root: Object3D, radiusScene: number): void {
	root.updateMatrixWorld(true);
	const bbox = new Box3().setFromObject(root);
	const size = new Vector3();
	bbox.getSize(size);
	const maxDim = Math.max(size.x, size.y, size.z);
	if (maxDim <= 0) return;
	const k = (2 * radiusScene) / maxDim;
	root.scale.multiplyScalar(k);
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
