/**
 * The shadow that one body casts on another. Each fragment of a
 * {@link MeshStandardMaterial} body finds the part of the disc of the Sun that
 * the bodies near it leave in view, and scales the direct sunlight by it. The
 * Sun is a disc, so the shadow has a penumbra, and an occluder smaller than
 * the Sun gives an annular eclipse.
 *
 * An occluder with air also bends some sunlight into its shadow. That light
 * goes through much air and comes out red. It gives the Moon its colour in a
 * total lunar eclipse.
 *
 * The occluders are spheres. The shadow of an oblate planet on its rings is in
 * `rings.ts`.
 */

import { type MeshStandardMaterial, Vector3, Vector4 } from 'three';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import type { AtmosphereParams } from './atmosphere';

/** Hard cap on simultaneously-tracked occluders. The shader loops up to
 *  {@link EclipseSceneUniforms.uOccluderCount} so unused slots cost
 *  nothing past the early-exit. Sized to comfortably cover Saturn's main
 *  moon set with headroom; bigger systems can bump this. */
export const MAX_OCCLUDERS = 32;

/** Display gain of the light that air bends into a shadow, of the same kind as the ambient fill. The physical value is about 1e-4. */
export const ECLIPSE_LEAK_GAIN = 0.5;
/** That light follows this power of the hidden part of the Sun, so that the penumbra stays grey. */
const LEAK_FADE = 8;

/**
 * The eclipse uniforms of the scene. Every body shader shares the one set,
 * and the renderer changes its values in place each frame.
 *
 * The Sun is a direction and an angular radius, not a place and a radius. It
 * is about 1 AU from receivers near the focus, so `uSunPos - vWorldPos` in
 * float32 would show stripes. The CPU finds both in float64 once. Over one
 * body they change much less than the angular size of the Sun.
 */
export interface EclipseSceneUniforms {
	/** Unit vector from the focus origin toward the Sun. */
	uSunDir: { value: Vector3 };
	/** Sun's angular radius in radians, computed from the focus origin.
	 *  0 disables the eclipse factor entirely. */
	uSunAngularRadius: { value: number };
	/** Number of populated entries in `uOccluders`. */
	uOccluderCount: { value: number };
	/** Pre-allocated occluder slots: `.xyz` = focus-relative center,
	 *  `.w` = scene-unit radius. Renderer mutates the first
	 *  `uOccluderCount` entries in place. */
	uOccluders: { value: Vector4[] };
	/** The air of each occluder, at the index of the occluder. See
	 *  {@link atmosphereLeak}. All 0 for an occluder with no air. */
	uOccluderLeak: { value: Vector4[] };
}

const SHARED: EclipseSceneUniforms = {
	uSunDir: { value: new Vector3(1, 0, 0) },
	uSunAngularRadius: { value: 0 },
	uOccluderCount: { value: 0 },
	uOccluders: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) },
	uOccluderLeak: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) }
};

/**
 * GLSL of the part of the disc of the Sun that the occluders leave in view.
 * Every receiver material and the atmosphere shell use it. It declares the
 * occluder uniforms. The caller gives the place of the fragment, the centre of
 * its own body and the direction of the Sun. Mirrored on the CPU by
 * {@link sunInView} and {@link evaluateEclipseFactor}. A change to one must be
 * made in the other. `eclipse-shadow.test.ts` is the contract. Needs `PI` from
 * three.js `<common>`.
 *
 * `sunInView` has two cases:
 *  (1) Discs of comparable size (the Moon over the Sun): the area of the lens
 *      that two circles share.
 *  (2) An occluder more than 10 times as wide as the Sun (the Earth over a
 *      satellite): the terms of the lens formula almost cancel in float32, and
 *      the limb is almost straight over the disc of the Sun. The part of the
 *      disc on one side of a chord replaces the lens.
 */
