/**
 * The glow on the screen. It draws first, like the skybox, and reads no depth,
 * so every solid thing draws over it on either depth path. `1 - exp(-g)` stays
 * under the bloom threshold, and composes with the stars' screen blending in
 * any order.
 *
 * It reads one of three sources. The screen target of the march holds this
 * frame's rays at a part of the screen's resolution, and the composite scales
 * it up. The octahedral sky map holds the emission alone from the Sun, and the
 * composite reads it along each pixel's ray. The skybox's cube, blurred past
 * the size of its stars, is the sky from the Sun near the join (`glow-sky.ts`).
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
import { glslFloat } from '$lib/scene/dust/glsl';
import { octUvGlsl } from '$lib/scene/dust/octahedral';

/** What a composite reads: the screen target, an octahedral map of `size`, or
 *  the skybox's cube. */
export type CompositeSource = { kind: 'screen' } | { kind: 'sky'; size: number } | { kind: 'cube' };

const VERTEX = /* glsl */ `
uniform highp mat3 uRayAxes;
uniform highp vec4 uLens;
varying highp vec3 vRay;
varying highp vec2 vUv;

void main() {
	gl_Position = vec4(position.xy, 0.0, 1.0);
	vUv = position.xy * 0.5 + 0.5;
	vRay = uRayAxes * vec3((position.xy + uLens.zw) * uLens.xy, -1.0);
}
`;

/** Weights of a Gaussian of one texel's sigma, at 0 and 1 texel. */
const BLUR = [1, Math.exp(-0.5)];
const BLUR_SUM = (BLUR[0] + 2 * BLUR[1]) ** 2;

/** The screen target, with a Gaussian of one target texel: the march's noise is
 *  per texel, and this takes most of it out of a single pass. */
const SCREEN_READ = /* glsl */ `
highp vec3 readScreen() {
	highp vec2 texel = 1.0 / vec2(textureSize(uMap, 0));
	highp vec3 sum = vec3(0.0);
	for (int j = -1; j <= 1; j++) {
		for (int i = -1; i <= 1; i++) {
			highp float w = (i == 0 ? ${glslFloat(BLUR[0])} : ${glslFloat(BLUR[1])}) * (j == 0 ? ${glslFloat(BLUR[0])} : ${glslFloat(BLUR[1])});
			sum += w * textureLod(uMap, vUv + vec2(float(i), float(j)) * texel, 0.0).rgb;
		}
	}
	return sum * ${glslFloat(1 / BLUR_SUM)};
}`;

/** The skybox's cube at the place's gain `uExposure`, on the glow's curve: a
 *  value s of the cube is 1 - exp(-g) at the Sun's exposure. */
const CUBE_FRAGMENT = /* glsl */ `
uniform highp samplerCube uMap;
uniform highp float uExposure;
uniform highp float uShare;
uniform highp float uLod;
uniform highp float uIntensity;
varying highp vec3 vRay;

void main() {
	highp vec3 s = textureLod(uMap, normalize(vRay), uLod).rgb * uIntensity;
	highp vec3 shown = 1.0 - pow(max(1.0 - s, vec3(0.0)), vec3(uExposure));
	gl_FragColor = vec4(shown * uShare, 1.0);
}
`;

function fragment(source: CompositeSource): string {
	if (source.kind === 'cube') return CUBE_FRAGMENT;
	const read =
		source.kind === 'screen'
			? 'readScreen()'
			: 'textureLod(uMap, dustOctUv(normalize(vRay)), 0.0).rgb';
	return /* glsl */ `
uniform highp sampler2D uMap;
uniform highp float uExposure;
uniform highp float uShare;
varying highp vec3 vRay;
varying highp vec2 vUv;
${source.kind === 'sky' ? octUvGlsl(source.size) : SCREEN_READ}

void main() {
	highp vec3 glow = ${read} * uExposure;
	gl_FragColor = vec4((1.0 - exp(-glow)) * uShare, 1.0);
}
`;
}

const _camera = new Matrix3();

/** The view's rays on nest axes, as the march and the composite need them. */
export class ViewRays {
	/** View to nest axes. */
	readonly axes = new Matrix3();
	/** x and y over z of the view at the screen's edge, and the projection's offset. */
	readonly lens = new Vector4();
	private readonly toTree = new Matrix3();

	/** `nestAxes` is the rotation from tree axes to nest axes. */
	constructor(private readonly nestAxes: Matrix3) {}

	set(camera: PerspectiveCamera, sceneToTree: Matrix4): void {
		const p = camera.projectionMatrix.elements;
		this.lens.set(1 / p[0], 1 / p[5], p[8], p[9]);
		this.toTree.setFromMatrix4(sceneToTree);
		_camera.setFromMatrix4(camera.matrixWorld);
		this.axes.copy(this.nestAxes).multiply(this.toTree).multiply(_camera);
	}
}

/** Before every opaque object. */
const RENDER_ORDER = -1e6;

export class GlowComposite {
	private readonly mesh: Mesh<BufferGeometry, ShaderMaterial>;

	constructor(scene: Scene, source: CompositeSource, rays: Pick<ViewRays, 'axes' | 'lens'>) {
		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3)
		);
		const material = new ShaderMaterial({
			uniforms: {
				uMap: { value: null as Texture | null },
				uExposure: { value: 0 },
				uShare: { value: 0 },
				uLod: { value: 0 },
				uIntensity: { value: 1 },
				uRayAxes: { value: rays.axes },
				uLens: { value: rays.lens }
			},
			vertexShader: VERTEX,
			fragmentShader: fragment(source),
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

	/** Draw `map` at `exposure`, times `share`. The rays are this frame's. A
	 *  cube reads its mip `lod` and takes `intensity` before the exposure. */
	show(map: Texture, exposure: number, share: number, lod = 0, intensity = 1): void {
		const { uniforms } = this.mesh.material;
		uniforms.uMap.value = map;
		uniforms.uExposure.value = exposure;
		uniforms.uShare.value = share;
		uniforms.uLod.value = lod;
		uniforms.uIntensity.value = intensity;
		this.mesh.visible = true;
	}

	dispose(): void {
		this.mesh.removeFromParent();
		this.mesh.geometry.dispose();
		this.mesh.material.dispose();
	}
}
