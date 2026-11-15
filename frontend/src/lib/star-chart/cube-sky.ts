/**
 * The sky of a chart from a cube map that a renderer already holds: the
 * skybox of the map. One pass of a shader reads the cube into a target.
 */

import {
	Mesh,
	OrthographicCamera,
	PlaneGeometry,
	Scene,
	ShaderMaterial,
	WebGLRenderTarget,
	type CubeTexture,
	type WebGLRenderer
} from 'three';
import { centreScaleDeg, type ChartFrame } from './frame';
import { CHART_GLSL, rayUniforms, type Pixels, type SkySource } from './sky';

const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
	vUv = uv;
	gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

/** Taps on each side of a pixel, at most. */
const MAX_TAPS = 8;
/** How much of a pixel's brightest tap it keeps over its mean. A mean alone
 *  loses the stars of a small chart, since a star is one texel. */
const PEAK_SHARE = 0.7;

/** Cube texels along one pixel of a picture `width` wide, at the centre of the frame. */
export function texelsPerPixel(frame: ChartFrame, width: number, faceTexels: number): number {
	return ((centreScaleDeg(frame) * frame.width) / width) * (faceTexels / 90);
}

/** Taps on each side of a pixel: one per texel, up to the limit. Past the
 *  limit each tap reads a mip that holds its share of the pixel, so no texel
 *  falls between two taps. */
export function tapsPerSide(texels: number): number {
	return Math.min(Math.max(Math.ceil(texels), 1), MAX_TAPS);
}

// The read starts at the bottom row of the target, so the top of the frame is
// drawn there. The cube's axes are (-y, z, x) of ICRS.
const FRAGMENT = /* glsl */ `
uniform samplerCube uSky;
uniform vec2 uPixel;
uniform int uTaps;
varying vec2 vUv;
${CHART_GLSL}
vec3 cubeRay(vec2 uv) {
	vec3 ray = chartRay(uv);
	return vec3(-ray.y, ray.z, ray.x);
}

void main() {
	// A tap covers its share of the pixel: the GPU picks the mip from this step.
	vec3 centre = cubeRay(vUv);
	vec3 stepX = dFdx(centre) / float(uTaps);
	vec3 stepY = dFdy(centre) / float(uTaps);
	vec3 mean = vec3(0.0);
	vec3 peak = vec3(0.0);
	for (int i = 0; i < ${MAX_TAPS}; i++) {
		for (int j = 0; j < ${MAX_TAPS}; j++) {
			if (i >= uTaps || j >= uTaps) continue;
			vec2 offset = (vec2(float(i), float(j)) + 0.5) / float(uTaps) - 0.5;
			vec3 tap = textureGrad(uSky, cubeRay(vUv + offset * uPixel), stepX, stepY).rgb;
			mean += tap;
			peak = max(peak, tap);
		}
	}
	mean /= float(uTaps * uTaps);
	gl_FragColor = vec4(chartTone(mix(mean, peak, ${PEAK_SHARE})), 1.0);
}
`;

export class CubeSkySource implements SkySource {
	private readonly scene = new Scene();
	private readonly camera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);
	private readonly geometry = new PlaneGeometry(2, 2);
	private readonly material = new ShaderMaterial({
		vertexShader: VERTEX,
		fragmentShader: FRAGMENT,
		uniforms: {
			uSky: { value: null },
			uPixel: { value: [0, 0] },
			uTaps: { value: 1 },
			uRight: { value: [0, 0, 0] },
			uUp: { value: [0, 0, 0] },
			uForward: { value: [0, 0, 0] },
			uHalf: { value: [0, 0] }
		},
		depthTest: false,
		depthWrite: false,
		toneMapped: false
	});
	private readonly listeners = new Set<() => void>();
	private target: WebGLRenderTarget | null = null;

	/**
	 * @param cube J2000 equatorial faces in the order of the skybox, with mips
	 *   and `userData.faceTexels`. Null while the renderer holds none.
	 */
	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly cube: () => CubeTexture | null
	) {
		const quad = new Mesh(this.geometry, this.material);
		quad.frustumCulled = false;
		this.scene.add(quad);
	}

	async paint(frame: ChartFrame, width: number, height: number): Promise<Pixels | null> {
		const cube = this.cube();
		const { renderer } = this;
		if (!cube || renderer.getContext().isContextLost()) return null;
		if (!this.target) this.target = new WebGLRenderTarget(width, height, { depthBuffer: false });
		else this.target.setSize(width, height);
		const uniforms = this.material.uniforms;
		uniforms.uSky.value = cube;
		uniforms.uPixel.value = [1 / width, 1 / height];
		uniforms.uTaps.value = tapsPerSide(
			texelsPerPixel(frame, width, cube.userData.faceTexels as number)
		);
		Object.entries(rayUniforms(frame)).forEach(([name, value]) => {
			uniforms[name].value = value;
		});
		const data = new Uint8ClampedArray(width * height * 4);
		const before = renderer.getRenderTarget();
		renderer.setRenderTarget(this.target);
		renderer.render(this.scene, this.camera);
		renderer.readRenderTargetPixels(this.target, 0, 0, width, height, data);
		renderer.setRenderTarget(before);
		return { data, width, height };
	}

	onChange(listener: () => void): () => void {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	/** The renderer holds another cube. */
	changed(): void {
		for (const listener of this.listeners) listener();
	}

	dispose(): void {
		this.listeners.clear();
		this.target?.dispose();
		this.geometry.dispose();
		this.material.dispose();
	}
}
