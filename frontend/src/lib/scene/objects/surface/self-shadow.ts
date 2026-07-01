/**
 * In-shader terrain self-shadowing + relief shading for displacement-mapped
 * bodies. The vertex `displacementMap` already gives true silhouette and
 * parallax; this adds the two things displacement alone can't:
 *
 *  1. Lit relief — the geometric sphere normal is replaced by the height
 *     field's gradient normal, so shading follows craters instead of treating
 *     the surface as smooth (a normal map we never have to bake).
 *  2. Self-cast shadows — a per-fragment march of the height texture toward the
 *     Sun: if terrain along the light ray rises above the line of sight, the
 *     fragment is occluded. Detail is bounded by texture resolution, not the
 *     coarse mesh tessellation, which is why this beats a geometry shadow map
 *     at planet scale.
 *
 * The `onBeforeCompile` is chained so it stacks with the eclipse/ring-shadow
 * modifiers; the shadow scales direct light only, like the eclipse path.
 */

import { type MeshStandardMaterial, type Texture, Vector2 } from 'three';
import { getEclipseSceneUniforms } from './eclipse-shadow';

/** Self-shadow march sample count. */
const STEPS = 32;
/** Relief slope multiplier; 1.0 = physically true. */
const NORMAL_STRENGTH = 1.0;
/** Gradient half-width in texels; wider masks the 8-bit quantisation terracing
 *  (per-texel step ≈ scale_km/256, worst on big-relief bodies like Vesta). */
const GRADIENT_STENCIL = 2.0;
/** Max relief slope (rise/run): caps quantisation spikes and stops near-terminator
 *  normals tilting sunward (the back-side leak). atan(1.5) ≈ 56°, above real terrain. */
const SLOPE_CLAMP = 1.5;
/** Shadow ray length, in scene units, as a multiple of the peak relief height
 *  (`uScale`). Longer resolves grazing-terminator shadows but costs taps. */
const SHADOW_REACH = 4.0;
/** Penetration (scene units, relative to peak relief) at which a fragment is
 *  fully shadowed — softens the umbra edge. */
const SHADOW_SOFT = 0.04;
/** Macro-terminator gate window (geometric N·L): direct light is full above LIT,
 *  zero below DARK. Suppresses the relief-normal back-side leak on the night side. */
const TERMINATOR_GATE_LIT = 0.02;
const TERMINATOR_GATE_DARK = -0.08;
/** Grazing-angle fade for the self-shadow march (geometric N·L). Below this the
 *  march goes fully horizontal and flags every away-facing slope as occluded,
 *  printing a hard shadow stripe along the terminator; fade it out there and let
 *  the relief-normal Lambert darken that zone softly instead. */
const MARCH_GRAZE_FADE = 0.18;

export interface SelfShadowUniforms {
	uSelfHeightMap: { value: Texture | null };
	/** Scene units per unit texel value: `kmToScene(scale_km)`. Bias is dropped —
	 *  only relative heights matter for slope and occlusion. */
	uSelfScale: { value: number };
	uSelfTexel: { value: Vector2 };
}

/**
 * Attach the self-shadow + relief path. Call once the displacement texture is
 * known; pass it here so the fragment march samples the same height field the
 * vertex stage displaces by. `scaleScene` = `kmToScene(dispMeta.scale_km)`.
 */
