/**
 * Per-channel sun-transmittance tints the scattering shell can't provide: its
 * premultiplied alpha is a luminance scalar, so it dims what lies behind but
 * never colours it, and it can't touch the light striking a surface.
 *
 * - Surface patch: direct light × sun→fragment transmittance (sunset light).
 * - {@link VIEW_TINT_GLSL}: camera→fragment chroma for the sun disc —
 *   per-fragment, because from orbit the disc outsizes the atmosphere band
 *   and only the sliver behind it may redden.
 * - {@link sunPathTransmittance}: CPU ratio for corona/star point.
 *
 * Tints are T/lum(T) ratios, so the shell's alpha keeps sole ownership of
 * dimming. Same columns as the shell, on the unsquashed sphere — oblateness
 * is below what a tint resolves.
 */

import { type Material, type MeshStandardMaterial, Vector3 } from 'three';
import { type AtmosphereParams, TERRAIN_DIP_KM } from './atmosphere';
import { type EclipseSelfUniforms, getEclipseSceneUniforms } from './eclipse-shadow';

/** Kept well under the shell's LIGHT_STEPS — the surface patch runs over
 *  full-screen landed terrain. */
const FRAGMENT_STEPS = 6;
const CPU_STEPS = 16;

/** Scene-wide enable flag (mirrors the atmosphere visibility setting); shared
 *  value ref like the eclipse uniforms, mutated in place each frame. */
const SCENE = { uAtmoTEnable: { value: 1 } };

export function setSunTransmittanceEnabled(on: boolean): void {
	SCENE.uAtmoTEnable.value = on ? 1 : 0;
}

const PARAM_DECLS = `
	uniform vec3 uAtmoTBetaR;        // Rayleigh β, per planet radius, (R,G,B)
	uniform vec3 uAtmoTBetaMExt;     // Mie extinction β, per planet radius
	uniform vec3 uAtmoTBetaA;        // absorber band β, per planet radius
	uniform float uAtmoTRayleighH;
	uniform float uAtmoTMieH;
	uniform float uAtmoTAbsCenter;
	uniform float uAtmoTAbsWidth;
	uniform float uAtmoTTopR;        // shell radius / planet radius
	uniform float uAtmoTBlockR;      // sun-ray block sphere, ~terrain dip below datum
	uniform float uAtmoTBakedComp;
	uniform float uAtmoTRadiusScene;
	uniform float uAtmoTEnable;
	uniform vec3 uAtmoTCenter;       // body centre, scene/world space
`;

const SUN_TINT_GLSL = `
	// Eclipse's uSunDir/uEclipseSelfPos are declared after this chunk's
	// insertion point — same value refs re-bound under own names.
	uniform vec3 uAtmoTSunDir;
	${PARAM_DECLS}

	// Column (∫density above h) of the linear-tent absorber, in radii of
	// surface-density-equivalent path — mirrors tentColumnAboveKm.
	float atmoTTentColumn(float h) {
		if (uAtmoTAbsWidth <= 0.0) return 0.0;
		float lo = uAtmoTAbsCenter - uAtmoTAbsWidth;
		float hi = uAtmoTAbsCenter + uAtmoTAbsWidth;
		if (h <= lo) return uAtmoTAbsWidth;
		if (h >= hi) return 0.0;
		if (h <= uAtmoTAbsCenter)
			return uAtmoTAbsWidth - (h - lo) * (h - lo) / (2.0 * uAtmoTAbsWidth);
		return (hi - h) * (hi - h) / (2.0 * uAtmoTAbsWidth);
	}

	vec3 atmoSunTint(vec3 worldPos) {
		if (uAtmoTEnable < 0.5) return vec3(1.0);
		vec3 p = (worldPos - uAtmoTCenter) / uAtmoTRadiusScene;
		float b = dot(p, uAtmoTSunDir);
		float c = dot(p, p);
		// Sun under the horizon: zero, not huge τ — only clips DEM slopes, the
		// analytic sphere's NdotL is already ≤ 0 there.
		float d = b * b - (c - uAtmoTBlockR * uAtmoTBlockR);
		if (d > 0.0 && -b - sqrt(d) > 0.0) return vec3(0.0);
		d = b * b - (c - uAtmoTTopR * uAtmoTTopR);
		if (d <= 0.0) return vec3(1.0);
		float tFar = -b + sqrt(d);
		if (tFar <= 0.0) return vec3(1.0);
		// Fragment sits inside the shell → the segment starts at the fragment.
		float dt = tFar / ${FRAGMENT_STEPS.toFixed(1)};
		vec3 od = vec3(0.0);
		for (int i = 0; i < ${FRAGMENT_STEPS}; i++) {
			float h = max(length(p + uAtmoTSunDir * (dt * (float(i) + 0.5))) - 1.0, 0.0);
			od += vec3(
				exp(-h / uAtmoTRayleighH),
				exp(-h / uAtmoTMieH),
				max(0.0, 1.0 - abs(h - uAtmoTAbsCenter) / uAtmoTAbsWidth)
			) * dt;
		}
		vec3 tau = uAtmoTBetaR * od.x + uAtmoTBetaMExt * od.y + uAtmoTBetaA * od.z;
		// Only the slant excess over the texture's baked vertical column —
		// noon stays untouched, the terminator reddens.
		float h0 = max(length(p) - 1.0, 0.0);
		vec3 tauVert = uAtmoTBetaR * (uAtmoTRayleighH * exp(-h0 / uAtmoTRayleighH)) +
			uAtmoTBetaMExt * (uAtmoTMieH * exp(-h0 / uAtmoTMieH)) +
			uAtmoTBetaA * atmoTTentColumn(h0);
		return exp(-max(tau - uAtmoTBakedComp * tauVert, vec3(0.0)));
	}
`;

