import {
	ACESFilmicToneMapping,
	AmbientLight,
	DirectionalLight,
	PCFSoftShadowMap,
	PerspectiveCamera,
	Scene,
	Vector2,
	WebGLRenderer
} from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { kmToScene } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ThrottledCSS2DRenderer } from '$lib/scene/label/throttled-renderer';
import { setTrailResolution } from '$lib/scene/objects/trail/material';
import { AMBIENT_INTENSITY } from '$lib/scene/lighting';

export interface ThreeBoot {
	renderer: WebGLRenderer;
	labelRenderer: ThrottledCSS2DRenderer;
	scene: Scene;
	camera: PerspectiveCamera;
	composer: EffectComposer;
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
 * control). Bloom threshold=1.0 — only the Sun's HDR pixels cross it.
 */
export function bootThree(
	canvas: HTMLCanvasElement,
	labelContainer: HTMLElement,
	ctx: ContextManager
): ThreeBoot {
	const renderer = new WebGLRenderer({ canvas, logarithmicDepthBuffer: true, antialias: true });
	renderer.setPixelRatio(window.devicePixelRatio);
	renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
	// Shadow maps are enabled globally for the model-overlay scene's directional
	// sun (see renderer.ts). Main-scene lights keep `castShadow = false`, so the
	// cost is paid only when a focused body has a 3D model attached.
	renderer.shadowMap.enabled = true;
	renderer.shadowMap.type = PCFSoftShadowMap;
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
	scene.add(shadowLight);
	scene.add(shadowLight.target);

	const aspect = canvas.clientWidth / canvas.clientHeight;
	const camera = new PerspectiveCamera(60, aspect, kmToScene(0.001), 100000);

	const composer = new EffectComposer(renderer);
	composer.setPixelRatio(window.devicePixelRatio);
	composer.setSize(canvas.clientWidth, canvas.clientHeight);
	composer.addPass(new RenderPass(scene, camera));
	const bloomPass = new UnrealBloomPass(
		new Vector2(canvas.clientWidth, canvas.clientHeight),
		0.3, // strength
		0.5, // radius
		1.0 // threshold — only HDR over-bright pixels (the Sun) bloom
	);
	composer.addPass(bloomPass);
	composer.addPass(new OutputPass());

	return { renderer, labelRenderer, scene, camera, composer, bloomPass, ambientLight, shadowLight };
}
