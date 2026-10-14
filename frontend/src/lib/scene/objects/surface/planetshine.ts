/**
 * The sunlight that a nearby body reflects onto another: Saturn on Mimas, Mars
 * on Phobos, the Earth on the Moon. It lights the night side that faces the
 * shiner.
 *
 * The shiner is a Lambert sphere. Its light at the receiver comes from the
 * direction of its centre, and its disc has an angular radius, so a facet
 * near the horizon of the shiner sees part of the disc.
 *
 * The light goes into the indirect diffuse term. The eclipse, relief-shadow
 * and photometry hooks scale only the direct terms, so they do not change it.
 * The shadow of a third body on the shiner and the shadow of the terrain on
 * the receiver are not in the model.
 */

import { type Color, type MeshStandardMaterial, Vector3, Vector4 } from 'three';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';

/** Shiners per receiver. A moon has one planet. The second slot is for a large neighbour. */
export const MAX_SHINERS = 2;

/** Light of a shiner, as a part of the sunlight on it, below which it is skipped.
 *  At this level it is under 4% of the ambient fill. Earthshine on the Moon is below it. */
export const SHINE_FLOOR = 1e-4;

/** Light of a Lambert sphere at phase angle `a`, in radians, over its light at full phase. */
export function lambertSpherePhase(a: number): number {
	return (Math.sin(a) + (Math.PI - a) * Math.cos(a)) / Math.PI;
}

/**
 * Irradiance that a Lambert sphere of albedo 1 gives a facet that faces it,
 * over the irradiance of the sunlight on the sphere. `radius` and `distance`
 * are in one unit. `a` is the phase angle at the sphere, from the Sun to the
 * receiver. 2/3 of the Lambert albedo is the geometric albedo of the sphere.
 */
export function planetshineFraction(radius: number, distance: number, a: number): number {
	const k = radius / distance;
	return (2 / 3) * lambertSpherePhase(a) * k * k;
}

/**
 * The light of a sphere on a facet, over its light on a facet that faces it.
 * `cosTheta` is the cosine of the angle from the normal to the centre of the
 * sphere. `sinAlpha` is the sine of the angular radius of the sphere. Where
 * all of the disc is above the horizon, it is the cosine. Across the horizon,
 * a parabola joins it to 0 with the same slope at both ends.
 *
 * CPU port of `sphereLightCosine` in {@link PLANETSHINE_GLSL}. A change to one
 * must be made in the other. `planetshine.test.ts` is the contract.
 */
export function sphereLightCosine(cosTheta: number, sinAlpha: number): number {
	if (cosTheta >= sinAlpha) return cosTheta;
	const t = Math.max(cosTheta + sinAlpha, 0);
	return (t * t) / (4 * sinAlpha);
}

const PLANETSHINE_GLSL = /* glsl */ `
	#define PLANETSHINE_SHINERS ${MAX_SHINERS}
	uniform vec4 uShineDir[PLANETSHINE_SHINERS];
	uniform vec3 uShineLight[PLANETSHINE_SHINERS];

	float sphereLightCosine(float cosTheta, float sinAlpha) {
		float t = max(cosTheta + sinAlpha, 0.0);
		return cosTheta >= sinAlpha ? cosTheta : t * t / (4.0 * sinAlpha);
	}
`;

const PLANETSHINE_LIGHT = /* glsl */ `
	for (int i = 0; i < PLANETSHINE_SHINERS; i++) {
		vec4 shiner = uShineDir[i];
		// The slots fill in order, so the first empty slot ends the list.
		if (shiner.w <= 0.0) break;
		float cosine = sphereLightCosine(dot(geometryNormal, mat3(viewMatrix) * shiner.xyz), shiner.w);
		reflectedLight.indirectDiffuse += uShineLight[i] * cosine * BRDF_Lambert(material.diffuseContribution);
	}
`;

/** The planetshine uniforms of one receiver. Slots go from the strongest shiner down. */
export interface PlanetshineUniforms {
	/** `.xyz` is the unit vector from the receiver to the shiner, in world
	 *  space. `.w` is the sine of the angular radius of the shiner, 0 for an
	 *  empty slot. */
	uShineDir: { value: Vector4[] };
	/** Irradiance of the shiner on a facet that faces it, in the units of the scene lights. */
	uShineLight: { value: Vector3[] };
}

