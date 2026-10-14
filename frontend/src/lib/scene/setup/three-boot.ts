import {
	ACESFilmicToneMapping,
	AmbientLight,
	DepthTexture,
	DirectionalLight,
	FloatType,
	HalfFloatType,
	PCFShadowMap,
	PCFSoftShadowMap,
	PerspectiveCamera,
	Scene,
	Vector2,
	WebGLRenderer,
	WebGLRenderTarget
} from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { kmToScene } from '$lib/math/units';
import { currentRenderTier, renderPixelRatio } from '$lib/scene/render-tier';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ThrottledCSS2DRenderer } from '$lib/scene/label/throttled-renderer';
import { setTrailResolution } from '$lib/scene/objects/trail/material';
import { AMBIENT_INTENSITY, BLOOM_THRESHOLD } from '$lib/scene/lighting';
import { installBloomHighPass } from './bloom-high-pass';
import { installLogDepthChunks, setReversedDepth } from './depth-mode';

/** Solar-system-view far plane (scene units, ~0.5 ly). Under reversed-Z, far
 *  only defines clipping — depth precision is relative to distance and doesn't
 *  depend on it. Under the logarithmic-depth fallback, precision scales as
 *  1/log2(far), so the renderer pulls far in when zoomed into a subsystem —
 *  see `SceneRenderer.updateDepthFar`. */
export const CAMERA_FAR_DEFAULT = 100000;

/** Reversed-Z needs EXT_clip_control, probed before renderer creation so the
 *  fallback can enable the logarithmic depth buffer instead — the two modes
 *  write incompatible fragment depths and can't both be on. */
function probeClipControl(): boolean {
	try {
		const gl = document.createElement('canvas').getContext('webgl2');
		return Boolean(gl?.getExtension('EXT_clip_control'));
	} catch {
		return false;
	}
}

/** WebGL2 context creation failed (no-WebGL2 device, GPU blocklist, …);
 *  Scene.svelte catches it to show the fallback panel. */
export class WebGLUnavailableError extends Error {
	constructor(cause?: unknown) {
		super('WebGL is unavailable on this device.', { cause });
		this.name = 'WebGLUnavailableError';
	}
}

export interface ThreeBoot {
	renderer: WebGLRenderer;
	labelRenderer: ThrottledCSS2DRenderer;
	scene: Scene;
	camera: PerspectiveCamera;
	composer: EffectComposer;
	/** Most samples the device has for the composer's half-float target. It can
	 *  be under the limit that three checks, or none. */
	maxSceneSamples: number;
	bloomPass: UnrealBloomPass;
	/** Main-scene ambient fill; intensity is driven by the high-ambient toggle. */
	ambientLight: AmbientLight;
	/** Sub-system view's directional sun light. Solar-system view drives the
	 *  Sun's `PointLight` instead — see `shaders/sun-shadow-light.ts`. Shadow
	 *  map disabled; body-on-body shadows are computed analytically. */
	shadowLight: DirectionalLight;
}

/**
 * Build the Three.js foundation: WebGL renderer, label renderer, scene + lights,
 * camera, and the composer with bloom + tonemap passes. Tonemapping moves to
 * the composer's OutputPass (the renderer's own stage doesn't run under composer
 * control). Only the Sun's HDR pixels cross the bloom threshold.
 */
