/**
 * Ring annulus node: a flat disc whose albedo is sampled from 1-D radial
 * profile WebPs (`backscattered`, `unlitside`, `transparency`, `color`)
 * shipped per body under `v1/rings/{id}/`. The 5th channel
 * (`forwardscattered`) is exported but unused for now — the simpler lit/unlit
 * blend ignores it.
 *
 * The mesh is added directly to the scene as a sibling of the body's mesh
 * (not a child) so the planet's triaxial-flattening scale doesn't distort the
 * circular profile; the renderer reapplies its position and orientation each
 * frame in step with the body, then writes per-frame `uSunDir` so the
 * fragment shader can pick lit-side vs unlit-side at the right cadence.
 */

import {
	DoubleSide,
	LinearFilter,
	type Material,
	Mesh,
	MeshDepthMaterial,
	NormalBlending,
	RGBADepthPacking,
	RingGeometry,
	ShaderMaterial,
	SRGBColorSpace,
	type Texture,
	type TextureLoader,
	UniformsLib,
	UniformsUtils,
	Vector3
} from 'three';
import { kmToScene } from '$lib/math/units';
import { DATA_BASE } from '$lib/fetch/data-base';

export interface RingMeta {
	source: string;
	organisation: string;
	inner_radius_km: number;
	outer_radius_km: number;
	sample_count: number;
	color_space?: string;
	channels: {
		backscattered: string;
		forwardscattered: string;
		unlitside: string;
		transparency: string;
		color: string;
	};
	attribution?: string;
	description?: string;
}

/** Per-body ring scene data, owned by `BodyObjects.rings`. */
export interface RingNode {
	mesh: Mesh;
	material: ShaderMaterial;
	/** Outer ring radius in scene units. Used by the renderer to grow the
	 *  shadow-camera frustum so the planet's shadow on the rings stays
	 *  on-screen even when the camera is zoomed in close to the planet. */
	outerScene: number;
}

const RING_ANGULAR_SEGMENTS = 256;

/**
 * Alpha threshold for shadow casting. Fragments where the ring is more
 * transparent than this don't write to the shadow map — keeps the
 * Cassini division and other gaps clearly visible in Saturn's projected
 * ring shadow instead of a solid disc.
 */
const RING_SHADOW_ALPHA_THRESHOLD = 0.35;

function loadTexture(loader: TextureLoader, url: string, srgb: boolean): Promise<Texture> {
	return new Promise((resolve, reject) => {
		loader.load(
			url,
			(tex) => {
				if (srgb) tex.colorSpace = SRGBColorSpace;
				// Sharp 1-D profile — bilinear over a 1×N strip is the expected
				// look; mip generation costs extra GPU memory for no gain since
				// the texel-to-pixel ratio is set by camera distance, not mip LOD.
				tex.minFilter = LinearFilter;
				tex.magFilter = LinearFilter;
				tex.generateMipmaps = false;
				tex.needsUpdate = true;
				resolve(tex);
			},
			undefined,
			reject
		);
	});
}

const VERTEX_SHADER = `
	#include <common>
	#include <shadowmap_pars_vertex>
	#include <logdepthbuf_pars_vertex>

	varying vec3 vLocalPos;
	varying vec3 vWorldNormal;

	void main() {
		vLocalPos = position;
		// shadowmap_vertex reads \`worldPosition\` (vec4) and \`transformedNormal\`
		// (view-space normal) to compute the per-light shadow-coord varyings.
		// Passing the world normal as transformedNormal is fine here: the only
		// downstream use is a normal-bias offset, which we leave at default 0,
		// so the bias multiplication zeros out regardless of frame.
		vec4 worldPosition = modelMatrix * vec4(position, 1.0);
		vec3 transformedNormal = normalize(mat3(modelMatrix) * vec3(0.0, 1.0, 0.0));
		vWorldNormal = transformedNormal;
		gl_Position = projectionMatrix * viewMatrix * worldPosition;
		#include <shadowmap_vertex>
		#include <logdepthbuf_vertex>
	}
`;

/**
 * Lit/unlit-only fragment shader. The lit face of the ring (the one whose
 * outward normal points toward the sun) samples `backscattered` and tints by
 * the Cassini-derived `color` profile; the unlit face samples `unlitside`
 * and tints by a fixed warm-white constant — the BJJ color profile is
 * calibrated against backscattered light only, so reusing it on the unlit
 * side would distort the gap-vs-material contrast. Forward-scattering is
 * intentionally skipped for v1.
 *
 * Radial sampling: vertices are pre-rotated so the ring sits in the local XZ
 * plane; the radial coordinate is `length(localPos.xz)`, normalised to
 * [0, 1] across [inner, outer] and used as the U on each 1×N profile.
 *
 * Transparency convention follows BJJ: profile value = 1 → empty space
 * (transparent), 0 → opaque ring material. Alpha is therefore `1 - profile`.
 *
 * Side detection: a single DoubleSide draw uses `gl_FrontFacing` to know
 * which face this fragment belongs to, then flips the world-space normal so
 * the lit/unlit test sees the *outward* normal regardless of side.
 */
