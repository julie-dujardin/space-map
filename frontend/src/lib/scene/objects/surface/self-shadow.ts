/**
 * In-shader terrain self-shadowing + relief shading for displacement-mapped
 * bodies, adding what vertex displacement alone can't:
 *
 *  1. Lit relief — geometric normal replaced by the height field's gradient
 *     normal, so shading follows craters (a normal map we never bake). Up
 *     close the gradient comes from the body's height tiles.
 *  2. Self-cast shadows — per-fragment march of the height texture toward the
 *     Sun. Detail is bounded by texture resolution, not mesh tessellation,
 *     beating a geometry shadow map at planet scale. Up close the march is
 *     over the height tiles too.
 *
 * Chained onto `onBeforeCompile` to stack with eclipse/ring-shadow; scales
 * direct light only, like the eclipse path.
 */

import { type MeshStandardMaterial, type Texture, Vector2, type Vector3 } from 'three';
import { getEclipseSceneUniforms } from './eclipse-shadow';
import { type ReliefTiles, reliefTilesGlsl } from './relief-tiles';
import { reliefShadowSteps } from '$lib/scene/render-tier';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';

/** Self-shadow march sample count. */
const STEPS = 32;
/** Relief slope multiplier; 1.0 = physically true. */
const NORMAL_STRENGTH = 1.0;
/** Gradient half-width in texels; wider masks the 8-bit quantisation terracing
 *  (per-texel step ≈ scale_km/256, worst on big-relief bodies like Vesta). */
const GRADIENT_STENCIL = 2.0;
/** Max relief slope (rise/run): caps quantisation spikes and stops near-terminator
 *  normals tilting sunward. atan(1.5) ≈ 56°, above real terrain. */
const SLOPE_CLAMP = 1.5;
/** Shadow ray length (scene units, × peak relief height). Longer resolves grazing-terminator shadows but costs taps. */
const SHADOW_REACH = 4.0;
/** Penetration depth at which a fragment is fully shadowed — softens the umbra edge. */
const SHADOW_SOFT = 0.04;
/** Macro-terminator gate (geometric N·L): full light above LIT, none below
 *  DARK. Suppresses the relief-normal back-side leak on the night side. */
const TERMINATOR_GATE_LIT = 0.02;
const TERMINATOR_GATE_DARK = -0.08;
/** Below this N·L the march goes near-horizontal and flags every away-facing
 *  slope as occluded, banding the terminator; fade it out and let Lambert darken that zone instead. */
const MARCH_GRAZE_FADE = 0.18;

/** The tiles' own shadow: the Sun in the body's frame, as a way along the
 *  sphere and a height above it. Ground that faces away from the Sun takes
 *  no light from it, and so needs no ray. */
const TILE_LIGHT = /* glsl */ `
						if (byTiles > 0.005 && dot(normal, mat3(viewMatrix) * L) > 0.0) {
							vec3 sunward = normalize(L * mat3(modelMatrix));
							float up = dot(sunward, selfDir);
							vec3 along = sunward - selfDir * up;
							float run = length(along);
							if (run > 1e-4) tileLight = reliefTileShadow(selfDir, selfCharts, along / run, up / run, uSelfSunSize, selfFirst);
							if (tileLight < 0.0) byTiles = 0.0;
						}`;

export interface SelfShadowUniforms {
	uSelfHeightMap: { value: Texture | null };
	/** Scene units per unit texel value: `kmToScene(scale_km)`. Bias is dropped —
	 *  only relative heights matter for slope and occlusion. */
	uSelfScale: { value: number };
	uSelfTexel: { value: Vector2 };
}

/** Attach the self-shadow + relief path, once the displacement texture is known, so the fragment march samples the same height field the vertex stage displaces by.
 *
 *  `scaleScene` is read against the mesh's *world* radius, so a caller whose
 *  mesh carries the scale (the lineup's unit spheres) passes local units times
 *  that scale, and re-calls on every resize. `sunDir` defaults to the scene's
 *  Sun; a stage with a light of its own passes that light's direction. `tiles`
 *  gives the slope and the shadows of the ground up close, where the body has
 *  height tiles. */
