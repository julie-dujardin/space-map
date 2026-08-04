/**
 * Per-body atmospheric-scattering shell. Sphere drawn just outside the planet;
 * the fragment shader ray-marches single-scattered sunlight (Rayleigh + Mie +
 * one absorber band) and composites premultiplied over the scene: in-scatter
 * adds, and alpha = 1 − view-path transmittance attenuates what lies behind, so
 * optically thick decks (Titan, Venus) read opaque down to the ground while
 * thin columns only tint. Coordinates run in planet-radius-normalised units to
 * keep float32 well-conditioned — Earth's 8 km scale height in scene units is
 * mush.
 *
 * Recipe follows Maxime Heckel's "On rendering realistic-looking skies, sunsets,
 * and planets" (which distills Bruneton/Hillaire); brute-force per-fragment
 * march is fine because the shell only ever covers the planet's screen footprint.
 * Aerosols scatter and absorb per RGB channel, with phase functions tabulated
 * by the data pipeline from Mie theory per body — that spectral asymmetry, not
 * the Rayleigh column, is what makes Mars butterscotch, Titan orange and Venus
 * sulfur-pale.
 *
 * Per-body parameters arrive via `$lib/fetch/atmospheres` (exported
 * `atmospheres.json`, derived from cited constants in
 * data/src/space_map_data/constants/atmosphere/); this module only defines the
 * parameter shape and the shader that consumes it.
 *
 * Oblate bodies: the mesh stays a sphere sized to the equatorial radius (it is
 * only a coverage primitive), and the shader ray-marches in a "squashed" space
 * where the ellipsoid is a unit sphere (`uSpinAxis`/`uStretch`). Constant-
 * density surfaces become similar ellipsoids, compressing polar scale heights
 * by up to 1/uStretch — invisible next to a proper geopotential model.
 *
 * The material flips FrontSide/BackSide as the camera crosses the shell
 * boundary ({@link updateAtmosphereShaders}) so the sky still renders from
 * inside. Fragments over terrain are then depth-rejected, so in-atmosphere
 * views get the sky above the horizon but no aerial perspective on the ground.
 */

import {
	CustomBlending,
	DataTexture,
	FloatType,
	FrontSide,
	type Material,
	Mesh,
	OneFactor,
	OneMinusSrcAlphaFactor,
	RGBAFormat,
	ShaderMaterial,
	SphereGeometry,
	type Texture,
	Vector2,
	Vector3,
	Vector4
} from 'three';
import {
	atmosphereConfigKey,
	currentAtmosphereConfig,
	type AtmosphereQualityConfig
} from './atmosphere-quality';
import { ECLIPSE_FACTOR_GLSL, getEclipseSceneUniforms, MAX_OCCLUDERS } from './eclipse-shadow';
import type { PlanetRingShadowUniforms } from './rings';

/** Rendered terrain can dip this far below the analytic ellipsoid (Gale crater
 *  sits at −4.5 km); the shell keeps marching (and glowing) down to it.
 *
 * Only applied with the camera inside the shell, where a camera below the datum
 * would otherwise have its horizon rays blocked at t≈0. From outside, sinking
 * the floor makes every disc ray integrate a slab of surface-density air under
 * the ground — 6 km against Earth's 1.2 km aerosol scale height is 6× the real
 * column, and it defeats the baked-texture compensation (which can only cancel
 * one vertical column out of the inflated total). */
export const TERRAIN_DIP_KM = 6;

/** Outside view: after the opaque planet and clouds (renderOrder 1) so the
 *  glow composites over the surface, but before the rings (renderOrder 3) —
 *  the shell writes depth from outside, so foreground rings occlude the glow. */
export const ATMOSPHERE_RENDER_ORDER = 2;
/** Inside view: the sky is the frame's backdrop and depth test is off, so it
 *  must draw after every scene-level transparent — rings, other bodies'
 *  shells, point clouds, trails (all ≤ 3) — and composite them away behind
 *  its 1−transmittance alpha. Debug overlays (999+) stay on top. */
export const ATMOSPHERE_INSIDE_RENDER_ORDER = 10;

// Placeholder for the ring-shadow sampler while a body has no rings — the
// shader guards on uRingShadowOuterScene, but the sampler must still be bound.
let white: DataTexture | null = null;
function whiteTexture(): DataTexture {
	if (!white) {
		white = new DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
		white.needsUpdate = true;
	}
	return white;
}

/** Pack a layered Mie density profile into an N×1 RGBA float texture (R used). */
function mieProfileTexture(profile: readonly number[]): DataTexture {
	const data = new Float32Array(profile.length * 4);
	for (let i = 0; i < profile.length; i++) {
		data[i * 4] = profile[i];
		data[i * 4 + 3] = 1;
	}
	const tex = new DataTexture(data, profile.length, 1, RGBAFormat, FloatType);
	tex.needsUpdate = true;
	return tex;
}

/** Rebind the profile LUT when a param swap changes it (body switch in the
 *  debug tuner; seasonal derivations keep the same array ref → no-op). */
function syncProfileTexture(
	material: ShaderMaterial,
	prev: readonly number[] | undefined,
	next: readonly number[] | undefined
): void {
	if (prev === next) return;
	const u = material.uniforms;
	if (u.uMieProfileTex.value !== white) (u.uMieProfileTex.value as Texture).dispose();
	u.uMieProfileTex.value = next ? mieProfileTexture(next) : whiteTexture();
	u.uMieProfileOn.value = next ? 1 : 0;
	u.uMieProfileN.value = next?.length ?? 1;
}

/** Pack a 3×128 phase table (R,G,B blocks of 128) into a 128×1 RGBA float
 *  texture — see the uMiePhaseTex shader comment for why not a uniform array. */