export function attachSelfShadowToBody(
	material: MeshStandardMaterial,
	heightMap: Texture,
	scaleScene: number
): SelfShadowUniforms {
	const tex = heightMap.image as { width?: number; height?: number } | undefined;
	const texel = new Vector2(1 / (tex?.width ?? 4096), 1 / (tex?.height ?? 2048));

	// Idempotent: a system reload re-attaches on the persistent material, so
	// update the existing uniforms in place rather than chaining a second
	// onBeforeCompile — re-injecting every declaration is a "redefinition"
	// compile error (and the race made it intermittent).
	const existing = material.userData.selfShadow as SelfShadowUniforms | undefined;
	if (existing) {
		existing.uSelfHeightMap.value = heightMap;
		existing.uSelfScale.value = scaleScene;
		existing.uSelfTexel.value.copy(texel);
		return existing;
	}

	const uniforms: SelfShadowUniforms = {
		uSelfHeightMap: { value: heightMap },
		uSelfScale: { value: scaleScene },
		uSelfTexel: { value: texel }
	};
	material.userData.selfShadow = uniforms;
	const sun = getEclipseSceneUniforms().uSunDir;

	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
		// Unique name: the eclipse shader (chained before us) already declares
		// `uSunDir`; reusing it would be a duplicate uniform → compile error.
		Object.assign(shader.uniforms, uniforms, { uSelfSunDir: sun });

		shader.vertexShader = shader.vertexShader
			.replace(
				'#include <common>',
				`#include <common>
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
					varying vec3 vSelfEastW;
					varying vec3 vSelfNorthW;
					varying float vSelfRadiusW;
					varying float vSelfCosLat;`
			)
			.replace(
				'#include <beginnormal_vertex>',
				`#include <beginnormal_vertex>
				vSelfWorldNormal = normalize(mat3(modelMatrix) * objectNormal);
				vSelfUv = uv;
					// Analytic equirect tangent basis from the base sphere — smooth per
					// fragment, so the relief normal no longer inherits the mesh facets.
					vec3 nObj = normalize(position);
					vec3 ec = cross(vec3(0.0, 1.0, 0.0), nObj);
					float cl = length(ec);
					vec3 eastObj = cl > 1e-5 ? ec / cl : vec3(1.0, 0.0, 0.0);
					vSelfEastW = normalize(mat3(modelMatrix) * eastObj);
					vSelfNorthW = normalize(mat3(modelMatrix) * cross(nObj, eastObj));
					vSelfRadiusW = length(mat3(modelMatrix) * position);
					vSelfCosLat = cl;`
			);

		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>
				#define SELF_STEPS ${STEPS}
				uniform sampler2D uSelfHeightMap;
				uniform float uSelfScale;
				uniform vec2 uSelfTexel;
				uniform vec3 uSelfSunDir;
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
					varying vec3 vSelfEastW;
					varying vec3 vSelfNorthW;
					varying float vSelfRadiusW;
					varying float vSelfCosLat;

				float selfHeight(vec2 uv) {
					return texture2D(uSelfHeightMap, uv).r * uSelfScale;
				}

					// Analytic equirect frame (Tu=∂pos/∂u east, Tv=∂pos/∂v south) from the base
					// sphere. Screen-derivative tangents were piecewise-constant per triangle
					// and tiled the relief normal with mesh facets (diagonal terminator bands).
					// |Tu| = 2πR·cos(lat), |Tv| = πR keeps the true equirect metric.
					void selfTangents(out vec3 Tu, out vec3 Tv) {
						float R = vSelfRadiusW;
						Tu = vSelfEastW * (6.2831853 * R * vSelfCosLat);
						Tv = -vSelfNorthW * (3.14159265 * R);
					}`
			)
			// Replace the geometric normal with the relief gradient normal. Every
			// normalize/divide is guarded: a degenerate frame (poles, where |Tu|→0)
			// falls back to the geometric normal rather than emitting a NaN that
			// renders the body transparent.
			.replace(
				'#include <normal_fragment_maps>',
				`#include <normal_fragment_maps>
				{
					vec3 Tu, Tv;
					selfTangents(Tu, Tv);
					float lenTu = length(Tu);
					float lenTv = length(Tv);
					vec3 Nw = normalize(vSelfWorldNormal);
					if (uSelfScale > 0.0 && lenTu > 1e-12 && lenTv > 1e-12) {
						// Wider-than-one-texel stencil averages out 8-bit terracing.
						vec2 d = uSelfTexel * ${GRADIENT_STENCIL.toFixed(3)};
						float hu = selfHeight(vSelfUv + vec2(d.x, 0.0))
							- selfHeight(vSelfUv - vec2(d.x, 0.0));
						float hv = selfHeight(vSelfUv + vec2(0.0, d.y))
							- selfHeight(vSelfUv - vec2(0.0, d.y));
						// Slope = Δheight / Δworld-distance along each axis.
						float su = ${NORMAL_STRENGTH.toFixed(3)} * hu / (2.0 * d.x * lenTu);
						float sv = ${NORMAL_STRENGTH.toFixed(3)} * hv / (2.0 * d.y * lenTv);
						// |Tu|/|Tv| = 2·cos(lat): fade relief toward the equirect poles,
						// where |Tu|→0 makes the east-west slope blow up into a starburst.
						float poleFade = smoothstep(0.0, 0.12, lenTu / (2.0 * lenTv));
						su = clamp(su * poleFade, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
						sv = clamp(sv * poleFade, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
						vec3 reliefN = cross(Tu / lenTu + Nw * su, Tv / lenTv + Nw * sv);
						float rl = length(reliefN);
						if (rl > 1e-12) {
							reliefN /= rl;
							if (dot(reliefN, Nw) < 0.0) reliefN = -reliefN;
							normal = normalize((viewMatrix * vec4(reliefN, 0.0)).xyz);
						}
					}
				}`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				{
					vec3 Nw = normalize(vSelfWorldNormal);
					vec3 L = normalize(uSelfSunDir);
					float gN = dot(L, Nw);
					// Macro-terminator gate on the GEOMETRIC normal: the relief normal
					// can tilt sunward past the terminator and light the night side
					// (back-side leak). Fading direct light by the geometric N·L keeps
					// the night dark regardless.
					float shadow = smoothstep(${TERMINATOR_GATE_DARK.toFixed(3)}, ${TERMINATOR_GATE_LIT.toFixed(3)}, gN);
					vec3 Tu, Tv;
					selfTangents(Tu, Tv);
					float lenTu = length(Tu);
					float lenTv = length(Tv);
					// Local crater self-shadow, lit hemisphere only (the macro gate owns
					// the night side, which the short march can't see the curvature of).
					if (shadow > 0.0 && uSelfScale > 0.0 && lenTu > 1e-12 && lenTv > 1e-12 && gN > 0.0) {
						float lu = dot(L, Tu / lenTu);
						float lv = dot(L, Tv / lenTv);
						float lh = sqrt(lu * lu + lv * lv);
						if (lh > 1e-4) {
							float ds = ${SHADOW_REACH.toFixed(3)} * uSelfScale / float(SELF_STEPS);
							// World step → uv step via the per-axis metric (|Tu|, |Tv|).
							vec2 stepUv = ds * vec2((lu / lh) / lenTu, (lv / lh) / lenTv);
							float h0 = selfHeight(vSelfUv);
							float tanElev = gN / lh;
							float block = 0.0;
							for (int i = 1; i <= SELF_STEPS; i++) {
								vec2 uv = vSelfUv + float(i) * stepUv;
								float rayH = h0 + float(i) * ds * tanElev;
								block = max(block, selfHeight(uv) - rayH);
							}
							// Fade the march out at grazing angles: a near-horizontal ray
							// occludes every away-facing slope, banding the terminator.
							float marchFade = smoothstep(0.0, ${MARCH_GRAZE_FADE.toFixed(3)}, gN);
							shadow *= 1.0 - marchFade * clamp(block / (${SHADOW_SOFT.toFixed(3)} * uSelfScale), 0.0, 1.0);
						}
					}
					reflectedLight.directDiffuse *= shadow;
					reflectedLight.directSpecular *= shadow;
				}`
			);
	};
	material.needsUpdate = true;
	return uniforms;
}

/** Drop the height-map reference; the material keeps its compiled shader but the
 *  uniform goes inert. Called from the displacement unload path. */
export function detachSelfShadow(uniforms: SelfShadowUniforms | null): void {
	if (!uniforms) return;
	uniforms.uSelfHeightMap.value = null;
	uniforms.uSelfScale.value = 0;
}
