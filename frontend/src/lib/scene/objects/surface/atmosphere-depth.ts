import {
	DepthTexture,
	FloatType,
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
 */
export class AtmosphereDepthPass {
	#target: WebGLRenderTarget;
	readonly #forward = new Vector3();
	readonly #size = new Vector2();

	constructor(width: number, height: number) {
		this.#target = makeTarget(width, height);
	}

	setSize(width: number, height: number): void {
		this.#target.dispose();
		this.#target.depthTexture?.dispose();
		this.#target = makeTarget(width, height);
	}

	/** Render opaque scene depth and bind it onto every atmosphere material. Shells hide during the pass so they don't occlude themselves. */
	run(
		renderer: WebGLRenderer,
		scene: Scene,
		camera: PerspectiveCamera,
		bodyObjects: Map<string, BodyObjects>
	): void {
		const hidden: BodyObjects[] = [];
		for (const bo of bodyObjects.values()) {
			if (bo.atmosphere?.mesh.visible) {
				bo.atmosphere.mesh.visible = false;
				hidden.push(bo);
			}
		}

		const prevTarget = renderer.getRenderTarget();
		renderer.setRenderTarget(this.#target);
		renderer.clear();
		renderer.render(scene, camera);
		renderer.setRenderTarget(prevTarget);

		for (const bo of hidden) bo.atmosphere!.mesh.visible = true;

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