const FRAGMENT_SHADER = `
	#include <common>
	#include <packing>
	#include <shadowmap_pars_fragment>
	#include <logdepthbuf_pars_fragment>

	uniform sampler2D uBackscattered;
	uniform sampler2D uUnlitside;
	uniform sampler2D uTransparency;
	uniform sampler2D uColor;
	uniform float uInnerScene;
	uniform float uOuterScene;
	uniform vec3 uSunDir;

	varying vec3 vLocalPos;
	varying vec3 vWorldNormal;

	// Per BJJ: the Cassini-derived color profile only fits backscattered
	// light. For the unlit side they suggest a warm near-white tint.
	const vec3 UNLIT_TINT = vec3(1.0, 0.97075, 0.952);

	void main() {
		float radius = length(vLocalPos.xz);
		float t = (radius - uInnerScene) / (uOuterScene - uInnerScene);
		// Outside the annulus envelope: discard so anti-aliased edges don't
		// pick up clamped boundary samples.
		if (t < 0.0 || t > 1.0) discard;

		vec2 uv = vec2(clamp(t, 0.0, 1.0), 0.5);

		// gl_FrontFacing: outward face of the annulus (vertices wound CCW from
		// +Y). Flip the world normal on the back face so the lit test compares
		// against the outward direction of *this* face.
		vec3 N = gl_FrontFacing ? vWorldNormal : -vWorldNormal;

		// Lit if the sun is on the same side of the ring plane as this face.
		bool lit = dot(uSunDir, N) > 0.0;

		vec3 albedo;
		vec3 tint;
		if (lit) {
			albedo = texture2D(uBackscattered, uv).rgb;
			tint = texture2D(uColor, uv).rgb;
		} else {
			albedo = texture2D(uUnlitside, uv).rgb;
			tint = UNLIT_TINT;
		}
		// BJJ transparency: 1.0 = empty space, 0.0 = opaque material.
		float alpha = 1.0 - texture2D(uTransparency, uv).r;

		// Saturn's shadow on the rings: sample the directional shadow map
		// (the same one the planet meshes cast into) and modulate the lit
		// contribution. The unlit-side appearance comes from sunlight
		// transmitting through the material — also blocked when the planet
		// occludes the sun — so the shadow factor multiplies both branches.
		// Falls back to a no-op when the renderer is in solar-system view
		// (NUM_DIR_LIGHT_SHADOWS = 0, e.g. PointLight active).
		float shadow = 1.0;
		#if NUM_DIR_LIGHT_SHADOWS > 0
			DirectionalLightShadow ds = directionalLightShadows[0];
			shadow = getShadow(
				directionalShadowMap[0],
				ds.shadowMapSize,
				ds.shadowIntensity,
				ds.shadowBias,
				ds.shadowRadius,
				vDirectionalShadowCoord[0]
			);
		#endif

		gl_FragColor = vec4(albedo * tint * shadow, alpha);
		#include <logdepthbuf_fragment>
	}
`;

/**
 * Custom depth material for the shadow-casting pass. Three's default
 * MeshDepthMaterial writes a solid disc — fine for an opaque sphere, but a
 * ring is mostly empty space. We patch the depth shader to sample the
 * transparency profile and discard fragments where the ring is more empty
 * than {@link RING_SHADOW_ALPHA_THRESHOLD}, so the projected shadow on
 * Saturn shows the ring banding (Cassini division, A/B/C boundaries) instead
 * of an opaque disc.
 *
 * `depthPacking: RGBADepthPacking` matches what `WebGLShadowMap` expects when
 * the renderer hasn't been configured for depth textures — same packing the
 * stock `MeshDepthMaterial` uses on receiveShadow surfaces.
 */