export const ECLIPSE_FACTOR_GLSL = `
	#define ECLIPSE_MAX_OCCLUDERS ${MAX_OCCLUDERS}
	uniform float uSunAngularRadius;
	uniform int uOccluderCount;
	uniform vec4 uOccluders[ECLIPSE_MAX_OCCLUDERS];

	float sunInView(float aSun, float aOc, float sep) {
		if (aOc > 10.0 * aSun) {
			// Case (2): chord.
			float t = (aOc - sep) / aSun;
			if (t >= 1.0) return 0.0;
			if (t <= -1.0) return 1.0;
			return 1.0 - (acos(-t) + t * sqrt(max(1.0 - t * t, 0.0))) / PI;
		}

		// Case (1): lens.
		if (sep >= aSun + aOc) return 1.0;
		if (sep + aSun <= aOc) return 0.0;
		if (sep + aOc <= aSun) return 1.0 - (aOc * aOc) / (aSun * aSun);
		float a = aSun, b = aOc, c = sep;
		float x = (c * c + a * a - b * b) / (2.0 * c);
		float y = sqrt(max(a * a - x * x, 0.0));
		float A = a * a * acos(clamp(x / a, -1.0, 1.0))
			+ b * b * acos(clamp((c - x) / b, -1.0, 1.0))
			- c * y;
		return 1.0 - A / (PI * a * a);
	}

	float eclipseFactorAt(vec3 fragPos, vec3 selfPos, vec3 sunDir) {
		if (uSunAngularRadius <= 0.0) return 1.0;
		float aSun = uSunAngularRadius;
		float result = 1.0;
		for (int i = 0; i < ECLIPSE_MAX_OCCLUDERS; i++) {
			if (i >= uOccluderCount) break;
			vec4 oc = uOccluders[i];
			float r = oc.w;
			if (r <= 0.0) continue;
			// Bodies do not overlap, so an occluder this near the centre of the receiver is the receiver.
			if (length(oc.xyz - selfPos) < r * 0.5) continue;
			vec3 toOc = oc.xyz - fragPos;
			float dOc = length(toOc);
			if (dOc < 1e-5) continue;
			float aOc = asin(min(r / dOc, 1.0));
			float sep = acos(clamp(dot(sunDir, toOc) / dOc, -1.0, 1.0));
			result *= sunInView(aSun, aOc, sep);
			if (result <= 0.0) break;
		}
		return result;
	}
`;

/**
 * GLSL of the sunlight that the air of the occluders bends into their shadow,
 * with the display gain. For surfaces. It goes after
 * {@link ECLIPSE_FACTOR_GLSL}. Mirrored on the CPU by {@link sunLeak} and
 * {@link evaluateEclipseLeak}. A change to one must be made in the other.
 */
const ECLIPSE_LEAK_GLSL = `
	uniform vec4 uOccluderLeak[ECLIPSE_MAX_OCCLUDERS];

	vec3 eclipseLeakAt(vec3 fragPos, vec3 selfPos, vec3 sunDir) {
		vec3 leak = vec3(0.0);
		float aSun = uSunAngularRadius;
		if (aSun <= 0.0) return leak;
		for (int i = 0; i < ECLIPSE_MAX_OCCLUDERS; i++) {
			if (i >= uOccluderCount) break;
			vec4 air = uOccluderLeak[i];
			if (air.w <= 0.0) continue;
			vec4 oc = uOccluders[i];
			if (length(oc.xyz - selfPos) < oc.w * 0.5) continue;
			vec3 toOc = oc.xyz - fragPos;
			float dOc = length(toOc);
			float aOc = asin(min(oc.w / dOc, 1.0));
			float sep = acos(clamp(dot(sunDir, toOc) / dOc, -1.0, 1.0));
			float inView = sunInView(aSun, aOc, sep);
			float behind = sunInView(aSun, max(aOc - air.w, 0.0), sep) - inView;
			if (behind > 0.0) leak += behind * pow(1.0 - inView, ${LEAK_FADE.toFixed(1)}) * exp(-air.xyz * clamp(aOc - sep, 0.0, air.w));
		}
		return ${ECLIPSE_LEAK_GAIN.toFixed(3)} * leak;
	}
`;

