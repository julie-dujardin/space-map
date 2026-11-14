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

import {
	type MeshStandardMaterial,
	type Texture,
	UnsignedByteType,
	Vector2,
	type Vector3
} from 'three';
import { getEclipseSceneUniforms } from './eclipse-shadow';
import {
	REFINE_STEPS,
	type ReliefTiles,
	STEEPEST,
	SUN_DISC_GLSL,
	reliefTilesGlsl
} from './relief-tiles';
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
/** Gate on the geometric N·L: full light above LIT, none below DARK. The
 *  relief normal can face the Sun far past the terminator, where the
 *  shadow ray is too short to see the curve of the body. */
const TERMINATOR_GATE_LIT = 0.02;
const TERMINATOR_GATE_DARK = -0.08;
/** Least gate value that gets a shadow ray: below it the ray's result does not show. */
const GATE_MIN = 0.005;

/** The tiles' own shadow: the Sun in the body's frame, as a way along the
 *  sphere and a height above it. Ground that faces away from the Sun takes
 *  no light from it, and so needs no ray. */
const TILE_LIGHT = /* glsl */ `
						if (byTiles > 0.005 && dot(normal, mat3(viewMatrix) * L) > 0.0) {
							vec3 sunward = normalize(L * mat3(modelMatrix));
							float up = dot(sunward, selfDir);
							vec3 along = sunward - selfDir * up;
							float run = length(along);
							if (run > 1e-4) tileLight = reliefTileShadow(selfDir, selfMap, selfCap, selfSide, along / run, up / run, uSelfSunSize, selfFirst);
							if (tileLight < 0.0) byTiles = 0.0;
						}`;

export interface SelfShadowUniforms {
	uSelfHeightMap: { value: Texture | null };
	/** Scene units per unit texel value: `kmToScene(scale_km)`. Bias is dropped —
	 *  only relative heights matter for slope and occlusion. */
	uSelfScale: { value: number };
	uSelfTexel: { value: Vector2 };
	/** One step of the map's coding, in texel value. */
	uSelfQuantum: { value: number };
}

/** One step of the coding of `heightMap`, in texel value: a tier's byte, or
 *  the 16-bit step that the pyramid's map records. */
function quantumOf(heightMap: Texture): number {
	const step = heightMap.userData.heightStep as number | undefined;
	return step ?? (heightMap.type === UnsignedByteType ? 1 / 255 : 0);
}

