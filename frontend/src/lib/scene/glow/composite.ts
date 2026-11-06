/**
 * The glow on the screen. It draws first, like the skybox, and reads no depth,
 * so every solid thing draws over it on either depth path. `1 - exp(-g)` stays
 * under the bloom threshold, and composes with the stars' screen blending in
 * any order.
 *
 * Far outside, a map about the Galaxy holds the disc at about a screen pixel a
 * texel (`outside.ts`); the octahedral map holds the rest of the sky. Each map
 * has its own frame, so the blend from the last map reads each in its own.
 */

import {
	AddEquation,
	BufferAttribute,
	BufferGeometry,
	CustomBlending,
	Matrix3,
	Mesh,
	OneFactor,
	OneMinusDstColorFactor,
	ShaderMaterial,
	Vector4,
	type Matrix4,
	type PerspectiveCamera,
	type Scene,
	type Texture
} from 'three';
import { octUvGlsl } from '$lib/scene/dust/octahedral';
import type { GalaxyFrame } from './outside';

/** The map about the Galaxy fades out over this share of its half width at its
 *  edge, so its edge does not show where the halo is faint in both maps. */
const EDGE_SHARE = 0.05;

const VERTEX = /* glsl */ `
uniform highp mat3 uRayAxes;
uniform highp vec4 uLens;
varying highp vec3 vRay;

void main() {
	gl_Position = vec4(position.xy, 0.0, 1.0);
	vRay = uRayAxes * vec3((position.xy + uLens.zw) * uLens.xy, -1.0);
}
`;

const fragment = (size: number): string => /* glsl */ `
uniform highp sampler2D uMap;
uniform highp sampler2D uPrevious;
uniform highp float uBlend;
uniform highp sampler2D uGain;
uniform highp float uExposure;
uniform highp float uShare;
uniform highp sampler2D uGalaxy;
uniform highp sampler2D uGalaxyPrevious;
uniform highp mat3 uFrame;
uniform highp mat3 uFramePrevious;
/** Tangent of the half width and share of each map about the Galaxy: front in
 *  x and y, previous in z and w. A share of 0 means none. */
uniform highp vec4 uGalaxyShape;
varying highp vec3 vRay;
${octUvGlsl(size)}

// The sky map's light, or where the map about the Galaxy holds the ray, a mix
// toward it by its share.
highp vec3 galaxyMix(highp sampler2D map, highp mat3 frame, highp vec2 shape, highp vec3 ray, highp vec3 sky) {
	if (shape.y <= 0.0) return sky;
	highp vec3 c = ray * frame;
	if (c.z <= 0.0) return sky;
	highp vec2 q = c.xy / (c.z * shape.x);
	highp float edge = 1.0 - max(abs(q.x), abs(q.y));
	if (edge <= 0.0) return sky;
	highp vec3 galaxy = textureLod(map, q * 0.5 + 0.5, 0.0).rgb;
	return mix(sky, galaxy, shape.y * min(edge * ${(1 / EDGE_SHARE).toFixed(1)}, 1.0));
}

void main() {
	highp vec3 ray = normalize(vRay);
	highp vec2 uv = dustOctUv(ray);
	highp vec3 glow = galaxyMix(uGalaxy, uFrame, uGalaxyShape.xy, ray, textureLod(uMap, uv, 0.0).rgb);
	if (uBlend < 1.0) {
		highp vec3 previous = textureLod(uPrevious, uv, 0.0).rgb;
		previous = galaxyMix(uGalaxyPrevious, uFramePrevious, uGalaxyShape.zw, ray, previous);
		glow = mix(previous, glow, uBlend);
	}
	// The eye's gain over the Sun's exposure, in log (eye.ts).
	glow *= uExposure * exp(texelFetch(uGain, ivec2(0), 0).g);
	gl_FragColor = vec4((1.0 - exp(-glow)) * uShare, 1.0);
}
`;

/** What the composite reads of one map: the sky, and the map about the Galaxy
 *  with its frame where there is one. */
