/**
 * Per-body atmospheric-scattering shell: a sphere a little larger than the
 * planet, drawn with an additive {@link ShaderMaterial} that ray-marches the
 * single-scattered sunlight (Rayleigh + Mie, with an ozone absorption layer)
 * along the slice of atmosphere each view ray passes through and adds the
 * in-scattered radiance on top of the already-rendered scene.
 *
 * From space this reads as the planet's limb glow / blue rim plus a
 * forward-scattered haze on the sunward edge; over the lit disc it adds the
 * faint dayside airglow. The shell does not (yet) tint or darken the surface
 * seen *through* it — that's aerial perspective, which the LUT-based pipeline
 * handles.
 *
 * Coordinates: the scattering integral runs in planet-radius-normalised units
 * (planet = unit sphere, atmosphere top = {@link uAtmosphereRatio}), not scene
 * units. Earth's radius is ~4e-4 scene units and its 8 km Rayleigh scale
 * height is ~6e-7 of that — squarely in float32 mush — whereas normalised it's
 * ~1.3e-3 and every density/optical-depth term stays smooth. The only scene-
 * unit input is `cameraPosition - planetCenter`, divided by the planet radius
 * up front.
 *
 * The single-scatter recipe — primary march, nested light march toward the
 * Sun, Cornette–Shanks Mie phase, exponential Rayleigh/Mie density layers, a
 * tent-shaped ozone layer, Beer–Lambert transmittance — follows the approach
 * walked through in Maxime Heckel's "On rendering realistic-looking skies,
 * sunsets, and planets"
 * (https://blog.maximeheckel.com/posts/on-rendering-the-sky-sunsets-and-planets/),
 * which in turn distills the Bruneton / Hillaire precomputed-scattering model.
 * Here it stays a brute-force per-fragment march: the shell only ever covers a
 * planet's screen footprint, so there's no need for the precomputed LUTs.
 *
 * Limitation: `side: FrontSide` assumes the camera is *outside* the shell.
 * That's the only regime this path is wired for; viewing from within the
 * atmosphere needs a different coverage primitive (and the full LUT /
 * composition pipeline).
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
	/** Ozone absorption coefficient, per km, for (R, G, B). Pure absorption,
	 *  no scattering — it carves the blue/purple out of twilight. */
	ozoneAbsorptionPerKm: [number, number, number];
	/** Centre altitude of the (linear tent) ozone layer, km. */
	ozoneCenterKm: number;
	/** Half-width of the ozone tent, km — density falls linearly to 0 at
	 *  `ozoneCenterKm ± ozoneWidthKm`. */
	ozoneWidthKm: number;
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
	ozoneAbsorptionPerKm: [0.65e-3, 1.881e-3, 0.085e-3],
	ozoneCenterKm: 25,
	ozoneWidthKm: 15,
	sunIntensity: 3,
	sunColor: [1.0, 1.0, 1.0]
};

/**
 * Atmosphere parameters keyed by NAIF body id. Only bodies listed here get a
 * scattering shell. Earth-only for now; other atmospheres (Mars, Venus, Titan,
 * the gas giants) are mostly artistic rather than measured and can be added
 * here as they're tuned.
 */
export const ATMOSPHERE_PARAMS: Record<string, AtmosphereParams> = {
	'naif-399': EARTH
};

/** Scene-side handle for a body's atmosphere shell. */
export interface AtmosphereNode {
	mesh: Mesh;
	material: ShaderMaterial;
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
	uniform float uPlanetRadiusScene;
	uniform float uAtmosphereRatio;  // (planet radius + atmosphere top) / planet radius
	uniform vec3 uRayleighScatter;   // β_R, per planet radius, (R,G,B)
	uniform float uRayleighScaleHeight;
	uniform float uMieScatter;       // β_M scattering, per planet radius
	uniform float uMieExtinction;    // β_M extinction, per planet radius
	uniform float uMieScaleHeight;
	uniform float uMieG;
	uniform vec3 uOzoneAbsorption;   // β_O, per planet radius, (R,G,B)
	uniform float uOzoneCenter;
	uniform float uOzoneWidth;
	uniform float uSunIntensity;
	uniform vec3 uSunColor;

	varying vec3 vWorldPos;
	varying vec3 vPlanetCenter;

	#define PRIMARY_STEPS 16
	#define LIGHT_STEPS 8

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

	// Local (Rayleigh, Mie, ozone) densities at altitude h, in planet radii
	// above the surface. Ozone is a linear tent peaking at uOzoneCenter.
	vec3 densities(float h) {
		return vec3(
			exp(-h / uRayleighScaleHeight),
			exp(-h / uMieScaleHeight),
			max(0.0, 1.0 - abs(h - uOzoneCenter) / uOzoneWidth)
		);
	}

	// Optical depth (Rayleigh, Mie, ozone), in planet-radius units, from p
	// toward the Sun out to the top of the atmosphere. Returns a huge value if
	// the planet itself blocks the Sun from p, so the caller's exp() collapses
	// transmittance to ~0 (a hard terminator — no refraction modelled).
	vec3 sunOpticalDepth(vec3 p) {
		if (raySphere(p, uSunDir, 1.0).x > 0.0) return vec3(1e6);
		float far = raySphere(p, uSunDir, uAtmosphereRatio).y;
		float dt = far / float(LIGHT_STEPS);
		vec3 od = vec3(0.0);
		for (int i = 0; i < LIGHT_STEPS; i++) {
			vec3 s = p + uSunDir * (dt * (float(i) + 0.5));
			od += densities(length(s) - 1.0) * dt;
		}
		return od;
	}