function miePhaseTexture(table: readonly number[]): DataTexture {
	const data = new Float32Array(128 * 4);
	for (let i = 0; i < 128; i++) {
		data[i * 4] = table[i];
		data[i * 4 + 1] = table[i + 128];
		data[i * 4 + 2] = table[i + 256];
		data[i * 4 + 3] = 1;
	}
	const tex = new DataTexture(data, 128, 1, RGBAFormat, FloatType);
	tex.needsUpdate = true;
	return tex;
}

/**
 * Physical parameters of a body's atmosphere, in human-readable units (per-km
 * coefficients, kilometre scale heights/altitudes). {@link buildAtmosphereNode}
 * converts them to the planet-radius-normalised form the shader works in.
 */
export interface AtmosphereParams {
	/** Top of the modelled atmosphere above the surface, km. The shell sphere
	 *  sits at the planet radius plus this. */
	topAltitudeKm: number;
	/** Rayleigh scattering coefficient at sea level, per km, for (R, G, B). */
	rayleighScatterPerKm: [number, number, number];
	/** Rayleigh density e-folding height, km. */
	rayleighScaleHeightKm: number;
	/** Mie scattering coefficient at sea level, per km, for (R, G, B) — real
	 *  aerosols (dust, tholins, H₂SO₄ droplets) are big enough to colour the
	 *  scattered light, unlike the grey-Mie textbook shortcut. */
	mieScatterPerKm: [number, number, number];
	/** Mie *absorption* at sea level, per km, for (R, G, B). Extinction =
	 *  scattering + this. */
	mieAbsorptionPerKm: [number, number, number];
	/** Mie density e-folding height, km. */
	mieScaleHeightKm: number;
	/** Tabulated per-channel Mie phase for the body's aerosol, 3×128 floats
	 *  (R, G, B blocks sampled at θ = π·(i/127)²). */
	miePhase: readonly number[];
	/** Absorption coefficient of the body's absorber band (ozone on Earth,
	 *  tholins on Titan…), per km, for (R, G, B). Pure absorption, no
	 *  scattering — it carves colour out of the transmitted light. */
	absorptionPerKm: [number, number, number];
	/** Centre altitude of the (linear tent) absorber band, km. */
	absorptionCenterKm: number;
	/** Half-width of the absorber tent, km — density falls linearly to 0 at
	 *  `absorptionCenterKm ± absorptionWidthKm`. */
	absorptionWidthKm: number;
	/** 0..1: fraction of a vertical atmospheric column assumed already baked
	 *  into the surface texture (satellite mosaics and cloud-deck photos are
	 *  shot through the air above them). Surface-hitting rays render only the
	 *  slant excess over that column, so the disc keeps the texture's own tint
	 *  and the shell contributes where the texture can't — limb and terminator.
	 *  0 for bodies whose texture is NOT the photographed appearance: Titan's
	 *  map is the haze-hidden surface, Venus's the cloud deck itself — there the
	 *  shell must stay opaque over the disc. */
	bakedCompensation: number;
	/** Gain on the isotropic multiple-scattering ambient term. Single scatter
	 *  alone goes black wherever the direct sun path is extinguished — for
	 *  optically thick atmospheres (Titan, Venus) that wrongly darkens the
	 *  poles and the terminator, so thick/bright atmospheres want ≥ 1. */
	multiScatterGain: number;
	/** Linear gain on the in-scattered radiance ahead of the shader's 1−exp
	 *  rolloff (and the composer's ACES). ~22 ≈ 1-AU solar irradiance in the
	 *  bench calibration this port follows; per-body deviations are taste. */
	sunIntensity: number;
	/** Sun colour the scattering integral is multiplied by. */
	sunColor: [number, number, number];
	/** Apply the inverse-square solar irradiance even with realistic lighting
	 *  off. For far-out wisps tuned at the physical `sunIntensity`, flat 1-AU
	 *  sunlight blows the faint backlit haze into an opaque glowing shell. */
	realisticSunAlways?: boolean;
	/** (n − 1) at the reference level for (R, G, B) — drives the in-atmosphere
	 *  refraction lift of the Sun's visuals near the horizon. */
	refractivity?: [number, number, number];
	/** Bond-ish albedo of what the shell sits above (surface or cloud deck) —
	 *  boosts the multiple-scatter ambient near the ground. */
	groundAlbedo?: number;
	/** Layered Mie density LUT: densities at equal altitude steps over
	 *  [0, topAltitudeKm], 0 at the top, column-normalised to match the
	 *  exponential's β·H. Sampled by the ATMO_LAYERED shader path
	 *  (high/ultra); other tiers and profile-less bodies keep the single
	 *  exponential. */
	mieProfile?: readonly number[];
	/** Mars-style seasonal cycle (interpolated per frame from L_s). Lives on
	 *  the base params; derived seasonal params drop it. */
	seasonal?: AtmosphereSeasonalTable;
}

/** Piecewise-linear seasonal factors on a wrap-around solar-longitude grid. */
export interface AtmosphereSeasonalTable {
	lsDeg: readonly number[];
	dustTauFactor: readonly number[];
	dustScaleHeightKm: readonly number[];
	pressureFactor: readonly number[];
}

/** Scene-side handle for a body's atmosphere shell. */
export interface AtmosphereNode {
	mesh: Mesh;
	material: ShaderMaterial;
	/** Source params, kept so {@link syncAtmosphereEllipsoid} and the debug
	 *  tuner ({@link applyAtmosphereParams}) can re-derive the radius-normalised
	 *  uniforms. The per-frame uniform update reads `sunIntensity` from here. */
	params: AtmosphereParams;
	/** Radius the shell's SphereGeometry was built with, scene units. */
	geometryRadiusScene: number;
	/** Reference radius (equatorial once SPICE radii land), km. */
	planetRadiusKm: number;
	/** {@link atmosphereConfigKey} of the quality config the program was
	 *  compiled with — {@link applyAtmosphereQuality} rebuilds on mismatch. */
	qualityKey: string;
}

