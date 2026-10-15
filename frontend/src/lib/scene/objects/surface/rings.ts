/**
 * Ring annuli drawn from 1-D radial profiles. Each body ships one N×5 strip,
 * `v1/rings/{id}/strip.webp`: color, backscattered, forwardscattered,
 * unlitside and transparency (1 − opacity). After decode each row becomes its
 * own texture, so that mipmaps cannot mix the rows. The three scatter rows
 * share one texture as its R, G and B channels. Stored values × the bundle's
 * `intensity_scale` are physical; the overexpose-rings toggle skips the scale.
 *
 * The mesh is a sibling of the body in the scene, so the triaxial scale of the
 * planet does not distort the rings.
 *
 * Refs: Björn Jónsson https://bjj.mmedia.is/data/s_rings/index.html (channel
 * meanings, color calibrated against backscatter only, warm-white unlit hint);
 * John Spencer https://www2.boulder.swri.edu/~spencer/ringrender.html (radial-
 * profile recipe + Beer–Lambert ring-shadow formulation used by {@link attachRingShadowToPlanet}).
 */

import {
	CanvasTexture,
	Color,
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
	Vector2,
	Vector3
} from 'three';
import { kmToScene } from '$lib/math/units';
import { versionedUrl } from '$lib/fetch/data-base';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';
import { MAX_ANISOTROPY } from './anisotropy';
import {
	FORWARD_TINT_BIAS,
	makeRingLight,
	PLANET_LIGHT_AZIMUTHS,
	PARTICLE_PHASE_EXPONENT,
	PLANET_LIGHT_RADII,
	PROFILE_MU,
	type RingLight,
	ringProfile,
	type RingshineUniforms,
	UNLIT_TINT
} from './ring-light';

export type RingChannel =
	| 'color'
	| 'backscattered'
	| 'forwardscattered'
	| 'unlitside'
	| 'transparency';

/** The five channels every bundle has, plus the optional thickness profile. */
type StripRows = Record<RingChannel, number> & { thickness?: number };
interface StripTextures {
	color: Texture;
	/** Backscattered, forwardscattered and unlitside as R, G and B. */
	scatter: Texture;
	transparency: Texture;
	thickness?: Texture;
}

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
	/** The light of the planet on this bundle, and of this bundle on the planet. */
	light: RingLight;
	/** Ringshine on the planet's material. Only on the bundle that casts the
	 *  shadow, and only where its light can show. */
	ringshine: RingshineUniforms | null;
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
 * skips it unless the overexpose toggle is on. Its light scales with the
 * same intensity. A quarter of an 8-bit code value against white is generous
 * headroom: culled bundles (Jupiter's τ~5e-6 rings, Saturn's outer tenuous
 * system) sit orders of magnitude under it; the faintest survivor (Neptune's,
 * 0.0031) clears it 3×.
 */
export const RING_MIN_VISIBLE_ALPHA = 0.25 / 255;

/**
 * Fetch the body's N×5 strip and make its rows into 2-tall CanvasTextures.
 * Canvases, not TextureLoader: an Android Chrome bug zeroes 1-px-tall VP8L
 * WebPs, and a canvas can scale the strip under GL MAX_TEXTURE_SIZE (Saturn's
 * strip is 13177 px; Adreno 5xx stops at 4096). The doubled row lets mipmap
 * generation succeed. Also returns the strip's pixels at native width.
 */