export function makePlanetshineUniforms(): PlanetshineUniforms {
	return {
		uShineDir: { value: Array.from({ length: MAX_SHINERS }, () => new Vector4(0, 0, 0, 0)) },
		uShineLight: { value: Array.from({ length: MAX_SHINERS }, () => new Vector3()) }
	};
}

/**
 * Attach planetshine to the material of a natural body. A receiver with no
 * shiner stops at the first slot. `uniforms` lets a second material of the
 * same body, such as its shape model, use the uniforms of the first.
 */
export function attachPlanetshine(
	material: MeshStandardMaterial,
	uniforms?: PlanetshineUniforms
): PlanetshineUniforms {
	const self = uniforms ?? makePlanetshineUniforms();
	chainShaderHook(material, 'planetshine', (shader) => {
		Object.assign(shader.uniforms, self);
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', `#include <common>\n${PLANETSHINE_GLSL}`)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>\n${PLANETSHINE_LIGHT}`
			);
	});
	return self;
}

/** A body that can light others, for one frame. Positions are in scene units. */
export interface Shiner {
	x: number;
	y: number;
	z: number;
	radius: number;
	/** Unit vector from the shiner to the Sun. */
	sunX: number;
	sunY: number;
	sunZ: number;
	/** Irradiance of the sunlight on the shiner, in the units of the scene lights. */
	sunlight: number;
	/** Lambert albedo in linear RGB. */
	albedo: Color;
}

const _strength = new Float64Array(MAX_SHINERS);
const _swapDir = new Vector4();
const _swapLight = new Vector3();

/**
 * Fill `out` with the strongest of the first `count` shiners at the point
 * (`x`, `y`, `z`), and return how many it keeps. A shiner whose light is below
 * {@link SHINE_FLOOR} of its sunlight is skipped. A shiner whose centre is
 * within its radius of the point is the receiver itself.
 */
export function selectShiners(
	out: PlanetshineUniforms,
	x: number,
	y: number,
	z: number,
	shiners: readonly Shiner[],
	count: number
): number {
	const dirs = out.uShineDir.value;
	const lights = out.uShineLight.value;
	let kept = 0;
	for (let i = 0; i < count; i++) {
		const s = shiners[i];
		const dx = s.x - x;
		const dy = s.y - y;
		const dz = s.z - z;
		const d2 = dx * dx + dy * dy + dz * dz;
		// The phase function and the albedo are at most 1.
		if ((2 / 3) * s.radius * s.radius < SHINE_FLOOR * d2) continue;
		const d = Math.sqrt(d2);
		if (d <= s.radius) continue;
		const k = s.radius / d;
		const cosPhase = -(dx * s.sunX + dy * s.sunY + dz * s.sunZ) / d;
		const fraction = planetshineFraction(
			s.radius,
			d,
			Math.acos(Math.max(-1, Math.min(1, cosPhase)))
		);
		const strength = fraction * (0.2126 * s.albedo.r + 0.7152 * s.albedo.g + 0.0722 * s.albedo.b);
		if (strength < SHINE_FLOOR) continue;
		let slot = kept;
		if (kept < MAX_SHINERS) kept++;
		else if (strength > _strength[MAX_SHINERS - 1]) slot = MAX_SHINERS - 1;
		else continue;
		_strength[slot] = strength;
		dirs[slot].set(dx / d, dy / d, dz / d, k);
		lights[slot].set(s.albedo.r, s.albedo.g, s.albedo.b).multiplyScalar(s.sunlight * fraction);
		for (; slot > 0 && _strength[slot - 1] < strength; slot--) {
			_strength[slot] = _strength[slot - 1];
			_strength[slot - 1] = strength;
			_swapDir.copy(dirs[slot - 1]);
			dirs[slot - 1].copy(dirs[slot]);
			dirs[slot].copy(_swapDir);
			_swapLight.copy(lights[slot - 1]);
			lights[slot - 1].copy(lights[slot]);
			lights[slot].copy(_swapLight);
		}
	}
	for (let i = kept; i < MAX_SHINERS; i++) {
		dirs[i].set(0, 0, 0, 0);
		lights[i].set(0, 0, 0);
	}
	return kept;
}