const VERTEX_SHADER = `
	#include <common>
	#include <logdepthbuf_pars_vertex>

	varying vec3 vWorldPos;
	varying vec3 vPlanetCenter;

	void main() {
		vec4 worldPos = modelMatrix * vec4(position, 1.0);
		vWorldPos = worldPos.xyz;
		// The shell mesh is positioned at the planet's centre with no rotation
		// or scale, so the model origin in world space *is* the planet centre.
		// Constant across all vertices, so it survives interpolation exactly.
		vPlanetCenter = (modelMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
		gl_Position = projectionMatrix * viewMatrix * worldPos;
		#include <logdepthbuf_vertex>
	}
`;

const FRAGMENT_SHADER = `
	#include <common>
	#include <logdepthbuf_pars_fragment>

	uniform vec3 uSunDir;            // unit, planet → Sun
	uniform vec3 uSpinAxis;          // unit, world — body pole
	uniform float uStretch;          // equatorial radius / polar radius, >= 1
	uniform float uPlanetRadiusScene; // equatorial, scene units
	uniform float uAtmosphereRatio;  // (planet radius + atmosphere top) / planet radius
	uniform float uSurfaceBlockR;    // march floor, ~6 km below the datum, in planet radii
	uniform vec3 uRayleighScatter;   // β_R, per planet radius, (R,G,B)
	uniform float uRayleighScaleHeight;
	uniform vec3 uMieScatter;        // β_M scattering, per planet radius, (R,G,B)
	uniform vec3 uMieExtinction;     // β_M extinction, per planet radius, (R,G,B)
	uniform float uMieScaleHeight;
	// Layered Mie density LUT over [0, shell top] (Venus decks, Titan's
	// detached haze), normalised to 1 at the reference level. Only sampled on
	// ATMO_LAYERED tiers and only when uMieProfileOn is set.
	uniform sampler2D uMieProfileTex;
	uniform float uMieProfileOn;
	uniform float uMieProfileN;      // texel count of uMieProfileTex
	// Ground-bounce gain on the multiple-scatter ambient: sunlight reflected
	// by the surface/deck under the shell and rescattered by the air above it.
	uniform float uGroundAlbedo;
	// Tabulated Mie phase, 128x1 RGBA float texel row (RGB used). A texture, not
	// a uniform array: 384 floats would eat 384 uniform vectors and blow past
	// mobile GPUs' fragment-uniform limit (~224), which kills the program link.
	uniform sampler2D uMiePhaseTex;
	uniform vec3 uAbsorption;        // absorber band β, per planet radius, (R,G,B)
	uniform float uAbsorptionCenter;
	uniform float uAbsorptionWidth;
	uniform float uMultiScatter;
	uniform float uBakedComp;        // 0..1, vertical column already in the texture
	uniform float uSunIntensity;
	uniform vec3 uSunColor;
	// Ring shadow on the air column — same analytic ray-plane march as
	// attachRingShadowToPlanet, shared value-refs once rings load.
	uniform sampler2D uRingShadowTransparency;
	uniform float uRingShadowInnerScene;
	uniform float uRingShadowOuterScene; // 0 = no rings
	uniform float uRingShadowIntensity;
	uniform float uRingShadowSunAngularRadius;
	uniform vec3 uRingShadowSunDir;
	uniform vec3 uRingShadowPoleDir;
	uniform vec3 uRingShadowCenter;
	// Opaque-scene depth, sampled only when the camera is inside the shell (the
	// far-hemisphere pass runs with depthTest off so the sky renders, which
	// would otherwise paint over foreground terrain). uUseDepth gates it; the
	// texture holds reversed-Z or logarithmic depth depending on the renderer's
	// mode (uReversedDepth), decoded to an eye-forward distance below.
	uniform sampler2D uSceneDepth;
	uniform float uUseDepth;
	uniform float uReversedDepth;
	uniform vec3 uCamForward;   // unit, world — camera view axis
	uniform float uCameraNear;
	uniform float uCameraFar;
	uniform vec2 uResolution;

	varying vec3 vWorldPos;
	varying vec3 vPlanetCenter;

	${ECLIPSE_FACTOR_GLSL}

	// PRIMARY_STEPS / LIGHT_STEPS and the ATMO_ECLIPSE / ATMO_RING_SHADOW /
	// ATMO_INSIDE feature flags come from material.defines — quality tiers
	// recompile the program rather than branch per fragment.
	#define ISO_PHASE 0.0795775   // 1 / 4π — isotropic phase for the ambient term
	#define MS_DIFFUSION 0.3      // slant-τ weight in the diffusive ambient falloff

	// Rendered terrain (DEM craters, below-datum landing sites) dips under the
	// analytic ellipsoid; the march floor sits ~6 km below the datum (set per
	// body, see setRadiusUniforms) so air keeps glowing in front of that
	// terrain instead of leaving a dark band under the horizon. Density below
	// the datum clamps to the surface value, so the overshoot on rays that hit
	// normal ground stays a bounded sliver.

	// Squashed space: stretch the spin-axis component so the oblate ellipsoid
	// becomes a sphere of equatorial radius. Linear, so rays stay straight;
	// squashed path lengths are converted back to world lengths by the caller.
	vec3 squash(vec3 v) {
		return v + (uStretch - 1.0) * dot(v, uSpinAxis) * uSpinAxis;
	}

	// Inverse of squash — squashed offsets back to world offsets.
	vec3 unsquash(vec3 v) {
		return v + (1.0 / uStretch - 1.0) * dot(v, uSpinAxis) * uSpinAxis;
	}

	// Tabulated aerosol phase function. Texels sit at theta = pi*(i/127)^2, so
	// the lookup warps back with a square root — most of the 128 samples sit on
	// the sharp forward peak. Two nearest taps + manual lerp: linear filtering
	// of float textures is an optional extension on mobile.
	vec3 miePhase(float mu) {
		float theta = acos(clamp(mu, -1.0, 1.0));
		float w = sqrt(theta / PI) * 127.0;
		float i0 = clamp(floor(w), 0.0, 126.0);
		vec3 a = texture2D(uMiePhaseTex, vec2((i0 + 0.5) / 128.0, 0.5)).rgb;
		vec3 b = texture2D(uMiePhaseTex, vec2((i0 + 1.5) / 128.0, 0.5)).rgb;
		return mix(a, b, w - i0);
	}

	// Ray (origin ro, unit dir rd) vs sphere centred at the origin, radius r.
	// Returns vec2(tNear, tFar). On a miss it returns (+huge, -huge) so that
	// "is the hit ahead of us and before tEnd?" tests fail cleanly; a negative
	// component is a real intersection behind ro.
	vec2 raySphere(vec3 ro, vec3 rd, float r) {
		float b = dot(ro, rd);
		float c = dot(ro, ro) - r * r;
		float d = b * b - c;
		if (d < 0.0) return vec2(1e9, -1e9);
		float s = sqrt(d);
		return vec2(-b - s, -b + s);
	}

	// Local (Rayleigh, Mie, absorber) densities at altitude h, in planet radii
	// above the surface. The absorber is a linear tent peaking at uAbsorptionCenter.
	// Below-datum altitudes clamp to surface density: rays grazing under the
	// datum (real below-datum terrain, sun paths past the terminator) keep
	// integrating smoothly growing optical depth — path length, not a density
	// blow-up, provides the soft horizon/twilight falloff.
	// Each exponential is shifted down by its value at the shell top so density
	// reaches exactly 0 at the boundary: the raw truncated profile leaves a
	// finite residue there (Mars dust: ~3e-4 of surface density) that the
	// forward-scatter lobe near the sun amplifies into glow with a hard edge
	// at the sphere's silhouette.
	vec3 densities(float h) {
		float hc = max(h, 0.0);
		float top = uAtmosphereRatio - 1.0;
		float mie;
		#ifdef ATMO_LAYERED
		if (uMieProfileOn > 0.5) {
			// Piecewise profile LUT; two nearest taps + manual lerp, same
			// float-filtering caveat as the phase table. Ends at exactly 0, so
			// no shell-top shift is needed on this path.
			float w = clamp(hc / top, 0.0, 1.0) * (uMieProfileN - 1.0);
			float i0 = min(floor(w), uMieProfileN - 2.0);
			float a = texture2D(uMieProfileTex, vec2((i0 + 0.5) / uMieProfileN, 0.5)).r;
			float b = texture2D(uMieProfileTex, vec2((i0 + 1.5) / uMieProfileN, 0.5)).r;
			mie = mix(a, b, w - i0);
		} else
		#endif
		{
			mie = max(exp(-hc / uMieScaleHeight) - exp(-top / uMieScaleHeight), 0.0);
		}
		return vec3(
			max(exp(-hc / uRayleighScaleHeight) - exp(-top / uRayleighScaleHeight), 0.0),
			mie,
			max(0.0, 1.0 - abs(hc - uAbsorptionCenter) / uAbsorptionWidth)
		);
	}

	// Physical (× intensity) ring transmittance at u; outside the annulus is
	// empty space.
	float ringShadowTrans(float u) {
		if (u < 0.0 || u > 1.0) return 1.0;
		return 1.0 - clamp(
			(1.0 - texture2D(uRingShadowTransparency, vec2(u, 0.5)).r)
				* uRingShadowIntensity,
			0.0, 1.0);
	}

	// Ring transmittance toward the sun from a world-space point: intersect the
	// ring plane, box-average the transparency profile over the sun disc's
	// penumbra, Beer–Lambert with slant correction. Mirrors
	// attachRingShadowToPlanet so the shadow the rings cast on the surface
	// continues up through the air above it.
	float ringShadowAt(vec3 worldPos) {
		// Second test: zeroed for a bundle too faint to darken anything.
		if (uRingShadowOuterScene <= 0.0 || uRingShadowIntensity <= 0.0) return 1.0;
		float denom = dot(uRingShadowSunDir, uRingShadowPoleDir);
		if (abs(denom) < 1e-6) return 1.0;
		vec3 rel = worldPos - uRingShadowCenter;
		float t = -dot(rel, uRingShadowPoleDir) / denom;
		if (t < 0.0) return 1.0;
		vec3 hit = rel + t * uRingShadowSunDir;
		vec3 hitPerp = hit - dot(hit, uRingShadowPoleDir) * uRingShadowPoleDir;
		float r = length(hitPerp);
		float penumbra = t * uRingShadowSunAngularRadius;
		if (r < uRingShadowInnerScene - penumbra || r > uRingShadowOuterScene + penumbra)
			return 1.0;
		float uSpan = uRingShadowOuterScene - uRingShadowInnerScene;
		float u = (r - uRingShadowInnerScene) / uSpan;
		float pu = penumbra / uSpan;
		float trans = (
			ringShadowTrans(u - pu) + ringShadowTrans(u - 0.5 * pu) +
			ringShadowTrans(u) +
			ringShadowTrans(u + 0.5 * pu) + ringShadowTrans(u + pu)
		) / 5.0;
		return pow(max(trans, 1e-4), 1.0 / max(abs(denom), 0.02));
	}

	// Optical depth (Rayleigh, Mie, absorber), in planet-radius units, from p
	// toward the Sun out to the top of the atmosphere; sd/sunLen are the
	// squashed sun direction and its pre-squash length. Rays dipping below the
	// density clamp band are fully blocked (no refraction modelled); grazing
	// rays get the marched, clamped optical depth, which is what softens and
	// colours the terminator.
	vec3 sunOpticalDepth(vec3 p, vec3 sd, float sunLen) {
		// Block only on a real forward hit (a miss returns +1e9/-1e9, so also
		// require .y > 0) — sun more than ~10° below the horizon ends twilight.
		vec2 block = raySphere(p, sd, uSurfaceBlockR - 0.015);
		if (block.x > 0.0 && block.y > 0.0) return vec3(1e6);
		float far = raySphere(p, sd, uAtmosphereRatio).y;
		float dt = far / float(LIGHT_STEPS);
		vec3 od = vec3(0.0);
		for (int i = 0; i < LIGHT_STEPS; i++) {
			vec3 s = p + sd * (dt * (float(i) + 0.5));
			od += densities(length(s) - 1.0) * dt;
		}
		return od / sunLen; // squashed → world path length
	}

	void main() {
		vec3 roWorld = (cameraPosition - vPlanetCenter) / uPlanetRadiusScene;
		vec3 rdWorld = normalize(vWorldPos - cameraPosition);
		// March in squashed space; rdSq is non-unit, so squashed path lengths
		// convert to world lengths via 1/dLen when accumulating optical depth.
		vec3 ro = squash(roWorld);
		vec3 rdSq = squash(rdWorld);
		float dLen = length(rdSq);
		vec3 rd = rdSq / dLen;

		vec2 atmoHit = raySphere(ro, rd, uAtmosphereRatio);
		if (atmoHit.y < 0.0) discard;             // atmosphere entirely behind us

		vec2 planetHit = raySphere(ro, rd, uSurfaceBlockR);
		float tStart = max(atmoHit.x, 0.0);       // covers the camera-inside case too
		float tEnd = atmoHit.y;
		float hitSurface = 0.0;                   // baked-texture compensation applies
		if (planetHit.x > tStart && planetHit.x < tEnd) {
			tEnd = planetHit.x;                   // march stops at the surface
			hitSurface = 1.0;
		}
		// Stop at real opaque terrain (decoded from the depth prepass), which
		// the analytic-surface march is blind to. Clamp tEnd *before* the step
		// size is set so the samples spread smoothly up to the surface — a
		// mid-march cutoff quantises the haze depth into bands down a slope. Only
		// active inside the shell, where depthTest is off (updateAtmosphereShaders);
		// forward distance decodes as t = w·dLen / (R·(rd·camFwd)).
		#ifdef ATMO_INSIDE
		if (uUseDepth > 0.5) {
			// Single-tap, so the clamp sits exactly at the opaque depth: averaging
			// neighbours pulls in the far sky value at the silhouette and bleeds
			// haze onto the ground there. The hard per-pixel edge can shimmer as
			// terrain drifts sub-pixel (single-sample depth vs the MSAA'd colour
			// edge), but that's less objectionable than glow leaking through solid
			// ground.
			float d = texture2D(uSceneDepth, gl_FragCoord.xy / uResolution).x;
			float fwd = dot(rdWorld, uCamForward);
			// "No geometry" is the cleared value: 0 under reversed-Z, 1 under log.
			bool hitGeom = uReversedDepth > 0.5 ? d > 0.0 : d < 1.0;
			if (hitGeom && fwd > 1e-4) {
				float terrainW = uReversedDepth > 0.5
					? uCameraNear * uCameraFar / (d * (uCameraFar - uCameraNear) + uCameraNear)
					: exp2(d * log2(uCameraFar + 1.0)) - 1.0;
				float tTerrain = terrainW * dLen / (uPlanetRadiusScene * fwd);
				if (tTerrain < tEnd) {
					tEnd = tTerrain;
					hitSurface = 1.0;
				}
			}
		}
		#endif
		if (tEnd <= tStart) discard;

		float mu = dot(rdWorld, uSunDir);         // phase angle is physical — world space
		float phaseR = (3.0 / (16.0 * PI)) * (1.0 + mu * mu);
		vec3 phaseM = miePhase(mu);

		vec3 sunSq = squash(uSunDir);
		float sunLen = length(sunSq);
		vec3 sd = sunSq / sunLen;

		float dt = (tEnd - tStart) / float(PRIMARY_STEPS);
		float dtWorld = dt / dLen;                // squashed step → world path length
		// Midpoint sampling, except on layered profiles: their sharp features
		// (Titan's ~30 km detached layer vs ~100 km steps) alias into
		// concentric bands, so the sample point is jittered per fragment
		// (interleaved gradient noise) — trades the bands for fine grain.
		float samplePos = 0.5;
		#ifdef ATMO_LAYERED
		if (uMieProfileOn > 0.5) {
			samplePos = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
		}
		#endif
		vec3 viewT = vec3(1.0);                   // running transmittance, camera → sample
		vec3 viewOD = vec3(0.0);                  // total marched optical depth (for alpha)
		vec3 accumR = vec3(0.0);                  // Σ transmittance · ρ_R · dt, per channel
		vec3 accumM = vec3(0.0);
		vec3 accumMS = vec3(0.0);                 // isotropic multiple-scatter ambient

		for (int i = 0; i < PRIMARY_STEPS; i++) {
			vec3 p = ro + rd * (tStart + dt * (float(i) + samplePos));
			vec3 dens = densities(length(p) - 1.0); // (ρ_R, ρ_M, ρ_A)
			vec3 dStep = dens * dtWorld;
			viewOD += dStep;

			// Energy-conserving step: (1 − e^−τ)/τ is the step's average
			// transmittance, so one optically thick step still emits its
			// saturated share instead of self-extinguishing to black — dense
			// limbs (Venus) stay lit however coarse the sampling.
			vec3 tauStep = uRayleighScatter * dStep.x +
				uMieExtinction * dStep.y +
				uAbsorption * dStep.z;
			vec3 stepT = exp(-tauStep);
			vec3 wStep = (vec3(1.0) - stepT) / max(tauStep, vec3(1e-5));

			vec3 sunOD = sunOpticalDepth(p, sd, sunLen);
			vec3 sunT = exp(-(
				uRayleighScatter * sunOD.x +
				uMieExtinction * sunOD.y +
				uAbsorption * sunOD.z
			));
			// Sun-disc occlusion by other bodies (a moon during a solar
			// eclipse) and by the ring system both dim the light reaching this
			// sample — the shadows sweep through the atmosphere just like
			// across the surface.
			float sunVis = 1.0;
			#if defined(ATMO_ECLIPSE) || defined(ATMO_RING_SHADOW)
			vec3 pWorld = vPlanetCenter + unsquash(p) * uPlanetRadiusScene;
			#endif
			#ifdef ATMO_ECLIPSE
			sunVis *= eclipseFactorAt(pWorld, vPlanetCenter, uSunDir);
			#endif
			#ifdef ATMO_RING_SHADOW
			sunVis *= ringShadowAt(pWorld);
			#endif

			vec3 direct = viewT * wStep * sunT * sunVis;
			accumR += direct * dStep.x;
			accumM += direct * dStep.y;

			// Ambient multiple scattering: single scatter goes black wherever
			// the direct sun path is extinguished (thick-atmosphere poles, past
			// the terminator), but multiply-scattered light survives — through a
			// conservative slab of slant depth τ it decays like 1/(1+τ) (two-
			// stream), not exponentially. Reusing the marched sun path gives a
			// twilight that fades algebraically through the terminator and dies
			// with the ~10° below-horizon block; absorbers stay exponential.
			vec3 msSunT = exp(-uAbsorption * sunOD.z) /
				(1.0 + MS_DIFFUSION * (uRayleighScatter * sunOD.x + uMieScatter * sunOD.y));
			vec3 odVert = uRayleighScatter * (uRayleighScaleHeight * dens.x) +
				uMieExtinction * (uMieScaleHeight * dens.y);
			// Ground bounce: the surface/deck reflects uGroundAlbedo of the
			// sunlight into the air above it, weighted by proximity to the
			// ground via the local (normalised) density; msSunT already carries
			// the day/night gating.
			float bounce = 1.0 + uGroundAlbedo * 0.5 * (dens.x + dens.y);
			accumMS += viewT * wStep * exp(-odVert) * msSunT *
				(uRayleighScatter * dStep.x + uMieScatter * dStep.y) *
				(uMultiScatter * sunVis * bounce);

			viewT *= stepT;
		}

		vec3 color = uSunIntensity * uSunColor * (
			accumR * uRayleighScatter * phaseR +
			accumM * uMieScatter * phaseM +
			accumMS * ISO_PHASE
		);

		// Baked-texture compensation: a surface-hitting ray ends on a texture that
		// was itself photographed through one vertical air column, so the shell
		// may only add the slant excess over that column — thin-limit share
		// (τ_view − τ_vert)/τ_view of the in-scatter, τ_view − τ_vert of the
		// occlusion. Disc-centre rays cancel to ≈ the bare texture; at the limb
		// τ_view ≫ τ_vert and the full glow survives. τ_vert is analytic:
		// β·H per exponential species, tent area β·W for the absorber.
		vec3 tauView = uRayleighScatter * viewOD.x +
			uMieExtinction * viewOD.y +
			uAbsorption * viewOD.z;
		vec3 tauVert = uRayleighScatter * uRayleighScaleHeight +
			uMieExtinction * uMieScaleHeight +
			uAbsorption * uAbsorptionWidth;
		vec3 tauBaked = min(tauVert, tauView) * (uBakedComp * hitSurface);
		color *= 1.0 - tauBaked / max(tauView, vec3(1e-6));

		// Soft HDR rolloff: keeps thick-deck in-scatter below the bloom
		// threshold and inside ACES's comfortable range while staying ≈ linear
		// for faint glows.
		color = 1.0 - exp(-max(color, 0.0));

		// What the ray marched through also occludes what lies behind it —
		// surface texture for disk rays, stars/bodies past the limb — minus the
		// baked share the texture already absorbed. Scalar alpha
		// (luminance-weighted) approximates the per-channel transmittance.
		vec3 occT = exp(-(tauView - tauBaked));
		float alpha = 1.0 - dot(occT, vec3(0.2126, 0.7152, 0.0722));

		// Fade out as the planet shrinks below ~half a pixel — beyond that the
		// limb-width ray-sphere math is just float32 noise, and the glow is
		// invisible anyway. length(roWorld) is the camera distance in planet radii.
		float fade = 1.0 - smoothstep(2000.0, 6000.0, length(roWorld));
		color *= fade;
		alpha *= fade;

		// Contributes nothing → keep the depth buffer untouched too (the
		// material writes depth from outside so point clouds/trails composite
		// by depth); without this, invisible outer-annulus fragments would
		// still cull dots behind them.
		if (max(alpha, max(color.r, max(color.g, color.b))) < 0.004) discard;

		gl_FragColor = vec4(color, alpha);
		#include <logdepthbuf_fragment>
	}
`;