async function loadStripTextures(
	url: string,
	rows: StripRows,
	maxTextureSize: number
): Promise<{ textures: StripTextures; pixels: Uint8ClampedArray; width: number }> {
	const response = await fetch(url);
	if (!response.ok) {
		throw new Error(`Failed to load ${url}: ${response.status} ${response.statusText}`);
	}
	const blob = await response.blob();
	const bitmap = await createImageBitmap(blob);
	const width = bitmap.width;
	const targetWidth = Math.min(width, maxTextureSize);
	if (targetWidth < width) {
		console.info(
			`Ring strip ${url}: downscaling ${width}px → ${targetWidth}px to fit GL MAX_TEXTURE_SIZE.`
		);
	}
	const pixels = readStripPixels(bitmap, url, maxTextureSize);
	bitmap.close();
	const line = (row: number) => boxFilterRow(pixels, width, row, targetWidth);
	const texture = (data: ImageData, srgb = false): Texture => {
		const canvas = document.createElement('canvas');
		canvas.width = targetWidth;
		canvas.height = 2;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error(`Failed to acquire 2D context for ring strip ${url}`);
		ctx.putImageData(data, 0, 0);
		ctx.putImageData(data, 0, 1);
		const tex = new CanvasTexture(canvas);
		if (srgb) tex.colorSpace = SRGBColorSpace;
		// Seen at a low angle, a pixel covers many more texels along the radius than across it.
		tex.minFilter = LinearMipmapLinearFilter;
		tex.magFilter = LinearFilter;
		tex.generateMipmaps = true;
		tex.anisotropy = MAX_ANISOTROPY;
		tex.needsUpdate = true;
		return tex;
	};
	// One fetch gives all three scatter profiles.
	const scatter = line(rows.backscattered);
	const forward = line(rows.forwardscattered);
	const unlit = line(rows.unlitside);
	for (let d = 0; d < scatter.data.length; d += 4) {
		scatter.data[d + 1] = forward.data[d];
		scatter.data[d + 2] = unlit.data[d];
	}
	const textures: StripTextures = {
		// Color is a perceptual albedo tint (sRGB); scalar profiles are linear.
		color: texture(line(rows.color), true),
		scatter: texture(scatter),
		transparency: texture(line(rows.transparency))
	};
	if (rows.thickness !== undefined) textures.thickness = texture(line(rows.thickness));
	return { textures, pixels, width };
}

/**
 * The whole strip read back at native width, RGBA. Copied in chunks no wider
 * than the GL limit, and always 1:1 — a scaling copy is what corrupts these
 * rows (see {@link boxFilterRow}).
 */
function readStripPixels(
	bitmap: ImageBitmap,
	url: string,
	maxTextureSize: number
): Uint8ClampedArray {
	const out = new Uint8ClampedArray(bitmap.width * bitmap.height * 4);
	const canvas = document.createElement('canvas');
	canvas.width = Math.min(bitmap.width, maxTextureSize);
	canvas.height = bitmap.height;
	const ctx = canvas.getContext('2d', { willReadFrequently: true });
	if (!ctx) throw new Error(`Failed to acquire 2D context for ring strip ${url}`);
	for (let x = 0; x < bitmap.width; x += canvas.width) {
		const w = Math.min(canvas.width, bitmap.width - x);
		ctx.clearRect(0, 0, w, bitmap.height);
		ctx.drawImage(bitmap, x, 0, w, bitmap.height, 0, 0, w, bitmap.height);
		const chunk = ctx.getImageData(0, 0, w, bitmap.height).data;
		for (let y = 0; y < bitmap.height; y++) {
			out.set(chunk.subarray(y * w * 4, (y + 1) * w * 4), (y * bitmap.width + x) * 4);
		}
	}
	return out;
}

/**
 * One strip row box-filtered down to `targetWidth`, as a 1-tall ImageData.
 * Identity when no downscale is due.
 *
 * The arithmetic is ours because the browsers' is wrong on a strip: asked to
 * scale down, Chrome mipmaps the source image, and a mip level of an N×6 strip
 * averages the channel rows into each other — a 1-px-tall source rect does not
 * fence it off. On a phone (GL limit 4096 against Saturn's 13177 samples) that
 * blended every profile toward their common mean, and `unlitside`, the one row
 * anti-correlated with its neighbours, lost its structure completely.
 */
