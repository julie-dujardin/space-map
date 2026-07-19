import { BackSide, FrontSide, Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { sunIrradianceFactor } from '$lib/scene/lighting';
import {
	applyAtmosphereQuality,
	type AtmosphereParams
} from '$lib/scene/objects/surface/atmosphere';
import type { AtmosphereQualityConfig } from '$lib/scene/objects/surface/atmosphere-quality';
import { getEclipseSceneUniforms } from '$lib/scene/objects/surface/eclipse-shadow';
import type { Vector4 } from 'three';

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

/**
 * Zenith transmittance of the atmosphere above altitude `hKm`: the physical
 * fraction of starlight the overhead column lets through. Per-channel Beer-
 * Lambert over the exponential Rayleigh/Mie columns (∫β·e^(−h/H) above h =
 * β·H·e^(−h/H)) and the absorber tent, collapsed to a scalar with photopic
 * luminance weights since `scene.backgroundIntensity` is not chromatic.
 */
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

/**
 * Skybox factor for a camera under `hKm`-altitude air: physical zenith
 * extinction × the exposure compensation above, the latter faded in with the
 * overhead optical depth (so it is continuous at the shell edge) and steered
 * between its night/day floors by the sun's elevation at the camera.
 */
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
}

/**
 * Fill a shell's private occluder uniforms from the scene-wide set, keeping
 * only bodies whose shadow cone could touch the shell: sunward of it, and
 * within (shell + occluder + penumbra-growth) of the shell's sun axis. The
 * scene list is every loaded body (~32), and the shell evaluates its loop per
 * march sample — unculled, that tax dwarfed the march itself on views with no
 * shadow anywhere near. Conservative test: kept occluders render identically,
 * culled ones could never have contributed. Requires updateEclipseUniforms to
 * have run this frame.
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
 * Refresh per-frame shell state: `uSunDir`, the body's spin axis (world-space
 * pole for the shader's oblateness squash), and the material side — the shell
 * flips to BackSide when the camera enters it, so the sky keeps rendering from
 * inside the atmosphere. `realistic` scales the tuned sun intensity by the
 * body's inverse-square distance from the Sun (bodies flagged
 * `realisticSunAlways` get that scaling in every mode); `sunScale` is the
 * debug lighting-tuner multiplier shared with the scene's sun lights.
 * `quality` is the effective tier config — shells compiled against a different
 * config recompile here, and `insideView: false` keeps every shell an
 * outside-only FrontSide mesh (never inside → the depth prepass never runs).
 */
export function updateAtmosphereShaders(
	bodyObjects: Map<string, BodyObjects>,
	cameraPosition: Vector3,
	visible: boolean,
	realistic: boolean,
	sunScale: number,
	quality: AtmosphereQualityConfig
): AtmosphereFrameState {
	const state: AtmosphereFrameState = {
		insideShell: false,
		shellProminent: false,
		skyboxIntensity: 1
	};
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return state;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		bo.atmosphere.mesh.visible = visible;
		if (!visible) continue;
		applyAtmosphereQuality(bo.atmosphere, quality);
		const [bx, by, bz] = bo.body.position;
		const uniforms = bo.atmosphere.material.uniforms;
		const sunVec = (uniforms.uSunDir.value as Vector3).set(
			sunPos[0] - bx,
			sunPos[1] - by,
			sunPos[2] - bz
		);
		const params = bo.atmosphere.params;
		uniforms.uSunIntensity.value =
			params.sunIntensity *
			(realistic || params.realisticSunAlways ? sunIrradianceFactor(sunVec.length()) : 1) *
			sunScale;
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
		// From inside, the visible shell fragment is the far hemisphere — writing
		// its depth would cull the point clouds/trails beyond the night sky, and
		// depth-testing it against the nearer terrain would reject the very
		// fragments that carry the camera→ground aerial perspective. So depth
		// test/write are off; instead the shader samples the opaque-depth prepass
		// (uUseDepth) to stop its march at real terrain.
		bo.atmosphere.material.depthWrite = !inside;
		bo.atmosphere.material.depthTest = !inside;
		bo.atmosphere.material.uniforms.uUseDepth.value = inside ? 1 : 0;
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
		}
	}
	return state;
}
