/**
 * Ring annulus disc, albedo sampled from 1-D radial profiles shipped per body
 * as a single N×5 `v1/rings/{id}/strip.webp` (color, backscattered,
 * forwardscattered, unlitside, transparency=1−opacity). Split into separate
 * 1-row textures after decode so per-channel filtering can't bleed rows
 * together. Channel values are normalised; × `intensity_scale` recovers
 * physical brightness/opacity — the overexpose-rings toggle skips that scale.
 *
 * Mesh is a scene-level sibling of the body (not a child) so the planet's
 * triaxial flattening doesn't distort the circular profile.
 *
 * Refs: Björn Jónsson https://bjj.mmedia.is/data/s_rings/index.html (channel
 * meanings, color calibrated against backscatter only, warm-white unlit hint);
 * John Spencer https://www2.boulder.swri.edu/~spencer/ringrender.html (radial-
 * profile recipe + Beer–Lambert ring-shadow formulation used by {@link attachRingShadowToPlanet}).
 */

import {
	CanvasTexture,
	DoubleSide,
	InstancedBufferAttribute,
	InstancedMesh,
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
	Vector3
} from 'three';
import { kmToScene } from '$lib/math/units';
import { versionedUrl } from '$lib/fetch/data-base';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';

export type RingChannel =
	| 'color'
	| 'backscattered'
	| 'forwardscattered'
	| 'unlitside'
	| 'transparency';

/** The five channels every bundle has, plus the optional thickness profile. */
type StripRows = Record<RingChannel, number> & { thickness?: number };
type StripTextures = Record<RingChannel, Texture> & { thickness?: Texture };

/** One contributor to a bundle — bundles mix sources (e.g. Saturn mixes
 *  Björn Jónsson's photometry with NSSDCA vertical extents), so each states
 *  what it contributed rather than the bundle claiming one origin. */
export interface RingSource {
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
}

export interface RingMeta {
	/** Bundle name within the body; also its export sub-directory. */
	bundle: string;
	sources: RingSource[];
	inner_radius_km: number;
	outer_radius_km: number;
	sample_count: number;
	/** Stored channel value × this = physical value. */
	intensity_scale: number;
	/** km per unit of the thickness row; 0 = flat rings (no such row). */
	thickness_scale_km?: number;
	color_space?: string;
	strip: string;
	strip_height: number;
	strip_rows: StripRows;
	description?: string;
}

/** Per-body ring scene data, owned by `BodyObjects.rings`. */
export interface RingNode {
	mesh: Mesh;
	material: ShaderMaterial;
	/** Sheet stack for a vertically thick bundle; null when the bundle renders flat. */
	layers: InstancedMesh | null;
	/** Full vertical extent of the stack in scene units (0 = flat). */
	thicknessScene: number;
	/** Shared with the planet's ring-shadow ray-march so it isn't loaded twice. */
	transparency: Texture;
	/** Physical multiplier for stored channel values (1 when overexpose-rings is on). */
	intensityScale: number;
	/** Inner ring radius in scene units, for the planet's ray-march clipping. */
	innerScene: number;
	/** Outer ring radius in scene units, for the ray-march clipping. */
	outerScene: number;
	/** Planet material's ring-shadow uniforms; null until {@link attachRingShadowToPlanet} runs. */
	planetShadow: PlanetRingShadowUniforms | null;
	/** Ring material's planet-shadow uniforms; radii set once by `loadRingNode`'s caller. */
	planetShadowOnRing: PlanetShadowOnRingUniforms;
}

/**
 * Per-frame uniforms for the planet-shadow ray-march inside the ring's own
 * ShaderMaterial: traces each fragment toward the sun against the planet's
 * oblate spheroid, keeping the shadow crisp per-pixel instead of relying on
 * the directional shadow map (which stair-steps at close zoom).
 */
export interface PlanetShadowOnRingUniforms {
	/** World-space (focus-relative) position of the planet's center. */
	uPlanetCenter: { value: Vector3 };
	/** World-space unit vector along the planet's spin axis. */
	uPlanetPoleDir: { value: Vector3 };
	/** Planet equatorial radius in scene units; 0 disables the shadow. */
	uPlanetEquatorialScene: { value: number };
	/** Planet polar radius in scene units. */
	uPlanetPolarScene: { value: number };
}

