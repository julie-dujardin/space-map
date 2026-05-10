/**
 * Ring annulus node: a flat disc whose albedo is sampled from 1-D radial
 * profile WebPs (`backscattered`, `forwardscattered`, `unlitside`,
 * `transparency`, `color`) shipped per body under `v1/rings/{id}/`.
 *
 * The mesh is added directly to the scene as a sibling of the body's mesh
 * (not a child) so the planet's triaxial-flattening scale doesn't distort the
 * circular profile; the renderer reapplies its position and orientation each
 * frame in step with the body, then writes per-frame `uSunDir` so the
 * fragment shader can pick lit-side vs unlit-side at the right cadence and
 * compute the phase-angle blend between back/unlit/forward scatter.
 *
 * References:
 *  - Björn Jónsson's source page documents the channel meanings, the
 *    transparency convention (1 = empty, 0 = opaque), the warning that the
 *    color profile is calibrated against backscatter only, and the warm
 *    near-white tint suggestion for the unlit branch:
 *    https://bjj.mmedia.is/data/s_rings/index.html
 *  - John Spencer's ring-render notes (SwRI) describe the radial-profile
 *    rendering recipe and the Beer–Lambert-with-slant-correction shadow
 *    formulation used by {@link attachRingShadowToPlanet}:
 *    https://www2.boulder.swri.edu/~spencer/ringrender.html
 */

import {
	DoubleSide,
	LinearFilter,
	LinearMipmapLinearFilter,
	type Material,
	Mesh,
	type MeshStandardMaterial,
	NormalBlending,
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
	/** Transparency profile texture — shared with the planet's ray-march
	 *  ring-shadow path so we don't load it twice. */
	transparency: Texture;
	/** Inner ring radius in scene units. Used by the planet's ring-shadow
	 *  ray-march to clip intersections to the actual annulus. */
	innerScene: number;
	/** Outer ring radius in scene units. Used by the renderer to grow the
	 *  shadow-camera frustum so the planet's shadow on the rings stays
	 *  on-screen even when the camera is zoomed in close to the planet,
	 *  and also by the ray-march clipping. */
	outerScene: number;
	/** Live per-frame uniforms on the planet material's ring-shadow path —
	 *  null until {@link attachRingShadowToPlanet} runs. The renderer mutates
	 *  the contained Vector3 values in place each frame. */
	planetShadow: PlanetRingShadowUniforms | null;
}

const RING_ANGULAR_SEGMENTS = 256;