/** Attach the self-shadow + relief path, once the displacement texture is known, so the fragment march samples the same height field the vertex stage displaces by.
 *
 *  `scaleScene` is read against the mesh's *world* radius, so a caller whose
 *  mesh carries the scale (the lineup's unit spheres) passes local units times
 *  that scale, and re-calls on every resize. `sunDir` defaults to the scene's
 *  Sun; a stage with a light of its own passes that light's direction, and
 *  its shadows take the least edge. `tiles`
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
		existing.uSelfQuantum.value = quantumOf(heightMap);
		return existing;
	}

	const uniforms: SelfShadowUniforms = {
		uSelfHeightMap: { value: heightMap },
		uSelfScale: { value: scaleScene },
		uSelfTexel: { value: texel },
		uSelfQuantum: { value: quantumOf(heightMap) }
	};
	material.userData.selfShadow = uniforms;
	const sun = sunDir ?? getEclipseSceneUniforms().uSunDir;
	const sunSize = sunDir ? { value: 0 } : getEclipseSceneUniforms().uSunAngularRadius;

	// The shader with tiles has the samples of its shadow ray as a constant.
	const mod = tiles ? () => `selfShadowTiles${reliefShadowSteps()}` : 'selfShadow';
	chainShaderHook(material, mod, (shader) => {
		const steps = tiles ? reliefShadowSteps() : 0;
		// Unique name: the chained eclipse shader already declares uSunDir.
		Object.assign(shader.uniforms, uniforms, { uSelfSunDir: sun }, tiles?.uniforms);
		shader.uniforms.uSelfSunSize = sunSize;

		shader.vertexShader = shader.vertexShader
			.replace(
				'#include <common>',
				`#include <common>
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
				varying vec3 vSelfDir;
				varying float vSelfRadiusW;
				${tiles ? 'varying vec3 vReliefOff;\n\t\t\t\tuniform vec3 uReliefAnchor;' : ''}`
			)
			.replace(
				'#include <beginnormal_vertex>',
				`#include <beginnormal_vertex>
				vSelfWorldNormal = normalize(mat3(modelMatrix) * objectNormal);
				vSelfUv = uv;
				vSelfDir = position;
				${tiles ? 'vReliefOff = position - uReliefAnchor;' : ''}
				vSelfRadiusW = length(mat3(modelMatrix) * position);`
			);

		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>
				#define SELF_STEPS ${STEPS}
				uniform sampler2D uSelfHeightMap;
				uniform float uSelfScale;
				uniform vec2 uSelfTexel;
				uniform float uSelfQuantum;
				uniform vec3 uSelfSunDir;
				uniform float uSelfSunSize;
				uniform mat3 normalMatrix;
				uniform mat4 modelMatrix;
				varying vec3 vSelfWorldNormal;
				varying vec2 vSelfUv;
				varying vec3 vSelfDir;
				varying float vSelfRadiusW;
				${SUN_DISC_GLSL}
				${tiles ? reliefTilesGlsl(steps) : ''}

				// Where the unit direction p of the body's frame is on the map.
				vec2 selfUvOf(vec3 p) {
					return vec2(fract(atan(p.z, -p.x) / 6.2831853), 1.0 - acos(clamp(p.y, -1.0, 1.0)) / 3.14159265);
				}

				// Height of the map at uv, at mip lod. A loop with a break has no
				// derivatives of its own, so the mip comes from outside it.
				float selfHeightUv(vec2 uv, float lod) {
					return textureLod(uSelfHeightMap, uv, lod).r * uSelfScale;
				}

				float selfHeightAt(vec3 p, float lod) {
					return selfHeightUv(selfUvOf(p), lod);
				}

				// Mip of the fragment's footprint on the ground, for the fragment at
				// dir whose vSelfUv changes by gx and gy over a screen pixel. Near a
				// pole the map's columns close in, and a mip of the footprint on the
				// map would blur along them.
				float selfGroundLod(vec3 dir, vec2 gx, vec2 gy) {
					// The map's u runs east over 2π·cos(lat) radians, its v north over π.
					vec2 scale = vec2(6.2831853 * length(dir.xz), 3.14159265);
					float foot = max(length(gx * scale), length(gy * scale));
					return log2(max(foot / (3.14159265 * uSelfTexel.y), 1.0));
				}

				// A texel of the map in uv, floored at the low tier's, so that a finer
				// map keeps the same smoothing width on the ground.
				vec2 selfTexel() {
					return max(uSelfTexel, vec2(1.0 / 2048.0, 1.0 / 1024.0));
				}

				// Slope of the whole-globe height map at a direction of the
				// body's frame: a vector along the unit sphere that points
				// uphill, as long as the rise over the run, read at mip lod.
				//
				// The samples are a step away on the ground, not on the map: near
				// a pole the map's columns close in, and a step along them would
				// cover no ground.
				vec3 selfMapSlope(vec3 dir, float lod) {
					float cosLat = length(dir.xz);
					vec3 east = cosLat > 1e-5 ? vec3(dir.z, 0.0, -dir.x) / cosLat : vec3(1.0, 0.0, 0.0);
					vec3 north = cross(dir, east);
					// Wider than a texel to average out 8-bit terracing.
					float arc = selfTexel().y * ${GRADIENT_STENCIL.toFixed(3)} * 3.14159265;
					float c = cos(arc);
					float s = sin(arc);
					float hu = selfHeightAt(dir * c + east * s, lod) - selfHeightAt(dir * c - east * s, lod);
					float hv = selfHeightAt(dir * c + north * s, lod) - selfHeightAt(dir * c - north * s, lod);
					float run = 2.0 * arc * vSelfRadiusW;
					float su = clamp(hu / run * ${NORMAL_STRENGTH.toFixed(3)}, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
					float sv = clamp(hv / run * ${NORMAL_STRENGTH.toFixed(3)}, -${SLOPE_CLAMP.toFixed(3)}, ${SLOPE_CLAMP.toFixed(3)});
					return east * su + north * sv;
				}

				// Where the ray is on the map 's' along it, for a fragment at dir that
				// looks along 'along'. Near a pole the ray is the great circle itself:
				// a line of one bearing winds off it there. Elsewhere a curve on the
				// map to second order holds it at a fraction of the cost.
				vec2 selfRayUv(float s, bool polar, vec3 dir, vec3 along, vec2 uvPer, vec2 uvBend) {
					if (polar) {
						float a = s / vSelfRadiusW;
						return selfUvOf(dir * cos(a) + along * sin(a));
					}
					vec2 uv = vSelfUv + s * uvPer + (s * s) * uvBend;
					return vec2(fract(uv.x), uv.y);
				}

				// Part of the Sun's disc that the ground of the whole-globe map
				// leaves in sight, for a Sun towards L, read at mip lod.
				float selfMapLight(vec3 L, float lod) {
					vec3 dir = normalize(vSelfDir);
					float cosLat = length(dir.xz);
					if (cosLat < 1e-5) return 1.0;
					vec3 sunward = normalize(L * mat3(modelMatrix));
					float up = dot(sunward, dir);
					vec3 along = sunward - dir * up;
					float run = length(along);
					if (run < 1e-4) return 1.0;
					along /= run;
					float tanElev = up / run;
					vec3 east = vec3(dir.z, 0.0, -dir.x) / cosLat;
					float sinA = dot(along, east);
					float cosA = dot(along, cross(dir, east));
					float R = vSelfRadiusW;
					// The map's u runs east over 2π·cos(lat) radii, its v north over π radii.
					vec2 uvPer = vec2(sinA / (6.2831853 * cosLat), cosA / 3.14159265) / R;
					float tanLat = dir.y / cosLat;
					bool polar = cosLat < 0.5;
					vec2 uvBend = vec2(sinA * cosA * tanLat / (6.2831853 * cosLat), -0.5 * sinA * sinA * tanLat / 3.14159265) / (R * R);
					// The length of the ray over one texel. Within it the samples read
					// the fragment's own slope, which is the normal's to light.
					vec2 texel = selfTexel();
					float pixel = 1.0 / max(abs(uvPer.x) / texel.x, abs(uvPer.y) / texel.y);
					float reach = ${SHADOW_REACH.toFixed(3)} * uSelfScale;
					if (reach <= pixel) return 1.0;
					float ds = (reach - pixel) / float(SELF_STEPS);
					float h0 = selfHeightUv(vSelfUv, lod);
					float bend = 0.5 / R;
					// The edge is as soft as the Sun's disc, widened by a step of the
					// map's coding at that distance.
					float disc = sunDiscRise(uSelfSunSize, tanElev);
					float coding = uSelfQuantum * uSelfScale;
					float stands = -1e9;
					float worst = 0.0;
					for (int i = 1; i <= SELF_STEPS; i++) {
						float s = pixel + float(i) * ds;
						// The sphere falls away under the ray by s² / 2R.
						float rise = (selfHeightUv(selfRayUv(s, polar, dir, along, uvPer, uvBend), lod) - h0) / s - s * bend - tanElev;
						float x = rise / (disc + coding / s);
						if (x > stands) {
							stands = x;
							worst = s;
							if (stands >= 1.0) break;
						}
					}
					// The crest that hides the most lies between two samples. Look for it
					// around the best one, each time at half the distance, as the tiles do.
					float around = ds;
					if (stands < 1.0 && stands + ${(STEEPEST * 0.5).toFixed(3)} * ds / worst / disc > -1.0) {
						for (int k = 0; k < ${REFINE_STEPS}; k++) {
							around *= 0.5;
							float centre = worst;
							for (int e = 0; e < 2; e++) {
								float s = centre + (e == 0 ? -around : around);
								if (s <= pixel) continue;
								float rise = (selfHeightUv(selfRayUv(s, polar, dir, along, uvPer, uvBend), lod) - h0) / s - s * bend - tanElev;
								float x = rise / (disc + coding / s);
								if (x > stands) {
									stands = x;
									worst = s;
								}
							}
						}
					}
					return sunDiscLight(stands);
				}`
			)
			// Replace the geometric normal with the one of the ground's slope: from
			// the height tiles where they cover the fragment, from the whole-globe
			// map elsewhere.
			.replace(
				'#include <normal_fragment_maps>',
				`#include <normal_fragment_maps>
				vec3 selfDir = normalize(vSelfDir);
				float selfLod = selfGroundLod(selfDir, dFdx(vSelfUv), dFdy(vSelfUv));
				// The part of the fragment that the tiles answer for.
				float selfCovered = 0.0;
				${tiles ? 'mat3x2 selfMap;\n\t\t\t\tmat3x2 selfCap;\n\t\t\t\tfloat selfSide;\n\t\t\t\ttileChartsFrom(uReliefAnchor, vReliefOff, selfMap, selfCap, selfSide);\n\t\t\t\tint selfFirst = -1;' : ''}
				{
					vec3 slope = vec3(0.0);
					${tiles ? 'slope = reliefTileSlope(selfDir, selfMap, selfCap, selfSide, selfCovered, selfFirst);' : ''}
					if (selfCovered < 0.995 && uSelfScale > 0.0) slope += (1.0 - selfCovered) * selfMapSlope(selfDir, selfLod);
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
					float shadow = smoothstep(${TERMINATOR_GATE_DARK.toFixed(3)}, ${TERMINATOR_GATE_LIT.toFixed(3)}, gN);
					// Past the terminator the ground is in its own shadow, save where it stands into the Sun.
					if (shadow > ${GATE_MIN.toFixed(3)}) {
						// The part of the fragment whose shadow the tiles cast.
						float byTiles = ${steps > 0 ? 'selfCovered' : '0.0'};
						float tileLight = 1.0;
						${steps > 0 ? TILE_LIGHT : ''}
						float mapLight = 1.0;
						if (byTiles < 0.995 && uSelfScale > 0.0) mapLight = selfMapLight(L, selfLod);
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