	void main() {
		vec3 ro = (cameraPosition - vPlanetCenter) / uPlanetRadiusScene;
		vec3 rd = normalize(vWorldPos - cameraPosition);

		vec2 atmoHit = raySphere(ro, rd, uAtmosphereRatio);
		if (atmoHit.y < 0.0) discard;             // atmosphere entirely behind us

		vec2 planetHit = raySphere(ro, rd, 1.0);
		float tStart = max(atmoHit.x, 0.0);       // camera may sit just inside the shell
		float tEnd = atmoHit.y;
		if (planetHit.x > tStart && planetHit.x < tEnd) tEnd = planetHit.x; // march stops at the surface
		if (tEnd <= tStart) discard;

		float mu = dot(rd, uSunDir);
		float phaseR = (3.0 / (16.0 * PI)) * (1.0 + mu * mu);
		float g = uMieG;
		float phaseM = (3.0 / (8.0 * PI))
			* ((1.0 - g * g) * (1.0 + mu * mu))
			/ ((2.0 + g * g) * pow(max(1.0 + g * g - 2.0 * g * mu, 1e-4), 1.5));

		float dt = (tEnd - tStart) / float(PRIMARY_STEPS);
		vec3 viewOD = vec3(0.0);                  // optical depth, camera → current sample
		vec3 accumR = vec3(0.0);                  // Σ transmittance · ρ_R · dt, per channel
		vec3 accumM = vec3(0.0);

		for (int i = 0; i < PRIMARY_STEPS; i++) {
			vec3 p = ro + rd * (tStart + dt * (float(i) + 0.5));
			vec3 dStep = densities(length(p) - 1.0) * dt;   // (ρ_R, ρ_M, ρ_O) · dt
			viewOD += dStep;

			vec3 totalOD = viewOD + sunOpticalDepth(p);     // camera → sample → Sun
			vec3 transmittance = exp(-(
				uRayleighScatter * totalOD.x +
				uMieExtinction * totalOD.y +
				uOzoneAbsorption * totalOD.z
			));
			accumR += transmittance * dStep.x;
			accumM += transmittance * dStep.y;
		}

		vec3 color = uSunIntensity * uSunColor * (
			accumR * uRayleighScatter * phaseR +
			accumM * uMieScatter * phaseM
		);

		// Fade out as the planet shrinks below ~half a pixel — beyond that the
		// limb-width ray-sphere math is just float32 noise, and the glow is
		// invisible anyway. length(ro) is the camera distance in planet radii.
		color *= 1.0 - smoothstep(2000.0, 6000.0, length(ro));

		gl_FragColor = vec4(max(color, 0.0), 1.0);
		#include <logdepthbuf_fragment>
	}
`;

/**
 * Build the atmosphere shell for a body. `planetRadiusScene` / `planetRadiusKm`
 * are the body's surface radius in scene units and kilometres respectively; the
 * shell sphere is `planetRadiusScene · (1 + topAltitudeKm / planetRadiusKm)`.
 *
 * The mesh carries no position of its own — the renderer keeps it at the
 * planet's focus-relative centre via the body's `extraObjects` list, and pushes
 * the body→Sun direction onto `material.uniforms.uSunDir` each frame.
 */
export function buildAtmosphereNode(
	params: AtmosphereParams,
	planetRadiusScene: number,
	planetRadiusKm: number
): AtmosphereNode {
	const ratio = 1 + params.topAltitudeKm / planetRadiusKm;
	// "Per planet radius": multiply a per-km coefficient by the radius in km so
	// the shader integrates optical depth over distances measured in radii.
	const toNorm = (perKm: number) => perKm * planetRadiusKm;
	const r = params.rayleighScatterPerKm;
	const oz = params.ozoneAbsorptionPerKm;
	const c = params.sunColor;

	const material = new ShaderMaterial({
		uniforms: {
			uSunDir: { value: new Vector3(1, 0, 0) },
			uPlanetRadiusScene: { value: planetRadiusScene },
			uAtmosphereRatio: { value: ratio },
			uRayleighScatter: { value: new Vector3(toNorm(r[0]), toNorm(r[1]), toNorm(r[2])) },
			uRayleighScaleHeight: { value: params.rayleighScaleHeightKm / planetRadiusKm },
			uMieScatter: { value: toNorm(params.mieScatterPerKm) },
			uMieExtinction: { value: toNorm(params.mieExtinctionPerKm) },
			uMieScaleHeight: { value: params.mieScaleHeightKm / planetRadiusKm },
			uMieG: { value: params.mieG },
			uOzoneAbsorption: { value: new Vector3(toNorm(oz[0]), toNorm(oz[1]), toNorm(oz[2])) },
			uOzoneCenter: { value: params.ozoneCenterKm / planetRadiusKm },
			uOzoneWidth: { value: params.ozoneWidthKm / planetRadiusKm },
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

	const geometry = new SphereGeometry(planetRadiusScene * ratio, 64, 64);
	const mesh = new Mesh(geometry, material);
	// Draw after the opaque planet and after clouds/rings (renderOrder 1) so the
	// glow composites over everything else around the body.
	mesh.renderOrder = 2;
	mesh.userData.isAtmosphereMesh = true;
	return { mesh, material };
}

/** Dispose the GPU resources owned by an atmosphere node. */
export function disposeAtmosphereNode(node: AtmosphereNode): void {
	node.mesh.geometry.dispose();
	(node.mesh.material as Material).dispose();
}
