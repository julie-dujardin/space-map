/**
 * The light of the Sun that the ground of a natural body sends to the camera.
 *
 * Dry ground has no specular light. Water keeps it. The specular mask gives
 * the part of a texel under water.
 *
 * A body with no atmosphere follows the lunar-Lambert law. At full phase its
 * disc is as bright at the limb as at the centre. A body with an atmosphere
 * keeps the Lambert law.
 *
 * The law has no phase function here, so ground that faces the Sun and the
 * camera keeps its brightness. Ground that the camera sees at a lower angle
 * than the Sun does would go above that brightness. There the lunar part
 * holds its value for equal angles.
 */

import type { MeshStandardMaterial, Vector3 } from 'three';
import { getAtmosphereParams } from '$lib/fetch/atmospheres';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import { getEclipseSceneUniforms } from './eclipse-shadow';

/** Polynomial of the lunar part in the phase angle, in degrees. From McEwen
 *  (1996), as `LunarLambertMcEwen` of USGS ISIS has it. */
const WEIGHT_POLY = [-0.019, 0.000242, -0.00000146] as const;
/** Floor of the sum of the two cosines. It bounds the gain where the Sun and
 *  the camera are both at the horizon of a facet. */
const GRAZE_FLOOR = 0.05;

/**
 * GLSL of the lunar-Lambert law. Mirrored on the CPU by
 * {@link lunarLambertWeight} and {@link lunarLambertGain}. A change to one
 * must be made in the other. `photometry.test.ts` is the contract.
 */
const LUNAR_LAMBERT_GLSL = /* glsl */ `
	float lunarLambertWeight(float phaseDeg) {
		return clamp(1.0 + phaseDeg * (${WEIGHT_POLY[0].toFixed(8)} + phaseDeg * (${WEIGHT_POLY[1].toFixed(8)} + phaseDeg * ${WEIGHT_POLY[2].toFixed(8)})), 0.0, 1.0);
	}

	float lunarLambertGain(float phaseDeg, float mu0, float mu) {
		float weight = lunarLambertWeight(phaseDeg);
		float sun = max(mu0, 0.0);
		return 2.0 * weight / max(sun + max(mu, sun), ${GRAZE_FLOOR.toFixed(3)}) + 1.0 - weight;
	}
`;

/** Weight of the lunar part. It is 1 at phase 0, and 0 from about 104° on,
 *  where the law is all Lambert. */
export function lunarLambertWeight(phaseDeg: number): number {
	const [a, b, c] = WEIGHT_POLY;
	return Math.min(1, Math.max(0, 1 + phaseDeg * (a + phaseDeg * (b + phaseDeg * c))));
}

/**
 * Radiance of the lunar-Lambert law over that of the Lambert law. `mu0` and
 * `mu` are the cosines of the incidence and emission angles. An emission
 * cosine below the incidence cosine counts as equal to it, so the product
 * with `mu0` is at most 1.
 */
export function lunarLambertGain(phaseDeg: number, mu0: number, mu: number): number {
	const weight = lunarLambertWeight(phaseDeg);
	const sun = Math.max(mu0, 0);
	return (2 * weight) / Math.max(sun + Math.max(mu, sun), GRAZE_FLOOR) + 1 - weight;
}

/** The Sun's specular light, kept for the part of the texel under water. */
const DRY_GROUND = /* glsl */ `
	#ifdef USE_ROUGHNESSMAP
		reflectedLight.directSpecular *= texelRoughness.g;
	#else
		reflectedLight.directSpecular = vec3(0.0);
	#endif
`;

/** The gain on the Sun's diffuse light, from the shaded normal. */
const LUNAR_LAMBERT = /* glsl */ `
	{
		vec3 sunView = mat3(viewMatrix) * uPhotometrySunDir;
		#if NUM_POINT_LIGHTS > 0
			// At the scale of the solar system the Sun is a point light, and the shared direction is that of the focus.
			if (pointLights[0].color.g > 0.0) sunView = normalize(pointLights[0].position - geometryPosition);
		#endif
		float phaseDeg = degrees(acos(clamp(dot(sunView, geometryViewDir), -1.0, 1.0)));
		reflectedLight.directDiffuse *= lunarLambertGain(
			phaseDeg,
			dot(geometryNormal, sunView),
			dot(geometryNormal, geometryViewDir)
		);
	}
`;

/**
 * Attach the law of the ground to the material of a natural body. A body with
 * no entry in the atmosphere table gets the lunar-Lambert law, so the table
 * must be loaded first. `sunDir` defaults to the scene's Sun; a stage with a
 * light of its own passes that light's direction.
 */
export function attachSurfacePhotometry(
	material: MeshStandardMaterial,
	bodyId: string,
	sunDir?: { value: Vector3 }
): void {
	const airless = !getAtmosphereParams(bodyId);
	chainShaderHook(material, airless ? 'photometryAirless' : 'photometry', (shader) => {
		let pars = '';
		let light = DRY_GROUND;
		if (airless) {
			// The chained eclipse shader declares `uSunDir`, so this one has its own name.
			shader.uniforms.uPhotometrySunDir = sunDir ?? getEclipseSceneUniforms().uSunDir;
			pars = `uniform vec3 uPhotometrySunDir;\n${LUNAR_LAMBERT_GLSL}`;
			light += LUNAR_LAMBERT;
		}
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', `#include <common>\n${pars}`)
			.replace('#include <lights_fragment_end>', `#include <lights_fragment_end>\n${light}`);
	});
}
