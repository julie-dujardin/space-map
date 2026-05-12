/**
 * Off-screen post-processing pipeline for Earth's atmosphere — the full,
 * LUT-based path (aerial perspective on the rendered terrain + a sky-view fill
 * when the camera sits inside the atmosphere) described in Maxime Heckel's
 * "On rendering realistic-looking skies, sunsets, and planets"
 * (https://blog.maximeheckel.com/posts/on-rendering-the-sky-sunsets-and-planets/),
 * after Bruneton/Hillaire. It only stands up — and only takes over the render —
 * when the camera is in the Earth-Moon system; everywhere else the renderer
 * draws straight to the canvas as before, and the cheap additive limb-glow
 * shell (see `objects/atmosphere.ts`) is all that runs.
 *
 * Phase 2 (current): just the scaffold. The scene renders into an HDR,
 * multisampled render target (so it can blow past 1.0 for the scattering math,
 * and MSAA survives the off-screen detour) and {@link OutputPass} composites it
 * back to the canvas with the renderer's tone mapping + colour-space transform —
 * which, with `NoToneMapping`, is exactly what the direct path does. The
 * scene-depth texture, the LUT-generation passes, and the atmosphere
 * composition shader slot in between in later phases (the composition shader
 * will eventually replace {@link OutputPass} so it can tone-map the composited
 * result in one go).
 */

import {
	HalfFloatType,
	type PerspectiveCamera,
	type Scene,
	Vector2,
	type WebGLRenderer,
	WebGLRenderTarget
} from 'three';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

export class AtmospherePipeline {
	private readonly renderer: WebGLRenderer;
	private readonly scene: Scene;
	private readonly camera: PerspectiveCamera;
	/** HDR + MSAA target the scene renders into before compositing. */
	private readonly sceneTarget: WebGLRenderTarget;
	/** Final composite-to-canvas pass (tone mapping + colour-space transform).
	 *  Stands in for the atmosphere composition shader until that lands. */
	private readonly outputPass: OutputPass;

	constructor(renderer: WebGLRenderer, scene: Scene, camera: PerspectiveCamera) {
		this.renderer = renderer;
		this.scene = scene;
		this.camera = camera;

		const dpr = renderer.getPixelRatio();
		const size = renderer.getSize(new Vector2());
		const w = Math.max(1, Math.round(size.width * dpr));
		const h = Math.max(1, Math.round(size.height * dpr));

		// HalfFloat so the scattering composite can carry HDR; samples:4 so the
		// off-screen render keeps the antialiasing the default framebuffer would
		// have given. Resolved (single-sample) texture is what the output pass
		// reads — its colour space stays linear, so the linear→sRGB transform
		// happens once, in OutputPass.
		this.sceneTarget = new WebGLRenderTarget(w, h, {
			type: HalfFloatType,
			samples: 4
		});
		this.sceneTarget.texture.name = 'AtmospherePipeline.scene';

		this.outputPass = new OutputPass();
		this.outputPass.renderToScreen = true;
	}

	/**
	 * Render the scene through the pipeline to the canvas. Mirrors a bare
	 * `renderer.render(scene, camera)` for now: scene → HDR target, then
	 * OutputPass → canvas with the renderer's tone mapping / colour space.
	 */
	render(): void {
		const prevTarget = this.renderer.getRenderTarget();
		this.renderer.setRenderTarget(this.sceneTarget);
		this.renderer.render(this.scene, this.camera);
		// renderToScreen is true, so writeBuffer is ignored — pass the scene
		// target as the read buffer.
		this.outputPass.render(this.renderer, this.sceneTarget, this.sceneTarget, 0, false);
		this.renderer.setRenderTarget(prevTarget);
	}

	/** Free the GPU resources. Call when leaving the Earth-Moon system or on
	 *  resize (the pipeline is re-created lazily on the next frame that needs
	 *  it, sized to the new viewport). */
	dispose(): void {
		this.sceneTarget.dispose();
		this.outputPass.dispose();
	}
}