const RING_ANGULAR_SEGMENTS = 256;
// Radial tessellation for thickness-displaced rings (vertex-sampled profile).
const RING_RADIAL_SEGMENTS = 96;
// Upper bound on the vertical sheet stack. The renderer picks the live count
// from on-screen spread — face-on one sheet suffices, edge-on needs the most —
// and above this, discrete sheets separate into visible lines more than a
// pixel apart.
export const RING_THICKNESS_LAYERS_MAX = 48;

/**
 * Peak opacity below which a bundle can't change any pixel, so the renderer
 * skips it unless the overexpose toggle is on. Occlusion (intensity alone)
 * sets the floor rather than additive brightness (intensity²), since it's
 * the more visible effect. A quarter of an 8-bit code value against white is
 * generous headroom: culled bundles (Jupiter's τ~5e-6 rings, Saturn's outer
 * tenuous system) sit orders of magnitude under it; the faintest survivor
 * (Neptune's, 0.0031) clears it 3×.
 */
export const RING_MIN_VISIBLE_ALPHA = 0.25 / 255;

/**
 * Fetch the body's N×5 strip and split each channel row into its own 2-tall
 * CanvasTexture. Split-after-decode avoids mipmapping averaging adjacent rows
 * into each other. Per-channel canvases (not TextureLoader) work around an
 * Android-Chrome bug that zeroes 1-px-tall VP8L WebPs, and let us downscale
 * past GL MAX_TEXTURE_SIZE (Saturn's strip is ~13177px; Adreno 5xx caps at
 * 4096). The doubled row lets mipmap generation succeed.
 */
async function loadStripTextures(
	url: string,
	rows: StripRows,
	maxTextureSize: number
): Promise<StripTextures> {
	const response = await fetch(url);
	if (!response.ok) {
		throw new Error(`Failed to load ${url}: ${response.status} ${response.statusText}`);
	}
	const blob = await response.blob();
	const bitmap = await createImageBitmap(blob);
	const targetWidth = Math.min(bitmap.width, maxTextureSize);
	if (targetWidth < bitmap.width) {
		console.info(
			`Ring strip ${url}: downscaling ${bitmap.width}px → ${targetWidth}px to fit GL MAX_TEXTURE_SIZE.`
		);
	}
	const textures = {} as StripTextures;
	for (const [channel, row] of Object.entries(rows) as [keyof StripTextures, number][]) {
		const canvas = document.createElement('canvas');
		canvas.width = targetWidth;
		canvas.height = 2;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error(`Failed to acquire 2D context for ring strip ${url}`);
		ctx.imageSmoothingEnabled = true;
		ctx.imageSmoothingQuality = 'high';
		ctx.drawImage(bitmap, 0, row, bitmap.width, 1, 0, 0, targetWidth, 1);
		ctx.drawImage(bitmap, 0, row, bitmap.width, 1, 0, 1, targetWidth, 1);

		const tex = new CanvasTexture(canvas);
		// Color is a perceptual albedo tint (sRGB); scalar profiles are linear.
		if (channel === 'color') tex.colorSpace = SRGBColorSpace;
		// 1×N radial profile at grazing angles: many samples per pixel plus a
		// screen-space U-gradient far steeper than V — exactly what trilinear
		// + anisotropic filtering is for. Three.js clamps anisotropy to the
		// GPU's max, so 16 is safe unconditionally.
		tex.minFilter = LinearMipmapLinearFilter;
		tex.magFilter = LinearFilter;
		tex.generateMipmaps = true;
		tex.anisotropy = 16;
		tex.needsUpdate = true;
		textures[channel] = tex;
	}
	bitmap.close();
	return textures;
}

