/**
 * Per-body atmospheric-scattering shell. Additive sphere drawn just outside the
 * planet; the fragment shader ray-marches single-scattered sunlight (Rayleigh +
 * Mie + one absorber band). Coordinates run in planet-radius-normalised units to keep
 * float32 well-conditioned — Earth's 8 km scale height in scene units is mush.
 *
 * Recipe follows Maxime Heckel's "On rendering realistic-looking skies, sunsets,
 * and planets" (which distills Bruneton/Hillaire); brute-force per-fragment
 * march is fine because the shell only ever covers the planet's screen footprint.
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
	AdditiveBlending,
	FrontSide,
	type Material,
	Mesh,
	ShaderMaterial,
	SphereGeometry,
	Vector3
} from 'three';
import { ECLIPSE_FACTOR_GLSL, getEclipseSceneUniforms } from './eclipse-shadow';

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
	/** Mie scattering coefficient at sea level, per km (wavelength-independent). */
	mieScatterPerKm: number;
	/** Mie *extinction* (scattering + absorption) at sea level, per km. */
	mieExtinctionPerKm: number;
	/** Mie density e-folding height, km. */
	mieScaleHeightKm: number;
	/** Mie phase asymmetry g ∈ [0, 1) — forward-scatter bias of aerosols. */
	mieG: number;
	/** Absorption coefficient of the body's absorber band (ozone on Earth,
	 *  tholins on Titan…), per km, for (R, G, B). Pure absorption, no
	 *  scattering — it carves colour out of the transmitted light. */
	absorptionPerKm: [number, number, number];
	/** Centre altitude of the (linear tent) absorber band, km. */
	absorptionCenterKm: number;
	/** Half-width of the absorber tent, km — density falls linearly to 0 at
	 *  `absorptionCenterKm ± absorptionWidthKm`. */
	absorptionWidthKm: number;
	/** Gain on the isotropic multiple-scattering ambient term. Single scatter
	 *  alone goes black wherever the direct sun path is extinguished — for
	 *  optically thick atmospheres (Titan, Venus) that wrongly darkens the
	 *  poles and the terminator, so thick/bright atmospheres want ≥ 1. */
	multiScatterGain: number;
	/** Linear gain on the in-scattered radiance. The scene renders LDR with no
	 *  tone mapping, so this is the knob that fits the glow brightness to it. */
	sunIntensity: number;
	/** Sun colour the scattering integral is multiplied by. */
	sunColor: [number, number, number];
}

/**
 * Earth's atmosphere. Rayleigh / Mie / ozone coefficients and the ozone tent
 * are the sRGB-fitted values from Bruneton's "Precomputed Atmospheric
 * Scattering" reference model (also the defaults Sébastien Hillaire's paper
 * uses); the 100 km atmosphere top matches Hillaire's `ATMOSPHERE_TOP`.
 * `sunIntensity` is a free knob tuned against this project's LDR rendering, not
 * a physical irradiance.
 */
