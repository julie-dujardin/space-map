import {
	BackSide,
	DepthTexture,
	FloatType,
	type Material,
	type Mesh,
	MeshDepthMaterial,
	type MeshStandardMaterial,
	type PerspectiveCamera,
	type Scene,
	Vector2,
	Vector3,
	type WebGLRenderer,
	WebGLRenderTarget
} from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { isReversedDepth } from '$lib/scene/setup/depth-mode';

/**
 * Opaque-depth prepass for the atmosphere shells. Inside a shell, depthTest is
 * off so the sky draws from inside — without this, the far-hemisphere haze
 * would paint over foreground terrain. The shell shader samples this texture
 * to stop its march at real terrain instead of the analytic datum.
 *
 * Only the bodies whose shell the camera is inside can sit in front of that
 * haze, so the pass draws just their meshes, with a depth-only material that
 * keeps the surface displacement.
 */
export class AtmosphereDepthPass {
	#target: WebGLRenderTarget;
	readonly #forward = new Vector3();
	readonly #size = new Vector2();
	/** Depth-only twin per surface material; displacement is re-synced each pass. */
	readonly #depthMaterials = new WeakMap<Material, MeshDepthMaterial>();
	readonly #swapped: { mesh: Mesh; material: Material | Material[] }[] = [];

	constructor(width: number, height: number) {
		this.#target = makeTarget(width, height);
	}

	setSize(width: number, height: number): void {
		this.#target.dispose();
		this.#target.depthTexture?.dispose();
		this.#target = makeTarget(width, height);
	}

	/** Render the depth of every body the camera is inside the shell of, on
	 *  `layer` alone, and bind it onto every atmosphere material. */
	run(
		renderer: WebGLRenderer,
		scene: Scene,
		camera: PerspectiveCamera,
		bodyObjects: Map<string, BodyObjects>,
		layer: number
	): void {
		const swapped = this.#swapped;
		for (const bo of bodyObjects.values()) {
			// `updateAtmosphereShaders` flips a shell to BackSide once the camera is inside it.
			if (bo.atmosphere?.material.side !== BackSide) continue;
			if (bo.mesh) this.#stage(bo.mesh, layer);
			if (bo.model && bo.model.parent === bo.modelRoot) {
				bo.model.traverse((o) => {
					if ((o as Mesh).isMesh) this.#stage(o as Mesh, layer);
				});
			}
		}

		const prevTarget = renderer.getRenderTarget();
		const prevMask = camera.layers.mask;
		const prevBackground = scene.background;
		camera.layers.set(layer);
		scene.background = null;
		renderer.setRenderTarget(this.#target);
		renderer.clear();
		renderer.render(scene, camera);
		renderer.setRenderTarget(prevTarget);
		scene.background = prevBackground;
		camera.layers.mask = prevMask;

		for (const { mesh, material } of swapped) {
			mesh.material = material;
			mesh.layers.disable(layer);
		}
		swapped.length = 0;

		camera.getWorldDirection(this.#forward);
		renderer.getDrawingBufferSize(this.#size);
		for (const bo of bodyObjects.values()) {
			const u = bo.atmosphere?.material.uniforms;
			if (!u) continue;
			u.uSceneDepth.value = this.#target.depthTexture;
			(u.uCamForward.value as Vector3).copy(this.#forward);
			u.uReversedDepth.value = isReversedDepth() ? 1 : 0;
			u.uCameraNear.value = camera.near;
			u.uCameraFar.value = camera.far;
			(u.uResolution.value as Vector2).copy(this.#size);
		}
	}

	/** Put `mesh` on the pass layer with its depth-only material. */
	#stage(mesh: Mesh, layer: number): void {
		if (!mesh.visible) return;
		const material = mesh.material;
		if (Array.isArray(material)) return;
		let depth = this.#depthMaterials.get(material);
		if (!depth) {
			depth = new MeshDepthMaterial();
			this.#depthMaterials.set(material, depth);
		}
		const src = material as MeshStandardMaterial;
		if ((depth.displacementMap ?? null) !== (src.displacementMap ?? null)) {
			depth.displacementMap = src.displacementMap ?? null;
			depth.needsUpdate = true;
		}
		depth.displacementScale = src.displacementScale ?? 1;
		depth.displacementBias = src.displacementBias ?? 0;
		depth.side = src.side;
		this.#swapped.push({ mesh, material });
		mesh.material = depth;
		mesh.layers.enable(layer);
	}

	dispose(): void {
		this.#target.depthTexture?.dispose();
		this.#target.dispose();
	}
}

function makeTarget(width: number, height: number): WebGLRenderTarget {
	// FloatType: both depth decodes (reversed-Z hyperbolic, log-depth exponential)
	// magnify small value differences, so lower precision bands and jitters terrain distance.
	const target = new WebGLRenderTarget(width, height);
	target.depthTexture = new DepthTexture(width, height, FloatType);
	return target;
}
