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

/** Scene-wide eclipse uniforms — a single instance shared by every body's
 *  fragment shader, mutated in place by the renderer once per frame. */
export interface EclipseSceneUniforms {
	/** Sun position in focus-relative world coords (matches the receiver's
	 *  `vEclipseWorldPos`). */
	uSunPos: { value: Vector3 };
	/** Sun radius in scene units. 0 disables the eclipse factor entirely. */
	uSunRadiusScene: { value: number };
	/** Number of populated entries in `uOccluders`. */
	uOccluderCount: { value: number };
	/** Pre-allocated occluder slots: `.xyz` = focus-relative center,
	 *  `.w` = scene-unit radius. Renderer mutates the first
	 *  `uOccluderCount` entries in place. */
	uOccluders: { value: Vector4[] };
}

const SHARED: EclipseSceneUniforms = {
	uSunPos: { value: new Vector3() },
	uSunRadiusScene: { value: 0 },
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
 * Inject the analytical sun-disc occlusion path into a
 * {@link MeshStandardMaterial}. Chains the existing `onBeforeCompile` so
 * other shader modifiers (e.g. `attachRingShadowToPlanet`) can stack on
 * top — Saturn ends up running both this and the ring-cast factor.
 *
 * The shader edits land after `<lights_fragment_end>`, so they scale only
 * the resolved direct light contribution. Indirect (ambient/env) light is
 * left alone — the umbra stays softly lit by ambient light, matching real
 * eclipses where the lunar/Earth umbra never goes pitch black.
 */
export function attachEclipseShadowToBody(material: MeshStandardMaterial): EclipseSelfUniforms {
	const self: EclipseSelfUniforms = {
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
				uniform vec3 uSunPos;
				uniform float uSunRadiusScene;
				uniform int uOccluderCount;
				uniform vec4 uOccluders[ECLIPSE_MAX_OCCLUDERS];
				uniform vec3 uEclipseSelfPos;
				varying vec3 vEclipseWorldPos;

				// Closed-form Sun-disc obscuration: the Sun and each occluder are
				// modelled as discs at their respective angular radii from the
				// receiver fragment. Returns 1.0 (lit) down to 0.0 (umbra) by
				// summing the lens-shaped intersection areas of each occluder
				// disc with the Sun disc, normalised by Sun-disc area. Multiple
				// occluders compose multiplicatively — close enough when their
				// silhouettes don't overlap, which is the common case.
				float eclipseFactor() {
					if (uSunRadiusScene <= 0.0) return 1.0;
					vec3 P = vEclipseWorldPos;
					vec3 toSun = uSunPos - P;
					float dSun = length(toSun);
					if (dSun < 1e-5) return 1.0;
					float aSun = asin(min(uSunRadiusScene / dSun, 1.0));
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
						vec3 toOc = oc.xyz - P;
						float dOc = length(toOc);
						if (dOc < 1e-5) continue;
						float aOc = asin(min(r / dOc, 1.0));
						float sep = acos(clamp(dot(toSun, toOc) / (dSun * dOc), -1.0, 1.0));
						if (sep >= aSun + aOc) continue;                  // no overlap
						if (sep + aSun <= aOc) { result = 0.0; break; }   // total
						if (sep + aOc <= aSun) {                          // annular
							result *= 1.0 - (aOc * aOc) / (aSun * aSun);
							continue;
						}
						// Partial: lens-shaped intersection of two discs.
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