const EARTH: AtmosphereParams = {
	topAltitudeKm: 80,
	rayleighScatterPerKm: [5.802e-3, 13.558e-3, 33.1e-3],
	rayleighScaleHeightKm: 8,
	mieScatterPerKm: 3.996e-3,
	mieExtinctionPerKm: 4.4e-3,
	mieScaleHeightKm: 1.2,
	mieG: 0.8,
	absorptionPerKm: [0.65e-3, 1.881e-3, 0.085e-3],
	absorptionCenterKm: 25,
	absorptionWidthKm: 15,
	multiScatterGain: 0.3,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/*
 * Non-Earth Rayleigh coefficients and scale heights are computed from each
 * atmosphere's composition, refractivity, King factor and number density at the
 * reference level (surface, cloud top, or 1-bar level — whatever the rendered
 * sphere shows), calibrated so the same formula reproduces Bruneton's Earth
 * values. Mie/haze rows are visual starting knobs, not derived: real aerosol
 * spectra are out of scope (cf. CosmoScout's Mie-theory paper). Gas giants and
 * the ice giants get a near-neutral shell — Uranus/Neptune's blue-green is CH₄
 * red absorption already baked into their cloud textures, so it isn't repeated
 * here. Titan's bluish Rayleigh shell above the orange haze texture matches its
 * real detached upper haze.
 */

/** Mars: thin CO₂ column (~2% of Earth's β_R) under a dominant dust layer. */
const MARS: AtmosphereParams = {
	topAltitudeKm: 100,
	rayleighScatterPerKm: [1.32e-4, 3.084e-4, 7.53e-4],
	rayleighScaleHeightKm: 10.9,
	mieScatterPerKm: 5e-3,
	mieExtinctionPerKm: 5.5e-3,
	mieScaleHeightKm: 11,
	mieG: 0.65,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.4,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Venus above the rendered cloud deck (~1 bar): dense CO₂ + bright limb haze. */
const VENUS: AtmosphereParams = {
	topAltitudeKm: 70,
	rayleighScatterPerKm: [1.531e-2, 3.578e-2, 8.736e-2],
	rayleighScaleHeightKm: 6.5,
	mieScatterPerKm: 2e-2,
	mieExtinctionPerKm: 2.2e-2,
	mieScaleHeightKm: 5,
	mieG: 0.7,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 1.5,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Titan: cold dense N₂ column; the orange haze is the texture itself. */
const TITAN: AtmosphereParams = {
	topAltitudeKm: 300,
	rayleighScatterPerKm: [3.067e-2, 7.166e-2, 1.749e-1],
	rayleighScaleHeightKm: 21.1,
	mieScatterPerKm: 8e-3,
	mieExtinctionPerKm: 8.8e-3,
	mieScaleHeightKm: 50,
	mieG: 0.6,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.5,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Jupiter above the 1-bar cloud texture: weak H₂/He Rayleigh, soft blue limb. */
const JUPITER: AtmosphereParams = {
	topAltitudeKm: 200,
	rayleighScatterPerKm: [1.955e-3, 4.569e-3, 1.116e-2],
	rayleighScaleHeightKm: 25.0,
	mieScatterPerKm: 1e-3,
	mieExtinctionPerKm: 1.1e-3,
	mieScaleHeightKm: 25,
	mieG: 0.6,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.3,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Saturn above the 1-bar cloud texture: like Jupiter, taller scale height. */
const SATURN: AtmosphereParams = {
	topAltitudeKm: 400,
	rayleighScatterPerKm: [2.646e-3, 6.184e-3, 1.51e-2],
	rayleighScaleHeightKm: 51.6,
	mieScatterPerKm: 1e-3,
	mieExtinctionPerKm: 1.1e-3,
	mieScaleHeightKm: 50,
	mieG: 0.6,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.3,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Uranus above the 1-bar level: near-neutral H₂/He shell. */
const URANUS: AtmosphereParams = {
	topAltitudeKm: 220,
	rayleighScatterPerKm: [4.32e-3, 1.009e-2, 2.464e-2],
	rayleighScaleHeightKm: 28.0,
	mieScatterPerKm: 5e-4,
	mieExtinctionPerKm: 5.5e-4,
	mieScaleHeightKm: 28,
	mieG: 0.5,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.4,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/** Neptune above the 1-bar level: near-neutral H₂/He shell. */
const NEPTUNE: AtmosphereParams = {
	topAltitudeKm: 170,
	rayleighScatterPerKm: [4.062e-3, 9.492e-3, 2.317e-2],
	rayleighScaleHeightKm: 21.2,
	mieScatterPerKm: 5e-4,
	mieExtinctionPerKm: 5.5e-4,
	mieScaleHeightKm: 21,
	mieG: 0.5,
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	multiScatterGain: 0.4,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/**
 * Atmosphere parameters keyed by NAIF body id. Only bodies listed here get a
 * scattering shell.
 */
export const ATMOSPHERE_PARAMS: Record<string, AtmosphereParams> = {
	'naif-299': VENUS,
	'naif-399': EARTH,
	'naif-499': MARS,
	'naif-599': JUPITER,
	'naif-606': TITAN,
	'naif-699': SATURN,
	'naif-799': URANUS,
	'naif-899': NEPTUNE
};

/** Scene-side handle for a body's atmosphere shell. */
export interface AtmosphereNode {
	mesh: Mesh;
	material: ShaderMaterial;
	/** Source params, kept so {@link syncAtmosphereEllipsoid} can re-derive the
	 *  radius-normalised uniforms when SPICE radii arrive. */
	params: AtmosphereParams;
	/** Radius the shell's SphereGeometry was built with, scene units. */
	geometryRadiusScene: number;
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
	uniform vec3 uRayleighScatter;   // β_R, per planet radius, (R,G,B)
	uniform float uRayleighScaleHeight;
	uniform float uMieScatter;       // β_M scattering, per planet radius
	uniform float uMieExtinction;    // β_M extinction, per planet radius
	uniform float uMieScaleHeight;
	uniform float uMieG;
	uniform vec3 uAbsorption;        // absorber band β, per planet radius, (R,G,B)
	uniform float uAbsorptionCenter;
	uniform float uAbsorptionWidth;
	uniform float uMultiScatter;
	uniform float uSunIntensity;
	uniform vec3 uSunColor;

	varying vec3 vWorldPos;
	varying vec3 vPlanetCenter;

	${ECLIPSE_FACTOR_GLSL}

	#define PRIMARY_STEPS 16
	#define LIGHT_STEPS 8
	#define ISO_PHASE 0.0795775   // 1 / 4π — isotropic phase for the ambient term
	#define MS_DIFFUSION 0.3      // slant-τ weight in the diffusive ambient falloff

	// Rendered terrain (DEM craters, below-datum landing sites) dips under the
	// analytic ellipsoid; ray blocking uses a slightly smaller sphere so the
	// shell's horizon never floats above the drawn ground. Density still
	// references the true surface (altitude 0 at radius 1).
	#define SURFACE_BLOCK_R 0.996

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
	// Below-surface altitudes are clamped so grazing sun rays integrate a huge
	// but finite optical depth — light through the deep atmosphere fades and
	// reddens smoothly instead of cutting off at a binary horizon test.
	vec3 densities(float h) {
		float hc = max(h, -0.02);
		// min() keeps the sub-surface exponentials finite in float32 (tiny
		// scale heights would overflow); 1e20 still collapses transmittance.
		return vec3(
			min(exp(-hc / uRayleighScaleHeight), 1e20),
			min(exp(-hc / uMieScaleHeight), 1e20),
			max(0.0, 1.0 - abs(hc - uAbsorptionCenter) / uAbsorptionWidth)
		);
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
		vec2 block = raySphere(p, sd, SURFACE_BLOCK_R - 0.015);
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

		vec2 planetHit = raySphere(ro, rd, SURFACE_BLOCK_R);
		float tStart = max(atmoHit.x, 0.0);       // covers the camera-inside case too
		float tEnd = atmoHit.y;
		if (planetHit.x > tStart && planetHit.x < tEnd) tEnd = planetHit.x; // march stops at the surface
		if (tEnd <= tStart) discard;

		float mu = dot(rdWorld, uSunDir);         // phase angle is physical — world space
		float phaseR = (3.0 / (16.0 * PI)) * (1.0 + mu * mu);
		float g = uMieG;
		float phaseM = (3.0 / (8.0 * PI))
			* ((1.0 - g * g) * (1.0 + mu * mu))
			/ ((2.0 + g * g) * pow(max(1.0 + g * g - 2.0 * g * mu, 1e-4), 1.5));

		vec3 sunSq = squash(uSunDir);
		float sunLen = length(sunSq);
		vec3 sd = sunSq / sunLen;

		float dt = (tEnd - tStart) / float(PRIMARY_STEPS);
		float dtWorld = dt / dLen;                // squashed step → world path length
		vec3 viewOD = vec3(0.0);                  // optical depth, camera → current sample
		vec3 accumR = vec3(0.0);                  // Σ transmittance · ρ_R · dt, per channel
		vec3 accumM = vec3(0.0);
		vec3 accumMS = vec3(0.0);                 // isotropic multiple-scatter ambient

		for (int i = 0; i < PRIMARY_STEPS; i++) {
			vec3 p = ro + rd * (tStart + dt * (float(i) + 0.5));
			vec3 dens = densities(length(p) - 1.0); // (ρ_R, ρ_M, ρ_A)
			vec3 dStep = dens * dtWorld;
			viewOD += dStep;

			vec3 viewT = exp(-(
				uRayleighScatter * viewOD.x +
				uMieExtinction * viewOD.y +
				uAbsorption * viewOD.z
			));
			vec3 sunOD = sunOpticalDepth(p, sd, sunLen);
			vec3 sunT = exp(-(
				uRayleighScatter * sunOD.x +
				uMieExtinction * sunOD.y +
				uAbsorption * sunOD.z
			));
			// Sun-disc occlusion by other bodies (e.g. the Moon during a solar
			// eclipse) dims the light reaching this sample — the shadow cone
			// sweeps through the atmosphere just like across the surface.
			vec3 pWorld = vPlanetCenter + unsquash(p) * uPlanetRadiusScene;
			float eclipse = eclipseFactorAt(pWorld, vPlanetCenter, uSunDir);

			vec3 direct = viewT * sunT * eclipse;
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
			accumMS += viewT * exp(-odVert) * msSunT *
				(uRayleighScatter * dStep.x + uMieScatter * dStep.y) *
				(uMultiScatter * eclipse);
		}

		vec3 color = uSunIntensity * uSunColor * (
			accumR * uRayleighScatter * phaseR +
			accumM * uMieScatter * phaseM +
			accumMS * ISO_PHASE
		);

		// Fade out as the planet shrinks below ~half a pixel — beyond that the
		// limb-width ray-sphere math is just float32 noise, and the glow is
		// invisible anyway. length(roWorld) is the camera distance in planet radii.
		color *= 1.0 - smoothstep(2000.0, 6000.0, length(roWorld));

		gl_FragColor = vec4(max(color, 0.0), 1.0);
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
	const ab = params.absorptionPerKm;
	const u = material.uniforms;
	u.uPlanetRadiusScene.value = planetRadiusScene;
	u.uAtmosphereRatio.value = 1 + params.topAltitudeKm / planetRadiusKm;
	(u.uRayleighScatter.value as Vector3).set(toNorm(r[0]), toNorm(r[1]), toNorm(r[2]));
	u.uRayleighScaleHeight.value = params.rayleighScaleHeightKm / planetRadiusKm;
	u.uMieScatter.value = toNorm(params.mieScatterPerKm);
	u.uMieExtinction.value = toNorm(params.mieExtinctionPerKm);
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
	const material = new ShaderMaterial({
		uniforms: {
			// Scene-wide eclipse occluder set — shared value refs, mutated in
			// place by updateEclipseUniforms each frame.
			uSunAngularRadius: eclipse.uSunAngularRadius,
			uOccluderCount: eclipse.uOccluderCount,
			uOccluders: eclipse.uOccluders,
			uSunDir: { value: new Vector3(1, 0, 0) },
			uSpinAxis: { value: new Vector3(0, 1, 0) },
			uStretch: { value: 1 },
			uPlanetRadiusScene: { value: 0 },
			uAtmosphereRatio: { value: 0 },
			uRayleighScatter: { value: new Vector3() },
			uRayleighScaleHeight: { value: 0 },
			uMieScatter: { value: 0 },
			uMieExtinction: { value: 0 },
			uMieScaleHeight: { value: 0 },
			uMieG: { value: params.mieG },
			uAbsorption: { value: new Vector3() },
			uAbsorptionCenter: { value: 0 },
			uAbsorptionWidth: { value: 0 },
			uMultiScatter: { value: params.multiScatterGain },
			uSunIntensity: { value: params.sunIntensity },
			uSunColor: { value: new Vector3(c[0], c[1], c[2]) }
		},
		vertexShader: VERTEX_SHADER,
		fragmentShader: FRAGMENT_SHADER,
		transparent: true,
		depthWrite: false,
		blending: AdditiveBlending,
		side: FrontSide
	});
	setRadiusUniforms(material, params, planetRadiusScene, planetRadiusKm);

	const geometryRadiusScene = planetRadiusScene * (1 + params.topAltitudeKm / planetRadiusKm);
	const geometry = new SphereGeometry(geometryRadiusScene, 64, 64);
	const mesh = new Mesh(geometry, material);
	// Draw after the opaque planet and after clouds/rings (renderOrder 1) so the
	// glow composites over everything else around the body.
	mesh.renderOrder = 2;
	mesh.userData.isAtmosphereMesh = true;
	return { mesh, material, params, geometryRadiusScene };
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
	setRadiusUniforms(node.material, node.params, equatorialScene, equatorialKm);
	node.material.uniforms.uStretch.value = equatorialKm / polarKm;
	const shellScene = equatorialScene * (1 + node.params.topAltitudeKm / equatorialKm);
	node.mesh.scale.setScalar(shellScene / node.geometryRadiusScene);
}

/** Dispose the GPU resources owned by an atmosphere node. */
export function disposeAtmosphereNode(node: AtmosphereNode): void {
	node.mesh.geometry.dispose();
	(node.mesh.material as Material).dispose();
}
