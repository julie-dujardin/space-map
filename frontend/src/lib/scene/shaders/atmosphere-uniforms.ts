import { BackSide, FrontSide, Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { getAtmosphereParams, getSunLimbAlpha } from '$lib/fetch/atmospheres';
import { sunIrradianceFactor } from '$lib/scene/lighting';
import {
	applyAtmosphereParams,
	applyAtmosphereQuality,
	ATMOSPHERE_INSIDE_RENDER_ORDER,
	ATMOSPHERE_RENDER_ORDER,
	TERRAIN_DIP_KM,
	type AtmosphereParams
} from '$lib/scene/objects/surface/atmosphere';
import type { AtmosphereQualityConfig } from '$lib/scene/objects/surface/atmosphere-quality';
import { seasonalParamsForJd } from '$lib/scene/objects/surface/atmosphere-season';
import { getEclipseSceneUniforms } from '$lib/scene/objects/surface/eclipse-shadow';
import {
	bindViewTint,
	setSunTransmittanceEnabled,
	sunPathTransmittance,
	syncSunTransmittanceUniforms
} from '$lib/scene/objects/surface/sun-transmittance';
import { setStarLimbAlpha, starViewTintUniforms } from '$lib/scene/objects/sun';
import type { Material, Vector4 } from 'three';

const spinAxis = new Vector3();
const camUp = new Vector3();

/** Photopic luminance weights (Rec. 709). */
const LUM = [0.2126, 0.7152, 0.0722];

/** Column (∫density above h) of a linear-tent absorber band, in km of
 *  surface-density-equivalent path. Total tent area is `w`. */
function tentColumnAboveKm(hKm: number, centerKm: number, widthKm: number): number {
	if (widthKm <= 0) return 0;
	if (hKm <= centerKm - widthKm) return widthKm;
	if (hKm >= centerKm + widthKm) return 0;
	if (hKm <= centerKm) return widthKm - (hKm - (centerKm - widthKm)) ** 2 / (2 * widthKm);
	return (centerKm + widthKm - hKm) ** 2 / (2 * widthKm);
}

/** Zenith transmittance above altitude `hKm`: per-channel Beer-Lambert over
 *  the exponential Rayleigh/Mie columns and the absorber tent, collapsed to a
 *  scalar with photopic weights since `backgroundIntensity` isn't chromatic. */
function zenithTransmittance(p: AtmosphereParams, hKm: number): number {
	const h = Math.max(hKm, 0);
	const rayleigh = p.rayleighScaleHeightKm * Math.exp(-h / p.rayleighScaleHeightKm);
	const mie = p.mieScaleHeightKm * Math.exp(-h / p.mieScaleHeightKm);
	const tent = tentColumnAboveKm(h, p.absorptionCenterKm, p.absorptionWidthKm);
	let t = 0;
	for (let i = 0; i < 3; i++) {
		const tau =
			p.rayleighScatterPerKm[i] * rayleigh +
			(p.mieScatterPerKm[i] + p.mieAbsorptionPerKm[i]) * mie +
			p.absorptionPerKm[i] * tent;
		t += LUM[i] * Math.exp(-tau);
	}
	return t;
}

/** The star map is a long-exposure composite, far hotter than naked-eye — the
 *  look we want in space, but wrong under an air column: the shell's tone-
 *  mapped in-scatter can't swamp it the way a real daytime sky swamps stars.
 *  So under air the map is also compressed toward these floors — a subdued
 *  Milky Way at night, gone in daylight. */
const NIGHT_EXPOSURE_COMP = 0.4;
const DAY_EXPOSURE_COMP = 0.05;

/** Twilight ramp on sin(sun elevation): night below −6°, full day near +12°. */
const TWILIGHT_SIN_START = -0.105;
const TWILIGHT_SIN_SPAN = 0.3;

/** Overhead optical depth at which the exposure compensation reaches full
 *  strength — much thinner columns keep a space-like sky. */
const EXPOSURE_COMP_TAU_SAT = 0.05;

/** Skybox factor under `hKm`-altitude air: zenith extinction × exposure
 *  compensation, faded in with overhead optical depth and steered between
 *  night/day floors by the sun's elevation at the camera. */
export function skyboxDimFactor(p: AtmosphereParams, hKm: number, sinSunElev: number): number {
	const t = zenithTransmittance(p, hKm);
	const thickness = Math.min(1, -Math.log(Math.max(t, 1e-3)) / EXPOSURE_COMP_TAU_SAT);
	const day = Math.min(1, Math.max(0, (sinSunElev - TWILIGHT_SIN_START) / TWILIGHT_SIN_SPAN));
	const floor = NIGHT_EXPOSURE_COMP + (DAY_EXPOSURE_COMP - NIGHT_EXPOSURE_COMP) * day;
	return t * (1 + (floor - 1) * thickness);
}

export interface AtmosphereFrameState {
	/** Any shell has the camera inside it — gates the opaque-depth prepass. */
	insideShell: boolean;
	/** Any shell spans a meaningful part of the view — the perf governor only
	 *  counts slow frames the atmosphere could actually be causing. */
	shellProminent: boolean;
	/** `scene.backgroundIntensity` target: 1 in space; inside a shell, the
	 *  {@link skyboxDimFactor} of the air above the camera. */
	skyboxIntensity: number;
	/** Corona/star-point chroma ({@link applyStarTint}): camera→sun
	 *  transmittance over its luminance — the shell's scalar alpha owns the
	 *  dimming. The disc uses per-fragment VIEW_TINT_GLSL instead. Shared
	 *  scratch — consume within the frame. */
	sunTint: Vector3;
	/** Astronomical-refraction lift of the Sun's visuals for a camera inside a
	 *  shell: rotate the camera→Sun direction by `angleRad` toward `up` (the
	 *  camera's local zenith). Applied by the renderer's sun-proxy pass so the
	 *  proxy re-seat and the lift compose. Shared scratch `up` — consume
	 *  within the frame. */
	sunRefraction: { angleRad: number; up: Vector3 } | null;
}

/** Refraction lift of the Sun at true elevation `e` under a
 *  `refractivity`-strength atmosphere: n−1 times an airmass-like factor,
 *  saturating at the horizon and decaying once the Sun is geometrically below it. */
export function refractionLiftRad(
	n1: number,
	e: number,
	scaleHeightKm: number,
	radiusKm: number
): number {
	const w = Math.sqrt((2 * scaleHeightKm) / radiusKm);
	const qHorizon = Math.sqrt((Math.PI * radiusKm) / (2 * scaleHeightKm));
	if (e >= 0) return n1 / (Math.tan(e) + 1 / qHorizon);
	return n1 * qHorizon * Math.exp(e / w);
}

/** Camera distance bound, in shell radii, for the sun tints. Covers GEO and
 *  the Moon-distance Earth-eclipse ring (~57 R); far past it the band is
 *  sub-pixel and cross-system transits are out of scope. */
const SUN_TINT_MAX_RATIO = 200;

const frameSunTint = new Vector3();
const sunT = new Vector3();
const camRel = new Vector3();
const refractionUp = new Vector3();

/**
 * Fill a shell's private occluder uniforms from the scene-wide set, keeping
 * only bodies whose shadow cone could touch the shell. The shell evaluates
 * this loop per march sample, so an uncapped scan dwarfed the march itself.
 * Conservative: kept occluders render identically, culled ones couldn't have
 * contributed. Requires `updateEclipseUniforms` to have run this frame.
 */
function cullShellOccluders(
	uniforms: Record<string, { value: unknown }>,
	shellCenter: Vector3,
	sunDir: Vector3,
	shellRadius: number
): void {
	const shared = getEclipseSceneUniforms();
	const aSun = shared.uSunAngularRadius.value;
	const src = shared.uOccluders.value;
	const srcCount = shared.uOccluderCount.value;
	const dst = uniforms.uOccluders.value as Vector4[];
	let n = 0;
	for (let i = 0; i < srcCount; i++) {
		const oc = src[i];
		const ox = oc.x - shellCenter.x;
		const oy = oc.y - shellCenter.y;
		const oz = oc.z - shellCenter.z;
		const d2 = ox * ox + oy * oy + oz * oz;
		if (d2 < oc.w * oc.w * 0.25) continue; // the shell's own planet (shader self-skip)
		const t = ox * sunDir.x + oy * sunDir.y + oz * sunDir.z;
		if (t < -(shellRadius + oc.w)) continue; // anti-sunward — casts away from the shell
		const reach = shellRadius + oc.w + aSun * (t + shellRadius) * 1.5;
		if (d2 - t * t > reach * reach) continue; // off the sun axis beyond any penumbra
		dst[n++].copy(oc);
	}
	uniforms.uOccluderCount.value = n;
}

/**
 * Refresh per-frame shell state: sun direction, spin axis, and material side
 * — flips to BackSide when the camera enters the shell so the sky keeps
 * rendering from inside. `realistic` scales sun intensity by inverse-square
 * solar distance (`realisticSunAlways` bodies get half the log-space dimming
 * even without it). `quality.insideView:
 * false` keeps every shell outside-only, so the depth prepass never runs.
 */
export function updateAtmosphereShaders(
	bodyObjects: Map<string, BodyObjects>,
	cameraPosition: Vector3,
	visible: boolean,
	realistic: boolean,
	sunScale: number,
	quality: AtmosphereQualityConfig,
	jd: number
): AtmosphereFrameState {
	const state: AtmosphereFrameState = {
		insideShell: false,
		shellProminent: false,
		skyboxIntensity: 1,
		sunTint: frameSunTint.set(1, 1, 1),
		sunRefraction: null
	};
	setSunTransmittanceEnabled(visible && quality.sunTint);
	const sunBo = bodyObjects.get(SUN_ID);
	setStarLimbAlpha(sunBo?.mesh?.material as Material | undefined, getSunLimbAlpha());
	// Disc chroma re-aims (or stays off) every frame — clear before the loop.
	const sunViewTint = starViewTintUniforms(sunBo?.mesh?.material as Material | undefined);
	if (sunViewTint) sunViewTint.uAtmoTEnable.value = 0;
	let bestViewTintRatio = SUN_TINT_MAX_RATIO;
	const sunPos = sunBo?.body.position;
	if (!sunPos) return state;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		bo.atmosphere.mesh.visible = visible;
		if (!visible) continue;
		applyAtmosphereQuality(bo.atmosphere, quality);
		// Seasonal bodies (Mars) re-derive their params when L_s drifts; off
		// (or reverting) snaps back to the base params. Derived objects are
		// cached, so the identity check keeps this a per-frame no-op.
		const base = getAtmosphereParams(bo.body.data.id);
		if (base?.seasonal) {
			const target = quality.seasonal ? seasonalParamsForJd(base, jd) : base;
			if (bo.atmosphere.params !== target) {
				applyAtmosphereParams(bo.atmosphere, target);
				// The surface/cloud sunset-tint patches march the same columns.
				const prs = bo.atmosphere.material.uniforms.uPlanetRadiusScene.value as number;
				for (const patch of bo.sunTint ?? []) {
					syncSunTransmittanceUniforms(patch, target, prs, bo.atmosphere.planetRadiusKm);
				}
			}
		}
		const [bx, by, bz] = bo.body.position;
		const uniforms = bo.atmosphere.material.uniforms;
		uniforms.uGroundAlbedo.value = quality.groundAlbedo
			? (bo.atmosphere.params.groundAlbedo ?? 0)
			: 0;
		const sunVec = (uniforms.uSunDir.value as Vector3).set(
			sunPos[0] - bx,
			sunPos[1] - by,
			sunPos[2] - bz
		);
		const params = bo.atmosphere.params;
		// realisticSunAlways bodies (Pluto, Triton) get the geometric mean of
		// inverse-square and flat: full realism is near-black at 30–40 AU, flat
		// sun drowns the haze. Global realistic lighting still applies in full.
		const irradiance = realistic
			? sunIrradianceFactor(sunVec.length())
			: params.realisticSunAlways
				? Math.sqrt(sunIrradianceFactor(sunVec.length()))
				: 1;
		uniforms.uSunIntensity.value = params.sunIntensity * irradiance * sunScale;
		sunVec.normalize();
		// applyOrientation puts the pole on mesh-local +Y; the quaternion's spin
		// component is about that same axis, so the phase doesn't matter.
		if (bo.mesh) {
			spinAxis.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
			(uniforms.uSpinAxis.value as Vector3).copy(spinAxis);
		}
		const atmoMesh = bo.atmosphere.mesh;
		const shellRadius = bo.atmosphere.geometryRadiusScene * atmoMesh.scale.x;
		const camDist = cameraPosition.distanceTo(atmoMesh.position);
		// ~11°+ of view — big enough that its fragments dominate frame cost.
		if (shellRadius > camDist * 0.1) state.shellProminent = true;
		if (quality.eclipseShadows)
			cullShellOccluders(uniforms, atmoMesh.position, sunVec, shellRadius);
		const inside = quality.insideView && camDist < shellRadius;
		bo.atmosphere.material.side = inside ? BackSide : FrontSide;
		// With depth test off inside, order alone decides compositing — hoist
		// the sky above rings/other shells/dots so Saturn can't draw over
		// Titan's haze from within it.
		atmoMesh.renderOrder = inside ? ATMOSPHERE_INSIDE_RENDER_ORDER : ATMOSPHERE_RENDER_ORDER;
		// From inside, the visible shell fragment is the far hemisphere — writing
		// its depth would cull the point clouds/trails beyond the night sky, and
		// depth-testing it against the nearer terrain would reject the very
		// fragments that carry the camera→ground aerial perspective. So depth
		// test/write are off; instead the shader samples the opaque-depth prepass
		// (uUseDepth) to stop its march at real terrain.
		bo.atmosphere.material.depthWrite = !inside;
		bo.atmosphere.material.depthTest = !inside;
		bo.atmosphere.material.uniforms.uUseDepth.value = inside ? 1 : 0;
		// Sink the march floor under the datum only from inside, where a camera
		// below it would otherwise have its horizon rays blocked at t≈0. See
		// TERRAIN_DIP_KM — from outside the slab is pure spurious column.
		uniforms.uSurfaceBlockR.value = inside ? 1 - TERRAIN_DIP_KM / bo.atmosphere.planetRadiusKm : 1;
		if (inside) {
			state.insideShell = true;
			const kmPerScene = (bo.atmosphere.planetRadiusKm + params.topAltitudeKm) / shellRadius;
			const altKm = camDist * kmPerScene - bo.atmosphere.planetRadiusKm;
			const sinSunElev = camUp
				.copy(cameraPosition)
				.sub(atmoMesh.position)
				.divideScalar(camDist)
				.dot(sunVec);
			state.skyboxIntensity *= skyboxDimFactor(params, altKm, sinSunElev);
			if (quality.refraction && params.refractivity) {
				// Green-channel refractivity at the camera's altitude; the lift
				// direction is the camera's zenith on this body.
				const n1 =
					params.refractivity[1] * Math.exp(-Math.max(altKm, 0) / params.rayleighScaleHeightKm);
				const lift = refractionLiftRad(
					n1,
					Math.asin(Math.min(1, Math.max(-1, sinSunElev))),
					params.rayleighScaleHeightKm,
					bo.atmosphere.planetRadiusKm
				);
				// Sub-arcsecond lifts are float noise on the disc — skip.
				if (lift > 5e-6) {
					state.sunRefraction = { angleRad: lift, up: refractionUp.copy(camUp) };
				}
			}
		}
		const shellRatio = camDist / shellRadius;
		if (quality.sunTint && shellRatio < SUN_TINT_MAX_RATIO) {
			const planetRadiusScene =
				shellRadius / (1 + params.topAltitudeKm / bo.atmosphere.planetRadiusKm);
			camRel.copy(cameraPosition).sub(atmoMesh.position);
			const shellSpinAxis = uniforms.uSpinAxis.value as Vector3;
			const shellStretch = uniforms.uStretch.value as number;
			if (
				sunPathTransmittance(
					params,
					camRel,
					sunVec,
					planetRadiusScene,
					bo.atmosphere.planetRadiusKm,
					sunT,
					shellSpinAxis,
					shellStretch
				)
			) {
				const lum = LUM[0] * sunT.x + LUM[1] * sunT.y + LUM[2] * sunT.z;
				if (lum > 1e-4) {
					state.sunTint.multiply(sunT.divideScalar(lum));
				}
			}
			// One uniform set → one shell; nearest in shell radii wins.
			if (sunViewTint && shellRatio < bestViewTintRatio) {
				bestViewTintRatio = shellRatio;
				bindViewTint(
					sunViewTint,
					params,
					atmoMesh.position,
					planetRadiusScene,
					bo.atmosphere.planetRadiusKm,
					shellSpinAxis,
					shellStretch
				);
			}
		}
	}
	return state;
}