/** The single scene-wide eclipse uniform set. Every receiver's
 *  `onBeforeCompile` re-pins these references via `Object.assign`, so
 *  mutating the values here propagates to every body. */
export function getEclipseSceneUniforms(): EclipseSceneUniforms {
	return SHARED;
}

/** The eclipse uniforms of one body. `updateEclipseUniforms` fills them each
 *  frame with the centre of the body, which its shader skips as an occluder,
 *  and with the scene occluders whose shadow can reach it. The loop of a
 *  fragment is over this short list. */
export interface EclipseSelfUniforms {
	uEclipseSelfPos: { value: Vector3 };
	uOccluders: { value: Vector4[] };
	uOccluderLeak: { value: Vector4[] };
	uOccluderCount: { value: number };
}

export function makeEclipseSelfUniforms(): EclipseSelfUniforms {
	return {
		uEclipseSelfPos: { value: new Vector3() },
		uOccluders: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) },
		uOccluderLeak: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) },
		uOccluderCount: { value: 0 }
	};
}

/**
 * Copy into `dst` the scene occluders whose shadow cone can touch a sphere of
 * `radius` at `center`, and return how many. `leakDst` takes the air of each
 * one. An occluder that stays draws the same. An occluder that goes had no
 * effect.
 */
export function cullOccludersFor(
	dst: Vector4[],
	center: Vector3,
	radius: number,
	sunDir: Vector3,
	leakDst?: Vector4[]
): number {
	const aSun = SHARED.uSunAngularRadius.value;
	const src = SHARED.uOccluders.value;
	const leak = SHARED.uOccluderLeak.value;
	const srcCount = SHARED.uOccluderCount.value;
	let n = 0;
	for (let i = 0; i < srcCount; i++) {
		const oc = src[i];
		const ox = oc.x - center.x;
		const oy = oc.y - center.y;
		const oz = oc.z - center.z;
		const d2 = ox * ox + oy * oy + oz * oz;
		if (d2 < oc.w * oc.w * 0.25) continue; // the receiver itself (shader self-skip)
		const t = ox * sunDir.x + oy * sunDir.y + oz * sunDir.z;
		if (t < -(radius + oc.w)) continue; // anti-sunward: casts away from the receiver
		const reach = radius + oc.w + aSun * (t + radius) * 1.5;
		if (d2 - t * t > reach * reach) continue; // off the sun axis beyond any penumbra
		leakDst?.[n].copy(leak[i]);
		dst[n++].copy(oc);
	}
	return n;
}

/**
 * The part of the disc of the Sun that one occluder leaves in view, from 0 to
 * 1. `aSun` and `aOc` are the angular radii of the Sun and of the occluder.
 * `sep` is the angle between their centres.
 *
 * CPU port of `sunInView` in {@link ECLIPSE_FACTOR_GLSL}. A change to one must
 * be made in the other. `eclipse-shadow.test.ts` is the contract.
 */
export function sunInView(aSun: number, aOc: number, sep: number): number {
	if (aOc > 10 * aSun) {
		const t = (aOc - sep) / aSun;
		if (t >= 1) return 0;
		if (t <= -1) return 1;
		return 1 - (Math.acos(-t) + t * Math.sqrt(Math.max(1 - t * t, 0))) / Math.PI;
	}

	if (sep >= aSun + aOc) return 1;
	if (sep + aSun <= aOc) return 0;
	if (sep + aOc <= aSun) return 1 - (aOc * aOc) / (aSun * aSun);
	const a = aSun;
	const b = aOc;
	const c = sep;
	const x = (c * c + a * a - b * b) / (2 * c);
	const y = Math.sqrt(Math.max(a * a - x * x, 0));
	const A =
		a * a * Math.acos(Math.max(-1, Math.min(1, x / a))) +
		b * b * Math.acos(Math.max(-1, Math.min(1, (c - x) / b))) -
		c * y;
	return 1 - A / (Math.PI * a * a);
}