function makeRingDepthMaterial(
	transparency: Texture,
	innerScene: number,
	outerScene: number
): MeshDepthMaterial {
	const material = new MeshDepthMaterial({
		depthPacking: RGBADepthPacking,
		side: DoubleSide
	});
	material.onBeforeCompile = (shader) => {
		shader.uniforms.uTransparency = { value: transparency };
		shader.uniforms.uInnerScene = { value: innerScene };
		shader.uniforms.uOuterScene = { value: outerScene };
		shader.uniforms.uAlphaThreshold = { value: RING_SHADOW_ALPHA_THRESHOLD };

		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vRingLocalPos;')
			.replace('#include <begin_vertex>', '#include <begin_vertex>\nvRingLocalPos = position;');

		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>
				uniform sampler2D uTransparency;
				uniform float uInnerScene;
				uniform float uOuterScene;
				uniform float uAlphaThreshold;
				varying vec3 vRingLocalPos;`
			)
			.replace(
				'void main() {',
				`void main() {
					float ringRadius = length(vRingLocalPos.xz);
					float ringT = (ringRadius - uInnerScene) / (uOuterScene - uInnerScene);
					if (ringT < 0.0 || ringT > 1.0) discard;
					float ringAlpha = 1.0 - texture2D(uTransparency, vec2(clamp(ringT, 0.0, 1.0), 0.5)).r;
					if (ringAlpha < uAlphaThreshold) discard;
				`
			);
	};
	return material;
}

export async function loadRingNode(
	bodyId: string,
	meta: RingMeta,
	textureLoader: TextureLoader
): Promise<RingNode | null> {
	const innerScene = kmToScene(meta.inner_radius_km);
	const outerScene = kmToScene(meta.outer_radius_km);

	// Color channel is sRGB (perceptual albedo tint); the scalar profiles are
	// linear (packed uint8 luminance, not gamma-encoded).
	const baseUrl = `${DATA_BASE}/v1/rings/${bodyId}`;
	const ch = meta.channels;
	let backscattered: Texture, unlitside: Texture, transparency: Texture, color: Texture;
	try {
		[backscattered, unlitside, transparency, color] = await Promise.all([
			loadTexture(textureLoader, `${baseUrl}/${ch.backscattered}`, false),
			loadTexture(textureLoader, `${baseUrl}/${ch.unlitside}`, false),
			loadTexture(textureLoader, `${baseUrl}/${ch.transparency}`, false),
			loadTexture(textureLoader, `${baseUrl}/${ch.color}`, true)
		]);
	} catch (err) {
		console.warn(`Failed to load ring textures for ${bodyId}:`, err);
		return null;
	}

	// Merge Three's light/shadow uniforms (directionalShadowMap[],
	// directionalShadowMatrix[], DirectionalLightShadow struct array) so the
	// `<shadowmap_pars_*>` chunks find what they need. `lights: true` tells
	// the WebGLRenderer to populate those uniforms with the scene's actual
	// shadow data each frame.
	const material = new ShaderMaterial({
		uniforms: UniformsUtils.merge([
			UniformsLib.lights,
			{
				uBackscattered: { value: backscattered },
				uUnlitside: { value: unlitside },
				uTransparency: { value: transparency },
				uColor: { value: color },
				uInnerScene: { value: innerScene },
				uOuterScene: { value: outerScene },
				uSunDir: { value: new Vector3(1, 0, 0) }
			}
		]),
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		transparent: true,
		depthWrite: false,
		blending: NormalBlending,
		side: DoubleSide,
		lights: true
	});

	// UniformsUtils.merge deep-clones values via toJSON/fromJSON, which strips
	// the live Texture / Vector3 references and replaces them with plain objects.
	// Re-pin our own uniforms after the merge so the shader actually samples the
	// loaded WebPs and the per-frame `uSunDir` mutation propagates.
	material.uniforms.uBackscattered.value = backscattered;
	material.uniforms.uUnlitside.value = unlitside;
	material.uniforms.uTransparency.value = transparency;
	material.uniforms.uColor.value = color;
	material.uniforms.uInnerScene.value = innerScene;
	material.uniforms.uOuterScene.value = outerScene;
	material.uniforms.uSunDir.value = new Vector3(1, 0, 0);

	// RingGeometry lies in the XY plane with normals +Z; rotate to XZ plane
	// (normals +Y) so applyOrientation's pole-to-+Y mapping puts the ring on
	// the equator with no extra fixup.
	const geometry = new RingGeometry(innerScene, outerScene, RING_ANGULAR_SEGMENTS, 1);
	geometry.rotateX(-Math.PI / 2);

	const mesh = new Mesh(geometry, material);
	mesh.frustumCulled = false; // repositioned by the renderer each frame
	mesh.renderOrder = 1; // draw after opaque planet so transparent alpha composites cleanly
	mesh.receiveShadow = true; // planet shadow on rings
	mesh.castShadow = true; // ring shadow on planet (depth-only pass uses customDepthMaterial)
	mesh.customDepthMaterial = makeRingDepthMaterial(transparency, innerScene, outerScene);
	mesh.userData.isRingMesh = true;

	return { mesh, material, outerScene };
}

/** Dispose all GPU resources owned by a ring node. */
export function disposeRingNode(ring: RingNode): void {
	ring.mesh.geometry.dispose();
	const uniforms = ring.material.uniforms as Record<string, { value: Texture | unknown }>;
	for (const key of ['uBackscattered', 'uUnlitside', 'uTransparency', 'uColor']) {
		const tex = uniforms[key]?.value as Texture | undefined;
		tex?.dispose();
	}
	(ring.mesh.material as Material).dispose();
	(ring.mesh.customDepthMaterial as Material | undefined)?.dispose();
}