export function attachSelfShadowToBody(
	material: MeshStandardMaterial,
	heightMap: Texture,
	scaleScene: number,
	sunDir?: { value: Vector3 },
	tiles?: ReliefTiles
): SelfShadowUniforms {
	const tex = heightMap.image as { width?: number; height?: number } | undefined;
	const texel = new Vector2(1 / (tex?.width ?? 4096), 1 / (tex?.height ?? 2048));

	// Idempotent: update existing uniforms in place rather than chaining a
	// second onBeforeCompile — re-injecting declarations is a "redefinition" error.
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
	const sun = sunDir ?? getEclipseSceneUniforms().uSunDir;

	// The shader with tiles has the samples of its shadow ray as a constant.
	const mod = tiles ? () => `selfShadowTiles${reliefShadowSteps()}` : 'selfShadow';
	chainShaderHook(material, mod, (shader) => {
		const steps = tiles ? reliefShadowSteps() : 0;
		// Unique name: the chained eclipse shader already declares uSunDir.
		Object.assign(shader.uniforms, uniforms, { uSelfSunDir: sun }, tiles?.uniforms);
		// Unique name here too: the eclipse shader declares the scene's own.
		if (tiles) shader.uniforms.uSelfSunSize = getEclipseSceneUniforms().uSunAngularRadius;

		shader.vertexShader = shader.vertexShader
			.replace(
				'#include <common>',
				`#include <common>
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
				varying vec3 vSelfDir;
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
				vSelfDir = position;
					// Analytic equirect tangent basis: smooth per fragment, so the
					// relief normal doesn't inherit mesh facets.
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
				uniform mat3 normalMatrix;
				${tiles ? 'uniform mat4 modelMatrix;\n\t\t\t\tuniform float uSelfSunSize;' : ''}
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
				varying vec3 vSelfDir;
					varying vec3 vSelfEastW;
					varying vec3 vSelfNorthW;
					varying float vSelfRadiusW;
					varying float vSelfCosLat;
				${tiles ? reliefTilesGlsl(steps) : ''}

				float selfHeight(vec2 uv) {
					return texture2D(uSelfHeightMap, uv).r * uSelfScale;
				}

				// Slope of the whole-globe height map at a direction of the
				// body's frame: a vector along the unit sphere that points
				// uphill, as long as the rise over the run.
				vec3 selfMapSlope(vec3 dir) {
					float cosLat = sqrt(max(1.0 - dir.y * dir.y, 0.0));
					if (cosLat < 1e-5) return vec3(0.0);
					vec3 east = vec3(dir.z, 0.0, -dir.x) / cosLat;
					vec3 north = cross(dir, east);
					// Wider-than-one-texel stencil averages out 8-bit terracing, floored
					// at the low tier's texel so a higher-res map keeps the same
					// physical smoothing width instead of flattening the relief.
					vec2 d = max(uSelfTexel, vec2(1.0 / 2048.0, 1.0 / 1024.0)) * ${GRADIENT_STENCIL.toFixed(3)};
					float hu = selfHeight(vSelfUv + vec2(d.x, 0.0))
						- selfHeight(vSelfUv - vec2(d.x, 0.0));
					float hv = selfHeight(vSelfUv + vec2(0.0, d.y))
						- selfHeight(vSelfUv - vec2(0.0, d.y));
					// The map's u runs east over 2π·cos(lat) radii, its v north over π radii.
					float su = hu / (2.0 * d.x * 6.2831853 * cosLat * vSelfRadiusW);
					float sv = hv / (2.0 * d.y * 3.14159265 * vSelfRadiusW);
					// Fade at the poles, where the columns of the map close in and
					// blow the east-west slope up into a starburst.
					float gain = ${NORMAL_STRENGTH.toFixed(3)} * smoothstep(0.0, 0.12, cosLat);
					su = clamp(su * gain, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
					sv = clamp(sv * gain, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
					return east * su + north * sv;
				}

					// Analytic equirect frame for the shadow march: Tu=∂pos/∂u runs east and
					// Tv=∂pos/∂v north, as the map's v does. |Tu|=2πR·cos(lat), |Tv|=πR.
					void selfTangents(out vec3 Tu, out vec3 Tv) {
						float R = vSelfRadiusW;
						Tu = vSelfEastW * (6.2831853 * R * vSelfCosLat);
						Tv = vSelfNorthW * (3.14159265 * R);
					}

				// Part of the Sun's light that the ground of the whole-globe map
				// lets through, for a Sun towards L that is gN above the sphere.
				float selfMapLight(vec3 L, float gN) {
					vec3 Tu, Tv;
					selfTangents(Tu, Tv);
					float lenTu = length(Tu);
					float lenTv = length(Tv);
					if (lenTu <= 1e-12 || lenTv <= 1e-12) return 1.0;
					float lu = dot(L, Tu / lenTu);
					float lv = dot(L, Tv / lenTv);
					float lh = sqrt(lu * lu + lv * lv);
					if (lh <= 1e-4) return 1.0;
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
					return 1.0 - marchFade * clamp(block / (${SHADOW_SOFT.toFixed(3)} * uSelfScale), 0.0, 1.0);
				}`
			)
			// Replace the geometric normal with the one of the ground's slope: from
			// the height tiles where they cover the fragment, from the whole-globe
			// map elsewhere.
			.replace(
				'#include <normal_fragment_maps>',
				`#include <normal_fragment_maps>
				vec3 selfDir = normalize(vSelfDir);
				// The part of the fragment that the tiles answer for.
				float selfCovered = 0.0;
				${tiles ? 'TileCharts selfCharts = tileCharts(selfDir);\n\t\t\t\tint selfFirst = -1;' : ''}
				{
					vec3 slope = vec3(0.0);
					${tiles ? 'slope = reliefTileSlope(selfDir, selfCharts, selfCovered, selfFirst);' : ''}
					if (selfCovered < 0.995 && uSelfScale > 0.0) slope += (1.0 - selfCovered) * selfMapSlope(selfDir);
					float steep = length(slope);
					if (steep > ${SLOPE_CLAMP.toFixed(3)}) slope *= ${SLOPE_CLAMP.toFixed(3)} / steep;
					normal = normalize(normalMatrix * (selfDir - slope));
				}`
			)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				{
					vec3 Nw = normalize(vSelfWorldNormal);
					vec3 L = normalize(uSelfSunDir);
					float gN = dot(L, Nw);
					// Gate on the GEOMETRIC normal: the relief normal can tilt sunward
					// past the terminator and light the night side. Fading direct light
					// by geometric N·L keeps the night dark regardless.
					float shadow = smoothstep(${TERMINATOR_GATE_DARK.toFixed(3)}, ${TERMINATOR_GATE_LIT.toFixed(3)}, gN);
					// Local crater self-shadow, lit hemisphere only — the macro gate owns
					// the night side; the short march can't see that curvature.
					if (shadow > 0.0 && gN > 0.0) {
						// The part of the fragment whose shadow the tiles cast.
						float byTiles = ${steps > 0 ? 'selfCovered' : '0.0'};
						float tileLight = 1.0;
						${steps > 0 ? TILE_LIGHT : ''}
						float mapLight = 1.0;
						if (byTiles < 0.995 && uSelfScale > 0.0) mapLight = selfMapLight(L, gN);
						shadow *= mix(mapLight, tileLight, byTiles);
					}
					reflectedLight.directDiffuse *= shadow;
					reflectedLight.directSpecular *= shadow;
				}`
			);
	});
	return uniforms;
}

/** Drop the height-map reference; the material keeps its compiled shader but the
 *  uniform goes inert. Called from the displacement unload path. */
export function detachSelfShadow(uniforms: SelfShadowUniforms | null): void {
	if (!uniforms) return;
	uniforms.uSelfHeightMap.value = null;
	uniforms.uSelfScale.value = 0;
}
