/**
 * The glow on the screen. It draws first, like the skybox, and reads no depth,
 * so every solid thing draws over it on either depth path. `1 - exp(-g)` stays
 * under the bloom threshold, and composes with the stars' screen blending in
 * any order.
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
varying highp vec3 vRay;
${octUvGlsl(size)}

void main() {
	highp vec2 uv = dustOctUv(normalize(vRay));
	highp vec3 glow = textureLod(uMap, uv, 0.0).rgb;
	if (uBlend < 1.0) glow = mix(textureLod(uPrevious, uv, 0.0).rgb, glow, uBlend);
	// The eye's gain over the Sun's exposure, in log (eye.ts).
	glow *= uExposure * exp(texelFetch(uGain, ivec2(0), 0).g);
	gl_FragColor = vec4((1.0 - exp(-glow)) * uShare, 1.0);
}
`;

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
		map: Texture,
		previous: Texture,
		blend: number,
		gain: Texture,
		exposure: number,
		share: number,
		camera: PerspectiveCamera,
		sceneToTree: Matrix4
	): void {
		const { uniforms } = this.mesh.material;
		uniforms.uMap.value = map;
		uniforms.uPrevious.value = previous;
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