function loadTexture(loader: TextureLoader, url: string, srgb: boolean): Promise<Texture> {
	return new Promise((resolve, reject) => {
		loader.load(
			url,
			(tex) => {
				if (srgb) tex.colorSpace = SRGBColorSpace;
				// 1×13177 radial profile: at distance many radial samples fall in
				// one pixel and a single nearest/linear tap aliases into sparkle,
				// while at grazing angles the U-gradient across the screen is far
				// higher than the V-gradient (V is constant) — exactly the case
				// anisotropic filtering is designed for. Trilinear + max anisotropy
				// addresses both. Three.js silently clamps anisotropy to whatever
				// the GPU advertises, so 16 is safe without poking the renderer.
				tex.minFilter = LinearMipmapLinearFilter;
				tex.magFilter = LinearFilter;
				tex.generateMipmaps = true;
				tex.anisotropy = 16;
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
	varying vec3 vWorldPos;
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
		vWorldPos = worldPosition.xyz;
		vWorldNormal = transformedNormal;
		gl_Position = projectionMatrix * viewMatrix * worldPosition;
		#include <shadowmap_vertex>
		#include <logdepthbuf_vertex>
	}
`;

/**
 * Phase-angle-aware fragment shader. Three sample sources per ring strip,
 * picked by ring-plane side and phase angle per BJJ's documentation:
 *
 *  - **Lit side** (observer and sun on the same side of the ring plane):
 *    blend between `backscattered` (low phase, color-tinted) and
 *    `forwardscattered` (high phase, warm-white tint) based on phase angle.
 *    Per BJJ, backscattered is "the appearance at phase angle 0°" and
 *    forwardscattered was "captured at phase angle 139°"; the blend lets
 *    the rings dim and shift toward forward as the camera moves to the
 *    far-azimuth side of the sun.
 *  - **Unlit side** (observer and sun on opposite sides of the ring plane):
 *    use the `unlitside` profile — this *is* the forward / transmitted
 *    appearance for opposite-side viewing per BJJ ("how well sunlight
 *    filters through the rings"). No phase blend on this side.
 *
 * The Cassini-derived `color` profile is calibrated against backscatter
 * only, so it's applied only to the backscattered branch; the forward and
 * unlit branches use a fixed warm-white tint per BJJ's recommendation.
 *
 * Geometry: side is decided by `dot(uSunDir, N) > 0` where N is the outward
 * normal of the face being viewed (gl_FrontFacing-flipped). Phase angle α
 * uses `cos α = dot(sunDir, viewDir)` against the auto-injected
 * `cameraPosition`.
 *
 * Radial sampling: vertices are pre-rotated so the ring sits in the local XZ
 * plane; the radial coordinate is `length(localPos.xz)`, normalised to
 * [0, 1] across [inner, outer] and used as the U on each 1×N profile.
 *
 * Transparency convention follows BJJ: profile value = 1 → empty space
 * (transparent), 0 → opaque ring material. Alpha is therefore `1 - profile`.
 */
const FRAGMENT_SHADER = `
	#include <common>
	#include <packing>
	#include <shadowmap_pars_fragment>
	#include <logdepthbuf_pars_fragment>

	uniform sampler2D uBackscattered;
	uniform sampler2D uForwardscattered;
	uniform sampler2D uUnlitside;
	uniform sampler2D uTransparency;
	uniform sampler2D uColor;
	uniform float uInnerScene;
	uniform float uOuterScene;
	uniform vec3 uSunDir;

	varying vec3 vLocalPos;
	varying vec3 vWorldPos;
	varying vec3 vWorldNormal;

	// Per BJJ: the Cassini-derived color profile only fits backscattered
	// light. For the unlit / forward branches we tint by a near-white
	// constant — slightly warm for the diffuse unlit transmission, since
	// that's what BJJ recommends.
	const vec3 UNLIT_TINT = vec3(1.0, 0.97075, 0.952);

	// Slight red bias on top of the color profile for the forward-scatter
	// branch, matching BJJ's "becoming slightly redder" observation as
	// phase angle climbs.
	const vec3 FORWARD_TINT_BIAS = vec3(1.02, 0.99, 0.97);

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

		// cosAlpha = cos(phase angle). +1 = sun aligned with view (low phase),
		// -1 = sun directly opposite view (high phase). cameraPosition is
		// auto-injected by three.js.
		vec3 viewDir = normalize(cameraPosition - vWorldPos);
		float cosAlpha = dot(uSunDir, viewDir);

		vec3 finalAlbedo;
		if (lit) {
			// Sun and observer on the same side of the ring plane. Blend
			// backscatter → forward scatter with phase angle. smoothstep
			// across the full [-1, 1] cosAlpha range gives a sigmoidal
			// transition centered on edge-on viewing (α = 90°) — at α = 139°
			// (BJJ's reference forward image), wForward ≈ 0.87, mostly
			// forward. Pure backscatter at α = 0°, pure forward at α → 180°
			// (which lit-side viewing can approach when the sun grazes the
			// ring plane and the camera sits on the far azimuthal side).
			//
			// Both branches share the Cassini-derived color profile: BJJ
			// notes it's photometrically calibrated against backscatter only,
			// but forward-scattered Cassini imagery (e.g. "In Saturn's
			// Shadow") clearly keeps the ring's tan/gold hue with a slight
			// red shift, so dropping color entirely (pure grayscale) is
			// visibly wrong. Using the same tint plus a small red bias on
			// the forward branch matches BJJ's "becoming slightly redder"
			// description while preserving the radial color variation.
			vec3 colorTint = texture2D(uColor, uv).rgb;
			vec3 forwardTint = colorTint * FORWARD_TINT_BIAS;
			vec3 back = texture2D(uBackscattered, uv).rgb * colorTint;
			vec3 forward = texture2D(uForwardscattered, uv).rgb * forwardTint;
			float wForward = 1.0 - smoothstep(-1.0, 1.0, cosAlpha);
			finalAlbedo = mix(back, forward, wForward);
		} else {
			// Sun and observer on opposite sides of the ring plane. BJJ's
			// unlitside profile *is* the transmitted-light appearance for
			// this geometry and doesn't get a separate phase-angle blend —
			// dense regions read dark, transparent regions glow brighter as
			// sunlight filters through.
			finalAlbedo = texture2D(uUnlitside, uv).rgb * UNLIT_TINT;
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

		gl_FragColor = vec4(finalAlbedo * shadow, alpha);
		#include <logdepthbuf_fragment>
	}
`;

/**
 * Per-frame uniforms driving the ring-shadow ray-march inside the planet's
 * MeshStandardMaterial — see {@link attachRingShadowToPlanet}. The renderer
 * updates each Vector3 in place each frame; the texture and radii are
 * loaded once.
 */
export interface PlanetRingShadowUniforms {
	uRingShadowTransparency: { value: Texture };
	uRingShadowInnerScene: { value: number };
	uRingShadowOuterScene: { value: number };
	/** World-space unit vector pointing from the planet toward the sun. */
	uRingShadowSunDir: { value: Vector3 };
	/** World-space unit vector along the planet's spin axis (= ring plane normal). */
	uRingShadowPoleDir: { value: Vector3 };
	/** World-space (focus-relative) position of the planet's center. */
	uRingShadowCenter: { value: Vector3 };
}

/**
 * Attach an analytical ring-shadow ray-march to the planet's standard
 * material. For each lit fragment we trace from the surface toward the sun,
 * intersect the ring plane, sample the transparency profile at the
 * intersection radius, and apply Beer–Lambert (with slant correction for
 * grazing solar elevation) to attenuate the direct light.
 *
 * Beats a shadow-map cast for transparent ring profiles: no rasterization
 * resolution, no dither artifacts, partial transparency comes out for free
 * via `pow(transparency, 1 / sin(elevation))`.
 *
 * `material.onBeforeCompile` triggers a one-shot recompile (we set
 * `needsUpdate`); the returned uniforms object is the live reference the
 * renderer mutates each frame.
 */
export function attachRingShadowToPlanet(
	planetMaterial: MeshStandardMaterial,
	innerScene: number,
	outerScene: number,
	transparency: Texture
): PlanetRingShadowUniforms {
	const uniforms: PlanetRingShadowUniforms = {
		uRingShadowTransparency: { value: transparency },
		uRingShadowInnerScene: { value: innerScene },
		uRingShadowOuterScene: { value: outerScene },
		uRingShadowSunDir: { value: new Vector3(1, 0, 0) },
		uRingShadowPoleDir: { value: new Vector3(0, 1, 0) },
		uRingShadowCenter: { value: new Vector3(0, 0, 0) }
	};

	planetMaterial.onBeforeCompile = (shader) => {
		Object.assign(shader.uniforms, uniforms);

		// Expose the fragment's world-space position to the fragment shader.
		// MeshStandardMaterial doesn't ship `vWorldPosition` to fragments by
		// default; we add our own varying so the ray-march can compute the
		// vector from surface → ring plane.
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vRingShadowWorldPos;')
			.replace(
				'#include <begin_vertex>',
				'#include <begin_vertex>\nvRingShadowWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;'
			);

		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>
				uniform sampler2D uRingShadowTransparency;
				uniform float uRingShadowInnerScene;
				uniform float uRingShadowOuterScene;
				uniform vec3 uRingShadowSunDir;
				uniform vec3 uRingShadowPoleDir;
				uniform vec3 uRingShadowCenter;
				varying vec3 vRingShadowWorldPos;

				float ringShadowFactor() {
					// Ray-plane intersect: starting from the lit surface, march
					// along the sun direction. The ring plane passes through the
					// planet's center with normal = pole direction.
					float denom = dot(uRingShadowSunDir, uRingShadowPoleDir);
					if (abs(denom) < 1e-6) return 1.0; // sun grazing the ring plane
					vec3 rel = vRingShadowWorldPos - uRingShadowCenter;
					float t = -dot(rel, uRingShadowPoleDir) / denom;
					if (t < 0.0) return 1.0; // ring is behind the sun from this surface point
					vec3 hit = rel + t * uRingShadowSunDir;
					// Radial distance in the ring plane (subtract out-of-plane component).
					vec3 hitPerp = hit - dot(hit, uRingShadowPoleDir) * uRingShadowPoleDir;
					float r = length(hitPerp);
					if (r < uRingShadowInnerScene || r > uRingShadowOuterScene) return 1.0;
					float u = (r - uRingShadowInnerScene) / (uRingShadowOuterScene - uRingShadowInnerScene);
					float trans = texture2D(uRingShadowTransparency, vec2(clamp(u, 0.0, 1.0), 0.5)).r;
					// Beer–Lambert with slant correction: ray traverses 1/sin(B)
					// times the normal optical depth where B is the sun's
					// elevation above the ring plane. transparency stored on
					// disk is exp(-tau_normal), so slant transmittance is
					// pow(transparency, 1/sin(B)). Clamp sinB to avoid blow-up
					// when the sun lies almost in the ring plane.
					float sinB = abs(denom);
					return pow(max(trans, 1e-4), 1.0 / max(sinB, 0.02));
				}`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				float ringShadow = ringShadowFactor();
				reflectedLight.directDiffuse *= ringShadow;
				reflectedLight.directSpecular *= ringShadow;`
			);
	};
	planetMaterial.needsUpdate = true;
	return uniforms;
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
	let backscattered: Texture,
		forwardscattered: Texture,
		unlitside: Texture,
		transparency: Texture,
		color: Texture;
	try {
		[backscattered, forwardscattered, unlitside, transparency, color] = await Promise.all([
			loadTexture(textureLoader, `${baseUrl}/${ch.backscattered}`, false),
			loadTexture(textureLoader, `${baseUrl}/${ch.forwardscattered}`, false),
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
				uForwardscattered: { value: forwardscattered },
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
	material.uniforms.uForwardscattered.value = forwardscattered;
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
	mesh.userData.isRingMesh = true;
	// Ring → planet shadow is handled by an analytical ray-march in the
	// planet's own material (see `attachRingShadowToPlanet`), so the ring
	// doesn't cast into the shadow map.

	return { mesh, material, transparency, innerScene, outerScene, planetShadow: null };
}

/** Dispose all GPU resources owned by a ring node. */
export function disposeRingNode(ring: RingNode): void {
	ring.mesh.geometry.dispose();
	const uniforms = ring.material.uniforms as Record<string, { value: Texture | unknown }>;
	for (const key of [
		'uBackscattered',
		'uForwardscattered',
		'uUnlitside',
		'uTransparency',
		'uColor'
	]) {
		const tex = uniforms[key]?.value as Texture | undefined;
		tex?.dispose();
	}
	(ring.mesh.material as Material).dispose();
}