/**
 * Chroma (T/lum(T)) of the air on the camera→`worldPos` ray, multiplied into
 * the fragment colour. The shell over the same pixel dims by the luminance of
 * its own marched transmittance, so the product is true per-channel
 * filtering; rays missing the shell stay neutral, confining the reddening to
 * the band when the disc outsizes it. No baked offset — sky paths carry no
 * texture. Uniforms: {@link ViewTintUniforms}; `cameraPosition` is three's.
 */
export const VIEW_TINT_GLSL = `
	${PARAM_DECLS}

	vec3 atmoViewTint(vec3 worldPos) {
		if (uAtmoTEnable < 0.5) return vec3(1.0);
		vec3 p = (cameraPosition - uAtmoTCenter) / uAtmoTRadiusScene;
		vec3 rd = normalize(worldPos - cameraPosition);
		float b = dot(p, rd);
		float c = dot(p, p);
		float d = b * b - (c - uAtmoTBlockR * uAtmoTBlockR);
		if (d > 0.0 && -b - sqrt(d) > 0.0) return vec3(1.0);
		d = b * b - (c - uAtmoTTopR * uAtmoTTopR);
		if (d <= 0.0) return vec3(1.0);
		float s = sqrt(d);
		float t1 = -b + s;
		if (t1 <= 0.0) return vec3(1.0);
		float t0 = max(-b - s, 0.0);
		float dt = (t1 - t0) / ${FRAGMENT_STEPS.toFixed(1)};
		vec3 od = vec3(0.0);
		for (int i = 0; i < ${FRAGMENT_STEPS}; i++) {
			float h = max(length(p + rd * (t0 + dt * (float(i) + 0.5))) - 1.0, 0.0);
			od += vec3(
				exp(-h / uAtmoTRayleighH),
				exp(-h / uAtmoTMieH),
				max(0.0, 1.0 - abs(h - uAtmoTAbsCenter) / uAtmoTAbsWidth)
			) * dt;
		}
		vec3 t = exp(-(uAtmoTBetaR * od.x + uAtmoTBetaMExt * od.y + uAtmoTBetaA * od.z));
		float lum = dot(t, vec3(0.2126, 0.7152, 0.0722));
		return t / max(lum, 1e-4);
	}
`;

/** Param-driven uniforms shared by both GLSL patches — sync with
 *  {@link syncSunTransmittanceUniforms} (the debug tuner re-syncs live). */
export interface SunTransmittanceParamUniforms {
	uAtmoTBetaR: { value: Vector3 };
	uAtmoTBetaMExt: { value: Vector3 };
	uAtmoTBetaA: { value: Vector3 };
	uAtmoTRayleighH: { value: number };
	uAtmoTMieH: { value: number };
	uAtmoTAbsCenter: { value: number };
	uAtmoTAbsWidth: { value: number };
	uAtmoTTopR: { value: number };
	uAtmoTBlockR: { value: number };
	uAtmoTBakedComp: { value: number };
	uAtmoTRadiusScene: { value: number };
	uAtmoTEnable: { value: number };
}