const VERTEX_SHADER = `
	#include <common>
	#include <logdepthbuf_pars_vertex>

	uniform sampler2D uThickness;
	uniform float uThicknessScene; // 0 = flat ring, no displacement
	uniform float uInnerScene;
	uniform float uOuterScene;

	// Sheet index and live count in the vertical stack; deriving the offset
	// from the live count keeps sheets evenly spread at every LOD. A plain
	// (non-instanced) mesh leaves this unbound (GL defines 0), landing on
	// the midplane when uLayerCount is 1.
	attribute float aLayerIndex;
	uniform float uLayerCount;

	varying vec3 vLocalPos;
	varying vec3 vWorldPos;
	varying vec3 vWorldNormal;

	void main() {
		vec3 displaced = position;
		if (uThicknessScene > 0.0) {
			float t = clamp(
				(length(position.xz) - uInnerScene) / (uOuterScene - uInnerScene), 0.0, 1.0);
			float layer = (aLayerIndex + 0.5) / uLayerCount - 0.5; // cell centres, midplane-symmetric
			displaced.y += layer * texture2D(uThickness, vec2(t, 0.5)).r * uThicknessScene;
		}
		vLocalPos = displaced;
		vec4 worldPosition = modelMatrix * vec4(displaced, 1.0);
		vWorldPos = worldPosition.xyz;
		vWorldNormal = normalize(mat3(modelMatrix) * vec3(0.0, 1.0, 0.0));
		gl_Position = projectionMatrix * viewMatrix * worldPosition;
		#include <logdepthbuf_vertex>
	}
`;

/**
 * Phase-angle-aware fragment shader, per BJJ's documentation. Lit side
 * (observer and sun on the same side of the ring plane) blends
 * `backscattered` (low phase, color-tinted) toward `forwardscattered` (high
 * phase, warm-white) with phase angle. Unlit side (opposite sides) uses
 * `unlitside` directly — that profile already *is* the transmitted
 * appearance, no phase blend. The Cassini-derived `color` profile is
 * calibrated against backscatter only, so it tints just that branch; forward
 * and unlit use a fixed warm-white tint.
 *
 * Transparency convention: profile value 1 = empty space, 0 = opaque, so
 * alpha = `1 - profile`.
 *
 * Planet shadow is a per-pixel analytic ray trace against the planet's
 * oblate spheroid, avoiding shadow-map resolution limits (stair-stepping) at
 * any zoom.
 */