export function bootThree(
	canvas: HTMLCanvasElement,
	labelContainer: HTMLElement,
	ctx: ContextManager
): ThreeBoot {
	let renderer: WebGLRenderer;
	const reversedDepth = probeClipControl();
	if (!reversedDepth) installLogDepthChunks();
	try {
		// The canvas keeps its antialiasing for the model overlay, the one scene drawn straight to it.
		renderer = new WebGLRenderer(
			reversedDepth
				? { canvas, reversedDepthBuffer: true, antialias: true }
				: { canvas, logarithmicDepthBuffer: true, antialias: true }
		);
	} catch (e) {
		// Normalize three's bare Error so the caller can branch on type.
		throw new WebGLUnavailableError(e);
	}
	if (reversedDepth && !renderer.capabilities.reversedDepthBuffer) {
		// Probe context had the extension but the real one doesn't — neither
		// depth mode is active, so precision at scale will suffer.
		console.warn('EXT_clip_control probe mismatch: reversed depth unavailable on main context');
	}
	setReversedDepth(renderer.capabilities.reversedDepthBuffer);
	const tier = currentRenderTier();
	renderer.setPixelRatio(renderPixelRatio());
	renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	// Shadow maps serve the focused 3D model only: the overlay scene's
	// directional sun for spacecraft, or the main-scene shadow light while a
	// natural-body model is mounted (toggled with a model-tight frustum in
	// `SceneRenderer.updateFocusedMountedModel`). The cost is paid only when a
	// focused body has a 3D model attached.
	renderer.shadowMap.enabled = true;
	renderer.shadowMap.type = tier.softShadows ? PCFSoftShadowMap : PCFShadowMap;
	// ACES rolls the Sun's HDR output to saturated white. LDR overlays (trails,
	// halos) are scaled in their own builders to compensate.
	renderer.toneMapping = ACESFilmicToneMapping;
	renderer.toneMappingExposure = 1.0;
	// Fat trails expand by `width / resolution` in NDC; feed the CSS-pixel
	// size so width reads as pixels regardless of devicePixelRatio.
	setTrailResolution(canvas.clientWidth, canvas.clientHeight);

	const labelRenderer = new ThrottledCSS2DRenderer({ element: labelContainer });
	labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight);
	ctx.visibility.updateViewport(canvas.clientHeight);

	const scene = new Scene();
	const ambientLight = new AmbientLight(0xffffff, AMBIENT_INTENSITY);
	scene.add(ambientLight);
	const shadowLight = new DirectionalLight(0xffffff, 0);
	shadowLight.castShadow = false;
	// A grazing-Sun shadow across a model-tight frustum wants 4096²; low tiers take less.
	shadowLight.shadow.mapSize.set(tier.shadowMapSize, tier.shadowMapSize);
	shadowLight.shadow.bias = -0.0001;
	scene.add(shadowLight);
	scene.add(shadowLight.target);

	const aspect = canvas.clientWidth / canvas.clientHeight;
	const camera = new PerspectiveCamera(60, aspect, kmToScene(0.001), CAMERA_FAR_DEFAULT);

	// The canvas's own antialiasing does not reach this target. The renderer sets its sample count.
	const composerTarget = new WebGLRenderTarget(canvas.clientWidth, canvas.clientHeight, {
		type: HalfFloatType,
		// The model overlay reads the scene's depth: the renderer resolves it while one is drawn.
		resolveDepthBuffer: false,
		// Float: reversed depth needs it, and decoding a depth magnifies small differences.
		// three takes the buffer's type from this texture.
		depthTexture: new DepthTexture(canvas.clientWidth, canvas.clientHeight, FloatType)
	});
	const gl = renderer.getContext() as WebGL2RenderingContext;
	// The counts come in descending order. A device can have none for this format.
	const sampleCounts: Int32Array = gl.getInternalformatParameter(
		gl.RENDERBUFFER,
		gl.RGBA16F,
		gl.SAMPLES
	);
	const composer = new EffectComposer(renderer, composerTarget);
	composer.setPixelRatio(renderPixelRatio());
	composer.setSize(canvas.clientWidth, canvas.clientHeight);
	composer.addPass(new RenderPass(scene, camera));
	// Sized in CSS pixels times the tier's scale: the Sun's glow has no detail
	// to lose, so low tiers blur at half the canvas.
	const bloomPass = new UnrealBloomPass(
		new Vector2(canvas.clientWidth * tier.bloomScale, canvas.clientHeight * tier.bloomScale),
		0.3, // strength
		0.5, // radius
		BLOOM_THRESHOLD
	);
	installBloomHighPass(bloomPass);
	composer.addPass(bloomPass);
	const outputPass = new OutputPass();
	// With no swap after the last pass, three never builds the composer's second target.
	outputPass.needsSwap = false;
	composer.addPass(outputPass);

	return {
		renderer,
		labelRenderer,
		scene,
		camera,
		composer,
		maxSceneSamples: sampleCounts[0] ?? 0,
		bloomPass,
		ambientLight,
		shadowLight
	};
}