/** Surface-patch handle: params + the re-bound eclipse sun-dir/centre refs. */
export interface SunTransmittanceUniforms extends SunTransmittanceParamUniforms {
	uAtmoTSunDir: { value: Vector3 };
	uAtmoTCenter: { value: Vector3 };
}

/** View-tint handle: params + an owned centre, re-aimed per frame at whichever
 *  shell sits near the camera ({@link bindViewTint}). */
export interface ViewTintUniforms extends SunTransmittanceParamUniforms {
	uAtmoTCenter: { value: Vector3 };
}

function makeParamUniforms(enable: { value: number }): SunTransmittanceParamUniforms {
	return {
		uAtmoTBetaR: { value: new Vector3() },
		uAtmoTBetaMExt: { value: new Vector3() },
		uAtmoTBetaA: { value: new Vector3() },
		uAtmoTRayleighH: { value: 0 },
		uAtmoTMieH: { value: 0 },
		uAtmoTAbsCenter: { value: 0 },
		uAtmoTAbsWidth: { value: 0 },
		uAtmoTTopR: { value: 0 },
		uAtmoTBlockR: { value: 0 },
		uAtmoTBakedComp: { value: 0 },
		uAtmoTRadiusScene: { value: 0 },
		uAtmoTEnable: enable
	};
}

/** (Re-)derive every param-driven uniform, radius-normalised like the shell. */
export function syncSunTransmittanceUniforms(
	u: SunTransmittanceParamUniforms,
	params: AtmosphereParams,
	planetRadiusScene: number,
	planetRadiusKm: number
): void {
	const toNorm = (perKm: number) => perKm * planetRadiusKm;
	const r = params.rayleighScatterPerKm;
	const ms = params.mieScatterPerKm;
	const ma = params.mieAbsorptionPerKm;
	const ab = params.absorptionPerKm;
	u.uAtmoTBetaR.value.set(toNorm(r[0]), toNorm(r[1]), toNorm(r[2]));
	u.uAtmoTBetaMExt.value.set(toNorm(ms[0] + ma[0]), toNorm(ms[1] + ma[1]), toNorm(ms[2] + ma[2]));
	u.uAtmoTBetaA.value.set(toNorm(ab[0]), toNorm(ab[1]), toNorm(ab[2]));
	u.uAtmoTRayleighH.value = params.rayleighScaleHeightKm / planetRadiusKm;
	u.uAtmoTMieH.value = params.mieScaleHeightKm / planetRadiusKm;
	u.uAtmoTAbsCenter.value = params.absorptionCenterKm / planetRadiusKm;
	u.uAtmoTAbsWidth.value = params.absorptionWidthKm / planetRadiusKm;
	u.uAtmoTTopR.value = 1 + params.topAltitudeKm / planetRadiusKm;
	u.uAtmoTBlockR.value = 1 - TERRAIN_DIP_KM / planetRadiusKm - 0.015;
	u.uAtmoTBakedComp.value = params.bakedCompensation;
	u.uAtmoTRadiusScene.value = planetRadiusScene;
}

/** Make a view-tint uniform set: disabled until {@link bindViewTint} aims it
 *  at a shell (own enable — proximity-driven, not the scene toggle). */
export function makeViewTintUniforms(): ViewTintUniforms {
	return { ...makeParamUniforms({ value: 0 }), uAtmoTCenter: { value: new Vector3() } };
}

/** Aim a view-tint uniform set at one body's shell for this frame. */
export function bindViewTint(
	u: ViewTintUniforms,
	params: AtmosphereParams,
	center: Vector3,
	planetRadiusScene: number,
	planetRadiusKm: number
): void {
	syncSunTransmittanceUniforms(u, params, planetRadiusScene, planetRadiusKm);
	u.uAtmoTCenter.value.copy(center);
	u.uAtmoTEnable.value = 1;
}

/**
 * Filter resolved direct light (diffuse + specular) by the sun→fragment
 * transmittance. Requires `attachEclipseShadowToBody` on the material first —
 * reuses its `vEclipseWorldPos` varying and value refs. Indirect light stays
 * untouched, same rationale as the eclipse patch. Returns the handle for the
 * tuner's live re-syncs; production params are fixed per body.
 */