const FRAGMENT_SHADER = `
	#include <common>
	#include <logdepthbuf_pars_fragment>

	uniform sampler2D uBackscattered;
	uniform sampler2D uForwardscattered;
	uniform sampler2D uUnlitside;
	uniform sampler2D uTransparency;
	uniform sampler2D uColor;
	uniform float uInnerScene;
	uniform float uOuterScene;
	uniform vec3 uSunDir;
	uniform vec3 uPlanetCenter;
	uniform vec3 uPlanetPoleDir;
	uniform float uPlanetEquatorialScene;
	uniform float uPlanetPolarScene;
	// Solar irradiance factor for the realistic-lighting toggle; 1 otherwise.
	// The BJJ profiles are pre-lit albedo, so scene lights never touch rings.
	uniform float uLightScale;
	// Stored channel value × this = physical brightness/opacity. 1 for
	// Saturn's measured profiles; ~1e-6..0.7 for the synthetic tenuous
	// systems. The overexpose-rings toggle sets it to 1.
	uniform float uIntensityScale;
	// Sun's angular radius as seen from the ring, for penumbra widths.
	uniform float uSunAngularRadius;
	// 1/layerCount: opacity is split across the vertical layer instances so
	// the composited stack reproduces the strip's alpha.
	uniform float uLayerAlphaExp;

	varying vec3 vLocalPos;
	varying vec3 vWorldPos;
	varying vec3 vWorldNormal;

	// Per BJJ: the Cassini-derived color profile only fits backscattered
	// light. Unlit/forward branches get a fixed near-white tint per BJJ.
	const vec3 UNLIT_TINT = vec3(1.0, 0.97075, 0.952);

	// Red bias on the forward-scatter branch, per BJJ's "becoming slightly
	// redder" observation as phase angle climbs.
	const vec3 FORWARD_TINT_BIAS = vec3(1.02, 0.99, 0.97);

	// Ray-march from the fragment toward the sun against the planet's oblate
	// spheroid: warp into the pole-aligned frame so the spheroid becomes a
	// unit sphere, then test the scaled ray. Edge width is the larger of a
	// 1-texel fwidth feather and the physical penumbra.
	float planetShadow() {
		if (uPlanetEquatorialScene <= 0.0) return 1.0;
		vec3 originRel = vWorldPos - uPlanetCenter;
		float originAxial = dot(originRel, uPlanetPoleDir);
		vec3 originRadial = originRel - originAxial * uPlanetPoleDir;
		float dirAxial = dot(uSunDir, uPlanetPoleDir);
		vec3 dirRadial = uSunDir - dirAxial * uPlanetPoleDir;
		float invEq = 1.0 / uPlanetEquatorialScene;
		float invPol = 1.0 / uPlanetPolarScene;
		vec3 oScaled = originRadial * invEq + uPlanetPoleDir * (originAxial * invPol);
		vec3 dScaled = dirRadial * invEq + uPlanetPoleDir * (dirAxial * invPol);
		float a = dot(dScaled, dScaled);
		float b = dot(oScaled, dScaled);
		// b > 0: closest approach is behind the fragment, so no occlusion.
		if (b > 0.0) return 1.0;
		float closest = sqrt(max(dot(oScaled, oScaled) - b * b / a, 0.0));
		// Penumbra grows linearly with distance to the closest-approach point.
		float penumbra = uSunAngularRadius * (-b) / sqrt(a);
		float w = max(fwidth(closest), max(penumbra, 1e-5));
		return smoothstep(1.0 - w, 1.0 + w, closest);
	}

	void main() {
		float radius = length(vLocalPos.xz);
		float t = (radius - uInnerScene) / (uOuterScene - uInnerScene);
		// Outside the annulus: discard so anti-aliased edges don't pick up
		// clamped boundary samples.
		if (t < 0.0 || t > 1.0) discard;

		vec2 uv = vec2(clamp(t, 0.0, 1.0), 0.5);

		// Flip the world normal on the back face so lit-test compares against
		// the outward direction of the face actually being viewed.
		vec3 N = gl_FrontFacing ? vWorldNormal : -vWorldNormal;

		bool lit = dot(uSunDir, N) > 0.0;

		// cosAlpha = cos(phase angle): +1 low phase, -1 high phase.
		vec3 viewDir = normalize(cameraPosition - vWorldPos);
		float cosAlpha = dot(uSunDir, viewDir);

		vec3 finalAlbedo;
		if (lit) {
			// Blend backscatter → forward scatter with phase angle; smoothstep
			// over [-1, 1] centers the transition on edge-on viewing (α = 90°).
			// Both branches share the Cassini color profile (calibrated for
			// backscatter only) plus a small red bias on the forward branch,
			// since dropping color entirely visibly loses the ring's tan/gold
			// hue seen in forward-scattered Cassini imagery.
			vec3 colorTint = texture2D(uColor, uv).rgb;
			vec3 forwardTint = colorTint * FORWARD_TINT_BIAS;
			vec3 back = texture2D(uBackscattered, uv).rgb * colorTint;
			vec3 forward = texture2D(uForwardscattered, uv).rgb * forwardTint;
			float wForward = 1.0 - smoothstep(-1.0, 1.0, cosAlpha);
			finalAlbedo = mix(back, forward, wForward);
		} else {
			// unlitside already is the transmitted-light appearance; no
			// phase-angle blend needed.
			finalAlbedo = texture2D(uUnlitside, uv).rgb * UNLIT_TINT;
		}
		// Transparency convention: 1.0 = empty space, 0.0 = opaque.
		float alpha = clamp((1.0 - texture2D(uTransparency, uv).r) * uIntensityScale, 0.0, 1.0);
		// Split opacity across layer instances so the composited stack
		// reproduces the strip's alpha.
		alpha = 1.0 - pow(1.0 - alpha, uLayerAlphaExp);

		float shadow = planetShadow();

		gl_FragColor = vec4(finalAlbedo * uIntensityScale * shadow * uLightScale, alpha);
		#include <logdepthbuf_fragment>
	}
`;