export interface GlowMapView {
	sky: Texture;
	galaxy: Texture | null;
	frame: GalaxyFrame | null;
}

function setFrame(out: Matrix3, frame: GalaxyFrame | null): void {
	if (!frame) return;
	const a = frame.axes;
	// The axes are columns; Matrix3.set takes rows.
	out.set(a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8]);
}

/** Before every opaque object. */
const RENDER_ORDER = -1e6;

const _camera = new Matrix3();

export class GlowComposite {
	private readonly mesh: Mesh<BufferGeometry, ShaderMaterial>;
	private readonly axes = new Matrix3();
	private readonly toTree = new Matrix3();

	/** `nestAxes` is the rotation from tree axes to nest axes. */
	constructor(
		scene: Scene,
		size: number,
		private readonly nestAxes: Matrix3
	) {
		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3)
		);
		const material = new ShaderMaterial({
			uniforms: {
				uMap: { value: null as Texture | null },
				uPrevious: { value: null as Texture | null },
				uBlend: { value: 1 },
				uGain: { value: null as Texture | null },
				uExposure: { value: 0 },
				uShare: { value: 0 },
				uGalaxy: { value: null as Texture | null },
				uGalaxyPrevious: { value: null as Texture | null },
				uFrame: { value: new Matrix3() },
				uFramePrevious: { value: new Matrix3() },
				uGalaxyShape: { value: new Vector4() },
				uRayAxes: { value: this.axes },
				uLens: { value: new Vector4() }
			},
			vertexShader: VERTEX,
			fragmentShader: fragment(size),
			blending: CustomBlending,
			blendEquation: AddEquation,
			blendSrc: OneMinusDstColorFactor,
			blendDst: OneFactor,
			depthTest: false,
			depthWrite: false,
			toneMapped: false
		});
		this.mesh = new Mesh(geometry, material);
		this.mesh.name = 'glow';
		this.mesh.frustumCulled = false;
		this.mesh.matrixAutoUpdate = false;
		this.mesh.renderOrder = RENDER_ORDER;
		this.mesh.visible = false;
		scene.add(this.mesh);
	}

	hide(): void {
		this.mesh.visible = false;
	}

	show(
		map: GlowMapView,
		previous: GlowMapView,
		blend: number,
		gain: Texture,
		exposure: number,
		share: number,
		camera: PerspectiveCamera,
		sceneToTree: Matrix4
	): void {
		const { uniforms } = this.mesh.material;
		uniforms.uMap.value = map.sky;
		uniforms.uPrevious.value = previous.sky;
		// A sampler must hold a texture even where its share is 0.
		uniforms.uGalaxy.value = map.galaxy ?? map.sky;
		uniforms.uGalaxyPrevious.value = previous.galaxy ?? previous.sky;
		setFrame(uniforms.uFrame.value as Matrix3, map.frame);
		setFrame(uniforms.uFramePrevious.value as Matrix3, previous.frame);
		const shape = (f: GalaxyFrame | null, galaxy: Texture | null) =>
			f && galaxy ? [f.tan, f.share] : [1, 0];
		(uniforms.uGalaxyShape.value as Vector4).set(
			...(shape(map.frame, map.galaxy) as [number, number]),
			...(shape(previous.frame, previous.galaxy) as [number, number])
		);
		uniforms.uBlend.value = blend;
		uniforms.uGain.value = gain;
		uniforms.uExposure.value = exposure;
		uniforms.uShare.value = share;
		const p = camera.projectionMatrix.elements;
		(uniforms.uLens.value as Vector4).set(1 / p[0], 1 / p[5], p[8], p[9]);
		this.toTree.setFromMatrix4(sceneToTree);
		_camera.setFromMatrix4(camera.matrixWorld);
		this.axes.copy(this.nestAxes).multiply(this.toTree).multiply(_camera);
		this.mesh.visible = true;
	}

	dispose(): void {
		this.mesh.removeFromParent();
		this.mesh.geometry.dispose();
		this.mesh.material.dispose();
	}
}