/**
 * {@link sunInView} for every occluder of the scene, at one point. It reads
 * the `SHARED` uniforms, so call it after `updateEclipseUniforms`. The
 * spacecraft 3D-model overlay uses it. The fragment shader cannot reach that
 * scene, and one ray from the centre of the craft is sufficient.
 */
export function evaluateEclipseFactor(receiverPos: Vector3, selfPos: Vector3): number {
	const aSun = SHARED.uSunAngularRadius.value;
	if (aSun <= 0) return 1;
	const sunDir = SHARED.uSunDir.value;
	const count = SHARED.uOccluderCount.value;
	const occluders = SHARED.uOccluders.value;
	let result = 1;
	for (let i = 0; i < count; i++) {
		const oc = occluders[i];
		const r = oc.w;
		if (r <= 0) continue;
		const dxSelf = oc.x - selfPos.x;
		const dySelf = oc.y - selfPos.y;
		const dzSelf = oc.z - selfPos.z;
		if (Math.hypot(dxSelf, dySelf, dzSelf) < r * 0.5) continue;
		const tx = oc.x - receiverPos.x;
		const ty = oc.y - receiverPos.y;
		const tz = oc.z - receiverPos.z;
		const dOc = Math.hypot(tx, ty, tz);
		if (dOc < 1e-5) continue;
		const aOc = Math.asin(Math.min(r / dOc, 1));
		const cosSep = Math.max(-1, Math.min(1, (sunDir.x * tx + sunDir.y * ty + sunDir.z * tz) / dOc));
		result *= sunInView(aSun, aOc, Math.acos(cosSep));
		if (result === 0) return 0;
	}
	return result;
}

/**
 * Fill `out` with the air of an occluder, as its shadow needs it. `.xyz` is
 * the Rayleigh optical depth of a ray that grazes the limb, per radian of its
 * bend, for (R, G, B). `.w` is the largest bend of a ray that comes through,
 * in radians. All 0 for air with no `refractivity`. `radiusKm` is the radius
 * of the reference level.
 *
 * The bend of a ray and its optical depth are both in proportion to the
 * density of the air at its lowest point. The transmittance of the ray with a
 * given bend is thus `exp(-k · bend)`. The lowest ray that comes through
 * grazes the reference level, or the level where the haze has an optical
 * depth of 1 along the ray if that is higher.
 */
export function atmosphereLeak(params: AtmosphereParams, radiusKm: number, out: Vector4): Vector4 {
	const refractivity = params.refractivity?.[1];
	if (!refractivity) return out.set(0, 0, 0, 0);
	const scaleKm = params.rayleighScaleHeightKm;
	const hazeScaleKm = params.mieScaleHeightKm;
	const haze = Math.min(
		params.mieScatterPerKm[0] + params.mieAbsorptionPerKm[0],
		params.mieScatterPerKm[1] + params.mieAbsorptionPerKm[1],
		params.mieScatterPerKm[2] + params.mieAbsorptionPerKm[2]
	);
	const hazeDepth = haze * Math.sqrt(2 * Math.PI * radiusKm * hazeScaleKm);
	const hazeFloor = Math.min(1, hazeDepth ** (-hazeScaleKm / scaleKm));
	const groundBend = refractivity * Math.sqrt((2 * Math.PI * radiusKm) / scaleKm);
	const perBend = scaleKm / refractivity;
	const [r, g, b] = params.rayleighScatterPerKm;
	return out.set(r * perBend, g * perBend, b * perBend, groundBend * hazeFloor);
}

/**
 * The sunlight that the air of one occluder bends to a point in its shadow,
 * for (R, G, B), as a part of the full sunlight and before the display gain.
 * `air` is from {@link atmosphereLeak}. The other arguments are those of
 * {@link sunInView}.
 *
 * The part of the disc of the Sun that is behind the limb, but not deeper
 * than the largest bend, gives the light. A power of the hidden part of the
 * Sun fades it out in the penumbra. The ray from the centre of the Sun gives
 * its colour.
 *
 * CPU port of one pass of the loop in `ECLIPSE_LEAK_GLSL`.
 */