/**
 * Per-frame uniforms for the ring-shadow ray-march inside the planet's
 * MeshStandardMaterial — see {@link attachRingShadowToPlanet}. One set per
 * material, reused across visits.
 */
export interface PlanetRingShadowUniforms {
	/** Null while no bundle is resident; paired with a zeroed intensity. */
	uRingShadowTransparency: { value: Texture | null };
	uRingShadowInnerScene: { value: number };
	uRingShadowOuterScene: { value: number };
	/** Same physical multiplier as the ring material's `uIntensityScale`, so
	 *  the cast shadow tracks the overexpose-rings toggle. */
	uRingShadowIntensity: { value: number };
	/** Sun's angular radius from the planet, for the shadow's penumbra. */
	uRingShadowSunAngularRadius: { value: number };
	/** World-space unit vector pointing from the planet toward the sun. */
	uRingShadowSunDir: { value: Vector3 };
	/** World-space unit vector along the planet's spin axis (= ring plane normal). */
	uRingShadowPoleDir: { value: Vector3 };
	/** World-space (focus-relative) position of the planet's center. */
	uRingShadowCenter: { value: Vector3 };
	/** Zero the shadow and release the profile texture when the ring bundle
	 *  unloads. Does *not* remove the ray-march from the shader — see
	 *  {@link attachRingShadowToPlanet}. */
	disable: () => void;
}

/** Where {@link attachRingShadowToPlanet} parks a material's uniforms so a
 *  re-attach reuses them. */
interface RingShadowCarrier {
	ringShadow?: PlanetRingShadowUniforms;
}

/**
 * Attach an analytical ring-shadow ray-march to the planet's standard
 * material: trace from the lit fragment toward the sun, intersect the ring
 * plane, and apply Beer–Lambert (slant-corrected) at the sampled radius.
 * Beats a shadow-map cast for transparent profiles — no rasterization
 * resolution, partial transparency falls out of `pow(transparency, 1/sinB)`.
 *
 * The hook and uniforms are installed once and kept for the material's
 * lifetime; `disable` zeroes intensity on system exit and re-entry re-points
 * the same uniforms. Never detach: three.js keys its program cache on
 * `onBeforeCompile.toString()`, so removing and re-adding the hook reuses the
 * cached program *without* re-running `onBeforeCompile` — the surface would
 * keep sampling the dead uniforms from before.
 */
