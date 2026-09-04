/**
 * Analytical sun-disc occlusion: each {@link MeshStandardMaterial} body
 * computes how much of the Sun's disc neighbouring bodies block and dims
 * direct sunlight by that fraction. Treating the Sun as a finite disc gives a
 * real penumbra, a 100%-obscured umbra core, and annular eclipses for free
 * when the occluder's angular size is smaller than the Sun's.
 *
 * Replaces the directional shadow map for body-on-body shadows: per-pixel,
 * so no blockiness or resolution dropout on close zoom, and one formula
 * covers solar/lunar eclipses and mutual moon transits alike. The
 * Saturn-on-rings shadow instead uses the oblate-spheroid ray-march in
 * `rings.ts`; this is the spherical-occluder version for solid bodies.
 */

import { type MeshStandardMaterial, Vector3, Vector4 } from 'three';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';

/** Hard cap on simultaneously-tracked occluders. The shader loops up to
 *  {@link EclipseSceneUniforms.uOccluderCount} so unused slots cost
 *  nothing past the early-exit. Sized to comfortably cover Saturn's main
 *  moon set with headroom; bigger systems can bump this. */
export const MAX_OCCLUDERS = 32;

/**
 * Scene-wide eclipse uniforms — one instance shared by every body's fragment
 * shader, mutated in place each frame.
 *
 * `uSunDir`/`uSunAngularRadius` instead of `uSunPos`/`uSunRadius`: the Sun is
 * ~1 AU away while receivers sit near the focus origin, so float32 would
 * quantise `uSunPos - vWorldPos` into stripes. CPU-normalising once in
 * float64 keeps the direction smooth; per-fragment `dSun` variation is far
 * below the Sun's angular size, so `asin(R_sun / dSun)` is precomputed too.
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
}

const SHARED: EclipseSceneUniforms = {
	uSunDir: { value: new Vector3(1, 0, 0) },
	uSunAngularRadius: { value: 0 },
	uOccluderCount: { value: 0 },
	uOccluders: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) }
};

/**
 * GLSL closed-form Sun-disc obscuration, shared by every receiver material and
 * the atmosphere shell. Declares the scene-wide occluder uniforms; the caller
 * supplies the fragment position, the receiver's own center (self-skip), and
 * the sun direction. Mirrored on the CPU by {@link evaluateEclipseFactor};
 * keep both in sync (eclipse-shadow.test.ts is the contract). Requires
 * three.js `<common>` (PI).
 *
 * Two regimes:
 *  (1) Comparable angular sizes (e.g. Earth eclipse, aSun ≈ aMoon): the
 *      standard two-circle lens-area formula — stable since no term
 *      dominates by orders of magnitude.
 *  (2) Occluder much larger than the Sun (e.g. LEO satellite under Earth):
 *      the lens formula's terms nearly cancel there, amplifying float32
 *      noise into blocky shading. The occluder limb is locally straight at
 *      sun-disc scale for aOc > 10·aSun, so use a chord approximation
 *      instead: covered fraction = Sun-disc area on one side of a chord at
 *      signed distance (aOc − sep).
 */
export const ECLIPSE_FACTOR_GLSL = `
	#define ECLIPSE_MAX_OCCLUDERS ${MAX_OCCLUDERS}
	uniform float uSunAngularRadius;
	uniform int uOccluderCount;
	uniform vec4 uOccluders[ECLIPSE_MAX_OCCLUDERS];

	float eclipseFactorAt(vec3 fragPos, vec3 selfPos, vec3 sunDir) {
		if (uSunAngularRadius <= 0.0) return 1.0;
		float aSun = uSunAngularRadius;
		float result = 1.0;
		for (int i = 0; i < ECLIPSE_MAX_OCCLUDERS; i++) {
			if (i >= uOccluderCount) break;
			vec4 oc = uOccluders[i];
			float r = oc.w;
			if (r <= 0.0) continue;
			// Skip the receiver's own body. Distinct bodies don't overlap, so
			// any occluder closer than its own radius to the receiver center
			// IS the receiver.
			if (length(oc.xyz - selfPos) < r * 0.5) continue;
			vec3 toOc = oc.xyz - fragPos;
			float dOc = length(toOc);
			if (dOc < 1e-5) continue;
			float aOc = asin(min(r / dOc, 1.0));
			float sep = acos(clamp(dot(sunDir, toOc) / dOc, -1.0, 1.0));

			if (aOc > 10.0 * aSun) {
				// Regime (2): chord approximation.
				float t = (aOc - sep) / aSun;
				if (t >= 1.0) { result = 0.0; break; }    // sun fully behind
				if (t <= -1.0) continue;                  // no overlap
				float covered = (acos(-t) + t * sqrt(max(1.0 - t * t, 0.0))) / PI;
				result *= 1.0 - covered;
				continue;
			}

			// Regime (1): lens formula.
			if (sep >= aSun + aOc) continue;                  // no overlap
			if (sep + aSun <= aOc) { result = 0.0; break; }   // total
			if (sep + aOc <= aSun) {                          // annular
				result *= 1.0 - (aOc * aOc) / (aSun * aSun);
				continue;
			}
			float a = aSun, b = aOc, c = sep;
			float x = (c * c + a * a - b * b) / (2.0 * c);
			float y = sqrt(max(a * a - x * x, 0.0));
			float A = a * a * acos(clamp(x / a, -1.0, 1.0))
				+ b * b * acos(clamp((c - x) / b, -1.0, 1.0))
				- c * y;
			result *= 1.0 - A / (PI * a * a);
		}
		return result;
	}
`;

