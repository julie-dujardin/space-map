/**
 * Analytical sun-disc occlusion: each {@link MeshStandardMaterial} body
 * computes how much of the Sun's disc is blocked by neighbouring bodies and
 * dims direct sunlight by that fraction. With the Sun treated as a finite
 * disc (rather than a directional light), partial obscuration produces a
 * real penumbra, the umbra core falls out as 100% obscuration, and annular
 * eclipses appear automatically when the occluder's angular size is smaller
 * than the Sun's.
 *
 * Replaces the directional shadow map for body-on-body shadows: it runs
 * per-pixel so there's no blockiness, no resolution dropout when zooming
 * close to the receiver, and the same code generalises across every
 * geometry the engine cares about — solar eclipses on Earth, lunar
 * eclipses on the Moon, mutual transits between Galilean moons, etc. The
 * Saturn-on-rings shadow uses a sibling oblate-spheroid ray-march in
 * `rings.ts`; this is the spherical-occluder version for solid bodies.
 */

import { type MeshStandardMaterial, Vector3, Vector4 } from 'three';

/** Hard cap on simultaneously-tracked occluders. The shader loops up to
 *  {@link EclipseSceneUniforms.uOccluderCount} so unused slots cost
 *  nothing past the early-exit. Sized to comfortably cover Saturn's main
 *  moon set with headroom; bigger systems can bump this. */
export const MAX_OCCLUDERS = 32;

/**
 * Scene-wide eclipse uniforms — one instance shared by every body's fragment
 * shader, mutated in place each frame.
 *
 * `uSunDir`/`uSunAngularRadius` instead of `uSunPos`/`uSunRadius`: in scene
 * units the Sun sits ~1 AU away while a receiver fragment is at most a
 * body-radius from focus origin, so float32 quantises `uSunPos - vWorldPos`
 * into stripes. CPU-normalising once in float64 keeps the direction smooth
 * across the whole body, and the per-fragment `dSun` variation (~1e-5) is far
 * below the Sun's angular size, so `asin(R_sun / dSun)` is also precomputed.
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

/** The single scene-wide eclipse uniform set. Every receiver's
 *  `onBeforeCompile` re-pins these references via `Object.assign`, so
 *  mutating the values here propagates to every body. */
export function getEclipseSceneUniforms(): EclipseSceneUniforms {
	return SHARED;
}

/** Per-body eclipse uniforms. The renderer mutates `uEclipseSelfPos` in
 *  place each frame so the shader can skip self-occlusion. */
export interface EclipseSelfUniforms {
	uEclipseSelfPos: { value: Vector3 };
}

/**
 * CPU port of the GLSL `eclipseFactor()` defined below. Reads the same
 * `SHARED` uniforms the shader does, so call after `updateEclipseUniforms`.
 *
 * Used for the spacecraft 3D-model overlay: the model lives in a parallel
 * scene with its own coordinates, so the per-fragment shader path can't run
 * on it. A single ray from the focused body's center is sufficient — at
 * spacecraft scale the penumbra is uniform across the model.
 *
 * Any change to the GLSL formula below MUST be mirrored here, and the
 * vitest cases in `eclipse-shadow.test.ts` are the contract that keeps the
 * two in sync.
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
 * top — Saturn ends up running both this and the ring-cast factor.
 *
 * The shader edits land after `<lights_fragment_end>`, so they scale only
 * the resolved direct light contribution. Indirect (ambient/env) light is
 * left alone — the umbra stays softly lit by ambient light, matching real
 * eclipses where the lunar/Earth umbra never goes pitch black.
 *
 * `selfUniforms` lets a sibling material (e.g. the cloud overlay above a
 * body's surface) reuse the body's self-position so its self-occlusion
 * skip targets the same center the renderer updates each frame.
 */
export function attachEclipseShadowToBody(
	material: MeshStandardMaterial,
	selfUniforms?: EclipseSelfUniforms
): EclipseSelfUniforms {
	const self: EclipseSelfUniforms = selfUniforms ?? {
		uEclipseSelfPos: { value: new Vector3() }
	};
	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
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
				#define ECLIPSE_MAX_OCCLUDERS ${MAX_OCCLUDERS}
				uniform vec3 uSunDir;
				uniform float uSunAngularRadius;
				uniform int uOccluderCount;
				uniform vec4 uOccluders[ECLIPSE_MAX_OCCLUDERS];
				uniform vec3 uEclipseSelfPos;
				varying vec3 vEclipseWorldPos;

				// Closed-form Sun-disc obscuration. Two regimes.
				// Mirrored on the CPU by evaluateEclipseFactor above;
				// keep both in sync (eclipse-shadow.test.ts is the contract).
				//
				//  (1) Comparable angular sizes (e.g. solar eclipse on Earth:
				//      aSun ≈ aMoon): use the standard two-circle intersection
				//      (lens-area) formula. Numerically stable in this regime
				//      because no term dominates by orders of magnitude.
				//
				//  (2) Occluder much larger than the Sun (e.g. ISS in LEO sees
				//      Earth at aOc ≈ 1.2 rad against aSun ≈ 0.005 rad — ratio
				//      ~250): the lens formula's b²·acos((c-x)/b) and c·y
				//      terms are each O(b·aSun) but cancel to O(aSun²). Tiny
				//      per-fragment perturbations in sep (down to ~1e-7 rad
				//      from float32 vEclipseWorldPos quantisation) amplify
				//      through that cancellation by b/aSun, producing the
				//      blocky shading the LEO satellite placeholders showed.
				//      Switch to the chord approximation — the occluder limb
				//      is locally straight at sun-disc scale (relative error
				//      O((aSun/sin(aOc))²) ≈ 1e-5 when aOc > 10·aSun) so the
				//      covered fraction is just the area of the Sun disc on
				//      one side of a chord at signed distance (aOc − sep).
				float eclipseFactor() {
					if (uSunAngularRadius <= 0.0) return 1.0;
					float aSun = uSunAngularRadius;
					float result = 1.0;
					for (int i = 0; i < ECLIPSE_MAX_OCCLUDERS; i++) {
						if (i >= uOccluderCount) break;
						vec4 oc = uOccluders[i];
						float r = oc.w;
						if (r <= 0.0) continue;
						// Skip the receiver's own body. Distinct bodies don't
						// overlap, so any occluder closer than its own radius
						// to the receiver center IS the receiver.
						if (length(oc.xyz - uEclipseSelfPos) < r * 0.5) continue;
						vec3 toOc = oc.xyz - vEclipseWorldPos;
						float dOc = length(toOc);
						if (dOc < 1e-5) continue;
						float aOc = asin(min(r / dOc, 1.0));
						float sep = acos(clamp(dot(uSunDir, toOc) / dOc, -1.0, 1.0));

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
	material.needsUpdate = true;
	return self;
}