export function attachRingShadowToPlanet(
	planetMaterial: MeshStandardMaterial,
	innerScene: number,
	outerScene: number,
	transparency: Texture,
	intensityScale: number
): PlanetRingShadowUniforms {
	const carrier = planetMaterial.userData as RingShadowCarrier;
	const existing = carrier.ringShadow;
	if (existing) {
		existing.uRingShadowTransparency.value = transparency;
		existing.uRingShadowInnerScene.value = innerScene;
		existing.uRingShadowOuterScene.value = outerScene;
		existing.uRingShadowIntensity.value = intensityScale;
		return existing;
	}

	const prev = planetMaterial.onBeforeCompile;
	const uniforms: PlanetRingShadowUniforms = {
		uRingShadowTransparency: { value: transparency },
		uRingShadowInnerScene: { value: innerScene },
		uRingShadowOuterScene: { value: outerScene },
		uRingShadowIntensity: { value: intensityScale },
		uRingShadowSunAngularRadius: { value: 0 },
		uRingShadowSunDir: { value: new Vector3(1, 0, 0) },
		uRingShadowPoleDir: { value: new Vector3(0, 1, 0) },
		uRingShadowCenter: { value: new Vector3(0, 0, 0) },
		disable: () => {
			// March early-outs on non-positive intensity, so stale radii are
			// harmless. Dropping the texture lets the caller dispose it.
			uniforms.uRingShadowIntensity.value = 0;
			uniforms.uRingShadowTransparency.value = null;
		}
	};
	const hook: MeshStandardMaterial['onBeforeCompile'] = (shader, renderer) => {
		prev?.(shader, renderer);
		Object.assign(shader.uniforms, uniforms);

		// MeshStandardMaterial doesn't ship world position to fragments by
		// default; add our own varying for the surface→ring-plane vector.
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
				uniform float uRingShadowIntensity;
				uniform float uRingShadowSunAngularRadius;
				uniform vec3 uRingShadowSunDir;
				uniform vec3 uRingShadowPoleDir;
				uniform vec3 uRingShadowCenter;
				varying vec3 vRingShadowWorldPos;

				// Transmittance of the ring profile at u; outside the annulus is empty space.
				float ringShadowTrans(float u) {
					if (u < 0.0 || u > 1.0) return 1.0;
					return 1.0 - clamp(
						(1.0 - texture2D(uRingShadowTransparency, vec2(u, 0.5)).r)
							* uRingShadowIntensity,
						0.0, 1.0);
				}

				float ringShadowFactor() {
					if (uRingShadowIntensity <= 0.0) return 1.0;
					// Ray-plane intersect: march from the lit surface along the
					// sun direction; the ring plane passes through the planet's
					// center with normal = pole direction.
					float denom = dot(uRingShadowSunDir, uRingShadowPoleDir);
					if (abs(denom) < 1e-6) return 1.0; // sun grazing the ring plane
					vec3 rel = vRingShadowWorldPos - uRingShadowCenter;
					float t = -dot(rel, uRingShadowPoleDir) / denom;
					if (t < 0.0) return 1.0; // ring is behind the sun from this surface point
					vec3 hit = rel + t * uRingShadowSunDir;
					vec3 hitPerp = hit - dot(hit, uRingShadowPoleDir) * uRingShadowPoleDir;
					float r = length(hitPerp);
					// Reject only when the penumbra-widened band misses the annulus.
					float penumbra = t * uRingShadowSunAngularRadius;
					if (r < uRingShadowInnerScene - penumbra || r > uRingShadowOuterScene + penumbra)
						return 1.0;
					float uSpan = uRingShadowOuterScene - uRingShadowInnerScene;
					float u = (r - uRingShadowInnerScene) / uSpan;
					// 5-tap box over the penumbra: averages the profile the sun
					// disc spans, softening shadow edges physically.
					float pu = penumbra / uSpan;
					float trans = (
						ringShadowTrans(u - pu) + ringShadowTrans(u - 0.5 * pu) +
						ringShadowTrans(u) +
						ringShadowTrans(u + 0.5 * pu) + ringShadowTrans(u + pu)
					) / 5.0;
					// Beer–Lambert, slant-corrected: ray traverses 1/sin(B) times
					// normal optical depth (B = sun elevation above ring plane).
					// Clamp sinB to avoid blow-up near grazing incidence.
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
	planetMaterial.onBeforeCompile = hook;
	tagShaderModifier(planetMaterial, 'ringShadow');
	planetMaterial.needsUpdate = true;
	carrier.ringShadow = uniforms;
	return uniforms;
}

export async function loadRingNode(
	bodyId: string,
	meta: RingMeta,
	maxTextureSize: number
): Promise<RingNode | null> {
	const innerScene = kmToScene(meta.inner_radius_km);
	const outerScene = kmToScene(meta.outer_radius_km);
	const intensityScale = meta.intensity_scale ?? 1;

	let textures: StripTextures;
	try {
		textures = await loadStripTextures(
			versionedUrl(`/v1/rings/${bodyId}/${meta.strip}`, 'rings'),
			meta.strip_rows,
			maxTextureSize
		);
	} catch (err) {
		console.warn(`Failed to load ring strip for ${bodyId}:`, err);
		return null;
	}

	// Vertically thick rings (Jupiter's halo torus) render as a stack of
	// instanced sheets displaced by the thickness profile; flat bundles stay
	// a single sheet.
	const thicknessScene =
		meta.thickness_scale_km && textures.thickness ? kmToScene(meta.thickness_scale_km) : 0;
	const layers = thicknessScene > 0 ? RING_THICKNESS_LAYERS_MAX : 1;

	const material = new ShaderMaterial({
		uniforms: {
			uBackscattered: { value: textures.backscattered },
			uForwardscattered: { value: textures.forwardscattered },
			uUnlitside: { value: textures.unlitside },
			uTransparency: { value: textures.transparency },
			uColor: { value: textures.color },
			// Falls back to any bound texture: never sampled when
			// uThicknessScene is 0, but the sampler must be complete.
			uThickness: { value: textures.thickness ?? textures.transparency },
			uThicknessScene: { value: thicknessScene },
			// Both are re-derived per frame by the LOD; start as a single
			// midplane sheet so the first frame can't flash a partial stack.
			uLayerCount: { value: 1 },
			uLayerAlphaExp: { value: 1 },
			uInnerScene: { value: innerScene },
			uOuterScene: { value: outerScene },
			uSunDir: { value: new Vector3(1, 0, 0) },
			uSunAngularRadius: { value: 0 },
			uPlanetCenter: { value: new Vector3() },
			uPlanetPoleDir: { value: new Vector3(0, 1, 0) },
			uPlanetEquatorialScene: { value: 0 },
			uPlanetPolarScene: { value: 0 },
			uLightScale: { value: 1 },
			uIntensityScale: { value: intensityScale }
		},
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		transparent: true,
		depthWrite: false,
		blending: NormalBlending,
		side: DoubleSide
	});

	// RingGeometry lies in the XY plane with normals +Z; rotate to XZ (normals
	// +Y) so applyOrientation's pole-to-+Y mapping needs no extra fixup.
	//
	// The polygon is inscribed in the annulus: mid-chord, the outer boundary
	// dips inside the true circle by outer·(1 − cos(π/N)), enough to clip
	// rings narrower than that sagitta (Neptune's 15km Adams ring rendered as
	// dotted arcs). Circumscribe the outer edge instead; the shader's t > 1
	// discard trims back to the exact circle. Inner chords are already
	// covered by the t < 0 discard.
	const sagittaPad = 1 / Math.cos(Math.PI / RING_ANGULAR_SEGMENTS);
	const geometry = new RingGeometry(
		innerScene,
		outerScene * sagittaPad,
		RING_ANGULAR_SEGMENTS,
		layers > 1 ? RING_RADIAL_SEGMENTS : 1
	);
	geometry.rotateX(-Math.PI / 2);

	let mesh: Mesh;
	if (layers > 1) {
		geometry.setAttribute(
			'aLayerIndex',
			new InstancedBufferAttribute(
				Float32Array.from({ length: layers }, (_, i) => i),
				1
			)
		);
		const instanced = new InstancedMesh(geometry, material, layers);
		instanced.count = 1; // until the first LOD pass
		mesh = instanced;
	} else {
		mesh = new Mesh(geometry, material);
	}
	mesh.frustumCulled = false; // repositioned by the renderer each frame
	// After the planet and atmosphere shell (renderOrder 2), so foreground
	// rings depth-test in front of the glow instead of it bleeding through.
	mesh.renderOrder = 3;
	mesh.userData.isRingMesh = true;
	// Both shadow directions are per-pixel analytical ray-marches (ring→planet
	// in `attachRingShadowToPlanet`, planet→ring in this material's fragment
	// shader) — neither needs the directional shadow map.

	const planetShadowOnRing: PlanetShadowOnRingUniforms = {
		uPlanetCenter: material.uniforms.uPlanetCenter as { value: Vector3 },
		uPlanetPoleDir: material.uniforms.uPlanetPoleDir as { value: Vector3 },
		uPlanetEquatorialScene: material.uniforms.uPlanetEquatorialScene as { value: number },
		uPlanetPolarScene: material.uniforms.uPlanetPolarScene as { value: number }
	};

	return {
		mesh,
		material,
		layers: mesh instanceof InstancedMesh ? mesh : null,
		thicknessScene,
		transparency: textures.transparency,
		intensityScale,
		innerScene,
		outerScene,
		planetShadow: null,
		planetShadowOnRing
	};
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
		'uColor',
		'uThickness'
	]) {
		const tex = uniforms[key]?.value as Texture | undefined;
		tex?.dispose();
	}
	(ring.mesh.material as Material).dispose();
}