/**
 * Set every radius-normalised uniform for an (equatorial) reference radius.
 * "Per planet radius": a per-km coefficient is multiplied by the radius in km
 * so the shader integrates optical depth over distances measured in radii.
 */
function setRadiusUniforms(
	material: ShaderMaterial,
	params: AtmosphereParams,
	planetRadiusScene: number,
	planetRadiusKm: number
): void {
	const toNorm = (perKm: number) => perKm * planetRadiusKm;
	const r = params.rayleighScatterPerKm;
	const ms = params.mieScatterPerKm;
	const ma = params.mieAbsorptionPerKm;
	const ab = params.absorptionPerKm;
	const u = material.uniforms;
	u.uPlanetRadiusScene.value = planetRadiusScene;
	u.uAtmosphereRatio.value = 1 + params.topAltitudeKm / planetRadiusKm;
	// Outside default; updateAtmosphereShaders sinks it once the camera is in.
	u.uSurfaceBlockR.value = 1;
	(u.uRayleighScatter.value as Vector3).set(toNorm(r[0]), toNorm(r[1]), toNorm(r[2]));
	u.uRayleighScaleHeight.value = params.rayleighScaleHeightKm / planetRadiusKm;
	(u.uMieScatter.value as Vector3).set(toNorm(ms[0]), toNorm(ms[1]), toNorm(ms[2]));
	(u.uMieExtinction.value as Vector3).set(
		toNorm(ms[0] + ma[0]),
		toNorm(ms[1] + ma[1]),
		toNorm(ms[2] + ma[2])
	);
	u.uMieScaleHeight.value = params.mieScaleHeightKm / planetRadiusKm;
	(u.uAbsorption.value as Vector3).set(toNorm(ab[0]), toNorm(ab[1]), toNorm(ab[2]));
	u.uAbsorptionCenter.value = params.absorptionCenterKm / planetRadiusKm;
	u.uAbsorptionWidth.value = params.absorptionWidthKm / planetRadiusKm;
}