/** The single scene-wide eclipse uniform set. Every receiver's
 *  `onBeforeCompile` re-pins these references via `Object.assign`, so
 *  mutating the values here propagates to every body. */
export function getEclipseSceneUniforms(): EclipseSceneUniforms {
	return SHARED;
}

/** Per-body eclipse uniforms, refilled each frame by `updateEclipseUniforms`:
 *  the receiver's own centre (so the shader skips its own slot) and the scene
 *  occluders whose shadow can reach it. The per-fragment loop runs over this
 *  short list, not the scene-wide one. */
export interface EclipseSelfUniforms {
	uEclipseSelfPos: { value: Vector3 };
	uOccluders: { value: Vector4[] };
	uOccluderCount: { value: number };
}

export function makeEclipseSelfUniforms(): EclipseSelfUniforms {
	return {
		uEclipseSelfPos: { value: new Vector3() },
		uOccluders: { value: Array.from({ length: MAX_OCCLUDERS }, () => new Vector4()) },
		uOccluderCount: { value: 0 }
	};
}

/**
 * Copy into `dst` the scene occluders whose shadow cone can touch a sphere of
 * `radius` at `center`, and return how many. Conservative: a kept occluder
 * renders identically, a dropped one could not have contributed.
 */
export function cullOccludersFor(
	dst: Vector4[],
	center: Vector3,
	radius: number,
	sunDir: Vector3
): number {
	const aSun = SHARED.uSunAngularRadius.value;
	const src = SHARED.uOccluders.value;
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
		dst[n++].copy(oc);
	}
	return n;
}

/**
 * CPU port of {@link ECLIPSE_FACTOR_GLSL}. Reads the same `SHARED` uniforms
 * the shader does, so call after `updateEclipseUniforms`. Used for the
 * spacecraft 3D-model overlay, which lives in a parallel scene the
 * per-fragment shader can't reach — a single ray from the body's center
 * suffices since the penumbra is uniform at spacecraft scale.
 *
 * Any change to the GLSL formula MUST be mirrored here; `eclipse-shadow.test.ts` is the contract.
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
		const sep = Math.acos(cosSep);

		if (aOc > 10 * aSun) {
			const t = (aOc - sep) / aSun;
			if (t >= 1) return 0;
			if (t <= -1) continue;
			const covered = (Math.acos(-t) + t * Math.sqrt(Math.max(1 - t * t, 0))) / Math.PI;
			result *= 1 - covered;
			continue;
		}

		if (sep >= aSun + aOc) continue;
		if (sep + aSun <= aOc) return 0;
		if (sep + aOc <= aSun) {
			result *= 1 - (aOc * aOc) / (aSun * aSun);
			continue;
		}
		const a = aSun;
		const b = aOc;
		const c = sep;
		const x = (c * c + a * a - b * b) / (2 * c);
		const y = Math.sqrt(Math.max(a * a - x * x, 0));
		const A =
			a * a * Math.acos(Math.max(-1, Math.min(1, x / a))) +
			b * b * Math.acos(Math.max(-1, Math.min(1, (c - x) / b))) -
			c * y;
		result *= 1 - A / (Math.PI * a * a);
	}
	return result;
}

/**
 * Inject the analytical sun-disc occlusion path into a
 * {@link MeshStandardMaterial}. Chains the existing `onBeforeCompile` so
 * other shader modifiers (e.g. `attachRingShadowToPlanet`) can stack on
 * top — Saturn runs both this and the ring-cast factor.
 *
 * Edits land after `<lights_fragment_end>`, scaling only direct light —
 * ambient/env light is untouched, so the umbra stays softly lit like a real
 * eclipse. `selfUniforms` lets a sibling material (e.g. a cloud overlay)
 * reuse the body's self-position for its own self-occlusion skip.
 */
export function attachEclipseShadowToBody(
	material: MeshStandardMaterial,
	selfUniforms?: EclipseSelfUniforms
): EclipseSelfUniforms {
	const self = selfUniforms ?? makeEclipseSelfUniforms();
	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
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
				float eclipseFactor() {
					return eclipseFactorAt(vEclipseWorldPos, uEclipseSelfPos, uSunDir);
				}
				`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				float eclipseShadow = eclipseFactor();
				reflectedLight.directDiffuse *= eclipseShadow;
				reflectedLight.directSpecular *= eclipseShadow;`
			);
	};
	tagShaderModifier(material, 'eclipse');
	material.needsUpdate = true;
	return self;
}
