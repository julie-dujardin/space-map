/**
 * The far H II regions as sprites: each a Gaussian ball of its size, its light
 * intrinsic, dimmed by the dust from the camera to it at the lines' K. They are
 * surface brightness, so they draw through the glow's exposure and its curve:
 * screen blending of `1 - exp(-x)` adds in linear light before the curve, as if
 * they were in the map. They read nothing that loads but the dust's column map,
 * so they hold still while stars load, and with nothing moving no frame draws.
 *
 * A sprite is at least a pixel wide, so a far region keeps its light. It fades
 * out as the camera nears it: inside, there is no volume to show.
 */

import {
	BufferAttribute,
	CustomBlending,
	AddEquation,
	InstancedBufferAttribute,
	InstancedBufferGeometry,
	Matrix3,
	Mesh,
	OneFactor,
	OneMinusDstColorFactor,
	ShaderMaterial,
	Vector3,
	Vector4,
	type Matrix4,
	type PerspectiveCamera,
	type Scene,
	type Texture
} from 'three';
import { DUST_COLUMN_GLSL } from '$lib/scene/dust/lookup';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { lineDepth, type EmissionRegions, type GlowEmission } from './emission';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

/** Flux from flux at 10 pc: (10 pc)². */
const AT_TEN_PC = 100;
/** Widths of the sprite's square, in its sigma: the Gaussian outside is 1%. */
const EXTENT_SIGMA = 3;
/** The share of a Gaussian's light inside a disc of `EXTENT_SIGMA`. */
const INSIDE = 1 - Math.exp(-0.5 * EXTENT_SIGMA * EXTENT_SIGMA);
/** Drawn after the glow, before every opaque object. */
const RENDER_ORDER = -1e6 + 1;

const vertex = (emission: GlowEmission): string => /* glsl */ `
uniform highp mat3 uNestToView;
uniform highp vec3 uCamera;
uniform highp vec4 uLens;
uniform highp float uPixel;
uniform highp float uExposure;
uniform highp sampler2D uGain;
uniform highp sampler2DArray uColumns;
uniform highp vec3 uColumnOrigin;
attribute highp vec3 region;
attribute highp float sigma;
attribute highp float light;
varying highp vec2 vAt;
varying highp vec3 vPeak;
${DUST_COLUMN_GLSL}

void main() {
	highp vec3 v = uNestToView * (region - uCamera);
	highp float d = length(v);
	float fade = smoothstep(1.0, 3.0, d / sigma);
	if (v.z >= 0.0 || fade <= 0.0) {
		gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
		vPeak = vec3(0.0);
		vAt = vec2(0.0);
		return;
	}
	// Angular sigma, at least a pixel.
	highp float s = max(sigma / d, uPixel);
	float column = dustColumn(uColumns, uColumnOrigin, region - uColumnOrigin);
	vec3 flux = light * ${glslVec3(emission.lines.colour)} * ${glslFloat(AT_TEN_PC)} / (d * d) * exp(-column * ${glslVec3(lineDepth(emission))});
	float gain = uExposure * exp(texelFetch(uGain, ivec2(0), 0).g);
	vPeak = flux * (gain * fade / (6.2831853 * s * s * ${glslFloat(INSIDE)}));
	vAt = position.xy * ${glslFloat(EXTENT_SIGMA)};
	highp vec2 at = vec2(uLens.x * v.x + uLens.z * v.z, uLens.y * v.y + uLens.w * v.z) / -v.z;
	gl_Position = vec4(at + position.xy * uLens.xy * (s * ${glslFloat(EXTENT_SIGMA)}), 0.0, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
uniform highp float uShare;
varying highp vec2 vAt;
varying highp vec3 vPeak;

void main() {
	highp float r2 = dot(vAt, vAt);
	if (r2 > ${glslFloat(EXTENT_SIGMA * EXTENT_SIGMA)}) discard;
	gl_FragColor = vec4((1.0 - exp(-vPeak * exp(-0.5 * r2))) * uShare, 1.0);
}
`;