/**
 * Build the atmosphere shell for a body. `planetRadiusScene` / `planetRadiusKm`
 * are the body's surface radius in scene units and kilometres respectively; the
 * shell sphere is `planetRadiusScene · (1 + topAltitudeKm / planetRadiusKm)`.
 *
 * The mesh carries no position of its own — the renderer keeps it at the
 * planet's focus-relative centre via the body's `extraObjects` list, and pushes
 * the body→Sun direction onto `material.uniforms.uSunDir` each frame. Bodies
 * start spherical; `syncAtmosphereEllipsoid` reshapes the shell when SPICE
 * triaxial radii are applied to the planet mesh.
 */
export function buildAtmosphereNode(
	params: AtmosphereParams,
	planetRadiusScene: number,
	planetRadiusKm: number
): AtmosphereNode {
	const c = params.sunColor;
	const eclipse = getEclipseSceneUniforms();
	const quality = currentAtmosphereConfig();
	const material = new ShaderMaterial({
		defines: qualityDefines(quality),
		uniforms: {
			// Shared scene ref (mutated in place by updateEclipseUniforms).
			uSunAngularRadius: eclipse.uSunAngularRadius,
			// Own occluder set, unlike surface materials which share the scene
			// list: the shell pays the eclipse loop per march sample, so
			// updateAtmosphereShaders culls it down to occluders that could
			// actually shadow this shell (almost always none).
			uOccluderCount: { value: 0 },
			uOccluders: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) },
			uSunDir: { value: new Vector3(1, 0, 0) },
			uSpinAxis: { value: new Vector3(0, 1, 0) },
			uStretch: { value: 1 },
			uPlanetRadiusScene: { value: 0 },
			uAtmosphereRatio: { value: 0 },
			uSurfaceBlockR: { value: 1 },
			// Inert until attachRingShadowToAtmosphere swaps in the live refs.
			uRingShadowTransparency: { value: whiteTexture() },
			uRingShadowInnerScene: { value: 0 },
			uRingShadowOuterScene: { value: 0 },
			uRingShadowIntensity: { value: 1 },
			uRingShadowSunAngularRadius: { value: 0 },
			uRingShadowSunDir: { value: new Vector3(1, 0, 0) },
			uRingShadowPoleDir: { value: new Vector3(0, 1, 0) },
			uRingShadowCenter: { value: new Vector3() },
			uRayleighScatter: { value: new Vector3() },
			uRayleighScaleHeight: { value: 0 },
			uMieScatter: { value: new Vector3() },
			uMieExtinction: { value: new Vector3() },
			uMieScaleHeight: { value: 0 },
			uMiePhaseTex: { value: miePhaseTexture(params.miePhase) },
			uMieProfileTex: {
				value: params.mieProfile ? mieProfileTexture(params.mieProfile) : whiteTexture()
			},
			uMieProfileOn: { value: params.mieProfile ? 1 : 0 },
			uMieProfileN: { value: params.mieProfile?.length ?? 1 },
			// Quality-gated per frame by updateAtmosphereShaders (0 = off).
			uGroundAlbedo: { value: params.groundAlbedo ?? 0 },
			uAbsorption: { value: new Vector3() },
			uAbsorptionCenter: { value: 0 },
			uAbsorptionWidth: { value: 0 },
			uMultiScatter: { value: params.multiScatterGain },
			uBakedComp: { value: params.bakedCompensation },
			uSunIntensity: { value: params.sunIntensity },
			uSunColor: { value: new Vector3(c[0], c[1], c[2]) },
			// Depth-clamp inputs, bound by the renderer only while inside the
			// shell (see updateAtmosphereShaders / the depth prepass).
			uSceneDepth: { value: whiteTexture() },
			uUseDepth: { value: 0 },
			uReversedDepth: { value: 0 },
			uCamForward: { value: new Vector3(0, 0, -1) },
			uCameraNear: { value: 0.001 },
			uCameraFar: { value: 1 },
			uResolution: { value: new Vector2(1, 1) }
		},
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		transparent: true,
		// From outside, the shell writes depth so later transparents (point-
		// cloud dots, trails at renderOrder 3) depth-sort against it: dots
		// behind the limb glow hide, dots in front draw over. Nothing orbits
		// inside the thin shell, so the single depth is a faithful proxy.
		// updateAtmosphereShaders clears it when the camera is inside — the
		// far hemisphere must not cull the night sky's dots.
		depthWrite: true,
		// Premultiplied compositing: src + dst·(1−α). In-scatter radiance is
		// already transmittance-weighted, so it must not be multiplied by α again.
		blending: CustomBlending,
		blendSrc: OneFactor,
		blendDst: OneMinusSrcAlphaFactor,
		side: FrontSide
	});
	setRadiusUniforms(material, params, planetRadiusScene, planetRadiusKm);

	const geometryRadiusScene = planetRadiusScene * (1 + params.topAltitudeKm / planetRadiusKm);
	const geometry = new SphereGeometry(geometryRadiusScene, 64, 64);
	const mesh = new Mesh(geometry, material);
	mesh.renderOrder = ATMOSPHERE_RENDER_ORDER;
	mesh.userData.isAtmosphereMesh = true;
	return {
		mesh,
		material,
		params,
		geometryRadiusScene,
		planetRadiusKm,
		qualityKey: atmosphereConfigKey(quality)
	};
}

