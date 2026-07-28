/**
 * Ring annulus disc, albedo sampled from 1-D radial profiles shipped per body
 * as a single N×5 `v1/rings/{id}/strip.webp` (one row per channel: color,
 * backscattered, forwardscattered, unlitside, transparency=1−opacity). The
 * strip is split into separate 1-row textures after decode so per-channel
 * trilinear/anisotropic filtering can't bleed rows into each other.
 *
 * Channel values are stored normalised; × `intensity_scale` recovers physical
 * brightness/opacity (1 for Saturn's measured data, ~1e-6..0.7 for the
 * synthetic tenuous systems). The overexpose-rings layer toggle renders the
 * stored values unscaled instead, lifting each system to its full dynamic
 * range.
 *
 * Mesh is a scene-level sibling of the body (not a child) so the planet's
 * triaxial-flattening scale doesn't distort the circular profile. The renderer
 * tracks position/orientation and writes per-frame `uSunDir`.
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

export type RingChannel =
	| 'color'
	| 'backscattered'
	| 'forwardscattered'
	| 'unlitside'
	| 'transparency';

/** The five channels every bundle has, plus the optional thickness profile. */
type StripRows = Record<RingChannel, number> & { thickness?: number };
type StripTextures = Record<RingChannel, Texture> & { thickness?: Texture };

/** One work behind a bundle. Bundles mix sources — Saturn's measured strips
 *  are Björn Jónsson's photometry with NSSDCA vertical extents — so each
 *  states what it contributed rather than the bundle claiming one origin. */
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
	/** The sheet stack for a vertically thick bundle, so the renderer can vary
	 *  `count` with apparent thickness; null when the bundle renders flat. */
	layers: InstancedMesh | null;
	/** Full vertical extent of the stack in scene units (0 = flat). */
	thicknessScene: number;
	/** Transparency profile texture — shared with the planet's ray-march
	 *  ring-shadow path so we don't load it twice. */
	transparency: Texture;
	/** Physical multiplier for the stored channel values. The renderer writes
	 *  it (or 1 when the overexpose-rings toggle is on) into the material and
	 *  ring-shadow uniforms each frame. */
	intensityScale: number;
	/** Inner ring radius in scene units. Used by the planet's ring-shadow
	 *  ray-march to clip intersections to the actual annulus. */
	innerScene: number;
	/** Outer ring radius in scene units. Used by the ray-march clipping. */
	outerScene: number;
	/** Live per-frame uniforms on the planet material's ring-shadow path —
	 *  null until {@link attachRingShadowToPlanet} runs. The renderer mutates
	 *  the contained Vector3 values in place each frame. */
	planetShadow: PlanetRingShadowUniforms | null;
	/** Live per-frame uniforms on the ring material's planet-shadow
	 *  ray-march. The radii are set once by the caller of `loadRingNode`
	 *  (which knows the planet's oblate-spheroid extent); the renderer
	 *  mutates the Vector3 values in place each frame. */
	planetShadowOnRing: PlanetShadowOnRingUniforms;
}

/**
 * Per-frame uniforms driving the planet-shadow ray-march inside the ring's
 * own ShaderMaterial. The ring fragment shader traces from each fragment
 * toward the sun and tests against the planet's oblate spheroid, so the
 * shadow stays crisp per-pixel instead of relying on the directional shadow
 * map (which stair-steps the planet terminator across the rings when the
 * camera is zoomed close).
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
// from how far the stack spreads *on screen*, which inverts the cost the
// helpful way: face-on the sheets project onto each other and one suffices,
// and the counts that approach this bound only happen edge-on, where the ring
// covers a thin band. Sheets are a discrete stand-in for a volume, so they
// separate into visible lines once they land more than a pixel apart — this
// is the ceiling on how fine that approximation can get.
export const RING_THICKNESS_LAYERS_MAX = 48;

/**
 * Peak opacity below which a bundle cannot change any pixel, so the renderer
 * skips drawing it unless the overexpose toggle is on.
 *
 * A ring affects the frame two ways. What it *adds* goes as intensity² (the
 * albedo and the alpha both carry the scale), but what it *hides* of the
 * background goes as intensity alone — so occlusion is what sets this floor.
 * A quarter of an 8-bit code value against a fully white backdrop is already
 * generous: the bundles this culls (Jupiter's τ~5e-6 rings, Saturn's outer
 * tenuous system) sit two to three orders of magnitude under it, while the
 * faintest bundle that survives — Neptune's, at 0.0031 — clears it 3×.
 */