function boxFilterRow(
	pixels: Uint8ClampedArray,
	srcWidth: number,
	row: number,
	targetWidth: number
): ImageData {
	const out = new ImageData(targetWidth, 1);
	for (let x = 0; x < targetWidth; x++) {
		const from = Math.floor((x * srcWidth) / targetWidth);
		const to = Math.max(from + 1, Math.floor(((x + 1) * srcWidth) / targetWidth));
		let r = 0;
		let g = 0;
		let b = 0;
		for (let i = from; i < to; i++) {
			const s = (row * srcWidth + i) * 4;
			r += pixels[s];
			g += pixels[s + 1];
			b += pixels[s + 2];
		}
		const n = to - from;
		const d = x * 4;
		out.data[d] = Math.round(r / n);
		out.data[d + 1] = Math.round(g / n);
		out.data[d + 2] = Math.round(b / n);
		out.data[d + 3] = 255;
	}
	return out;
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
 * Ring fragment shader, after Björn Jónsson's notes. A face reflects the light
 * from its own side of the ring plane: `backscattered` at low phase under the
 * phase function of the particles (`particlePhase` of `ring-light.ts`),
 * `forwardscattered` at high phase, with the Cassini `color` on both. A face
 * passes the light from the other side as `unlitside`, with a fixed warm
 * white tint.
 *
 * The output is premultiplied: the ring adds its light and hides the
 * background by its opacity along the line of sight. `backscattered` is the
 * light of the ring as seen. Jónsson stretched each profile to a peak of 1,
 * and only the backscatter has a level checked against measurements (see
 * `ring-light.ts`). The other two keep the level they had under the opacity.
 * The light changes with the elevation of the Sun and of the eye
 * (`reflectionGain` and `unlitGain` of `ring-light.ts`), so the rings go dark
 * when the Sun is in their plane. A gain over 1 lifts only the backscatter:
 * on the other two profiles it would lift a level that no measurement sets.
 *
 * Two lights reach the rings. The Sun is one. An exact ray test against the
 * planet's spheroid gives the planet's shadow on the rings. The planet is the
 * other, from the texture of `ring-light.ts`.
 *
 * A transparency of 1 is empty space and 0 is opaque.
 */
const FRAGMENT_SHADER = `
	#include <common>
	#include <logdepthbuf_pars_fragment>

	uniform sampler2D uScatter;
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
	// Light of the planet on the +Y and the -Y face over the Sun's, per unit of the
	// planet's albedo, and the mean sine of its incidence on each, by the cosine
	// of the azimuth from the Sun (x) and radius (y).
	uniform sampler2D uPlanetLight;
	// Lambert albedo of the planet, linear RGB.
	uniform vec3 uPlanetAlbedo;
	// Unit direction of the Sun in the local XZ plane.
	uniform vec2 uSunAzimuth;

	varying vec3 vLocalPos;
	varying vec3 vWorldPos;
	varying vec3 vWorldNormal;

	const vec3 UNLIT_TINT = vec3(${UNLIT_TINT.join(', ')});
	const vec3 FORWARD_TINT_BIAS = vec3(${FORWARD_TINT_BIAS.join(', ')});
	const float PROFILE_MU = ${PROFILE_MU};

	float oneMinusExp(float x) {
		return x < 1e-3 ? x * (1.0 - 0.5 * x) : 1.0 - exp(-x);
	}

	float reflectionGain(float mu0, float mu, float tau) {
		float a = max(mu0, 1e-4);
		float b = max(mu, 1e-4);
		return mu0 / (a + b) * oneMinusExp(tau * (1.0 / a + 1.0 / b))
			/ (0.5 * oneMinusExp(2.0 * tau / PROFILE_MU));
	}

	float unlitGain(float mu0, float mu) {
		return 2.0 * mu0 / max(mu0 + mu, 1e-4);
	}

	// Weight of forward scatter: 0 at phase 0, 1 at phase 180 deg, 0.5 edge-on.
	float forwardWeight(float cosPhase) {
		return 1.0 - smoothstep(-1.0, 1.0, cosPhase);
	}

	float particlePhase(float cosPhase) {
		return pow(1.0 - acos(clamp(cosPhase, -1.0, 1.0)) / PI, ${PARTICLE_PHASE_EXPONENT});
	}

	// The lit face at a phase and a gain: the backscatter profile under the
	// phase function of the particles, blended into the forward-scatter profile.
	vec3 litLight(vec3 back, vec3 forward, float cosPhase, float gain) {
		return mix(
			back * particlePhase(cosPhase) * gain,
			forward * min(gain, 1.0),
			forwardWeight(cosPhase)
		);
	}

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

		float sunMu = dot(uSunDir, N);
		bool lit = sunMu > 0.0;
		float mu0 = abs(sunMu);

		vec3 viewDir = normalize(cameraPosition - vWorldPos);
		float mu = abs(dot(viewDir, N));
		// Transparency convention: 1.0 = empty space, 0.0 = opaque.
		float opacity = clamp((1.0 - texture2D(uTransparency, uv).r) * uIntensityScale, 0.0, 1.0);
		float tau = max(-log(max(1.0 - opacity, 1e-6)), 1e-6);

		vec3 colorTint = texture2D(uColor, uv).rgb;
		vec3 scatter = texture2D(uScatter, uv).rgb;
		vec3 back = scatter.r * colorTint;
		vec3 forward = scatter.g * opacity * colorTint * FORWARD_TINT_BIAS;
		vec3 unlit = scatter.b * opacity * UNLIT_TINT;
		vec3 sunLit = lit
			? litLight(back, forward, dot(uSunDir, viewDir), reflectionGain(mu0, mu, tau))
			: unlit * min(unlitGain(mu0, mu), 1.0);

		// The light is the same at plus and minus an azimuth, so the texture holds its cosine.
		float azimuth = 0.5 - 0.5 * dot(vLocalPos.xz, uSunAzimuth) / radius;
		const vec2 NODES = vec2(${PLANET_LIGHT_AZIMUTHS}.0, ${PLANET_LIGHT_RADII}.0);
		vec4 planet = texture2D(uPlanetLight, (vec2(azimuth, t) * (NODES - 1.0) + 0.5) / NODES);
		vec2 near = gl_FrontFacing ? planet.xz : planet.yw;
		vec2 far = gl_FrontFacing ? planet.yw : planet.xz;
		float planetPhase = dot(normalize(uPlanetCenter - vWorldPos), viewDir);
		vec3 planetLit = uPlanetAlbedo * (
			near.x * litLight(back, forward, planetPhase, reflectionGain(near.y, mu, tau))
			+ far.x * min(unlitGain(far.y, mu), 1.0) * unlit);

		// The slant path hides more of the background.
		float alpha = oneMinusExp(tau / max(mu, 0.02));
		// Split the opacity across the sheets of the stack so that it composites
		// to the layer's. Each sheet adds its share of the light.
		float layerAlpha = 1.0 - pow(1.0 - alpha, uLayerAlphaExp);
		float share = alpha > 1e-4 ? layerAlpha / alpha : uLayerAlphaExp;

		float shadow = planetShadow();

		gl_FragColor = vec4(
			(sunLit * shadow + planetLit) * uIntensityScale * uLightScale * share,
			layerAlpha
		);
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
 * Analytical ring-shadow march at a world-space point: intersect the ring
 * plane along the sun direction, box-average the transparency profile over the
 * sun disc's penumbra, apply Beer–Lambert with slant correction. Beats a
 * shadow-map cast for transparent profiles — no rasterization resolution,
 * partial transparency falls out of `pow(transparency, 1/sinB)`.
 *
 * Shared by the planet surface and the atmosphere shell, so the shadow
 * continues up through the air above the ground it darkens. Self-contained
 * (uniforms included, no varying) — the shell carries no world-position
 * varying of its own.
 */
export const RING_SHADOW_GLSL = `
	uniform sampler2D uRingShadowTransparency;
	uniform float uRingShadowInnerScene;
	uniform float uRingShadowOuterScene; // 0 = no rings
	uniform float uRingShadowIntensity;
	uniform float uRingShadowSunAngularRadius;
	uniform vec3 uRingShadowSunDir;
	uniform vec3 uRingShadowPoleDir;
	uniform vec3 uRingShadowCenter;

	// Physical (× intensity) transmittance of the ring profile at u; outside the
	// annulus is empty space.
	float ringShadowTrans(float u) {
		if (u < 0.0 || u > 1.0) return 1.0;
		return 1.0 - clamp(
			(1.0 - texture2D(uRingShadowTransparency, vec2(u, 0.5)).r)
				* uRingShadowIntensity,
			0.0, 1.0);
	}

	float ringShadowAt(vec3 worldPos) {
		// Outer radius 0 is a body with no rings at all; intensity 0 a bundle too
		// faint to darken anything, and how the shadow is switched off on exit.
		if (uRingShadowOuterScene <= 0.0 || uRingShadowIntensity <= 0.0) return 1.0;
		// Ray-plane intersect: march from the lit point along the sun direction;
		// the ring plane passes through the planet's center with normal = pole.
		float denom = dot(uRingShadowSunDir, uRingShadowPoleDir);
		if (abs(denom) < 1e-6) return 1.0; // sun grazing the ring plane
		vec3 rel = worldPos - uRingShadowCenter;
		float t = -dot(rel, uRingShadowPoleDir) / denom;
		if (t < 0.0) return 1.0; // ring is behind the sun from this point
		vec3 hit = rel + t * uRingShadowSunDir;
		vec3 hitPerp = hit - dot(hit, uRingShadowPoleDir) * uRingShadowPoleDir;
		float r = length(hitPerp);
		// Reject only when the penumbra-widened band misses the annulus.
		float penumbra = t * uRingShadowSunAngularRadius;
		if (r < uRingShadowInnerScene - penumbra || r > uRingShadowOuterScene + penumbra)
			return 1.0;
		float uSpan = uRingShadowOuterScene - uRingShadowInnerScene;
		float u = (r - uRingShadowInnerScene) / uSpan;
		// 5-tap box over the penumbra: averages the profile the sun disc spans,
		// softening shadow edges physically.
		float pu = penumbra / uSpan;
		float trans = (
			ringShadowTrans(u - pu) + ringShadowTrans(u - 0.5 * pu) +
			ringShadowTrans(u) +
			ringShadowTrans(u + 0.5 * pu) + ringShadowTrans(u + pu)
		) / 5.0;
		// Beer–Lambert, slant-corrected: the ray traverses 1/sin(B) times normal
		// optical depth (B = sun elevation above the ring plane). sinB is clamped
		// to avoid blow-up near grazing incidence.
		return pow(max(trans, 1e-4), 1.0 / max(abs(denom), 0.02));
	}
`;

/**
 * Attach {@link RING_SHADOW_GLSL} to the planet's standard material, marching
 * from each lit fragment.
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
				varying vec3 vRingShadowWorldPos;
				// The sky light of sun-transmittance.ts reads ringShadow.
				#define PLANET_RING_SHADOW
				${RING_SHADOW_GLSL}`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				float ringShadow = ringShadowAt(vRingShadowWorldPos);
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
	let light: RingLight;
	try {
		const strip = await loadStripTextures(
			versionedUrl(`/v1/rings/${bodyId}/${meta.strip}`, 'rings'),
			meta.strip_rows,
			maxTextureSize
		);
		textures = strip.textures;
		light = makeRingLight(
			ringProfile(
				strip.pixels,
				strip.width,
				meta.strip_rows,
				innerScene,
				outerScene,
				intensityScale
			)
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
			uScatter: { value: textures.scatter },
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
			uIntensityScale: { value: intensityScale },
			uPlanetLight: { value: light.planetLight },
			uPlanetAlbedo: { value: new Color(0, 0, 0) },
			uSunAzimuth: { value: new Vector2(1, 0) }
		},
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		transparent: true,
		depthWrite: false,
		blending: NormalBlending,
		premultipliedAlpha: true,
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
		planetShadowOnRing,
		light,
		ringshine: null
	};
}

/** Dispose all GPU resources owned by a ring node. */
export function disposeRingNode(ring: RingNode): void {
	ring.mesh.geometry.dispose();
	const uniforms = ring.material.uniforms as Record<string, { value: Texture | unknown }>;
	for (const key of ['uScatter', 'uTransparency', 'uColor', 'uThickness', 'uPlanetLight']) {
		const tex = uniforms[key]?.value as Texture | undefined;
		tex?.dispose();
	}
	(ring.mesh.material as Material).dispose();
}