function qualityDefines(config: AtmosphereQualityConfig): Record<string, string | number> {
	const defines: Record<string, string | number> = {
		PRIMARY_STEPS: config.primarySteps,
		LIGHT_STEPS: config.lightSteps
	};
	if (config.eclipseShadows) defines.ATMO_ECLIPSE = '';
	if (config.ringShadows) defines.ATMO_RING_SHADOW = '';
	if (config.insideView) defines.ATMO_INSIDE = '';
	if (config.layeredDensity) defines.ATMO_LAYERED = '';
	return defines;
}

/** Recompile the shell for a new quality config; no-op when it already
 *  matches. Rare and ≤10 programs, so the compile hitch is acceptable. */
export function applyAtmosphereQuality(
	node: AtmosphereNode,
	config: AtmosphereQualityConfig
): void {
	const key = atmosphereConfigKey(config);
	if (key === node.qualityKey) return;
	node.qualityKey = key;
	node.material.defines = qualityDefines(config);
	node.material.needsUpdate = true;
}

/**
 * Debug tuner entry point: swap in a full replacement param set and re-derive
 * every uniform (plus the shell scale, for `topAltitudeKm` changes) against the
 * node's current reference radius. The phase table is per-aerosol offline data,
 * not a tunable — it stays whatever the body was built with.
 */
