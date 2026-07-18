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

/**
 * Opaque-depth prepass feeding the atmosphere shells. When the camera is inside
 * a shell it renders with depthTest off (so the sky draws from inside), which
 * would otherwise paint the far-hemisphere haze over foreground terrain. This
 * renders the scene's depth into a texture the shell shader samples to stop its
 * march at real terrain instead of the analytic datum. Gated by the renderer to
 * the inside-a-shell case, so the extra scene pass is only paid at surface zoom.
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

	/**
	 * Render opaque scene depth and bind it (plus the camera basis the shader
	 * decodes it against) onto every atmosphere material. Atmosphere shells are
	 * hidden during the pass so they don't occlude themselves.
	 */
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
	// The colour attachment is unused — only depthTexture is read — but a target
	// still needs one. FloatType keeps full precision: the shader decodes the
	// logarithmic-depth value through an exponential, so a low-bit depth texture
	// quantises the terrain distance into visible bands (and jitters per frame).
	const target = new WebGLRenderTarget(width, height);
	target.depthTexture = new DepthTexture(width, height, FloatType);
	return target;
}