/** Where the columns from the camera's side are read: a map and its origin. */
export interface ColumnMap {
	map: Texture;
	origin: Vec3;
}

const _view = new Matrix3();

export class GlowRegions {
	private readonly mesh: Mesh<InstancedBufferGeometry, ShaderMaterial>;
	private readonly toTree = new Matrix3();

	/** `nestAxes` is the rotation from tree axes to nest axes. */
	constructor(
		scene: Scene,
		regions: EmissionRegions,
		emission: GlowEmission,
		private readonly nestAxes: Matrix3
	) {
		const n = regions.light.length;
		const at = new Float32Array(n * 3);
		for (let i = 0; i < n; i++) at.set([regions.x[i], regions.y[i], regions.z[i]], 3 * i);
		const geometry = new InstancedBufferGeometry();
		geometry.setAttribute(
			'position',
			new BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3)
		);
		geometry.setIndex([0, 1, 2, 0, 2, 3]);
		geometry.setAttribute('region', new InstancedBufferAttribute(at, 3));
		geometry.setAttribute('sigma', new InstancedBufferAttribute(regions.sigma, 1));
		geometry.setAttribute('light', new InstancedBufferAttribute(regions.light, 1));
		geometry.instanceCount = n;
		const material = new ShaderMaterial({
			uniforms: {
				uNestToView: { value: new Matrix3() },
				uCamera: { value: new Vector3() },
				uLens: { value: new Vector4() },
				uPixel: { value: 0 },
				uExposure: { value: 0 },
				uGain: { value: null as Texture | null },
				uColumns: { value: null as Texture | null },
				uColumnOrigin: { value: new Vector3() },
				uShare: { value: 0 }
			},
			vertexShader: vertex(emission),
			fragmentShader: FRAGMENT,
			blending: CustomBlending,
			blendEquation: AddEquation,
			blendSrc: OneMinusDstColorFactor,
			blendDst: OneFactor,
			depthTest: false,
			depthWrite: false,
			toneMapped: false
		});
		this.mesh = new Mesh(geometry, material);
		this.mesh.name = 'glow-regions';
		this.mesh.frustumCulled = false;
		this.mesh.matrixAutoUpdate = false;
		this.mesh.renderOrder = RENDER_ORDER;
		this.mesh.visible = false;
		scene.add(this.mesh);
	}

	hide(): void {
		this.mesh.visible = false;
	}

	/**
	 * `at` is the camera on nest axes, `exposure` the glow's with the gain by
	 * place, `gain` the eye's texture, `pixel` the angle of a CSS pixel at the
	 * view's centre.
	 */
	show(
		at: Vec3,
		columns: ColumnMap,
		gain: Texture,
		exposure: number,
		share: number,
		camera: PerspectiveCamera,
		sceneToTree: Matrix4,
		pixel: number
	): void {
		const { uniforms } = this.mesh.material;
		const p = camera.projectionMatrix.elements;
		(uniforms.uLens.value as Vector4).set(p[0], p[5], p[8], p[9]);
		(uniforms.uCamera.value as Vector3).set(...at);
		(uniforms.uColumnOrigin.value as Vector3).set(...columns.origin);
		uniforms.uColumns.value = columns.map;
		uniforms.uGain.value = gain;
		uniforms.uExposure.value = exposure;
		uniforms.uShare.value = share;
		uniforms.uPixel.value = pixel;
		// Nest to view: the transpose of view to nest, all rotations.
		this.toTree.setFromMatrix4(sceneToTree);
		_view.setFromMatrix4(camera.matrixWorld);
		(uniforms.uNestToView.value as Matrix3)
			.copy(this.nestAxes)
			.multiply(this.toTree)
			.multiply(_view)
			.transpose();
		this.mesh.visible = share > 0;
	}

	dispose(): void {
		this.mesh.removeFromParent();
		this.mesh.geometry.dispose();
		this.mesh.material.dispose();
	}
}