export function applyAtmosphereParams(node: AtmosphereNode, params: AtmosphereParams): void {
	syncProfileTexture(node.material, node.params.mieProfile, params.mieProfile);
	node.params = params;
	const u = node.material.uniforms;
	u.uGroundAlbedo.value = params.groundAlbedo ?? 0;
	const planetRadiusScene = u.uPlanetRadiusScene.value as number;
	setRadiusUniforms(node.material, params, planetRadiusScene, node.planetRadiusKm);
	u.uMultiScatter.value = params.multiScatterGain;
	u.uBakedComp.value = params.bakedCompensation;
	const c = params.sunColor;
	(u.uSunColor.value as Vector3).set(c[0], c[1], c[2]);
	const shellScene = planetRadiusScene * (1 + params.topAltitudeKm / node.planetRadiusKm);
	node.mesh.scale.setScalar(shellScene / node.geometryRadiusScene);
}

/**
 * Reshape the shell for a body whose mesh just received SPICE triaxial radii.
 * The mesh stays a sphere sized to contain the atmosphere ellipsoid (equatorial
 * radius); the shader's squashed-space march (`uStretch` along `uSpinAxis`)
 * models the flattening. a/b asymmetry is below visual relevance, so the
 * larger equatorial axis is used.
 */
export function syncAtmosphereEllipsoid(
	node: AtmosphereNode,
	equatorialKm: number,
	polarKm: number,
	equatorialScene: number
): void {
	node.planetRadiusKm = equatorialKm;
	setRadiusUniforms(node.material, node.params, equatorialScene, equatorialKm);
	node.material.uniforms.uStretch.value = equatorialKm / polarKm;
	const shellScene = equatorialScene * (1 + node.params.topAltitudeKm / equatorialKm);
	node.mesh.scale.setScalar(shellScene / node.geometryRadiusScene);
}

