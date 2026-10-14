import {
	type DepthTexture,
	type PerspectiveCamera,
	ShaderMaterial,
	Vector2,
	type WebGLRenderer
} from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { eyeToLogDepthGlsl, isReversedDepth, logDepthToEyeGlsl } from '$lib/scene/setup/depth-mode';

const VERTEX_SHADER = /* glsl */ `
void main() {
	gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = /* glsl */ `
uniform sampler2D uSceneDepth;
uniform vec2 uResolution;
uniform float uReversed;
uniform float uSceneNear;
uniform float uSceneFar;
uniform float uNear;
uniform float uFar;
uniform float uUnit;
uniform float uFront;

void main() {
	float d = texture2D(uSceneDepth, gl_FragCoord.xy / uResolution).x;
	// The cleared depth: nothing in front of the model here.
	if (uReversed > 0.5 ? d <= 0.0 : d >= 1.0) discard;
	float w = (uReversed > 0.5
		? uSceneNear * uSceneFar / (d * (uSceneFar - uSceneNear) + uSceneNear)
		: ${logDepthToEyeGlsl('d', 'uSceneFar')}) / uUnit;
	if (w >= uFront) discard;
	gl_FragDepth = uReversed > 0.5
		? uNear * (uFar - w) / (w * (uFar - uNear))
		: ${eyeToLogDepthGlsl('w', 'uFar')};
}
`;

/**
 * Puts the depth of the main scene into the canvas before the model overlay
 * draws, so that the ground in front of a model hides it. The overlay camera
 * is the main camera scaled down by `unit` about the model, so a scene depth
 * is the same distance divided by `unit` in the overlay.
 *
 * Only the depth in front of the model's bounding sphere goes in. A landed
 * model stands on the ground facet under its centre, and the ground under its
 * feet can be some centimetres higher.
 */
export class ModelDepthPass {
	readonly #material = new ShaderMaterial({
		uniforms: {
			uSceneDepth: { value: null },
			uResolution: { value: new Vector2(1, 1) },
			uReversed: { value: 0 },
			uSceneNear: { value: 1 },
			uSceneFar: { value: 2 },
			uNear: { value: 1 },
			uFar: { value: 2 },
			uUnit: { value: 1 },
			uFront: { value: 0 }
		},
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		colorWrite: false
		// Not AlwaysDepth: three turns it into NeverDepth under reversed depth.
		// Every depth passes the default test against the cleared buffer.
	});
	readonly #quad = new FullScreenQuad(this.#material);

	/** Write `depth`, drawn by `sceneCamera`, as `modelCamera` depth into the
	 *  current target, where it is nearer than `front` in overlay units. */
	run(
		renderer: WebGLRenderer,
		depth: DepthTexture,
		sceneCamera: PerspectiveCamera,
		modelCamera: PerspectiveCamera,
		unit: number,
		front: number
	): void {
		const u = this.#material.uniforms;
		u.uSceneDepth.value = depth;
		renderer.getDrawingBufferSize(u.uResolution.value as Vector2);
		u.uReversed.value = isReversedDepth() ? 1 : 0;
		u.uSceneNear.value = sceneCamera.near;
		u.uSceneFar.value = sceneCamera.far;
		u.uNear.value = modelCamera.near;
		u.uFar.value = modelCamera.far;
		u.uUnit.value = unit;
		u.uFront.value = front;
		this.#quad.render(renderer);
	}

	dispose(): void {
		this.#quad.dispose();
		this.#material.dispose();
	}
}