export function sunLeak(
	aSun: number,
	aOc: number,
	sep: number,
	air: Vector4,
	out: Vector3
): Vector3 {
	const inView = sunInView(aSun, aOc, sep);
	const behind = sunInView(aSun, Math.max(aOc - air.w, 0), sep) - inView;
	if (behind <= 0) return out.set(0, 0, 0);
	const weight = behind * (1 - inView) ** LEAK_FADE;
	const bend = Math.min(Math.max(aOc - sep, 0), air.w);
	return out.set(
		weight * Math.exp(-air.x * bend),
		weight * Math.exp(-air.y * bend),
		weight * Math.exp(-air.z * bend)
	);
}

const _leak = new Vector3();

/**
 * {@link sunLeak} for every occluder of the scene, at one point, with the
 * display gain. The light of the Sun there is {@link evaluateEclipseFactor}
 * plus this. It reads the `SHARED` uniforms, as that function does.
 */
export function evaluateEclipseLeak(receiverPos: Vector3, selfPos: Vector3, out: Vector3): Vector3 {
	out.set(0, 0, 0);
	const aSun = SHARED.uSunAngularRadius.value;
	if (aSun <= 0) return out;
	const sunDir = SHARED.uSunDir.value;
	const count = SHARED.uOccluderCount.value;
	const occluders = SHARED.uOccluders.value;
	const leaks = SHARED.uOccluderLeak.value;
	for (let i = 0; i < count; i++) {
		const air = leaks[i];
		if (air.w <= 0) continue;
		const oc = occluders[i];
		if (Math.hypot(oc.x - selfPos.x, oc.y - selfPos.y, oc.z - selfPos.z) < oc.w * 0.5) continue;
		const tx = oc.x - receiverPos.x;
		const ty = oc.y - receiverPos.y;
		const tz = oc.z - receiverPos.z;
		const dOc = Math.hypot(tx, ty, tz);
		const aOc = Math.asin(Math.min(oc.w / dOc, 1));
		const cosSep = Math.max(-1, Math.min(1, (sunDir.x * tx + sunDir.y * ty + sunDir.z * tz) / dOc));
		out.add(sunLeak(aSun, aOc, Math.acos(cosSep), air, _leak));
	}
	return out.multiplyScalar(ECLIPSE_LEAK_GAIN);
}

/**
 * Attach the shadow of the other bodies to a {@link MeshStandardMaterial}. It
 * scales the direct light by the part of the Sun in view, and adds the light
 * that the air of the occluders bends in. The ambient light stays in the
 * umbra. `selfUniforms` lets a second material of the same body, such as its
 * cloud overlay, use the uniforms of the first.
 */
export function attachEclipseShadowToBody(
	material: MeshStandardMaterial,
	selfUniforms?: EclipseSelfUniforms
): EclipseSelfUniforms {
	const self = selfUniforms ?? makeEclipseSelfUniforms();
	chainShaderHook(material, 'eclipse', (shader) => {
		// `self` last: its occluder list shadows the scene-wide one.
		Object.assign(shader.uniforms, SHARED, self);

		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vEclipseWorldPos;')
			.replace(
				'#include <begin_vertex>',
				'#include <begin_vertex>\nvEclipseWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;'
			);

		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>
				uniform vec3 uSunDir;
				uniform vec3 uEclipseSelfPos;
				varying vec3 vEclipseWorldPos;
				${ECLIPSE_FACTOR_GLSL}
				${ECLIPSE_LEAK_GLSL}
				`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				vec3 eclipseLight = eclipseFactorAt(vEclipseWorldPos, uEclipseSelfPos, uSunDir)
					+ eclipseLeakAt(vEclipseWorldPos, uEclipseSelfPos, uSunDir);
				reflectedLight.directDiffuse *= eclipseLight;
				reflectedLight.directSpecular *= eclipseLight;`
			);
	});
	return self;
}