export function attachSunTransmittanceToBody(
	material: MeshStandardMaterial,
	params: AtmosphereParams,
	planetRadiusScene: number,
	planetRadiusKm: number,
	self: EclipseSelfUniforms
): SunTransmittanceUniforms {
	const uniforms: SunTransmittanceUniforms = {
		...makeParamUniforms(SCENE.uAtmoTEnable),
		uAtmoTSunDir: getEclipseSceneUniforms().uSunDir,
		uAtmoTCenter: self.uEclipseSelfPos
	};
	syncSunTransmittanceUniforms(uniforms, params, planetRadiusScene, planetRadiusKm);
	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
		Object.assign(shader.uniforms, uniforms);
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', `#include <common>\n${SUN_TINT_GLSL}`)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>
				vec3 atmoTint = atmoSunTint(vEclipseWorldPos);
				reflectedLight.directDiffuse *= atmoTint;
				reflectedLight.directSpecular *= atmoTint;`
			);
	};
	material.needsUpdate = true;
	return uniforms;
}

/**
 * View-ray chroma for a chunk-based material (the tuner's sun disc). Custom
 * ShaderMaterials (the production photosphere) embed {@link VIEW_TINT_GLSL}
 * directly instead.
 */
export function attachViewTintToMaterial(material: Material): ViewTintUniforms {
	const uniforms = makeViewTintUniforms();
	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
		Object.assign(shader.uniforms, uniforms);
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vAtmoTWorldPos;')
			.replace(
				'#include <begin_vertex>',
				'#include <begin_vertex>\nvAtmoTWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;'
			);
		shader.fragmentShader = shader.fragmentShader
			.replace(
				'#include <common>',
				`#include <common>\nvarying vec3 vAtmoTWorldPos;\n${VIEW_TINT_GLSL}`
			)
			.replace(
				'#include <color_fragment>',
				'#include <color_fragment>\ndiffuseColor.rgb *= atmoViewTint(vAtmoTWorldPos);'
			);
	};
	material.needsUpdate = true;
	return uniforms;
}

const _p = new Vector3();

/**
 * CPU twin of the fragment march, along the camera→Sun ray. `camRelPos` is
 * camera − body centre in scene units. Writes `out`; false when the ray
 * misses the shell or the body blocks the sun (disc occluded — no tint).
 */
export function sunPathTransmittance(
	params: AtmosphereParams,
	camRelPos: Vector3,
	sunDir: Vector3,
	planetRadiusScene: number,
	planetRadiusKm: number,
	out: Vector3
): boolean {
	const p = _p.copy(camRelPos).divideScalar(planetRadiusScene);
	const topR = 1 + params.topAltitudeKm / planetRadiusKm;
	const blockR = 1 - TERRAIN_DIP_KM / planetRadiusKm - 0.015;
	const b = p.dot(sunDir);
	const c = p.lengthSq();
	let d = b * b - (c - blockR * blockR);
	if (d > 0 && -b - Math.sqrt(d) > 0) return false;
	d = b * b - (c - topR * topR);
	if (d <= 0) return false;
	const s = Math.sqrt(d);
	const tFar = -b + s;
	if (tFar <= 0) return false;
	const tNear = Math.max(-b - s, 0);
	const dt = (tFar - tNear) / CPU_STEPS;
	const dtKm = dt * planetRadiusKm;
	let odR = 0;
	let odM = 0;
	let odA = 0;
	for (let i = 0; i < CPU_STEPS; i++) {
		const t = tNear + dt * (i + 0.5);
		const hKm = Math.max(
			(Math.hypot(p.x + sunDir.x * t, p.y + sunDir.y * t, p.z + sunDir.z * t) - 1) * planetRadiusKm,
			0
		);
		odR += Math.exp(-hKm / params.rayleighScaleHeightKm) * dtKm;
		odM += Math.exp(-hKm / params.mieScaleHeightKm) * dtKm;
		odA +=
			Math.max(0, 1 - Math.abs(hKm - params.absorptionCenterKm) / params.absorptionWidthKm) * dtKm;
	}
	const r = params.rayleighScatterPerKm;
	const ms = params.mieScatterPerKm;
	const ma = params.mieAbsorptionPerKm;
	const ab = params.absorptionPerKm;
	out.set(
		Math.exp(-(r[0] * odR + (ms[0] + ma[0]) * odM + ab[0] * odA)),
		Math.exp(-(r[1] * odR + (ms[1] + ma[1]) * odM + ab[1] * odA)),
		Math.exp(-(r[2] * odR + (ms[2] + ma[2]) * odM + ab[2] * odA))
	);
	return true;
}