export const RING_MIN_VISIBLE_ALPHA = 0.25 / 255;

/**
 * Fetch the body's N×5 strip and split each channel row into its own 2-tall
 * CanvasTexture. Split-after-decode (not one multi-row texture): mipmap
 * levels of a row-per-channel texture would average adjacent rows, bleeding
 * channels into each other under trilinear minification.
 *
 * Per-channel canvases (not TextureLoader): (a) works around an Android-Chrome
 * bug that gives all-zero samples for 1-px-tall VP8L WebPs, (b) lets us
 * downscale past GL MAX_TEXTURE_SIZE (Saturn's profile is ~13177 px; Adreno
 * 5xx caps at 4096 and silently uploads incomplete textures). The doubled row
 * lets mipmap generation succeed; the shader samples at v = 0.5.
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
		// Color is a perceptual albedo tint (sRGB); the scalar profiles are
		// linear (packed uint8 luminance, not gamma-encoded).
		if (channel === 'color') tex.colorSpace = SRGBColorSpace;
		// 1×N radial profile: at distance many radial samples fall in one
		// pixel and a single nearest/linear tap aliases into sparkle, while at
		// grazing angles the U-gradient across the screen is far higher than
		// the V-gradient (V is constant) — exactly the case anisotropic
		// filtering is designed for. Trilinear + max anisotropy addresses
		// both. Three.js silently clamps anisotropy to whatever the GPU
		// advertises, so 16 is safe without poking the renderer.
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

	// Sheet index within the vertical stack, and how many of them are being
	// drawn this frame. Deriving the offset from the live count (rather than
	// baking it into the attribute) keeps the sheets evenly spread across the
	// full extent at every LOD level. A plain (non-instanced) mesh leaves the
	// attribute unbound, which GL defines as 0, so with uLayerCount 1 it lands
	// on the midplane.
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
			// Cell centres: 1 sheet sits at the midplane, N spread symmetrically.
			float layer = (aLayerIndex + 0.5) / uLayerCount - 0.5;
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
 *
 * Planet shadow: from each fragment we trace toward the sun and test
 * intersection with the planet's oblate spheroid. Per-pixel analytic test —
 * no shadow-map resolution to worry about, so the terminator stays crisp
 * at any zoom and there's no blocky stair-stepping on the ring strips.
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
	// light. For the unlit / forward branches we tint by a near-white
	// constant — slightly warm for the diffuse unlit transmission, since
	// that's what BJJ recommends.
	const vec3 UNLIT_TINT = vec3(1.0, 0.97075, 0.952);

	// Slight red bias on top of the color profile for the forward-scatter
	// branch, matching BJJ's "becoming slightly redder" observation as
	// phase angle climbs.
	const vec3 FORWARD_TINT_BIAS = vec3(1.02, 0.99, 0.97);

	// Saturn's shadow on the rings: ray-march from the fragment toward the
	// sun against the planet's oblate spheroid. Working in the pole-aligned
	// frame, apply the affine warp (eq⁻¹, pol⁻¹, eq⁻¹) so the spheroid
	// becomes a unit sphere, then test the scaled ray against it. Edge width
	// is the larger of a 1-texel fwidth feather (screen stability) and the
	// physical penumbra: the sun's angular radius times the distance from
	// the fragment to the occluding limb.
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
		// b > 0 → closest approach is behind the fragment along the sun ray,
		// so the planet can't occlude the sun from here.
		if (b > 0.0) return 1.0;
		float closest = sqrt(max(dot(oScaled, oScaled) - b * b / a, 0.0));
		// Distance to the closest-approach point in unit-sphere units: the
		// penumbra grows linearly with it (umbra shrinks correspondingly).
		float penumbra = uSunAngularRadius * (-b) / sqrt(a);
		float w = max(fwidth(closest), max(penumbra, 1e-5));
		return smoothstep(1.0 - w, 1.0 + w, closest);
	}

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
		float alpha = clamp((1.0 - texture2D(uTransparency, uv).r) * uIntensityScale, 0.0, 1.0);
		// Split opacity across the vertical layer instances so the composited
		// stack reproduces the strip's alpha (coincident layers included).
		alpha = 1.0 - pow(1.0 - alpha, uLayerAlphaExp);

		// Planet shadow modulates both branches: the lit-side reflection
		// from blocked direct sunlight, and the unlit-side transmission
		// (sunlight filters through the rings only where the sun is unblocked).
		float shadow = planetShadow();

		gl_FragColor = vec4(finalAlbedo * uIntensityScale * shadow * uLightScale, alpha);
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
	/** Restore the planet material's `onBeforeCompile` to its pre-attachment
	 *  state and force a recompile, dropping the ring-shadow ray-march from the
	 *  fragment shader. Idempotent and safe to call after a subsequent attach
	 *  has replaced the hook (the new hook stays). */
	detach: () => void;
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
	transparency: Texture,
	intensityScale: number
): PlanetRingShadowUniforms {
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
		detach: () => {
			// Only restore if our hook is still the active one — a subsequent
			// reattach replaced it and owns the slot now.
			if (planetMaterial.onBeforeCompile === hook) {
				planetMaterial.onBeforeCompile = prev;
				planetMaterial.needsUpdate = true;
			}
		}
	};
	const hook: MeshStandardMaterial['onBeforeCompile'] = (shader, renderer) => {
		prev?.(shader, renderer);
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
				uniform float uRingShadowIntensity;
				uniform float uRingShadowSunAngularRadius;
				uniform vec3 uRingShadowSunDir;
				uniform vec3 uRingShadowPoleDir;
				uniform vec3 uRingShadowCenter;
				varying vec3 vRingShadowWorldPos;

				// Physical (× intensity) transmittance of the ring profile at u;
				// outside the annulus is empty space.
				float ringShadowTrans(float u) {
					if (u < 0.0 || u > 1.0) return 1.0;
					return 1.0 - clamp(
						(1.0 - texture2D(uRingShadowTransparency, vec2(u, 0.5)).r)
							* uRingShadowIntensity,
						0.0, 1.0);
				}

				float ringShadowFactor() {
					// Zeroed by the renderer for a bundle too faint to darken
					// anything, so the march below is skipped outright.
					if (uRingShadowIntensity <= 0.0) return 1.0;
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
					// Penumbra half-width at the ring plane: the sun's angular
					// radius times the surface→ring distance. Reject only when
					// even the penumbra-widened band misses the annulus.
					float penumbra = t * uRingShadowSunAngularRadius;
					if (r < uRingShadowInnerScene - penumbra || r > uRingShadowOuterScene + penumbra)
						return 1.0;
					float uSpan = uRingShadowOuterScene - uRingShadowInnerScene;
					float u = (r - uRingShadowInnerScene) / uSpan;
					// 5-tap box over the penumbra: averages the profile the sun
					// disc actually spans, softening shadow edges physically.
					float pu = penumbra / uSpan;
					float trans = (
						ringShadowTrans(u - pu) + ringShadowTrans(u - 0.5 * pu) +
						ringShadowTrans(u) +
						ringShadowTrans(u + 0.5 * pu) + ringShadowTrans(u + pu)
					) / 5.0;
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
	planetMaterial.onBeforeCompile = hook;
	planetMaterial.needsUpdate = true;
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
	// instanced sheets, each displaced by the per-radius thickness profile;
	// the fragment shader splits opacity across the stack. Flat bundles stay
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

	// RingGeometry lies in the XY plane with normals +Z; rotate to XZ plane
	// (normals +Y) so applyOrientation's pole-to-+Y mapping puts the ring on
	// the equator with no extra fixup.
	//
	// The polygon is inscribed in the annulus: mid-chord, the outer boundary
	// dips inside the true circle by outer·(1 − cos(π/N)) — enough to
	// periodically clip rings narrower than that sagitta (Neptune's 15 km
	// Adams ring rendered as dotted arcs). Circumscribe the outer edge
	// instead; the fragment shader's t > 1 discard trims back to the exact
	// circle. The inner chords already dip inward, covered by the t < 0
	// discard. Radial segments only matter when the vertex shader samples
	// the thickness profile.
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
	// After the opaque planet AND the atmosphere shell (renderOrder 2): the shell
	// writes depth from outside, so foreground rings depth-test in front of the
	// glow and the dense inner ring composites over it instead of the glow
	// bleeding through. Ties with trails/points (also 3) resolve by distance.
	mesh.renderOrder = 3;
	mesh.userData.isRingMesh = true;
	// Both shadow directions are handled by per-pixel analytical ray-marches —
	// ring → planet inside the planet's own MeshStandardMaterial (see
	// `attachRingShadowToPlanet`), planet → ring inside this material's
	// fragment shader. Neither needs the directional shadow map.

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