/**
 * Point the shell's ring-shadow uniforms at the ring system once it loads.
 * The Vector3 slots are the *same objects* `updateRingShaders` mutates for the
 * planet-surface shadow each frame, so the air column and the ground stay in
 * lockstep for free.
 */
export function attachRingShadowToAtmosphere(
	node: AtmosphereNode,
	ringShadow: PlanetRingShadowUniforms,
	transparency: Texture,
	innerScene: number,
	outerScene: number
): void {
	const u = node.material.uniforms;
	u.uRingShadowTransparency.value = transparency;
	u.uRingShadowInnerScene.value = innerScene;
	u.uRingShadowOuterScene.value = outerScene;
	u.uRingShadowSunDir = ringShadow.uRingShadowSunDir;
	u.uRingShadowPoleDir = ringShadow.uRingShadowPoleDir;
	u.uRingShadowCenter = ringShadow.uRingShadowCenter;
	// Shared refs: the renderer's per-frame writes reach both materials.
	u.uRingShadowIntensity = ringShadow.uRingShadowIntensity;
	u.uRingShadowSunAngularRadius = ringShadow.uRingShadowSunAngularRadius;
}

/** Dispose the GPU resources owned by an atmosphere node. */
export function disposeAtmosphereNode(node: AtmosphereNode): void {
	node.mesh.geometry.dispose();
	(node.material.uniforms.uMiePhaseTex.value as Texture).dispose();
	const profileTex = node.material.uniforms.uMieProfileTex.value as Texture;
	if (profileTex !== white) profileTex.dispose();
	(node.mesh.material as Material).dispose();
}
